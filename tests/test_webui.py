"""UI（webui）のロジックのテスト。ハードウェア不要。"""
from __future__ import annotations

import math
import unittest

from dds140 import const as C
from dds140.scope import Calibration, Frame
from dds140.webui import (_envelope, _freq_estimate, _nice_ylim, _stats,
                          DEFAULT_CFG, DemoSource, frame_to_json)

CAL = Calibration(raw={1: 117, 2: 120, 3: 164, 4: 160, 5: 125})


def make_frame(v1, v2):
    raw = bytearray()
    for a, b in zip(v1, v2):
        raw.append(a & 0xFF)
        raw.append(b & 0xFF)
    return Frame(raw=bytes(raw), rate_hz=100e6,
                 ch1_range=C.CH1_RANGES["1V"], ch2_range=C.CH2_RANGES["1V"],
                 cal=CAL)


class EnvelopeTest(unittest.TestCase):
    def test_short_series_is_passed_through(self):
        vals = [0.0, 1.0, 2.0]
        self.assertEqual(_envelope(vals, points=100), vals)

    def test_triplets_min_mean_max(self):
        vals = [0.0, 10.0, 2.0, 4.0, 6.0, 8.0]
        env = _envelope(vals, points=2)
        self.assertEqual(len(env), 6)
        self.assertEqual((env[0], env[1], env[2]), (0.0, 4.0, 10.0))
        self.assertEqual((env[3], env[4], env[5]), (4.0, 6.0, 8.0))

    def test_length_is_multiple_of_three(self):
        vals = [math.sin(i / 10) for i in range(5000)]
        self.assertEqual(len(_envelope(vals, points=100)) % 3, 0)


class FreqTest(unittest.TestCase):
    def test_sine(self):
        dt = 1e-8
        rate = 1 / dt
        f = 1e6
        vals = [math.sin(2 * math.pi * f * i * dt) for i in range(20000)]
        got = _freq_estimate(vals, dt)
        self.assertIsNotNone(got)
        self.assertAlmostEqual(got / f, 1.0, places=2)

    def test_noise_is_rejected(self):
        import random
        random.seed(1)
        vals = [random.uniform(-1, 1) for _ in range(20000)]
        self.assertIsNone(_freq_estimate(vals, 1e-8))

    def test_flat_is_rejected(self):
        self.assertIsNone(_freq_estimate([0.5] * 1000, 1e-8))


class YlimTest(unittest.TestCase):
    def test_spikes_do_not_dominate(self):
        import random
        random.seed(2)
        vals = [0.01 * random.uniform(-1, 1) for _ in range(10000)]
        vals[0] = 50.0          # 単発スパイク
        lo, hi = _nice_ylim(vals)
        self.assertLess(hi, 5.0)
        self.assertGreater(lo, -5.0)

    def test_ordering(self):
        lo, hi = _nice_ylim([-0.3, 0.0, 0.2, 0.5])
        self.assertLess(lo, hi)


class FrameJsonTest(unittest.TestCase):
    def setUp(self):
        n = 2000
        v1 = [int(round(117 + 6 * math.sin(i / 50))) for i in range(n)]
        v2 = [int(round(120 + 3 * math.sin(i / 120))) for i in range(n)]
        self.f = make_frame(v1, v2)

    def test_payload_shape(self):
        p = frame_to_json(self.f, 1, dict(DEFAULT_CFG))
        self.assertEqual(p["samples"], 2000)
        self.assertEqual(len(p["ylim"]), 2)
        for ch in ("ch1", "ch2"):
            self.assertIn("stats", p[ch])
            self.assertIn("envelope", p[ch])
            self.assertIn("freq", p[ch])

    def test_stats(self):
        st = _stats([0.0, 1.0, 2.0])
        self.assertEqual(st["min"], 0.0)
        self.assertEqual(st["max"], 2.0)
        self.assertAlmostEqual(st["mean"], 1.0)
        self.assertAlmostEqual(st["rms"], math.sqrt(5 / 3))


class DemoSourceTest(unittest.TestCase):
    def test_demo_looks_like_a_signal(self):
        src = DemoSource()
        src.cfg = dict(DEFAULT_CFG)
        src.cfg["samples"] = 4096
        f = src.capture()
        self.assertEqual(f.samples, 4096)
        v = f.ch1_volts()
        self.assertGreater(max(v) - min(v), 0.5)
        freq = _freq_estimate(v, 1 / f.rate_hz)
        self.assertIsNotNone(freq)


if __name__ == "__main__":
    unittest.main()
