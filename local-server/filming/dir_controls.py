import math
import re

from . import blender, camera_moves, camera_path, camera_rigs, scene as scene_mod

VERSION = 1
MAX_TEXT = 120
MAX_NOTES = 10
MAX_NOTE = 200
MAX_NAME = 40
MAX_PROMPT = 2000
MAX_ACTORS = 8
MAX_REFS = 10
TEXT_FIELDS = ("lens", "style", "color", "light", "location", "sound")
SPEEDS = ("slow", "medium", "fast")
CAMERA_KEYS = ("move", "speed", "direction", "end", "size", "angle", "allow_cuts", "rig")
RIG_KEYS = {"ots": ("type", "over", "at", "t", "side"), "reverse": ("type", "over", "at", "t", "side"),
            "two_shot": ("type", "a", "b", "t", "side")}
RIG_SIZES = {"ots": ("cu", "mcu", "ms"), "reverse": ("cu", "mcu", "ms"), "two_shot": ("ms", "ws")}
RIG_DEFAULT_SIZE = {"ots": "mcu", "reverse": "mcu", "two_shot": "ms"}
RIG_NOTE_HINT = {"ots_widened": "ots_widened（兩個角色身高差太多，焦距放廣到兩個頭都入鏡，實際景別比要求的寬；近景建議改用單人鏡）",
                 "ots_weak_fg": "ots_weak_fg（前景的人拉不到畫面邊上；建議改用中近景或特寫，或讓兩人站開一點）"}
RARE = ("tiny_planet", "bullet_time", "bolt_cam")
KEYS = ("version", "prompt", "model", "shot", "cast", "camera", "blocking", "performance",
        "first_frame", "last_frame", "references", "resolution") + TEXT_FIELDS

SIZES = {"大遠景": "extreme wide shot", "遠景": "wide shot", "全景": "full shot", "中景": "medium shot",
         "中近景": "medium close-up", "近景": "close shot", "特寫": "close-up", "大特寫": "extreme close-up"}
SIZE_IDS = {"ews": "大遠景", "ws": "遠景", "ms": "中景", "mcu": "中近景", "cu": "特寫", "ecu": "大特寫"}
ANGLES = {"eye": "eye-level", "high": "high angle", "low": "low angle", "top": "top-down angle", "dutch": "dutch angle"}
XS = {"left": "frame left", "center": "frame center", "right": "frame right"}
DEPTHS = {"front": "in the foreground", "mid": "in the midground", "back": "in the background"}
FACINGS = {"camera": "facing the camera", "left": "facing left", "right": "facing right", "away": "facing away"}
BLOCK_KEYS = ("name", "at", "facing", "to", "action")
HOLD_MARKS = "Characters keep their screen positions."
REF_OK = re.compile(r"^(asset://|https?://|data:image/)", re.I)
REF_TYPES = ("image", "video", "audio")

class DirControlsError(ValueError):
    pass

def _bad(where, msg):
    raise DirControlsError("%s %s" % (where, msg))

def _txt(v, where, limit=MAX_TEXT):
    if v is None:
        return ""
    if not isinstance(v, str):
        _bad(where, "要是字串")
    s = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", v)).strip()
    if len(s) > limit:
        _bad(where, "最多 %d 字" % limit)
    return s

def _keys(d, allowed, where):
    if not isinstance(d, dict):
        _bad(where, "要是物件")
    extra = set(d) - set(allowed)
    if extra:
        _bad(where, "不認得的欄位 %s" % "、".join(sorted(extra)))

def _ref(v, where):
    s = _txt(v, where, 4096)
    if s and not REF_OK.match(s):
        _bad(where, "要是 asset://、http(s):// 或 data:image/ 開頭")
    return s

def _mark(m, where, need_x):
    _keys(m, ("x", "depth"), where)
    out = {}
    if m.get("x") is not None or need_x:
        if m.get("x") not in XS:
            _bad(where + ".x", "只能是 %s" % "／".join(XS))
        out["x"] = m["x"]
    if m.get("depth") is not None:
        if m["depth"] not in DEPTHS:
            _bad(where + ".depth", "只能是 %s" % "／".join(DEPTHS))
        out["depth"] = m["depth"]
    if not out:
        _bad(where, "至少要有 x 或 depth")
    return out

def _rig(r):
    if not isinstance(r, dict) or r.get("type") not in RIG_KEYS:
        _bad("camera.rig.type", "只能是 %s" % "／".join(RIG_KEYS))
    _keys(r, RIG_KEYS[r["type"]], "camera.rig")
    out = {"type": r["type"]}
    pair = ("a", "b") if r["type"] == "two_shot" else ("over", "at")
    for k in pair:
        n = _txt(r.get(k), "camera.rig." + k, MAX_NAME)
        if not n:
            _bad("camera.rig." + k, "要是角色名字")
        out[k] = n
    if out[pair[0]] == out[pair[1]]:
        _bad("camera.rig", "%s 和 %s 要是兩個不同的角色" % pair)
    t = r.get("t", 0)
    if isinstance(t, bool) or not isinstance(t, (int, float)) or t < 0:
        _bad("camera.rig.t", "要是 ≥0 的秒數")
    out["t"] = t
    if r.get("side", "front") not in ("front", "back"):
        _bad("camera.rig.side", "只能是 front／back")
    out["side"] = r.get("side", "front")
    return out

def _camera(c):
    _keys(c, CAMERA_KEYS, "camera")
    out = {}
    mv = c.get("move")
    if mv not in (None, ""):
        if mv not in camera_moves.PREVIS:
            _bad("camera.move", "不認得：%r（用 shot_controls 的 24 種運鏡 id）" % (mv,))
        out["move"] = mv
    sp = c.get("speed")
    if sp not in (None, ""):
        if sp not in SPEEDS:
            _bad("camera.speed", "只能是 %s" % "／".join(SPEEDS))
        out["speed"] = sp
    for k in ("direction", "end"):
        t = _txt(c.get(k), "camera." + k)
        if t:
            out[k] = t
    sz = c.get("size")
    if sz not in (None, ""):
        sz = SIZE_IDS.get(sz, sz)
        if sz not in SIZES:
            _bad("camera.size", "只能是 %s 或 %s" % ("、".join(SIZES), "／".join(SIZE_IDS)))
        out["size"] = sz
    an = c.get("angle")
    if an not in (None, ""):
        if an not in ANGLES:
            _bad("camera.angle", "只能是 %s" % "／".join(ANGLES))
        out["angle"] = an
    if c.get("rig") is not None:
        out["rig"] = _rig(c["rig"])
    if c.get("allow_cuts") not in (None, False, True):
        _bad("camera.allow_cuts", "要是 true／false")
    if c.get("allow_cuts") is True:
        out["allow_cuts"] = True
    return out

def check(desc):
    _keys(desc, KEYS, "描述檔")
    if desc.get("version") != VERSION:
        _bad("version", "要是 %d" % VERSION)
    out = {"version": VERSION}
    out["prompt"] = _txt(desc.get("prompt"), "prompt", MAX_PROMPT)
    if not out["prompt"]:
        _bad("prompt", "不能是空的（畫面描述）")
    for k in ("model", "resolution"):
        t = _txt(desc.get(k), k, 80)
        if t:
            out[k] = t
    shot = desc.get("shot")
    if shot is not None:
        if isinstance(shot, bool) or not isinstance(shot, int) or shot < 1:
            _bad("shot", "要是 ≥1 的整數（第幾鏡）")
        out["shot"] = shot
    cast = desc.get("cast")
    if cast not in (None, False):
        if cast is not True and not (isinstance(cast, list) and cast and all(isinstance(x, str) and x.strip() for x in cast)):
            _bad("cast", "要是 true（用角色庫）或角色名字清單")
        out["cast"] = True if cast is True else [x.strip()[:MAX_NAME] for x in cast]
    out["camera"] = _camera(desc["camera"]) if desc.get("camera") is not None else {}
    for k in TEXT_FIELDS:
        t = _txt(desc.get(k), k)
        if t:
            out[k] = t
    blocking = desc.get("blocking") or []
    if not isinstance(blocking, list) or len(blocking) > MAX_ACTORS:
        _bad("blocking", "要是最多 %d 個角色的清單" % MAX_ACTORS)
    names, out["blocking"] = set(), []
    for i, b in enumerate(blocking):
        w = "blocking[%d]" % i
        _keys(b, BLOCK_KEYS, w)
        name = _txt(b.get("name"), w + ".name", MAX_NAME)
        if not name:
            _bad(w + ".name", "不能是空的")
        if name in names:
            _bad(w + ".name", "重複：%s" % name)
        names.add(name)
        one = {"name": name, "at": _mark(b.get("at"), w + ".at", need_x=True)}
        fc = b.get("facing")
        if fc not in (None, ""):
            fc = _txt(fc, w + ".facing", MAX_NAME)
            if fc not in FACINGS and fc not in {x.get("name") for x in blocking if isinstance(x, dict)}:
                _bad(w + ".facing", "只能是 %s 或另一個角色的名字" % "／".join(FACINGS))
            if fc == name:
                _bad(w + ".facing", "不能面向自己")
            one["facing"] = fc
        if b.get("to") is not None:
            one["to"] = _mark(b["to"], w + ".to", need_x=False)
        act = _txt(b.get("action"), w + ".action")
        if act:
            one["action"] = act
        out["blocking"].append(one)
    rig = out["camera"].get("rig")
    if rig:
        missing = [rig[k] for k in ("over", "at", "a", "b") if k in rig and rig[k] not in names]
        if missing:
            _bad("camera.rig", "%s 不在 blocking 裡（機位要照站位算）" % "、".join(missing))
    perf = desc.get("performance") or []
    if not isinstance(perf, list) or len(perf) > MAX_ACTORS:
        _bad("performance", "要是最多 %d 個角色的清單" % MAX_ACTORS)
    seen, out["performance"] = set(), []
    for i, p in enumerate(perf):
        w = "performance[%d]" % i
        _keys(p, ("name", "notes"), w)
        name = _txt(p.get("name"), w + ".name", MAX_NAME)
        if not name or name in seen:
            _bad(w + ".name", "不能是空的或重複")
        seen.add(name)
        notes = p.get("notes")
        if not isinstance(notes, list) or not notes or len(notes) > MAX_NOTES:
            _bad(w + ".notes", "要是 1–%d 條筆記" % MAX_NOTES)
        clean = [_txt(n, "%s.notes[%d]" % (w, j), MAX_NOTE) for j, n in enumerate(notes)]
        clean = [n for n in clean if n]
        if not clean:
            _bad(w + ".notes", "不能全是空的")
        out["performance"].append({"name": name, "notes": clean})
    for k in ("first_frame", "last_frame"):
        r = _ref(desc.get(k), k)
        if r:
            out[k] = r
    refs = desc.get("references") or []
    if not isinstance(refs, list) or len(refs) > MAX_REFS:
        _bad("references", "要是最多 %d 張的清單" % MAX_REFS)
    out["references"] = []
    for i, r in enumerate(refs):
        w = "references[%d]" % i
        _keys(r, ("url", "type", "role"), w)
        url = _ref(r.get("url"), w + ".url")
        if not url:
            _bad(w + ".url", "不能是空的")
        tp = r.get("type") or "image"
        if tp not in REF_TYPES:
            _bad(w + ".type", "只能是 %s" % "／".join(REF_TYPES))
        out["references"].append({"type": tp, "url": url, "role": _txt(r.get("role"), w + ".role", 40) or "reference_image"})
    return out

def _where(m):
    segs = [XS[m["x"]]] if m.get("x") else []
    if m.get("depth"):
        segs.append(DEPTHS[m["depth"]])
    return " ".join(segs)

def blocking_line(blocking):
    if not blocking:
        return ""
    parts = []
    for b in blocking:
        s = "%s stands %s" % (b["name"], _where(b["at"]))
        fc = b.get("facing")
        if fc:
            s += ", " + (FACINGS[fc] if fc in FACINGS else "facing " + fc)
        if b.get("action"):
            s += ", " + b["action"].rstrip(" .。")
        if b.get("to"):
            s += ", then moves to " + _where(b["to"])
        parts.append(s)
    line = "Blocking: " + "; ".join(parts) + "."
    if len(blocking) > 1 and not any(b.get("to") for b in blocking):
        line += " " + HOLD_MARKS
    return line

def performance_lines(perf):
    return ["Performance (%s): %s." % (p["name"], "; ".join(n.rstrip(".。") for n in p["notes"])) for p in perf]

RIG_TEXT = {"ots": "over-the-shoulder shot from behind {over}, framing {at}",
            "reverse": "reverse over-the-shoulder shot from behind {at}, framing {over}",
            "two_shot": "two-shot of {a} and {b}"}

def shot_line(cam):
    segs = [SIZES[cam["size"]]] if cam.get("size") else []
    if cam.get("rig"):
        segs.append(RIG_TEXT[cam["rig"]["type"]].format(**cam["rig"]))
    if cam.get("angle"):
        segs.append(ANGLES[cam["angle"]])
    return ("Shot: " + ", ".join(segs) + ".") if segs else ""

def controls_of(c):
    cam = c["camera"]
    out = {}
    for src, dst in (("move", "camera_move"), ("speed", "speed"), ("direction", "direction"), ("end", "end"),
                     ("allow_cuts", "allow_cuts")):
        if src in cam:
            out[dst] = cam[src]
    for k in TEXT_FIELDS:
        if c.get(k):
            out[k] = c[k]
    return out

def _status(caps, kind):
    return ((caps.get(kind) or {}).get("status")) or "untested"

def compose(desc, caps=None, apply_controls=None):
    c = check(desc)
    caps = caps if isinstance(caps, dict) else {}
    cam = c["camera"]
    warnings, support = [], {}

    def warn(code):
        if code not in warnings:
            warnings.append(code)

    segs = [shot_line(cam), c["prompt"], blocking_line(c["blocking"])] + performance_lines(c["performance"])
    body = {"prompt": re.sub(r"\s{2,}", " ", " ".join(s for s in segs if s)).strip()}
    if c.get("model"):
        body["model"] = c["model"]
    if c.get("resolution"):
        body["resolution"] = c["resolution"]
        res = caps.get("resolutions")
        if res and c["resolution"] not in res:
            warn("resolution_unsupported")
    ctl = controls_of(c)
    if ctl:
        body["controls"] = ctl
    for k in ("camera", "blocking", "performance") + TEXT_FIELDS:
        if (k == "camera" and cam) or (k != "camera" and c.get(k)):
            support[k] = "text"
    if cam.get("move") in RARE:
        warn("rare_move")
    if cam.get("move") and camera_moves.PREVIS[cam["move"]] is None and c.get("first_frame"):
        warn("no_previs_move")

    ff = caps.get("first_frame") or {}
    first, last = c.get("first_frame"), c.get("last_frame")
    if first:
        st = _status(caps, "first_frame")
        if st == "fail":
            warn("first_frame_fail")
            first, support["first_frame"] = None, "dropped"
        else:
            if st != "ok":
                warn("first_frame_untested")
            support["first_frame"] = st
    if last:
        st = _status(caps, "last_frame")
        if st == "fail":
            warn("last_frame_fail")
            last, support["last_frame"] = None, "dropped"
        elif ff.get("status") == "ok" and ff.get("field") in ("frame_images_str", "image_url") and st != "ok":
            warn("last_frame_unsupported")
            last, support["last_frame"] = None, "dropped"
        else:
            if st != "ok":
                warn("last_frame_untested")
            support["last_frame"] = st
    if first:
        body["first_frame"] = first
    if last:
        body["last_frame"] = last
    refs = c["references"]
    if refs:
        st = _status(caps, "input_references")
        if first or last:
            warn("refs_dropped_frames")
            support["references"] = "dropped"
        elif st == "fail":
            warn("input_references_fail")
            support["references"] = "dropped"
        else:
            if st != "ok":
                warn("input_references_untested")
            support["references"] = st
            body["input_references"] = [dict(r) for r in refs]
    if c.get("cast") is not None:
        body["cast"] = c["cast"]
        if c.get("shot"):
            body["cast_shot"] = c["shot"]
        support["cast"] = "text"
        if first or last:
            warn("cast_refs_skipped_frames")
    out = {"body": body, "warnings": warnings, "support": support}
    if apply_controls is not None:
        out["prompt"], extra = apply_controls(body["prompt"], ctl) if ctl else (body["prompt"], [])
        for w in extra:
            warn(w)
    return out

def accumulate(notes, new):
    out = []
    for n in list(notes or []) + list(new or []):
        if not isinstance(n, str):
            continue
        s = re.sub(r"\s+", " ", n).strip()[:MAX_NOTE]
        if s:
            if s in out:
                out.remove(s)
            out.append(s)
    return out[-MAX_NOTES:]

SIZE_TO_PREVIS = {"大遠景": "ews", "遠景": "ws", "全景": "ws", "中景": "ms", "中近景": "mcu", "近景": "mcu",
                  "特寫": "cu", "大特寫": "ecu"}
LOSSY_SIZES = ("全景", "近景")
ASPECT_WH = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:3": 4 / 3, "3:4": 3 / 4, "21:9": 21 / 9}
DEPTH_K = {"front": 0.3, "mid": 0.0, "back": -0.6}
FACE_DEG = {"camera": 0.0, "away": 180.0, "left": -90.0, "right": 90.0}

def _xz(mark, frame_w, frame_h, prev=None):
    px, pz = prev or (0.0, 0.0)
    x = {"left": -frame_w / 3, "center": 0.0, "right": frame_w / 3}[mark["x"]] if mark.get("x") else px
    z = DEPTH_K[mark["depth"]] * frame_h if mark.get("depth") else pz
    return [round(x, 3), round(z, 3)]

def _face(facing, me, others, default=0.0):
    if not facing:
        return default
    if facing in FACE_DEG:
        return FACE_DEG[facing]
    ox, oz = others[facing]
    return round(math.degrees(math.atan2(ox - me[0], oz - me[1])), 3)

DEFAULT_HEIGHT = 1.72

def _footprint(h):
    H = max(0.3, h)
    return blender.FIG["upper"][0] * H, blender.FIG["upper"][2] * H

def subject_height(desc, heights=None):
    c = check(desc)
    hs = heights or {}
    names = [b["name"] for b in c["blocking"]]
    if not any(n in hs for n in names):
        return None
    return max(hs.get(n, DEFAULT_HEIGHT) for n in names)
SIZE_ORDER = ("ecu", "cu", "mcu", "ms", "ws", "ews")

def _marks(blocking, size, aspect, scale=1.0):
    frame_h = camera_path.SIZE_FRAME[size][0] * scale
    frame_w = frame_h * ASPECT_WH[aspect]
    start = {b["name"]: _xz(b["at"], frame_w, frame_h) for b in blocking}
    end = {b["name"]: _xz(b["to"], frame_w, frame_h, start[b["name"]]) if b.get("to") else start[b["name"]]
           for b in blocking}
    return start, end

def _crowded(start, end, heights=None):
    hs = heights or {}
    fp = {n: _footprint(hs.get(n, DEFAULT_HEIGHT)) for n in start}
    worst = None
    names = list(start)
    for pos in (start, end):
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                dx, dz = abs(pos[a][0] - pos[b][0]), abs(pos[a][1] - pos[b][1])
                if dx < (fp[a][0] + fp[b][0]) / 2 and dz < (fp[a][1] + fp[b][1]) / 2 and (worst is None or dx < worst[2]):
                    worst = (a, b, round(dx, 3))
    return worst

def _roomy_size(blocking, size, aspect, scale=1.0, heights=None):
    for s in SIZE_ORDER[SIZE_ORDER.index(size) + 1:]:
        if not _crowded(*_marks(blocking, s, aspect, scale), heights=heights):
            return SIZE_IDS[s]
    return SIZE_IDS["ews"]

def scene_desc(desc, dur=5, aspect="9:16", heights=None, props=None, set_pieces=None):
    c = check(desc)
    if not c["blocking"]:
        raise DirControlsError("blocking 至少要一個角色才能轉 3D 預演")
    if aspect not in ASPECT_WH:
        _bad("aspect", "只能是 %s" % "／".join(ASPECT_WH))
    cam = c["camera"]
    notes = []
    rig = cam.get("rig")
    size = SIZE_TO_PREVIS.get(cam.get("size"), RIG_DEFAULT_SIZE[rig["type"]] if rig else "ms")
    if rig and size not in RIG_SIZES[rig["type"]]:
        _bad("camera.size", "%s 只能配 %s" % (rig["type"], "、".join(SIZE_IDS[x] for x in RIG_SIZES[rig["type"]])))
    if rig and cam.get("move") not in (None, "static"):
        notes.append("rig_static_only")
    if cam.get("size") in LOSSY_SIZES:
        notes.append("size_approx:%s→%s" % (cam["size"], size))
    if cam.get("move") and camera_moves.PREVIS[cam["move"]] is None:
        notes.append("no_previs_move")
    place_size = size if not rig or SIZE_ORDER.index(size) >= SIZE_ORDER.index("ms") else "ms"
    sh = subject_height(desc, heights)
    try:
        scale = camera_path.subject_scale({"subject_height": sh}) if sh is not None else 1.0
    except ValueError as e:
        raise DirControlsError("heights %s" % e) from None
    start, end = _marks(c["blocking"], place_size, aspect, scale)
    crowd = None if rig and rig["type"] != "two_shot" else _crowded(start, end, heights)
    if crowd:
        a, b, gap = crowd
        notes.append("crowded_frame:%s／%s:%.2fm（建議改用%s以上，或用過肩）"
                     % (a, b, gap, _roomy_size(c["blocking"], size, aspect, scale, heights)))
    arrive = round(dur - 1 if dur > 2.5 else dur, 3)
    heights = heights or {}
    actors = []
    for b in c["blocking"]:
        n = b["name"]
        a = {"name": n, "who": n, "at": start[n], "face": _face(b.get("facing"), start[n], start)}
        h = heights.get(n)
        if h is not None:
            a["height"] = h
        if b.get("to") and end[n] != start[n]:
            a["path"] = [{"t": arrive, "at": end[n], "face": _face(b.get("facing"), end[n], end, a["face"])}]
        actors.append(a)
    sd = {"version": scene_mod.VERSION, "dur": dur, "aspect": aspect, "actors": actors,
          "camera": {"move": cam.get("move") or "static", "size": size, "angle": cam.get("angle") or "eye"}}
    if cam.get("speed"):
        sd["camera"]["speed"] = cam["speed"]
    if props:
        sd["props"] = props
    if set_pieces:
        sd["set"] = set_pieces
    return sd, notes

def to_scene(desc, dur=5, aspect="9:16", heights=None, props=None, set_pieces=None):
    sd, notes = scene_desc(desc, dur, aspect, heights, props, set_pieces)
    try:
        out = scene_mod.compile(sd)
    except scene_mod.SceneError as e:
        raise DirControlsError("scene.%s" % e) from None
    sh = subject_height(desc, heights)
    if sh is not None:
        out["subject_height"] = sh
    rig = check(desc)["camera"].get("rig")
    if rig:
        spec = {"rig": "two_shot" if rig["type"] == "two_shot" else "ots", "t": min(rig["t"], out["dur"]),
                "side": rig["side"], "size": out["cam"]["plan"]["size"]}
        if rig["type"] == "two_shot":
            spec.update(a=rig["a"], b=rig["b"])
        elif rig["type"] == "ots":
            spec.update(over=rig["over"], at=rig["at"])
        else:
            spec.update(over=rig["at"], at=rig["over"])
        try:
            cam = camera_rigs.rig(out, spec)
        except camera_rigs.RigError as e:
            raise DirControlsError("camera.rig %s" % e) from None
        for n in cam.pop("notes", []):
            n = RIG_NOTE_HINT.get(n, n)
            if n not in notes:
                notes.append(n)
        out = camera_rigs.place(out, cam)
    out["notes"] = notes
    return out

CAMERA_WORDS = (
    ("固定鏡頭", "static"), ("固定", "static"), ("靜止", "static"), ("不動", "static"),
    ("向左橫搖", "pan_left"), ("向右橫搖", "pan_right"), ("左搖", "pan_left"), ("右搖", "pan_right"),
    ("向上仰", "tilt_up"), ("向下俯", "tilt_down"), ("上仰", "tilt_up"), ("下俯", "tilt_down"),
    ("變焦推近", "zoom_in"), ("變焦拉遠", "zoom_out"), ("急推變焦", "crash_zoom"), ("急推", "crash_zoom"),
    ("滑動變焦", "dolly_zoom"), ("希區考克", "dolly_zoom"),
    ("緩推", "dolly_in"), ("推近", "dolly_in"), ("推進", "dolly_in"), ("拉遠", "dolly_out"), ("拉開", "dolly_out"),
    ("向左平移", "truck_left"), ("向右平移", "truck_right"), ("左移", "truck_left"), ("右移", "truck_right"),
    ("垂直上升", "pedestal_up"), ("垂直下降", "pedestal_down"),
    ("搖臂上升", "crane_up"), ("搖臂下降", "crane_down"), ("升鏡", "crane_up"), ("降鏡", "crane_down"),
    ("弧形繞拍", "arc"), ("弧形", "arc"), ("繞拍", "arc"), ("環繞一圈", "orbit_360"), ("環繞", "orbit_360"),
    ("跟拍", "tracking"), ("跟隨", "tracking"), ("手持", "handheld"), ("甩鏡", "whip_pan"), ("甩", "whip_pan"),
    ("空拍", "aerial"), ("小星球", "tiny_planet"), ("子彈時間", "bullet_time"), ("鏡頭旋轉", "camera_roll"),
    ("移焦", "rack_focus"), ("穿越機", "fpv_drone"), ("俯衝", "top_down_drop"), ("高速機械臂", "bolt_cam"),
    ("機械臂", "bolt_cam"),
)
CAMERA_GUESS = (("橫搖", "pan_right"), ("平移", "truck_right"), ("搖鏡", "pan_right"), ("推", "dolly_in"),
                ("拉", "dolly_out"), ("仰", "tilt_up"), ("俯", "tilt_down"))
SLOW_WORDS, FAST_WORDS = ("緩", "慢", "輕"), ("快", "急", "猛")
SB_KEYS = ("prompt", "seconds", "shot_size", "camera", "cast") + TEXT_FIELDS
SPLIT_CAST = re.compile(r"[、,，/／;；\s]+")
AUTO_X = {1: ("center",), 2: ("left", "right"), 3: ("left", "center", "right")}

def parse_camera(text):
    t = str(text or "").strip()
    if not t:
        return {}, ["camera"], []
    hits, taken = [], [False] * len(t)
    for table, guess in ((CAMERA_WORDS, False), (CAMERA_GUESS, True)):
        for w, mv in sorted(table, key=lambda x: -len(x[0])):
            start = 0
            while True:
                i = t.find(w, start)
                if i < 0:
                    break
                if not any(taken[i:i + len(w)]):
                    hits.append((i, mv, guess))
                    for j in range(i, i + len(w)):
                        taken[j] = True
                start = i + 1
    if not hits:
        return {}, ["camera.move"], []
    hits.sort()
    out, gaps, guessed = {"move": hits[0][1]}, [], []
    if hits[0][2]:
        guessed.append("camera.move")
    if len({h[1] for h in hits}) > 1:
        gaps.append("camera.multiple_moves")
    if out["move"] != "static":
        if any(w in t for w in SLOW_WORDS):
            out["speed"] = "slow"
        elif any(w in t for w in FAST_WORDS):
            out["speed"] = "fast"
    return out, gaps, guessed

def _cast_names(cast):
    out = []
    for c in cast or []:
        n = c.get("name") if isinstance(c, dict) else c
        if isinstance(n, str) and n.strip():
            out.append(n.strip()[:MAX_NAME])
    return out

def from_storyboard(sb_shot, cast=None):
    if not isinstance(sb_shot, dict):
        raise DirControlsError("分鏡 要是物件（storyboard.parse_shots 的一鏡）")
    gaps, guessed = ["unknown:%s" % k for k in sorted(set(sb_shot) - set(SB_KEYS))], []
    prompt = re.sub(r"\s+", " ", str(sb_shot.get("prompt") or "")).strip()[:MAX_PROMPT]
    if not prompt:
        raise DirControlsError("分鏡 prompt 是空的：沒有畫面描述擬不出草稿")
    desc = {"version": VERSION, "prompt": prompt}
    cam, g2, g3 = parse_camera(sb_shot.get("camera"))
    gaps += g2
    guessed += g3
    size = str(sb_shot.get("shot_size") or "").strip()
    if size in SIZES:
        cam["size"] = size
    else:
        gaps.append("camera.size")
    if cam:
        desc["camera"] = cam
    for k in TEXT_FIELDS:
        v = re.sub(r"[\x00-\x1f\x7f]", " ", str(sb_shot.get(k) or ""))
        v = re.sub(r"\s+", " ", v).strip()[:MAX_TEXT]
        if v:
            desc[k] = v
    names = [n.strip()[:MAX_NAME] for n in SPLIT_CAST.split(str(sb_shot.get("cast") or "")) if n.strip()]
    names = list(dict.fromkeys(names))
    library = _cast_names(cast)
    known = [n for n in names if n in library]
    gaps += ["cast:%s" % n for n in names if n not in library]
    if known:
        desc["cast"] = known
    who = known[:3]
    if len(known) > 3:
        gaps.append("blocking:too_many")
    if who:
        xs = AUTO_X[len(who)]
        desc["blocking"] = [{"name": n, "at": {"x": x},
                             "facing": (who[1 - i] if len(who) == 2 else "camera")} for i, (n, x) in enumerate(zip(who, xs))]
        guessed.append("blocking")
    elif names:
        gaps.append("blocking")
    sec = sb_shot.get("seconds")
    dur = sec if isinstance(sec, (int, float)) and not isinstance(sec, bool) and sec > 0 else None
    if dur is None:
        gaps.append("seconds")
    check(desc)
    return {"desc": desc, "dur": dur, "draft_gaps": gaps, "guessed": guessed}

MUST_ASK_PREFIX = ("cast:", "blocking:too_many", "camera.multiple_moves", "prompt")
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

def must_ask(code):
    return any(code == p or (p.endswith(":") and code.startswith(p)) for p in MUST_ASK_PREFIX)

def from_storyboard_all(shots, cast=None):
    if not isinstance(shots, list) or not shots:
        raise DirControlsError("shots 要是非空的分鏡清單")
    out, gaps, seen = [], {}, set()
    for i, sh in enumerate(shots):
        if not isinstance(sh, dict):
            raise DirControlsError("shots[%d] 要是物件" % i)
        sh = dict(sh)
        key = sh.pop("key", None) or sh.pop("shot_key", None) or "seg%d" % (i + 1)
        sh.pop("shot_key", None)
        if not isinstance(key, str) or not KEY_RE.match(key) or key in seen:
            raise DirControlsError("shots[%d].key 要是 1–32 個英數字、底線或連字號，而且不能重複" % i)
        seen.add(key)
        if not re.sub(r"\s+", "", str(sh.get("prompt") or "")):
            one = {"desc": None, "dur": None, "draft_gaps": ["prompt"], "guessed": []}
        else:
            one = from_storyboard(sh, cast)
        one["ask"] = [c for c in one["draft_gaps"] if must_ask(c)]
        one["fill"] = [c for c in one["draft_gaps"] if not must_ask(c)] + list(one["guessed"])
        out.append(dict({"key": key}, **one))
        for code in one["draft_gaps"] + one["guessed"]:
            gaps.setdefault(code, []).append(key)
    return {"shots": out, "gaps": gaps, "must_ask": sorted(c for c in gaps if must_ask(c))}
