# 怎么刷、怎么回滚

## 前提

**先查自己手机在哪个槽，别照抄下面的 `_b`：**

```bash
adb shell getprop ro.boot.slot_suffix      # 输出 _a 还是 _b
```

- 本文命令以 `_b` 为例。**你查到什么槽，就把命令里的 `_b` 换成那个**
- 只动当前槽的分区，另一个槽保持原厂（最后一道保险）
- 三个镜像必须配套，缺一不可
- 刷之前先确认工程线 / BROM 能写 `lk`，否则不要动 `lk_?`
- 本仓库 `stock-500` 是 **`_b` 槽的 readback**；你在 `_a` 槽就得自己 readback 一份，或先切槽

## 刷写顺序（不能变）

```bash
# 1) lk — 必须最先，它是让改过的镜像能被接受的前提
fastboot flash lk_b patched-lk.img
fastboot reboot

# 2) vendor_boot — 去掉安全守卫模块，root 才能真正拿到
fastboot flash vendor_boot_b patched-vendor_boot.img
fastboot reboot

# 3) boot — 自编内核
fastboot flash boot_b patched-boot.img
fastboot reboot
```

> 上文以 `_b` 槽为例。`_a` 槽请换成 `lk_a` / `vendor_boot_a` / `boot_a`。

### 为什么顺序不能反

`flash.locked=1` 时，LK 对 `boot` / `vendor_boot` 的 AVB 校验失败是**致命**的，直接弹「系统文件被损坏」不启动（不是变 orange）。

只有刷了 `lk.img`（里面关掉了 boot 验签）之后，改过的 `boot` / `vendor_boot` 才能被放行。

**先单独刷 `vendor_boot` 或 `boot` 必然报「文件损坏」。** 这是刷写顺序错误，不是镜像坏了。

## 每步验收

```bash
# 第 1 步后：仍跑原厂内核，能正常开机
adb shell uname -r        # 5.10.209-android12-9-o-gaad6b7fc18f9
adb shell getprop ro.boot.verifiedbootstate   # green

# 第 2 步后：管理器不再报「获取 Root 失败」
# 第 3 步后：
adb shell uname -v        # #1 SMP PREEMPT Fri Oct 23 05:20:00 UTC 2026  ← 区分原厂的关键
adb shell su -c id        # uid=0(root) context=u:r:ksu:s0
adb shell getprop ro.boot.vbmeta.device_state  # locked
```

`uname -r` 两版内核完全一样（都是伪装串），**必须用 `uname -v` 的编译时间戳判断**跑的是哪个内核：

| 内核 | `uname -v` |
|---|---|
| 原厂 | `Sat Feb 8 05:36:32 UTC 2025` |
| 自编 | `Fri Oct 23 05:20:00 UTC 2026` |

## 回滚

原厂镜像在 [Release `stock-500`](https://github.com/ilmilm/ace-pgkm10-kernel/releases/tag/stock-500)。

```bash
# 以 _b 槽为例；_a 槽换成 lk_a / vendor_boot_a / boot_a，并按槽取原版镜像
fastboot flash lk_b           原版lk_b.img
fastboot flash vendor_boot_b  原版vendor_boot_b.img
fastboot flash boot_b         原版boot_b.img
```

**三个一起刷回。** 不要只回滚 `lk_?`——那样 `boot`/`vendor_boot` 还是改过的，没有 lk 补丁放行会立刻「文件损坏」。

## 出事怎么办

### 还能进 fastboot

直接刷回原厂三个分区。

### 进不了 fastboot（刷 lk 刷坏了）

只能走 BROM：

1. 关机
2. 按住音量键组合 + 插 USB 进 BROM（不同 MTK 机型组合不同，PGKM10 通常需要工程线）
3. 用 GeekFlashTool / mtkclient 写回原厂 `lk_b.img`
4. 再写回原厂 `boot_b.img` / `vendor_boot_b.img`

**这就是为什么第一步要测试 BROM 能不能写 lk。** 写不进去就别碰 `lk_b`。

## 分区对照（PGKM10，实测）

| 分区 | by-name |
|---|---|
| `lk_a` / `lk_b` | sdc38 / sdc71 |
| `boot_a` / `boot_b` | sdc39 / sdc72 |
| `vendor_boot_a` / `vendor_boot_b` | sdc40 / sdc73 |
| `seccfg` | sdc21 |
| `super` | sdc79 |

共 88 个分区，**没有 `init_boot`**。

## 管理器

装 `SukiSU_v4.2.1-r1_41049-release.apk`。

配对看 **UAPI 版本**（现在两边都是 6），不看 build 号；UAPI 高的一侧会提示更新另一侧。

装完之后打开一次管理器，它需要拿到 root 才会把 `ksud` 装进 `/data/adb/`：

```bash
adb shell su -c id                    # 验证
adb shell su -c 'ls -l /data/adb/ksud'
```
