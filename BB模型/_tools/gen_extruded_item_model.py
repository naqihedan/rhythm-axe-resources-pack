# -*- coding: utf-8 -*-
"""
Generate a Blockbench project (.bbmodel) that is a *3D extruded* version of a
Minecraft 16x16 item sprite.

Why: a vanilla item (item/generated) is baked into a 1-pixel thick plate. That is
faithful, but when you rotate it for a first person swing it collapses to a line
and disappears. Minecraft's own ItemModelGenerator actually bakes one quad per
run of opaque pixels; this script reproduces that as real boxes, so the axe keeps
its silhouette from every angle.

Usage:
    py gen_extruded_item_model.py <sprite.png> <out.bbmodel> [--name NAME]
                                  [--thickness PX] [--grip SPRITE_X,SPRITE_Y]
                                  [--eye X,Y,Z] [--target X,Y,Z] [--fov DEG]

Defaults: thickness 2 (vanilla is 1), grip at sprite pixel (4, 12) measured from
 the top-left, which lands on the axe handle just above its butt. The default
camera is this project's first-person angle.

The 4 swing clips are baked in and designed against that camera: the arc is a
roll about the model's Z axis (so the plate can never turn edge-on) and the hand
travels along the screen plane.
"""

import json
import math
import os
import struct
import sys
import zlib


# ------------------------------------------------------------------------ camera

def _sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def _norm(a):
    length = math.sqrt(_dot(a, a))
    return [v / length for v in a]


def _rotate_z(angle_deg, point):
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    return [point[0] * c - point[1] * s, point[0] * s + point[1] * c, point[2]]


def camera_basis(eye, target):
    """Return (forward, right, up) unit vectors; forward points eye -> target."""
    forward = _norm(_sub(target, eye))
    right = _norm(_cross(forward, [0.0, 1.0, 0.0]))
    up = _cross(right, forward)
    return forward, right, up


def to_model_offset(basis, dr, du, dd):
    """Screen-relative offset (right / up / towards camera) -> model space."""
    forward, right, up = basis
    return [dr * right[i] + du * up[i] - dd * forward[i] for i in range(3)]


# --------------------------------------------------------------------------- png

def read_png(path):
    """Minimal 8-bit PNG reader -> (width, height, channels, [rows of bytes])."""
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG: " + path)
    pos = 8
    idat = b""
    width = height = bitdepth = colortype = None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, bitdepth, colortype, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
            if bitdepth != 8 or interlace != 0:
                raise ValueError("only 8-bit non-interlaced PNGs are supported")
        elif tag == b"IDAT":
            idat += chunk
        elif tag == b"IEND":
            break

    channels = {0: 1, 2: 3, 4: 2, 6: 4}[colortype]
    stride = width * channels
    raw = zlib.decompress(idat)
    rows = []
    prev = bytearray(stride)
    p = 0
    for _ in range(height):
        ftype = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if ftype == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 255
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ftype == 3:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif ftype == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        elif ftype != 0:
            raise ValueError("unknown PNG filter %d" % ftype)
        rows.append(line)
        prev = line
    return width, height, channels, rows


def opaque_runs(path, alpha_cutoff=16):
    """-> list of rows, each a list of (x_start, x_end_inclusive) opaque runs."""
    width, height, channels, rows = read_png(path)
    result = []
    for y in range(height):
        line = rows[y]
        runs = []
        start = None
        for x in range(width):
            alpha = line[x * channels + channels - 1] if channels in (2, 4) else 255
            solid = alpha >= alpha_cutoff
            if solid and start is None:
                start = x
            elif not solid and start is not None:
                runs.append((start, x - 1))
                start = None
        if start is not None:
            runs.append((start, width - 1))
        result.append(runs)
    return width, height, result


# ------------------------------------------------------------------------ model

def build_elements(runs, thickness, grip_x, grip_y):
    """One box per run of opaque pixels; vertical runs with equal width are merged."""
    half = thickness / 2.0
    # map sprite (sx, sy) -> model: x = sx - grip_x, y = grip_y - sy
    boxes = []
    for sy, row_runs in enumerate(runs):
        for x1, x2 in row_runs:
            if boxes:
                last = boxes[-1]
                # same width and touching the previous sprite row -> extend it
                if last["sprite"] == (x1, x2) and last["rows"][1] == sy - 1:
                    last["rows"] = (last["rows"][0], sy)
                    continue
            boxes.append({"sprite": (x1, x2), "rows": (sy, sy)})

    elements = []
    for index, box in enumerate(boxes, start=1):
        sx1, sx2 = box["sprite"]
        sy1, sy2 = box["rows"]
        mx1 = sx1 - grip_x
        mx2 = sx2 + 1 - grip_x
        my1 = grip_y - (sy2 + 1)
        my2 = grip_y - sy1
        front = [sx1, sy1, sx2 + 1, sy2 + 1]
        left_edge = [sx1, sy1, sx1 + 1, sy2 + 1]
        right_edge = [sx2, sy1, sx2 + 1, sy2 + 1]
        elements.append({
            "name": "axe_%02d" % index,
            "box_uv": False,
            "from": [mx1, my1, -half],
            "to": [mx2, my2, half],
            "origin": [0, 0, 0],
            "rotation": [0, 0, 0],
            "autouv": 0,
            "color": 0,
            "faces": {
                # north and south both unmirrored: a flat plate is never seen from
                # both sides at once, so neither may be flipped.
                "north": {"uv": list(front), "texture": 0},
                "south": {"uv": list(front), "texture": 0},
                "east": {"uv": right_edge, "texture": 0},
                "west": {"uv": left_edge, "texture": 0},
                "up": {"uv": list(front), "texture": 0},
                "down": {"uv": list(front), "texture": 0},
            },
            "type": "cube",
            "uuid": "b3000000-0000-4000-8000-%012d" % index,
        })
    return elements


# ------------------------------------------------------------------- animations

def swing_animations(group_uuid, basis):
    """4 no-wind-up swing clips, designed against the first-person camera.

    Motion design:
      * The arc is a roll about the model's Z axis. That is the model's own XY
        plane, so the plate normal never changes: the item cannot turn edge-on
        no matter where the camera sits. Pitch and yaw stay at zero, both
        because they would tilt the plate and because mixed-axis values would
        depend on Blockbench's Euler order.
      * The hand (the model's origin) also travels along the screen plane. A
        clip that only rotates reads as a compass needle; the travel is what
        makes it read as a swing.
      * No wind-up: every clip moves in the swing direction from frame 1, hits
        the extreme fast, overshoots, then settles.

    Rows are (time, roll_z, offset_right, offset_up, offset_towards_camera);
    offsets are in blocks and get converted from screen space to model space.
    """
    def clip(index, name, length, rows):
        keyframes = []
        for i, (t, rz, dr, du, dd) in enumerate(rows, start=1):
            keyframes.append({
                "uuid": "e3000000-0000-4000-8000-%06d%04d" % (index, i),
                "channel": "rotation", "time": t, "color": -1,
                "interpolation": "catmullrom", "data_points": [{"x": 0, "y": 0, "z": rz}],
            })
        for i, (t, rz, dr, du, dd) in enumerate(rows, start=1):
            offset = to_model_offset(basis, dr, du, dd)
            keyframes.append({
                "uuid": "e3000000-0000-4000-8000-%06d%04d" % (index, 90 + i),
                "channel": "position", "time": t, "color": -1,
                "interpolation": "catmullrom",
                "data_points": [{"x": round(offset[0], 5),
                                 "y": round(offset[1], 5),
                                 "z": round(offset[2], 5)}],
            })
        return {
            "uuid": "d3000000-0000-4000-8000-%012d" % index,
            "name": name, "loop": "once", "override": False, "length": length,
            "snapping": 20, "selected": False, "saved": True, "path": "", "group_name": "",
            "animators": {group_uuid: {"name": "axe", "type": "bone",
                                       "rotation_global": False, "keyframes": keyframes}},
        }

    # Peaks sit well inside the usable roll window of the camera above. One block
    # of translation is only ~0.04 of a half-frame height at this distance, so the
    # offsets below are deliberately tiny: the swing is carried by the roll and
    # they only add a hair of secondary motion.
    return [
        # 0.40s / 8 frames -- short sharp leftward flick
        clip(1, "swing_snappy", 0.40, [
            (0.00,    0,  0.00,  0.00,  0.00),
            (0.05,   30, -0.05,  0.02,  0.02),
            (0.10,   62, -0.09,  0.03,  0.03),
            (0.20,   88, -0.13,  0.04,  0.04),
            (0.30,   24, -0.04,  0.01,  0.01),
            (0.35,  -18,  0.03, -0.01, -0.01),
            (0.40,    0,  0.00,  0.00,  0.00),
        ]),
        # 0.55s / 11 frames -- downward chop
        clip(2, "swing_chop", 0.55, [
            (0.00,    0,  0.00,  0.00,  0.00),
            (0.05,  -22,  0.02, -0.04,  0.04),
            (0.15,  -46,  0.04, -0.07,  0.07),
            (0.25,  -64,  0.05, -0.09,  0.09),
            (0.35,  -24,  0.02, -0.03,  0.03),
            (0.45,   18, -0.02,  0.02, -0.02),
            (0.55,    0,  0.00,  0.00,  0.00),
        ]),
        # 0.80s / 16 frames -- wide leftward sweep, the biggest arc
        clip(3, "swing_sweep", 0.80, [
            (0.00,    0,  0.00,  0.00,  0.00),
            (0.10,   46, -0.07,  0.02,  0.03),
            (0.20,   92, -0.14,  0.04,  0.05),
            (0.30,  132, -0.20,  0.06,  0.07),
            (0.45,   44, -0.07,  0.02,  0.02),
            (0.60,  -26,  0.04, -0.01, -0.02),
            (0.70,   10, -0.02,  0.01,  0.01),
            (0.80,    0,  0.00,  0.00,  0.00),
        ]),
        # 1.10s / 22 frames -- heavy downward smash, long after-shake
        clip(4, "swing_heavy", 1.10, [
            (0.00,    0,  0.00,  0.00,  0.00),
            (0.10,  -24,  0.03, -0.05,  0.06),
            (0.20,  -62,  0.06, -0.10,  0.14),
            (0.30,  -72,  0.06, -0.10,  0.14),
            (0.45,  -28,  0.03, -0.05,  0.05),
            (0.60,   22, -0.02,  0.03, -0.02),
            (0.75,   -9,  0.01, -0.01,  0.01),
            (0.90,    4,  0.00,  0.00, -0.01),
            (1.10,    0,  0.00,  0.00,  0.00),
        ]),
    ]


def build_project(sprite_path, name, thickness, grip, basis):
    width, height, runs = opaque_runs(sprite_path)
    group_uuid = "a3000000-0000-4000-8000-000000000001"
    elements = build_elements(runs, thickness, grip[0], grip[1])
    return {
        "meta": {"format_version": "5.0", "model_format": "free", "box_uv": False},
        "name": name,
        "model_identifier": name,
        "parent": "",
        "ambientocclusion": True,
        "front_gui_light": False,
        "variable_placeholders": "",
        "resolution": {"width": width, "height": height},
        "elements": elements,
        "groups": [{
            "name": "axe", "origin": [0, 0, 0], "rotation": [0, 0, 0], "color": 0,
            "uuid": group_uuid, "export": True, "mirror_uv": False, "shade": True,
            "reset": False, "locked": False, "visibility": True, "autouv": 0,
            "isOpen": True, "children": [],
        }],
        "outliner": [{
            "uuid": group_uuid, "isOpen": True,
            "children": [e["uuid"] for e in elements],
        }],
        "textures": [{
            "name": os.path.basename(sprite_path),
            "path": os.path.abspath(sprite_path),
            "relative_path": "textures/" + os.path.basename(sprite_path),
            "folder": "item", "namespace": "minecraft", "id": "0",
            "particle": False, "render_mode": "default", "visible": True,
            "internal": False, "saved": True,
            "uv_width": width, "uv_height": height,
            "uuid": "c3000000-0000-4000-8000-000000000001",
        }],
        "animations": swing_animations(group_uuid, basis),
    }


def report(project, basis, eye, target, grip, fov=45.0, aspect=16.0 / 9.0):
    """Numeric check that each clip actually reads as a swing from the camera.

    visible -- min |plate normal . direction to camera|. A pure Z roll keeps it
               constant; below ~0.35 the item is effectively edge-on.
    arc     -- how far the axe head travels across the screen, in half-frame
               widths (1.0 = the head crosses a full half-width). A wobble
               gives ~0.05; a real swing gives well over 0.5.
    sweep   -- how many degrees the axe turns on screen, measured about the
               grip. A real swing is well over 60 degrees.
    """
    forward, right, up = basis
    to_camera = _norm(_sub(eye, target))
    tan_half = math.tan(math.radians(fov) / 2.0)
    head_model = [9.5 - grip[0], grip[1] - 4.5, 0.0]

    print("")
    print("  %-14s %6s %7s   %-8s %-7s %s" % (
        "animation", "len", "frames", "visible", "arc", "sweep"))
    worst_visible = 1.0
    for anim in project["animations"]:
        roll, offset = {}, {}
        for animator in anim["animators"].values():
            for keyframe in animator["keyframes"]:
                point = keyframe["data_points"][0]
                if keyframe["channel"] == "rotation":
                    roll[keyframe["time"]] = point["z"]
                elif keyframe["channel"] == "position":
                    offset[keyframe["time"]] = (point["x"], point["y"], point["z"])

        visible = 1.0
        head_screen = []
        angles = []
        for t in sorted(roll):
            visible = min(visible, abs(_dot(_rotate_z(roll[t], [0.0, 0.0, 1.0]), to_camera)))
            off = offset.get(t, (0.0, 0.0, 0.0))
            rotated = _rotate_z(roll[t], head_model)
            head = [rotated[i] + off[i] for i in range(3)]
            rel = _sub(head, eye)
            depth = _dot(rel, forward)
            if depth <= 1e-4:
                continue
            head_screen.append((_dot(rel, right) / depth / tan_half,
                                _dot(rel, up) / depth / tan_half))
            grip_rel = _sub(list(off), eye)
            grip_depth = _dot(grip_rel, forward)
            if grip_depth > 1e-4:
                gx = _dot(grip_rel, right) / grip_depth / tan_half
                gy = _dot(grip_rel, up) / grip_depth / tan_half
                angles.append(math.degrees(math.atan2(head_screen[-1][1] - gy,
                                                      head_screen[-1][0] - gx)))

        arc = sum(math.dist(head_screen[i], head_screen[i + 1])
                  for i in range(len(head_screen) - 1))
        sweep = 0.0
        if angles:
            base = angles[0]
            sweep = max(abs((a - base + 180.0) % 360.0 - 180.0) for a in angles)
        frames = int(round(anim["length"] * anim["snapping"]))
        # Is the whole arc inside the frame? y is in half-frame-heights with the
        # frame spanning -1..1, and x is measured against the half-width, which
        # is `aspect` half-heights wide (16:9 -> 1.78).
        low = min(p[1] for p in head_screen)
        high = max(p[1] for p in head_screen)
        wide = max(abs(p[0]) for p in head_screen)
        fits = low >= -1.0 and high <= 1.0 and wide <= aspect
        print("  %-14s %5.2fs %6d   %.3f    %.3f   %5.0f deg   y %+.2f..%+.2f  |x| %.2f  %s" % (
            anim["name"], anim["length"], frames, visible, arc, sweep,
            low, high, wide, "in frame" if fits else "OUT OF FRAME"))
        worst_visible = min(worst_visible, visible)

    print("  worst visible %.3f  (want >= 0.35)   %s" % (
        worst_visible, "OK" if worst_visible >= 0.35 else "FAIL"))


def main():
    args = list(sys.argv[1:])
    if len(args) < 2:
        print(__doc__)
        return 1
    sprite, out = args[0], args[1]
    name = os.path.splitext(os.path.basename(out))[0]
    thickness = 2.0
    grip = (4.0, 12.0)
    # Camera solved for the overlay render: keep the model where it is, but place
    # the eye so the grip lands at screen (0.55, -0.55) and the axe head orbits it
    # at ~0.75 half-frame-heights. That leaves roughly 254 degrees of usable roll
    # (about -95 .. +158) before the head leaves the frame -- wide enough for the
    # clips below to read as swings instead of flicks. The whole axe stays inside
    # a 16:9 frame, sitting in the lower right at about 65% of the frame height.
    eye = (17.13, 2.36, 26.35)
    target = (-4.07, 6.75, 5.58)
    fov = 45.0
    if "--name" in args:
        name = args[args.index("--name") + 1]
    if "--thickness" in args:
        thickness = float(args[args.index("--thickness") + 1])
    if "--grip" in args:
        gx, gy = args[args.index("--grip") + 1].split(",")
        grip = (float(gx), float(gy))
    if "--eye" in args:
        eye = tuple(float(v) for v in args[args.index("--eye") + 1].split(","))
    if "--target" in args:
        target = tuple(float(v) for v in args[args.index("--target") + 1].split(","))
    if "--fov" in args:
        fov = float(args[args.index("--fov") + 1])

    basis = camera_basis(list(eye), list(target))
    project = build_project(sprite, name, thickness, grip, basis)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(project, handle, indent=2, ensure_ascii=False)
    print("wrote %s" % out)
    print("  boxes: %d   sprite: %s   thickness: %gpx   grip: %s" % (
        len(project["elements"]), os.path.basename(sprite), thickness, grip))
    print("  camera eye %s -> target %s   fov %g" % (list(eye), list(target), fov))
    report(project, basis, list(eye), list(target), grip, fov)
    return 0


if __name__ == "__main__":
    sys.exit(main())
