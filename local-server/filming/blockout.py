import json
import os
import re
import struct
import subprocess

FPS = 24
DUR_MIN, DUR_MAX = 2, 15
MAX_UPLOAD = 20 * 1024 * 1024
MAX_PNG = 10 * 1024 * 1024
KINDS = ("first_frame", "last_frame", "depth", "ref_video")
SLOT = {"first_frame": "first_frame", "last_frame": "last_frame", "depth": None, "ref_video": "input_references"}
PNG_SIG = b"\x89PNG\r\n\x1a\n"

class BlockoutError(ValueError):
    pass

def export_size(aspect):
    m = re.match(r"^(\d+):(\d+)$", str(aspect or "16:9"))
    a = int(m.group(1)) / int(m.group(2)) if m and int(m.group(2)) else 16 / 9

    def ev(x):
        return max(2, _round(x / 2) * 2)
    if a >= 1:
        w = 1680 if a >= 2 else 1280 if a > 1.5 else 960
        return {"w": w, "h": ev(w / a)}
    h = 1680 if a <= 0.5 else 1280 if a < 0.67 else 960
    return {"w": ev(h * a), "h": h}

def _round(x):
    return int(x + 0.5)

def spec(scene, caps=None):
    if not isinstance(scene, dict) or not isinstance(scene.get("dur"), (int, float)):
        raise BlockoutError("要給 previs 場景（有 dur、aspect）")
    dur = float(scene["dur"])
    size = export_size(scene.get("aspect"))
    frames = max(1, _round(dur * FPS))
    warnings = []
    outputs = [{"kind": "first_frame", "format": "png", "t": 0.0, "max_bytes": MAX_PNG},
               {"kind": "last_frame", "format": "png", "t": round((frames - 1) / FPS, 3), "max_bytes": MAX_PNG},
               {"kind": "depth", "format": "png", "t": 0.0, "max_bytes": MAX_PNG, "encoding": "gray_near_white"},
               {"kind": "ref_video", "format": "mp4", "codec": "h264", "dur": dur, "frames": frames, "fps": FPS,
                "max_bytes": MAX_UPLOAD}]
    if not DUR_MIN <= dur <= DUR_MAX:
        warnings.append("ref_video_dur")
    caps = caps if isinstance(caps, dict) else {}
    bind = {}
    for kind in KINDS:
        slot = SLOT[kind]
        if slot is None:
            bind[kind] = {"slot": None, "status": "no_slot"}
            continue
        cell = caps.get(slot) or {}
        st = cell.get("status", "untested")
        if kind == "ref_video" and "ref_video_dur" in warnings:
            st = "fail"
        b = {"slot": slot, "status": st}
        if cell.get("field"):
            b["field"] = cell["field"]
        if cell.get("drift"):
            b["drift"] = cell["drift"]
        bind[kind] = b
        if st == "untested":
            warnings.append("%s_untested" % kind)
    return {"size": size, "fps": FPS, "dur": dur, "outputs": outputs, "bind": bind, "warnings": warnings}

def _png_size(path):
    with open(path, "rb") as fh:
        head = fh.read(24)
    if len(head) < 24 or head[:8] != PNG_SIG or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])

def _probe(ffprobe, path):
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=codec_name,width,height,nb_frames:format=duration", "-of", "json", path],
                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        return None
    try:
        j = json.loads(r.stdout or "{}")
        s = (j.get("streams") or [{}])[0]
        if not s.get("codec_name") or not s.get("width"):
            return None
        return {"codec": s.get("codec_name"), "w": s.get("width"), "h": s.get("height"),
                "dur": float((j.get("format") or {}).get("duration") or 0)}
    except (ValueError, TypeError):
        return None

def check(sp, files, ffprobe=None):
    probs = []
    w, h = sp["size"]["w"], sp["size"]["h"]
    for o in sp["outputs"]:
        k = o["kind"]
        p = (files or {}).get(k)
        if not p or not os.path.isfile(p):
            probs.append({"kind": k, "code": "missing", "detail": ""})
            continue
        n = os.path.getsize(p)
        if n > o["max_bytes"]:
            probs.append({"kind": k, "code": "too_big", "detail": "%d > %d bytes" % (n, o["max_bytes"])})
        if o["format"] == "png":
            got = _png_size(p)
            if got is None:
                probs.append({"kind": k, "code": "not_png", "detail": ""})
            elif got != (w, h):
                probs.append({"kind": k, "code": "size", "detail": "%dx%d，要 %dx%d" % (got[0], got[1], w, h)})
        elif ffprobe:
            v = _probe(ffprobe, p)
            if v is None:
                probs.append({"kind": k, "code": "unreadable", "detail": ""})
                continue
            if v["codec"] != "h264":
                probs.append({"kind": k, "code": "codec", "detail": str(v["codec"])})
            if (v["w"], v["h"]) != (w, h):
                probs.append({"kind": k, "code": "size", "detail": "%sx%s，要 %dx%d" % (v["w"], v["h"], w, h)})
            if abs(v["dur"] - o["dur"]) > 1.5 / FPS:
                probs.append({"kind": k, "code": "dur", "detail": "%.3f 秒，要 %.3f" % (v["dur"], o["dur"])})
    return {"ok": not probs, "problems": probs}
