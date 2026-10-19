#!/usr/bin/env bash
# =============================================================================
# OnePlus Ace (PGKM10 / OP5565 / MT6895) builtin KernelSU + SuSFS
#
# Target : ColorOS 15.0.0.1800 (CN01), kernel 5.10.236-android12-9
# Source : OnePlusOSS mt6895, branch oneplus/mt6895_v_15.0.0_ace
#
# Verified on the device: LTO_CLANG_FULL / CFI_CLANG / CFI_CLANG_SHADOW /
# SHADOW_CALL_STACK / KASAN_HW_TAGS / MODVERSIONS are all =y in the stock
# config.  If any of them silently disappears during olddefconfig the build
# is useless: every vendor module CRC changes.
#
# usage: bash build_ace_kernel.sh <OP dir>
#   env TC = path to clang-r416183b
# =============================================================================
set -euo pipefail

OP=${1:?usage: build_ace_kernel.sh <OP dir>}
K=$OP/kernel
M=$OP/modules
S=$OP/susfs510
SU=$OP/sukisu
O=$OP/kout
HERE=$(cd "$(dirname "$0")/.." && pwd)
BRANCH=${BRANCH:-oneplus/mt6895_v_15.0.0_ace}
TC=${TC:-$OP/toolchain/clang}

log() { printf '\n=== %s ===\n' "$*"; }

export PATH=$TC/bin:$PATH
export ARCH=arm64 LLVM=1 LLVM_IAS=1
export CROSS_COMPILE=aarch64-linux-gnu-
export CLANG_TRIPLE=aarch64-linux-gnu-

for t in clang ld.lld llvm-nm llvm-ar llvm-objcopy llvm-objdump llvm-readelf llvm-strip; do
  command -v "$t" >/dev/null || { echo "FATAL: $t not in PATH" >&2; exit 1; }
done
log "toolchain"; clang --version | head -2

# ------------------------------------------------------------------- sources
mkdir -p "$OP"
log "sources"
[ -d "$K/.git" ]  || git clone -b "$BRANCH" --depth 1 \
  https://github.com/OnePlusOSS/android_kernel_5.10_oneplus_mt6895 "$K"
[ -d "$M/.git" ]  || git clone -b "$BRANCH" --depth 1 \
  https://github.com/OnePlusOSS/android_vendor_mediatek_kernel_modules_mt6895 "$M"
[ -d "$S/.git" ]  || git clone -b gki-android12-5.10 --depth 1 \
  https://github.com/ShirkNeko/susfs4ksu "$S"
if [ ! -d "$SU/.git" ]; then
  git clone https://github.com/SukiSU-Ultra/SukiSU-Ultra "$SU"
  git -C "$SU" checkout builtin
fi

# -------------------------------------------------------------- integration
cd "$K"
rm -rf "$OP/vendor"; mkdir -p "$OP/vendor"
[ -d "$M/vendor" ] && cp -a "$M/vendor/." "$OP/vendor/"

if [ -d "$M/vendor/oplus/kernel/cpu" ]; then
  rm -rf kernel/oplus_cpu
  cp -a "$M/vendor/oplus/kernel/cpu" kernel/oplus_cpu
fi

log "susfs files"
cp "$S/kernel_patches/fs/susfs.c"                 fs/susfs.c
cp "$S/kernel_patches/include/linux/susfs.h"      include/linux/susfs.h
cp "$S/kernel_patches/include/linux/susfs_def.h"  include/linux/susfs_def.h

log "susfs patch"
patch -p1 --forward --no-backup-if-mismatch \
  < "$S/kernel_patches/50_add_susfs_in_gki-android12-5.10.patch" || true
REJ=$(find . -name '*.rej' | wc -l)
echo "rejects: $REJ"
[ "$REJ" -eq 0 ] || { echo "FATAL: susfs patch rejected, fix before building" >&2; exit 1; }

# NOTE: this tree DOES provide inotify_mark_user_mask(); do not rewrite it.
# (The 2V device tree inlined the mask instead - different tree, different fix.)

grep -q 'VMA_PAD_START' include/linux/susfs_def.h || cat >> include/linux/susfs_def.h <<'EOF'

#ifndef VMA_PAD_START
#define VMA_PAD_START(vma) ((vma)->vm_start)
#endif
EOF

log "KernelSU builtin"
rm -rf KernelSU; mkdir -p KernelSU; cp -a "$SU/kernel/." KernelSU/; rm -rf KernelSU/.git
rm -f drivers/kernelsu; ln -sf ../KernelSU drivers/kernelsu
grep -q 'obj-$(CONFIG_KSU)' drivers/Makefile || \
  printf '\nobj-$(CONFIG_KSU) += kernelsu/\n' >> drivers/Makefile
grep -q 'drivers/kernelsu/Kconfig' drivers/Kconfig || \
  sed -i '/^endmenu/i source "drivers/kernelsu/Kconfig"' drivers/Kconfig

MF=KernelSU/Makefile
sed -i 's|^\$(shell cd \$(KSU_SRC).*unshallow.*|# offline|' "$MF" 2>/dev/null || true
sed -i 's|^CURL_BIN.*|CURL_BIN := true|' "$MF" 2>/dev/null || true
sed -i 's|^KSU_GITHUB_VER.*|KSU_GITHUB_VER := |' "$MF" 2>/dev/null || true
sed -i 's|^GITHUB_COMMITS.*|GITHUB_COMMITS := |' "$MF" 2>/dev/null || true

# ------------------------------------------------------------------- config
log "config"
cp "$HERE/configs/stock_defconfig" arch/arm64/configs/ace_defconfig
# Deterministic UTS suffix: 5.10.236-android12-9-o-g6973d81cd2ac
sed -i 's|^CONFIG_LOCALVERSION=.*|CONFIG_LOCALVERSION="-android12-9-o-g6973d81cd2ac"|' \
  arch/arm64/configs/ace_defconfig
sed -i 's|^CONFIG_LOCALVERSION_AUTO=.*|# CONFIG_LOCALVERSION_AUTO is not set|' \
  arch/arm64/configs/ace_defconfig
grep -E '^CONFIG_LOCALVERSION|^# CONFIG_LOCALVERSION_AUTO' arch/arm64/configs/ace_defconfig
mkdir -p "$O"
make -C "$K" O="$O" ace_defconfig
cat "$HERE/configs/ksu_susfs.config" >> "$O/.config"
make -C "$K" O="$O" olddefconfig

# Deterministic UTS: 5.10.236-android12-9-o-g6973d81cd2ac
printf '#!/bin/sh\nexit 0\n' > scripts/setlocalversion
chmod +x scripts/setlocalversion
make -C "$K" O="$O" olddefconfig
echo "LOCALVERSION in .config: $(grep -E '^CONFIG_LOCALVERSION=' "$O/.config")"
grep -q '^CONFIG_LOCALVERSION="-android12-9-o-g6973d81cd2ac"' "$O/.config" || {
  echo "FATAL: LOCALVERSION not applied" >&2; exit 1; }

# /proc/config.gz must show the factory config, not ours
cp "$HERE/configs/stock_defconfig" arch/arm64/configs/stock_defconfig
if grep -q '^\$(obj)/config_data: \$(KCONFIG_CONFIG) FORCE$' kernel/Makefile; then
  sed -i 's|^\$(obj)/config_data: \$(KCONFIG_CONFIG) FORCE$|$(obj)/config_data: arch/arm64/configs/stock_defconfig FORCE|' kernel/Makefile
fi
grep -n -A1 'config_data:' kernel/Makefile | head -4

log "config guard"
for c in LTO_CLANG_FULL CFI_CLANG CFI_CLANG_SHADOW SHADOW_CALL_STACK \
         KASAN_HW_TAGS MODVERSIONS ARM64_4K_PAGES; do
  grep -q "^CONFIG_${c}=y$" "$O/.config" || {
    echo "FATAL: CONFIG_${c} was dropped -> vendor module CRCs will not match" >&2
    exit 1; }
done
echo "all critical configs present"

# -------------------------------------------------------------------- build
log "build"
export KBUILD_BUILD_VERSION=1
export KBUILD_BUILD_USER=build-user
export KBUILD_BUILD_HOST=build-host
export KBUILD_BUILD_TIMESTAMP="Tue Feb 10 13:50:12 UTC 2026"
rm -f "$O/include/generated/compile.h" "$O/init/version.o" "$O/.version" || true
echo 1 > "$O/.version"

make -C "$K" O="$O" -j"$(nproc)" KSU_VERSION=${KSU_VERSION:-40900} Image

log "verify UTS"
strings "$O/vmlinux" | grep -m1 '^Linux version' || true
echo "KSU/SuSFS symbols: $(nm "$O/vmlinux" | grep -cE ' (T|t|D|d|B|b) (ksu_|susfs_|kernelsu_)' || true)"
echo "config.gz KSU/SUSFS lines: $(zcat "$O/kernel/config_data.gz" 2>/dev/null | grep -cE 'CONFIG_KSU' || true)"
echo "exported __crc_ symbols : $(nm "$O/vmlinux" | grep -c '^__crc_' || true)"

log "DONE: $O/arch/arm64/boot/Image"
