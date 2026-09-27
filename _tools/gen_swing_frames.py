# -*- coding: utf-8 -*-
"""生成手持挥砍动画的逐帧物品模型、items 定义与数据包 item_modifier。

用法：
    py _tools/gen_swing_frames.py

工作流：
    1) 你做「关键帧」模型，放到：
       assets/rhythm_axe/models/item/keyframes/<clip>_k<帧号>.json
       clip ∈ {down, left, up, right}；帧号 ∈ 0..15（关键帧落在哪一帧）。
       每个文件只需覆盖 display.firstperson_righthand（rotation/translation/scale），
       父模型固定为 rhythm_axe:item/axe_base。
    2) 运行本脚本 → 自动插值生成 0..15 帧。

产出（幂等，可重复运行）：
    assets/rhythm_axe/items/swing_<clip>_<frame>.json        物品模型定义（item_model 指向）
    assets/rhythm_axe/models/item/swing_<clip>_<frame>.json  插值后的帧模型
    data/.../item_modifier/swing/<clip>_<frame>.json         数据包 modifier（设 item_model）

插值：非均匀 Catmull-Rom（Barry-Goldman，与 Blockbench catmullrom 同源手感），
      每个关键帧的 9 个通道（旋转/平移/缩放 × xyz）独立插值；
      关键帧 <2 个时退化为线性/常量；帧号在首尾关键帧之外时夹取端点值；
      没有任何关键帧时，全部 16 帧 = 原版第一人称静止位。
"""
import json
import os
import re

RP = r"d:\Program Files (x86)\Minecrafts\PCL 正式版 2.10.3 (1)\.minecraft\versions\26.2-Fabric 0.19.5 Rhythm_Axe\resourcepacks\rhythm_axe 节奏地图资源包"
DP = r"d:\Program Files (x86)\Minecrafts\PCL 正式版 2.10.3 (1)\.minecraft\versions\26.2-Fabric 0.19.5 Rhythm_Axe\saves\节奏地图2026 - 高版本重置版\datapacks\rhythm_axe"

FRAMES = 16
CLIPS = ["down", "left", "up", "right"]

REST = {
    "rotation": [0.0, -90.0, 25.0],
    "translation": [1.13, 3.2, 1.13],
    "scale": [0.68, 0.68, 0.68],
}

KEYFRAME_DIR = os.path.join(RP, "assets", "rhythm_axe", "models", "item", "keyframes")
ITEMS_DIR = os.path.join(RP, "assets", "rhythm_axe", "items")
MODELS_DIR = os.path.join(RP, "assets", "rhythm_axe", "models", "item")
MODIFIER_DIR = os.path.join(DP, "data", "rhythm_axe", "item_modifier", "swing")


def load_keyframes(clip):
    """返回 {frame: 9 个通道值}，按文件名 <clip>_k<帧号>.json 解析。"""
    found = {}
    if not os.path.isdir(KEYFRAME_DIR):
        return found
    pattern = re.compile(r"^" + clip + r"_k(\d+)\.json$")
    for name in os.listdir(KEYFRAME_DIR):
        m = pattern.match(name)
        if not m:
            continue
        frame = int(m.group(1))
        if frame < 0 or frame >= FRAMES:
            print("  [警告] %s 帧号 %d 超出 0..%d，跳过" % (name, frame, FRAMES - 1))
            continue
        with open(os.path.join(KEYFRAME_DIR, name), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        disp = data.get("display", {}).get("firstperson_righthand")
        if not disp:
            print("  [警告] %s 缺少 display.firstperson_righthand，跳过" % name)
            continue
        vals = []
        for key in ("rotation", "translation", "scale"):
            v = disp.get(key, REST[key])
            vals.extend([float(v[0]), float(v[1]), float(v[2])])
        found[frame] = vals
    return found


def sample_channel(keys, frame):
    """keys: 已排序的 [(frame, value)]；返回该通道在 frame 的值。"""
    frames = [k[0] for k in keys]
    if not keys:
        return 0.0
    if frame <= frames[0]:
        return keys[0][1]
    if frame >= frames[-1]:
        return keys[-1][1]
    if len(keys) == 1:
        return keys[0][1]
    if len(keys) == 2:
        f0, v0 = keys[0]
        f1, v1 = keys[1]
        t = (frame - f0) / (f1 - f0)
        return v0 + (v1 - v0) * t
    i = 0
    while i < len(frames) - 1 and frame > frames[i + 1]:
        i += 1
    idx = [i - 1, i, i + 1, i + 2]
    p = []
    t = []
    for k in idx:
        if k < 0:
            p.append(keys[0][1])
            t.append(float(frames[0] - (frames[1] - frames[0])))
        elif k >= len(keys):
            p.append(keys[-1][1])
            t.append(float(frames[-1] + (frames[-1] - frames[-2])))
        else:
            p.append(keys[k][1])
            t.append(float(frames[k]))
    p0, p1, p2, p3 = p
    t0, t1, t2, t3 = t
    x = float(frame)
    a1 = (t1 - x) / (t1 - t0) * p0 + (x - t0) / (t1 - t0) * p1
    a2 = (t2 - x) / (t2 - t1) * p1 + (x - t1) / (t2 - t1) * p2
    a3 = (t3 - x) / (t3 - t2) * p2 + (x - t2) / (t3 - t2) * p3
    b1 = (t2 - x) / (t2 - t0) * a1 + (x - t0) / (t2 - t0) * a2
    b2 = (t3 - x) / (t3 - t1) * a2 + (x - t1) / (t3 - t1) * a3
    return (t2 - x) / (t2 - t1) * b1 + (x - t1) / (t2 - t1) * b2


def clean(v):
    v = round(v, 3)
    return 0.0 if abs(v) < 0.0005 else v


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)


def main():
    total = 0
    for clip in CLIPS:
        kf = load_keyframes(clip)
        frames = sorted(kf)
        if frames:
            print("[%s] 关键帧帧号: %s" % (clip, frames))
        else:
            print("[%s] 无关键帧 -> 16 帧全用静止位" % clip)
        for frame in range(FRAMES):
            if not kf:
                disp = {"rotation": list(REST["rotation"]),
                        "translation": list(REST["translation"]),
                        "scale": list(REST["scale"])}
            else:
                disp = {}
                for key, off in (("rotation", 0), ("translation", 3), ("scale", 6)):
                    arr = []
                    for j in range(3):
                        keys_j = sorted([(f, vals[off + j]) for f, vals in kf.items()])
                        arr.append(clean(sample_channel(keys_j, frame)))
                    disp[key] = arr
            write_json(os.path.join(MODELS_DIR, "swing_%s_%d.json" % (clip, frame)),
                       {"parent": "rhythm_axe:item/axe_base",
                        "display": {"firstperson_righthand": disp}})
            write_json(os.path.join(ITEMS_DIR, "swing_%s_%d.json" % (clip, frame)),
                       {"model": {"type": "minecraft:model",
                                  "model": "rhythm_axe:item/swing_%s_%d" % (clip, frame)}})
            write_json(os.path.join(MODIFIER_DIR, "%s_%d.json" % (clip, frame)),
                       {"function": "minecraft:set_components",
                        "components": {"minecraft:item_model": "rhythm_axe:swing_%s_%d" % (clip, frame)}})
            total += 1
    print("完成：%d 段 × %d 帧 = %d 帧，× 3 类文件 = %d 个文件" % (len(CLIPS), FRAMES, total, total * 3))


if __name__ == "__main__":
    main()
