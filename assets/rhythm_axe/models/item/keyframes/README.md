# 手持挥砍动画 —— 关键帧约定

你在这里放**关键帧模型**，我（生成器脚本）读它们并插值出 0..15 的中间帧。

## 命名规则

```
<clip>_k<帧号>.json
```

- `clip` ∈ `down` / `left` / `up` / `right`（四段挥砍）
- `帧号` ∈ 0..15 的整数，表示这个关键帧落在动画的哪一帧

例：`down_k0.json`、`down_k4.json`、`down_k8.json`、`down_k15.json`

## 文件内容

每个关键帧**只写第一人称右手显示变换**，父模型固定为 `rhythm_axe:item/axe_base`：

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

## 插值行为

- 每个关键帧的 9 个通道（旋转/平移/缩放 × xyz）独立做 **Catmull-Rom** 插值（手感与 Blockbench `catmullrom` 一致）
- 只有 1 个关键帧 → 16 帧全是那个姿势；2 个关键帧 → 线性
- 帧号在首/尾关键帧之外 → 夹取端点值（不越界）
- 没有任何关键帧 → 16 帧全用静止位

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
