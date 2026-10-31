# CLAUDE.md

## このプロジェクト

SainSmart **DDS140**（USB オシロスコープ + 信号発生器モジュール）を macOS から
扱えるようにする。まず USB プロトコル（制御コマンドと波形データの取得）を把握し、
そのうえで CLI を作る。ハードと既知事項は `README.md` / `docs/`。

**現状: 2026-10-31 に土台を作っただけ。実機は未接続（`8312:8312` は見えていない）。
`tools/usb_probe.py` は pyusb で書いたが、実機に対して未試験。**

## 決定済みのこと

- **読み取り専用から始める。** descriptor 取得、EP の読み出し、制御転送の観測まで。
  EEPROM（24LC64I）への書き込み・ファームの差し替えはしない。
- **基板のジャンパ J1 を外さない。** 外すとファーム未ロードの `04b4:8613`
  （Cypress ブートローダ）で上がり、ベンダ FW を入れ直さないと動かない。
- ベンダ DLL の挙動は **Windows 側で USBPcap + Wireshark** を採って把握する
  （macOS には USBPcap 相当が無い）。macOS 側は pyusb で同じ転送を再現する係。
- 波形データの解釈（`DataPreDisposal()` 相当）は**まだ誰も解いていない**。
  推測で実装しない。まず生データを採る。

## 前提の誤解に注意

- 「DDS140」は **AD9851 の DDS モジュール**とは別物。SainSmart には
  `AD9851 DDS Signal Generator Module` という別製品があり、混同しやすい。
- DDS140 は **USB オシロ**で、信号発生器は**後付けモジュール**。単体では出ていない。
- 公式ソフトは **Windows XP〜8 専用**。macOS/Linux 用は無い。
  **sigrok は対応していない**（status: Planned）。
- 通常時は EEPROM からファームが起動して `8312:8312`（BUUDAI / USB104）で見える。
  ファームを PC からアップロードしているわけではない。

## 開発時に効いてくる制約

- USB は **500mA** を申告する。バスパワーなので、ハブ経由で電圧が下がると
  列挙が不安定になる。直挿しで試す。
- **オシロ入力の定格**: 1x で ±5V、10x プローブで ±50V。測定対象を繋ぐ前に
  プローブの減衰設定と入力レンジを確認する。壊すと復旧できない。
- `EP 0x82` は **Interrupt IN 1024B**、`0x86`/`0x88` は Bulk IN 512B、
  `0x04` は Bulk OUT。読み出しは `0x86`/`0x88` を第一候補にする。
- macOS で `set_configuration()` が `Resource busy` になる場合は、
  ベンダソフトや他プロセスが掴んでいる。`--no-claim` で descriptor だけ見る。
- 取得した USB キャプチャには**測定対象の波形**が入りうる。`captures/` は Git 管理外。

## 最初に確認すること

1. 実機のリビジョン、J1 の有無、シルク（`USB104` / `BUUDAI` か）。
2. macOS で `8312:8312` が見えるか（`tools/usb_probe.py`）。
3. descriptor が sigrok の記録（4 EP / vendor specific）と一致するか。
4. Windows 機で USBPcap を採れるか（ベンダソフトの起動〜波形表示まで）。
5. 信号発生器モジュールが付いているか（付いていれば制御コマンドも採る）。

## 一次資料

- sigrok: https://sigrok.org/wiki/SainSmart_DDS140
- lsusb -v の生ログ: https://sigrok.org/wiki/SainSmart_DDS140/Info
- 既存のリバースエンジニアリング: https://github.com/SamantazFox/dds140-reverse-engineering
- ベンダ製品ページ（discontinued）:
  https://www.sainsmart.com/products/sainsmart-dds-140-40m-200m-s-virtual-oscilloscope-signal-generator

---

<!-- ここから下は project-setup スキルが貼った連携先の知識。要約せずそのまま置くこと。
     相手の API が変わったら追随が要る（各節の updated を参照） -->

# SainSmart DDS140（USB オシロ + 信号発生器）の前提

updated: 2026-10-31
正典: sigrok wiki（2020-09-26 版）と、そこから辿れる実測ログ。**手元の実機では未確認**。

## 何の装置か

- SainSmart **DDS140**。USB 接続の 2ch オシロスコープ。
  - 40MHz 帯域、200MS/s（1ch）/ 100MS/s（2ch）、8bit、64K メモリ。
  - オプションの**信号発生器モジュール**（矩形/三角/正弦/PWM、±4V、正弦 1Hz〜20MHz）と
    **ロジックアナライザ**（8ch、100MHz）を後付けできる。
- 公式ソフトは **Windows XP〜8 のみ**。macOS/Linux 用は無い。
- sigrok の対応状況は **Planned（未対応）**。既存の OSS ドライバは無い。

## USB（ここが一番効く）

| 状態 | VID:PID | 備考 |
|---|---|---|
| 通常（I²C EEPROM から FW 起動、基板ジャンパ **J1 あり**） | **`8312:8312`** | iManufacturer=`BUUDAI`, iProduct=`USB104` |
| FW 未ロード（**J1 を外した**状態） | `04b4:8613` | Cypress FX2LP の既定 ID（ブートローダ） |

通常状態の構成（1 interface、vendor specific、4 endpoint）:

| EP | 方向 | 転送 | サイズ |
|---|---|---|---|
| `0x82` | IN | Interrupt | 1024 B |
| `0x04` | OUT | Bulk | 512 B |
| `0x86` | IN | Bulk | 512 B |
| `0x88` | IN | Bulk | 512 B |

- `MaxPower 500mA`、セルフパワー表記。**PC の USB から給電**（AC アダプタは無い）。
- ドライバは WinUSB。ベンダ DLL が `WinUsb_ControlTransfer()` と `WinUsb_ReadPipe()` を
  ラップしている。

## 基板（実装部品）

- USB: **Cypress CY7C68013A-100AXC（FX2LP）**、24MHz 水晶
- EEPROM: Microchip **24LC64I**（64KB I²C）→ ここに FW が入っていて単体で起動する
- ADC: **MXTronix MXT2088** デュアル 8bit 100MSPS
- CPLD: **Altera MAX II EPM240T100CN**、80MHz 水晶
- SRAM: **ISSI IS61LV6416-8TI**（64K×16、8ns）
- アナログ: CD4052BM ×5（mux）、LM393（コンパレータ）、AMS1117-3.3
- 信号発生器基板: CD4052B、**AD603AR**（90MHz VGA）、AD826（オペアンプ）

## プロトコル

- 独自プロトコル。**1 バイトのコマンドコード（0〜255）+ 引数**を control transfer で送る。
- データ取得側（`WinUsb_ReadPipe` + `DataPreDisposal()`）は**まだ誰も解けていない**。
- 既存のリバースエンジニアリング:
  `https://github.com/SamantazFox/dds140-reverse-engineering`
  （`program/Commands_summary.rst` に判明したコマンド一覧。
  ミラー: `https://gitlab.com/SamantazFox/dds140-reverse-engineering`）
- sigrok のページ: `https://sigrok.org/wiki/SainSmart_DDS140`
  （lsusb -v の生ログは `/Info` サブページ）

## macOS で触るときの注意

- ベンダソフトは Windows 専用。**DLL の呼び出しを真似るには Windows 側で
  USBPcap + Wireshark** を取るのが早い（macOS には USBPcap 相当が無い）。
- pyusb + libusb で列挙・descriptor 取得・EP 読みはできる（実機未確認）。
- FX2LP は **ファームを書き換えられる**。J1 を外すと 04b4:8613 で上がる＝
  ブートローダ状態。**EEPROM の中身を消す/書く操作は復旧手段が無いのでしない**
  （ベンダ FW の再入手は公式 RAR のみ）。
