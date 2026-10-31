# プロトコル（既知 / 未知）

## 既知

- **コマンドは 1 バイト（0〜255）+ 引数**。USB の **control transfer** で送る。
  （ベンダ DLL の `USBCtrlTransSimple()` / `USBCtrlTrans()` が
  `WinUsb_ControlTransfer()` のラッパ）
- 波形データは **`WinUsb_ReadPipe()`** で読む（EP `0x86` / `0x88` が候補）。
- 取得後の `DataPreDisposal()` が GUI のズーム・位置に依存した前処理をする。
  **この中身が未解明** = 生データをそのままプロットしても波形にならない可能性が高い。
- 判明しているコマンドの一覧（第三者）:
  <https://github.com/SamantazFox/dds140-reverse-engineering/blob/master/program/Commands_summary.rst>

## 未知

| 項目 | 状態 |
|---|---|
| control transfer の bmRequestType / wValue / wIndex の意味 | 未解明 |
| サンプリング開始・停止のコマンド列 | 未解明 |
| EP `0x86` / `0x88` / `0x82` の役割分担 | 未解明（3 本の IN の使い分け） |
| 波形データのヘッダ有無・エンディアン・チャンネル交互配置 | 未解明 |
| 電圧 → コードの変換（8bit、レンジ切替） | 未解明 |
| 信号発生器モジュールのコマンド | 未解明 |

## 進め方

1. **Windows 実機で USBPcap + Wireshark** を採る。
   - ベンダソフト起動 → デバイス認識 → 1ch 表示 → 2ch 表示 → 停止
   - 操作ごとにキャプチャを分ける（あとで差分が取れる）
2. 制御転送だけを抜き出して**コマンド列**にする（同じ操作を 2 回やって
   再現するか確認）。
3. macOS 側で `tools/usb_probe.py --ctrl` により**同じ転送を 1 つずつ再現**し、
   EP の応答が一致するかを見る。
4. `--read` で生データを取り、ヘッダの周期・繰り返しから形式を推定する。
5. 推定が当たったら CLI（`dds140 scope --ch 1 --samples 10000`）にする。

## やってはいけないこと

- EEPROM への書き込み（`0x24LC64I`）。復旧手段が無い。
- 未確認のコマンドを総当たりで送る（設定が飛ぶと Windows ソフトでも戻せない）。
  1 つ送るごとにキャプチャと応答を残す。
- `DataPreDisposal()` を推測で再実装して「波形が出た」と主張すること。
  生データと、ベンダソフトの画面を並べて一致を確認する。
