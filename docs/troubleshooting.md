# 踩过的坑

这份是排错手册。每一条都是真机上撞出来的，附现象、根因、判断方法。

---

## 1. 刷 vendor_boot 后报「文件损坏」

**现象**：`flash.locked=1` 状态下，单独刷改过的 `vendor_boot` 或 `boot`，开机直接「系统文件被损坏」不启动。

**根因**：LK 对 `boot`/`vendor_boot` 的 AVB 校验失败是**致命**的，不是变 orange。
只有先刷了 `lk.img`（关掉 boot 验签）才放行。

**处理**：顺序改为 `lk → vendor_boot → boot`。详见 [`flash.md`](flash.md)。

---

## 2. lk 报「系统文件被破坏」但 boot/vendor_boot 都是原厂

**现象**：只刷了改过的 `lk_b`，`boot`/`vendor_boot` 保持原厂，AVB 本该通过，却弹「文件损坏」。

**根因**：启动状态值填错了。我把 setter 改成 `#3`，而 **3 = red = corrupt**。

**处理**：改成 `#0`（green）。枚举实测值：

| 值 | 含义 |
|---|---|
| 0 | green |
| 2 | orange |
| 3 | red（损坏画面） |

**判断**：如果原厂镜像也报损坏，几乎一定是状态值的问题，不是镜像问题。

---

## 3. lk 卡第一屏无限重启

**现象**：能亮屏到第一屏，然后循环重启，不报"损坏"。

**根因**：把 21 条门禁表（`0x148df0`）全清零了。
全零让 LK 连 `lk_main_dtb` 等分区的加载一起跳过，流程走不下去。

**处理**：不要动门禁表。只改 boot 加载器里的单个调用点 `0x86310`。

**判断**：「文件损坏」= 校验没过；「无限重启」= LK 流程被破坏。两者根因不同。

---

## 4. 管理器显示「工作中」，但 `su` 不存在、没有页签

这是最耗时间的一个，有三个不同原因，现象几乎一样。

### 4.1 安全守卫模块在拦

**现象**：管理器报「获取 Root 失败」，系统弹「安全警告：检测到有恶意程序尝试破坏手机系统」。

**根因**：`oplus_security_guard.ko`（OPPO 的提权拦截模块）hook execve、读 verified_bootstate、
直接 `do_exit` 杀进程。它在 vendor_boot 的 ramdisk 里，加载后 `ksud` 装不进去。

**处理**：从 ramdisk 删除 `lib/modules/oplus_security_guard.ko`，
并从 `lib/modules/modules.load` 和 `modules.load.recovery` 中去掉对应行。

不需要 root——改的是源头。

`oplus_secure_harden.ko` 可以保留（它也有 ROOTCHECK 串，但不拦提权）。

### 4.2 KSU 与 susfs 版本错配

**现象**：管理器显示「工作中 / Built-in」，能读出版本号，但 `su`、`ksud`、三个页签全都没有。
没有任何错误提示。

**根因**：`builtin` 分支靠内核源码调用 hook 入口，**版本错配时 inline hook 静默失效**。
supercall 不依赖 hook，所以管理器能读版本；但 execve 从不被拦截，`su` 永远不触发重定向。

**处理**：固定到验证过的组合：

```
SukiSU-Ultra  builtin              6c284e957feaa9a388a9f1c37dc4ec80d95e434b
susfs4ksu     gki-android12-5.10   9892175b4acec7ee844e113b8d02c0f4d12cdfac
```

**判断口诀**：能读版本 = supercall 通；`su` 不可用 = hook 没生效。

**不要**用 2026-10-19 之后的新提交。

### 4.3 ksud 还没装

**现象**：内核正常、hook 正常，刚开机时 `su` 还没有。

**根因**：`ksud` 由管理器拿到 root 后自己写入 `/data/adb/ksud`，首次开机要等一下。

**处理**：打开一次管理器，等几秒；不行重启再开。

**验证**：

```bash
adb shell su -c 'ls -l /data/adb/ksud'
```

---

## 5. vmlinux 链接期 undefined symbol

**现象**：跑了 65 分钟，最后 `ld.lld: error: undefined symbol: ksu_preinit_handle_post_execveat / my_setprocattr / ...`

**根因**：susfs 补丁**半应用**——调用点的 hunk 打上了，定义的 hunk 没打上。
用 `patch --forward` 时，打不上的 hunk 会被**静默跳过、不留 `.rej`**，于是只剩链接期才报错。

**处理**：

1. 去掉 `--forward`（本仓库脚本已改），打不上必须留 `.rej`
2. 加早断言：`rejects: 0` + 关键定义必须存在
3. 注意 `my_setprocattr` 是**补丁自己定义**在 `security/selinux/hooks.c` 里的，
   不是 KSU 提供的符号——断言要查"定义在不在"，不能只 grep 名字

---

## 6. 内核版本串不对（缺 `-android12-9-o-...`）

**现象**：编出来 `uname -r` 是 `5.10.209`，少了后缀。

**根因**：kbuild 的 localversion **来自 `scripts/setlocalversion`**，
不是 `CONFIG_LOCALVERSION`。把 `setlocalversion` 换成 `exit 0` 就丢后缀了。

**处理**：让 `scripts/setlocalversion` 直接输出完整后缀，并用 `make kernelrelease` 硬断言。

---

## 7. 关键 config 被静默降级

**现象**：内核能编能开，但厂商模块加载失败 / CRC 不对 / Wi-Fi 之类不工作。

**根因**：`olddefconfig` 时某些选项因为工具链不认识被降级（例如用 GNU binutils 会关掉 LTO）。

**必须保住的 7 项**：

```
LTO_CLANG_FULL  CFI_CLANG  CFI_CLANG_SHADOW  SHADOW_CALL_STACK
KASAN_HW_TAGS   MODVERSIONS  ARM64_4K_PAGES
```

**处理**：CI 里硬断言，掉了直接失败。

---

## 8. `/proc/config.gz` 泄漏 KSU

**现象**：`zcat /proc/config.gz | grep CONFIG_KSU` 有输出。

**根因**：`config_data.gz` 默认从当前 `.config` 生成。

**处理**：把 `kernel/Makefile` 里 `config_data` 的依赖指向原厂 defconfig：

```sh
sed -i 's|^\$(obj)/config_data: \$(KCONFIG_CONFIG) FORCE$|$(obj)/config_data: arch/arm64/configs/stock_defconfig FORCE|' kernel/Makefile
```

**验证**：

```bash
adb shell su -c 'zcat /proc/config.gz | grep -c CONFIG_KSU'   # 期望 0
```

注意 `grep -ci ksu` 会误匹配 `CONFIG_NETFILTER_XT_TARGET_CHE**CKSU**M`，要用 `CONFIG_KSU`。

---

## 9. 怎么确认设备上跑的是哪个内核

`uname -r` 两版完全一样（都是伪装串），**必须看 `uname -v` 的编译时间戳**：

| 内核 | `uname -v` |
|---|---|
| 原厂 500 | `Sat Feb 8 05:36:32 UTC 2025` |
| 自编 | `Tue Feb 10 13:50:12 UTC 2026` |

看代码就是 `#1 SMP PREEMPT <时间戳>` 这一串。

---

## 10. 探测 KSU su hook 的正确姿势

**错误的探针**：把 `sh` 复制成 `/data/local/tmp/su` 再执行，期望被重定向。

**为什么不行**：KSU 只对**精确路径 `/system/bin/su`** 做 `memcmp` 判定，
改名的二进制不会触发。这个探针跑出来是 `uid=2000`，看着像 hook 坏了，其实什么也没证明。

**正确的判断依据**：

```bash
adb shell su -c id          # uid=0 且 context=u:r:ksu:s0 才算通
adb shell su -c 'ls -l /data/adb/ksud'   # ksud 在不在
```

---

## 11. 想永久宽容 SELinux —— 别走这条路

**试过且失败的**：往 `boot.img` 头部的 cmdline 写 `androidboot.selinux=permissive`。

**为什么失败**：LK 从 DTB 重建启动参数，**不采用 boot 头里的 cmdline**，`getenforce` 仍是 `Enforcing`。

**结论**：最终方案根本不需要宽容模式，`Enforcing` 下也能正常工作。要真改启动参数得从 DTB bootargs
或 LK 内部下手，没有必要。

---

## 12. PowerShell 处理二进制/UTF-8 的坑

- `adb exec-out screencap -p > file` 在 PowerShell 里会把二进制写成文本，PNG 损坏。
  改用 `adb shell screencap -p /sdcard/x.png` 然后 `adb pull`。
- `Set-Content -Encoding utf8` 会写 BOM，导致文档变乱码 / URL 上传失败。
  用 `[IO.File]::WriteAllText($p, $t, (New-Object Text.UTF8Encoding($false)))`。

---

## 13. 刷完内核某个硬件哑了（没声音 / 无声 / 某某功能不工作）

**现象**：系统正常启动、KSU 正常、显示 WiFi 都正常，但某个硬件**静默失效**。没有任何报错。

**根因**：内核源码版本与设备固件不匹配。设备是 **500 固件 / 内核 5.10.209**，
源码必须来自同一固件版本的提交，而不是上游分支的最新状态。

源码版本不同，导出的符号 CRC 就不完全相同。`CONFIG_MODVERSIONS=y` 时，厂商 `.ko` 加载要逐个比对
它依赖的每个符号 CRC，对不上就拒绝加载。大部分模块恰好没变化，系统能起来；
但依赖了变化符号的那批模块会全部加载失败 → 对应硬件静默失效。

**为什么难发现**：模块加载失败只写 dmesg，不弹任何 UI 提示。而 `lsmod` 少几个模块，不专门看根本注意不到。

**定位**：

```bash
su -c 'dmesg | grep -iE "disagrees about version|no symbol version|Unknown symbol"'
su -c 'lsmod | wc -l; ls /vendor/lib/modules/*.ko | wc -l'
```

出现 `disagrees about version of symbol xxx` 就是 CRC 不匹配。

**处理**：源码固定到与固件版本号一致的提交。

```
kernel  OnePlusOSS/android_kernel_5.10_oneplus_mt6895
        3a3edc50a4d410988728d9c4e382afa1abdc42f5   PGKM10_15.0.0.500 (5.10.209)
vendor  OnePlusOSS/android_vendor_mediatek_kernel_modules_mt6895
        4c1f20261d8d489d3dca5c1dd8ac62db92b89913   PGKM10_15.0.0.500
```

**判断源码对不对**：

```bash
grep -E '^(VERSION|PATCHLEVEL|SUBLEVEL) =' Makefile     # 必须 5 / 10 / 209
git log -1 --format=%s                                   # 必须含 PGKM10_15.0.0.500
```

**教训**：不要用"某个模块的导入符号 CRC 一致"来推断整体 ABI 兼容。
只核对单个模块的几十个导入符号说明不了全部，**结论可能是错的**。
唯一可靠判据是**源码提交与固件版本号一致**。

