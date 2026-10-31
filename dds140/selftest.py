"""実機のレンジ／レート設定を一通り試す（開発用・ハードウェア必須）。

    python3 -m dds140.selftest    # もしくは  python tools/selftest.py
"""
from __future__ import annotations

import sys

from dds140 import const as C
from dds140.scope import Scope
from dds140.transport import Transport


def stats(codes: bytes) -> str:
    n = len(codes)
    return (f"n={n} min={min(codes)} max={max(codes)} "
            f"mean={sum(codes)/n:.1f}")


def main() -> int:
    t = Transport.open()
    s = Scope(t, verbose=False)
    try:
        s.read_calibration()
        print("=== rates")
        for rate in ("100M", "10M", "625k", "240k", "39k"):
            for rng in ("1V",):
                s.configure(rate=rate, ch1_range=rng, ch2_range=rng)
                try:
                    f = s.capture(total_bytes=4096, timeout=8000)
                    print(f"  {rate:5s} {rng:5s}  ch1 {stats(f.ch1_codes)}  "
                          f"ch2 {stats(f.ch2_codes)}")
                except Exception as e:
                    print(f"  {rate:5s} {rng:5s}  失敗: {type(e).__name__}: {e}")

        print("=== ranges (rate=100M)")
        for name in C.CH1_RANGES:
            s.configure(rate="100M", ch1_range=name, ch2_range="1V")
            f = s.capture(total_bytes=2048)
            v = f.ch1_volts()
            print(f"  CH1 {name:6s} code={C.CH1_RANGES[name].code:3d} "
                  f"ctrl1=0x{s.ctrl1:02x}  {stats(f.ch1_codes)}  "
                  f"[{min(v):+.3f}, {max(v):+.3f}] V")
        for name in C.CH2_RANGES:
            s.configure(rate="100M", ch1_range="1V", ch2_range=name)
            f = s.capture(total_bytes=2048)
            v = f.ch2_volts()
            print(f"  CH2 {name:6s} code={C.CH2_RANGES[name].code:3d} "
                  f"ctrl1=0x{s.ctrl1:02x}  {stats(f.ch2_codes)}  "
                  f"[{min(v):+.3f}, {max(v):+.3f}] V")

        print("=== AC coupling")
        for ac1, ac2 in ((True, False), (False, True), (True, True)):
            s.configure(rate="100M", ch1_range="1V", ch2_range="1V",
                        ac_ch1=ac1, ac_ch2=ac2)
            f = s.capture(total_bytes=2048)
            print(f"  ac1={ac1} ac2={ac2} ctrl0=0x{s.ctrl0:02x} ctrl1=0x{s.ctrl1:02x}  "
                  f"ch1 {stats(f.ch1_codes)}  ch2 {stats(f.ch2_codes)}")
    finally:
        s.configure(rate="100M")
        t.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
