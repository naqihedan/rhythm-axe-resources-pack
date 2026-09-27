# -*- coding: utf-8 -*-
"""一次性把「斧头本体 element + trail 残影 element」注入所有关键帧。

用法：py _tools/add_trail_to_keyframes.py
之后记得重跑 gen_swing_frames.py 重新生成插值帧。
"""
import copy
import json
import os

RP = r"d:\Program Files (x86)\Minecrafts\PCL 正式版 2.10.3 (1)\.minecraft\versions\26.2-Fabric 0.19.5 Rhythm_Axe\resourcepacks\rhythm_axe 节奏地图资源包"
KEYFRAME_DIR = os.path.join(RP, "assets", "rhythm_axe", "models", "item", "keyframes")

# 用户 3D 斧头（up_k11）里的斧头本体元素，从该文件读取；#2 纹理引用统一改成 #layer0（随皮肤走）
SRC_AXE = os.path.join(KEYFRAME_DIR, "up", "up_k11.json")


def load_axe_elements():
    """从 up_k11 提取斧头本体 elements（除 trail 外），并把 #2 纹理引用改成 #layer0。"""
    with open(SRC_AXE, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for e in data.get("elements", []):
        if e.get("name") == "trail":
            continue
        e = copy.deepcopy(e)
        for face in e.get("faces", {}).values():
            if face.get("texture") == "#2":
                face["texture"] = "#layer0"
        out.append(e)
    return out

# 残影：照抄 up_k3 的 trail（#trail 专用贴图）
TRAIL_ELEMENT = {
    "name": "trail",
    "from": [10, -5, 8],
    "to": [20, 4, 8],
    "rotation": {"x": 0, "y": 2.5, "z": 45, "origin": [10, -5, 8]},
    "faces": {
        "north": {"uv": [16, 0, 0, 16], "texture": "#trail"},
        "east": {"uv": [2, 0, 2, 2], "texture": "#missing"},
        "south": {"uv": [0, 0, 16, 16], "texture": "#trail"},
        "west": {"uv": [0, 0, 0, 2], "texture": "#missing"},
        "up": {"uv": [0, 0, 10, 0], "texture": "#missing"},
        "down": {"uv": [0, 2, 10, 2], "texture": "#missing"}
    }
}

TEXTURES = {
    "layer0": "rhythm_axe:item/iron_axe",
    "trail": "rhythm_axe:item/trail3"
}


def main():
    axe_elements = load_axe_elements()
    for direction in ("down", "left", "up", "right"):
        d = os.path.join(KEYFRAME_DIR, direction)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith(".json") or name == "easing.json":
                continue
            path = os.path.join(d, name)
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            data["textures"] = copy.deepcopy(TEXTURES)
            data["elements"] = [copy.deepcopy(TRAIL_ELEMENT)] + copy.deepcopy(axe_elements)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            print("已更新 %s/%s" % (direction, name))


if __name__ == "__main__":
    main()
