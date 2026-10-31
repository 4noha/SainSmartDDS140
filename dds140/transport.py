"""USB 転送層（pyusb / libusb-1.0）。macOS でも Windows でも同じコードで動く。

実機で確認した転送は 2 種類だけ:

  1. 制御転送（コマンド）
       bmRequestType = 0x80  (device -> host, vendor, device)
       bRequest      = コマンド番号
       wValue        = 引数（16bit）
       wIndex        = 0
       wLength       = 1     (常に 1 バイト読み戻す)
     戻り値は「エコー」または「データ」。cmd 144 だけはキャリブレーション値が返る。

  2. EP 0x82 からの読み出し（波形）
       ベンダ GUI は 32 KiB ずつ WinUsb_ReadPipe を投げる。
"""
from __future__ import annotations

import time

import usb.backend.libusb1
import usb.core
import usb.util

from . import PRODUCT_ID, VENDOR_ID
from .const import CHUNK_BYTES, EP_DATA

BM_REQUEST = 0x80


def _backend():
    """libusb の場所を解決する。

    優先順位:
      1. 環境変数 DDS140_LIBUSB（libusb-1.0 の dylib/DLL へのパス）
      2. libusb_package（pip で入れた libusb 同梱パッケージ）
      3. システムの libusb（macOS は brew の /opt/homebrew/lib 等）
    """
    import os

    path = os.environ.get("DDS140_LIBUSB")
    if not path:
        try:
            import libusb_package
            path = libusb_package.get_library_path()
        except Exception:
            path = None
    if path:
        return usb.backend.libusb1.get_backend(find_library=lambda x: path)
    return usb.backend.libusb1.get_backend()


class DeviceNotFound(RuntimeError):
    pass


class Transport:
    def __init__(self, device=None, timeout=1000):
        self.dev = device
        self.timeout = timeout
        self.interface = 0
        self._claimed = False
        self._detached = False
        self._old_config = None

    # ------------------------------------------------------------- open / close
    @classmethod
    def open(cls, timeout=1000, verbose=False):
        dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID, backend=_backend())
        if dev is None:
            raise DeviceNotFound(
                "DDS140 (8312:8312) が見つかりません。\n"
                "  - USB を直挿しする（バスパワー 500mA。ハブ経由は不安定）\n"
                "  - J1 を外した基板は 04b4:8613（ブートローダ）で見える\n"
                "  - 他プロセスが掴んでいないか確認"
            )
        self = cls(dev, timeout=timeout)
        self._setup(verbose=verbose)
        return self

    def _setup(self, verbose=False):
        try:
            self._old_config = self.dev.get_active_configuration().bConfigurationValue
        except usb.core.USBError:
            self._old_config = None

        try:
            self.dev.set_configuration()
        except usb.core.USBError as e:
            # macOS では既に構成済みだと Resource busy になることがある。
            # その場合はそのまま claim に進む。
            if verbose:
                print(f"  set_configuration: {e} (続行)")

        # ベンダ固有 interface にカーネルドライバが付いていることは通常ないが、
        # 念のため外せるなら外す（外した場合は close で戻す）。
        try:
            if self.dev.is_kernel_driver_active(self.interface):
                self.dev.detach_kernel_driver(self.interface)
                self._detached = True
        except (usb.core.USBError, NotImplementedError):
            pass

        usb.util.claim_interface(self.dev, self.interface)
        self._claimed = True

    def close(self):
        if self._claimed:
            try:
                usb.util.release_interface(self.dev, self.interface)
            except usb.core.USBError:
                pass
            self._claimed = False
        if self._detached:
            try:
                self.dev.attach_kernel_driver(self.interface)
            except usb.core.USBError:
                pass
            self._detached = False
        try:
            usb.util.dispose_resources(self.dev)
        except usb.core.USBError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------------ commands
    def cmd(self, request: int, value: int = 0) -> int:
        """制御転送を 1 回。返り値は読み戻した 1 バイト。"""
        res = self.dev.ctrl_transfer(
            BM_REQUEST, request, value, 0, 1, timeout=self.timeout
        )
        return int(res[0]) if len(res) else -1

    def reset_pipe(self):
        """EP 0x82 のストールを解く（エラー時のみ）。"""
        try:
            self.dev.clear_halt(EP_DATA)
        except usb.core.USBError:
            pass

    # --------------------------------------------------------------------- data
    def flush(self, max_rounds: int = 64) -> int:
        """EP 0x82 に残っているデータを捨てる（短いタイムアウトで読む）。"""
        dropped = 0
        for _ in range(max_rounds):
            try:
                got = self.dev.read(EP_DATA, CHUNK_BYTES, timeout=1)
            except usb.core.USBError:
                break
            if not got:
                break
            dropped += len(got)
        return dropped

    def read_frame(self, total_bytes: int, chunk_bytes: int = CHUNK_BYTES,
                   timeout: int | None = None) -> bytes:
        """EP 0x82 から total_bytes 読む。ベンダ GUI と同じく 32 KiB ずつに分ける。

        実機のクセ: 読み出し長が 32 KiB の倍数でないと、末尾の半端な要求で
        `libusb: Overflow` になる（240k で実測）。そのため 32 KiB 単位に
        切り上げて読み、余分は捨てる。
        """
        timeout = timeout or self.timeout
        padded = -(-int(total_bytes) // chunk_bytes) * chunk_bytes
        buf = bytearray()
        while len(buf) < padded:
            want = min(chunk_bytes, padded - len(buf))
            try:
                got = self.dev.read(EP_DATA, want, timeout=timeout)
            except usb.core.USBError as e:
                # 取りこぼし（Overflow/Overrun）でも、読めた分は返す
                self.reset_pipe()
                if len(buf) >= total_bytes:
                    break
                raise IOError(
                    f"読み出し失敗（{len(buf)}/{total_bytes} バイト受信）: {e}"
                ) from e
            if not got:
                break
            buf += bytes(got)
        return bytes(buf[:total_bytes])


def drain(seconds: float = 0.02, dev=None, ep=EP_DATA) -> int:
    """読み残しを捨てる（次のフレームと混ざるのを防ぐ）。"""
    n = 0
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            n += len(dev.read(ep, 65536, timeout=1))
        except usb.core.USBError:
            break
    return n
