"""長時間フレームがどこまで取れるか実機で確かめる（開発用）。"""
import time

from dds140 import const as C
from dds140.scope import Scope
from dds140.transport import Transport

t = Transport.open(timeout=10000)
s = Scope(t)
s.read_calibration()

for rate, sizes in (("39k", [131072, 1048576, 5242880]),
                    ("240k", [5242880]),
                    ("100M", [5242880])):
    for size in sizes:
        s.configure(rate=rate)
        t.flush()
        t0 = time.monotonic()
        t.cmd(C.CMD_START)
        st = None
        while time.monotonic() - t0 < 30:
            st = t.cmd(C.CMD_STATUS)
            if st == 33:
                break
            time.sleep(0.05)
        t_ready = time.monotonic() - t0
        if st != 33:
            print(f"{rate:5s} {size:8d}B: status={st} でタイムアウト")
            continue
        try:
            data = t.read_frame(size, timeout=10000)
        except Exception as e:
            print(f"{rate:5s} {size:8d}B: read 失敗 {type(e).__name__}: {e}")
            continue
        el = time.monotonic() - t0
        ch1 = data[0::2]
        print(f"{rate:5s} {size:8d}B: {len(data)}B 受信 "
              f"(ready {t_ready:.1f}s, total {el:.1f}s) "
              f"ch1 {min(ch1)}..{max(ch1)} mean {sum(ch1)/len(ch1):.1f} "
              f"= {len(ch1)/C.SAMPLE_RATES[rate].hz:.2f}s 分")
t.close()
