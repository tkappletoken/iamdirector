from . import camera_moves

VERSION = 1
MAX_ACTORS, MAX_PROPS, MAX_SET, MAX_PATH = 8, 24, 8, 24
ASPECTS = ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9")
KEY_HEX = ("#8b5cf6", "#22c55e", "#f97316", "#3b82f6", "#ef4444", "#eab308", "#ec4899", "#14b8a6")
PROP_PRESETS = {"chair": (45, 90, 48), "table": (120, 75, 70), "cafe": (70, 75, 70), "cup": (8, 10, 8), "phone": (7, 15, 1),
                "bag": (32, 26, 12), "door": (90, 210, 6), "sofa": (200, 85, 90), "bed": (150, 50, 200),
                "car": (180, 145, 450), "bike": (60, 105, 175), "umbrella": (100, 90, 100), "box": (40, 30, 30)}
SET_PIECES = {"floor": (1200, 2, 1200), "wall": (400, 300, 12), "box": (100, 100, 100), "cyl": (60, 100, 60),
              "ramp": (200, 60, 200)}
TOP = {"version", "dur", "aspect", "actors", "props", "set", "camera"}

class SceneError(ValueError):
    pass

def _num(v, where, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise SceneError("%s 要是 %s–%s 的數字" % (where, lo, hi))
    return round(float(v), 3)

def _at(v, where):
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise SceneError("%s 要是 [x, z]（公尺）" % where)
    return [_num(v[0], where + "[0]", -50, 50), _num(v[1], where + "[1]", -50, 50)]

def _text(v, where, limit=40):
    if v is None:
        return ""
    if not isinstance(v, str) or len(v) > limit or any(ord(c) < 32 for c in v):
        raise SceneError("%s 要是最多 %d 字的文字" % (where, limit))
    return v

def _keys(d, allowed, where):
    if not isinstance(d, dict):
        raise SceneError("%s 要是物件" % where)
    extra = set(d) - allowed
    if extra:
        raise SceneError("%s 不認得的欄位 %s" % (where, "、".join(sorted(extra))))

def _id(prefix, i):
    return "%s%02d" % (prefix, i)

def compile(desc):
    _keys(desc, TOP, "描述檔")
    if desc.get("version") != VERSION:
        raise SceneError("version 要是 %d" % VERSION)
    dur = _num(desc.get("dur", 5), "dur", 1, 30)
    aspect = desc.get("aspect", "16:9")
    if aspect not in ASPECTS:
        raise SceneError("aspect 只能是 %s" % "／".join(ASPECTS))
    objs = []
    for i, s in enumerate(desc.get("set") or [{"kind": "floor"}]):
        w = "set[%d]" % i
        _keys(s, {"kind", "at", "face", "size_cm"}, w)
        if s.get("kind") not in SET_PIECES:
            raise SceneError("%s.kind 只能是 %s" % (w, "／".join(SET_PIECES)))
        cm = s.get("size_cm") or SET_PIECES[s["kind"]]
        if not isinstance(cm, (list, tuple)) or len(cm) != 3:
            raise SceneError("%s.size_cm 要是 [寬, 高, 深]（公分）" % w)
        x, z = _at(s.get("at", [0, 0]), w + ".at")
        objs.append(_obj(_id("s", i), s["kind"], "", "", "#b9bdc3" if s["kind"] == "floor" else "#c9ccd1",
                         [_num(c, w + ".size_cm", 1, 6000) / 100 for c in cm], x, z, s.get("face", 0), w))
    if len(objs) > MAX_SET:
        raise SceneError("set 最多 %d 件" % MAX_SET)
    props = desc.get("props") or []
    if len(props) > MAX_PROPS:
        raise SceneError("props 最多 %d 個" % MAX_PROPS)
    for i, p in enumerate(props):
        w = "props[%d]" % i
        _keys(p, {"preset", "name", "at", "face", "size_cm"}, w)
        if p.get("preset") not in PROP_PRESETS:
            raise SceneError("%s.preset 只能是 %s" % (w, "／".join(PROP_PRESETS)))
        cm = p.get("size_cm") or PROP_PRESETS[p["preset"]]
        if not isinstance(cm, (list, tuple)) or len(cm) != 3:
            raise SceneError("%s.size_cm 要是 [寬, 高, 深]（公分）" % w)
        x, z = _at(p.get("at", [0, 0]), w + ".at")
        o = _obj(_id("p", i), "prop", _text(p.get("name"), w + ".name"), "", "#9ea3aa",
                 [_num(c, w + ".size_cm", 1, 6000) / 100 for c in cm], x, z, p.get("face", 0), w)
        o["preset"] = p["preset"]
        objs.append(o)
    actors = desc.get("actors") or []
    if not 0 < len(actors) <= MAX_ACTORS:
        raise SceneError("actors 要有 1–%d 個角色" % MAX_ACTORS)
    for i, a in enumerate(actors):
        w = "actors[%d]" % i
        _keys(a, {"name", "who", "height", "at", "face", "path"}, w)
        h = _num(a.get("height", 1.72), w + ".height", 0.2, 3)
        x, z = _at(a.get("at", [0, 0]), w + ".at")
        o = _obj(_id("c", i), "char", _text(a.get("name"), w + ".name"), _text(a.get("who"), w + ".who"),
                 KEY_HEX[i % len(KEY_HEX)], [0.5, h, 0.3], x, z, a.get("face", 0), w)
        path = a.get("path") or []
        if not isinstance(path, list) or len(path) > MAX_PATH:
            raise SceneError("%s.path 要是最多 %d 個點的陣列" % (w, MAX_PATH))
        if path:
            keys, last = [{"t": 0.0, "p": o["base"]["p"], "r": o["base"]["r"], "s": [1, 1, 1], "e": "io"}], 0.0
            for j, k in enumerate(path):
                wk = "%s.path[%d]" % (w, j)
                _keys(k, {"t", "at", "face"}, wk)
                t = _num(k.get("t"), wk + ".t", 0.05, dur)
                if t <= last:
                    raise SceneError("%s.t 要比前一個點晚" % wk)
                kx, kz = _at(k.get("at"), wk + ".at")
                face = _num(k.get("face", a.get("face", 0)), wk + ".face", -360, 360)
                keys.append({"t": t, "p": [kx, 0.0, kz], "r": [0.0, face, 0.0], "s": [1, 1, 1], "e": "io"})
                last = t
            o["keys"] = keys
        objs.append(o)
    cam = desc.get("camera") or {"move": "static"}
    _keys(cam, {"move", "speed", "size", "angle"}, "camera")
    try:
        pc = camera_moves.previs_cam(cam.get("move", "static"), cam.get("speed"), cam.get("size", "ms"), cam.get("angle", "eye"))
    except camera_moves.MoveError as e:
        raise SceneError("camera：%s" % e) from None
    note = "" if pc else "這個運鏡 3D 預演做不到，只寫進提示詞（%s）" % cam.get("move")
    return {"v": VERSION, "dur": dur, "fps": 24, "aspect": aspect, "objs": objs,
            "cam": {"move": (pc or {}).get("move", "static"), "base": {"p": [0, 1.55, 5], "look": [0, 1.2, 0], "mm": 35, "roll": 0},
                    "keys": [], "plan": {k: v for k, v in (pc or {}).items() if k != "move"}},
            "note": note}

def _obj(oid, kind, name, who, color, size, x, z, face, where):
    face = _num(face, where + ".face", -360, 360)
    return {"id": oid, "kind": kind, "name": name, "who": who, "preset": "", "color": color,
            "size": [round(v, 3) for v in size], "base": {"p": [x, 0.0, z], "r": [0.0, face, 0.0], "s": [1, 1, 1]},
            "keys": []}
