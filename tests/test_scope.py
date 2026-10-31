"""ハードウェア不要のテスト。`python3 -m unittest discover -s tests`"""
from __future__ import annotations

import unittest

from dds140 import const as C
from dds140.scope import Calibration, Frame


class ConstTest(unittest.TestCase):
    def test_ranges_have_valid_cal_indices(self):
        for table in (C.CH1_RANGES, C.CH2_RANGES):
            for name, r in table.items():
                self.assertIn(r.cal_scale, C.CAL_ITEMS, name)
                self.assertIn(r.cal_zero, C.CAL_ITEMS, name)

    def test_ch1_ctrl_bits_fit_in_bit3(self):
        for name, r in C.CH1_RANGES.items():
            self.assertIn(r.code, (0, 2, 4), name)
            self.assertIn(r.ctrl_bits12, (0,), name)

    def test_ch2_codes(self):
        for name, r in C.CH2_RANGES.items():
            self.assertIn(r.code, (0, 64), name)
            self.assertEqual(r.ctrl_bit3, False, name)

    def test_sample_rate_codes(self):
        codes = {r.code for r in C.SAMPLE_RATES.values()}
        self.assertEqual(codes, {0x0, 0xC, 0x8, 0xB, 0xA})


class CombinedModeTest(unittest.TestCase):
    def test_200m_is_the_combined_timebase(self):
        r = C.SAMPLE_RATES["200M"]
        self.assertTrue(r.combine)
        self.assertEqual(r.code, C.ADC_100M)

    def test_other_rates_are_not_combined(self):
        for label in ("100M", "10M", "625k", "39k", "240k"):
            self.assertFalse(C.SAMPLE_RATES[label].combine, label)

    def test_combined_flag_does_not_change_data_layout(self):
        # 合成モードでもデータは CH1/CH2 の 2 バイト構成（実測）
        cal = Calibration(raw={1: 117, 2: 120, 3: 164, 4: 160})
        f = Frame(raw=bytes([117, 120, 118, 121]), rate_hz=1e6,
                  ch1_range=C.CH1_RANGES["1V"], ch2_range=C.CH2_RANGES["1V"],
                  cal=cal, combined=True)
        self.assertEqual(f.ch1_codes, bytes([117, 118]))
        self.assertEqual(f.ch2_codes, bytes([120, 121]))
        self.assertEqual(f.samples, 2)


class RangeTrimTest(unittest.TestCase):
    def test_apply_trims_scales_gain_values(self):
        import tempfile
        from pathlib import Path
        from dds140.calib import apply_trims, load_ranges, save_ranges

        cal = Calibration(raw={3: 164, 8: 122, 6: 174})
        n = apply_trims(cal, {"3": 0.875, "8": 0.909})
        self.assertEqual(n, 2)
        self.assertAlmostEqual(cal.raw[3], 143.5)
        self.assertAlmostEqual(cal.raw[8], 110.898)
        self.assertEqual(cal.raw[6], 174)          # 触っていない項目はそのまま

    def test_apply_trims_ignores_junk(self):
        from dds140.calib import apply_trims
        cal = Calibration(raw={3: 164})
        self.assertEqual(apply_trims(cal, {"x": 2.0, "99": 0.5}), 0)

    def test_save_and_load_round_trip(self):
        import tempfile
        from pathlib import Path
        from dds140.calib import load_ranges, save_ranges

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "r.json"
            data = {"reference_pp": 1.5, "trims": {"3": 0.875}}
            save_ranges(data, path)
            self.assertEqual(load_ranges(path), data)
            self.assertEqual(load_ranges(Path(d) / "missing.json"), {})


class FrameTest(unittest.TestCase):
    def setUp(self):
        self.cal = Calibration(raw={1: 117, 2: 120, 3: 164, 4: 160, 5: 125})

    def _frame(self, raw: bytes, ch1="1V", ch2="1V"):
        return Frame(raw=raw, rate_hz=100e6,
                     ch1_range=C.CH1_RANGES[ch1], ch2_range=C.CH2_RANGES[ch2],
                     cal=self.cal)

    def test_interleaved_split(self):
        # 実機と同じ並び: CH1, CH2, CH1, CH2, ...
        f = self._frame(bytes([117, 120, 118, 121]))
        self.assertEqual(f.ch1_codes, bytes([117, 118]))
        self.assertEqual(f.ch2_codes, bytes([120, 121]))
        self.assertEqual(f.samples, 2)

    def test_zero_maps_to_zero_volts(self):
        f = self._frame(bytes([117, 120]))
        self.assertAlmostEqual(f.ch1_volts()[0], 0.0)
        self.assertAlmostEqual(f.ch2_volts()[0], 0.0)

    def test_scale_matches_vendor_formula(self):
        # vendor: (code - zero) * dScale * (raw*2/255) / 255 * probe
        f = self._frame(bytes([127, 130]))
        ch1_per_lsb = 10 * (164 * 2 / 255) / 255
        ch2_per_lsb = 10 * (160 * 2 / 255) / 255
        self.assertAlmostEqual(f.ch1_volts()[0], 10 * ch1_per_lsb)
        self.assertAlmostEqual(f.ch2_volts()[0], 10 * ch2_per_lsb)

    def test_lower_range_is_finer(self):
        coarse = self._frame(bytes([127, 130]), ch1="1V").ch1_volts()[0]
        fine = self._frame(bytes([127, 130]), ch1="100mV").ch1_volts()[0]
        self.assertLess(abs(fine), abs(coarse))

    def test_times(self):
        f = self._frame(bytes([0, 0, 0, 0]))
        self.assertEqual(f.times(), [0.0, 1e-8])


if __name__ == "__main__":
    unittest.main()
