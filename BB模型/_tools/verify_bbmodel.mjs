
// _tools/verify_bbmodel.mjs
// 校验 Blockbench .bbmodel：几何连通性 / 骨骼层级 / 动画合理性，
// 并把模型渲染成正交线框图 PNG（_verify_out/*.png），便于肉眼检查。
// 用法: node _tools/verify_bbmodel.mjs [file.bbmodel ...]
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

// ----------------------------- tiny PNG writer -----------------------------
const CRC_T = (() => {
  const t = new Int32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c;
  }
  return t;
})();
const crc32 = (buf) => {
  let c = -1;
  for (let i = 0; i < buf.length; i++) c = CRC_T[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ -1) >>> 0;
};
const chunk = (type, data) => {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, 'latin1'), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
};
function writePNG(file, w, h, rgba) {
  const raw = Buffer.alloc((w * 4 + 1) * h);
  for (let y = 0; y < h; y++) {
    raw[y * (w * 4 + 1)] = 0;
    rgba.copy(raw, y * (w * 4 + 1) + 1, y * w * 4, (y + 1) * w * 4);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  fs.writeFileSync(file, Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]));
}

// ------------------------------- 3x5 bitmap font ---------------------------
const FONT = {
  A: ['.#.', '#.#', '###', '#.#', '#.#'], B: ['##.', '#.#', '##.', '#.#', '##.'],
  C: ['.##', '#..', '#..', '#..', '.##'], D: ['##.', '#.#', '#.#', '#.#', '##.'],
  E: ['###', '#..', '##.', '#..', '###'], F: ['###', '#..', '##.', '#..', '#..'],
  I: ['###', '.#.', '.#.', '.#.', '###'], L: ['#..', '#..', '#..', '#..', '###'],
  N: ['#.#', '##.', '##.', '#.#', '#.#'], O: ['.##', '#.#', '#.#', '#.#', '.##'],
  P: ['##.', '#.#', '##.', '#..', '#..'], R: ['##.', '#.#', '##.', '#.#', '#.#'],
  S: ['.##', '#..', '.#.', '..#', '##.'], T: ['###', '.#.', '.#.', '.#.', '.#.'],
  U: ['#.#', '#.#', '#.#', '#.#', '.##'], W: ['#.#', '#.#', '#.#', '##.', '#.#'],
  Y: ['#.#', '#.#', '.#.', '.#.', '.#.'], '-': ['...', '...', '###', '...', '...'],
  ' ': ['...', '...', '...', '...', '...'], '.': ['...', '...', '...', '...', '.#.'],
};

class Canvas {
  constructor(w, h) { this.w = w; this.h = h; this.buf = Buffer.alloc(w * h * 4); this.clear(0x1b, 0x1d, 0x22); }
  clear(r, g, b) { for (let i = 0; i < this.w * this.h; i++) { const o = i * 4; this.buf[o] = r; this.buf[o + 1] = g; this.buf[o + 2] = b; this.buf[o + 3] = 255; } }
  px(x, y, r, g, b) { x = Math.round(x); y = Math.round(y); if (x < 0 || y < 0 || x >= this.w || y >= this.h) return; const o = (y * this.w + x) * 4; this.buf[o] = r; this.buf[o + 1] = g; this.buf[o + 2] = b; this.buf[o + 3] = 255; }
  line(x0, y0, x1, y1, r, g, b) {
    x0 = Math.round(x0); y0 = Math.round(y0); x1 = Math.round(x1); y1 = Math.round(y1);
    const dx = Math.abs(x1 - x0), dy = Math.abs(y1 - y0);
    const sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    let err = dx - dy;
    for (;;) {
      this.px(x0, y0, r, g, b);
      if (x0 === x1 && y0 === y1) break;
      const e2 = 2 * err;
      if (e2 > -dy) { err -= dy; x0 += sx; }
      if (e2 < dx) { err += dx; y0 += sy; }
    }
  }
  text(str, x, y, r, g, b, scale = 1) {
    for (const ch of str.toUpperCase()) {
      const gl = FONT[ch] || FONT[' '];
      for (let ry = 0; ry < 5; ry++) for (let rx = 0; rx < 3; rx++) {
        if (gl[ry][rx] === '#') {
          for (let sy = 0; sy < scale; sy++) for (let sx = 0; sx < scale; sx++) {
            this.px(x + rx * scale + sx, y + ry * scale + sy, r, g, b);
          }
        }
      }
      x += 4 * scale;
    }
  }
}

// ------------------------------- geometry ----------------------------------
const IDENT = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
const mul = (A, B) => A.map((row, i) => B[0].map((_, j) => row.reduce((s, _, k) => s + A[i][k] * B[k][j], 0)));
const rotX = (d) => { const r = d * Math.PI / 180, c = Math.cos(r), s = Math.sin(r); return [[1, 0, 0], [0, c, -s], [0, s, c]]; };
const rotY = (d) => { const r = d * Math.PI / 180, c = Math.cos(r), s = Math.sin(r); return [[c, 0, s], [0, 1, 0], [-s, 0, c]]; };
const rotZ = (d) => { const r = d * Math.PI / 180, c = Math.cos(r), s = Math.sin(r); return [[c, -s, 0], [s, c, 0], [0, 0, 1]]; };
const apply = (M, v) => M.map((row) => row[0] * v[0] + row[1] * v[1] + row[2] * v[2]);
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];

// Blockbench applies element rotation in world space about element.origin (Z*Y*X order)
function elementMatrix(el) {
  const r = el.rotation || [0, 0, 0];
  if (!r[0] && !r[1] && !r[2]) return { M: IDENT, t: [0, 0, 0] };
  const M = mul(rotZ(r[2]), mul(rotY(r[1]), rotX(r[0])));
  const o = el.origin || [0, 0, 0];
  return { M, t: sub(o, apply(M, o)) };
}

function corners(el) {
  const { M, t } = elementMatrix(el);
  const [x0, y0, z0] = el.from, [x1, y1, z1] = el.to;
  const out = [];
  for (const x of [x0, x1]) for (const y of [y0, y1]) for (const z of [z0, z1]) out.push(add(apply(M, [x, y, z]), t));
  return out;
}
const aabb = (pts) => {
  const mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity];
  for (const p of pts) for (let i = 0; i < 3; i++) { mn[i] = Math.min(mn[i], p[i]); mx[i] = Math.max(mx[i], p[i]); }
  return { mn, mx, size: sub(mx, mn), center: sub(mx, mn).map((s, i) => mn[i] + s / 2) };
};
const overlap = (a, b) => {
  const m = a.mn.map((v, i) => Math.max(v, b.mn[i]));
  const M = a.mx.map((v, i) => Math.min(v, b.mx[i]));
  return { ok: m.every((v, i) => v <= M[i] + 1e-9), gap: M.map((v, i) => v - m[i]) };
};

const CUBE_EDGES = [[0,1],[0,2],[0,4],[1,3],[1,5],[2,3],[2,6],[3,7],[4,5],[4,6],[5,7],[6,7]];

const COLORS = {
  wood: [150, 106, 60], iron: [176, 180, 190], skin: [196, 148, 116], other: [120, 200, 140],
};
function colorOf(name) {
  if (/handle|stick|wood/i.test(name)) return COLORS.wood;
  if (/head|blade|socket|iron|axe/i.test(name)) return COLORS.iron;
  if (/arm|fist|hand|forearm/i.test(name)) return COLORS.skin;
  return COLORS.other;
}

// ------------------------------- views -------------------------------------
// side : screen_x = +Z, screen_y = -Y   (Z+ = "forward")
// front: screen_x = +X, screen_y = -Y
// top  : screen_x = +X, screen_y = +Z
const VIEWS = {
  SIDE: (p) => [p[2], -p[1]],
  FRONT: (p) => [p[0], -p[1]],
  TOP: (p) => [p[0], p[2]],
};

function renderViews(elements, outFile, title) {
  const all = elements.flatMap((e) => corners(e));
  const box = aabb(all);
  const pad = 8;
  const views = ['SIDE', 'FRONT', 'TOP'];
  const cellW = 380, cellH = 420;
  const canvas = new Canvas(cellW * views.length, cellH + 26);
  canvas.text(title || 'MODEL', 6, 6, 240, 240, 240, 2);

  views.forEach((vn, vi) => {
    const ox = vi * cellW;
    canvas.text(vn, ox + 6, 22, 120, 200, 255, 1);
    const proj = VIEWS[vn];
    const projBox = aabb(all.map(proj));
    const scale = Math.min((cellW - 2 * pad) / Math.max(projBox.size[0], 1e-6), (cellH - 60 - 2 * pad) / Math.max(projBox.size[1], 1e-6));
    // center the projected content
    const cx = (projBox.mn[0] + projBox.mx[0]) / 2, cy = (projBox.mn[1] + projBox.mx[1]) / 2;
    const toScreen = (p) => {
      const q = proj(p);
      return [ox + cellW / 2 + (q[0] - cx) * scale, 26 + (cellH - 26) / 2 + (q[1] - cy) * scale];
    };
    // 1px grid every 4 model units + axes
    const [r, g, b] = [44, 48, 56];
    for (let i = Math.floor(projBox.mn[0] / 4) * 4; i <= projBox.mx[0]; i += 4) {
      const a = toScreen(vn === 'TOP' ? [i, 0, 0] : vn === 'FRONT' ? [i, 0, 0] : [0, 0, i]);
      const c = toScreen(vn === 'TOP' ? [i, 0, 0] : vn === 'FRONT' ? [i, 0, 0] : [0, 0, i]);
      canvas.line(a[0], 26, c[0], cellH, r, g, b);
    }
    for (let i = Math.floor(projBox.mn[1] / 4) * 4; i <= projBox.mx[1]; i += 4) {
      const a = toScreen(vn === 'SIDE' ? [0, -i, 0] : [0, -i, 0]);
      canvas.line(ox, a[1], ox + cellW, a[1], r, g, b);
    }
    // axes: X red, Y green, Z blue from origin
    const O = toScreen([0, 0, 0]);
    for (const [ax, col] of [[[14, 0, 0], [230, 90, 90]], [[0, -14, 0], [110, 230, 110]], [[0, 0, 14], [110, 150, 255]]]) {
      const E = toScreen(ax);
      canvas.line(O[0], O[1], E[0], E[1], col[0], col[1], col[2]);
    }
    // cubes
    for (const el of elements) {
      const pts = corners(el);
      const col = colorOf(el.name || '');
      for (const [i, j] of CUBE_EDGES) {
        const a = toScreen(pts[i]), c = toScreen(pts[j]);
        canvas.line(a[0], a[1], c[0], c[1], col[0], col[1], col[2]);
      }
      // highlight element aabb
      const bb = aabb(pts);
      const c0 = toScreen(bb.center);
      canvas.text((el.name || '?').slice(0, 12), c0[0] + 3, c0[1] - 2, 220, 220, 220, 1);
    }
  });
  writePNG(outFile, canvas.w, canvas.h, canvas.buf);
}

// ------------------------------- checks ------------------------------------
const TOL = 0.001;
function checkModel(d, file) {
  const lines = [];
  const ok = (s) => lines.push('  [ok]   ' + s);
  const warn = (s) => lines.push('  [WARN] ' + s);
  const bad = (s) => lines.push('  [BAD]  ' + s);

  const groups = d.groups || [];
  const gname = (uuid) => (groups.find((g) => g.uuid === uuid) || {}).name || '?';
  lines.push('MODEL: ' + file);
  lines.push('  format=' + (d.meta && d.meta.format_version) + ' model_format=' + (d.meta && d.meta.model_format) +
    ' elements=' + (d.elements || []).length + ' groups=' + groups.length +
    ' textures=' + (d.textures || []).length + ' animations=' + (d.animations || []).length);

  // --- bone pivot sanity: in Blockbench the bone pivot should sit inside/at its children
  for (const g of groups) {
    const kids = collectChildren(d, g.uuid);
    if (!kids.length) continue;
    const bb = aabb(kids.flatMap((e) => corners(e)));
    const p = g.origin;
    const inside = p.every((v, i) => v >= bb.mn[i] - 1.5 && v <= bb.mx[i] + 1.5);
    const dist = Math.hypot(...p.map((v, i) => Math.max(0, Math.max(bb.mn[i] - v, v - bb.mx[i]))));
    if (inside) ok('bone "' + g.name + '" pivot ' + fmt(p) + ' lies on its geometry');
    else warn('bone "' + g.name + '" pivot ' + fmt(p) + ' is ' + dist.toFixed(1) + 'px outside its geometry ' + fmt(bb.mn) + '..' + fmt(bb.mx));
  }

  // --- inter-part connectivity: does the fist actually touch the handle?
  const byName = {};
  for (const e of d.elements || []) byName[e.name] = aabb(corners(e));
  const pairs = [
    ['fist', 'handle'], ['forearm', 'fist'], ['fist', 'head_socket'],
    ['handle', 'head_socket'], ['handle', 'head_blade'], ['head_socket', 'head_blade'],
  ];
  for (const [a, b] of pairs) {
    if (!byName[a] || !byName[b]) continue;
    const r = overlap(byName[a], byName[b]);
    if (r.ok) ok('"' + a + '" overlaps "' + b + '"');
    else {
      const gapVec = r.gap.map((v) => Math.max(0, -v));
      bad('"' + a + '" and "' + b + '" do NOT touch - gap ' + fmt(gapVec) + ' (|' + Math.hypot(...gapVec).toFixed(1) + 'px|)');
    }
  }
  return lines;
}

function collectChildren(d, uuid) {
  const out = [];
  const walk = (nodes) => {
    for (const n of nodes) {
      if (!n) continue;
      if (typeof n === 'string') { const e = (d.elements || []).find((x) => x.uuid === n); if (e) out.push(e); continue; }
      if (n.uuid === uuid) { collectElems(d, n.children, out); return; }
      if (n.children) walk(n.children);
    }
  };
  walk(d.outliner || []);
  return out;
}
function collectElems(d, nodes, out) {
  for (const n of nodes || []) {
    if (typeof n === 'string') { const e = (d.elements || []).find((x) => x.uuid === n); if (e) out.push(e); }
    else if (n.children) collectElems(d, n.children, out);
  }
}
const fmt = (v) => '[' + v.map((x) => (Math.abs(x) < 1e-9 ? 0 : +x.toFixed(2))).join(',') + ']';

// ------------------------------- animation report --------------------------
function animReport(d) {
  const lines = [];
  for (const an of d.animations || []) {
    lines.push('ANIM "' + an.name + '"  length=' + an.length + 's  loop=' + an.loop + '  snapping=' + an.snapping +
      '  ' + (an.snapping ? (an.length * an.snapping) + ' frames' : ''));
    for (const [uuid, anm] of Object.entries(an.animators || {})) {
      if (!anm.keyframes || !anm.keyframes.length) { lines.push('  bone "' + anm.name + '": (no keys)'); continue; }
      for (const kf of anm.keyframes) {
        const rows = kf.data_points.map((p) => [num(p.x), num(p.y), num(p.z)]);
        lines.push('  ' + anm.name + '.' + kf.channel + ' @' + kf.time + 's (' + kf.interpolation + ')  ' +
          rows.map((r) => '(' + r.map((v) => (Math.abs(v) < 1e-9 ? 0 : +v.toFixed(1))).join(', ') + ')').join(' '));
      }
    }
    // monotonic / neutral checks
    for (const [uuid, anm] of Object.entries(an.animators || {})) {
      for (const kf of anm.keyframes || []) {
        const ts = kf.data_points.map(() => kf.time);
        if (kf.time > an.length + 1e-9) lines.push('  [BAD] ' + anm.name + '.' + kf.channel + ' key at ' + kf.time + 's exceeds length ' + an.length);
      }
      const rot = (anm.keyframes || []).find((k) => k.channel === 'rotation');
      if (rot) {
        const first = rot.data_points[0], last = rot.data_points[rot.data_points.length - 1];
        const isZero = (p) => [p.x, p.y, p.z].every((v) => Math.abs(num(v)) < 1e-9);
        lines.push('  ' + anm.name + '.rotation: start ' + (isZero(first) ? 'neutral(0,0,0)' : 'NON-neutral') +
          ' -> end ' + (isZero(last) ? 'neutral(0,0,0)' : 'NON-neutral'));
      }
      const pos = (anm.keyframes || []).find((k) => k.channel === 'position');
      if (pos) {
        const isZero = (p) => [p.x, p.y, p.z].every((v) => Math.abs(num(v)) < 1e-9);
        lines.push('  ' + anm.name + '.position: start ' + (isZero(pos.data_points[0]) ? 'neutral' : 'NON-neutral') +
          ' -> end ' + (isZero(pos.data_points[pos.data_points.length - 1]) ? 'neutral' : 'NON-neutral'));
      }
    }
  }
  return lines;
}
const num = (v) => (typeof v === 'number' ? v : parseFloat(String(v || '0')) || 0);

// --------------------------- bone hierarchy + posing -----------------------
function findGroupNode(nodes, uuid) {
  for (const n of nodes || []) {
    if (!n || typeof n !== 'object') continue;
    if (n.uuid === uuid) return n;
    const r = findGroupNode(n.children, uuid);
    if (r) return r;
  }
  return null;
}
function boneChain(d, elemUuid) {
  const chain = [];
  const walk = (nodes, parents) => {
    for (const n of nodes || []) {
      if (!n) continue;
      if (typeof n === 'string') {
        if (n === elemUuid) chain.push(...parents);
        continue;
      }
      const g = (d.groups || []).find((x) => x.uuid === n.uuid);
      walk(n.children, g ? [...parents, g] : parents);
    }
  };
  walk(d.outliner || [], []);
  return chain;
}
// bone rotations applied at the element level are baked in; bones transform their children
function elementMatrixPosed(d, el, pose) {
  let M = el.rotation ? mul(rotZ(el.rotation[2]), mul(rotY(el.rotation[1]), rotX(el.rotation[0]))) : IDENT;
  let t = el.rotation ? sub(el.origin || [0, 0, 0], apply(M, el.origin || [0, 0, 0])) : [0, 0, 0];
  for (const bone of boneChain(d, el.uuid)) {
    const p = pose[bone.uuid];
    if (!p) continue;
    const B = mul(rotZ(p[2]), mul(rotY(p[1]), rotX(p[0])));
    const o = bone.origin || [0, 0, 0];
    t = add(apply(B, t), sub(o, apply(B, o)));
    M = mul(B, M);
  }
  return { M, t };
}
function posedCorners(d, el, pose) {
  const { M, t } = elementMatrixPosed(d, el, pose);
  const [x0, y0, z0] = el.from, [x1, y1, z1] = el.to;
  const out = [];
  for (const x of [x0, x1]) for (const y of [y0, y1]) for (const z of [z0, z1]) out.push(add(apply(M, [x, y, z]), t));
  return out;
}
const interp = (kfs, time) => {
  if (!kfs || !kfs.length) return [0, 0, 0];
  const pts = kfs.map((k) => ({ t: k.time, v: [num(k.data_points[0].x), num(k.data_points[0].y), num(k.data_points[0].z)] }))
    .sort((a, b) => a.t - b.t);
  if (time <= pts[0].t) return pts[0].v;
  if (time >= pts[pts.length - 1].t) return pts[pts.length - 1].v;
  for (let i = 0; i < pts.length - 1; i++) {
    if (time >= pts[i].t && time <= pts[i + 1].t) {
      const w = (time - pts[i].t) / (pts[i + 1].t - pts[i].t);
      return pts[i].v.map((v, j) => v + (pts[i + 1].v[j] - v) * w);
    }
  }
  return pts[pts.length - 1].v;
};
function poseAt(d, anim, time) {
  const pose = {};
  for (const [uuid, anm] of Object.entries(anim.animators || {})) {
    const r = (anm.keyframes || []).find((k) => k.channel === 'rotation');
    if (r && r.data_points && r.data_points.length) {
      // keyframes are {time, data_points:[{x,y,z}]}; resample each key's data point into its own kf
      const kfs = r.data_points.map(() => ({ time: r.time, data_points: [{ x: num(r.data_points[0].x), y: num(r.data_points[0].y), z: num(r.data_points[0].z) }] }));
      // one kf per distinct time
      const byTime = new Map();
      for (const k of anm.keyframes.filter((k) => k.channel === 'rotation')) {
        byTime.set(k.time, { time: k.time, data_points: k.data_points });
      }
      const list = [...byTime.values()].sort((a, b) => a.time - b.time);
      const v = interp(list, time);
      if (list.length) pose[uuid] = v;
    }
  }
  return pose;
}

// render a single animation as a filmstrip: row 1 = side view, row 2 = top view
function renderAnimStrip(d, anim, outFile) {
  const marks = [0, 0.12, 0.3, 0.55, 1].map((f) => +(anim.length * f).toFixed(4));
  const frames = marks.map((t) => {
    const pose = poseAt(d, anim, t);
    return { t, corners: (d.elements || []).map((e) => ({ el: e, pts: posedCorners(d, e, pose) })) };
  });
  const all = frames.flatMap((f) => f.corners.flatMap((c) => c.pts));
  const pad = 8, cellW = 300, cellH = 320, head = 30;
  const canvas = new Canvas(cellW * frames.length, cellH * 2 + head);
  canvas.text('ANIM ' + anim.name + '  ' + anim.length + 'S  ' + (anim.length * 20) + 'F', 6, 6, 245, 210, 120, 2);

  const rows = [['SIDE VIEW', VIEWS.SIDE], ['TOP VIEW', VIEWS.TOP]];
  rows.forEach(([label, proj], ri) => {
    const y0 = head + ri * cellH;
    frames.forEach((fr, fi) => {
      const ox = fi * cellW;
      canvas.text(String(label), ox + 6, y0 + 2, 130, 210, 255, 1);
      canvas.text('T=' + fr.t.toFixed(2), ox + 190, y0 + 2, 150, 150, 160, 1);
      const pb = aabb(all.map(proj));
      const scale = Math.min((cellW - 2 * pad) / Math.max(pb.size[0], 1e-6), (cellH - 26 - 2 * pad) / Math.max(pb.size[1], 1e-6));
      const cx = (pb.mn[0] + pb.mx[0]) / 2, cy = (pb.mn[1] + pb.mx[1]) / 2;
      const toScreen = (p) => { const q = proj(p); return [ox + cellW / 2 + (q[0] - cx) * scale, y0 + 24 + (cellH - 26) / 2 + (q[1] - cy) * scale]; };
      // reference axes at the grip
      const O = toScreen([0, 0, 0]);
      const AY = toScreen([0, -14, 0]), AZ = toScreen([0, 0, 14]), AX = toScreen([14, 0, 0]);
      canvas.line(O[0], O[1], AY[0], AY[1], 90, 200, 90);
      canvas.line(O[0], O[1], AZ[0], AZ[1], 90, 130, 240);
      canvas.line(O[0], O[1], AX[0], AX[1], 230, 90, 90);
      for (const c of fr.corners) {
        const col = colorOf(c.el.name || '');
        for (const [i, j] of CUBE_EDGES) {
          const a = toScreen(c.pts[i]), b = toScreen(c.pts[j]);
          canvas.line(a[0], a[1], b[0], b[1], col[0], col[1], col[2]);
        }
      }
    });
  });
  writePNG(outFile, canvas.w, canvas.h, canvas.buf);
}

// ------------------------------- main --------------------------------------
const files = process.argv.slice(2);
if (!files.length) { console.error('usage: node _tools/verify_bbmodel.mjs <file.bbmodel> [...]'); process.exit(1); }
const outDir = '_verify_out';
fs.mkdirSync(outDir, { recursive: true });
const verbose = process.argv.includes('-v');

for (const f of files) {
  const d = JSON.parse(fs.readFileSync(f, 'utf8'));
  const report = [...checkModel(d, f), '', ...(verbose ? animReport(d) : [])];
  console.log(report.join('\n'));
  const base = path.basename(f).replace(/\.bbmodel$/, '');
  renderViews(d.elements || [], path.join(outDir, base + '.wire.png'), base + ' (rest pose)');
  console.log('wrote ' + path.join(outDir, base + '.wire.png'));
  for (const anim of d.animations || []) {
    const strip = path.join(outDir, base + '.' + anim.name + '.strip.png');
    renderAnimStrip(d, anim, strip);
    console.log('wrote ' + strip);
  }
  console.log('');
}
