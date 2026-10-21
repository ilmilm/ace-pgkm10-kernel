# 一加 Ace (PGKM10 / OP5565 / MT6895) — 锁 BL + green + 内建 KernelSU + SuSFS

在 **BL 提示未解锁、系统报 green** 的状态下，跑自编译内核 + KernelSU + SuSFS 的完整方案。
针对 **ColorOS 15 / PGKM10_15.0.0.500(CN01)**、内核 **5.10.209-android12-9-o-gaad6b7fc18f9**。

> 本项目是在真机上一步步试错出来的，不是理论推演。每一处补丁地址、每一个枚举值都经过验证，
> 踩过的坑全部记录在 [`docs/troubleshooting.md`](docs/troubleshooting.md)。

---

## 成果

```
su -c id  →  uid=0(root) gid=0(root) groups=0(root) context=u:r:ksu:s0
```

| 验收项 | 实测值 |
|---|---|
| 系统版本 | `PGKM10_15.0.0.500(CN01)` |
| 内核版本 | `5.10.209-android12-9-o-gaad6b7fc18f9` |
| 内核编译戳 | `#1 SMP PREEMPT Tue Feb 10 13:50:12 UTC 2026`（伪装） |
| `ro.boot.verifiedbootstate` | **green** |
| `ro.boot.flash.locked` | **1** |
| `ro.boot.vbmeta.device_state` | **locked**（LK 强制输出；硬件真实状态仍是 unlocked） |
| SELinux | **Enforcing**（不需要宽容模式） |
| KernelSU | `工作中` / `Built-in` / `40900-2` |
| SuSFS | `v2.3.0 (SUSFS Inline Hook)`，`ksud susfs status` = `true` |
| `/proc/config.gz` 里 `CONFIG_KSU` | **0 条**（伪造为原厂配置） |
| `/proc/kallsyms` 里 `ksu_`/`susfs_` | **0 条**（符号隐藏生效） |
| 管理器页签 | 主页 / 超级用户 / 模块 / 设置 全部正常 |

---

## 三个镜像

产物体积太大不适合放 Git，需要的话自己按 [`docs/build.md`](docs/build.md) 编或提 Issue。

| 文件 | 改了什么 |
|---|---|
| `boot.img` | 自编内核（KSU 内建 + SuSFS）。ramdisk 与原厂逐字节相同，vbmeta 原样搬运 |
| `vendor_boot.img` | 删除 `oplus_security_guard.ko` 及其加载项（928 → 927 条目） |
| `lk.img` | 证书链 legacy 注入 + 只跳过 boot 验签 + 启动状态强制 green + `device_state` 强制 locked |

**三者必须配套使用，缺一不可。** 依赖关系：

```
lk.img          → 决定能不能启动（preloader 证书校验 + AVB 门禁）
vendor_boot.img → 决定能不能拿到 root（安全守卫模块会杀掉提权进程）
boot.img        → 决定有没有 root 功能（KSU 内核本体）
```

---

## 原版固件基线

回滚和重新构建都需要原厂镜像，放在 Release：

**[`stock-500`](https://github.com/ilmilm/ace-pgkm10-kernel/releases/tag/stock-500)**

| 文件 | sha256 |
|---|---|
| `boot_b.img` | `42baddf6915d02512de28833f532c11d4ce76cf9753379695f3b76a0c952df45` |
| `vendor_boot_b.img` | `04f08ec4e44ee99609760ff24c79af66bf15c670111a5ec9f3d315924227208a` |
| `lk_b.img` | `9c1fb6a99f13fd21a95cf5f69b8f24eac7e06684e5cc975bcf414b8d57706ef2` |

来源：GeekFlashTool 从设备 readback，未做任何修改。

---

## 快速开始

### 只想刷（需要有对应产物）

```bash
# 当前运行槽 _b，_a 保持原厂不动
fastboot flash lk_b           lk.img
fastboot reboot
fastboot flash vendor_boot_b  vendor_boot.img
fastboot reboot
fastboot flash boot_b         boot.img
fastboot reboot
```

**顺序不能变。** 先刷 lk：它是让改过的镜像能被接受的前提。详见 [`docs/flash.md`](docs/flash.md)。

### 想自己编译

推到 GitHub 私有仓库 → Actions 手动触发 `build-kernel` → 拿 artifact 里的 `Image.gz` → 用原厂 `boot_b.img` 打包。
完整步骤见 [`docs/build.md`](docs/build.md)。

### 配套管理器

```
SukiSU_v4.2.0_40900-release.apk
```

**不要升到 4.2.1 (40994)**：内核报 `40900`，版本对不上会一直提示有新版本。

---

## 关键技术点

完整推导见 [`docs/lk.md`](docs/lk.md) 和 [`docs/troubleshooting.md`](docs/troubleshooting.md)，这里只列结论：

**1. MTK 证书链靠 legacy 注入绕过**

preloader 用 CERT1/CERT2（RSA-2048 + RSASSA-PSS）校验 `lk`。没有私钥，走 legacy 模式（`bypass_mode=1`，tag `0x20`）插入伪造的 image hash 块即可通过。这是整套方案能成立的地基。

**2. LK 里的 AVB 门禁只能改一个点，不能全关**

21 条门禁表（`0x148df0`）**不能全清零**。全零会让 LK 连 `lk_main_dtb` 等分区的加载一起跳过，表现为卡第一屏无限重启。正确做法只改 boot 加载器里的一个调用点（`0x86310`）。

**3. 启动状态枚举：0 = green，2 = orange，3 = red**

改成 3 会直接弹「系统文件被破坏无法开机」——即使镜像是原厂的。必须改成 0。

**4. `oplus_security_guard.ko` 是 root 的真正拦路虎**

它 hook execve、读 `verified_bootstate`、直接 `do_exit` 杀进程，并弹「安全警告：检测到有恶意程序…」。只要它加载，`ksud` 就装不进去。它在 vendor_boot 的 ramdisk 里，**改源头即可，不需要 root**。

**5. KSU 与 susfs 版本必须配对**

`builtin` 分支不使用 kprobes，靠内核源码调用 hook 入口（susfs 补丁已经帮你插好）。
但 **KSU/susfs 版本错配时 inline hook 会静默失效**：supercall 不受影响，所以管理器显示「工作中」、能读出版本，但 `su`、`ksud`、页签全都没有——极难排查。
必须用验证过的组合：

```
SukiSU-Ultra  builtin              6c284e957feaa9a388a9f1c37dc4ec80d95e434b
susfs4ksu     gki-android12-5.10   9892175b4acec7ee844e113b8d02c0f4d12cdfac
```

**6. 7 项 config 一个都不能丢**

```
CONFIG_LTO_CLANG_FULL=y      CONFIG_CFI_CLANG=y
CONFIG_CFI_CLANG_SHADOW=y    CONFIG_SHADOW_CALL_STACK=y
CONFIG_KASAN_HW_TAGS=y       CONFIG_MODVERSIONS=y
CONFIG_ARM64_4K_PAGES=y
```

缺任一项，所有厂商 `.ko` 的 `__versions` CRC 全部失效。
CI 里有硬断言，掉了就构建失败。

**7. 版本串伪装走 `scripts/setlocalversion`**

kbuild 的 localversion 后缀来自 `scripts/setlocalversion`，**不是** `CONFIG_LOCALVERSION`。
脚本里直接输出 `-android12-9-o-gaad6b7fc18f9`，并断言 `make kernelrelease` 逐字等于原厂串。

---

## 目录结构

```
.github/workflows/build-kernel.yml   GitHub Actions 构建流程
scripts/build_ace_kernel.sh          构建主脚本（拉源码、打补丁、断言、编译）
scripts/add_manual_hooks.py          手动 hook 安装器（当前版本已由 susfs 补丁覆盖，保留作兜底）
configs/stock_defconfig              原厂 5.10.209 defconfig（232 KB）
configs/ksu_susfs.config             KSU + SuSFS 追加配置
docs/build.md                        怎么编译
docs/flash.md                        怎么刷、怎么回滚
docs/lk.md                           lk 补丁原理与地址表
docs/troubleshooting.md              踩过的坑与排查方法
```

---

## 已知限制

这几条改不掉，排查时别绕回来：

**1. `ro.boot.vbmeta.digest` 仍是真实摘要**

和出厂值不同。硬件密钥认证（TEE attestation）读的是真实摘要和真实锁状态，**不是**我们能改的 cmdline 属性。
所以 `device_state=locked` 只对"读属性"的检测生效，Play Integrity 的 `MEETS_DEVICE_INTEGRITY` 强校验过不了。

**2. 编译戳和原厂差一天**

我们的 `Tue Feb 10 13:50:12 UTC 2026`，原厂 `Sat Feb 8 05:36:32 UTC 2025`。
`uname -v` 能区分。要完全一致就把 `KBUILD_BUILD_TIMESTAMP` 改成原厂值重编。

**3. 安全守卫模块是删掉的**

OPPO 的提权拦截整体失效。副作用是部分检测类 App 可能有反应——但这是拿到 root 的前提。

**4. 内核源码是 5.10.236 分支，配置按 209 取值**

厂商 `.ko` 的 `__versions` CRC 两份固件实测一致（31/31），ABI 兼容。

---

## 风险提示

- **`lk_b` 刷错 = 不亮机 + 没有 fastboot**，只能靠 BROM / 工程线救。刷之前先确认 `mtk` 工具能列出分区表。
- 所有操作只动 `_b` 槽，`_a` 保持原厂，是最后一道保险。
- 自己负责自己的设备。

## 许可

本仓库的脚本与文档：MIT。
涉及的 KernelSU / SuSFS / OnePlus 内核源码各自遵循其原始许可。
原厂固件镜像版权归 OnePlus 所有，仅作个人设备恢复用途。
