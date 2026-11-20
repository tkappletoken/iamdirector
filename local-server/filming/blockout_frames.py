import os
import sys

from . import blender, blockout, lock_qc

MODES = ("legacy", "shadow", "on")
LOCK_MODES = ("measure", "gate")

def mode(env=None):
    env = os.environ if env is None else env
    v = str(env.get("STUDIO_BLOCKOUT_FRAMES") or "").strip().lower()
    return v if v in MODES else "legacy"

def lock_threshold(env=None):
    env = os.environ if env is None else env
    if str(env.get("STUDIO_LOCK_QC") or "").strip().lower() != "gate":
        return None
    try:
        v = float(env.get("STUDIO_LOCK_QC_MIN"))
    except (TypeError, ValueError):
        return None
    return v if 0 <= v <= 1 else None

def _fallback(out, code):
    out["fallback"] = code
    print("[blockout] fallback=%s" % code, file=sys.stderr)
    return out

def prepare(scene, workdir, env=None, render=None, caps=None, ffprobe=None):
    m = mode(env)
    out = {"mode": m, "first_frame": None, "upload": None, "check": None, "fallback": None}
    if m == "legacy":
        return out
    render = render or blender.render
    try:
        r = render(scene, workdir)
    except Exception as e:
        out["error"] = str(e)[:200]
        return _fallback(out, "render")
    sp = blockout.spec(scene, caps or {})
    chk = blockout.check(sp, r.get("files") or {}, ffprobe)
    out["check"] = chk
    if not chk["ok"]:
        return _fallback(out, "check:%s" % chk["problems"][0]["code"])
    out["first_frame"] = r["files"]["first_frame"]
    if m == "on":
        out["upload"] = out["first_frame"]
    return out

def preparer(workdir, env=None, render=None, caps=None, ffprobe=None):
    env = os.environ if env is None else env
    m = mode(env)
    if m == "legacy":
        return None

    def prepare_shot(shot_key, scene):
        r = prepare(scene, os.path.join(workdir, shot_key), env, render, caps, ffprobe)
        if m == "on":
            r["mode"] = "on→shadow"
        return r
    return prepare_shot

def measure(shot_key, prepared, generated_video, env=None, ffmpeg="ffmpeg", aspect_size=None, score=None):
    if not prepared or not prepared.get("first_frame"):
        return None
    return lock_qc.measure(shot_key, prepared["first_frame"], generated_video, ffmpeg, lock_threshold(env), aspect_size,
                           score)
