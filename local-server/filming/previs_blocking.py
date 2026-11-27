import math
import re

XS = ("left", "center", "right")
DEPTHS = ("front", "mid", "back")
FACINGS = ("camera", "left", "right", "away")
MAX_ACTORS = 8
_NAME_MAX = 40
_FRONT, _BACK = 0.15, -0.3
_FACE_TOL = 20
_FACE_AXIS = (("camera", 0), ("right", 90), ("away", 180), ("left", -90))

_MAX_OBJS, _MAX_KEYS = 40, 200
_SENSOR_H = 24
_KINDS = ("char", "prop", "floor", "wall", "box", "cyl", "ramp")
_SET_PIECES = {"floor": [1200, 2, 1200], "wall": [400, 300, 12], "box": [100, 100, 100], "cyl": [60, 100, 60],
               "ramp": [200, 60, 200]}
_ASPECT = re.compile(r"^\d{1,2}:\d{1,2}$")
_MISSING = object()

def _num(v, d):
    if v is _MISSING:
        return d
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else d
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return 0.0
        try:
            f = float(s)
        except ValueError:
            return d
        return f if math.isfinite(f) else d
    return d

def _r3(v):
    return math.floor(v * 1000 + 0.5) / 1000

def _v3(a, d):
    if isinstance(a, list) and len(a) == 3:
        return [_r3(_num(x, d[i])) for i, x in enumerate(a)]
    return list(d)

def _clamp(v, a, b):
    return min(b, max(a, v))

def _get(o, k):
    return o.get(k, _MISSING) if isinstance(o, dict) else _MISSING

def _norm_keys(lst, fix):
    out = []
    for k in (lst if isinstance(lst, list) else []):
        if not isinstance(k, dict) or _num(k.get("t", _MISSING), None) is None:
            continue
        out.append(k)
    out = out[:_MAX_KEYS]
    fixed = [fix(dict(k, t=_r3(_clamp(_num(k.get("t"), 0.0), 0, 30)))) for k in out]
    fixed.sort(key=lambda k: k["t"])
    res = []
    for i, k in enumerate(fixed):
        if i == 0 or k["t"] - fixed[i - 1]["t"] > 1e-4:
            res.append(k)
    return res

def _base_size(kind):
    if kind == "char":
        return [0.5, 1.72, 0.3]
    if kind == "prop":
        return [0.4, 0.4, 0.4]
    return [c / 100 for c in _SET_PIECES[kind]]

def normalize(raw):
    s = raw if isinstance(raw, dict) else {}
    objs = []
    for o in (s.get("objs") if isinstance(s.get("objs"), list) else [])[:_MAX_OBJS]:
        if not isinstance(o, dict):
            continue
        kind = o.get("kind") if o.get("kind") in _KINDS else "box"
        size = [_clamp(x, 0.01, 60) for x in _v3(o.get("size"), _base_size(kind))]
        b = o.get("base") if isinstance(o.get("base"), dict) else {}
        base = {"p": _v3(b.get("p"), [0, 0, 0]), "r": _v3(b.get("r"), [0, 0, 0])}
        keys = _norm_keys(o.get("keys"), lambda k, base=base: {
            "t": k["t"], "p": _v3(k.get("p"), base["p"]), "r": _v3(k.get("r"), base["r"]),
            "e": "io" if k.get("e") == "io" else "lin"})
        objs.append({"kind": kind, "name": str(o.get("name") or "")[:40], "who": str(o.get("who") or "")[:40],
                     "size": size, "base": base, "keys": keys})
    c = s.get("cam") if isinstance(s.get("cam"), dict) else {}
    cb = c.get("base") if isinstance(c.get("base"), dict) else {}
    cbase = {"p": _v3(cb.get("p"), [0, 1.55, 5]), "look": _v3(cb.get("look"), [0, 1.2, 0]),
             "mm": _clamp(_num(_get(cb, "mm"), 35), 8, 300), "roll": _clamp(_num(_get(cb, "roll"), 0), -180, 180)}
    ckeys = _norm_keys(c.get("keys"), lambda k: {
        "t": k["t"], "p": _v3(k.get("p"), cbase["p"]), "look": _v3(k.get("look"), cbase["look"]),
        "mm": _clamp(_num(_get(k, "mm"), cbase["mm"]), 8, 300), "roll": _clamp(_num(_get(k, "roll"), 0), -400, 400)})
    asp = s.get("aspect")
    return {"aspect": asp if isinstance(asp, str) and _ASPECT.match(asp) else "16:9", "objs": objs,
            "cam": {"base": cbase, "keys": ckeys}}

def _ease(u):
    return u * u * (3 - 2 * u)

def _cr(p0, p1, p2, p3, u):
    u2 = u * u
    u3 = u2 * u
    return 0.5 * ((2 * p1) + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u2 + (-p0 + 3 * p1 - 3 * p2 + p3) * u3)

def _segment(keys, t):
    if t <= keys[0]["t"]:
        return 0, 0.0
    last = len(keys) - 1
    if t >= keys[last]["t"]:
        return last, 0.0
    i = 0
    while i < last and keys[i + 1]["t"] <= t:
        i += 1
    span = keys[i + 1]["t"] - keys[i]["t"]
    return i, ((t - keys[i]["t"]) / span if span > 0 else 0.0)

def _spline(keys, f, i, u):
    last = len(keys) - 1

    def P(j):
        return keys[_clamp(j, 0, last)][f]
    if u == 0 or i >= last:
        return list(P(i))
    a, b, c, d = P(i - 1), P(i), P(i + 1), P(i + 2)
    return [_cr(a[k], b[k], c[k], d[k], u) for k in range(3)]

def _lerp(a, b, u):
    return a + (b - a) * u

def sample_obj(o, t):
    ks = o["keys"]
    if not ks:
        return list(o["base"]["p"]), list(o["base"]["r"])
    i, u = _segment(ks, t)
    if i >= len(ks) - 1 or u == 0:
        return list(ks[i]["p"]), list(ks[i]["r"])
    if ks[i + 1]["e"] == "io":
        u = _ease(u)
    return _spline(ks, "p", i, u), [_lerp(ks[i]["r"][k], ks[i + 1]["r"][k], u) for k in range(3)]

def sample_cam(cam, t):
    ks = cam["keys"]
    if not ks:
        return list(cam["base"]["p"]), list(cam["base"]["look"]), cam["base"]["mm"]
    i, u = _segment(ks, t)
    if i >= len(ks) - 1 or u == 0:
        return list(ks[i]["p"]), list(ks[i]["look"]), ks[i]["mm"]
    return _spline(ks, "p", i, u), _spline(ks, "look", i, u), _lerp(ks[i]["mm"], ks[i + 1]["mm"], u)

def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]

def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

def _unit(a):
    n = math.hypot(a[0], a[1], a[2]) or 1
    return [a[0] / n, a[1] / n, a[2] / n]

def _ang_diff(a, b):
    return abs(math.fmod(math.fmod(a - b, 360) + 540, 360) - 180)

def _rad(d):
    return d * math.pi / 180

def _vfov(mm):
    return 2 * math.atan(_SENSOR_H / 2 / max(6, mm or 35)) * 180 / math.pi

def blocking_from_scene(scene, t=0):
    s = normalize(scene)
    tt = _num(t if t is not None else _MISSING, 0.0)
    notes = []
    cp, clook, cmm = sample_cam(s["cam"], tt)
    fwd = _unit(_sub(clook, cp))
    right = _unit([-fwd[2], 0, fwd[0]])
    parts = s["aspect"].split(":")
    aw, ah = float(parts[0]), float(parts[1])
    half_v = math.tan(_rad(_vfov(cmm) / 2))
    half_h = half_v * (aw / ah if aw > 0 and ah > 0 else 16 / 9)
    d_look = _dot(_sub(clook, cp), fwd)
    fh = 2 * max(0.05, d_look) * half_v
    fwd_h = _unit([fwd[0], 0, fwd[2]])

    def where(o, p):
        c = [p[0], _clamp(clook[1], p[1], p[1] + o["size"][1]), p[2]]
        v = _sub(c, cp)
        zc = _dot(v, fwd)
        if zc <= 0.05:
            return None
        xs = _dot(v, right) / (zc * half_h)
        if abs(xs) > 1:
            return None
        dz = (d_look - zc) / fh
        return {"x": "left" if xs < -1 / 3 else "right" if xs > 1 / 3 else "center",
                "depth": "front" if dz >= _FRONT else "back" if dz <= _BACK else "mid"}

    def phi_of(yaw):
        f = [math.sin(_rad(yaw)), 0, math.cos(_rad(yaw))]
        return math.atan2(_dot(f, right), -_dot(f, fwd_h)) * 180 / math.pi

    seen, lst = set(), []
    for o in s["objs"]:
        if o["kind"] != "char":
            continue
        name = re.sub(r"\s+", " ", o["who"] or o["name"] or "").strip()[:_NAME_MAX]
        if not name:
            notes.append("unnamed")
            continue
        if name in seen:
            notes.append("duplicate:" + name)
            continue
        seen.add(name)
        p, r = sample_obj(o, tt)
        lst.append({"o": o, "name": name, "p": p, "yaw": r[1]})
    out = []
    for a in lst:
        if len(out) >= MAX_ACTORS:
            notes.append("too_many:" + a["name"])
            continue
        at = where(a["o"], a["p"])
        if not at:
            notes.append("offscreen:" + a["name"])
            continue
        one = {"name": a["name"], "at": at}
        phi = phi_of(a["yaw"])
        best = None
        for k, deg in _FACE_AXIS:
            e = _ang_diff(phi, deg)
            if best is None or e < best[1]:
                best = (k, e)
        for b in lst:
            if b is a:
                continue
            d = _sub(b["p"], a["p"])
            if math.hypot(d[0], d[2]) < 1e-6:
                continue
            e = _ang_diff(a["yaw"], math.atan2(d[0], d[2]) * 180 / math.pi)
            if e <= _FACE_TOL and e < best[1]:
                best = (b["name"], e)
        one["facing"] = best[0]
        ks = a["o"]["keys"]
        if len(ks) > 1:
            end = where(a["o"], ks[-1]["p"])
            if end:
                to = {}
                if end["x"] != at["x"]:
                    to["x"] = end["x"]
                if end["depth"] != at["depth"]:
                    to["depth"] = end["depth"]
                if to:
                    one["to"] = to
            else:
                notes.append("offscreen_end:" + a["name"])
        out.append(one)
    names = {b["name"] for b in out}
    for b in out:
        if b["facing"] in FACINGS or b["facing"] in names:
            continue
        a = next(x for x in lst if x["name"] == b["name"])
        phi = phi_of(a["yaw"])
        b["facing"] = min(_FACE_AXIS, key=lambda kd: _ang_diff(phi, kd[1]))[0]
    return {"blocking": out, "notes": notes}

def flat(lst):
    rows = []
    for b in lst or []:
        f = {"name": b.get("name")}
        at, to = b.get("at") or {}, b.get("to") or {}
        for k, v in (("x", at.get("x")), ("depth", at.get("depth")), ("facing", b.get("facing")),
                     ("tox", to.get("x")), ("todepth", to.get("depth")), ("action", b.get("action"))):
            if v:
                f[k] = v
        rows.append(f)
    return rows

def merge(prev, nxt):
    old = [b for b in (prev if isinstance(prev, list) else []) if isinstance(b, dict)]
    nx = nxt if isinstance(nxt, list) else []
    out = []
    for b in old:
        n = next((x for x in nx if x.get("name") == b.get("name")), None)
        if n is None:
            out.append(dict(b))
            continue
        m = {k: v for k, v in n.items() if k != "action"}
        if b.get("action"):
            m["action"] = b["action"]
        out.append(m)
    for n in nx:
        if not any(b.get("name") == n.get("name") for b in old):
            out.append(dict(n))
    return out
