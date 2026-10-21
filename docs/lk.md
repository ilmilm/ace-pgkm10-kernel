# lk 补丁原理与地址表

`lk.img` 是整个方案里最危险也最难的一环。这份文档记录所有补丁点、推导过程和验证结果。

## 镜像结构

`lk_b.img` 是 MTK 的多镜像容器（`0x500000` = 5242880 字节，padded）：

| 子镜像 | 偏移 |
|---|---|
| `lk` | `0x0` |
| `bl2_ext` | `0x14e080` |
| `aee` | `0x25bf80` |
| `lk_main_dtb` | `0x3a8720` |

`bl2_ext` / `aee` / `lk_main_dtb` 三个 payload **逐字节保持原样**，只改 `lk` 本体。
改完要重新签名（重建四个子镜像的 CERT2），最终全部证书链仍然 VALID。

## 一、证书链绕过（legacy 注入）

### 为什么必须做

preloader 在加载 `lk` 之前，用 MTK 的证书链校验：

- CERT1 / CERT2，RSA-2048 + RSASSA-PSS
- image hash OID `2.16.886.2454.2.1`，header hash OID `2.16.886.2454.2.4`

没有 OPPO 私钥，正常签名走不通。

### 怎么绕过

走 **legacy 模式**（`bypass_mode=1`，tag `0x20`）：在 image hash 块位置插入一段伪造数据，
让校验方走到"旧格式/无 hash"的分支，从而跳过实际比对。

工具：`pwnage24mtk/sign_mtk_cert.py -w --legacy`

用 1 字节的惰性改动（`app/` → `bpp/`，只出现在一条不会输出的断言字符串里）先做探针，验证注入成立：

- `lk_probe.img` 能开机 → 证书绕过可用
- 不能开机 → 这条方案对这台固件不成立，后面所有事都不用做了

**这是整个方案里唯一"赌"的一步**，所以必须先用探针单独验证，把「证书绕过」和「门禁补丁」两个变量分开。

## 二、AVB 门禁

### 正确的改法：只改一个调用点

LK 里有一个按分区名查"要不要验签"的函数：

```asm
0x8630c: add x0, sp, #0x18
0x86310: bl  #0x37954        ; get_img_auth_required(name)
0x86314: mov w26, w0
0x86318: cmp w0, #0
...
0x8644c: cbz w26, 0x86488    ; w26==0 就跳过摘要比对
```

把这个 `bl` 换成 `mov w0, wzr`：

```
0x86310: 97 fe c5 91  →  2a 1f 03 e0     (mov w0, wzr)
```

作用域只有这一个调用点，其他分区的验签照常。

### 错误的改法：把 21 条门禁表全清零

门禁表在 `0x148df0`，21 条 × `0x30` 字节，判定字段在 `+0x20/+0x24/+0x28/+0x2c`，
取值由锁状态选一组再 `& 1`。

全清零看起来最省事，**实测会卡第一屏无限重启**——因为 LK 把 `lk_main_dtb` 等分区的加载也一起跳过了，
流程走不下去。

**别这么干。**

## 三、启动状态

### 枚举值（实测，不是推测）

| 值 | 含义 |
|---|---|
| **0** | **green** |
| 2 | orange |
| 3 | **red → 弹「系统文件被破坏无法开机」** |

这一条是在真机上撞出来的：最初改成 3，连**原厂镜像**都报「文件损坏」。
改成 0 立刻正常。

### 三个 setter

```asm
0x5ebd0: 52 80 00 60  (mov w0, #3)  →  2a 1f 03 e0  (mov w0, wzr)
0x5ed94: 52 80 00 40  (mov w0, #2)  →  2a 1f 03 e0  (mov w0, wzr)
0x5ef88: 2a 1f 03 e0  (本来就是 wzr)  保持不变
```

三处都要改。改动后 `ro.boot.verifiedbootstate` 与 `oplusboot.verifiedbootstate` 都是 `green`。

### 损坏画面的显示函数

`0x5e7f4` 是弹「系统文件被损坏」并卡死的函数，触发条件是 AVB 结果结构体的 `+0x130` 等于 2，
或内部读到的状态等于 1。

如果要额外兜底，可以把 `0x5e7f4` 首指令换成 `ret`（`c0 03 5f d6`）：
它只负责显示，返回值没人用，直接返回等于"状态正常"。

> 这一条在 v5/v6 里**没有启用**（状态改成 0 之后它不会被触发）。
> 只有在需要压制其他来源的损坏提示时才用。

## 四、`device_state` 伪装

`ro.boot.vbmeta.device_state` 来自 LK 拼的 cmdline，写入点在：

```asm
0x6fd9c: ldurb w8, [x29, #-0x40]     ; 标志位
0x6fda0: adrp  x9, #0xa5000
0x6fda4: adrp  x10, #0xba000
0x6fda8: add   x9,  x9,  #0xa3f      ; → 0xa5c3f = "unlocked"
0x6fdac: add   x10, x10, #0x25a      ; → 0xba45a = "locked"
0x6fdb0: cmp   w8, #0
0x6fdb8: csel  x2, x10, x9, eq       ; w8==0 → "locked"，否则 → "unlocked"
0x6fdbc: add   x1, x1, #0x46a        ; → 0xce66a = "androidboot.vbmeta.device_state"
0x6fdc4: bl    #0x700d0              ; 写进 cmdline
```

改成无条件取 `x10`：

```
0x6fdb8: 42 01 89 9a  →  e2 03 0a aa     (mov x2, x10)
```

改完 `device_state` 固定输出 `locked`。

**注意这只影响属性层面。** 硬件密钥认证（TEE）读的是真实锁状态，改不了。

## 五、地址表（v5 / v6 实际使用）

| 地址 | 原指令 | 改成 | 作用 |
|---|---|---|---|
| `0x5ebd0` | `mov w0,#3` | `mov w0,wzr` | 状态 → 0 (green) |
| `0x5ed94` | `mov w0,#2` | `mov w0,wzr` | 状态 → 0 (green) |
| `0x5ef88` | `mov w0,wzr` | 不变 | 本来就是 0 |
| `0x86310` | `bl get_img_auth_required` | `mov w0,wzr` | 只跳过 boot 验签 |
| `0x6fdb8` | `csel x2,x10,x9,eq` | `mov x2,x10` | `device_state` → locked |

**总计 16 字节**（4 处 × 4 字节）。

版本差异：

| 版本 | 改动 | 结果 |
|---|---|---|
| v1 | 门禁表全清零 + 状态→3 | 弹「文件损坏」（3 = red） |
| v2 | v1 + 损坏画面函数 `ret` | 同样损坏（根因是 3） |
| v3 | 门禁表全清零 + 状态→0 + 画面 `ret` | **卡第一屏无限重启**（表清零破坏了 LK 流程） |
| v4 | 只改状态→0 | 能开机，green（证明 0 = green） |
| v5 | 状态→0 + 只跳 boot 验签 | **可用** |
| v6 | v5 + `device_state`→locked | **当前使用** |

## 六、推导方法（换机型时怎么重新定位）

1. **拆容器**：`build-part-img.py extract`，拿到 `lk` payload
2. **加载基址换算**：payload 从文件偏移 `0x200` 开始，所以
   `字符串地址 = P + A + 0x200`（当 `code_off & 0xfff >= 0x200`），否则 `= P + A - 0xe00`
   用一条必然出现的中文字符串（比如 `Orange State`）反推校准
3. **找字符串 xref**：`adrp` + `add` 两条配对，注意 `adrp` 是页对齐的
4. **验证枚举值**：不要靠猜。改成候选值、刷机、看实际现象，一次一个变量
5. **每次改完必须验证证书链**：`verify_mtk_image.py --all`，四个子镜像都要 VALID

## 工具

来自 [pwnage24mtk](https://github.com/pwnage24/pwnage24mtk)（ace2v 项目内附带）：

```sh
sign_mtk_cert.py    image -w --legacy -o out.img      # legacy 注入签名
build-part-img.py   replace 原厂.img --name lk --file payload.bin -o out.img
verify_mtk_image.py out.img --all                     # 校验四段证书链
```

容器重建后必须补零到 `5242880` 字节（分区大小），否则刷不进去。
