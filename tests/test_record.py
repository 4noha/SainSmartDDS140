"""記録まわりのテスト（ハードウェア不要）。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dds140 import const as C
from dds140.record import (MAX_BYTES, Recording, bytes_for, describe_capacity,
                           seconds_for, to_csv)


class SizeTest(unittest.TestCase):
    def test_bytes_for_is_even(self):
        for hz, sec in ((100e6, 0.001), (39e3, 10), (240e3, 3)):
            n = bytes_for(hz, sec)
            self.assertEqual(n % 2, 0, (hz, sec, n))
            self.assertAlmostEqual(seconds_for(hz, n), sec, places=6)

    def test_round_trip(self):
        self.assertEqual(seconds_for(240e3, bytes_for(240e3, 3.0)), 3.0)

    def test_capacity_table_mentions_all_rates(self):
        text = describe_capacity()
        for label in C.SAMPLE_RATES:
            self.assertIn(label, text)

    def test_max_bytes_is_40mb(self):
        self.assertEqual(MAX_BYTES, 40 * 1024 * 1024)


class SummaryTest(unittest.TestCase):
    def test_warns_when_transfer_is_much_faster_than_data(self):
        rec = Recording(
            path=Path("x.bin"), meta_path=Path("x.bin.json"),
            frames=[{"samples": 2_600_000, "rate_hz": 39e3,
                     "wall_seconds": 2.0, "read_seconds": 0.7}],
        )
        text = rec.summary()
        self.assertIn("realtime_factor", text)
        self.assertIn("連続していない可能性", text)

    def test_no_warning_at_realtime(self):
        rec = Recording(
            path=Path("x.bin"), meta_path=Path("x.bin.json"),
            frames=[{"samples": 720_000, "rate_hz": 240e3,
                     "wall_seconds": 12.0, "read_seconds": 3.0}],
        )
        self.assertNotIn("連続していない可能性", rec.summary())


class CsvTest(unittest.TestCase):
    def test_to_csv(self):
        with tempfile.TemporaryDirectory() as d:
            bin_path = Path(d) / "r.bin"
            data = bytes([117, 120, 118, 121, 119, 122])
            bin_path.write_bytes(data)
            meta = {
                "rate_hz": 1000.0,
                "calibration": {"zero_ch1_1V": 117, "zero_ch2_1V": 120},
                "frames": [{"offset_bytes": 0, "bytes": len(data),
                            "rate_hz": 1000.0, "samples": 3}],
            }
            Path(str(bin_path) + ".json").write_text(json.dumps(meta))
            csv_path = Path(d) / "r.bin.csv"
            to_csv(bin_path, csv_path)
            lines = csv_path.read_text().strip().split("\n")
            self.assertEqual(lines[0], "frame,time_s,ch1_code,ch2_code")
            self.assertEqual(len(lines), 4)
            self.assertEqual(lines[1].split(",")[2:], ["117", "120"])
            self.assertAlmostEqual(float(lines[3].split(",")[1]), 0.002)


if __name__ == "__main__":
    unittest.main()
