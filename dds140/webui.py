"""ブラウザで開くローカル UI（依存なし・標準ライブラリのみ）。

  python3 -m dds140 ui            # 実機を使う
  python3 -m dds140 ui --demo     # 波形は合成（ハード不要で UI を確認）

http://127.0.0.1:8765/ を開く。USB に触るのはワーカースレッド 1 本だけなので、
libusb のスレッド安全性を気にしなくてよい。
"""
from __future__ import annotations

import json
import math
import queue
import random
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import const as C
from . import record as REC
from .scope import Frame, Scope
from .transport import DeviceNotFound, Transport

WEB_DIR = Path(__file__).with_name("web")

DEFAULT_CFG = {
    "rate": "100M",
    "trigger": True,
    "trigger_level": 50,
    "ch1": "1V",
    "ch2": "1V",
    "ac1": False,
    "ac2": False,
    "skip": 16,
    "samples": 16384,
    "run": True,
}

MAX_SAMPLES = 262144
POINTS = 1000          # 1 画面あたりの横方向の点数（min/max 包絡）


# --------------------------------------------------------------------- 波形処理
def _stats(vals: list[float]) -> dict:
    n = len(vals)
    if not n:
        return {}
    mn = min(vals)
    mx = max(vals)
    mean = sum(vals) / n
    rms = math.sqrt(sum(v * v for v in vals) / n)
    return {"min": mn, "max": mx, "mean": mean, "rms": rms, "pp": mx - mn}


def _envelope(vals: list[float], points: int = POINTS) -> list[float]:
    """画面用に間引く。[min, mean, max, min, mean, max, ...] を返す。

    min/max を帯、mean を細い線として描く（ノイズでも波形でも見やすい）。
    """
    n = len(vals)
    if n <= points * 2:
        return vals
    out = []
    step = n / points
    for i in range(points):
        a = int(i * step)
        b = max(a + 1, int((i + 1) * step))
        chunk = vals[a:b]
        out.append(min(chunk))
        out.append(sum(chunk) / len(chunk))
        out.append(max(chunk))
    return out


def _freq_estimate(vals: list[float], dt: float) -> float | None:
    """ヒステリシス付きで立上りエッジ間隔から周波数を出す。

    量子化ノイズやランダムノイズで誤った値を出さないよう、
    周期のばらつきが大きいときは None（= 測定不能）を返す。
    """
    n = len(vals)
    if n < 32:
        return None
    lo = min(vals)
    hi = max(vals)
    swing = hi - lo
    if swing < 1e-3:
        return None
    mid = (hi + lo) / 2.0
    hyst = swing * 0.25
    edges = []
    armed = False
    for i, v in enumerate(vals):
        if not armed:
            if v < mid - hyst:
                armed = True
        elif v > mid + hyst:
            edges.append(i)
            armed = False
    if len(edges) < 3:
        return None
    periods = [edges[k + 1] - edges[k] for k in range(len(edges) - 1)]
    mean_p = sum(periods) / len(periods)
    if mean_p <= 2:
        return None
    var = sum((p - mean_p) ** 2 for p in periods) / len(periods)
    std = math.sqrt(var)
    if std / mean_p > 0.15:        # ノイズっぽい（周期がバラバラ）
        return None
    return 1.0 / (mean_p * dt)


def _nice_ylim(vals: list[float]) -> tuple[float, float]:
    """1〜99 パーセンタイルで表示レンジを決め、1-2-5 の刻みに丸める。

    スパイク数個で waveform が潰れるのを防ぐ（スコープの表示レンジ相当）。
    """
    if not vals:
        return (-1.0, 1.0)
    s = sorted(vals)
    n = len(s)
    lo = s[int(n * 0.01)]
    hi = s[int(n * 0.99)]
    if hi - lo < 1e-6:
        lo -= 0.05
        hi += 0.05
    pad = (hi - lo) * 0.15
    lo -= pad
    hi += pad
    step = 10 ** math.floor(math.log10(max(hi - lo, 1e-9)))
    for m in (1, 2, 5, 10):
        if (hi - lo) / (step * m) <= 5:
            step *= m
            break
    return (math.floor(lo / step) * step, math.ceil(hi / step) * step)


def frame_to_json(f: Frame, seq: int, cfg: dict) -> dict:
    v1 = f.ch1_volts()
    v2 = f.ch2_volts()
    dt = 1.0 / f.rate_hz
    ylim = _nice_ylim(v1 + v2)
    payload = {
        "seq": seq,
        "ylim": list(ylim),
        "time": time.time(),
        "rate": f.rate_hz,
        "dt": dt,
        "samples": f.samples,
        "cfg": cfg,
        "ch1": {
            "envelope": _envelope(v1),
            "stats": _stats(v1),
            "freq": _freq_estimate(v1, dt),
            "range": f.ch1_range.name,
            "zero": f.cal.zero(f.ch1_range.cal_zero),
        },
        "ch2": {
            "envelope": _envelope(v2),
            "stats": _stats(v2),
            "freq": _freq_estimate(v2, dt),
            "range": f.ch2_range.name,
            "zero": f.cal.zero(f.ch2_range.cal_zero),
        },
    }
    return payload


# ------------------------------------------------------------------ 合成波形
class DemoSource:
    """--demo 用。実機が無くても UI を触れるようにする。"""

    def __init__(self):
        self.t = 0.0

    def configure(self, cfg):
        self.cfg = cfg

    def capture(self) -> Frame:
        rate = C.SAMPLE_RATES[self.cfg["rate"]].hz
        n = int(self.cfg["samples"])
        self.t += n / rate
        # 画面に 5〜6 周期くらい見えるようにする（サンプル数に合わせる）
        f1 = rate / max(8.0, n / 5.5)
        f2 = rate / max(8.0, n / 3.0)
        lsb1 = 10 * (164 * 2 / 255) / 255     # 1V/div 相当
        lsb2 = 10 * (160 * 2 / 255) / 255
        raw = bytearray()
        for i in range(n):
            x = i / rate
            a = 0.55 * math.sin(2 * math.pi * f1 * x + self.t * 0.0001) \
                + 0.02 * random.uniform(-1, 1)
            # CH2 は三角波
            ph = (f2 * x) % 1.0
            tri = 4 * abs(ph - 0.5) - 1.0
            b = 0.35 * tri + 0.01 * random.uniform(-1, 1)
            ca = int(round(117 + a / lsb1))
            cb = int(round(120 + b / lsb2))
            raw.append(max(0, min(255, ca)))
            raw.append(max(0, min(255, cb)))
        cal = _demo_cal()
        return Frame(raw=bytes(raw), rate_hz=rate,
                     ch1_range=C.CH1_RANGES[self.cfg["ch1"]],
                     ch2_range=C.CH2_RANGES[self.cfg["ch2"]],
                     cal=cal)


def _demo_cal():
    from .scope import Calibration
    return Calibration(raw={1: 117, 2: 120, 3: 164, 4: 160, 5: 125,
                            6: 174, 7: 167, 8: 122, 9: 125, 10: 144,
                            11: 117, 12: 118, 13: 134,
                            14: 117, 15: 120, 16: 117, 17: 118, 18: 117, 19: 120})


# --------------------------------------------------------------------- worker
class ScopeWorker(threading.Thread):
    def __init__(self, demo: bool = False):
        super().__init__(daemon=True)
        self.demo = demo
        self.cfg = dict(DEFAULT_CFG)
        self.cmds: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        self.frame_json: dict | None = None
        self.last_frame: Frame | None = None
        self.cal_json: dict | None = None
        self.status = {"connected": False, "error": None, "frames": 0, "fps": 0.0,
                       "recording": False, "record_seconds": 0.0,
                       "last_record": None}
        self._stop = threading.Event()
        self._source = DemoSource() if demo else None
        self._transport: Transport | None = None
        self._scope: Scope | None = None
        if self._source is not None:
            self._source.cfg = self.cfg
        self._keep_last: dict | None = None

    # ---- UI からの指示
    def set_config(self, patch: dict) -> None:
        self.cmds.put(("config", patch))

    def resync(self) -> None:
        self.cmds.put(("resync", None))

    def start_record(self, seconds: float) -> None:
        self.cmds.put(("record", float(seconds)))

    def stop(self) -> None:
        self._stop.set()
        self.cmds.put(("stop", None))

    def snapshot(self) -> tuple[dict | None, dict, dict | None]:
        with self.lock:
            return self.frame_json, dict(self.status), self.cal_json

    def last(self) -> Frame | None:
        with self.lock:
            return self.last_frame

    # ---- 本体
    def run(self) -> None:
        transport = None
        scope = None
        last = time.monotonic()
        count = 0
        while not self._stop.is_set():
            try:
                while True:
                    kind, payload = self.cmds.get_nowait()
                    if kind == "config":
                        self.cfg.update(payload)
                    elif kind == "resync":
                        if scope:
                            scope.configure(**self._scope_kwargs())
                    elif kind == "record":
                        self._pending_record = payload
                    elif kind == "stop":
                        raise SystemExit
            except queue.Empty:
                pass
            except SystemExit:
                break

            if getattr(self, "_pending_record", None):
                secs = self._pending_record
                self._pending_record = None
                self._do_record(secs)
                continue

            if not self.cfg["run"] and self._keep_last is not None:
                time.sleep(0.05)
                continue

            try:
                if self.demo:
                    frame = self._source.capture()
                else:
                    if scope is None:
                        transport = Transport.open(timeout=3000)
                        scope = Scope(transport)
                        scope.read_calibration()
                        with self.lock:
                            self.cal_json = scope.cal.as_dict()
                        scope.configure(**self._scope_kwargs())
                        self._transport, self._scope = transport, scope
                        self._set_status(connected=True, error=None)
                    else:
                        self._apply_pending(scope)
                    frame = scope.capture(
                        total_bytes=int(self.cfg["samples"]) * 2,
                        poll_timeout=20.0,
                        skip=int(self.cfg["skip"]),
                    )
                    if self.cfg.get("trigger"):
                        idx = frame.find_trigger(
                            channel=1,
                            level=max(0.0, min(1.0, self.cfg.get("trigger_level", 50) / 100.0)))
                        if idx:
                            frame = frame.rotate(idx)
            except Exception as e:      # 実機が抜けた等
                msg = f"{type(e).__name__}: {e}"
                self._set_status(connected=False, error=msg)
                if transport is not None:
                    try:
                        transport.close()
                    except Exception:
                        pass
                transport = scope = None
                self._transport = self._scope = None
                time.sleep(1.5)
                continue

            with self.lock:
                count += 1
                now = time.monotonic()
                if now - last >= 1.0:
                    fps = count / (now - last)
                    count = 0
                    last = now
                else:
                    fps = self.status.get("fps", 0.0)
                seq = self.status.get("frames", 0) + 1
                payload = frame_to_json(frame, seq, dict(self.cfg))
                self.frame_json = payload
                self.last_frame = frame
                self._keep_last = payload
                self.status.update(connected=True, error=None, frames=seq, fps=fps)
            time.sleep(0.01)

        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass

    def _do_record(self, seconds: float) -> None:
        """記録する。ライブ表示の Transport があればそれを使い回す（二重 claim を避ける）。"""
        with self.lock:
            self.status.update(recording=True, record_seconds=seconds)
        own_transport = None
        try:
            if self.demo:
                time.sleep(min(seconds, 1.0))
                path = Path("captures") / f"demo-{int(time.time())}.bin"
                path.parent.mkdir(parents=True, exist_ok=True)
                f = self._source.capture()
                path.write_bytes(f.raw * max(1, int(seconds)))
                info = {"path": str(path), "seconds": seconds, "samples": f.samples,
                        "realtime": 1.0, "warning": None}
            else:
                scope = self._scope
                if scope is None:
                    own_transport = Transport.open(timeout=5000)
                    scope = Scope(own_transport)
                    scope.read_calibration()
                    scope.configure(**self._scope_kwargs())
                rec = REC.record(scope, seconds=seconds, cfg=dict(self.cfg),
                                 out=Path("captures") /
                                 f"ui-{time.strftime('%Y%m%d-%H%M%S')}.bin")
                read = rec.read_seconds or rec.wall_seconds
                rt = (rec.nominal_seconds / read) if read else 0.0
                warnings = []
                if rec.nominal_seconds < seconds * 0.9:
                    warnings.append(f"サイズ上限（{REC.MAX_BYTES // 1024 // 1024} MB）で "
                                    f"{rec.nominal_seconds:.2f} 秒に切り詰め")
                if rt > 3:
                    warnings.append("転送がデータ長より大幅に速いため、実時間で連続した"
                                    "データではない可能性（240k 推奨）")
                info = {"path": str(rec.path), "seconds": rec.nominal_seconds,
                        "samples": rec.total_samples, "realtime": rt,
                        "warning": " / ".join(warnings) or None}
        except Exception as e:
            info = {"error": f"{type(e).__name__}: {e}"}
        finally:
            if own_transport is not None:
                try:
                    own_transport.close()
                except Exception:
                    pass
        with self.lock:
            self.status.update(recording=False, record_seconds=0.0, last_record=info)

    def _scope_kwargs(self) -> dict:
        return dict(rate=self.cfg["rate"], ch1_range=self.cfg["ch1"],
                    ch2_range=self.cfg["ch2"], ac_ch1=self.cfg["ac1"],
                    ac_ch2=self.cfg["ac2"])

    def _apply_pending(self, scope: Scope) -> None:
        """設定が変わっていたら送り直す（毎フレーム 4 コマンド送るのは無駄なので）。"""
        key = (self.cfg["rate"], self.cfg["ch1"], self.cfg["ch2"],
               self.cfg["ac1"], self.cfg["ac2"])
        if getattr(self, "_last_key", None) != key:
            scope.configure(**self._scope_kwargs())
            self._last_key = key

    def _set_status(self, **kw) -> None:
        with self.lock:
            self.status.update(kw)


# ----------------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    worker: ScopeWorker = None       # type: ignore
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):     # 静かに
        pass

    # ---- helpers
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

    def _file(self, name: str, ctype: str) -> None:
        p = WEB_DIR / name
        if not p.exists():
            self._send(404, b"not found", "text/plain")
            return
        self._send(200, p.read_bytes(), ctype)

    # ---- routes
    def do_GET(self) -> None:
        url = urlparse(self.path)
        path = url.path
        if path in ("/", "/index.html"):
            self._file("index.html", "text/html; charset=utf-8")
        elif path == "/app.js":
            self._file("app.js", "application/javascript; charset=utf-8")
        elif path == "/style.css":
            self._file("style.css", "text/css; charset=utf-8")
        elif path == "/api/meta":
            self._json({
                "demo": self.worker.demo,
                "rates": list(C.SAMPLE_RATES),
                "ch1_ranges": list(C.CH1_RANGES),
                "ch2_ranges": list(C.CH2_RANGES),
                "defaults": DEFAULT_CFG,
                "capacity": {label: REC.seconds_for(r.hz, REC.MAX_BYTES)
                             for label, r in C.SAMPLE_RATES.items()},
                "max_mb": REC.MAX_BYTES // 1024 // 1024,
            })
        elif path == "/api/frame":
            frame, status, cal = self.worker.snapshot()
            self._json({"frame": frame, "status": status, "cal": cal})
        elif path == "/api/download":
            qs = parse_qs(url.query)
            name = (qs.get("name") or [""])[0]
            fmt = (qs.get("format") or ["bin"])[0]
            self._download(name, fmt)
        elif path == "/api/export":
            qs = parse_qs(url.query)
            kind = (qs.get("kind") or ["csv"])[0]
            try:
                body, ctype, name = _export(self.worker, kind)
            except FileNotFoundError as e:
                self._json({"error": str(e)}, 409)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self._send(404, b"not found", "text/plain")

    def _download(self, name: str, fmt: str) -> None:
        base = Path(name).name            # ディレクトリ抜きの名前だけ許可
        p = Path("captures") / base
        if not p.exists() or not p.is_file():
            self._json({"error": f"{base} がありません"}, 404)
            return
        if fmt == "csv":
            csv_path = p.with_suffix(p.suffix + ".csv")
            if not csv_path.exists():
                try:
                    REC.to_csv(p, csv_path)
                except Exception as e:
                    self._json({"error": f"CSV 変換に失敗: {e}"}, 500)
                    return
            p = csv_path
            ctype = "text/csv; charset=utf-8"
        else:
            ctype = "application/octet-stream"
        body = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", f'attachment; filename="{p.name}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self) -> None:
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if url.path == "/api/config":
            self.worker.set_config(body)
            self._json({"ok": True, "cfg": self.worker.cfg})
        elif url.path == "/api/record":
            self.worker.start_record(float(body.get("seconds", 5)))
            self._json({"ok": True})
        elif url.path == "/api/resync":
            self.worker.resync()
            self._json({"ok": True})
        else:
            self._send(404, b"not found", "text/plain")


def _export(worker: "ScopeWorker", kind: str):
    """最新フレームを CSV / SVG で返す（フル解像度）。"""
    frame = worker.last()
    if frame is None:
        raise FileNotFoundError("まだフレームがありません")
    if kind == "svg":
        return _svg_bytes(frame), "image/svg+xml", "dds140.svg"
    v1 = frame.ch1_volts()
    v2 = frame.ch2_volts()
    dt = 1.0 / frame.rate_hz
    lines = ["time_s,ch1_v,ch2_v"]
    for i in range(len(v1)):
        lines.append(f"{i * dt:.9g},{v1[i]:.6f},{v2[i]:.6f}")
    return ("\n".join(lines) + "\n").encode(), "text/csv; charset=utf-8", "dds140.csv"


def _svg_bytes(frame: Frame) -> bytes:
    w, h, pad = 1000, 400, 40
    series = [("CH1", "#3ec6ff", frame.ch1_volts()),
              ("CH2", "#ff5e8a", frame.ch2_volts())]
    vals = [v for _, _, s in series for v in s]
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        lo, hi = lo - 1, hi + 1
    span = hi - lo
    n = max(len(s) for _, _, s in series)
    step = max(1, n // 2000)

    def y(v):
        return pad + (h - 2 * pad) * (hi - v) / span

    def x(i):
        return pad + (w - 2 * pad) * i / max(1, n - 1)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">',
           f'<rect width="{w}" height="{h}" fill="#0d1117"/>']
    for k in range(11):
        out.append(f'<line x1="{pad + (w-2*pad)*k/10:.1f}" y1="{pad}" '
                   f'x2="{pad + (w-2*pad)*k/10:.1f}" y2="{h-pad}" stroke="#1f2937"/>')
        out.append(f'<line x1="{pad}" y1="{pad + (h-2*pad)*k/10:.1f}" '
                   f'x2="{w-pad}" y2="{pad + (h-2*pad)*k/10:.1f}" stroke="#1f2937"/>')
    for name, color, s in series:
        pts = " ".join(f"{x(i):.1f},{y(s[i]):.1f}" for i in range(0, n, step))
        out.append(f'<polyline fill="none" stroke="{color}" stroke-width="1.2" points="{pts}"/>')
    span_us = n * (1.0 / frame.rate_hz) * 1e6
    out.append(f'<text x="{pad}" y="24" fill="#e6edf3" font-family="monospace" '
               f'font-size="13">DDS140  {frame.rate_hz/1e6:g} MS/s  '
               f'{n} samples  {span_us:.4g} us</text>')
    out.append(f'<text x="{pad}" y="{h-10}" fill="#8b949e" font-family="monospace" '
               f'font-size="12">{lo:+.3f} V .. {hi:+.3f} V</text>')
    out.append("</svg>")
    return "\n".join(out).encode()


def serve(port: int = 8765, demo: bool = False, open_browser: bool = True) -> int:
    worker = ScopeWorker(demo=demo)
    handler = type("BoundHandler", (Handler,), {"worker": worker})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    worker.start()
    url = f"http://127.0.0.1:{port}/"
    print(f"DDS140 UI: {url}" + ("  (demo: 合成波形)" if demo else ""))
    print("  Ctrl+C で終了")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了します")
    finally:
        worker.stop()
        worker.join(timeout=3)
        server.server_close()
    return 0
