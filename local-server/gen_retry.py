import os
import re
import sys

import approvals
import cast_refs
import studio_store
import takes

MODES = ("off", "shadow", "on")
MAX_RETRIES = 2
MAX_QC_RETRIES = 1
QC_THRESHOLD = 7
GEN_REASON = "generation_failed"
QC_PREFIX = "qc:"
QC_ORDER = ("count_mismatch", "character_mismatch", "artifacts", "low_score", "color_mismatch")

def _mode(env):
    v = os.environ.get(env, "").strip().lower()
    return v if v in MODES else "off"

def mode():
    return _mode("GEN_RETRY")

def qc_mode():
    return _mode("GEN_RETRY_QC")

def terminal(st):
    s = str((st or {}).get("status") or "").lower() if isinstance(st, dict) else ""
    return s in takes.UPSTREAM_READY or s in takes.UPSTREAM_FAILED

def own_key_refunded(st):
    v = (st or {}).get("price_charged") if isinstance(st, dict) else None
    if v is None or isinstance(v, bool):
        return False
    try:
        return float(v) == 0.0
    except (TypeError, ValueError):
        return False

def log(code, extra=""):
    sys.stderr.write("[gen_retry] %s%s\n" % (code, (" " + extra) if extra else ""))

def plan(conn, tenant, job_id, st, charge_status):
    err = (st or {}).get("error") if isinstance(st, dict) else None
    got = takes.sync_job(conn, tenant, job_id, (st or {}).get("status"),
                         error=err if isinstance(err, str) else (str(err)[:200] if err else None))
    if not got:
        return None
    take, changed = got
    if not changed or take["status"] != "failed":
        return None
    shot = takes.list_takes(conn, tenant, take.get("project_id"), take["shot_key"])
    p = takes.retry_plan(take, charge_status, _budget(shot, lambda r: r == GEN_REASON), MAX_RETRIES)
    if p.get("retake"):
        p = _shared_stop(shot) or p
    if not p.get("retake"):
        return {"stop": p.get("stop") or "no_retake", "take": take["id"]}
    return _with_payload(conn, tenant, take, GEN_REASON)

def _budget(shot, mine):
    return [t for t in shot if not t.get("parent_take") or mine(str(t.get("reason") or ""))]

def _shared_stop(shot):
    p = takes.retake_plan(shot, "auto", 1 << 30) if shot else None
    return p if p and p.get("stop") in ("already_picked", "already_ok") else None

def _with_payload(conn, tenant, take, reason):
    card = approvals.get(conn, tenant, take["approval_id"]) if take.get("approval_id") else None
    payload = (card or {}).get("payload")
    if not isinstance(payload, dict) or not payload:
        return {"stop": "no_payload", "take": take["id"]}
    notes = []
    if cast_refs.mode() != "legacy":
        try:
            raw = studio_store.kv_get(conn, tenant, cast_refs.STORE_KEY).get("value")
            payload, notes = cast_refs.refresh_notes(payload, raw)
        except Exception as e:
            log("notes_skipped", type(e).__name__)
    return {"retake": True, "take": take, "payload": payload, "payer": card.get("payer"), "notes": notes, "reason": reason}

def _report(subject, ok, score, defects, redo, note=""):
    return {"block": "qc", "subject": str(subject)[:64], "ok": bool(ok),
            "score": None if score is None else round(float(score), 3), "defects": list(dict.fromkeys(defects)),
            "redo": None if redo is None else {"scope": redo["scope"], "target": str(redo.get("target", ""))[:64]},
            "source": "qc", "note": str(note or "")[:120]}

def qc_report(v, job_id, shot=None, threshold=QC_THRESHOLD):
    target = {"scope": "shot", "target": shot if shot is not None else job_id}
    if not isinstance(v, dict) or not v.get("ok"):
        return _report(job_id, False, None, ["unreadable"], target)
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
    ok = bool(v.get("subjects_ok") and not v.get("defects") and overall >= threshold and v.get("count_ok", True))
    return _report(job_id, ok, overall / 10.0, defects, None if ok else target, "overall %d/10" % overall)

def qc_reason(defects):
    ds = [str(d) for d in (defects or []) if isinstance(d, str)]
    pick = next((d for d in QC_ORDER if d in ds), ds[0] if ds else "")
    code = re.sub(r"[^a-z_]+", "_", pick.strip().lower()).strip("_")
    r = QC_PREFIX + code
    return r if code and takes.REASON.match(r) else QC_PREFIX + "other"

def qc_plan(conn, tenant, job_id, verdict):
    take = takes.by_job(conn, tenant, job_id)
    if not take:
        return None
    rep = qc_report(verdict, job_id)
    keep = [r for r in (take.get("qc") or []) if isinstance(r, dict) and r.get("block") != "qc"]
    take = takes.record_qc(conn, tenant, take["id"], (keep + [rep])[-32:])
    if rep["ok"]:
        return None
    if "unreadable" in rep["defects"]:
        return {"stop": "qc_unreadable", "take": take["id"]}
    reason = qc_reason(rep["defects"])
    shot = takes.list_takes(conn, tenant, take.get("project_id"), take["shot_key"])
    p = takes.retake_plan(_budget(shot, lambda r: r.startswith(QC_PREFIX)), reason, MAX_QC_RETRIES)
    if p.get("retake"):
        p = _shared_stop(shot) or p
    if not p.get("retake"):
        return {"stop": p.get("stop") or "no_retake", "take": take["id"]}
    return _with_payload(conn, tenant, take, reason)

AUTO_REASON = "auto_take"

def auto_mode():
    return _mode("STUDIO_AUTO_TAKES")

def _take_of_card(conn, tenant, approval_id):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM shot_takes WHERE tenant_id = %s::uuid AND approval_id = %s LIMIT 1",
                    (str(tenant), str(approval_id)))
        row = cur.fetchone()
    return row[0] if row else None

def auto_take(conn, tenant, job_id, approval_id=None, charge_id=None, apply=True):
    if not job_id:
        return {"skip": "no_shot_key"}
    if takes.by_job(conn, tenant, job_id):
        return {"skip": "has_take"}
    if approval_id and _take_of_card(conn, tenant, approval_id):
        return {"skip": "has_take"}
    key = str(job_id)
    if not takes.SHOT_KEY.match(key):
        return {"skip": "bad_shot_key"}
    if not apply:
        return {"would": key}
    t = takes.create(conn, tenant, project_id=None, shot_key=key, job_id=key, reason=AUTO_REASON,
                     approval_id=approval_id, charge_id=charge_id, status="generating")
    return {"take": t["id"], "shot_key": key}

def record(conn, tenant, take, approval_id, job_id, reason=GEN_REASON):
    return takes.create(conn, tenant, project_id=take.get("project_id"), shot_key=take["shot_key"], job_id=job_id,
                        parent_take=take["id"], reason=reason, approval_id=approval_id,
                        status="generating" if job_id else "queued")

def public(result):
    keep = ("state", "stop", "take", "reason", "approval_id", "approval_status", "job_id", "approve_url")
    return {k: result[k] for k in keep if result.get(k) is not None}
