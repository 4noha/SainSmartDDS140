"""コマンドライン。`python3 -m dds140 ...` で使う。"""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from . import const as C
from .scope import Frame, Scope
from .transport import DeviceNotFound, Transport


def _scope(args) -> Scope:
    t = Transport.open(timeout=args.timeout)
    s = Scope(t, verbose=args.verbose)
    return s


def cmd_info(args) -> int:
    with Transport.open(timeout=args.timeout) as t:
        dev = t.dev
        print(f"{dev.idVendor:04x}:{dev.idProduct:04x}  DDS140 (USB104 / BUUDAI)")
        try:
            print(f"  bus={dev.bus} addr={dev.address} speed={dev.speed}")
        except Exception:
            pass
        for cfg in dev.configurations():
            print(f"  config {cfg.bConfigurationValue}: "
                  f"{cfg.bNumInterfaces} interface(s) maxPower={cfg.bMaxPower * 2}mA")
            for intf in cfg:
                print(f"    interface {intf.bInterfaceNumber} "
                      f"class={intf.bInterfaceClass:#04x}/"
                      f"{intf.bInterfaceSubClass:#04x}/{intf.bInterfaceProtocol:#04x}")
                for ep in intf:
                    import usb.util
                    d = "IN " if usb.util.endpoint_direction(ep.bEndpointAddress) else "OUT"
                    ty = {0: "ctrl", 1: "iso", 2: "bulk", 3: "intr"}[
                        usb.util.endpoint_type(ep.bmAttributes)]
                    print(f"      EP {ep.bEndpointAddress:#04x} {d} {ty:<4} "
                          f"{ep.wMaxPacketSize}B")
        s = Scope(t, verbose=args.verbose)
        print("  自己診断（各コマンドのエコー）:")
        for cmd, val in s.selfcheck().items():
            print(f"    cmd {cmd} -> {val}")
    return 0


def cmd_cal(args) -> int:
    with Transport.open(timeout=args.timeout) as t:
        s = Scope(t, verbose=args.verbose)
        cal = s.read_calibration()
        if args.json:
            print(json.dumps(cal.as_dict(), indent=2, ensure_ascii=False))
        else:
            for idx in sorted(cal.raw):
                print(f"  {idx:2d}  {C.CAL_ITEMS[idx]:16s} = {cal.raw[idx]:3d}"
                      f"   (gain {cal.gain(idx):.4f} V-ish)")
    return 0


def _write_csv(path: str, f: Frame, ch1: bool, ch2: bool) -> None:
    t = f.times()
    v1 = f.ch1_volts() if ch1 else None
    v2 = f.ch2_volts() if ch2 else None
    with open(path, "w") as fh:
        head = ["time_s"]
        if ch1:
            head.append("ch1_v")
        if ch2:
            head.append("ch2_v")
        fh.write(",".join(head) + "\n")
        for i in range(f.samples):
            row = [f"{t[i]:.9g}"]
            if ch1:
                row.append(f"{v1[i]:.6f}")
            if ch2:
                row.append(f"{v2[i]:.6f}")
            fh.write(",".join(row) + "\n")


def _stats(name: str, values) -> None:
    n = len(values)
    if not n:
        return
    mn = min(values)
    mx = max(values)
    avg = sum(values) / n
    vs = sorted(values)
    rms = (sum(v * v for v in values) / n) ** 0.5
    print(f"  {name}: n={n} min={mn:.4f} max={mx:.4f} avg={avg:.4f} "
          f"rms={rms:.4f} pp={mx - mn:.4f} median={vs[n // 2]:.4f}")


def cmd_capture(args) -> int:
    t = Transport.open(timeout=args.timeout)
    s = Scope(t, verbose=args.verbose)
    try:
        s.read_calibration()
        s.configure(rate=args.rate, ch1_range=args.ch1, ch2_range=args.ch2,
                    ac_ch1=args.ac1, ac_ch2=args.ac2)
        total = args.samples * 2      # 1 サンプル = 2 バイト（CH1, CH2）
        frames = []
        for i in range(args.frames):
            f = s.capture(total_bytes=total, timeout=args.timeout,
                          poll_timeout=args.poll_timeout, skip=args.skip)
            frames.append(f)
            if args.verbose:
                print(f"  frame {i}: {f.samples} samples / ch @ {f.rate_hz/1e6:g} MS/s")
        f = frames[-1]
    finally:
        t.close()

    ch1 = not args.only_ch2
    ch2 = not args.only_ch1
    print(f"DDS140: {f.samples} サンプル/ch, {f.rate_hz/1e6:g} MS/s, "
          f"CH1 {f.ch1_range.name}/div, CH2 {f.ch2_range.name}/div")
    if ch1:
        _stats("CH1", f.ch1_volts())
    if ch2:
        _stats("CH2", f.ch2_volts())

    if args.out:
        _write_csv(args.out, f, ch1, ch2)
        print(f"  -> {args.out}")

    if args.raw:
        with open(args.raw, "wb") as fh:
            fh.write(f.raw)
        print(f"  -> {args.raw} (生バイト, 交互配置)")

    if args.svg:
        _write_svg(args.svg, f, ch1, ch2)
        print(f"  -> {args.svg} (SVG)")

    if args.plot:
        _plot(f, ch1, ch2)
    return 0


def _write_svg(path: str, f: Frame, ch1: bool, ch2: bool, width: int = 1000,
               height: int = 400) -> None:
    """依存なしで波形を SVG にする（matplotlib が無い環境用）。"""
    pad = 40
    w = width - pad * 2
    h = height - pad * 2
    series = []
    if ch1:
        series.append(("CH1", "#1f77b4", f.ch1_volts()))
    if ch2:
        series.append(("CH2", "#d62728", f.ch2_volts()))
    if not series:
        return
    lo = min(min(v) for _, _, v in series)
    hi = max(max(v) for _, _, v in series)
    if hi - lo < 1e-12:
        hi, lo = lo + 1.0, lo - 1.0
    span = hi - lo
    n = len(series[0][2])
    step = max(1, n // 2000)

    def x(i):
        return pad + w * i / max(1, n - 1)

    def y(v):
        return pad + h * (hi - v) / span

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}">',
           f'<rect width="{width}" height="{height}" fill="#ffffff"/>']
    for k in range(11):
        gx = pad + w * k / 10
        gy = pad + h * k / 10
        out.append(f'<line x1="{gx:.1f}" y1="{pad}" x2="{gx:.1f}" y2="{pad + h}" '
                   f'stroke="#e6e6e6" stroke-width="1"/>')
        out.append(f'<line x1="{pad}" y1="{gy:.1f}" x2="{pad + w}" y2="{gy:.1f}" '
                   f'stroke="#e6e6e6" stroke-width="1"/>')
    out.append(f'<rect x="{pad}" y="{pad}" width="{w}" height="{h}" fill="none" '
               f'stroke="#888" stroke-width="1"/>')
    for name, color, vals in series:
        pts = " ".join(f"{x(i):.1f},{y(vals[i]):.1f}" for i in range(0, n, step))
        out.append(f'<polyline fill="none" stroke="{color}" stroke-width="1.2" '
                   f'points="{pts}"/>')
    dt = 1.0 / f.rate_hz
    out.append(f'<text x="{pad}" y="{pad - 12}" font-family="monospace" font-size="12">'
               f'DDS140  {n} samples  {f.rate_hz/1e6:g} MS/s  '
               f'{dt*1e6:.4g} us/sample  span {dt*n*1e6:.4g} us</text>')
    out.append(f'<text x="{pad}" y="{height - 12}" font-family="monospace" '
               f'font-size="12">{lo:+.3f} V .. {hi:+.3f} V</text>')
    for k, (name, color, _) in enumerate(series):
        out.append(f'<text x="{pad + 8 + k * 60}" y="{pad + 16}" '
                   f'font-family="monospace" font-size="13" fill="{color}">{name}</text>')
    out.append('</svg>')
    with open(path, "w") as fh:
        fh.write("\n".join(out) + "\n")


def _plot(f: Frame, ch1: bool, ch2: bool) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("  ! matplotlib が無いのでプロットを省略", file=sys.stderr)
        return
    t = [x * 1e6 for x in f.times()]      # µs
    fig, ax = plt.subplots(figsize=(10, 4))
    if ch1:
        ax.plot(t, f.ch1_volts(), label="CH1", linewidth=0.8)
    if ch2:
        ax.plot(t, f.ch2_volts(), label="CH2", linewidth=0.8)
    ax.set_xlabel("time [us]")
    ax.set_ylabel("[V]")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    plt.show()


def cmd_inputcheck(args) -> int:
    """入力に信号が来ているかを、レンジごとの AC 成分で判定する。

    本物の信号はレンジを変えても電圧（AC RMS）が変わらない。
    ADC のノイズやドリフトはレンジ（= ゲイン）に比例して変化する。
    """
    import statistics

    t = Transport.open(timeout=args.timeout)
    s = Scope(t, verbose=args.verbose)
    try:
        s.read_calibration()
        print("レンジごとの AC 成分（100 MS/s, 32k サンプル）")
        print(f"{'range':>7s}  {'CH1 rms':>9s} {'CH1 pp':>8s} "
              f"{'CH2 rms':>9s} {'CH2 pp':>8s}")
        rows = []
        for rng in ("2V", "1V", "500mV", "200mV", "100mV", "50mV"):
            s.configure(rate="100M", ch1_range=rng, ch2_range=rng)
            f = s.capture(total_bytes=65536, poll_timeout=15, skip=64)
            out = []
            for vals in (f.ch1_volts(), f.ch2_volts()):
                m = sum(vals) / len(vals)
                ac = [v - m for v in vals]
                rms = (sum(v * v for v in ac) / len(ac)) ** 0.5
                out.append((rms, max(vals) - min(vals)))
            rows.append((rng, out))
            print(f"{rng:>7s}  {out[0][0]:9.4f} {out[0][1]:8.4f} "
                  f"{out[1][0]:9.4f} {out[1][1]:8.4f}")
        print()
        for ch in (0, 1):
            name = f"CH{ch + 1}"
            rms = [r[1][ch][0] for r in rows]
            big = max(rms)
            small = min(rms)
            if big < 0.005:
                verdict = "信号なし（ノイズレベル）"
            elif big > 0 and (big - small) / big < 0.25:
                verdict = f"信号あり（レンジを変えても AC RMS {big:.3f} V で一定）"
            else:
                verdict = (f"信号は見えない（レンジで AC RMS が {small:.3f}→{big:.3f} V と"
                           " 変わる = ノイズ/ドリフト）")
            print(f"  {name}: {verdict}")
        if args.spectrum:
            print()
            print("CH1 の低周波スペクトル（100 MS/s, 10 ms）")
            f = s.capture(total_bytes=2097152, poll_timeout=15, skip=64)
            v = f.ch1_volts()
            k = 100
            x = [sum(v[i:i + k]) / k for i in range(0, len(v) - k, k)]
            fs = f.rate_hz / k
            n = len(x)
            m = sum(x) / n
            x = [a - m for a in x]

            def goertzel(fr):
                import math
                w = 2 * math.pi * fr / fs
                c = 2 * math.cos(w)
                s1 = s2 = 0.0
                for val in x:
                    s0 = val + c * s1 - s2
                    s2 = s1
                    s1 = s0
                return (s1 * s1 + s2 * s2 - c * s1 * s2) ** 0.5

            peaks = []
            for fr in range(50, 3000, 50):
                peaks.append((goertzel(fr), fr))
            peaks.sort(reverse=True)
            for mag, fr in peaks[:5]:
                print(f"    {fr:5d} Hz  相対 {mag:.1f}")
    finally:
        t.close()
    return 0


def cmd_monitor(args) -> int:
    """ターミナルで数値をライブ表示する（プローブの当たり確認用）。"""
    import time as _time

    from .webui import _freq_estimate

    t = Transport.open(timeout=args.timeout)
    s = Scope(t, verbose=args.verbose)
    try:
        s.read_calibration()
        s.configure(rate=args.rate, ch1_range=args.ch1, ch2_range=args.ch2,
                    ac_ch1=args.ac1, ac_ch2=args.ac2)
        print(f"DDS140 monitor  rate={args.rate} CH1={args.ch1}/div CH2={args.ch2}/div"
              f"  (Ctrl+C で終了)")
        print("   時刻       CH1 rms      pp    周波数  |   CH2 rms      pp    周波数")
        end = _time.monotonic() + args.seconds if args.seconds else None
        while True:
            f = s.capture(total_bytes=int(args.samples) * 2,
                          poll_timeout=15.0, skip=args.skip)
            cells = []
            for vals in (f.ch1_volts(), f.ch2_volts()):
                m = sum(vals) / len(vals)
                ac = [v - m for v in vals]
                rms = (sum(v * v for v in ac) / len(ac)) ** 0.5
                pp = max(vals) - min(vals)
                fr = _freq_estimate(vals, 1.0 / f.rate_hz)
                ftxt = "     -  " if fr is None else f"{fr/1000:8.2f}k"
                cells.append(f"{rms:8.4f} {pp:7.4f} {ftxt}")
            stamp = _time.strftime("%H:%M:%S")
            print(f"  {stamp}  {cells[0]}  | {cells[1]}", flush=True)
            if end and _time.monotonic() > end:
                break
            _time.sleep(max(0.0, args.interval))
    except KeyboardInterrupt:
        pass
    finally:
        t.close()
    return 0


def cmd_record(args) -> int:
    from . import record as R

    if args.capacity:
        print("1 フレームで連続記録できる長さ（実測の上限 40 MB）:")
        print(R.describe_capacity())
        return 0

    t = Transport.open(timeout=args.timeout)
    s = Scope(t, verbose=args.verbose)
    try:
        s.read_calibration()
        s.configure(rate=args.rate, ch1_range=args.ch1, ch2_range=args.ch2,
                    ac_ch1=args.ac1, ac_ch2=args.ac2)
        cfg = {"rate": args.rate, "skip": args.skip}
        rec = R.record(s, out=args.out, seconds=args.seconds, samples=args.samples,
                       frames=args.frames, cfg=cfg)
    finally:
        t.close()
    print(rec.summary())
    if args.csv:
        csv_path = str(rec.path) + ".csv"
        R.to_csv(rec.path, csv_path)
        print(f"  CSV: {csv_path}")
    return 0


def cmd_ui(args) -> int:
    from .webui import serve
    return serve(port=args.port, demo=args.demo, open_browser=not args.no_open)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dds140",
        description="SainSmart DDS140 (USB オシロ) を macOS から操作する",
    )
    p.add_argument("--version", action="version", version=f"dds140 {__version__}")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--timeout", type=int, default=3000, help="USB タイムアウト [ms]")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("info", help="デバイスの descriptor と自己診断")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("cal", help="個体キャリブレーション（cmd 144）を読む")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_cal)

    sp = sub.add_parser("capture", help="1 フレーム取得")
    sp.add_argument("--samples", type=int, default=65536,
                    help="1ch あたりのサンプル数（既定 65536）")
    sp.add_argument("--frames", type=int, default=1, help="取るフレーム数（最後を出力）")
    sp.add_argument("--poll-timeout", type=float, default=15.0,
                    help="取得開始（status 33）を待つ秒数。240k/39k は数秒かかる")
    sp.add_argument("--rate", choices=sorted(C.SAMPLE_RATES), default="100M")
    sp.add_argument("--ch1", choices=sorted(C.CH1_RANGES), default="1V",
                    help="CH1 の V/div（既定 1V）")
    sp.add_argument("--ch2", choices=sorted(C.CH2_RANGES), default="1V")
    sp.add_argument("--ac1", action="store_true", help="CH1 を AC 結合")
    sp.add_argument("--ac2", action="store_true", help="CH2 を AC 結合")
    sp.add_argument("--only-ch1", action="store_true")
    sp.add_argument("--only-ch2", action="store_true")
    sp.add_argument("-o", "--out", help="CSV 出力先")
    sp.add_argument("--raw", help="生バイト出力先（CH1,CH2 交互）")
    sp.add_argument("--skip", type=int, default=0,
                    help="フレーム先頭の捨てサンプル数。実測では先頭 ~10 個が整定で跳ねる")
    sp.add_argument("--svg", help="SVG で波形を書き出す（依存なし）")
    sp.add_argument("--plot", action="store_true",
                    help="matplotlib で表示（入っていれば）")
    sp.set_defaults(func=cmd_capture)

    sp = sub.add_parser("monitor", help="数値をライブ表示（プローブ確認用）")
    sp.add_argument("--rate", choices=sorted(C.SAMPLE_RATES), default="10M")
    sp.add_argument("--ch1", choices=sorted(C.CH1_RANGES), default="200mV")
    sp.add_argument("--ch2", choices=sorted(C.CH2_RANGES), default="200mV")
    sp.add_argument("--ac1", action="store_true")
    sp.add_argument("--ac2", action="store_true")
    sp.add_argument("--samples", type=int, default=8192)
    sp.add_argument("--skip", type=int, default=16)
    sp.add_argument("--interval", type=float, default=0.3)
    sp.add_argument("--seconds", type=float, default=0, help="0 で Ctrl+C まで続ける")
    sp.set_defaults(func=cmd_monitor)

    sp = sub.add_parser("input-check",
                        help="入力に信号が来ているか調べる（レンジごとの AC 成分）")
    sp.add_argument("--spectrum", action="store_true",
                    help="CH1 の低周波スペクトルも出す")
    sp.set_defaults(func=cmd_inputcheck)

    sp = sub.add_parser("record", help="信号を記録してファイルに保存")
    sp.add_argument("--capacity", action="store_true",
                    help="レートごとの 1 フレーム最大長を表示して終了")
    sp.add_argument("--seconds", type=float, default=5.0,
                    help="1 フレームの長さ（秒）。--samples があればそちら優先")
    sp.add_argument("--samples", type=int, help="1ch あたりのサンプル数で指定")
    sp.add_argument("--frames", type=int, default=1, help="フレーム数（間隔が空く）")
    sp.add_argument("--rate", choices=sorted(C.SAMPLE_RATES), default="240k")
    sp.add_argument("--ch1", choices=sorted(C.CH1_RANGES), default="1V")
    sp.add_argument("--ch2", choices=sorted(C.CH2_RANGES), default="1V")
    sp.add_argument("--ac1", action="store_true")
    sp.add_argument("--ac2", action="store_true")
    sp.add_argument("--skip", type=int, default=0,
                    help="先頭の捨てサンプル数（記録では既定 0 = 連続性を保つ）")
    sp.add_argument("-o", "--out", help="出力 .bin（メタは .bin.json）")
    sp.add_argument("--csv", action="store_true", help="CSV も書き出す")
    sp.set_defaults(func=cmd_record)

    sp = sub.add_parser("ui", help="ブラウザ UI を起動（依存なし）")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--demo", action="store_true",
                    help="実機を使わず合成波形で UI を確認する")
    sp.add_argument("--no-open", action="store_true", help="ブラウザを自動で開かない")
    sp.set_defaults(func=cmd_ui)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except DeviceNotFound as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
