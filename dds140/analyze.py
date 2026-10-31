"""入力波形の周波数成分を調べる（遅い信号・ハム・1kHz の校正用）。

純 Python なので numpy は使わない。Goertzel で指定範囲だけ走査する。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .scope import Scope


@dataclass
class Peak:
    freq: float
    mag: float
    rel: float           # 最大ピークを 1 とした相対値


def decimate(vals: list[float], k: int) -> list[float]:
    return [sum(vals[i:i + k]) / k for i in range(0, len(vals) - k + 1, k)]


def goertzel(x: list[float], freq: float, rate: float) -> float:
    w = 2.0 * math.pi * freq / rate
    c = 2.0 * math.cos(w)
    s1 = s2 = 0.0
    for v in x:
        s0 = v + c * s1 - s2
        s2 = s1
        s1 = s0
    return math.sqrt(max(0.0, s1 * s1 + s2 * s2 - c * s1 * s2))


def scan(vals: list[float], rate: float, f_lo: float, f_hi: float,
         step: float = 5.0, dec: int = 1) -> list[Peak]:
    """vals を rate でサンプリングしたとみなし、f_lo..f_hi のピークを返す。"""
    if dec > 1:
        vals = decimate(vals, dec)
        rate = rate / dec
    m = sum(vals) / len(vals)
    x = [v - m for v in vals]
    peaks: list[Peak] = []
    f = f_lo
    while f <= f_hi:
        if f < rate / 2.5:            # ナイキスト近傍は避ける
            peaks.append(Peak(f, goertzel(x, f, rate), 0.0))
        f += step
    if not peaks:
        return []
    top = max(p.mag for p in peaks) or 1.0
    for p in peaks:
        p.rel = p.mag / top
    peaks.sort(key=lambda p: p.mag, reverse=True)
    return peaks


def analyse(scope: Scope, rate: str = "240k", ch: int = 1,
            seconds: float = 0.5, f_lo: float = 10.0, f_hi: float = 5000.0,
            step: float = 5.0) -> tuple[list[Peak], dict]:
    """指定レートで取得してピークを返す。"""
    scope.configure(rate=rate, ch1_range="1V", ch2_range="1V")
    n = int(scope.rate_hz * seconds) * 2
    # 巨大なフレームは実機で詰まることがあるので上限を置く（262144 B = 131k サンプル）
    n = max(8192, min(n, 262144))
    frame = scope.capture(total_bytes=n, poll_timeout=25.0, skip=64)
    vals = frame.ch1_volts() if ch == 1 else frame.ch2_volts()
    # 間引いてから走査する（平均で落とすのでエイリアスしにくい）
    dec = max(1, int(frame.rate_hz / (f_hi * 8)))
    decimated = decimate(vals, dec)
    # Goertzel は点数×周波数に比例して重いので、窓を 20000 点までに制限する
    if len(decimated) > 20000:
        decimated = decimated[:20000]
    peaks = scan(decimated, frame.rate_hz / dec, f_lo,
                 min(f_hi, frame.rate_hz / 2.5), step, 1)
    info = {
        "rate": frame.rate_hz,
        "samples": frame.samples,
        "seconds": frame.samples / frame.rate_hz,
        "decimation": dec,
        "pp": max(vals) - min(vals),
        "rms": (sum((v - sum(vals) / len(vals)) ** 2 for v in vals)
                / len(vals)) ** 0.5,
    }
    return peaks, info


def mains_note(freq: float) -> str:
    """商用電源ハム（50/60Hz とその高調波）かどうかの注記。"""
    for base in (50.0, 60.0):
        for mult in range(1, 9):
            target = base * mult
            if abs(freq - target) <= target * 0.05:
                return f"（商用電源 {base:.0f}Hz の {mult} 次高調波の可能性）"
    return ""
