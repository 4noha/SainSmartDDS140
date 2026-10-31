# 保全した資料と配布物

DDS140 は 2026 年時点でメーカー（SainSmart）の製品ページが終売、秋月電子でも
「販売終了」になっている。手元で動かし続けるために、**マニュアルと配布ソフトを
このリポジトリに保全**した。取得日: 2026-10-31。

## 1. マニュアル（Git 管理・再配布可）

`docs/manual/` に PDF と、`pdftotext` で起こしたテキストを置いてある
（テキストは grep 用。正確な図表は PDF を見ること）。

| ファイル | 出典 | SHA-256 | ページ |
|---|---|---|---|
| `DDS Series_Manual_Hardware-W.pdf` | 秋月電子 g110159 の「マニュアル(ハードウェア)」 | `7593c29f…44f9e` | 15 |
| `SainSmart DDS_Manual_Software.pdf` | 同上「マニュアル(ソフトウェア)」 | `a01b858…84337` | 27 |

- 商品ページ: <https://akizukidenshi.com/catalog/g/g110159/>
- 取得元 URL:
  - <https://akizukidenshi.com/goodsaffix/DDS%20Series_Manual_Hardware-W.pdf>
  - <https://akizukidenshi.com/goodsaffix/SainSmart%20DDS_Manual_Software.pdf>
- ベンダ CD（下記）に入っている同名 PDF と **SHA-256 が一致**することを確認済み。

## 2. 配布ソフト（`vendor/`・Git 管理外）

容量が大きいので `vendor/` に置き、Git には入れていない（`.gitignore` 済み）。
**このディレクトリが消えると復元できない**ので、必要なら別途バックアップを取ること。

| パス | 中身 | サイズ | SHA-256 |
|---|---|---|---|
| `vendor/101-10-144.rar` | 配布物の**オリジナル**（CD 全体のアーカイブ、81 エントリ） | 187 MB | `814921e2…45374` |
| `vendor/CD/` | 上記を展開した CD の中身（`.avi` を除く） | 65 MB | `vendor/SHA256SUMS` |
| `vendor/CD/DDS140/` | **Windows アプリ本体**（DDS140.exe / USBInterFace.dll / FFT.dll / publicDLL.dll / Appdef.dll / help.chm / config.set） | 3.6 MB | 同上 |
| `vendor/CD/DDS120/` | DDS120 用の同型アプリ（比較用） | 3.4 MB | 同上 |
| `vendor/CD/Demo/VCSource/` | **ベンダ提供の VC ソース**（`publicDLL.dll` の `GetData/SetData` の使い方） | — | 同上 |
| `vendor/CD/Driver_*` | Windows 用ドライバ（XP/Win7/Win8、64bit） | — | 同上 |
| `vendor/CD/DDS140/help/` | `help.chm` を `7z` で展開した HTML（検索用） | 5.5 MB | 同上 |

- 展開元: `C:\Users\<user>\Downloads\101-10-144.rar`（配布元の RAR）
- `vendor/CD/` からは `.avi`（インストール手順とデモ映像 5 本、合計 176 MB）を除いた。
  **映像も `101-10-144.rar` の中に完全な形で入っている**ので、必要なら
  `bsdtar -xf vendor/101-10-144.rar` で取り出せる。
- 参考: ベンダ CD のファイル数 62、合計 241,057,828 バイト（`.avi` 込み）。
- `vendor/dds140/`・`vendor/demo/` は解析用に取り出したコピー（`vendor/CD/` と同内容）。

### 検証

```sh
tools/verify_archive.sh          # vendor/SHA256SUMS を全部チェック
bsdtar -tf vendor/101-10-144.rar # アーカイブの中身一覧
```

## 3. マニュアルから分かったこと（実装に効いた点）

詳細は `docs/manual-notes.md`。要点だけ:

- DDS140 の **最大サンプルレートは 200 MS/s（1ch）/ 100 MS/s（2ch）**、
  メモリ深度 64 KB。← ベンダ広告の「200MS/s」は 1ch 時の値。
- **レンジごとのノイズ**が明記されている: 1V/div ±50 mV、200mV/div ±10 mV、
  100mV/div ±8 mV、50mV/div ±4 mV。入力が何も繋がっていないときの目安になる。
- **プローブは 1x / 10x / 100x** を設定で切り替える（物理プローブは 1x/10x 切替式）。
- ベンダソフトには **Record / Review 機能**があり、`.dds140` 形式で保存される。
- **トリガ**は No Trigger / Normal / Single / Auto、CH1/CH2、立ち上がり/立ち下がり。
- モジュール選択: Oscilloscope / Oscilloscope + Signal Generator / Logic Analyzer。

## 4. 注意

- `help.chm` の「Key Features」ページには「Max sample rate 50M SPS for each channel」
  「storage depth 4k byte」と書かれているが、これは **DDS120 系の値**が
  そのまま残っている可能性が高い（ハードウェアマニュアルの DDS-140 の値と矛盾する）。
  実装では実測を優先している（`docs/protocol.md`）。
- ベンダソフトの再配布はしない（`vendor/` は Git 管理外）。
  マニュアルは秋月電子が公開している PDF をそのまま置いている。
