
export const VERSION = 1;
export const FPS = 24;
export const MAX_OBJS = 40;
export const MAX_KEYS = 200;
export const DUR_MIN = 2;
export const DUR_MAX = 15;

export const KEY_HEX = ['#8b5cf6', '#22c55e', '#f97316', '#3b82f6', '#ef4444', '#eab308', '#ec4899', '#14b8a6'];
export const NEUTRAL = { floor: '#b9bdc3', wall: '#c9ccd1', box: '#a7acb3', cyl: '#a7acb3', ramp: '#a7acb3', prop: '#9ea3aa' };

export const FIG = {
  lower: { w: 0.22, h: 0.48, d: 0.13 },
  upper: { w: 0.27, h: 0.36, d: 0.15 },
  head: { w: 0.14, h: 0.14, d: 0.14 },
  gap: 0.01,
};
export function figureParts(height) {
  const H = Math.max(0.3, Number(height) || 1.72);
  const g = FIG.gap * H;
  const lo = { w: FIG.lower.w * H, h: FIG.lower.h * H, d: FIG.lower.d * H };
  const up = { w: FIG.upper.w * H, h: FIG.upper.h * H, d: FIG.upper.d * H };
  const hd = { w: FIG.head.w * H, h: FIG.head.h * H, d: FIG.head.d * H };
  lo.y = lo.h / 2;
  up.y = lo.h + g + up.h / 2;
  hd.y = lo.h + g + up.h + g + hd.h / 2;
  return { lower: lo, upper: up, head: hd, top: hd.y + hd.h / 2 };
}

export const PROP_PRESETS = [
  ['chair', '椅子', [45, 90, 48]], ['table', '桌子', [120, 75, 70]], ['cafe', '咖啡桌', [70, 75, 70]],
  ['cup', '杯子', [8, 10, 8]], ['phone', '手機', [7, 15, 1]], ['bag', '包包', [32, 26, 12]],
  ['door', '門', [90, 210, 6]], ['sofa', '沙發', [200, 85, 90]], ['bed', '床', [150, 50, 200]],
  ['car', '汽車', [180, 145, 450]], ['bike', '腳踏車', [60, 105, 175]], ['umbrella', '傘', [100, 90, 100]],
  ['box', '紙箱', [40, 30, 30]],
];
export const SET_PIECES = { floor: [1200, 2, 1200], wall: [400, 300, 12], box: [100, 100, 100], cyl: [60, 100, 60], ramp: [200, 60, 200] };

const SIZE_FRAME = { ews: [14, 24], ws: [5, 28], ms: [1.7, 35], mcu: [0.95, 50], cu: [0.5, 85], ecu: [0.24, 100] };
const SPEED_K = { slow: 0.6, steady: 1, fast: 1.6 };
export const FOCALS = [18, 24, 28, 35, 50, 85, 135];
export const SENSOR_H = 24;

export const vfov = mm => 2 * Math.atan(SENSOR_H / 2 / Math.max(6, Number(mm) || 35)) * 180 / Math.PI;
export const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const num = (v, d) => (Number.isFinite(Number(v)) ? Number(v) : d);
const r3 = v => Math.round(v * 1000) / 1000;
const v3 = (a, d) => (Array.isArray(a) && a.length === 3 ? a.map((x, i) => r3(num(x, d[i]))) : d.slice());
export const snap = (t, fps) => Math.round(Number(t) * (fps || FPS)) / (fps || FPS);

let _n = 0;
export const newId = p => (p || 'o') + Date.now().toString(36).slice(-4) + (++_n).toString(36) + Math.random().toString(36).slice(2, 5);

export function makeObj(kind, opt) {
  const o = opt || {};
  const KIND = ['char', 'prop', 'floor', 'wall', 'box', 'cyl', 'ramp'];
  const k = KIND.includes(kind) ? kind : 'box';
  let size;
  if (k === 'char') size = [0.5, num(o.height, 1.72), 0.3];
  else if (k === 'prop') size = (o.cm || [40, 40, 40]).map(c => num(c, 40) / 100);
  else size = (o.cm || SET_PIECES[k]).map(c => num(c, 100) / 100);
  return {
    id: o.id || newId(k[0]), kind: k, name: o.name || '', who: o.who || '', preset: o.preset || '',
    color: o.color || (k === 'char' ? KEY_HEX[0] : NEUTRAL[k]),
    size,
    base: { p: v3(o.p, [0, 0, 0]), r: v3(o.r, [0, 0, 0]), s: [1, 1, 1] },
    keys: [],
  };
}

export function normalize(raw, fallback) {
  const s = raw && typeof raw === 'object' ? raw : {};
  const fb = fallback || {};
  const objs = (Array.isArray(s.objs) ? s.objs : []).slice(0, MAX_OBJS).map(o => {
    if (!o || typeof o !== 'object') return null;
    const base = makeObj(o.kind, {});
    const out = Object.assign(base, {
      id: typeof o.id === 'string' && o.id ? o.id.slice(0, 24) : base.id,
      name: String(o.name || '').slice(0, 40), who: String(o.who || '').slice(0, 40), preset: String(o.preset || '').slice(0, 16),
      color: /^#[0-9a-f]{6}$/i.test(o.color || '') ? o.color.toLowerCase() : base.color,
      size: v3(o.size, base.size).map(x => clamp(x, 0.01, 60)),
    });
    const b = o.base || {};
    out.base = { p: v3(b.p, [0, 0, 0]), r: v3(b.r, [0, 0, 0]), s: v3(b.s, [1, 1, 1]).map(x => clamp(x, 0.05, 40)) };
    out.keys = normKeys(o.keys, k => ({ t: k.t, p: v3(k.p, out.base.p), r: v3(k.r, out.base.r), s: v3(k.s, out.base.s), e: k.e === 'io' ? 'io' : 'lin' }));
    return out;
  }).filter(Boolean);
  const c = s.cam || {};
  const cb = c.base || {};
  const cam = {
    move: String(c.move || '').slice(0, 20),
    base: { p: v3(cb.p, [0, 1.55, 5]), look: v3(cb.look, [0, 1.2, 0]), mm: clamp(num(cb.mm, 35), 8, 300), roll: clamp(num(cb.roll, 0), -180, 180) },
  };
  cam.keys = normKeys(c.keys, k => ({ t: k.t, p: v3(k.p, cam.base.p), look: v3(k.look, cam.base.look),
                                      mm: clamp(num(k.mm, cam.base.mm), 8, 300), roll: clamp(num(k.roll, 0), -400, 400) }));
  return {
    v: VERSION,
    dur: clamp(num(s.dur, num(fb.dur, 5)), 1, 30),
    fps: FPS,
    aspect: /^\d{1,2}:\d{1,2}$/.test(s.aspect || '') ? s.aspect : (fb.aspect || '16:9'),
    objs, cam,
    ...(typeof s.subject_height === 'number' && s.subject_height >= 0.05 && s.subject_height <= 3 ? { subject_height: r3(s.subject_height) } : {}),
  };
}
function normKeys(list, fix) {
  return (Array.isArray(list) ? list : []).filter(k => k && Number.isFinite(Number(k.t)))
    .slice(0, MAX_KEYS).map(k => fix(Object.assign({}, k, { t: r3(clamp(Number(k.t), 0, 30)) })))
    .sort((a, b) => a.t - b.t)
    .filter((k, i, a) => i === 0 || k.t - a[i - 1].t > 1e-4);
}

const lerp = (a, b, u) => a + (b - a) * u;
const ease = u => u * u * (3 - 2 * u);
function cr(p0, p1, p2, p3, u) {
  const u2 = u * u, u3 = u2 * u;
  return 0.5 * ((2 * p1) + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u2 + (-p0 + 3 * p1 - 3 * p2 + p3) * u3);
}
export function segment(keys, t) {
  if (!keys.length) return null;
  if (t <= keys[0].t) return { i: 0, u: 0 };
  const L = keys.length - 1;
  if (t >= keys[L].t) return { i: L, u: 0 };
  let i = 0;
  while (i < L && keys[i + 1].t <= t) i++;
  const span = keys[i + 1].t - keys[i].t;
  return { i, u: span > 0 ? (t - keys[i].t) / span : 0 };
}
function splineV(keys, f, i, u) {
  const L = keys.length - 1;
  const P = j => keys[clamp(j, 0, L)][f];
  if (u === 0 || i >= L) return P(i).slice();
  const a = P(i - 1), b = P(i), c = P(i + 1), d = P(i + 2);
  return [0, 1, 2].map(k => cr(a[k], b[k], c[k], d[k], u));
}
const linV = (a, b, u) => [0, 1, 2].map(k => lerp(a[k], b[k], u));

export function sampleObj(o, t) {
  const ks = o.keys || [];
  if (!ks.length) return { p: o.base.p.slice(), r: o.base.r.slice(), s: o.base.s.slice() };
  const g = segment(ks, t);
  const L = ks.length - 1;
  if (g.i >= L || g.u === 0) { const k = ks[g.i]; return { p: k.p.slice(), r: k.r.slice(), s: k.s.slice() }; }
  const u = ks[g.i + 1].e === 'io' ? ease(g.u) : g.u;
  return { p: splineV(ks, 'p', g.i, u), r: linV(ks[g.i].r, ks[g.i + 1].r, u), s: linV(ks[g.i].s, ks[g.i + 1].s, u) };
}
export function sampleCam(cam, t) {
  const ks = cam.keys || [];
  if (!ks.length) return { p: cam.base.p.slice(), look: cam.base.look.slice(), mm: cam.base.mm, roll: cam.base.roll || 0 };
  const g = segment(ks, t);
  const L = ks.length - 1;
  if (g.i >= L || g.u === 0) { const k = ks[g.i]; return { p: k.p.slice(), look: k.look.slice(), mm: k.mm, roll: k.roll || 0 }; }
  const a = ks[g.i], b = ks[g.i + 1];
  return { p: splineV(ks, 'p', g.i, g.u), look: splineV(ks, 'look', g.i, g.u), mm: lerp(a.mm, b.mm, g.u), roll: lerp(a.roll || 0, b.roll || 0, g.u) };
}

export function upsertKey(keys, t, val, before, fps) {
  const tt = r3(snap(t, fps));
  const out = (keys || []).filter(k => Math.abs(k.t - tt) > 1e-4).map(k => Object.assign({}, k));
  if (!out.length && !(keys || []).length && tt > 0 && before) out.push(Object.assign({ t: 0 }, before));
  out.push(Object.assign({}, val, { t: tt }));
  return out.sort((a, b) => a.t - b.t).slice(0, MAX_KEYS);
}
export function moveKey(keys, from, to, dur, fps) {
  const tt = r3(clamp(snap(to, fps), 0, dur));
  const k = keys.find(x => Math.abs(x.t - from) < 1e-4);
  if (!k) return keys;
  if (keys.some(x => x !== k && Math.abs(x.t - tt) < 1e-4)) return keys;
  return keys.map(x => (x === k ? Object.assign({}, x, { t: tt }) : x)).sort((a, b) => a.t - b.t);
}
export function fitKeys(keys, dur) {
  const out = [];
  (keys || []).forEach(k => {
    const t = Math.min(k.t, dur);
    const i = out.findIndex(x => Math.abs(x.t - t) < 1e-4);
    if (i >= 0) out[i] = Object.assign({}, k, { t }); else out.push(Object.assign({}, k, { t }));
  });
  return out.sort((a, b) => a.t - b.t);
}

const rad = d => d * Math.PI / 180;
const around = (T, d, az, y) => [T[0] + d * Math.sin(rad(az)), y, T[2] + d * Math.cos(rad(az))];

export const REF_HEIGHT = 1.7;
export function subjectScale(scene) {
  const h = scene && scene.subject_height;
  return typeof h === 'number' && h >= 0.05 && h <= 3 ? h / REF_HEIGHT : 1;
}
export function framing(cam, T, scale) {
  const c = cam || {};
  const s = scale || 1;
  const [hFrame0, mm0] = SIZE_FRAME[c.size] || SIZE_FRAME.ms;
  const hFrame = hFrame0 * s;
  const mm = mm0;
  const half = rad(vfov(mm) / 2);
  const d = clamp(hFrame / 2 / Math.tan(half), 0.6 * s, 60);
  let y = T[1] + 0.15 * s, roll = 0, top = false;
  if (c.angle === 'high') y = T[1] + d * 0.55;
  else if (c.angle === 'low') y = Math.max(0.25 * s, T[1] - d * 0.35);
  else if (c.angle === 'top') { y = T[1] + d; top = true; }
  else if (c.angle === 'dutch') roll = 14;
  return { d, mm, y, roll, top };
}

export function camPath(cam, ctx) {
  const c = cam || {};
  const T = (ctx && ctx.target) || [0, 1.2, 0];
  const dur = clamp(num(ctx && ctx.dur, 5), 0.5, 30);
  const k = SPEED_K[c.speed] || 1;
  const s = (ctx && ctx.scale) || 1;
  const [c24, c04, c11, c22, c7, c26, c008, c005, c006, c004] = [2.4, 0.4, 1.1, 2.2, 7, 2.6, 0.08, 0.05, 0.06, 0.04].map(v => v * s);
  const f = framing(c, T, s);
  const moveEnd = dur > 2.5 ? dur - 1 : dur;
  const N = 8;
  const out = [];
  let note = '';
  const at = (u, pose) => out.push(Object.assign({ t: r3(u * moveEnd) }, pose));
  const pose = (p, look, mm, roll) => ({ p: p.map(r3), look: look.map(r3), mm: r3(mm), roll: r3(roll || 0) });
  const base = (az, d, y, look, mm, roll) => pose(f.top ? [T[0], y, T[2] + 0.01] : around(T, d, az, y), look || T, mm || f.mm, roll != null ? roll : f.roll);
  const sweep = fn => { for (let i = 0; i <= N; i++) { const u = i / N; at(u, fn(ease(u), u)); } };
  const mv = c.move || 'static';
  switch (mv) {
    case 'dolly_in': sweep(e => base(0, f.d * (1 + 0.5 * k) * (1 - e) + f.d * e, f.y)); break;
    case 'dolly_out': sweep(e => base(0, f.d + f.d * 0.6 * k * e, f.y)); break;
    case 'zoom_in': sweep(e => base(0, f.d * 1.6, f.y, null, f.mm * (1 + 0.9 * k * e) / 1)); note = '變焦：機位不動，只改焦距'; break;
    case 'zoom_out': sweep(e => base(0, f.d, f.y, null, f.mm * (1 + 0.9 * k) / (1 + 0.9 * k * e))); note = '變焦：機位不動，只改焦距'; break;
    case 'orbit_l': sweep(e => base(-60 * k * e, f.d, f.y)); break;
    case 'orbit_r': sweep(e => base(60 * k * e, f.d, f.y)); break;
    case 'arc': sweep(e => base(-45 * k + 90 * k * e, f.d, f.y)); break;
    case 'orbit_360': sweep(e => base(360 * e, f.d, f.y)); note = '360 度環繞：旋轉鏡頭要有正反面參考圖（方塊背面是暗色）'; break;
    case 'crane_up': sweep(e => base(0, f.d, f.y + c24 * k * e, [T[0], T[1] + c04 * e, T[2]])); break;
    case 'crane_down': sweep(e => base(0, f.d, f.y + c24 * k * (1 - e), [T[0], T[1] + c04 * (1 - e), T[2]])); break;
    case 'tilt_up': sweep(e => base(0, f.d, f.y, [T[0], T[1] - c11 * k + c22 * k * e, T[2]])); break;
    case 'tilt_down': sweep(e => base(0, f.d, f.y, [T[0], T[1] + c11 * k - c22 * k * e, T[2]])); break;
    case 'drone_rise': sweep(e => base(0, f.d * (1 + 1.5 * e * k), f.y + c7 * k * e, [T[0], T[1] * (1 - e * 0.6), T[2]])); break;
    case 'pan_l': case 'pan_r': {
      const sg = mv === 'pan_l' ? -1 : 1;
      const P = around(T, f.d, 0, f.y);
      const L = Math.hypot(T[0] - P[0], T[2] - P[2]);
      sweep(e => { const a = rad(sg * 40 * k * (e - 0.5)); return pose(P, [P[0] + L * Math.sin(a), T[1], P[2] - L * Math.cos(a)], f.mm, f.roll); });
      break;
    }
    case 'truck_l': case 'truck_r': {
      const sg = mv === 'truck_l' ? -1 : 1;
      sweep(e => { const dx = sg * c26 * k * (e - 0.5); const P = around(T, f.d, 0, f.y); return pose([P[0] + dx, P[1], P[2]], [T[0] + dx, T[1], T[2]], f.mm, f.roll); });
      break;
    }
    case 'track': {
      const fol = ctx && typeof ctx.follow === 'function' ? ctx.follow : null;
      const moving = fol && Math.hypot(...[0, 1, 2].map(i => fol(dur)[i] - fol(0)[i])) > c005;
      if (moving) {
        for (let i = 0; i <= N; i++) {
          const t = r3(dur * i / N);
          const q = fol(t);
          out.push(Object.assign({ t }, pose(around(q, f.d, 0, f.y - T[1] + q[1]), q, f.mm, f.roll)));
        }
      } else {
        sweep(e => { const dz = -c22 * k * e; const P = around(T, f.d, 0, f.y); return pose([P[0], P[1], P[2] + dz], [T[0], T[1], T[2] + dz], f.mm, f.roll); });
        note = '跟拍：主體還沒有移動的關鍵幀，先做成往前推；角色打好走位之後再按一次「產生」';
      }
      break;
    }
    case 'handheld': {
      let seed = 7;
      const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647 - 0.5; };
      const M = Math.max(4, Math.round(dur * 3));
      for (let i = 0; i <= M; i++) {
        const P = around(T, f.d, 0, f.y);
        out.push(Object.assign({ t: r3(dur * i / M) }, pose([P[0] + rnd() * c008, P[1] + rnd() * c005, P[2] + rnd() * c005],
          [T[0] + rnd() * c006, T[1] + rnd() * c004, T[2]], f.mm, f.roll + rnd() * 1.6)));
      }
      break;
    }
    case 'dolly_zoom': sweep(e => { const d = f.d * (1.8 - 0.9 * e); return base(0, d, f.y, null, f.mm * d / (f.d * 1.8)); }); note = '滑動變焦：往前推的同時焦距變廣，主體大小不變、背景拉開'; break;
    case 'whip': {
      const P = around(T, f.d, 0, f.y);
      const L = f.d;
      const hold = Math.max(0, dur - 0.6);
      out.push(Object.assign({ t: 0 }, pose(P, T, f.mm, f.roll)));
      out.push(Object.assign({ t: r3(hold) }, pose(P, T, f.mm, f.roll)));
      const a = rad(75);
      out.push(Object.assign({ t: r3(dur) }, pose(P, [P[0] + L * Math.sin(a), T[1], P[2] - L * Math.cos(a)], f.mm, f.roll)));
      note = '甩鏡：最後 0.6 秒快速橫甩（積木預演只表現方向，動態模糊交給模型）';
      break;
    }
    case 'roll': sweep(e => base(0, f.d, f.y, null, null, f.roll + 28 * k * e)); break;
    case 'rack': at(0, base(0, f.d, f.y)); note = '移焦在積木預演裡看不出來：機位固定，對焦變化寫在提示詞'; break;
    default: at(0, base(0, f.d, f.y));
  }
  return { keys: out.filter((x, i, a) => i === 0 || x.t - a[i - 1].t > 1e-4), note };
}

const AIM = { ecu: 0.93, cu: 0.92, mcu: 0.88, ms: 0.74, ws: 0.55, ews: 0.5 };
export function subjectTarget(scene, t, size) {
  const tt = t || 0;
  const aim = AIM[size] || 0.8;
  const pick = scene.objs.filter(o => o.kind === 'char');
  const list = pick.length ? pick : scene.objs.filter(o => o.kind === 'prop');
  if (!list.length) return [0, 1.2, 0];
  const acc = [0, 0, 0];
  list.forEach(o => {
    const p = sampleObj(o, tt).p;
    acc[0] += p[0]; acc[2] += p[2];
    acc[1] += o.kind === 'char' ? o.size[1] * aim + p[1] : o.size[1] * 0.6 + p[1];
  });
  return acc.map(v => r3(v / list.length));
}

export const BLOCK_XS = ['left', 'center', 'right'];
export const BLOCK_DEPTHS = ['front', 'mid', 'back'];
export const BLOCK_FACINGS = ['camera', 'left', 'right', 'away'];
export const BLOCK_MAX = 8;
const BLOCK_NAME_MAX = 40;
const BLOCK_TEXT_MAX = 120;
const BLOCK_FRONT = 0.15, BLOCK_BACK = -0.3;
const BLOCK_FACE_TOL = 20;
const FACE_AXIS = { camera: 0, right: 90, away: 180, left: -90 };
const sub3 = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const unit3 = a => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
const angDiff = (a, b) => { const d = ((a - b) % 360 + 540) % 360 - 180; return Math.abs(d); };

export function blockingOf(scene, t) {
  const s = scene || {};
  const tt = num(t, 0);
  const notes = [];
  const cam = sampleCam(s.cam || { base: { p: [0, 1.55, 5], look: [0, 1.2, 0], mm: 35 } }, tt);
  const fwd = unit3(sub3(cam.look, cam.p));
  const right = unit3([-fwd[2], 0, fwd[0]]);
  const [aw, ah] = String(s.aspect || '16:9').split(':').map(Number);
  const halfV = Math.tan(rad(vfov(cam.mm) / 2)), halfH = halfV * ((aw > 0 && ah > 0) ? aw / ah : 16 / 9);
  const dLook = dot3(sub3(cam.look, cam.p), fwd);
  const fh = 2 * Math.max(0.05, dLook) * halfV;
  const fwdH = unit3([fwd[0], 0, fwd[2]]);
  const where = (o, p) => {
    const c = [p[0], clamp(cam.look[1], p[1], p[1] + o.size[1]), p[2]];
    const v = sub3(c, cam.p);
    const zc = dot3(v, fwd);
    if (zc <= 0.05) return null;
    const xs = dot3(v, right) / (zc * halfH);
    if (Math.abs(xs) > 1) return null;
    const dz = (dLook - zc) / fh;
    return { x: xs < -1 / 3 ? 'left' : xs > 1 / 3 ? 'right' : 'center',
             depth: dz >= BLOCK_FRONT ? 'front' : dz <= BLOCK_BACK ? 'back' : 'mid' };
  };
  const chars = (s.objs || []).filter(o => o && o.kind === 'char');
  const seen = new Set(), list = [];
  chars.forEach(o => {
    const name = String(o.who || o.name || '').replace(/\s+/g, ' ').trim().slice(0, BLOCK_NAME_MAX);
    if (!name) { notes.push('unnamed'); return; }
    if (seen.has(name)) { notes.push('duplicate:' + name); return; }
    seen.add(name);
    list.push({ o, name, p: sampleObj(o, tt).p, yaw: sampleObj(o, tt).r[1] });
  });
  const out = [];
  list.forEach(a => {
    if (out.length >= BLOCK_MAX) { notes.push('too_many:' + a.name); return; }
    const at = where(a.o, a.p);
    if (!at) { notes.push('offscreen:' + a.name); return; }
    const one = { name: a.name, at };
    const f = [Math.sin(rad(a.yaw)), 0, Math.cos(rad(a.yaw))];
    const phi = Math.atan2(dot3(f, right), -dot3(f, fwdH)) * 180 / Math.PI;
    let best = null;
    Object.entries(FACE_AXIS).forEach(([k, deg]) => { const e = angDiff(phi, deg); if (!best || e < best.e) best = { k, e }; });
    list.forEach(b => {
      if (b === a) return;
      const d = sub3(b.p, a.p);
      if (Math.hypot(d[0], d[2]) < 1e-6) return;
      const e = angDiff(a.yaw, Math.atan2(d[0], d[2]) * 180 / Math.PI);
      if (e <= BLOCK_FACE_TOL && e < best.e) best = { k: b.name, e };
    });
    one.facing = best.k;
    const ks = a.o.keys || [];
    if (ks.length > 1) {
      const end = where(a.o, ks[ks.length - 1].p);
      if (end) {
        const to = {};
        if (end.x !== at.x) to.x = end.x;
        if (end.depth !== at.depth) to.depth = end.depth;
        if (Object.keys(to).length) one.to = to;
      } else notes.push('offscreen_end:' + a.name);
    }
    out.push(one);
  });
  const names = new Set(out.map(b => b.name));
  out.forEach(b => {
    if (BLOCK_FACINGS.includes(b.facing) || names.has(b.facing)) return;
    const a = list.find(x => x.name === b.name);
    const phi = Math.atan2(dot3([Math.sin(rad(a.yaw)), 0, Math.cos(rad(a.yaw))], right), -dot3([Math.sin(rad(a.yaw)), 0, Math.cos(rad(a.yaw))], fwdH)) * 180 / Math.PI;
    b.facing = Object.entries(FACE_AXIS).sort((x, y) => angDiff(phi, x[1]) - angDiff(phi, y[1]))[0][0];
  });
  return { blocking: out, notes };
}

export function blockingCheck(list) {
  if (!Array.isArray(list) || list.length > BLOCK_MAX) return 'blocking 要是最多 ' + BLOCK_MAX + ' 個角色的清單';
  const txt = v => String(v).replace(/[\x00-\x1f\x7f]/g, ' ').replace(/\s+/g, ' ').trim();
  const names = new Set(list.filter(b => b && typeof b === 'object').map(b => (typeof b.name === 'string' ? txt(b.name) : '')));
  const mark = (m, w, needX) => {
    if (!m || typeof m !== 'object' || Array.isArray(m)) return w + ' 要是物件';
    if (Object.keys(m).some(k => !['x', 'depth'].includes(k))) return w + ' 只收 x、depth';
    if ((m.x != null || needX) && !BLOCK_XS.includes(m.x)) return w + '.x 只能是 ' + BLOCK_XS.join('／');
    if (m.depth != null && !BLOCK_DEPTHS.includes(m.depth)) return w + '.depth 只能是 ' + BLOCK_DEPTHS.join('／');
    if (m.x == null && m.depth == null) return w + ' 至少要有 x 或 depth';
    return '';
  };
  const seen = new Set();
  for (let i = 0; i < list.length; i++) {
    const b = list[i], w = 'blocking[' + i + ']';
    if (!b || typeof b !== 'object' || Array.isArray(b)) return w + ' 要是物件';
    if (Object.keys(b).some(k => !['name', 'at', 'facing', 'to', 'action'].includes(k))) return w + ' 有不認得的欄位';
    if (typeof b.name !== 'string') return w + '.name 要是字串';
    const name = txt(b.name);
    if (!name) return w + '.name 不能是空的';
    if (name.length > BLOCK_NAME_MAX) return w + '.name 最多 ' + BLOCK_NAME_MAX + ' 字';
    if (seen.has(name)) return w + '.name 重複：' + name;
    seen.add(name);
    const e = mark(b.at, w + '.at', true);
    if (e) return e;
    if (b.facing != null && b.facing !== '') {
      if (typeof b.facing !== 'string') return w + '.facing 要是字串';
      const fc = txt(b.facing);
      if (fc.length > BLOCK_NAME_MAX) return w + '.facing 最多 ' + BLOCK_NAME_MAX + ' 字';
      if (!BLOCK_FACINGS.includes(fc) && !names.has(fc)) return w + '.facing 只能是 ' + BLOCK_FACINGS.join('／') + ' 或另一個角色的名字';
      if (fc === name) return w + '.facing 不能面向自己';
    }
    if (b.to != null) { const e2 = mark(b.to, w + '.to', false); if (e2) return e2; }
    if (b.action != null) {
      if (typeof b.action !== 'string') return w + '.action 要是字串';
      if (txt(b.action).length > BLOCK_TEXT_MAX) return w + '.action 最多 ' + BLOCK_TEXT_MAX + ' 字';
    }
  }
  return '';
}

export function blockingFlat(list) {
  return (list || []).map(b => {
    const f = { name: b.name };
    if (b.at && b.at.x) f.x = b.at.x;
    if (b.at && b.at.depth) f.depth = b.at.depth;
    if (b.facing) f.facing = b.facing;
    if (b.to && b.to.x) f.tox = b.to.x;
    if (b.to && b.to.depth) f.todepth = b.to.depth;
    if (b.action) f.action = b.action;
    return f;
  });
}
export function blockingNested(rows) {
  return (rows || []).map(r => {
    const b = r && typeof r === 'object' ? r : {};
    const one = { name: b.name, at: {} };
    if (b.x) one.at.x = b.x;
    if (b.depth) one.at.depth = b.depth;
    if (b.facing) one.facing = b.facing;
    const to = {};
    if (b.tox) to.x = b.tox;
    if (b.todepth) to.depth = b.todepth;
    if (Object.keys(to).length) one.to = to;
    if (b.action) one.action = b.action;
    return one;
  });
}

export function mergeBlocking(prev, next) {
  const old = Array.isArray(prev) ? prev.filter(b => b && typeof b === 'object') : [];
  const nx = Array.isArray(next) ? next : [];
  const out = old.map(b => {
    const n = nx.find(x => x.name === b.name);
    if (!n) return Object.assign({}, b);
    const m = Object.assign({}, n);
    delete m.action;
    if (b.action) m.action = b.action;
    return m;
  });
  nx.forEach(n => { if (!old.some(b => b.name === n.name)) out.push(Object.assign({}, n)); });
  return out;
}

export function alignDur(want, align) {
  const w = clamp(num(want, 5), 0.5, 30);
  let a = {};
  try { a = (typeof align === 'function' && align(w)) || {}; } catch (e) { a = {}; }
  let dur = a.seconds != null ? Number(a.seconds) : (a.max != null ? Number(a.max) : Math.ceil(w));
  let note = '';
  if (a.seconds == null && a.max != null) note = '這個模型最長 ' + a.max + ' 秒';
  else if (Math.abs(dur - w) > 1e-6) note = '對齊這個模型收的秒數：' + r3(w) + ' → ' + dur;
  if (dur > DUR_MAX) { dur = DUR_MAX; note = '參考影片最長 ' + DUR_MAX + ' 秒'; }
  if (dur < DUR_MIN) { dur = DUR_MIN; note = '參考影片最短 ' + DUR_MIN + ' 秒'; }
  return { dur, note };
}

export function pickColor(who, keys, clash, taken) {
  const list = (keys || []).filter(k => k && k.c);
  const mine = who && list.find(k => k.who === who);
  if (mine) return mine.c.toLowerCase();
  const used = new Set(list.filter(k => k.who && k.who !== who).map(k => k.c.toLowerCase()).concat(taken || []));
  const ok = KEY_HEX.filter(c => !used.has(c));
  const clean = ok.find(c => !(typeof clash === 'function' && (clash(c) || []).length));
  return clean || ok[0] || KEY_HEX[0];
}
export function mergeKeys(keys, objs) {
  const out = (keys || []).filter(k => k && k.c).map(k => ({ c: k.c.toLowerCase(), who: k.who || '' }));
  const added = [], conflicts = [];
  (objs || []).filter(o => o.who && (o.kind === 'char' || o.kind === 'prop')).forEach(o => {
    const c = o.color.toLowerCase();
    const same = out.find(k => k.who === o.who);
    if (same) { if (same.c !== c) conflicts.push(o.who + ' 在分色對照是另一個顏色'); return; }
    const owner = out.find(k => k.c === c && k.who && k.who !== o.who);
    if (owner) { conflicts.push(o.who + ' 跟 ' + owner.who + ' 用了同一色'); return; }
    const blank = out.find(k => k.c === c && !k.who);
    if (blank) blank.who = o.who; else out.push({ c, who: o.who });
    added.push({ c, who: o.who });
  });
  return { keys: out, added, conflicts };
}

export function motionNote(scene) {
  const chars = (scene.objs || []).filter(o => o.kind === 'char').length;
  const parts = ['The motion source is a 3D blockout previs'];
  if (chars) parts.push('each coloured figure is three blocks (head, torso, legs) standing in for one character, the bright face of each block is its front and the dark face its back');
  parts.push('grey shapes are only set dressing and scale reference, replace them with the real location');
  parts.push('do not render blocks, grid or flat colours');
  return parts.join('; ') + '.';
}

export function exportSize(aspect) {
  const m = String(aspect || '16:9').match(/^(\d+):(\d+)$/);
  const a = m ? Number(m[1]) / Number(m[2]) : 16 / 9;
  const ev = x => Math.max(2, Math.round(x / 2) * 2);
  if (a >= 1) { const w = a >= 2 ? 1680 : a > 1.5 ? 1280 : 960; return { w, h: ev(w / a) }; }
  const h = a <= 0.5 ? 1680 : a < 0.67 ? 1280 : 960;
  return { w: ev(h * a), h };
}
export const frameCount = (dur, fps) => Math.max(1, Math.round(clamp(num(dur, 5), 0.1, 30) * (fps || FPS)));
export const AVC_CANDIDATES = ['avc1.640028', 'avc1.4d0028', 'avc1.42e028', 'avc1.42001f'];
export const bitrateFor = (w, h) => Math.round(clamp(w * h * FPS * 0.12, 1.5e6, 8e6));
export const MAX_UPLOAD = 20 * 1024 * 1024;

export const fmtT = t => { const s = Math.max(0, Number(t) || 0); return s.toFixed(2).padStart(5, '0') + 's'; };
export const sceneBytes = s => new TextEncoder().encode(JSON.stringify(s)).length;
