# AGENTS.md — 给任何接手本仓库的 AI / 协作者

> 本文件优先级高于 README 与 docs 里的任何叙述。**先读这里再动代码。**

## 唯一目标

```
设备    OnePlus Ace  PGKM10 / OP5565 / MT6895
固件    PGKM10_15.0.0.500(CN01)
内核    5.10.209-android12-9-o-gaad6b7fc18f9
```

**只支持这一个组合。** 不讨论、不支持、不引入任何其他固件版本或内核版本。
如果你的上下文里出现过别的固件号/内核号，那是历史残留，**不是目标**，不要照着做。

## 硬规则（违反即构建失败或砖机）

1. **源码必须钉到 500 对应的提交，禁止用分支 HEAD**
   ```
   kernel  3a3edc50a4d410988728d9c4e382afa1abdc42f5   PGKM10_15.0.0.500 (5.10.209)
   vendor  4c1f20261d8d489d3dca5c1dd8ac62db92b89913   PGKM10_15.0.0.500
   susfs   f43926dc94b8ffbf9b74321313536600f69367b1   gki-android12-5.10
   ksu     ce75122bec7423e0f1fa06e3e9a174085c5231ab   builtin
   ```
   KSU 与 susfs 必须**同代升级**，一次只动一个的后果：链接期 undefined symbol，
   或者编得过但 inline hook 静默失效（管理器显示"工作中"，`su` 根本不存在）。

   `KSU_VERSION=40994` 与管理器 `SukiSU_v4.2.1_40994-release.apk` 绑定；改号必须同时换 APK。

2. **7 项 config 一个都不能丢**：`LTO_CLANG_FULL` `CFI_CLANG` `CFI_CLANG_SHADOW`
   `SHADOW_CALL_STACK` `KASAN_HW_TAGS` `MODVERSIONS` `ARM64_4K_PAGES`。
   掉一项 → 所有厂商 `.ko` 的 `__versions` CRC 失效。

3. **版本串伪装走 `scripts/setlocalversion`**（不是 `CONFIG_LOCALVERSION`），
   必须 `make kernelrelease` 逐字等于 `5.10.209-android12-9-o-gaad6b7fc18f9`。

4. **`/proc/config.gz` 必须从原厂 defconfig 生成**：`kernel/Makefile` 里
   `$(obj)/config_data` 的依赖指向 `arch/arm64/configs/stock_defconfig`，
   改完要断言 `zcat /proc/config.gz | grep -c '^CONFIG_KSU'` == 0。

5. **lk 只需 4 处改动，共 16 字节**：`0x5ebd0` / `0x5ed94` / `0x86310` / `0x6fdb8`
   （`0x5ef88` 本来就是 `mov w0,wzr`）。地址是**原厂镜像**的文件偏移，
   改过的镜像因为注入块变长，`bl2_ext / aee / lk_main_dtb` 整体后移 `+0x450`。
   - **不要**清零 `0x148df0` 的 21 条门禁表 → 卡第一屏无限重启
   - **不要**把启动状态设成 3 → 弹"系统文件被破坏"，连原厂镜像都一样
   - 状态枚举：`0`=green，`2`=orange，`3`=red

6. **三个镜像必须配套，刷写顺序固定**：`lk` → `vendor_boot` → `boot`。
   先刷 `boot`/`vendor_boot` 必然报"文件损坏"（lk 里关了 boot 验签才放行）。

7. **`oplus_security_guard.ko` 是 root 的拦路虎**，从 vendor_boot 的 ramdisk 删掉
   （`lib/modules/` + `modules.load` + `modules.load.recovery`）。`oplus_secure_harden.ko` 可保留。

## 改东西之前

- 先读 [`docs/troubleshooting.md`](docs/troubleshooting.md)，13 条都是真机撞出来的
- 涉及 boot 打包：`scripts/pack_boot.py` 保持 ramdisk 逐字节原厂、vbmeta 原样搬运
- 涉及 lk：改完必须重建证书链并 `verify_mtk_image.py --all` 四段全 VALID

## 验收标准

```bash
adb shell su -c id                              # uid=0(root) context=u:r:ksu:s0
adb shell uname -r                              # 5.10.209-android12-9-o-gaad6b7fc18f9
adb shell uname -v                              # #1 SMP PREEMPT Fri Oct 23 05:20:00 UTC 2026（自编戳）
adb shell getprop ro.boot.verifiedbootstate     # green
adb shell getprop ro.boot.flash.locked          # 1
adb shell getprop ro.boot.vbmeta.device_state   # locked
adb shell getprop ro.boot.slot_suffix           # _a 或 _b —— 刷之前必须查
```

`uname -r` 两版内核完全相同，**只能用 `uname -v` 的编译时间戳区分**跑的是哪个内核。
