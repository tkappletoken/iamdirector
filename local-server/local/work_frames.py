import os
import re

ENV = "STUDIO_WORK_FRAMES"
URL_MAX = 2000
REFS_MAX = 9
REF_TYPES = ("image", "video", "audio")
URL_OK = re.compile(r"^(https?://|asset://)\S+$", re.I)
FRAME_KEYS = ("frame_images", "image_url")

class FramesError(ValueError):
    pass

def on(env=None):
    return str((env if env is not None else os.environ).get(ENV, "")).strip().lower() in ("1", "on", "true")

def key(pid):
    return "wf_" + str(pid).replace("-", "")[:29]

def _url(v, where):
    if not isinstance(v, str) or not v.strip() or len(v) > URL_MAX or not URL_OK.match(v.strip()):
        raise FramesError("%s 要是圖片網址或 asset://（%d 字內；不收 data URI，先用 asset_upload）" % (where, URL_MAX))
    return v.strip()

def one(s, where):
    if not isinstance(s, dict):
        return None
    out = {}
    for k in ("first_frame", "last_frame"):
        if s.get(k) not in (None, ""):
            out[k] = _url(s[k], "%s的 %s" % (where, k))
    refs = s.get("input_references")
    if refs not in (None, []):
        if out:
            raise FramesError("%s：首尾幀（first_frame／last_frame）跟參考圖（input_references）只能選一種" % where)
        if not isinstance(refs, list) or len(refs) > REFS_MAX:
            raise FramesError("%s的 input_references 要是最多 %d 個的陣列" % (where, REFS_MAX))
        clean = []
        for i, r in enumerate(refs, 1):
            w = "%s的第 %d 個參考" % (where, i)
            if not isinstance(r, dict) or r.get("type") not in REF_TYPES or set(r) - {"type", "url", "role"}:
                raise FramesError("%s 要是 {type: image／video／audio, url, role?}" % w)
            x = {"type": r["type"], "url": _url(r.get("url"), w)}
            if r.get("role") is not None:
                if not isinstance(r["role"], str) or not 0 < len(r["role"]) <= 40:
                    raise FramesError("%s的 role 要是 40 字以內的字串" % w)
                x["role"] = r["role"]
            clean.append(x)
        out["input_references"] = clean
    return out or None

def clean(shots):
    if not isinstance(shots, list):
        return []
    return [one(s, "第 %d 鏡" % i) for i, s in enumerate(shots, 1)]

def by_sid(board, per_shot):
    return {b["sid"]: f for b, f in zip(board or [], per_shot) if f and isinstance(b, dict) and b.get("sid")}

def for_run(shots, stored):
    if not isinstance(stored, dict):
        return {}
    return {"seg%d" % i: stored[s["sid"]] for i, s in enumerate(shots, 1)
            if isinstance(s, dict) and s.get("sid") in stored}
