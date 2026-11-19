
DEFECTS = (
    "unreadable",
    "character_mismatch",
    "color_mismatch",
    "artifacts",
    "low_score",
    "twist_not_found",
    "platform_spec",
    "platform_unknown",
    "blocks_fallback",
    "blocks_shadow_diff",
    "count_mismatch",
    "seam_jump",
)
SCOPES = ("shot", "line", "step")
NOTE_MAX = 120

class ReportError(ValueError):
    pass

def report(block, subject, ok, score=None, defects=(), redo=None, source="", note=""):
    if not isinstance(block, str) or not block:
        raise ReportError("要有 block")
    if score is not None:
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
            raise ReportError("score 要是 0–1")
        score = round(float(score), 3)
    bad = [d for d in defects if d not in DEFECTS]
    if bad:
        raise ReportError("不認得的缺點代碼 %s" % "、".join(bad))
    if redo is not None:
        if not isinstance(redo, dict) or redo.get("scope") not in SCOPES:
            raise ReportError("redo.scope 只能是 %s" % "／".join(SCOPES))
        redo = {"scope": redo["scope"], "target": str(redo.get("target", ""))[:64]}
    return {"block": block, "subject": str(subject)[:64], "ok": bool(ok), "score": score,
            "defects": list(dict.fromkeys(defects)), "redo": redo, "source": str(source)[:32],
            "note": str(note or "")[:NOTE_MAX]}

def from_qc_verdict(v, job_id, shot=None, threshold=7):
    target = {"scope": "shot", "target": shot if shot is not None else job_id}
    if not isinstance(v, dict) or not v.get("ok"):
        return report("qc", job_id, False, None, ["unreadable"], target, "qc")
    defects = []
    if not v.get("subjects_ok"):
        defects.append("character_mismatch")
    if v.get("colors_ok") is False:
        defects.append("color_mismatch")
    if v.get("defects"):
        defects.append("artifacts")
    if v.get("count_ok") is False:
        defects.append("count_mismatch")
    overall = int(v.get("overall") or 0)
    if overall < threshold:
        defects.append("low_score")
    passed = bool(v.get("subjects_ok") and not v.get("defects") and overall >= threshold and v.get("count_ok", True))
    return report("qc", job_id, passed, overall / 10.0, defects, None if passed else target, "qc",
                  "overall %d/10" % overall)

def from_twist(result, subject):
    at = (result or {}).get("at")
    if at is None:
        return report("twist_detect", subject, False, None, ["twist_not_found"],
                      {"scope": "step", "target": "twist_detect"}, "twist")
    return report("twist_detect", subject, True, None, (), None, "twist", "at %.2fs" % float(at))

def from_pitch_platform(row):
    checks = row.get("checks") or []
    defects = []
    if any(c.get("status") == "fail" for c in checks):
        defects.append("platform_spec")
    if any(c.get("status") == "unknown" for c in checks):
        defects.append("platform_unknown")
    ok = row.get("verdict") != "fail"
    return report("pitch", row.get("platform", "?"), ok, None, defects,
                  None if ok else {"scope": "step", "target": "pitch"}, "pitch",
                  "%d 項檢查" % len(checks))

def from_postblocks_event(ev, subject=""):
    event, reason = (ev or {}).get("event"), (ev or {}).get("reason")
    if event == "fallback":
        return report("postblocks", subject, False, None, ["blocks_fallback"], None, "postblocks",
                      "reason %s" % reason)
    if event == "shadow" and reason not in (None, "same"):
        return report("postblocks", subject, False, None, ["blocks_shadow_diff"], None, "postblocks",
                      "reason %s" % reason)
    return None

def merge(reports):
    rs = [r for r in reports if r]
    scores = [r["score"] for r in rs if r["score"] is not None]
    redo, seen = [], set()
    for r in rs:
        if r["redo"] and (r["redo"]["scope"], r["redo"]["target"]) not in seen:
            seen.add((r["redo"]["scope"], r["redo"]["target"]))
            redo.append(r["redo"])
    return {"ok": all(r["ok"] for r in rs), "count": len(rs), "failed": sum(1 for r in rs if not r["ok"]),
            "score": min(scores) if scores else None,
            "defects": sorted({d for r in rs for d in r["defects"]}), "redo": redo}
