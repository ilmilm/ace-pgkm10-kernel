# ace-pgkm10-kernel

OnePlus Ace（PGKM10 / OP5565 / MT6895）内建 KernelSU + SuSFS 内核构建。

目标固件：ColorOS 15 `PGKM10_15.0.0.1800(CN01)`，内核 `5.10.236-android12-9-o-g6973d81cd2ac`。

## 结构

```
.github/workflows/build-kernel.yml   CI 流程
scripts/build_ace_kernel.sh          克隆 + 集成 + 配置 + 编译
configs/stock_defconfig              设备导出的原厂 config（伪装目标）
configs/ksu_susfs.config             KSU / SuSFS 配置片段
```

## 使用

手动触发：Actions → `build-ace-kernel` → Run workflow。

产物 `ace-kernel.zip` 内含：

| 文件 | 说明 |
|---|---|
| `Image.gz` | 内核，喂给 `pack_boot.py` |
| `System.map` | `__crc_*` 符号，用于核对厂商模块 ABI |
| `Module.symvers` | 导出符号 CRC 清单 |
| `kernel.config` | 确认 LTO/CFI 没有被降级 |
| `config_data.gz` | 确认 `/proc/config.gz` 不含 KSU 条目 |

## 三条不可让步的约束

1. `CONFIG_LTO_CLANG_FULL` / `CFI_CLANG` / `KASAN_HW_TAGS` / `SHADOW_CALL_STACK`
   必须保留。任何一个被静默丢弃，469 个厂商模块的导出符号 CRC 全部失效，
   内核直接无法加载模块。脚本里有硬检查，缺一项立即失败。
2. `LLVM=1` 且 `clang/ld.lld/llvm-nm/llvm-ar` 必须全部来自同一套 r416183b 工具链。
   主机 GNU binutils 会让 Kconfig 判定 `HAS_LTO_CLANG=n` 并静默降级。
3. 内核版本串必须构造成 `5.10.236-android12-9-o-g6973d81cd2ac`：
   脚本把 `scripts/setlocalversion` 置空，并用 `CONFIG_LOCALVERSION` 精确指定。

## runner 规格说明

GitHub 免费 runner 是 4 核 / 16 GB。Full-LTO 链接峰值约 12 GB，因此流程里
先回收磁盘、再加 16 GB swap。耗时约 60–120 分钟。

若出现 OOM（日志含 `Killed`）：
- swap 提高到 24 GB
- 并行度降到 `-j2`

不要靠降级 LTO 来省内存。
