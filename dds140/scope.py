"""DDS140 の操作（キャリブレーション・設定・1 フレーム取得）。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import const as C
from .transport import Transport


@dataclass
class Calibration:
    raw: dict[int, int] = field(default_factory=dict)

    def get(self, index: int, default: int = 0) -> int:
        return self.raw.get(index, default)

    # ベンダ GUI と同じ換算: フルスケール = raw * 2 / 255
    def gain(self, index: int) -> float:
        return self.get(index) * 2.0 / 255.0

    def zero(self, index: int) -> int:
        return self.get(index)

    def as_dict(self) -> dict[str, int]:
        return {C.CAL_ITEMS.get(k, str(k)): v for k, v in sorted(self.raw.items())}


@dataclass
class Frame:
    raw: bytes
    rate_hz: float
    ch1_range: C.Range
    ch2_range: C.Range
    cal: Calibration
    probe_ch1: float = 1.0
    probe_ch2: float = 1.0
    poll_seconds: float = 0.0
    read_seconds: float = 0.0
    combined: bool = False        # cmd 36 bit0（ベンダの「200M」合成タイムベース）を使ったか

    # ---------------------------------------------------------------- 生データ
    @property
    def ch1_codes(self) -> bytes:
        return self.raw[0::2]

    @property
    def ch2_codes(self) -> bytes:
        return self.raw[1::2]

    @property
    def samples(self) -> int:
        return len(self.raw) // 2

    # ---------------------------------------------------------------- 電圧換算
    def _volts_per_lsb(self, rng: C.Range, cal_scale_index: int, probe: float) -> float:
        return rng.dscale * self.cal.gain(cal_scale_index) / 255.0 * probe

    def ch1_volts(self) -> list[float]:
        zero = self.cal.zero(self.ch1_range.cal_zero)
        k = self._volts_per_lsb(self.ch1_range, self.ch1_range.cal_scale, self.probe_ch1)
        return [(c - zero) * k for c in self.ch1_codes]

    def ch2_volts(self) -> list[float]:
        zero = self.cal.zero(self.ch2_range.cal_zero)
        k = self._volts_per_lsb(self.ch2_range, self.ch2_range.cal_scale, self.probe_ch2)
        return [(c - zero) * k for c in self.ch2_codes]

    # ---------------------------------------------------------------- トリガ
    def rotate(self, index: int) -> "Frame":
        """サンプル列を index だけ回す（表示を安定させるソフトウェアトリガ）。"""
        n = self.samples
        i = index % n if n else 0
        if i == 0:
            return self
        cut = 2 * i
        return Frame(raw=self.raw[cut:] + self.raw[:cut],
                     rate_hz=self.rate_hz, ch1_range=self.ch1_range,
                     ch2_range=self.ch2_range, cal=self.cal,
                     probe_ch1=self.probe_ch1, probe_ch2=self.probe_ch2,
                     combined=self.combined)

    def find_trigger(self, channel: int = 1, level: float = 0.5,
                     hysteresis: float = 0.15) -> int | None:
        """level（0..1, 振幅に対する位置）を上向きに横切る最初の位置。"""
        codes = self.ch1_codes if channel == 1 else self.ch2_codes
        n = len(codes)
        if n < 4:
            return None
        lo = min(codes)
        hi = max(codes)
        span = hi - lo
        if span < 4:
            return None
        mid = lo + span * level
        hyst = span * hysteresis
        armed = False
        for i, c in enumerate(codes):
            if not armed:
                if c < mid - hyst:
                    armed = True
            elif c > mid + hyst:
                return i
        return None

    def times(self) -> list[float]:
        dt = 1.0 / self.rate_hz
        return [i * dt for i in range(self.samples)]


class Scope:
    def __init__(self, transport: Transport, verbose: bool = False,
                 calibrate_rates: bool = True):
        self.t = transport
        self.verbose = verbose
        self.use_rate_calibration = calibrate_rates
        self.rate_label: str | None = None
        try:
            from .calib import load as _load_rates
            self.rate_cal = _load_rates() if calibrate_rates else {}
        except Exception:
            self.rate_cal = {}
        self.cal = Calibration()
        self.ctrl1 = 0x00      # cmd 36
        self.ctrl0 = 0x00      # cmd 148
        self.rate_hz = 100e6
        self.combined = False
        self.ch1_range = C.CH1_RANGES["1V"]
        self.ch2_range = C.CH2_RANGES["1V"]

    # ------------------------------------------------------------------ logging
    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    # -------------------------------------------------------------- calibration
    def read_calibration(self) -> Calibration:
        cal = Calibration()
        for idx in sorted(C.CAL_ITEMS):
            cal.raw[idx] = self.t.cmd(C.CMD_CAL, idx)
            self._log(f"  cal[{idx:2d}] {C.CAL_ITEMS[idx]:16s} = {cal.raw[idx]:3d}")
        self.cal = cal
        return cal

    # ----------------------------------------------------------------- configure
    def configure(self, rate: str = "100M", ch1_range: str = "1V",
                  ch2_range: str = "1V", ac_ch1: bool = False,
                  ac_ch2: bool = False) -> None:
        r = C.SAMPLE_RATES[rate]
        self.rate_label = rate
        self.combined = bool(r.combine)
        self.rate_hz = r.hz
        if self.use_rate_calibration:
            from .calib import rate_for
            eff = rate_for(rate, r.hz, self.rate_cal)
            if eff != r.hz:
                self.rate_hz = eff
                if self.verbose:
                    print(f"  rate {rate}: 校正値を使用 {eff/1e3:.2f} kS/s "
                          f"(ラベル {r.hz/1e3:.0f} kS/s)")

        # cmd 148: サンプルレート（下位ニブル）+ CH1 AC 結合（bit4）
        self.ctrl0 = (self.ctrl0 & 0xF0) | r.code
        if ac_ch1:
            self.ctrl0 |= C.AC_CH1
        else:
            self.ctrl0 &= ~C.AC_CH1

        # cmd 36: CH1/CH2 の減衰器ビット・CH2 AC 結合
        self.ch1_range = C.CH1_RANGES[ch1_range]
        self.ch2_range = C.CH2_RANGES[ch2_range]
        self.ctrl1 &= ~0x08
        if self.ch1_range.ctrl_bit3:
            self.ctrl1 |= 0x08
        self.ctrl1 &= ~0x06
        self.ctrl1 |= (self.ch2_range.ctrl_bits12 & 0x06)
        # 合成モード（cmd 36 bit0）: CH1/CH2 の 2 つの ADC を同じ入力に使う
        if r.combine:
            self.ctrl1 |= C.COMBINE
        else:
            self.ctrl1 &= ~C.COMBINE
        if ac_ch2:
            self.ctrl1 |= C.AC_CH2
        else:
            self.ctrl1 &= ~C.AC_CH2

        self._send(C.CMD_CH1_RANGE, self.ch1_range.code)
        self._send(C.CMD_CH2_RANGE, self.ch2_range.code)
        self._send(C.CMD_CONFIG1, self.ctrl1)
        self._send(C.CMD_CONFIG0, self.ctrl0)
        self._send(C.CMD_TRIG_SRC, 0)   # トリガ源 = CH1

    def _send(self, cmd: int, value: int) -> int:
        r = self.t.cmd(cmd, value)
        self._log(f"  cmd({cmd:3d}, 0x{value:04x}) -> 0x{r:02x}")
        return r

    # ------------------------------------------------------------------- capture
    def capture(self, total_bytes: int = 131072, timeout: int = 3000,
                poll_timeout: float = 15.0, skip: int = 0) -> Frame:
        if total_bytes % 2:
            total_bytes += 1

        # 取りこぼしが残っていると次フレームと混ざるので捨てる
        self.t.flush()

        t_start = time.monotonic()
        self._send(C.CMD_START, 0)
        deadline = t_start + poll_timeout
        status = None
        while time.monotonic() < deadline:
            status = self.t.cmd(C.CMD_STATUS)
            if status == C.STATUS_READY:
                break
            time.sleep(0.02)
        else:
            raise TimeoutError(
                f"取得開始待ちがタイムアウト（最後の status={status}）。"
                " サンプルレート設定かデバイス状態を確認"
            )

        t_ready = time.monotonic()
        data = self.t.read_frame(total_bytes, timeout=timeout)
        t_done = time.monotonic()
        if len(data) < total_bytes:
            raise IOError(f"読み出し不足: {len(data)} / {total_bytes} バイト")

        # フレーム先頭の数サンプルは ADC/マルチプレクサの整定で跳ねる（実測）。
        if skip:
            data = data[min(skip, total_bytes // 2) * 2:]

        return Frame(
            raw=data,
            rate_hz=self.rate_hz,
            ch1_range=self.ch1_range,
            ch2_range=self.ch2_range,
            cal=self.cal,
            poll_seconds=t_ready - t_start,
            read_seconds=t_done - t_ready,
            combined=self.combined,
        )

    # --------------------------------------------------------------------- misc
    def info(self) -> dict:
        d = self.t.dev
        return {
            "vid_pid": f"{d.idVendor:04x}:{d.idProduct:04x}",
            "manufacturer": _safe_string(d, d.iManufacturer),
            "product": _safe_string(d, d.iProduct),
            "serial": _safe_string(d, d.iSerialNumber),
            "bus": d.bus,
            "address": d.address,
            "speed": getattr(d, "speed", None),
        }

    def selfcheck(self) -> dict:
        """どのコマンドがエコーを返すか確認する（プロトコル検証用）。"""
        out = {}
        for cmd in (C.CMD_CONFIG1, C.CMD_CONFIG0, C.CMD_CH1_RANGE,
                    C.CMD_CH2_RANGE, C.CMD_TRIG_SRC):
            v = self.t.cmd(cmd, 0)
            out[cmd] = v
        out["status"] = self.t.cmd(C.CMD_STATUS)
        return out


def _safe_string(dev, index: int) -> str:
    import usb.util
    if not index:
        return ""
    try:
        return usb.util.get_string(dev, index).replace("\x00", "")
    except Exception:
        return "<取得不可>"
