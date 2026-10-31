# どうやってプロトコルを割ったか（再現手順の記録）

2026-10-31 に、実機が挿さっている Windows 機（`nokki@192.168.0.12`, host `n100box`,
Windows 11 22H2, 管理者）へ SSH して進めた。**同じことをやり直すときはこの順で。**

## 0. 前提の確認

```sh
ssh nokki@192.168.0.12 'powershell -NoProfile -Command "Get-PnpDevice -PresentOnly | ? { $_.InstanceId -like ''USB\VID_*'' }"'
```

`USB\VID_8312&PID_8312` = `USB104` が **USBDevice クラス**（= WinUSB ドライバ）で
見えていれば、ベンダソフトが動く状態。`04b4:8613` なら J1 が外れている。

## 1. ベンダソフトの素性を確認

`DDS140.exe` は **.NET**（`mscoree.dll` しか import していない）。これが決定的だった。
ネイティブの Win32 アプリだと Ghidra で追う必要があるが、.NET なら
`ilspycmd` でほぼ元の C# に戻る。

```sh
x86_64-w64-mingw32-objdump -p DDS140.exe | grep "DLL Name"   # => mscoree.dll
DOTNET_ROLL_FORWARD=LatestMajor ilspycmd -o /tmp/dds_cs DDS140.exe
```

（`ilspycmd` は .NET 6 向けなので、.NET 9 しか無い環境では
`DOTNET_ROLL_FORWARD=LatestMajor` が要る。）

関連 DLL も同様に:

- `Appdef.dll` … `DefLibrary`。`g_snCOMAppRes == 1` が **DDS140/240**、`2` が DDS120。
  よって DDS140 では **`_104` 付きのメソッド群が有効**（`_102` は DDS120 用の死んだコード）。
- `FFT.dll` … `OSC_Control` / `Logic_Control` / `Knob_Control`。描画とデータ解釈。
- `USBInterFace.dll` … WinUSB ラッパ（ネイティブ 32bit）。ここだけ Ghidra。

## 2. コマンド層を読む

`DDS140.exe` の中で `MyDLLImport.USBCtrlTrans(cmd, value, 1)` を検索すれば全部出る。
実測で確かめた対応（詳細は `docs/protocol.md`）:

- 34/35 = CH1/CH2 減衰器、36/148 = ビット設定（結合・レート）、144 = キャリブレーション、
  51 = 開始、80 = 状態（33 で準備完了）、231 = トリガ源。

`USBInterFace.dll` を Ghidra で見ると `USBCtrlTrans` は
`WinUsb_ControlTransfer(handle, {0x80, bRequest, wValue, 0, 1}, &buf, 1, &n, 0)` で、
**1 バイト読み戻す**だけの関数だと分かる。

```sh
analyzeHeadless /tmp/ghproj dds -import USBInterFace.dll \
  -scriptPath tools/ghidra -postScript DumpDecomp.java /tmp/usbiface.c
```

`AiReadBulkData` が OVERLAPPED 付き `WinUsb_ReadPipe` を投げっぱなしにしていて、
完了待ちは `EventCheck`（`WaitForMultipleObjects`）側、というのもここで分かった。
**この非同期性は実測時にも罠になった**（読み出し直後にバッファを見ると前のフレームが残っている）。

## 3. データ形式の確定

`DataPreDisposal()`（ネイティブ）を読むと、生バッファを

```
ch1 = *(p + i*2);  ch2 = *(p + i*2 + 1);
```

の形で読んでいた。つまり **8 bit × 2ch 交互配置**。
さらに `FFT.dll` の `DrawChannel` が `pGraphNativeMem[m_TrigIndex + i]` で
1 バイトずつ参照している（= チャネルごとの配列は DLL が間引き後に作る表示用）。

実測でも裏が取れた: 無入力時、CH1 の値が `cmd 144` の
`zero_ch1_1V = 117` にほぼ一致し、CH2 は `zero_ch2_1V = 120` 付近。

## 4. 実機で叩いて確かめる

GUI は session 0 で起動してもデバイス到着イベントが来ず、自動取得が始まらない。
なので **GUI を使わず、DLL を直接叩く C ハーネス**を書いた（`tools/winprobe/probe.c`）。

- `i686-w64-mingw32-gcc -O2 -o probe.exe probe.c -static` でクロスコンパイル
- 元の `USBInterFace.dll` を `USBInterFace_real.dll` にリネームして `LoadLibrary`
- `DeviceOpen` → キャリブレーション → 設定 → 51 → 80 ポーリング → `AiReadBulkData`

これで「コマンドが通る」「データが返る」「交互配置」が一気に確認できた。

### GUI の通信をそのまま記録したいとき

`tools/winproxy/` のプロキシ DLL（32bit）を `USBInterFace.dll` として置き、
本物を `USBInterFace_real.dll` にリネームすれば、全呼び出しが
`usb_proxy.log` に落ちる。**GUI が実際に取得を始めたときだけ**ログが出るので、
GUI のスタートボタンを押せる状況で使う。

## 5. macOS 実装

同じコードを Python（pyusb）で書き直した（`dds140/`）。
Windows 上でも pyusb + `libusb_package` の DLL で**同一コードが動く**ので、
Windows 実機で検証してから macOS に持っていける。

Windows で手早く試すための最小構成（インストーラ不要）:

```
python-3.12.x-embed-amd64.zip を展開（python312._pth に libs を追記）
pyusb と libusb_package の wheel を展開
set DDS140_LIBUSB=<...>\libusb_package\libusb-1.0.dll
python.exe -m dds140 info
```

## 罠メモ

- 初回フレームで `0xAA`（memset の残り）が返ってきた → 非同期読み出しの完了待ち漏れ。
- 240 kS/s は status 33 まで **6.8 秒**かかる。5 秒で諦めると失敗する。
- `scp` で Windows のパスに空白があるとき、二重クォートすると失敗する。
  OpenSSH 9 以降は SFTP モードなのでクォート無しで渡すのが正解。
- ベンダ GUI を SSH から起動しても、USB 到着通知が来ないので取得は始まらない。
  デバイスを無効化→有効化（`pnputil`）しても通知は来なかった。
