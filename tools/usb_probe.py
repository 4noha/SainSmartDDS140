#!/usr/bin/env python3
"""SainSmart DDS140 の USB を調べる（既定は読み取り専用）。

  python3 tools/usb_probe.py                 # DDS140 を探して descriptor を表示
  python3 tools/usb_probe.py --all           # USB 全部の VID:PID を一覧
  python3 tools/usb_probe.py --no-claim      # set_configuration せず descriptor だけ
  python3 tools/usb_probe.py --read 0x86 --count 4
  python3 tools/usb_probe.py --ctrl 0x01 --value 0 --length 64   # 制御転送 1 回

書き込みは `--write` を明示したときだけ（既定では行わない）。
"""
from __future__ import annotations

import argparse
import sys

try:
    import usb.core
    import usb.util
except ImportError:
    sys.exit("pyusb が必要です: /opt/homebrew/bin/python3.14 -m pip install pyusb")

KNOWN = {
    (0x8312, 0x8312): "DDS140 通常（EEPROM ファーム / BUUDAI USB104）",
    (0x04B4, 0x8613): "FX2LP ブートローダ（J1 を外した状態）",
}

XFER = {
    usb.util.ENDPOINT_TYPE_CTRL: "control",
    usb.util.ENDPOINT_TYPE_ISO: "isochronous",
    usb.util.ENDPOINT_TYPE_BULK: "bulk",
    usb.util.ENDPOINT_TYPE_INTR: "interrupt",
}


def safe_string(dev, index: int) -> str:
    if not index:
        return ""
    try:
        return usb.util.get_string(dev, index) or ""
    except Exception:
        return "<取得不可>"


def describe(dev) -> None:
    label = KNOWN.get((dev.idVendor, dev.idProduct), "unknown")
    print(f"\n{dev.idVendor:04x}:{dev.idProduct:04x}  {label}")
    print(f"  bus={dev.bus} addr={dev.address}  bcdUSB={dev.bcdUSB:#06x}  "
          f"class={dev.bDeviceClass:#04x}/{dev.bDeviceSubClass:#04x}/{dev.bDeviceProtocol:#04x}")
    mf = safe_string(dev, dev.iManufacturer)
    pr = safe_string(dev, dev.iProduct)
    se = safe_string(dev, dev.iSerialNumber)
    if mf or pr or se:
        print(f"  manufacturer={mf!r} product={pr!r} serial={se!r}")
    try:
        speed = dev.speed
        print(f"  speed={speed} ({'high' if speed == 3 else 'full' if speed == 2 else '?'})")
    except Exception:
        pass
    for ci, cfg in enumerate(dev.configurations() or []):
        attrs = cfg.bmAttributes
        powered = "self" if attrs & 0x40 else "bus"
        print(f"  config {cfg.bConfigurationValue}: {cfg.bNumInterfaces} interface(s) "
              f"{powered}-powered maxPower={cfg.bMaxPower * 2}mA")
        for intf in cfg:
            print(f"    interface {intf.bInterfaceNumber} alt={intf.bAlternateSetting} "
                  f"class={intf.bInterfaceClass:#04x}/{intf.bInterfaceSubClass:#04x}/"
                  f"{intf.bInterfaceProtocol:#04x}")
            for ep in intf:
                d = "IN " if usb.util.endpoint_direction(ep.bEndpointAddress) else "OUT"
                t = XFER.get(usb.util.endpoint_type(ep.bmAttributes), "?")
                print(f"      EP {ep.bEndpointAddress:#04x} {d} {t:<11} {ep.wMaxPacketSize}B")


def find_devices(all_devices: bool):
    out = []
    for dev in usb.core.find(find_all=True):
        if all_devices or (dev.idVendor, dev.idProduct) in KNOWN:
            out.append(dev)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="DDS140 の USB 調査（既定は読み取り専用）")
    ap.add_argument("--all", action="store_true", help="既知の VID:PID 以外も表示")
    ap.add_argument("--no-claim", action="store_true",
                    help="set_configuration / claim を行わない（他プロセスが使用中でも可）")
    ap.add_argument("--read", metavar="EP", help="IN エンドポイントから読む（例 0x86）")
    ap.add_argument("--count", type=int, default=1, help="読み出し回数")
    ap.add_argument("--timeout", type=int, default=1000, help="ms")
    ap.add_argument("--write", metavar="EP", help="OUT エンドポイントへ書く（明示時のみ）")
    ap.add_argument("--data", help="--write のデータ（hex 文字列 例 0102ff）")
    ap.add_argument("--ctrl", metavar="BREQUEST", help="制御転送の bRequest（16進/10進）")
    ap.add_argument("--bm", default="0x40", help="bmRequestType（既定 0x40 = vendor, host→device）")
    ap.add_argument("--value", default="0", help="wValue")
    ap.add_argument("--index", default="0", help="wIndex")
    ap.add_argument("--length", type=int, default=0, help="IN のときの読み出し長")
    args = ap.parse_args()

    devs = find_devices(args.all)
    if not devs:
        print("DDS140（8312:8312）が見つかりません。\n"
              "  - 実機を直挿しする（ハブ経由だと電圧降下で落ちることがある）\n"
              "  - J1 を外した状態なら 04b4:8613 で見える\n"
              "  - --all で他の VID:PID も確認する", file=sys.stderr)
        return 2

    for dev in devs:
        describe(dev)
        if (dev.idVendor, dev.idProduct) not in KNOWN:
            continue

        if args.read or args.write or args.ctrl:
            if args.no_claim:
                print("  ! --no-claim と転送系は併用できません", file=sys.stderr)
                continue
            try:
                dev.set_configuration()
                usb.util.claim_interface(dev, 0)
            except Exception as e:
                print(f"  ! 設定/claim に失敗: {e}\n"
                      "    他プロセスが掴んでいないか確認（--no-claim で descriptor のみ可）",
                      file=sys.stderr)
                continue

        if args.read:
            ep = int(args.read, 0)
            for i in range(max(1, args.count)):
                try:
                    data = dev.read(ep, 4096, timeout=args.timeout)
                    print(f"  read#{i} {ep:#04x} {len(data)}B: {bytes(data)[:64].hex()}")
                except Exception as e:
                    print(f"  read#{i} {ep:#04x} 失敗: {type(e).__name__}: {e}")
                    break

        if args.write:
            ep = int(args.write, 0)
            if not args.data:
                print("  ! --write には --data <hex> が必要です", file=sys.stderr)
            else:
                payload = bytes.fromhex(args.data)
                try:
                    n = dev.write(ep, payload, timeout=args.timeout)
                    print(f"  write {ep:#04x} {payload.hex()} -> {n}B")
                except Exception as e:
                    print(f"  write 失敗: {type(e).__name__}: {e}")

        if args.ctrl:
            req = int(args.ctrl, 0)
            bm = int(args.bm, 0)
            val = int(args.value, 0)
            idx = int(args.index, 0)
            try:
                if bm & 0x80:                     # device -> host
                    res = dev.ctrl_transfer(bm, req, val, idx, args.length,
                                            timeout=args.timeout)
                    print(f"  ctrl {bm:#04x} req={req:#04x} -> {len(res)}B: "
                          f"{bytes(res)[:64].hex()}")
                else:
                    payload = bytes.fromhex(args.data) if args.data else b""
                    res = dev.ctrl_transfer(bm, req, val, idx, payload,
                                            timeout=args.timeout)
                    print(f"  ctrl {bm:#04x} req={req:#04x} {payload.hex()} -> {res}")
            except Exception as e:
                print(f"  ctrl 失敗: {type(e).__name__}: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
