# -*- coding: utf-8 -*-
"""校验生成的模型 JSON：能解析，且每个 element 的 from < to（原版要求，否则模型烘焙失败 → 紫黑块）。

用法：py _tools/check_models.py
"""
import json
import os

RP = r"d:\Program Files (x86)\Minecrafts\PCL 正式版 2.10.3 (1)\.minecraft\versions\26.2-Fabric 0.19.5 Rhythm_Axe\resourcepacks\rhythm_axe 节奏地图资源包"
BASE = os.path.join(RP, "assets", "rhythm_axe")
bad = 0
checked = 0
for sub in ("models/item", "items"):
    d = os.path.join(BASE, sub)
    if not os.path.isdir(d):
        continue
    for f in sorted(os.listdir(d)):
        if not f.endswith(".json"):
            continue
        checked += 1
        p = os.path.join(d, f)
        try:
            j = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            print("PARSE FAIL", f, e)
            bad += 1
            continue
        for e in j.get("elements", []):
            fr, to = e.get("from"), e.get("to")
            if fr and to:
                for i in range(3):
                    if fr[i] >= to[i]:
                        print("EMPTY/INVERTED", f, e.get("name"), "axis", i, fr, to)
                        bad += 1
            rot = e.get("rotation")
            if rot and ("x" in rot or "y" in rot or "z" in rot) and "axis" not in rot:
                print("BAD ROTATION FORMAT (三轴非法)", f, e.get("name"), rot)
                bad += 1
print("checked %d files, bad = %d" % (checked, bad))
