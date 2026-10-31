# CLAUDE.md

## このプロジェクト

SainSmart **DDS140**（USB オシロスコープ + 信号発生器モジュール）を macOS から
扱えるようにする。まず USB プロトコル（制御コマンドと波形データの取得）を把握し、
そのうえで CLI を作る。ハードと既知事項は `README.md` / `docs/`。

**現状（2026-10-31）: プロトコルは解明済み。macOS 用クライアント `dds140/` を実装し、
Windows 実機（`8312:8312`、手元の Windows 機）でキャプチャまで動作確認した。
macOS 実機での確認だけが残っている（デバイスは Windows 機に挿さっている）。**

- コマンドは制御転送 `bmRequestType=0x80` / `bRequest=cmd` / `wValue=引数` / `wLength=1`。
- 波形は EP `0x82` から **8bit × 2ch の交互配置**（`raw[0::2]` が CH1）。
- 開始 `cmd 51` → 状態 `cmd 80` が **33** になったら読む。
- 詳細と実測値は `docs/protocol.md`、割り方は `docs/reverse-engineering.md`。
- 入口は CLI（`python3 -m dds140 capture`）とブラウザ UI（`python3 -m dds140 ui`）。
  エージェント向けの要約は `skills/dds140-scope/SKILL.md`（`skills/install.sh` で
  Claude/Codex に登録。**SKILL.md を直したら install.sh を流し直す**）。
  UI は標準ライブラリの HTTP サーバ + canvas。USB に触るのはワーカースレッド 1 本だけ。
- フレーム先頭 2〜10 サンプルは整定で跳ねる（実測）。既定で `skip=16` で捨てる。
- **読み出し長は 32 KiB の倍数にする**。半端な長さは `libusb: Overflow` になる（実測）。
- 連続記録が成立するのは **240 kS/s だけ**（転送時間がデータ長と一致する）。
  39k/625k/100M は転送が速すぎて、実時間で連続かどうか未確認。`docs/recording.md`。

## 決定済みのこと

- **読み取り専用から始める。** descriptor 取得、EP の読み出し、制御転送の観測まで。
  EEPROM（24LC64I）への書き込み・ファームの差し替えはしない。
- **基板のジャンパ J1 を外さない。** 外すとファーム未ロードの `04b4:8613`
  （Cypress ブートローダ）で上がり、ベンダ FW を入れ直さないと動かない。
- プロトコルの一次資料は**ベンダ CD の中身**（`DDS140.exe` は .NET なので
  逆コンパイルでほぼ読める）。USBPcap は不要だった。実機検証は
  `tools/winprobe`（DLL を直接叩く C ハーネス）で行った。
- 波形データの解釈は**解明済み**。`DataPreDisposal()` は表示用の間引き
  （4 バイト/px）なので、macOS 実装では自前で処理する（再現不要）。
- キャリブレーション（ゼロ点・ゲイン）は**個体差があるので毎回 `cmd 144` で読む**。
  固定値を埋め込まない。

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
- `EP 0x82` は **Interrupt IN 1024B** で、**波形データはここ**（実測）。
  `0x86`/`0x88` は Bulk IN 512B だが、波形取得には使われていない。
  `0x04` は Bulk OUT（未使用）。
- 波形は **8bit × 2ch 交互**（`raw[0::2]` = CH1、`raw[1::2]` = CH2）。
  `0x82` から 32 KiB ずつ読む。
- 取得は非同期。ベンダ DLL は読み出し完了を待たないので、DLL を直接叩くときは注意。
  libusb の同期読み出しなら問題ない。
- 240 kS/s は status 33 まで**7 秒近く**かかる。待ち時間を短くしない。
- macOS で `set_configuration()` が `Resource busy` になる場合は、
  ベンダソフトや他プロセスが掴んでいる。`--no-claim` で descriptor だけ見る。
- 取得した波形には**測定対象の信号**が入りうる。`captures/` は Git 管理外。

## 次にやること

1. **macOS にデバイスを挿して `python3 -m dds140 info` / `capture` を確認**（最優先）。
2. 信号を入れてレンジ（2V〜50mV）と AC/DC の実減衰量を校正する。
3. 200 MS/s 合成モード（`cmd36` bit0）のデータ配置を確認する。
4. トリガ、ロジックアナライザ（`cmd 52/53`）、信号発生器（`cmd 99/112..125`）は未着手。
5. 信号発生器モジュールが付いているか確認する（付いていれば実機検証に進める）。

## 一次資料（ローカルに保全済み）

**マニュアルと配布ソフトは `vendor/` に保全してある**（Git 管理外）。
著作物なのでリポジトリには含めない。出典・SHA-256 は `docs/sources.md`、
検証は `tools/verify_archive.sh`。`vendor/` は消えると復元できない。

- ハード/ソフトのマニュアル: `vendor/manual/*.pdf`（秋月電子 g110159 で公開、原本は CD 同梱）
- ベンダ CD 全体: `vendor/101-10-144.rar` + 展開済みの `vendor/CD/`
- ベンダアプリは .NET。`vendor/CD/DDS140/DDS140.exe` を逆コンパイルすればコマンド列が読める。
- `vendor/CD/Demo/VCSource/` に**ベンダ提供の VC ソース**がある（publicDLL の使い方）。

## 外部の一次資料

- 秋月電子 商品ページ（販売終了）: https://akizukidenshi.com/catalog/g/g110159/
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
