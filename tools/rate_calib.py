"""入力信号の周期を自己相関で推定し、各レート設定の「本当のサンプルレート」を推定する。

    PYTHONPATH=. python3 tools/rate_calib.py
"""
from __future__ import annotations

import statistics
import sys

from dds140 import const as C
from dds140.scope import Scope
from dds140.transport import Transport

N = 131072          # 1 回に取るサンプル数/ch


def decimate(vals: list[float], k: int) -> list[float]:
    out = []
    for i in range(0, len(vals) - k, k):
        out.append(sum(vals[i:i + k]) / k)
    return out


def autocorr_peaks(x: list[float], max_lag: int, top: int = 5):
    n = len(x)
    mean = sum(x) / n
    x = [v - mean for v in x]
    # 正規化（分散 1）
    var = sum(v * v for v in x) / n
    if var <= 0:
        return []
    x = [v / var ** 0.5 for v in x]
    scores = []
    for lag in range(3, max_lag):
        num = 0.0
        for i in range(0, n - lag, 4):
            num += x[i] * x[i + lag]
        scores.append((num / (n - lag), lag))
    scores.sort(reverse=True)
    return scores[:top]


def analyse(scope, rate, dec=8, ch=1):
    scope.configure(rate=rate, ch1_range="1V", ch2_range="1V")
    f = scope.capture(total_bytes=N * 2, poll_timeout=30, skip=16)
    vals = f.ch1_volts() if ch == 1 else f.ch2_volts()
    x = decimate(vals, dec)
    peaks = autocorr_peaks(x, max_lag=len(x) // 4)
    dt = dec / f.rate_hz
    print(f"--- {rate} ({len(vals)} サンプル = {len(vals)/f.rate_hz:.3f} s と仮定)")
    for score, lag in peaks[:3]:
        print(f"    lag={lag*dec:7d} smp  周期 {lag*dt*1e3:8.3f} ms  "
              f"→ {1/(lag*dt):9.1f} Hz   相関 {score:.3f}")
    return f, peaks


def main() -> int:
    rates = sys.argv[1:] or ["240k", "39k", "625k", "10M", "100M"]
    t = Transport.open(timeout=15000)
    s = Scope(t)
    s.read_calibration()
    try:
        for rate in rates:
            analyse(s, rate)
    finally:
        t.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
