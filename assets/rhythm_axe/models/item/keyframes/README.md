# 手持挥砍动画 —— 关键帧约定

你在这里放**关键帧模型**，我（生成器脚本）读它们并插值出 0..15 的中间帧。

## 命名规则

放到各自的分段子目录里：`keyframes/<clip>/<clip>_k<帧号>.json`

- `clip` ∈ `down` / `left` / `up` / `right`（四段挥砍）
- `帧号` ∈ 0..15 的整数，表示这个关键帧落在动画的哪一帧

例：`keyframes/down/down_k0.json`、`down_k4.json`、`down_k8.json`、`down_k15.json`

## 文件内容

两种写法都行（只要带 `display.firstperson_righthand`）：
- 精简版：父模型 `rhythm_axe:item/axe_base`，只写 firstperson
- 完整版：直接复制原版铁斧 JSON（`parent: minecraft:item/handheld` + `textures.layer0`），改 `display` 里的 firstperson

精简版示例：

```json
{
    "parent": "rhythm_axe:item/axe_base",
    "display": {
        "firstperson_righthand": {
            "rotation": [0, -90, 25],
            "translation": [1.13, 3.2, 1.13],
            "scale": [0.68, 0.68, 0.68]
        }
    }
}
```

- `rotation`：欧拉角，单位**度**，`[x, y, z]`
- `translation`：单位 **1/16 格**
- `scale`：倍数（1 = 原大小）

上面的数值就是**原版第一人称静止位**，第 0 帧和最后一帧通常用它。

## 插值行为（可配置）

默认**三次方缓入缓出**（`ease_in_out`）。两种改法：

- 全局：`keyframes/easing.json`
- 单段：`keyframes/<clip>/easing.json`（只写 `{"default": "..."}`，优先于全局）

```json
{
    "default": "ease_in_out",
    "clips": { "down": "ease_in_out" }
}
```

| 模式 | 效果 |
| --- | --- |
| `ease_in_out` | 三次方缓入缓出（默认） |
| `ease_in` | 三次方缓入（慢 → 快） |
| `ease_out` | 三次方缓出（快 → 慢） |
| `linear` | 线性 |
| `catmullrom` | Catmull-Rom（带轻微过冲） |

- 缓动按**关键帧之间的每一段**独立作用（每段开头/结尾速度归零 → 每个关键帧姿态都会短暂“定”一下）
- 9 个通道（旋转/平移/缩放 × xyz）独立插值；**缺写的通道**回落到原版静止位（旋转 [0,-90,25]、平移 [1.13,3.2,1.13]、缩放 0.68）
- 帧号范围 **0..15**（16 帧）；写 `k16` 会被当作最后一帧 15 处理
- 只有 1 个关键帧 → 16 帧全是那个姿势；没有任何关键帧 → 16 帧全用静止位

## 生成

```powershell
py _tools/gen_swing_frames.py
```

会产出三类文件：

| 路径 | 作用 |
| --- | --- |
| `assets/rhythm_axe/items/swing_<clip>_<frame>.json` | 物品模型定义（`item_model` 指向它） |
| `assets/rhythm_axe/models/item/swing_<clip>_<frame>.json` | 插值后的帧模型 |
| 数据包 `data/rhythm_axe/item_modifier/swing/<clip>_<frame>.json` | 设 `item_model` 的 modifier |

> 数据包侧已经按 `rhythm_axe:swing_<clip>_<frame>` 这个 ID 拼名字，**不要改命名规则**。
