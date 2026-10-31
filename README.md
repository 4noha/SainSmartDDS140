# SainSmartDDS140

SainSmart **DDS140**（USB オシロスコープ、オプションで信号発生器・ロジックアナライザ）を
**macOS から**扱うための実装。公式ソフトは Windows XP〜8 専用なので、
USB プロトコルを自作のクライアントで再現した。

**現状: macOS 用クライアントは実装済み・Windows 実機で動作確認済み。
macOS 実機では未確認（デバイスが Windows 機に挿さっているため）。**

## まず使う

```sh
cd ~/works/tools/SainSmartDDS140

# デバイスが見えるか（descriptor と簡易自己診断）
python3 -m dds140 info

# 個体キャリブレーション値
python3 -m dds140 cal

# 1 フレーム取って統計 + CSV
python3 -m dds140 capture --samples 65536 -o wave.csv

# プロット（matplotlib がある場合）
python3 -m dds140 capture --samples 65536 --plot

# レンジとレートを指定
python3 -m dds140 capture --rate 10M --ch1 200mV --ch2 1V --ac1 --samples 8192 -o w.csv
```

依存: `pyusb` + `libusb-1.0`（macOS は brew の `libusb` が入っていれば OK）。
libusb の場所を明示したいときは `DDS140_LIBUSB=/path/to/libusb-1.0.dylib`。

## オシロとして何ができるか

| 機能 | 状態 |
|---|---|
| 2ch 同時取り込み（8 bit、CH1/CH2 交互） | ✅ 動作確認 |
| サンプルレート 100M / 10M / 625k / 240k / 39k | ✅ 動作確認（240k は待ちが長い） |
| 200 MS/s 合成モード | ⬜ 未対応（データ配置が未検証） |
| 垂直レンジ 2V/1V/500mV/200mV/100mV/50mV per div | ⚠️ コマンドは送信・応答確認。実減衰量は未校正 |
| AC/DC 結合（CH 単位） | ⚠️ コマンドは送信。波形での確認は未 |
| 個体キャリブレーション（ゼロ点・ゲイン） | ✅ 起動時に読み出して電圧換算に使用 |
| トリガ（ハード） | ⬜ 未対応（ベンダ GUI もソフト処理） |
| ロジックアナライザ（8ch） | ⬜ 未着手 |
| 信号発生器 | ⬜ コマンドは判明、未実装 |

出力: CSV（`time_s,ch1_v,ch2_v`）、生バイト（`--raw`）、
matplotlib ウィンドウ（`--plot`）。

## 中身

| パス | 内容 |
|---|---|
| `dds140/transport.py` | 制御転送（`0x80` vendor IN 1B）と EP `0x82` の読み出し |
| `dds140/const.py` | 実機で確認したコマンド・レート・レンジの表 |
| `dds140/scope.py` | キャリブレーション、設定、1 フレーム取得、電圧換算 |
| `dds140/cli.py` | `info` / `cal` / `capture` |
| `dds140/selftest.py` | 実機でレート・レンジを一通り試す（開発用） |
| `docs/protocol.md` | **プロトコルの全容（実測ベース）** |
| `docs/hardware.md` | 部品・USB 構成 |
| `docs/reverse-engineering.md` | どうやってプロトコルを割ったか（手順の記録） |
| `tools/usb_probe.py` | 汎用 USB 調査（列挙・descriptor・単発転送） |
| `tools/winprobe/` | Windows 実機で DLL を直接叩く検証ハーネス（C） |
| `tools/winproxy/` | ベンダ DLL の差し替えプロキシ（通信ログ用, 32bit DLL） |
| `tools/ghidra/` | 逆コンパイル用 Ghidra スクリプト |

## テスト

```sh
python3 -m unittest discover -s tests     # ハードウェア不要
python3 -m dds140.selftest                # 実機が必要（レート・レンジ総当たり）
```

## 制約（守ること）

- **読み取り専用から。** EEPROM（24LC64I）への書き込み、ファームの差し替えはしない。
  J1 を外すと `04b4:8613`（ブートローダ）になり、ベンダ FW を戻さないと動かない。
- **オシロ入力の定格**: 1x で ±5V、10x プローブで ±50V。繋ぐ前にレンジとプローブを確認。
- USB はバスパワー 500mA。ハブ経由で不安定なら直挿し。
- 波形には測定対象の信号が入る。`captures/` と `vendor/` は Git 管理外。

## 参考

- sigrok: <https://sigrok.org/wiki/SainSmart_DDS140>
- lsusb -v 生ログ: <https://sigrok.org/wiki/SainSmart_DDS140/Info>
- 既存の RE: <https://github.com/SamantazFox/dds140-reverse-engineering>
- ベンダ製品ページ（discontinued）:
  <https://www.sainsmart.com/products/sainsmart-dds-140-40m-200m-s-virtual-oscilloscope-signal-generator>
