from . import blockout, shots

VERSION = 1
MAX_SEGMENTS, SEG_MIN, SEG_MAX = 12, 2, 15
PROMPT_MAX = 2000
SEAM_THRESHOLD = 0.5
EPS = 1e-6

class PlanError(ValueError):
    pass

def _ok(cell):
    return (cell or {}).get("status") == "ok"

def _prompt(v, where):
    if v is None:
        return ""
    if not isinstance(v, str) or len(v) > PROMPT_MAX:
        raise PlanError("%s 要是最多 %d 字的文字" % (where, PROMPT_MAX))
    return v.strip()

def _from_script(desc):
    segs = desc.get("segments")
    if not isinstance(segs, list) or not 0 < len(segs) <= MAX_SEGMENTS:
        raise PlanError("segments 要有 1–%d 段" % MAX_SEGMENTS)
    out, seen = [], set()
    for i, s in enumerate(segs):
        w = "segments[%d]" % i
        if not isinstance(s, dict) or set(s) - {"prompt", "seconds", "shot_key"}:
            raise PlanError("%s 只能有 prompt、seconds、shot_key" % w)
        sec = s.get("seconds")
        if isinstance(sec, bool) or not isinstance(sec, (int, float)) or not SEG_MIN <= sec <= SEG_MAX:
            raise PlanError("%s.seconds 要是 %d–%d" % (w, SEG_MIN, SEG_MAX))
        key = s.get("shot_key") or "seg%d" % (i + 1)
        if not isinstance(key, str) or not shots.KEY_RE.match(key) or key in seen:
            raise PlanError("%s.shot_key 要是 1–32 個英數字、底線或連字號，而且不能重複" % w)
        seen.add(key)
        p = _prompt(s.get("prompt"), w + ".prompt")
        if not p:
            raise PlanError("%s.prompt 不能是空的" % w)
        out.append({"key": key, "seconds": float(sec), "prompt": p, "scene": None, "joined": i > 0})
    return out

def _from_shots(desc):
    try:
        sh = shots.compile(desc.get("shots"))
    except shots.ShotsError as e:
        raise PlanError("shots.%s" % e) from None
    prompts = desc.get("prompts") or {}
    if not isinstance(prompts, dict) or set(prompts) - {s["key"] for s in sh["shots"]}:
        raise PlanError("prompts 要是 {鏡號: 提示詞}，鏡號要在 shots 裡")
    out = []
    for i, s in enumerate(sh["shots"]):
        joined = i > 0 and abs(s["from"] - sh["shots"][i - 1]["to"]) < EPS
        out.append({"key": s["key"], "seconds": round(s["to"] - s["from"], 3), "from": s["from"], "to": s["to"],
                    "prompt": _prompt(prompts.get(s["key"]), "prompts.%s" % s["key"]), "scene": s["scene"],
                    "joined": joined})
    return out

def plan(desc, caps=None, *, has_cast_refs=False, price_per_second=None, max_retakes=1, target_seconds=None):
    if not isinstance(desc, dict) or desc.get("version") != VERSION:
        raise PlanError("要給 version %d 的腳本（segments）或鏡頭表（shots）" % VERSION)
    if ("segments" in desc) == ("shots" in desc):
        raise PlanError("segments（腳本）與 shots（鏡頭表）要給其中一種")
    extra = set(desc) - {"version", "segments", "shots", "prompts"}
    if extra:
        raise PlanError("不認得的欄位 %s" % "、".join(sorted(extra)))
    if isinstance(max_retakes, bool) or not isinstance(max_retakes, int) or not 0 <= max_retakes <= 5:
        raise PlanError("max_retakes 要是 0–5")
    if price_per_second is not None and (isinstance(price_per_second, bool) or
                                         not isinstance(price_per_second, (int, float)) or price_per_second < 0):
        raise PlanError("price_per_second 要是 ≥ 0 的數字")
    segs = _from_shots(desc) if "shots" in desc else _from_script(desc)
    caps = caps if isinstance(caps, dict) else {}
    ff_ok, lf_ok = _ok(caps.get("first_frame")), _ok(caps.get("last_frame"))
    warnings, out, seams = [], [], []
    uploads = 0

    def warn(code):
        if code not in warnings:
            warnings.append(code)
    for i, s in enumerate(segs):
        seg = {"key": s["key"], "seconds": s["seconds"], "prompt": s["prompt"]}
        if "from" in s:
            seg["from"], seg["to"] = s["from"], s["to"]
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        if s["joined"] and ff_ok:
            first = {"source": "prev_last", "from": segs[i - 1]["key"]}
        elif s["scene"] is not None and ff_ok:
            first = {"source": "blockout", "from": None}
            uploads += 1
        elif has_cast_refs:
            first = {"source": "cast_refs", "from": None}
            if s["joined"] or s["scene"] is not None:
                warn("first_frame_unavailable")
        else:
            first = {"source": "none", "from": None}
            warn("no_continuity")
        seg["first_frame"] = first
        hand = bool(nxt and nxt["joined"] and ff_ok)
        seg["last_frame"] = {"hand_off_to": nxt["key"] if hand else None,
                             "pin": "blockout" if (s["scene"] is not None and lf_ok) else None}
        framed = first["source"] in ("prev_last", "blockout") or bool(seg["last_frame"]["pin"])
        seg["refs"] = ["cast_refs"] if has_cast_refs and not framed else []
        if has_cast_refs and framed:
            warn("refs_dropped_for_first_frame")
        if hand:
            uploads += 1
        if seg["last_frame"]["pin"]:
            uploads += 1
        if s["scene"] is not None:
            sp = blockout.spec(s["scene"], caps)
            seg["blockout"] = {"size": sp["size"], "bind": sp["bind"], "warnings": sp["warnings"]}
            if not lf_ok:
                warn("last_frame_untested")
        if i > 0 and s["joined"]:
            seams.append({"seam": "seam%d" % i, "after": segs[i - 1]["key"], "before": s["key"], "check": "seam_check",
                          "threshold": SEAM_THRESHOLD, "transition": "drop_first" if first["source"] == "prev_last" else None,
                          "redo": {"scope": "shot", "target": s["key"]}})
        out.append(seg)
    if ff_ok and any(x["first_frame"]["source"] == "prev_last" for x in out) and \
            (caps.get("first_frame") or {}).get("drift") == "yes":
        warn("first_frame_drift")
    total = round(sum(x["seconds"] for x in out), 3)
    if target_seconds is not None and abs(total - target_seconds) > 5:
        warn("length_off_target")
    n = len(out)
    totals = {"seconds": total, "segments": n, "worst_segments": n * (1 + max_retakes), "uploads": uploads,
              "seams": len(seams), "cost": None, "worst_cost": None}
    if price_per_second is None:
        warn("no_price")
    else:
        totals["cost"] = round(total * price_per_second, 2)
        totals["worst_cost"] = round(total * price_per_second * (1 + max_retakes), 2)
    chain = [{"prompt": x["prompt"], "seconds": x["seconds"], "shot_key": x["key"]} for x in out]
    return {"segments": out, "seams": seams, "totals": totals, "warnings": warnings, "chain_segments": chain}
