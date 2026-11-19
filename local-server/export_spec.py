import os
import re
import sys

try:
    import twist as _twist
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "export_lambda"))
    import twist as _twist

ASPECTS = ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9")
RESOLUTIONS = ("480p", "720p", "1080p")
FPS_ALLOWED = (24, 25, 30)
SUB_MODES = ("burn", "srt", "both", "none")
MAX_VIDEO, MAX_AUDIO, MAX_CUES, MAX_TEXT = 200, 200, 2000, 300
MAX_TOTAL = 30 * 60
DISCLOSE_MAX = 200
ID = re.compile(r"^exp_[a-z0-9]{8,40}$")
JOB = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,79}$")
AUDIO_URL = re.compile(r"^/api/audio/content\?sha=([0-9a-f]{64})$")
ASSET = re.compile(r"^ast_[A-Za-z0-9_-]{1,124}$")

class ExportError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg

def _num(v, name, lo=0.0, hi=float(MAX_TOTAL)):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ExportError(400, "%s 要是數字" % name)
    v = float(v)
    if v != v or v < lo or v > hi:
        raise ExportError(400, "%s 超出範圍" % name)
    return round(v, 3)

def _str(v, name, limit):
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ExportError(400, "%s 要是字串" % name)
    v = v.strip()
    if len(v) > limit:
        raise ExportError(400, "%s 太長（最多 %d 字）" % (name, limit))
    return v

def normalize(body):
    if not isinstance(body, dict):
        raise ExportError(400, "要是 JSON 物件")
    allowed = {"title", "format", "video", "audio", "cues", "subtitles", "disclosure", "titles",
               "captions", "effects", "twist",
               "pipeline"}
    bad = sorted(k for k in body if k not in allowed)
    if bad:
        raise ExportError(400, "匯出不收這些欄位：%s" % "、".join(bad))
    fmt = body.get("format") or {}
    if not isinstance(fmt, dict):
        raise ExportError(400, "format 要是物件")
    out = {"title": _str(body.get("title"), "標題", 80),
           "format": {"aspect": fmt.get("aspect", "16:9"), "resolution": fmt.get("resolution", "1080p"),
                      "fps": fmt.get("fps", 24)}}
    if out["format"]["aspect"] not in ASPECTS:
        raise ExportError(400, "畫面比例只能是 %s" % "／".join(ASPECTS))
    if out["format"]["resolution"] not in RESOLUTIONS:
        raise ExportError(400, "解析度只能是 %s" % "／".join(RESOLUTIONS))
    if out["format"]["fps"] not in FPS_ALLOWED:
        raise ExportError(400, "影格率只能是 %s" % "／".join(map(str, FPS_ALLOWED)))
    fit = fmt.get("fit", "pad")
    if fit not in ("pad", "crop"):
        raise ExportError(400, "畫面填法只能是 pad／crop")
    out["format"]["fit"] = fit

    vids = body.get("video")
    if not isinstance(vids, list) or not vids:
        raise ExportError(400, "V1 是空的：至少要有一段拍好的影片")
    if len(vids) > MAX_VIDEO:
        raise ExportError(400, "V1 最多 %d 段" % MAX_VIDEO)
    out["video"] = []
    for k, v in enumerate(vids):
        name = "V1 第 %d 段" % (k + 1)
        if not isinstance(v, dict):
            raise ExportError(400, "%s 要是物件" % name)
        if isinstance(v.get("job"), str) and JOB.match(v["job"]) and "asset" not in v:
            ref = {"job": v["job"]}
        elif isinstance(v.get("asset"), str) and ASSET.match(v["asset"]) and "job" not in v:
            ref = {"asset": v["asset"]}
        else:
            raise ExportError(400, "%s 沒有拍好的影片（缺上游 id）" % name)
        a, b = _num(v.get("in", 0), name + " 的入點"), _num(v.get("out"), name + " 的出點")
        if b - a < 0.2:
            raise ExportError(400, "%s 太短" % name)
        out["video"].append(dict(ref, **{"in": a, "out": b}))

    auds = body.get("audio") or []
    if not isinstance(auds, list) or len(auds) > MAX_AUDIO:
        raise ExportError(400, "聲音段最多 %d 段" % MAX_AUDIO)
    out["audio"] = []
    for k, v in enumerate(auds):
        name = "聲音第 %d 段" % (k + 1)
        if not isinstance(v, dict):
            raise ExportError(400, "%s 要是物件" % name)
        item = {"lane": v.get("lane") if v.get("lane") in ("A1", "A2") else "A1",
                "at": _num(v.get("at", 0), name + " 的起點"), "in": _num(v.get("in", 0), name + " 的入點"),
                "dur": _num(v.get("dur"), name + " 的長度", 0.05),
                "gain": _num(v.get("gain", 1.0), name + " 的音量", 0.0, 2.0)}
        if v.get("fade") is not None:
            item["fade"] = _num(v.get("fade"), name + " 的淡入淡出", 0.0, 1.0)
        if v.get("loop") is True:
            item["loop"] = True
        src, job = v.get("src"), v.get("job")
        if isinstance(src, str) and src:
            m = AUDIO_URL.match(src)
            if m:
                item["sha"] = m.group(1)
            elif src.startswith("data:audio/") and len(src) < 28 * 1024 * 1024:
                item["data"] = src
            else:
                raise ExportError(400, "%s 的音檔來源不認得（只收本站存的音檔）" % name)
        elif isinstance(job, str) and JOB.match(job):
            item["job"] = job
        elif isinstance(v.get("asset"), str) and ASSET.match(v["asset"]):
            item["asset"] = v["asset"]
        else:
            raise ExportError(400, "%s 沒有音檔來源" % name)
        if isinstance(v.get("model"), str) and MODEL.match(v["model"]):
            item["model"] = v["model"]
        out["audio"].append(item)

    cues = body.get("cues") or []
    if not isinstance(cues, list) or len(cues) > MAX_CUES:
        raise ExportError(400, "字幕最多 %d 句" % MAX_CUES)
    out["cues"] = []
    for k, q in enumerate(cues):
        if not isinstance(q, dict):
            raise ExportError(400, "第 %d 句字幕要是物件" % (k + 1))
        s, e = _num(q.get("start"), "字幕起點"), _num(q.get("end"), "字幕迄點")
        t = _str(q.get("text"), "第 %d 句字幕" % (k + 1), MAX_TEXT)
        if e > s and t:
            out["cues"].append({"start": s, "end": e, "text": t})
    mode = body.get("subtitles", "none")
    if mode not in SUB_MODES:
        raise ExportError(400, "字幕只能是 %s" % "／".join(SUB_MODES))
    out["subtitles"] = mode

    d = body.get("disclosure") or {}
    if not isinstance(d, dict):
        raise ExportError(400, "disclosure 要是物件")
    ti = body.get("titles") or {}
    if not isinstance(ti, dict) or any(k not in ("open", "end") for k in ti):
        raise ExportError(400, "titles 只收 open／end")
    out["titles"] = {}
    for k, v in ti.items():
        if not isinstance(v, dict):
            raise ExportError(400, "字卡要是物件")
        t = _str(v.get("text"), "字卡文字", 160)
        if t:
            out["titles"][k] = {"text": t, "seconds": _num(v.get("seconds", 3), "字卡秒數", 1, 8)}

    out["disclosure"] = {"on": d.get("on") is True,
                         "text": _str(d.get("text"), "揭露文字", DISCLOSE_MAX),
                         "seconds": _num(d.get("seconds", 4), "片尾秒數", 2, 8)}
    if out["disclosure"]["on"] and not out["disclosure"]["text"]:
        raise ExportError(400, "AI 揭露片尾開著，但沒有文字")
    try:
        out.update(_twist.clean_meme(body))
    except _twist.TwistError as e:
        raise ExportError(400, str(e)) from None
    if "pipeline" in body:
        import postblocks
        try:
            out["pipeline"] = postblocks.clean_user(body["pipeline"])
        except postblocks.PipelineError as e:
            raise ExportError(400, str(e)) from None
    return out

def build_spec(uid, eid, req, video_keys, video_models, audio_keys, src_bucket, out_bucket):
    models = []
    for v in req["video"]:
        m = video_models.get(v.get("job"))
        if m and m not in models:
            models.append(m)
    for a in req["audio"]:
        m = a.get("model")
        if m and m not in models:
            models.append(m)
    spec = {"version": 1, "id": eid, "user": str(uid),
            "src_bucket": src_bucket, "out_bucket": out_bucket,
            "format": dict(req["format"]),
            "video": [dict({"key": video_keys[_ref(v)], "in": v["in"], "out": v["out"]},
                           **({"job": v["job"]} if v.get("job") else {}),
                           **({"model": video_models[v["job"]]} if video_models.get(v.get("job")) else {}))
                      for v in req["video"]],
            "audio": [dict({"lane": a["lane"], "key": k, "at": a["at"], "in": a["in"], "dur": a["dur"],
                            "gain": a["gain"], "from": frm}, **({"fade": a["fade"]} if a.get("fade") else {}),
                           **({"loop": True} if a.get("loop") else {}))
                      for a, (k, frm) in zip(req["audio"], audio_keys)],
            "titles": dict(req.get("titles") or {}),
            "subtitles": {"mode": req["subtitles"], "cues": req["cues"]},
            "disclosure": {"on": req["disclosure"]["on"], "text": req["disclosure"]["text"],
                           "seconds": req["disclosure"]["seconds"], "models": models},
            "models": models}
    for k in ("captions", "effects", "twist"):
        if req.get(k):
            spec[k] = req[k]
    if req.get("pipeline"):
        spec["pipeline"] = req["pipeline"]
    return spec

def preview_spec(req, uid="preview"):
    vkeys = {_ref(v): "originals/%s/%064x" % (uid, i + 1) for i, v in enumerate(req["video"])}
    akeys = [("originals/%s/%064x" % (uid, 1000 + i), "preview") for i, _a in enumerate(req["audio"])]
    return build_spec(uid, "exp_preview0000", req, vkeys, {}, akeys, "preview-src", "preview-out")

def _ref(v):
    return v.get("job") or v.get("asset")

def refs(req):
    return list(dict.fromkeys([_ref(v) for v in req["video"]] +
                              [_ref(a) for a in req["audio"] if _ref(a)]))

HEAD_MAX = 8 * 1024 * 1024

def _frame_sync(h, i=0):
    return len(h) >= i + 2 and h[i] == 0xFF and (h[i + 1] & 0xE0) == 0xE0

def id3_end(h):
    if len(h) < 10 or not h.startswith(b"ID3") or any(b & 0x80 for b in h[6:10]):
        return None
    size = (h[6] << 21) | (h[7] << 14) | (h[8] << 7) | h[9]
    return 10 + size + (10 if h[5] & 0x10 else 0)

def media_kind(head):
    h = bytes(head)
    if h.startswith(b"ID3"):
        end = id3_end(h)
        return "audio" if end is not None and _frame_sync(h, end) else None
    h = h[:16]
    if len(h) >= 12 and h[4:8] == b"ftyp":
        return "video"
    if h.startswith(b"\x1a\x45\xdf\xa3"):
        return "video"
    if h.startswith(b"RIFF") and h[8:12] in (b"WAVE",):
        return "audio"
    if h.startswith((b"OggS", b"fLaC")):
        return "audio"
    if _frame_sync(h):
        return "audio"
    return None

class _Head:

    def __init__(self, head, src):
        self.head, self.src = head, src

    def read(self, n=-1):
        if self.head:
            out, self.head = self.head[:n] if n and n > 0 else self.head, self.head[n:] if n and n > 0 else b""
            return out
        return self.src.read(n)
