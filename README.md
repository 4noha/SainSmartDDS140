# SainSmartDDS140

SainSmart **DDS140**（USB オシロスコープ、オプションで信号発生器・ロジックアナライザ）を
**macOS から**扱うための作業場。公式ソフトは Windows XP〜8 専用なので、USB プロトコルを
自分で把握して CLI を作る。

## 対象ハードウェア

| 項目 | 内容 |
|---|---|
| 筐体 | DDS140（USB オシロ、2ch、40MHz、200MS/s、8bit、64K） |
| USB 側 | Cypress **FX2LP CY7C68013A** + 24LC64I EEPROM（ファームはここ） |
| ADC | MXTronix **MXT2088**（デュアル 8bit 100MSPS） |
| ロジック | Altera **EPM240T100CN**（MAX II CPLD） |
| メモリ | ISSI **IS61LV6416**（64K×16 SRAM） |
| VID:PID | 通常 **`8312:8312`**（BUUDAI / USB104）／ J1 無しは `04b4:8613` |
| 信号発生器 | 後付けモジュール（AD603 + AD826 + CD4052）。正弦 1Hz〜20MHz、±4V |

## できること（現時点で用意したもの）

- `tools/usb_probe.py`
  - 接続中の DDS140 を探して descriptor を表示（設定・インターフェース・EP）
  - `--read 0x86` で EP から読み出し（読み取り専用）
  - `--ctrl` で制御転送を 1 回だけ送る（引数を明示したときだけ）
- `docs/hardware.md`（部品・USB 構成）と `docs/protocol.md`（既知/未知の切り分け）
- `captures/`（USBPcap の pcapng 置き場、Git 管理外）

## セットアップ

```sh
# 依存（すでに入っている）
/opt/homebrew/bin/python3.14 -c "import usb; print(usb.__version__)"

# 実機を挿して列挙
python3 tools/usb_probe.py

# descriptor だけ（他プロセスが掴んでいても可）
python3 tools/usb_probe.py --no-claim

# EP 0x86 から 4 回読む（読み取り専用）
python3 tools/usb_probe.py --read 0x86 --count 4
```

## 使い方の例

```
$ python3 tools/usb_probe.py
8312:8312  BUUDAI USB104  bus=1 addr=7
  config 1: 4 endpoints
    EP 0x82 IN  interrupt 1024B
    EP 0x04 OUT bulk      512B
    EP 0x86 IN  bulk      512B
    EP 0x88 IN  bulk      512B
```

（実機が無いので、この出力は**記録から作った期待値**。実機で確認すること。）

## 制約

- **読み取り専用から。** EEPROM（24LC64I）への書き込み、ファームの差し替えはしない。
  J1 を外すと `04b4:8613`（ブートローダ）になり、ベンダ FW を戻さないと動かない。
- オシロ入力の定格は 1x で ±5V、10x プローブで ±50V。**繋ぐ前にレンジを確認**。
- USB はバスパワー 500mA。ハブ経由で不安定になるなら直挿し。
- 波形データの解釈アルゴリズム（ベンダ DLL の `DataPreDisposal()`）は未解明。
  推測で実装しない。

## 現状

| 項目 | 状態 |
|---|---|
| プロジェクト土台 | ✅ 2026-10-31 |
| USB 列挙・descriptor 表示 | 実装済み（実機未試験） |
| EP 読み出し | 実装済み（実機未試験） |
| 制御コマンドの再現 | 未着手（Windows 側の USBPcap 待ち） |
| 波形データのデコード | 未着手（既存情報なし） |
| 信号発生器の制御 | 未着手 |

## 参考リンク

- sigrok: <https://sigrok.org/wiki/SainSmart_DDS140>
- lsusb -v の生ログ: <https://sigrok.org/wiki/SainSmart_DDS140/Info>
- 既存の RE プロジェクト: <https://github.com/SamantazFox/dds140-reverse-engineering>
- ベンダ製品ページ: <https://www.sainsmart.com/products/sainsmart-dds-140-40m-200m-s-virtual-oscilloscope-signal-generator>
