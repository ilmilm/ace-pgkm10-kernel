#!/usr/bin/env python3
"""String xref for MTK LK sub-images (payload starts at file offset 0x200).

The sub-image header is 0x200 bytes, so the payload is loaded at a page-aligned
address while its first byte sits at file offset 0x200.  That constant offset
skews every adrp page; the correction depends on the instruction's own page
offset:

    s = P + A + 0x200        if (code_offset & 0xfff) >= 0x200
    s = P + A - 0xe00        if (code_offset & 0xfff) <  0x200

where P is the page address capstone prints for `adrp` and A the `add` immediate.
Verified on 'Orange State' (code 0x5f2d4 -> string 0xca9cd).

usage: python3 lkxref.py lk.bin "Orange State" "img_auth_required"
"""
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from capstone.arm64 import ARM64_OP_REG, ARM64_OP_IMM

CODE_START = 0x200


def fix(c, P, A):
    return (P + A - 0xE00) if (c & 0xFFF) < 0x200 else (P + A + 0x200)


def main():
    path = sys.argv[1]
    needles = [n.encode() for n in sys.argv[2:]]
    d = open(path, "rb").read()

    targets = {}
    for n in needles:
        off = 0
        while True:
            i = d.find(n, off)
            if i < 0:
                break
            targets.setdefault(i, []).append(n.decode("latin1"))
            off = i + 1

    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    md.skipdata = True
    md.detail = True
    ins = list(md.disasm(d[CODE_START:], CODE_START))
    print(f"{path}: {len(ins)} insns, {len(targets)} string offsets")

    hits = {}
    for i, x in enumerate(ins):
        if x.mnemonic != "adrp" or len(x.operands) < 2:
            continue
        if x.operands[1].type != ARM64_OP_IMM:
            continue
        reg = x.reg_name(x.operands[0].reg)
        P = x.operands[1].imm
        for j in range(i + 1, min(i + 4, len(ins))):
            y = ins[j]
            if y.mnemonic != "add" or len(y.operands) != 3:
                if y.mnemonic in ("adrp", "b", "bl", "br", "ret", "cbz", "cbnz"):
                    break
                continue
            o0, o1, o2 = y.operands
            if (o0.type == ARM64_OP_REG and o1.type == ARM64_OP_REG
                    and o2.type == ARM64_OP_IMM
                    and y.reg_name(o0.reg) == reg
                    and y.reg_name(o1.reg) == reg):
                s = fix(x.address, P, o2.imm)
                if s in targets:
                    hits.setdefault(s, []).append(x.address)
                break

    for s in sorted(hits):
        for name in targets[s]:
            addrs = ", ".join(f"0x{a:06x}" for a in sorted(set(hits[s])))
            print(f"  str 0x{s:06x} {name!r}\n    <- {addrs}")


if __name__ == "__main__":
    main()
