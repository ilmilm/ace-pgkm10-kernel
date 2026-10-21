# 怎么编译

内核由 GitHub Actions 编译，本地不需要装 clang/LLVM。一次完整构建约 **60–70 分钟**。

## 前置

- 一个 GitHub 仓库（建议私有），把本仓库内容推上去
- 仓库 Actions 已启用
- artifact 保留期默认 90 天

## 触发

Actions → `build-kernel` → **Run workflow** → 选 `main` → 运行。

工作流做四件事：

1. 装构建依赖 + 拉 Android clang `r416183b`
2. 跑 `scripts/build_ace_kernel.sh`
3. 上传 `Image` / `Image.gz` / `System.map` / `kernel.config` / `config_data.gz`
4. 输出 sanity 报告

## 构建脚本做了什么

`scripts/build_ace_kernel.sh` 的顺序：

```
1. 克隆三个上游
   ├─ OnePlusOSS/android_kernel_5.10_oneplus_mt6895        分支 oneplus/mt6895_v_15.0.0_ace
   ├─ OnePlusOSS/android_vendor_mediatek_kernel_modules_mt6895
   ├─ ShirkNeko/susfs4ksu                                  分支 gki-android12-5.10  ← 固定 commit
   └─ SukiSU-Ultra/SukiSU-Ultra                            builtin 分支            ← 固定 commit

2. 打 susfs 补丁（不加 --forward，打不上必须留 .rej）
3. 断言补丁自洽（my_setprocattr 定义必须存在）
4. 集成 KernelSU：链接到 drivers/kernelsu，挂进 drivers/Makefile + Kconfig
5. 安装手动 hook（susfs 补丁已覆盖，脚本作兜底 + 校验 4/4）
6. 配置：原厂 defconfig + ksu_susfs.config 片段
7. 版本串伪装 + kernelrelease 硬断言
8. /proc/config.gz 伪装
9. 7 项关键 config 硬断言
10. 编译 Image
```

### 关键：两处版本固定

```
SUSFS_SHA=9892175b4acec7ee844e113b8d02c0f4d12cdfac
KSU_SHA=6c284e957feaa9a388a9f1c37dc4ec80d95e434b
```

**这两个 commit 是验证过能工作的组合，不要随意升级。**

用 2026-10-19 之后的新提交会踩两个坑：

- susfs 引用了 KSU builtin 分支不存在的符号 → vmlinux 链接期 undefined symbol
- 两者版本错配 → inline hook 静默失效，管理器显示「工作中」但 `su` 根本没有

判断方法：管理器能读出版本号 = supercall 通；`su` 不可用 = hook 没生效。

### 关键：版本串伪装

kbuild 的 localversion 后缀来自 `scripts/setlocalversion`，**不是** `CONFIG_LOCALVERSION`。
脚本直接把整个文件替换成：

```sh
#!/bin/sh
echo "-android12-9-o-gaad6b7fc18f9"
```

然后断言：

```sh
KR=$(make -s -O="$O" kernelrelease)
[ "$KR" = "5.10.209-android12-9-o-gaad6b7fc18f9" ] || exit 1
```

不匹配直接失败，不会产出一个版本串不对的内核。

### 关键：7 项 config 硬断言

```sh
for c in LTO_CLANG_FULL CFI_CLANG CFI_CLANG_SHADOW SHADOW_CALL_STACK \
         KASAN_HW_TAGS MODVERSIONS ARM64_4K_PAGES; do
  grep -q "^CONFIG_${c}=y$" "$O/.config" || exit 1
done
```

`olddefconfig` 有可能因为工具链不认识而**静默降级**这些选项（例如用 GNU binutils 会关掉 LTO）。
一旦掉一项，编出来的内核所有厂商 `.ko` 的 `__versions` CRC 全部对不上，系统起不来。

### 关键：`/proc/config.gz` 伪装

```sh
sed -i 's|^\$(obj)/config_data: \$(KCONFIG_CONFIG) FORCE$|$(obj)/config_data: arch/arm64/configs/stock_defconfig FORCE|' kernel/Makefile
```

让 `config_data.gz` 从原厂 defconfig 生成，而不是从我们的 `.config`。
结果：解压 `/proc/config.gz` 得到的是原厂 209 配置，看不到任何 `CONFIG_KSU`。

## 拿到 artifact 之后

artifact 里是裸内核，需要装进原厂 `boot.img` 才能刷。

```sh
python pack_boot.py 原厂boot_b.img Image.gz out.img
```

`pack_boot.py` 做的是：

1. 用 `Image.gz` 替换原厂内核（保持 `gzip -9 -n` 风格，FLG=0x00）
2. ramdisk 逐字节保留原厂（不动它，避免 ksuinit/init 相关的坑）
3. vbmeta 原样搬运，按新的 `content_end` 重写 AVB footer
4. 刷之前校验：gunzip 后与 `Image` 一致、ARM64 magic、ramdisk 逐字节相同、vbmeta 逐字节相同

校验脚本会打印 11 项检查，必须全 PASS。

## 本地编译（不推荐）

需要 Android clang `r416183b`（clang 12.0.5）。用别的版本会触发 LTO/CFI 相关的 config 降级。
其余步骤和 CI 完全一致，直接跑 `bash scripts/build_ace_kernel.sh <工作目录>`。

## 常见失败

| 现象 | 原因 |
|---|---|
| 8 分钟内失败，`rejects: N`（N>0） | susfs 补丁与内核树冲突，换 `SUSFS_SHA` |
| `FATAL: susfs patch did not define my_setprocattr` | 补丁 hunk 半应用，同上 |
| `FATAL: CONFIG_XXX was dropped` | 工具链不对，LTO/CFI 被降级 |
| `FATAL: kernelrelease is '...'` | `scripts/setlocalversion` 没生效 |
| 65 分钟后 `undefined symbol: ksu_*` | KSU/susfs 版本错配，回退到上面那组 commit |
| 编出来能开机但 `su` 不可用 | inline hook 失效，同上 |
