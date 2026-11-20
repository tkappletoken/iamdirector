import math

from . import camera_path
from .shots import sample

SIZE_H = {"cu": 0.5, "mcu": 0.95, "ms": 1.7}
HEAD = 0.93
EYE = 0.9
HEIGHT_RATIO = 1.15
UPPER_W, HEAD_W = 0.27, 0.14
FIT = 0.95
BACK = 0.9
MM_MIN, MM_MAX = 18, 300

class RigError(ValueError):
    pass

def _find(scene, who):
    chars = [o for o in scene.get("objs", []) if o.get("kind") == "char"]
    for o in chars:
        if who in (o.get("name"), o.get("who"), o.get("id")) and who:
            return o
    raise RigError("場景裡找不到角色 %r（用 name、who 或 id；有 %s）" % (who, "、".join(o.get("name") or o["id"] for o in chars)))

def _pos(o, t):
    p = sample(o, t)["p"]
    return p, o["size"][1]

def _side(pa, pb, side, min_gap=0.2):
    dx, dz = pb[0] - pa[0], pb[2] - pa[2]
    L = math.hypot(dx, dz)
    if L < min_gap:
        raise RigError("兩個角色站得太近（%.2f 公尺，至少 %.2f），分不出 180 度線" % (L, min_gap))
    n = [-dz / L, dx / L]
    if (n[1] < 0) or (n[1] == 0 and n[0] < 0):
        n = [-n[0], -n[1]]
    return n if side == "front" else [-n[0], -n[1]]

def _mm_for(distance, frame_h):
    return round(min(MM_MAX, max(MM_MIN, camera_path.SENSOR_H * distance / frame_h)), 3)

def _cam(p, look, mm):
    r3 = camera_path.r3
    return {"move": "static", "base": {"p": [r3(v) for v in p], "look": [r3(v) for v in look], "mm": r3(mm), "roll": 0},
            "keys": []}

def _check_size(size, allowed):
    if size not in allowed:
        raise RigError("size 只能是 %s" % "／".join(allowed))

def project(cam, point, aspect="16:9"):
    b = cam["base"] if "base" in cam else cam
    p, look = b["p"], b["look"]
    f = [look[i] - p[i] for i in range(3)]
    fl = math.sqrt(sum(v * v for v in f))
    f = [v / fl for v in f]
    r = [-f[2], 0.0, f[0]]
    rl = math.hypot(r[0], r[2]) or 1.0
    r = [v / rl for v in r]
    u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]
    d = [point[i] - p[i] for i in range(3)]
    z = sum(d[i] * f[i] for i in range(3))
    if z <= 1e-6:
        return None
    x, y = sum(d[i] * r[i] for i in range(3)) / z, sum(d[i] * u[i] for i in range(3)) / z
    roll = math.radians(b.get("roll") or 0)
    x, y = x * math.cos(roll) + y * math.sin(roll), -x * math.sin(roll) + y * math.cos(roll)
    tv = math.tan(math.radians(camera_path.vfov(b["mm"])) / 2)
    return (x / (tv * _aspect(aspect)), y / tv)

def head(scene, who, t=0.0):
    o = _find(scene, who)
    p, h = _pos(o, t)
    return [p[0], p[1] + h * HEAD, p[2]]

def ots(scene, over, at, t=0.0, size="mcu", side="front", third=1 / 3, fg=0.75):
    _check_size(size, tuple(SIZE_H))
    a, b = _find(scene, over), _find(scene, at)
    if a is b:
        raise RigError("over 和 at 要是兩個不同的角色")
    pa, ha = _pos(a, t)
    pb, hb = _pos(b, t)
    n = _side(pa, pb, side, 0.2 * camera_path.subject_scale(scene))
    dx, dz = pb[0] - pa[0], pb[2] - pa[2]
    L = math.hypot(dx, dz)
    u = [dx / L, dz / L]
    target = [pb[0], pb[1] + hb * EYE, pb[2]]
    over_head = [pa[0], pa[1] + ha * HEAD, pa[2]]
    sc = camera_path.subject_scale(scene)
    back = BACK * sc
    uneven = max(ha, hb) / min(ha, hb) > HEIGHT_RATIO
    cam_y = pa[1] + ha * 0.97
    aspect = scene.get("aspect")

    def search(mm_fixed=None):
        best = None
        for i in range(1, 121):
            off = i / 100 * sc
            cam = [pa[0] - u[0] * back + n[0] * off, cam_y, pa[2] - u[1] * back + n[1] * off]
            mm = mm_fixed or _mm_for(math.dist(cam, target), SIZE_H[size] * sc)
            rc = _aim(cam, target, over_head, mm, aspect, third)
            po, pt = project(rc, over_head, aspect), project(rc, target, aspect)
            if po is None or pt is None:
                continue
            if uneven and not _clear(rc, over_head, ha, target, hb, aspect):
                continue
            err = abs(abs(po[0]) - fg)
            if best is None or err < best[0]:
                best = (err, rc)
        return best

    best = search()
    if best is None and not uneven:
        raise RigError("排不出過肩：%s 跟 %s 在畫面上投影不到" % (over, at))
    notes = []
    if uneven and (best is None or not _both_in(best[1], (target, over_head), aspect)):
        mm = best[1]["base"]["mm"] if best else _mm_for(BACK * sc + L, SIZE_H[size] * sc)
        while mm > MM_MIN:
            mm = max(MM_MIN, mm * 0.92)
            cand = search(mm)
            if cand is not None:
                best = cand
                if _both_in(best[1], (target, over_head), aspect):
                    break
        notes = ["ots_widened"]
    if best is None:
        raise RigError("排不出過肩：%s 擋住 %s，放廣到 %dmm 也一樣" % (over, at, MM_MIN))
    cam = best[1]
    cam["notes"] = (["ots_weak_fg"] if best[0] > 0.2 else []) + notes
    return cam

def _clear(cam, over_head, ho, target, ht, aspect):
    b = cam["base"]
    po, pt = project(cam, over_head, aspect), project(cam, target, aspect)
    if po is None or pt is None:
        return False
    tw = math.tan(math.radians(camera_path.vfov(b["mm"])) / 2) * _aspect(aspect)
    half = lambda w, p: (w / 2) / max(1e-6, math.dist(b["p"], p)) / tw
    return abs(po[0] - pt[0]) > half(UPPER_W * ho, over_head) + half(HEAD_W * ht, target)

def _both_in(cam, points, aspect):
    for pt in points:
        xy = project(cam, pt, aspect)
        if xy is None or abs(xy[0]) > FIT or abs(xy[1]) > FIT:
            return False
    return True

def _aim(cam, target, over_head, mm, aspect, third):
    straight = _cam(cam, target, mm)
    po = project(straight, over_head, aspect)
    want = -1 if (po is None or po[0] > 0) else 1
    th = math.tan(math.radians(camera_path.vfov(mm)) / 2) * _aspect(aspect)
    delta = math.atan(third * th)
    vx, vz = target[0] - cam[0], target[2] - cam[2]
    for s in (1, -1):
        c, si = math.cos(s * delta), math.sin(s * delta)
        rc = _cam(cam, [cam[0] + vx * c - vz * si, target[1], cam[2] + vx * si + vz * c], mm)
        pt = project(rc, target, aspect)
        if pt and pt[0] * want > 0:
            return rc
    return straight

def reverse(scene, a, b, t=0.0, size="mcu", side="front"):
    return [ots(scene, a, b, t, size, side), ots(scene, b, a, t, size, side)]

def two_shot(scene, a, b, t=0.0, size="ms", side="front", mm=35):
    _check_size(size, ("ms", "ws"))
    oa, ob = _find(scene, a), _find(scene, b)
    if oa is ob:
        raise RigError("a 和 b 要是兩個不同的角色")
    pa, ha = _pos(oa, t)
    pb, hb = _pos(ob, t)
    n = _side(pa, pb, side, 0.2 * camera_path.subject_scale(scene))
    mid = [(pa[0] + pb[0]) / 2, (pa[2] + pb[2]) / 2]
    sep = math.hypot(pb[0] - pa[0], pb[2] - pa[2])
    aspect = _aspect(scene.get("aspect"))
    v = math.radians(camera_path.vfov(mm)) / 2
    h = math.atan(math.tan(v) * aspect)
    frame_h = {"ms": max(ha, hb) * 1.0, "ws": max(ha, hb) * 1.8}[size]
    sc = camera_path.subject_scale(scene)
    d = max((sep + 0.9 * sc) / 2 / math.tan(h), frame_h / 2 / math.tan(v))
    eye = max(ha, hb) * 0.75
    cam = [mid[0] + n[0] * d, eye + 0.1 * sc, mid[1] + n[1] * d]
    look = [mid[0], eye - (0.25 if size == "ms" else 0.35) * max(ha, hb), mid[1]]
    return dict(_cam(cam, look, mm), notes=[])

def _aspect(a):
    try:
        w, h = (int(x) for x in str(a or "16:9").split(":"))
        return w / h
    except (ValueError, ZeroDivisionError):
        return 16 / 9

def rig(scene, spec):
    if not isinstance(spec, dict):
        raise RigError("spec 要是物件")
    kind = spec.get("rig")
    t = spec.get("t", 0.0)
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not 0 <= t <= float(scene.get("dur", 30)):
        raise RigError("t 要在 0 到場景長度之間")
    side = spec.get("side", "front")
    if side not in ("front", "back"):
        raise RigError("side 只能是 front／back")
    if kind == "ots":
        extra = set(spec) - {"rig", "over", "at", "size", "t", "side"}
        if extra:
            raise RigError("ots 不認得的欄位 %s" % "、".join(sorted(extra)))
        return ots(scene, spec.get("over"), spec.get("at"), t, spec.get("size", "mcu"), side)
    if kind == "two_shot":
        extra = set(spec) - {"rig", "a", "b", "size", "t", "side"}
        if extra:
            raise RigError("two_shot 不認得的欄位 %s" % "、".join(sorted(extra)))
        return two_shot(scene, spec.get("a"), spec.get("b"), t, spec.get("size", "ms"), side)
    raise RigError("rig 只能是 ots／two_shot（正反打＝兩支 ots，over 和 at 對調）")

def place(scene, cam):
    return dict(scene, cam=dict(cam))
