# -*- coding: utf-8 -*-
"""生成手持挥砍动画的逐帧物品模型、items 定义与数据包 item_modifier。

用法：
    py _tools/gen_swing_frames.py

工作流：
    1) 你做「关键帧」模型，放到：
       assets/rhythm_axe/models/item/keyframes/<clip>_k<帧号>.json
       clip ∈ {down, left, up, right}；帧号 = 任意非负整数（最后一帧由编号最大的关键帧决定）。
       每个文件只需覆盖 display.firstperson_righthand（rotation/translation/scale）；
       生成帧会整体复制该关键帧 JSON，只替换 firstperson 显示变换。
    2) 运行本脚本 → 自动插值生成 0..(最后一帧) 帧。

产出（幂等，可重复运行）：
    assets/rhythm_axe/items/swing_<clip>_<frame>.json        物品模型定义（item_model 指向）
    assets/rhythm_axe/models/item/swing_<clip>_<frame>.json  插值后的帧模型
    data/.../item_modifier/swing/<clip>_<frame>.json         数据包 modifier（设 item_model）

插值：默认「三次方缓入缓出」（ease_in_out），关键帧之间的每一段独立缓动；
      可选 linear / ease_in / ease_out / ease_in_out / catmullrom，通过 keyframes/easing.json 指定；
      每个关键帧的 9 个通道（旋转/平移/缩放 × xyz）独立插值；
      缺写的通道回落到原版静止位（旋转 [0,-90,25]、平移 [1.13,3.2,1.13]、缩放 0.68）；
      没有任何关键帧时，生成 16 帧静止位。
"""
import copy
import json
import math
import os
import re

RP = r"d:\Program Files (x86)\Minecrafts\PCL 正式版 2.10.3 (1)\.minecraft\versions\26.2-Fabric 0.19.5 Rhythm_Axe\resourcepacks\rhythm_axe 节奏地图资源包"
DP = r"d:\Program Files (x86)\Minecrafts\PCL 正式版 2.10.3 (1)\.minecraft\versions\26.2-Fabric 0.19.5 Rhythm_Axe\saves\节奏地图2026 - 高版本重置版\datapacks\rhythm_axe"

DEFAULT_FRAMES = 16
MAX_FRAMES = 64
CLIPS = ["down", "left", "up", "right"]

REST = {
    "rotation": [0.0, -90.0, 25.0],
    "translation": [1.13, 3.2, 1.13],
    "scale": [0.68, 0.68, 0.68],
}

# 斧头皮肤：编号 0..6 → 材质纹理（模型 layer0）。换编号对应的材质就改这里。
SKINS = [
    "rhythm_axe:item/wooden_axe",     # 0 木
    "rhythm_axe:item/stone_axe",      # 1 石
    "rhythm_axe:item/copper_axe",     # 2 铜
    "rhythm_axe:item/iron_axe",       # 3 铁
    "rhythm_axe:item/golden_axe",     # 4 金
    "rhythm_axe:item/diamond_axe",    # 5 钻
    "rhythm_axe:item/netherite_axe",  # 6 下界合金
]

KEYFRAME_DIR = os.path.join(RP, "assets", "rhythm_axe", "models", "item", "keyframes")
ITEMS_DIR = os.path.join(RP, "assets", "rhythm_axe", "items")
MODELS_DIR = os.path.join(RP, "assets", "rhythm_axe", "models", "item")
MODIFIER_DIR = os.path.join(DP, "data", "rhythm_axe", "item_modifier", "swing")
FRAME_COUNTS_FILE = os.path.join(DP, "data", "rhythm_axe", "function", "utilization", "swing_item", "_frame_counts.mcfunction")


EASING = {
    "linear": lambda t: t,
    "ease_in": lambda t: t * t * t,
    "ease_out": lambda t: 1.0 - (1.0 - t) ** 3,
    "ease_in_out": lambda t: (4.0 * t * t * t) if t < 0.5 else (1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0),
}

DEFAULT_MODE = "ease_in_out"
EASING_FILE = os.path.join(KEYFRAME_DIR, "easing.json")
VALID_MODES = set(EASING.keys()) | {"catmullrom"}

# 每帧追加的手持 Y 位移补偿（抵消客户端“换物品”下坠动画；正 = 上移）
# ★ 生效前提：动画（含定格）期间必须**每刻都在换 item_model**，让客户端一直保持下坠状态；
#   一旦有哪一刻写了「相同的」模型，下坠就会松开，这 +10 就会把物品顶到悬空
COMPENSATION_Y = 10.0

# 残影 = 底边钉在锚点上、朝「上一帧斧头的位置」伸出去的旗子（形状取自 down_k0 的残影）
#   长度（Y 尺寸）= 锚点一帧内的实际位移（含转动）× 该系数
#   朝向：TRAIL_AIM_MODE = "xz" 时用绕 X / 绕 Z 两个角【精确】指向上一帧锚点；
#         = "x"  时只动绕 X 的角，取「离目标最近」的解（能指到的方向只有一条一维曲线）
#           —— down 段的快速帧里运动方向几乎平行于旗子宽度轴，只动 X 根本指不过去，
#              残影会被迫翻 180°（还会经过侧立的瞬间），所以默认用 "xz"
TRAIL_LENGTH_FACTOR = 1.0
TRAIL_AIM_MODE = "xz"                  # "xz" = 精确指向（推荐）；"x" = 只动绕 X 的角

# ★ 这两个值要跟 down_k0.json 里残影的 from 和 (to.x - from.x) 保持一致；改了 down_k0 记得同步
TRAIL_ANCHOR = (2.0, 2.0, 8.0)        # 旗子底边钉在斧柄上的点（也是旋转原点）
TRAIL_WIDTH = 14.0                    # 残影固定宽度（底边长度）

# 朝向角微调（只作用在「绕 X」那个角上）：实测反了/整体偏了就在这里调
TRAIL_ANGLE_SIGN = 1.0                # -1 = 正负颠倒
TRAIL_ANGLE_OFFSET = 0.0              # 整体再加几度


def read_easing_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def get_clip_mode(clip):
    """解析 clip 的插值：keyframes/<clip>/easing.json 优先，其次全局 keyframes/easing.json。"""
    per_clip = os.path.join(KEYFRAME_DIR, clip, "easing.json")
    if os.path.isfile(per_clip):
        mode = read_easing_file(per_clip).get("default", DEFAULT_MODE)
        if mode not in VALID_MODES:
            print("  [警告] %s/easing.json 的 default=%s 未知，回退 %s" % (clip, mode, DEFAULT_MODE))
            mode = DEFAULT_MODE
        return mode
    if os.path.isfile(EASING_FILE):
        data = read_easing_file(EASING_FILE)
        mode = (data.get("clips") or {}).get(clip, data.get("default", DEFAULT_MODE))
        if mode not in VALID_MODES:
            print("  [警告] easing.json 里 %s 的插值 %s 未知，回退 %s" % (clip, mode, DEFAULT_MODE))
            mode = DEFAULT_MODE
        return mode
    return DEFAULT_MODE


def find_trail(data):
    """在关键帧 JSON 里找残影 element：优先 name=trail，否则第一个 element。"""
    elems = data.get("elements")
    if not elems:
        return None
    for e in elems:
        if e.get("name") == "trail":
            return e
    return elems[0]


def rotation_xyz(rot):
    """把 rotation 统一成 (x, y, z) 三个角。

    MC / Blockbench 有两种写法：
      · 单轴 {"angle": 45, "axis": "z"}      ← Blockbench 只转一个轴时存的
      · 三轴 {"x": 0, "y": 0, "z": 45}
    两种都必须认，否则单轴写法会被读成 0°，朝向直接跑偏。
    """
    if "angle" in rot and "axis" in rot and str(rot["axis"]) in "xyz":
        out = [0.0, 0.0, 0.0]
        out["xyz".index(str(rot["axis"]))] = float(rot["angle"])
        return out
    return [float(rot.get("x", 0.0)), float(rot.get("y", 0.0)), float(rot.get("z", 0.0))]


def trail_channels(trail):
    """提取残影 element 的 12 个插值通道：from(3) to(3) rotation(3) origin(3)。"""
    vals = []
    for key in ("from", "to"):
        v = trail.get(key, [0.0, 0.0, 0.0])
        vals.extend([float(v[0]), float(v[1]), float(v[2])])
    rot = trail.get("rotation", {})
    vals.extend(rotation_xyz(rot))
    origin = rot.get("origin", [0.0, 0.0, 0.0])
    vals.extend([float(origin[0]), float(origin[1]), float(origin[2])])
    return vals


def apply_trail_geom(elements, geom):
    """把插值后的 12 通道几何写回 elements 里的残影 element（name=trail 或第一个）。"""
    target = None
    for e in elements:
        if e.get("name") == "trail":
            target = e
            break
    if target is None and elements:
        target = elements[0]
    if target is None:
        return
    target["from"] = [geom[0], geom[1], geom[2]]
    target["to"] = [geom[3], geom[4], geom[5]]
    # ★ 必须整块替换：关键帧里残影可能写成单轴形式 {"angle":45,"axis":"z"}（Blockbench 保存的写法），
    #   只往里塞 x/y/z 会变成两套写法并存，MC 只会认其中一套 → 另一套直接失效。
    target["rotation"] = {"x": geom[6], "y": geom[7], "z": geom[8],
                          "origin": [geom[9], geom[10], geom[11]]}


def _rot_matrix(rx, ry, rz):
    """★ 元素旋转矩阵 R = Rz·Ry·Rx（先绕 X、再绕 Y、最后绕 Z），输入为度。

    来源（26.2 客户端 jar 字节码，不是猜的）：
      CuboidModelElement$Deserializer 里，rotation 写了 "x"/"y"/"z" 就造
      CuboidRotation$EulerXYZRotation → 内部调 Quaternionf.rotationZYX(z, y, x)，
      JOML 的 rotationZYX 等价于 rotationZ(z).rotateY(y).rotateX(x)（后乘），
      作用到向量上是「X 先转」，也就是矩阵 Rz·Ry·Rx。
      （只写 "angle"+"axis" 时走 SingleAxisRotation → Matrix4f.rotateAround，右手定则。）
    """
    a, b, c = math.radians(rx), math.radians(ry), math.radians(rz)
    ca, sa = math.cos(a), math.sin(a)
    cb, sb = math.cos(b), math.sin(b)
    cc, sc = math.cos(c), math.sin(c)
    return (
        (cc * cb, cc * sb * sa - sc * ca, cc * sb * ca + sc * sa),
        (sc * cb, sc * sb * sa + cc * ca, sc * sb * ca - cc * sa),
        (-sb,     cb * sa,                cb * ca),
    )


def _mat_mul(m, n):
    return tuple(tuple(sum(m[i][k] * n[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _rot_matrix_display(rx, ry, rz):
    """★ 显示变换矩阵 R = Rx·Ry·Rz（先绕 Z、再绕 Y、最后绕 X）——【和元素旋转刚好相反】

    来源：net/minecraft/client/resources/model/cuboid/ItemTransform 的常量池里有
      rotationXYZ（Quaternionf.rotationXYZ = qx·qy·qz → 作用到向量上「Z 先转」）
      + rotate(Quaternionfc)，也就是 display.firstperson_righthand 的 rotation [x,y,z]。
    ⚠ 以前这里误用了元素那套 Rz·Ry·Rx，会让「锚点世界位置」和「上一帧位置换算回模型空间」
      整圈偏掉十来度，残影长度和朝向都会跟着歪。
    """
    a, b, c = math.radians(rx), math.radians(ry), math.radians(rz)
    ca, sa = math.cos(a), math.sin(a)
    cb, sb = math.cos(b), math.sin(b)
    cc, sc = math.cos(c), math.sin(c)
    mx = ((1.0, 0.0, 0.0), (0.0, ca, -sa), (0.0, sa, ca))
    my = ((cb, 0.0, sb), (0.0, 1.0, 0.0), (-sb, 0.0, cb))
    mz = ((cc, -sc, 0.0), (sc, cc, 0.0), (0.0, 0.0, 1.0))
    return _mat_mul(mx, _mat_mul(my, mz))


def _mat_vec(m, v):
    return [m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2]]


def _anchor_world(disp):
    """残影锚点（TRAIL_ANCHOR）在 display/世界空间里的位置：v' = T + R·(S ⊙ v)。"""
    r = _rot_matrix_display(disp["rotation"][0], disp["rotation"][1], disp["rotation"][2])
    s = disp["scale"]
    p = _mat_vec(r, [TRAIL_ANCHOR[i] * s[i] for i in range(3)])
    t = disp["translation"]
    return [p[0] + t[0], p[1] + t[1], p[2] + t[2]]


def _display_inverse(u, disp):
    """display 变换的逆（作用于点）：D⁻¹(u) = (1/S) ⊙ (Rᵀ·(u − T))。"""
    r = _rot_matrix_display(disp["rotation"][0], disp["rotation"][1], disp["rotation"][2])
    rt = ((r[0][0], r[1][0], r[2][0]),
          (r[0][1], r[1][1], r[2][1]),
          (r[0][2], r[1][2], r[2][2]))
    t = disp["translation"]
    rd = _mat_vec(rt, [u[0] - t[0], u[1] - t[1], u[2] - t[2]])
    s = disp["scale"]
    return [rd[0] / s[0], rd[1] / s[1], rd[2] / s[2]]


def trail_motion(disp_from, disp_to):
    """算出这一帧残影的 (长度, 指向上一帧锚点的单位方向 / None)。

    把「上一帧锚点位置」用 display 逆变换换算回**当前帧的模型空间**，
    得到的就是「锚点相对上一帧动了多少」；拖尾该伸的方向就是它的反向，
    也就是从当前锚点指向上一帧锚点。
    """
    w_prev = _anchor_world(disp_from)
    w_cur = _anchor_world(disp_to)
    d = [w_cur[i] - w_prev[i] for i in range(3)]
    length = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
    p_prev = _display_inverse(w_prev, disp_to)
    v = [p_prev[i] - TRAIL_ANCHOR[i] for i in range(3)]
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n < 1e-6:
        return length, None
    return length, [v[i] / n for i in range(3)]


def _transpose(m):
    return ((m[0][0], m[1][0], m[2][0]),
            (m[0][1], m[1][1], m[2][1]),
            (m[0][2], m[1][2], m[2][2]))


def aim_rotation_x(u, ry, rz):
    """只解「绕 X 的角」：让旗子的外伸方向（局部 +Y）尽量贴近单位方向 u。

    绕 Y / 绕 Z 的角本函数一概不碰（用关键帧里手写的值），
    于是旗子指得到的方向只有一条一维曲线，这里取曲线上离 u 最近的那个点：
      · R = Rz·Ry·Rx ⟹ 旗子方向 = (Rz·Ry)·(0, cos rx, sin rx)
      · 令 w = (Rz·Ry)ᵀ·u，贴合度 = w_y·cos rx + w_z·sin rx
      · 取极大 → rx = atan2(w_z, w_y)，解析最优，不用迭代
    ★ 标定（down_k0）：z=45、rx=0 时方向 = (−sin45, cos45, 0) ∝ (−1,1,0)，与手写朝向一致。
    """
    w = _mat_vec(_transpose(_rot_matrix(0.0, ry, rz)), u)
    return math.degrees(math.atan2(w[2], w[1]))


def aim_rotation_xz(u, ry):
    """【精确指向】求绕 X / 绕 Z 两个角，使旗子外伸方向（局部 +Y）刚好等于单位方向 u。

    元素变换是 R = Rz·Ry·Rx，把 Ry 当固定值（关键帧里写的值），要解的就是 (rx, rz)：
      (Rz·Ry·Rx)·ŷ = Rz·(cb·sin rx, cos rx, sb·sin rx)
      ⟹ sin rx = u_z / cb      （cb = cos(ry)）
      ⟹ rz = atan2(u_y, u_x) − atan2(cos rx, cb·sin rx)
    两个自由度刚好够指到球面上的任意方向，所以这个模式下是【零误差】对准上一帧位置。
    """
    cb = math.cos(math.radians(ry))
    sb = math.sin(math.radians(ry))
    sz = u[2] / cb if abs(cb) > 1e-6 else u[2]
    rx = math.degrees(math.asin(max(-1.0, min(1.0, sz))))
    # Ry(ry)·Rx(rx)·ŷ = (sb·sin rx, cos rx, cb·sin rx)，再用 Rz(rz) 把它转到 (u_x, u_y)
    b = math.cos(math.radians(rx))
    a = sb * math.sin(math.radians(rx))
    rz = math.degrees(math.atan2(u[1], u[0]) - math.atan2(b, a))
    return rx, rz


def apply_trail(trail_geom, length, aim):
    """把残影写成「底边钉在锚点上、朝 aim 方向伸出 length 长」的旗子。
    - 几何：from = 锚点，to = 锚点 + (宽, 长, 0)（未旋转的局部空间）
    - 朝向：TRAIL_AIM_MODE = "xz" 用绕 X/Z 两个角精确指向；"x" 只改绕 X 的角
    - 旋转原点 = 锚点（底边贴着斧柄）
    """
    ax, ay, az = TRAIL_ANCHOR
    trail_geom[0], trail_geom[1], trail_geom[2] = ax, ay, az
    trail_geom[3] = ax + TRAIL_WIDTH
    trail_geom[4] = ay + abs(length) * TRAIL_LENGTH_FACTOR
    trail_geom[5] = az
    trail_geom[9], trail_geom[10], trail_geom[11] = ax, ay, az
    if aim is None:
        return
    if TRAIL_AIM_MODE == "xz":
        rx, rz = aim_rotation_xz(aim, trail_geom[7])
        trail_geom[6] = TRAIL_ANGLE_SIGN * rx + TRAIL_ANGLE_OFFSET
        trail_geom[8] = rz
    else:
        trail_geom[6] = (TRAIL_ANGLE_SIGN * aim_rotation_x(aim, trail_geom[7], trail_geom[8])
                     + TRAIL_ANGLE_OFFSET)


def load_keyframes(clip):
    """返回 {frame: {"display": 9通道, "trail": 12通道或 None}}，扫描 keyframes/ 下的关键帧。"""
    found = {}
    pattern = re.compile(r"^" + clip + r"_k(\d+)\.json$")
    dirs = [KEYFRAME_DIR, os.path.join(KEYFRAME_DIR, clip)]
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            m = pattern.match(name)
            if not m:
                continue
            frame = int(m.group(1))
            if frame < 0:
                print("  [警告] %s 帧号 %d 为负，跳过" % (name, frame))
                continue
            if frame >= MAX_FRAMES:
                print("  [警告] %s 帧号 %d 超出上限 %d，按 %d 处理" % (name, frame, MAX_FRAMES, MAX_FRAMES - 1))
                frame = MAX_FRAMES - 1
            with open(os.path.join(d, name), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            disp = data.get("display", {}).get("firstperson_righthand")
            if not disp:
                print("  [警告] %s 缺少 display.firstperson_righthand，跳过" % name)
                continue
            vals = []
            for key in ("rotation", "translation", "scale"):
                v = disp.get(key, REST[key])
                vals.extend([float(v[0]), float(v[1]), float(v[2])])
            trail = find_trail(data)
            trail_vals = trail_channels(trail) if trail is not None else None
            found[frame] = {"display": vals, "trail": trail_vals}
    return found


def load_template(clip):
    """返回该 clip 编号最小的关键帧文件的完整 JSON（作为生成帧的模板）。"""
    pattern = re.compile(r"^" + clip + r"_k(\d+)\.json$")
    dirs = [KEYFRAME_DIR, os.path.join(KEYFRAME_DIR, clip)]
    best_frame = None
    best_data = None
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            m = pattern.match(name)
            if not m:
                continue
            frame = int(m.group(1))
            if best_frame is None or frame < best_frame:
                best_frame = frame
                with open(os.path.join(d, name), "r", encoding="utf-8") as fh:
                    best_data = json.load(fh)
    return best_data


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


def sample_channel_eased(keys, frame, mode):
    """分段缓动：定位 frame 所在关键帧区间，再按 mode 缓动。"""
    frames = [k[0] for k in keys]
    if not keys:
        return 0.0
    if frame <= frames[0]:
        return keys[0][1]
    if frame >= frames[-1]:
        return keys[-1][1]
    if len(keys) == 1:
        return keys[0][1]
    i = 0
    while i < len(frames) - 1 and frame > frames[i + 1]:
        i += 1
    t = (frame - frames[i]) / (frames[i + 1] - frames[i])
    t = EASING[mode](t)
    return keys[i][1] + (keys[i + 1][1] - keys[i][1]) * t


def clean(v):
    v = round(v, 3)
    return 0.0 if abs(v) < 0.0005 else v


def unwrap(keys):
    """把相邻关键帧的角度差折到 [-180,180]，避免插值绕长路（如 Z 从 -129 到 +164 变成 +293 度大回旋）。"""
    if len(keys) < 2:
        return keys
    out = [list(keys[0])]
    for f, v in keys[1:]:
        prev = out[-1][1]
        while v - prev > 180.0:
            v -= 360.0
        while v - prev < -180.0:
            v += 360.0
        out.append([f, v])
    return out


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)


def write_frame_counts(counts):
    pairs = ", ".join("%s:%d" % (c, counts[c]) for c in CLIPS)
    content = ("# 自动生成（gen_swing_frames.py）——每段挥砍的帧数，start 时按 type 读取\n"
               "# ⚠️ 写的是存储「根键」，必须用 data merge（data modify 的目标必须带路径、不能是存储根）\n"
               "data merge storage rhythm_axe:swing_frames {%s}\n" % pairs)
    os.makedirs(os.path.dirname(FRAME_COUNTS_FILE), exist_ok=True)
    with open(FRAME_COUNTS_FILE, "w", encoding="utf-8") as fh:
        fh.write(content)


def cleanup_swing_files():
    """删除旧的 swing_*/restore* 文件（模型/items/modifier），避免命名方案变更后残留。"""
    for d in (MODELS_DIR, ITEMS_DIR):
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name.startswith("swing_") and name.endswith(".json"):
                p = os.path.join(d, name)
                if os.path.isfile(p):
                    os.remove(p)
    if os.path.isdir(MODIFIER_DIR):
        pattern = re.compile(r"^(?:(?:down|left|up|right)_\d+(?:_\d+)?b?|idle_\d+b?)\.json$")
        for name in os.listdir(MODIFIER_DIR):
            if name.startswith("restore") or pattern.match(name):
                p = os.path.join(MODIFIER_DIR, name)
                if os.path.isfile(p):
                    os.remove(p)


def write_skins():
    """生成每个皮肤的基础模型 axe_skin_<n>、静止 item_model axe_idle_<n> 与收尾/空闲循环用的 modifier。
    静止模型也要加同一份 +COMPENSATION_Y：空闲循环会让物品一直处于下坠状态，
    不加补偿的话斧头在手里会被压低一截。（REST 已核对 = 原版 item/handheld 的 firstperson_righthand）"""
    rest_disp = {"rotation": list(REST["rotation"]),
                 "translation": [REST["translation"][0], REST["translation"][1] + COMPENSATION_Y,
                                 REST["translation"][2]],
                 "scale": list(REST["scale"])}
    for n, layer0 in enumerate(SKINS):
        write_json(os.path.join(MODELS_DIR, "axe_skin_%d.json" % n),
                   {"parent": "minecraft:item/handheld",
                    "textures": {"layer0": layer0},
                    "display": {"firstperson_righthand": rest_disp}})
        write_json(os.path.join(ITEMS_DIR, "axe_idle_%d.json" % n),
                   {"model": {"type": "minecraft:model",
                              "model": "rhythm_axe:item/axe_skin_%d" % n}})
        write_json(os.path.join(MODIFIER_DIR, "restore_%d.json" % n),
                   {"function": "minecraft:set_components",
                    "components": {"minecraft:item_model": "rhythm_axe:axe_idle_%d" % n}})
        # 空闲循环用的「孪生份」：外观与 A 完全相同，只多一个 item_model ID
        write_json(os.path.join(ITEMS_DIR, "axe_idle_%db.json" % n),
                   {"model": {"type": "minecraft:model",
                              "model": "rhythm_axe:item/axe_skin_%d" % n}})
        write_json(os.path.join(MODIFIER_DIR, "idle_%db.json" % n),
                   {"function": "minecraft:set_components",
                    "components": {"minecraft:item_model": "rhythm_axe:axe_idle_%db" % n}})


def main():
    cleanup_swing_files()
    total = 0
    clip_counts = {}
    for clip in CLIPS:
        mode = get_clip_mode(clip)
        kf = load_keyframes(clip)
        frames = sorted(kf)
        count = (frames[-1] + 1) if frames else DEFAULT_FRAMES
        clip_counts[clip] = count
        if frames:
            print("[%s] 关键帧帧号: %s  帧数: %d  插值: %s" % (clip, frames, count, mode))
        else:
            print("[%s] 无关键帧 -> %d 帧全用静止位" % (clip, count))
        template = load_template(clip)
        # 第一遍：逐帧采样 display 与 trail 几何，存成数组
        sampled = []
        for frame in range(count):
            if not kf:
                disp = {"rotation": list(REST["rotation"]),
                        "translation": list(REST["translation"]),
                        "scale": list(REST["scale"])}
                trail_geom = None
            else:
                disp = {}
                for key, off in (("rotation", 0), ("translation", 3), ("scale", 6)):
                    arr = []
                    for j in range(3):
                        keys_j = sorted([(f, item["display"][off + j]) for f, item in kf.items()])
                        if key == "rotation":
                            keys_j = unwrap(keys_j)
                        if mode == "catmullrom":
                            v = sample_channel(keys_j, frame)
                        else:
                            v = sample_channel_eased(keys_j, frame, mode)
                        arr.append(clean(v))
                    disp[key] = arr
                trail_geom = None
                trail_items = [(f, item["trail"]) for f, item in kf.items() if item["trail"] is not None]
                if trail_items:
                    trail_geom = [0.0] * 12
                    for j in range(12):
                        keys_j = sorted([(f, tv[j]) for f, tv in trail_items])
                        if 6 <= j <= 8:
                            keys_j = unwrap(keys_j)
                        if mode == "catmullrom":
                            v = sample_channel(keys_j, frame)
                        else:
                            v = sample_channel_eased(keys_j, frame, mode)
                        trail_geom[j] = clean(v)
            sampled.append((disp, trail_geom))
        # 第二遍：按「上一帧 → 当前帧」的实际位移算残影长度与朝向
        #   ★ 用 prev→cur 而不是 cur→next：残影是「已经发生过的运动」的残留，
        #     用 next 会让残影领先一帧（挂在还没开始运动的那一帧上）
        #   ★ 必须在加 Y 补偿「之前」算：否则相邻帧一个带了补偿、一个还没带，
        #     位移里会凭空多出一个 10 → 长度看起来几乎不变
        angles = []
        resid = []
        prev_rx = prev_rz = None
        for frame, (disp, trail_geom) in enumerate(sampled):
            if trail_geom is None:
                continue
            prev_disp = sampled[max(frame - 1, 0)][0]
            length, aim = trail_motion(prev_disp, disp)
            # 最后一帧要定格，残影长度恒为 0（否则定格后会留一条静止的残影挂在斧头上）
            apply_trail(trail_geom, 0.0 if frame == count - 1 else length, aim)
            if aim is None:
                continue
            # 诊断：写进去的角度实际指到的方向，与目标方向还差多少度
            got = _mat_vec(_rot_matrix(trail_geom[6], trail_geom[7], trail_geom[8]), (0.0, 1.0, 0.0))
            d = max(-1.0, min(1.0, got[0] * aim[0] + got[1] * aim[1] + got[2] * aim[2]))
            resid.append((frame, math.degrees(math.acos(d))))
            # 角度连续化：±360° 是同一个旋转，按上一帧折叠一下，数值就不会来回跳
            rx, rz = trail_geom[6], trail_geom[8]
            if prev_rx is not None:
                while rx - prev_rx > 180.0:
                    rx -= 360.0
                while rx - prev_rx < -180.0:
                    rx += 360.0
                while rz - prev_rz > 180.0:
                    rz -= 360.0
                while rz - prev_rz < -180.0:
                    rz += 360.0
            trail_geom[6], trail_geom[8] = rx, rz
            prev_rx, prev_rz = rx, rz
            angles.append("(%d,%d)" % (round(rx), round(rz)))
        # 第三遍：加 Y 补偿 + 写帧
        for frame, (disp, trail_geom) in enumerate(sampled):
            disp["translation"][1] = clean(disp["translation"][1] + COMPENSATION_Y)
            # 每个皮肤一份帧模型：parent 指向 axe_skin_<n>，纹理随皮肤走
            for n in range(len(SKINS)):
                if template is not None:
                    obj = copy.deepcopy(template)
                    # 去掉 layer0（皮肤纹理从 axe_skin_<n> 继承），保留 trail 等其他自定义纹理
                    if "textures" in obj:
                        obj["textures"].pop("layer0", None)
                        if not obj["textures"]:
                            obj.pop("textures", None)
                    obj["parent"] = "rhythm_axe:item/axe_skin_%d" % n
                    obj.setdefault("display", {})["firstperson_righthand"] = disp
                    if trail_geom is not None:
                        apply_trail_geom(obj.setdefault("elements", []), trail_geom)
                else:
                    obj = {"parent": "rhythm_axe:item/axe_skin_%d" % n,
                           "display": {"firstperson_righthand": disp}}
                write_json(os.path.join(MODELS_DIR, "swing_%s_%d_%d.json" % (clip, frame, n)), obj)
                write_json(os.path.join(ITEMS_DIR, "swing_%s_%d_%d.json" % (clip, frame, n)),
                           {"model": {"type": "minecraft:model",
                                      "model": "rhythm_axe:item/swing_%s_%d_%d" % (clip, frame, n)}})
                write_json(os.path.join(MODIFIER_DIR, "%s_%d_%d.json" % (clip, frame, n)),
                           {"function": "minecraft:set_components",
                            "components": {"minecraft:item_model": "rhythm_axe:swing_%s_%d_%d" % (clip, frame, n)}})
                total += 1
        # 诊断：每帧残影的 (绕X角, 绕Z角) 与「离目标方向还差多少度」
        worst = [("#%d" % f, round(a)) for f, a in resid if a > 25.0]
        print("      残影角度 (rotX,rotZ): %s" % " ".join(angles))
        print("      朝向残差: 最大 %.1f°  平均 %.1f°%s" % (
            max([a for _, a in resid], default=0.0),
            (sum(a for _, a in resid) / len(resid)) if resid else 0.0,
            ("  偏差大的帧: " + " ".join("%s=%.0f°" % t for t in worst)) if worst else "  (全部对准)"))
        # 预热用的「孪生副本」：和最后一帧外观完全相同、只是 item_model ID 不同
        #   → 数据包在开头被原版忽略的那几刻交替写这两份，让物品「一直在变」，
        #     第 4 刻开始写动画帧时就能立即生效（不会再丢掉开头几帧）
        last = count - 1
        for n in range(len(SKINS)):
            base = "swing_%s_%d_%d" % (clip, last, n)
            write_json(os.path.join(ITEMS_DIR, base + "b.json"),
                       {"model": {"type": "minecraft:model", "model": "rhythm_axe:item/" + base}})
            write_json(os.path.join(MODIFIER_DIR, "%s_%d_%db.json" % (clip, last, n)),
                       {"function": "minecraft:set_components",
                        "components": {"minecraft:item_model": "rhythm_axe:" + base + "b"}})
    write_skins()
    write_frame_counts(clip_counts)
    print("完成：共 %d 帧 × %d 皮肤 = %d 个 modifier（模型/items 各一份）" % (total // len(SKINS), len(SKINS), total))


if __name__ == "__main__":
    main()
