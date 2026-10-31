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
                          poll_timeout=args.poll_timeout)
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

    if args.plot:
        _plot(f, ch1, ch2)
    return 0


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
    sp.add_argument("--plot", action="store_true", help="matplotlib で表示")
    sp.set_defaults(func=cmd_capture)
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
