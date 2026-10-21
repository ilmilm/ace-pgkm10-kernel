#!/usr/bin/env python3
"""Pack the rebuilt kernel into boot.img for OnePlus Ace (PGKM10).

Keeps the FACTORY-SIGNED vbmeta blob verbatim and only relocates it, which is
what makes LK accept the image shape (avbtool --algorithm NONE produces an
unsigned structure that makes the device loop at the first logo).

usage:  python3 pack_boot.py <stock_boot.img> <Image> <out_boot.img>
"""
import hashlib
import struct
import sys
import zlib

PAGE = 4096
PART = 67108864


def al(x, a=PAGE):
    return (x + a - 1) // a * a


def gz_pure(raw, level=9):
    """gzip with FLG=0x00, XFL=2, OS=3 — byte-identical header style to stock."""
    co = zlib.compressobj(level, zlib.DEFLATED, -zlib.MAX_WBITS, 9)
    body = co.compress(raw) + co.flush()
    hdr = b"\x1f\x8b\x08\x00" + struct.pack("<I", 0) + b"\x02\x03"
    return hdr + body + struct.pack("<II", zlib.crc32(raw) & 0xffffffff,
                                    len(raw) & 0xffffffff)


def main():
    stock_p, img_p, out_p = sys.argv[1:4]
    stock = open(stock_p, "rb").read()
    raw = open(img_p, "rb").read()

    assert stock[:8] == b"ANDROID!", "not a boot image"
    ks, rs = struct.unpack_from("<II", stock, 8)
    print(f"stock: kernel_size={ks} ramdisk_size={rs}")

    # stock kernel may already be gzip; if our input is a raw Image, compress
    if raw[:2] == b"\x1f\x8b":
        kernel = raw
        # normalise header to factory style
        if raw[3] != 0x00:
            import gzip
            kernel = gz_pure(gzip.decompress(raw))
    else:
        kernel = gz_pure(raw)
    print(f"kernel gz: {len(kernel)} head={kernel[:10].hex(' ')}")

    roff = PAGE + al(ks)
    ramdisk = stock[roff:roff + rs]

    # AVB footer: BE u64 at +12 / +20 / +28
    fin = stock[-64:]
    assert fin[:4] == b"AVBf", "no AVB footer"
    orig, vb_off, vb_size = struct.unpack_from(">QQQ", fin, 12)
    vbmeta = stock[vb_off:vb_off + vb_size]
    assert vbmeta[:4] == b"AVB0", "stock vbmeta magic missing"
    print(f"stock AVB: orig={orig} vbmeta_off={vb_off} size={vb_size}")

    content = bytearray(stock[:PAGE])
    content += kernel
    content += b"\x00" * (al(len(content)) - len(content))
    struct.pack_into("<I", content, 8, len(kernel))
    content += ramdisk
    content += b"\x00" * (al(len(content)) - len(content))
    struct.pack_into("<I", content, 12, len(ramdisk))
    content_end = len(content)
    print(f"content_end=0x{content_end:x}")

    out = bytearray(content)
    new_vb = content_end
    out += vbmeta
    if len(out) > PART - 64:
        raise SystemExit("content exceeds partition size")
    out += b"\x00" * (PART - 64 - len(out))

    footer = bytearray(64)
    footer[0:4] = b"AVBf"
    struct.pack_into(">I", footer, 4, 1)
    struct.pack_into(">I", footer, 8, 0)
    struct.pack_into(">Q", footer, 12, content_end)
    struct.pack_into(">Q", footer, 20, new_vb)
    struct.pack_into(">Q", footer, 28, len(vbmeta))
    out += footer
    assert len(out) == PART

    open(out_p, "wb").write(out)
    print(f"wrote {out_p} sha256={hashlib.sha256(out).hexdigest()}")


if __name__ == "__main__":
    main()
