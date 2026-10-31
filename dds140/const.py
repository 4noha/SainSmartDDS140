"""実機で確認した値だけを置く定数表。

出典はベンダ GUI（DDS140.exe, DefLibrary.g_snCOMAppRes == 1 側 = DDS140/240）の
逆コンパイル結果。`_104` 系メソッドが DDS140 用、`_102` 系は DDS120 用なので
ここでは使わない。
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------- 制御コマンド
CMD_CAL = 144          # 個体キャリブレーション読み出し（wValue=項目番号）→ 1 バイト
CMD_CH1_RANGE = 34     # CH1 減衰器
CMD_CH2_RANGE = 35     # CH2 減衰器
CMD_CONFIG1 = 36       # CH2 側の設定（減衰器ビット・AC 結合・チャネル合成）
CMD_CONFIG0 = 148      # サンプルレート（下位ニブル）・CH1 AC 結合（bit4）
CMD_TRIG_SRC = 231     # トリガ源（0 = CH1/CH2, 1 = 外部/ロジック）
CMD_MODE = 52          # 0 = オシロ表示, 1 = ロジックアナライザ表示
CMD_LATCH = 53         # ロジックアナライザ用ラッチ

CMD_START = 51         # 取得開始
CMD_STATUS = 80        # 取得状態。33 (0x21) で次のフレームが読める
STATUS_READY = 33

# 信号発生器（AD9834 系とみられる。今回は未使用）
CMD_GEN_CH1_W0 = 112
CMD_GEN_CH1_W1 = 113
CMD_GEN_CH2_W0 = 114
CMD_GEN_CH2_W1 = 115
CMD_GEN_LOAD = 116
CMD_PWM_H = 118
CMD_PWM_L = 119
CMD_PWM_H2 = 120
CMD_PWM_L2 = 121
CMD_OFFSET_H = 122
CMD_OFFSET_L = 123
CMD_OFFSET_H2 = 124
CMD_OFFSET_L2 = 125
CMD_GEN_MODE = 99

EP_DATA = 0x82         # interrupt IN 1024B — 波形データはここに来る
EP_BULK86 = 0x86
EP_BULK88 = 0x88
EP_OUT = 0x04

CHUNK_BYTES = 32768    # ベンダ GUI は ReadDataCount/32KiB 回に分けて読む

# ------------------------------------------------------------------ サンプルレート
# cmd 148 の下位ニブル。実測でフレームが返ることを確認済み。
ADC_100M = 0x0         # 100 MS/s（2ch 同時）／合成時は 200 MS/s
ADC_10M = 0xC
ADC_625K = 0x8
ADC_39K = 0xB
ADC_240K = 0xA

# cmd 148 bit4 = CH1 を AC 結合、cmd 36 bit4 = CH2 を AC 結合
AC_CH1 = 0x10
AC_CH2 = 0x10
# cmd 36 bit0 = CH1/CH2 合成（200 MS/s を片側に集める）
COMBINE = 0x01


@dataclass(frozen=True)
class SampleRate:
    code: int
    hz: float
    label: str
    channels: int = 2


SAMPLE_RATES = {
    "100M": SampleRate(ADC_100M, 100e6, "100 MS/s（2ch 同時）"),
    "10M": SampleRate(ADC_10M, 10e6, "10 MS/s"),
    "625k": SampleRate(ADC_625K, 625e3, "625 kS/s"),
    "39k": SampleRate(ADC_39K, 39e3, "39 kS/s"),
    "240k": SampleRate(ADC_240K, 240e3, "240 kS/s"),
    # 合成モードは cmd 36 bit0 も立てる。v0.1 では未使用（データ配置が未検証）。
}


# --------------------------------------------------------------------- 垂直レンジ
@dataclass(frozen=True)
class Range:
    name: str
    div: float          # V/div（表示上の目安）
    code: int           # cmd 34/35 に送る値
    ctrl_bit3: bool     # cmd 36 bit3 を立てるか（CH1 側）
    ctrl_bits12: int    # cmd 36 の bit1-2（CH2 側）
    dscale: float
    cal_scale: int      # cmd 144 の項目番号（フルスケール係数）
    cal_zero: int       # cmd 144 の項目番号（ゼロ点）


# CH1 (ch0) 用。cmd 34 と cmd 36 bit3 の組み合わせ。
CH1_RANGES = {
    "2V": Range("2V", 2.0, 0, True, 0, 10.0, 3, 1),
    "1V": Range("1V", 1.0, 0, True, 0, 10.0, 3, 1),
    "500mV": Range("500mV", 0.5, 2, True, 0, 5.0, 8, 14),
    "200mV": Range("200mV", 0.2, 0, False, 0, 2.0, 6, 1),
    "100mV": Range("100mV", 0.1, 2, False, 0, 1.0, 9, 18),
    "50mV": Range("50mV", 0.05, 4, False, 0, 0.5, 10, 16),
}

# CH2 (ch1) 用。cmd 35 と cmd 36 bit1-2 の組み合わせ。
CH2_RANGES = {
    "2V": Range("2V", 2.0, 0, False, 0, 10.0, 4, 2),
    "1V": Range("1V", 1.0, 0, False, 0, 10.0, 4, 2),
    "500mV": Range("500mV", 0.5, 0, False, 2, 5.0, 11, 15),
    "200mV": Range("200mV", 0.2, 64, False, 0, 2.0, 7, 2),
    "100mV": Range("100mV", 0.1, 64, False, 2, 1.0, 12, 19),
    "50mV": Range("50mV", 0.05, 64, False, 4, 0.5, 13, 17),
}

# cmd 144 の項目（ベンダ GUI の並び）
CAL_ITEMS = {
    1: "zero_ch1_1V",
    2: "zero_ch2_1V",
    3: "gain_ch1_1V",
    4: "gain_ch2_1V",
    5: "zero_uni",
    6: "gain_ch1_200mV",
    7: "gain_ch2_200mV",
    8: "gain_ch1_500mV",
    9: "gain_ch1_100mV",
    10: "gain_ch1_50mV",
    11: "gain_ch2_500mV",
    12: "gain_ch2_100mV",
    13: "gain_ch2_50mV",
    14: "zero_ch1_500mV",
    15: "zero_ch2_500mV",
    16: "zero_ch1_50mV",
    17: "zero_ch2_50mV",
    18: "zero_ch1_100mV",
    19: "zero_ch2_100mV",
}
