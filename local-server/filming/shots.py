import re

from . import scene

VERSION = 1
MAX_SHOTS = 12
SHOT_MIN, SHOT_MAX = 2, 15
STEP = 0.125
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

class ShotsError(ValueError):
    pass

def _ease(u):
    return u * u * (3 - 2 * u)

def _cr(p0, p1, p2, p3, u):
    u2, u3 = u * u, u * u * u
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

def sample(obj, t):
    ks = obj.get("keys") or []
    if not ks:
        b = obj["base"]
        return {"p": list(b["p"]), "r": list(b["r"]), "s": list(b["s"])}
    i, u = _segment(ks, t)
    last = len(ks) - 1
    if i >= last or u == 0:
        k = ks[i]
        return {"p": list(k["p"]), "r": list(k["r"]), "s": list(k["s"])}
    if ks[i + 1].get("e") == "io":
        u = _ease(u)

    def at(j):
        return ks[min(max(j, 0), last)]["p"]
    a, b, c, d = at(i - 1), at(i), at(i + 1), at(i + 2)
    lin = lambda f: [ks[i][f][n] + (ks[i + 1][f][n] - ks[i][f][n]) * u for n in range(3)]
    return {"p": [_cr(a[n], b[n], c[n], d[n], u) for n in range(3)], "r": lin("r"), "s": lin("s")}

def _r3(v):
    return [round(x, 3) + 0.0 for x in v]

def _times(t0, t1, ks):
    ts = {round(t0, 3), round(t1, 3)}
    n = int((t1 - t0) / STEP)
    ts.update(round(t0 + STEP * j, 3) for j in range(1, n + 1) if t0 + STEP * j < t1)
    ts.update(k["t"] for k in ks if t0 < k["t"] < t1)
    return sorted(ts)

def _slice(obj, t0, t1):
    o = dict(obj, base=dict(obj["base"]), keys=[])
    first = sample(obj, t0)
    o["base"] = {"p": _r3(first["p"]), "r": _r3(first["r"]), "s": _r3(first["s"])}
    if obj.get("keys"):
        for t in _times(t0, t1, obj["keys"]):
            s = sample(obj, t)
            o["keys"].append({"t": round(t - t0, 3), "p": _r3(s["p"]), "r": _r3(s["r"]), "s": _r3(s["s"]), "e": "lin"})
    return o

def _num(v, where, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise ShotsError("%s 要是 %s–%s 的數字" % (where, lo, hi))
    return round(float(v), 3)

def compile(desc):
    if not isinstance(desc, dict):
        raise ShotsError("鏡頭描述檔要是物件")
    extra = set(desc) - {"version", "scene", "shots"}
    if extra:
        raise ShotsError("鏡頭描述檔不認得的欄位 %s" % "、".join(sorted(extra)))
    if desc.get("version") != VERSION:
        raise ShotsError("version 要是 %d" % VERSION)
    shots = desc.get("shots")
    if not isinstance(shots, list) or not 0 < len(shots) <= MAX_SHOTS:
        raise ShotsError("shots 要有 1–%d 個鏡頭" % MAX_SHOTS)
    sd = desc.get("scene")
    if not isinstance(sd, dict):
        raise ShotsError("scene 要是場景描述檔（filming/scene.py 的形狀）")
    seen, out = set(), []
    base = None
    for i, sh in enumerate(shots):
        w = "shots[%d]" % i
        if not isinstance(sh, dict):
            raise ShotsError("%s 要是物件" % w)
        extra = set(sh) - {"key", "from", "to", "camera"}
        if extra:
            raise ShotsError("%s 不認得的欄位 %s" % (w, "、".join(sorted(extra))))
        key = sh.get("key")
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise ShotsError("%s.key 要是 1–32 個英數字、底線或連字號" % w)
        if key in seen:
            raise ShotsError("%s.key 重複：%s" % (w, key))
        seen.add(key)
        try:
            full = scene.compile(dict(sd, camera=sh.get("camera") or {"move": "static"}))
        except scene.SceneError as e:
            msg = str(e)
            raise ShotsError(w + "." + msg if msg.startswith("camera") else "scene." + msg) from None
        if base is None:
            base = full
        t0 = _num(sh.get("from"), w + ".from", 0, full["dur"])
        t1 = _num(sh.get("to"), w + ".to", 0, full["dur"])
        if not SHOT_MIN <= t1 - t0 <= SHOT_MAX:
            raise ShotsError("%s 長度要 %d–%d 秒（to−from；上游參考影片的範圍）" % (w, SHOT_MIN, SHOT_MAX))
        prev = dict(full, dur=round(t1 - t0, 3), objs=[_slice(o, t0, t1) for o in full["objs"]])
        note = prev.pop("note")
        out.append({"key": key, "from": t0, "to": t1, "camera": dict(sh.get("camera") or {"move": "static"}),
                    "scene": prev, "note": note})
    return {"dur": base["dur"], "aspect": base["aspect"], "shots": out}
