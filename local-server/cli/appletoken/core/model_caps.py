
DEFAULT_FIELD = "frame_images_obj"

CAPS = {
    "gputw/minimax-h3": {
        "first_frame": {"status": "ok", "field": "frame_images_str", "drift": "yes",
                        "evidence": "job_2e34c9802390ea1a490a；60 秒四段接力的接縫 SSIM 0.976／0.974／0.977"
                                    "（實測）",
                        "date": "2026-11-20",
                        "success": {"ok": 3, "tries": 5},
                        "notes": ["兩個角色身體接觸的動作（抱、扭打）短暫融在一起約 0.5 秒",
                                  "接片：後一段去掉第 1 幀再 concat，不做 xfade，接縫肉眼看不出來"],
                        "also": {"image_url": "fail：upstream generation_failed 1/1（已全額退款）",
                                 "frame_images_obj": "untested"}},
        "last_frame": {"status": "untested"},
        "input_references": {"status": "untested"},
        "resolutions": ("720p",),
    },
    "sailflow/minimax-h3": {
        "first_frame": {"status": "ok", "field": "image_url", "drift": "yes",
                        "evidence": "接縫 SSIM 0.979（實測）", "date": "2026-11-20",
                        "success": {"ok": 1, "tries": 1}},
        "last_frame": {"status": "untested"},
        "input_references": {"status": "untested"},
    },
    "minimax/minimax-h3": {"first_frame": {"status": "untested", "note": "720p 回 400，只收 768p／2k／1440p"},
                           "resolutions": ("768p", "2k", "1440p")},
    "gmi/minimax-h3": {"first_frame": {"status": "untested", "note": "只收 768p／1440p"},
                       "resolutions": ("768p", "1440p")},
    "minimax/minimax-h3-lite": {"first_frame": {"status": "untested"}, "resolutions": ("480p", "768p")},
}

KINDS = ("first_frame", "last_frame", "input_references")

class CapsError(ValueError):
    pass

def caps(model):
    return CAPS.get(str(model or "").strip(), {})

def status(model, kind):
    return (caps(model).get(kind) or {}).get("status", "untested")

def frames_payload(model, first=None, last=None):
    first = first.strip() if isinstance(first, str) and first.strip() else None
    last = last.strip() if isinstance(last, str) and last.strip() else None
    if not (first or last):
        return {}, []
    c = caps(model)
    ff = c.get("first_frame") or {}
    field = ff.get("field") if ff.get("status") == "ok" else None
    notes = []
    if first and ff.get("status") != "ok":
        notes.append("first_frame_untested")
    if last and status(model, "last_frame") != "ok":
        notes.append("last_frame_untested")
    if field == "frame_images_str":
        if last:
            raise CapsError("%s 的尾幀還沒實測過（首幀要用 frame_images 字串陣列，尾幀的寫法不知道）：先只給首幀" % model)
        return {"frame_images": [first]}, notes
    if field == "image_url":
        if last:
            raise CapsError("%s 的尾幀還沒實測過：先只給首幀" % model)
        return {"image_url": first}, notes
    frames = [{"frame_type": t, "image_url": u} for t, u in (("first_frame", first), ("last_frame", last)) if u]
    return {"frame_images": frames}, notes

def table():
    out = []
    for m, c in sorted(CAPS.items()):
        row = {"model": m}
        for k in KINDS:
            row[k] = dict(c.get(k) or {"status": "untested"})
        if c.get("resolutions"):
            row["resolutions"] = list(c["resolutions"])
        out.append(row)
    return out
