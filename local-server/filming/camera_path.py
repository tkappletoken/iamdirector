import math

SIZE_FRAME = {"ews": (14, 24), "ws": (5, 28), "ms": (1.7, 35), "mcu": (0.95, 50), "cu": (0.5, 85), "ecu": (0.24, 100)}
SPEED_K = {"slow": 0.6, "steady": 1, "fast": 1.6}
SENSOR_H = 24
AIM = {"ecu": 0.93, "cu": 0.92, "mcu": 0.88, "ms": 0.74, "ws": 0.55, "ews": 0.5}

def _jround(x):
    return math.floor(x + 0.5)

def r3(v):
    return _jround(v * 1000) / 1000

def clamp(v, a, b):
    return min(b, max(a, v))

def _num(v, d):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return d
    return f if math.isfinite(f) else d

def vfov(mm):
    return 2 * math.atan(SENSOR_H / 2 / max(6, _num(mm, 35) or 35)) * 180 / math.pi

def _rad(d):
    return d * math.pi / 180

def _ease(u):
    return u * u * (3 - 2 * u)

def _around(T, d, az, y):
    return [T[0] + d * math.sin(_rad(az)), y, T[2] + d * math.cos(_rad(az))]

REF_HEIGHT = 1.7

def subject_scale(scene):
    h = (scene or {}).get("subject_height")
    if h is None:
        return 1.0
    if isinstance(h, bool) or not isinstance(h, (int, float)) or not 0.05 <= h <= 3:
        raise ValueError("subject_height 要是 0.05–3 公尺")
    return h / REF_HEIGHT

def framing(cam, T, scale=1.0):
    c = cam or {}
    h_frame, mm = SIZE_FRAME.get(c.get("size"), SIZE_FRAME["ms"])
    h_frame = h_frame * scale
    half = _rad(vfov(mm) / 2)
    d = clamp(h_frame / 2 / math.tan(half), 0.6 * scale, 60)
    y, roll, top = T[1] + 0.15 * scale, 0, False
    a = c.get("angle")
    if a == "high":
        y = T[1] + d * 0.55
    elif a == "low":
        y = max(0.25 * scale, T[1] - d * 0.35)
    elif a == "top":
        y, top = T[1] + d, True
    elif a == "dutch":
        roll = 14
    return {"d": d, "mm": mm, "y": y, "roll": roll, "top": top}

def cam_path(cam, ctx):
    c = cam or {}
    ctx = ctx or {}
    T = ctx.get("target") or [0, 1.2, 0]
    dur = clamp(_num(ctx.get("dur"), 5), 0.5, 30)
    k = SPEED_K.get(c.get("speed"), 1)
    s = float(ctx.get("scale") or 1.0)
    f = framing(c, T, s)
    c24, c04, c11, c22, c7, c26, c008, c005, c006, c004 = (v * s for v in (2.4, 0.4, 1.1, 2.2, 7, 2.6, 0.08, 0.05, 0.06, 0.04))
    move_end = dur - 1 if dur > 2.5 else dur
    N = 8
    out = []
    note = ""

    def pose(p, look, mm, roll=0):
        return {"p": [r3(x) for x in p], "look": [r3(x) for x in look], "mm": r3(mm), "roll": r3(roll or 0)}

    def at(u, ps):
        out.append(dict({"t": r3(u * move_end)}, **ps))

    def base(az, d, y, look=None, mm=None, roll=None):
        p = [T[0], y, T[2] + 0.01] if f["top"] else _around(T, d, az, y)
        return pose(p, look or T, mm or f["mm"], f["roll"] if roll is None else roll)

    def sweep(fn):
        for i in range(N + 1):
            u = i / N
            at(u, fn(_ease(u)))
    mv = c.get("move") or "static"
    d0, y0 = f["d"], f["y"]
    if mv == "dolly_in":
        sweep(lambda e: base(0, d0 * (1 + 0.5 * k) * (1 - e) + d0 * e, y0))
    elif mv == "dolly_out":
        sweep(lambda e: base(0, d0 + d0 * 0.6 * k * e, y0))
    elif mv == "zoom_in":
        sweep(lambda e: base(0, d0 * 1.6, y0, None, f["mm"] * (1 + 0.9 * k * e) / 1))
        note = "變焦：機位不動，只改焦距"
    elif mv == "zoom_out":
        sweep(lambda e: base(0, d0, y0, None, f["mm"] * (1 + 0.9 * k) / (1 + 0.9 * k * e)))
        note = "變焦：機位不動，只改焦距"
    elif mv == "orbit_l":
        sweep(lambda e: base(-60 * k * e, d0, y0))
    elif mv == "orbit_r":
        sweep(lambda e: base(60 * k * e, d0, y0))
    elif mv == "arc":
        sweep(lambda e: base(-45 * k + 90 * k * e, d0, y0))
    elif mv == "orbit_360":
        sweep(lambda e: base(360 * e, d0, y0))
        note = "360 度環繞：旋轉鏡頭要有正反面參考圖（方塊背面是暗色）"
    elif mv == "crane_up":
        sweep(lambda e: base(0, d0, y0 + c24 * k * e, [T[0], T[1] + c04 * e, T[2]]))
    elif mv == "crane_down":
        sweep(lambda e: base(0, d0, y0 + c24 * k * (1 - e), [T[0], T[1] + c04 * (1 - e), T[2]]))
    elif mv == "tilt_up":
        sweep(lambda e: base(0, d0, y0, [T[0], T[1] - c11 * k + c22 * k * e, T[2]]))
    elif mv == "tilt_down":
        sweep(lambda e: base(0, d0, y0, [T[0], T[1] + c11 * k - c22 * k * e, T[2]]))
    elif mv == "drone_rise":
        sweep(lambda e: base(0, d0 * (1 + 1.5 * e * k), y0 + c7 * k * e, [T[0], T[1] * (1 - e * 0.6), T[2]]))
    elif mv in ("pan_l", "pan_r"):
        sgn = -1 if mv == "pan_l" else 1
        P = _around(T, d0, 0, y0)
        L = math.hypot(T[0] - P[0], T[2] - P[2])

        def pan(e):
            a = _rad(sgn * 40 * k * (e - 0.5))
            return pose(P, [P[0] + L * math.sin(a), T[1], P[2] - L * math.cos(a)], f["mm"], f["roll"])
        sweep(pan)
    elif mv in ("truck_l", "truck_r"):
        sgn = -1 if mv == "truck_l" else 1

        def truck(e):
            dx = sgn * c26 * k * (e - 0.5)
            P = _around(T, d0, 0, y0)
            return pose([P[0] + dx, P[1], P[2]], [T[0] + dx, T[1], T[2]], f["mm"], f["roll"])
        sweep(truck)
    elif mv == "track":
        fol = ctx.get("follow")
        moving = bool(fol) and math.hypot(*[fol(dur)[i] - fol(0)[i] for i in range(3)]) > c005
        if moving:
            for i in range(N + 1):
                t = r3(dur * i / N)
                q = fol(t)
                out.append(dict({"t": t}, **pose(_around(q, d0, 0, y0 - T[1] + q[1]), q, f["mm"], f["roll"])))
        else:
            def push(e):
                dz = -c22 * k * e
                P = _around(T, d0, 0, y0)
                return pose([P[0], P[1], P[2] + dz], [T[0], T[1], T[2] + dz], f["mm"], f["roll"])
            sweep(push)
            note = "跟拍：主體還沒有移動的關鍵幀，先做成往前推；角色打好走位之後再按一次「產生」"
    elif mv == "handheld":
        seed = [7]

        def rnd():
            seed[0] = (seed[0] * 16807) % 2147483647
            return seed[0] / 2147483647 - 0.5
        M = max(4, _jround(dur * 3))
        for i in range(M + 1):
            P = _around(T, d0, 0, y0)
            p = [P[0] + rnd() * c008, P[1] + rnd() * c005, P[2] + rnd() * c005]
            look = [T[0] + rnd() * c006, T[1] + rnd() * c004, T[2]]
            out.append(dict({"t": r3(dur * i / M)}, **pose(p, look, f["mm"], f["roll"] + rnd() * 1.6)))
    elif mv == "dolly_zoom":
        def dz(e):
            d = d0 * (1.8 - 0.9 * e)
            return base(0, d, y0, None, f["mm"] * d / (d0 * 1.8))
        sweep(dz)
        note = "滑動變焦：往前推的同時焦距變廣，主體大小不變、背景拉開"
    elif mv == "whip":
        P = _around(T, d0, 0, y0)
        L = d0
        hold = max(0, dur - 0.6)
        out.append(dict({"t": 0}, **pose(P, T, f["mm"], f["roll"])))
        out.append(dict({"t": r3(hold)}, **pose(P, T, f["mm"], f["roll"])))
        a = _rad(75)
        out.append(dict({"t": r3(dur)}, **pose(P, [P[0] + L * math.sin(a), T[1], P[2] - L * math.cos(a)], f["mm"], f["roll"])))
        note = "甩鏡：最後 0.6 秒快速橫甩（積木預演只表現方向，動態模糊交給模型）"
    elif mv == "roll":
        sweep(lambda e: base(0, d0, y0, None, None, f["roll"] + 28 * k * e))
    elif mv == "rack":
        at(0, base(0, d0, y0))
        note = "移焦在積木預演裡看不出來：機位固定，對焦變化寫在提示詞"
    else:
        at(0, base(0, d0, y0))
    keys = [x for i, x in enumerate(out) if i == 0 or x["t"] - out[i - 1]["t"] > 1e-4]
    return {"keys": keys, "note": note}

def subject_target(scene, t, size):
    from .shots import sample
    aim = AIM.get(size, 0.8)
    pick = [o for o in scene["objs"] if o["kind"] == "char"]
    lst = pick or [o for o in scene["objs"] if o["kind"] == "prop"]
    if not lst:
        return [0, 1.2, 0]
    acc = [0.0, 0.0, 0.0]
    for o in lst:
        p = sample(o, t or 0)["p"]
        acc[0] += p[0]
        acc[2] += p[2]
        acc[1] += (o["size"][1] * aim + p[1]) if o["kind"] == "char" else (o["size"][1] * 0.6 + p[1])
    return [r3(v / len(lst)) for v in acc]

def apply(scene):
    from .shots import sample
    cam = dict(scene["cam"])
    plan = dict(cam.get("plan") or {}, move=cam.get("move") or "static")
    ch = [o for o in scene["objs"] if o["kind"] == "char" and o.get("keys")]
    follow = None
    if ch:
        c0 = ch[0]

        def follow(t):
            p = sample(c0, t)["p"]
            return [p[0], c0["size"][1] * 0.8 + p[1], p[2]]
    res = cam_path(plan, {"target": subject_target(scene, 0, plan.get("size")), "dur": scene["dur"], "follow": follow,
                          "scale": subject_scale(scene)})
    cam["keys"] = res["keys"] if len(res["keys"]) > 1 else []
    if res["keys"]:
        k0 = res["keys"][0]
        cam["base"] = {"p": k0["p"], "look": k0["look"], "mm": k0["mm"], "roll": k0["roll"]}
    return dict(scene, cam=cam), res["note"]

def sample_cam(cam, t):
    from .shots import _cr, _segment
    ks = cam.get("keys") or []
    if not ks:
        b = cam["base"]
        return {"p": list(b["p"]), "look": list(b["look"]), "mm": b["mm"], "roll": b.get("roll") or 0}
    i, u = _segment(ks, t)
    last = len(ks) - 1
    if i >= last or u == 0:
        k = ks[i]
        return {"p": list(k["p"]), "look": list(k["look"]), "mm": k["mm"], "roll": k.get("roll") or 0}
    a, b = ks[i], ks[i + 1]

    def spline(f):
        P = [ks[min(max(j, 0), last)][f] for j in (i - 1, i, i + 1, i + 2)]
        return [_cr(P[0][n], P[1][n], P[2][n], P[3][n], u) for n in range(3)]
    return {"p": spline("p"), "look": spline("look"), "mm": a["mm"] + (b["mm"] - a["mm"]) * u,
            "roll": (a.get("roll") or 0) + ((b.get("roll") or 0) - (a.get("roll") or 0)) * u}
