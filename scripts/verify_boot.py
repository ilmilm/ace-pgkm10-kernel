#!/usr/bin/env python3
"""Verify a packed boot.img against the stock one.

usage: python3 verify_boot.py <stock_boot.img> <new_boot.img> <Image>
"""
import gzip
import hashlib
import struct
import sys

PAGE = 4096
PART = 67108864


def al(x, a=PAGE):
    return (x + a - 1) // a * a


ok = True


def chk(cond, msg):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    ok = ok and bool(cond)


def main():
    stock_p, new_p, img_p = sys.argv[1:4]
    s = open(stock_p, "rb").read()
    n = open(new_p, "rb").read()
    img = open(img_p, "rb").read()

    print("== size / header ==")
    chk(len(n) == PART, f"size == {PART}")
    chk(n[:8] == b"ANDROID!", "ANDROID! magic")
    nks, nrs, nosv, nhs = struct.unpack_from("<IIII", n, 8)
    sks, srs, sosv, shs = struct.unpack_from("<IIII", s, 8)
    chk((nosv, nhs) == (sosv, shs),
        f"os_version/header_size match stock (0x{nosv:08x}/{nhs})")

    # header_version lives at 0x28 (the old 5-tuple read grabbed reserved[0],
    # which is always 0 on both sides -> the check could never fail).
    nhv = struct.unpack_from("<I", n, 0x28)[0]
    shv = struct.unpack_from("<I", s, 0x28)[0]
    chk(nhv == shv, f"header_version match stock ({nhv})")
    nss = struct.unpack_from("<I", n, 0x1C)[0]
    sss = struct.unpack_from("<I", s, 0x1C)[0]
    chk(nss == sss == 0, f"no second stage (patched={nss} stock={sss})")

    hs, hn = bytearray(s[:PAGE]), bytearray(n[:PAGE])
    for buf in (hs, hn):
        struct.pack_into("<I", buf, 8, 0)
        struct.pack_into("<I", buf, 12, 0)
    chk(bytes(hs) == bytes(hn), "header identical except size fields")

    print("== kernel ==")
    k = n[PAGE:PAGE + nks]
    chk(k[:2] == b"\x1f\x8b", "kernel gzip")
    chk(k[:10][3] == 0x00, "gzip FLG=0x00 (factory style)")
    d = gzip.decompress(k)
    chk(d == img, f"gunzip(kernel) == built Image ({len(d)} bytes)")
    chk(d[:4] == b"\x4d\x5a\x00\x91", "ARM64 Image magic")

    print("== ramdisk ==")
    roff_n = PAGE + al(nks)
    rn = n[roff_n:roff_n + nrs]
    roff_s = PAGE + al(sks)
    rs = s[roff_s:roff_s + srs]
    chk(rn == rs, "ramdisk byte-identical to stock")

    print("== AVB ==")
    f = n[-64:]
    chk(f[:4] == b"AVBf", "footer magic")
    orig, vb_off, vb_size = struct.unpack_from(">QQQ", f, 12)
    vb = n[vb_off:vb_off + vb_size]
    chk(vb[:4] == b"AVB0", "vbmeta AVB0 magic")
    sf = s[-64:]
    sorig, svb_off, svb_size = struct.unpack_from(">QQQ", sf, 12)
    chk(vb == s[svb_off:svb_off + svb_size], "vbmeta byte-identical to stock")
    chk(vb_size == svb_size, f"vbmeta_size {vb_size} == stock {svb_size}")
    print(f"    original_image_size={orig} vbmeta_offset={vb_off} "
          f"vbmeta_size={vb_size}")

    print("== sha256 ==")
    print(f"    new  : {hashlib.sha256(n).hexdigest()}")
    print(f"    stock: {hashlib.sha256(s).hexdigest()}")
    print("\nRESULT:", "ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
