"""信号の記録（1 フレーム長時間 / 複数フレーム）と保存。

実機で測った限界（2026-10-31, macOS）:

| レート | 1 フレームの実質の長さ | 転送時間 | 備考 |
|---|---|---|---|
| 100 MS/s | 0.03 s（5.2 MB で 2.6M サンプル/ch） | 0.7 s | USB 帯域で決まる。連続記録は不可 |
| 240 kS/s | 10.9 s（5.2 MB） | 10.9 s | 転送が実時間と同じ = 連続ストリーム |
| 39 kS/s | 67 s（5.2 MB） | 0.7 s | 転送が実時間より桁で速い（下記注意） |

**注意（39 kS/s など）**: 転送が「データ長 ÷ レート」より桁で速いレートでは、
届いたサンプルが実時間で連続している保証がない（デバイス内部で間引いている可能性）。
240 kS/s は転送時間が実時間と一致するので連続とみなせる。
判別のため、記録メタデータに実測の転送時間と realtime_factor を残す。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from . import const as C
from .scope import Frame, Scope

DEFAULT_DIR = Path("captures")
# 実機で受信できた上限（40 MB）。超える要求は切り詰める。
MAX_BYTES = 40 * 1024 * 1024


def bytes_for(rate_hz: float, seconds: float, bytes_per_sample: int = 2) -> int:
    """指定秒数ぶんのバイト数（通常 1 サンプル 2 バイト = CH1/CH2 交互）。"""
    n = int(round(rate_hz * seconds)) * bytes_per_sample
    return max(bytes_per_sample, n + (n % bytes_per_sample))


def seconds_for(rate_hz: float, total_bytes: int, bytes_per_sample: int = 2) -> float:
    return (total_bytes // bytes_per_sample) / rate_hz


@dataclass
class Recording:
    path: Path
    meta_path: Path
    frames: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def total_samples(self) -> int:
        return sum(f["samples"] for f in self.frames)

    @property
    def nominal_seconds(self) -> float:
        return sum(f["samples"] / f["rate_hz"] for f in self.frames)

    @property
    def wall_seconds(self) -> float:
        return sum(f["wall_seconds"] for f in self.frames)

    @property
    def read_seconds(self) -> float:
        return sum(f.get("read_seconds", 0.0) for f in self.frames)

    def summary(self) -> str:
        read = self.read_seconds or self.wall_seconds
        rt = self.nominal_seconds / read if read else 0.0
        lines = [
            f"記録: {self.path}",
            f"  フレーム {len(self.frames)} 枚 / {self.total_samples} サンプル/ch",
            f"  データ長 {self.nominal_seconds:.2f} s / 転送 {read:.2f} s / "
            f"全体 {self.wall_seconds:.2f} s（realtime_factor {rt:.2f}）",
        ]
        if rt > 3:
            lines.append("  ! 転送がデータ長よりずっと速い = 実時間で連続していない可能性。"
                         " 連続性が要るなら 240k を使う。")
        lines.append(f"  メタデータ: {self.meta_path}")
        return "\n".join(lines)


def _meta(scope: Scope, cfg: dict) -> dict:
    return {
        "tool": f"dds140 {__version__}",
        "created": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "format": ("uint8: CH1 only, 2x rate (combined mode)"
                   if getattr(scope, "combined", False)
                   else "interleaved uint8: CH1, CH2, CH1, CH2, ..."),
        "rate_label": cfg["rate"],
        "rate_hz": scope.rate_hz,
        "ch1_range": scope.ch1_range.name,
        "ch2_range": scope.ch2_range.name,
        "ctrl0": scope.ctrl0,
        "ctrl1": scope.ctrl1,
        "skip": cfg.get("skip", 0),
        "calibration": scope.cal.as_dict(),
        "frames": [],
    }


def record(scope: Scope, out: str | Path | None = None, seconds: float | None = None,
           samples: int | None = None, frames: int = 1,
           cfg: dict | None = None, chunk_sleep: float = 0.0) -> Recording:
    """記録する。`samples`（1ch）優先、なければ `seconds` から計算。"""
    cfg = cfg or {}
    rate = scope.rate_hz
    per = 1 if getattr(scope, "combined", False) else 2
    if samples is None:
        seconds = 1.0 if seconds is None else seconds
        total_bytes = bytes_for(rate, seconds, per)
    else:
        total_bytes = int(samples) * per

    capped = False
    if total_bytes > MAX_BYTES:
        total_bytes = MAX_BYTES
        capped = True

    out = Path(out) if out else DEFAULT_DIR / (
        "dds140-" + _dt.datetime.now().strftime("%Y%m%d-%H%M%S") + ".bin")
    out.parent.mkdir(parents=True, exist_ok=True)
    meta_path = out.with_suffix(out.suffix + ".json")

    meta = _meta(scope, cfg)
    if capped:
        meta["note"] = f"要求サイズが上限 {MAX_BYTES} バイトを超えたので切り詰めた"

    with open(out, "wb") as fh:
        for _ in range(max(1, int(frames))):
            t0 = time.monotonic()
            frame = scope.capture(total_bytes=total_bytes,
                                  poll_timeout=30.0,
                                  skip=int(cfg.get("skip", 0)))
            wall = time.monotonic() - t0
            fh.write(frame.raw)
            fh.flush()
            meta["frames"].append({
                "offset_bytes": fh.tell() - len(frame.raw),
                "bytes": len(frame.raw),
                "samples": frame.samples,
                "rate_hz": frame.rate_hz,
                "wall_seconds": round(wall, 3),
                "poll_seconds": round(frame.poll_seconds, 3),
                "read_seconds": round(frame.read_seconds, 3),
            })
            if chunk_sleep:
                time.sleep(chunk_sleep)

    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    rec = Recording(path=out, meta_path=meta_path, frames=meta["frames"], meta=meta)
    return rec


def load_recording(path: str | Path) -> tuple[bytes, dict]:
    """保存した .bin と .json を読む（CSV 変換などに使う）。"""
    p = Path(path)
    meta = json.loads(Path(str(p) + ".json").read_text()) if Path(str(p) + ".json").exists() else {}
    return p.read_bytes(), meta


def to_csv(bin_path: str | Path, csv_path: str | Path) -> int:
    """.bin + .json から CSV を作る（フレームごとに時刻をリセット）。"""
    raw, meta = load_recording(bin_path)
    frames = meta.get("frames") or [{"offset_bytes": 0, "bytes": len(raw),
                                     "rate_hz": meta.get("rate_hz", 1e6)}]
    cal = meta.get("calibration") or {}
    zero1 = cal.get("zero_ch1_1V", 128)
    zero2 = cal.get("zero_ch2_1V", 128)
    lines = ["frame,time_s,ch1_code,ch2_code"]
    with open(csv_path, "w") as fh:
        fh.write(lines[0] + "\n")
        for fi, fr in enumerate(frames):
            off = fr["offset_bytes"]
            data = raw[off:off + fr["bytes"]]
            dt = 1.0 / fr["rate_hz"]
            for i in range(len(data) // 2):
                fh.write(f"{fi},{i * dt:.9g},{data[2 * i]},{data[2 * i + 1]}\n")
    return len(raw)


def describe_capacity() -> str:
    rows = []
    for label, r in C.SAMPLE_RATES.items():
        one = seconds_for(r.hz, MAX_BYTES)
        rows.append(f"  {label:5s} {r.hz/1e3:8.1f} kS/s  1 フレーム最大 {one:8.2f} s "
                    f"({MAX_BYTES // 1024 // 1024} MB)")
    return "\n".join(rows)
