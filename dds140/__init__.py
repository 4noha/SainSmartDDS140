"""DDS140 (SainSmart USB oscilloscope) を macOS から扱うためのパッケージ。

プロトコルの出どころ:
  - ベンダ CD の DDS140.exe（.NET）を逆コンパイルして得たコマンド列
  - USBInterFace.dll（WinUSB ラッパ）の静的解析
  - 実機（Windows, 8312:8312）に対する tools/winprobe での実測

詳細は docs/protocol.md を参照。
"""

__version__ = "0.1.0"

VENDOR_ID = 0x8312
PRODUCT_ID = 0x8312
