import json
import re
import secrets

ID = re.compile(r"^tk_[A-Za-z0-9]{16,32}$")
CHAIN_ID = re.compile(r"^chr_[A-Za-z0-9]{16,32}$")
SHOT_KEY = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
REASON = re.compile(r"^[a-z_:+]{1,64}$")
STATUSES = ("queued", "generating", "ready", "failed", "refunded")
MOVES = {"queued": ("generating", "ready", "failed"), "generating": ("ready", "failed"), "failed": ("refunded",),
         "ready": (), "refunded": ()}
PICKERS = ("human", "agent", "auto")
CHAIN_STATUSES = ("planning", "running", "done", "failed", "stopped")
CHAIN_MOVES = {"planning": ("running", "stopped", "failed"), "running": ("done", "failed", "stopped"),
               "stopped": ("running",), "done": (), "failed": ()}
MAX_ATTEMPT = 20
MAX_SEGMENTS = 12
NOT_READY = ("take（每鏡候選與定稿）尚未啟用：資料庫還沒套用 036_shot_takes。這段期間前端照舊用自己的版本清單，"
             "Agent 的 take 工具回這個訊息；其他功能不受影響。")
REFUNDED = ("refunded", "released", "cancelled")

_COLS = ("id", "tenant_id", "project_id", "shot_key", "job_id", "parent_take", "reason", "attempt", "charge_id",
         "approval_id", "status", "qc", "qc_ok", "picked", "picked_by", "picked_at", "error", "created_at", "updated_at")
SEL = ("SELECT id, tenant_id, project_id, shot_key, job_id, parent_take, reason, attempt, charge_id, approval_id, status,"
       " qc, qc_ok, picked, picked_by, picked_at, error, created_at, updated_at FROM shot_takes")
SQL_GET = SEL + " WHERE id = %s AND tenant_id = %s::uuid"
SQL_BY_JOB = SEL + " WHERE job_id = %s AND tenant_id = %s::uuid"
SQL_LIST_SHOT = SEL + (" WHERE tenant_id = %s::uuid AND project_id = %s::uuid AND shot_key = %s"
                       " ORDER BY created_at, attempt LIMIT %s")
SQL_LIST_SHOT_NOPROJ = SEL + (" WHERE tenant_id = %s::uuid AND project_id IS NULL AND shot_key = %s"
                              " ORDER BY created_at, attempt LIMIT %s")
SQL_LIST_PROJ = SEL + " WHERE tenant_id = %s::uuid AND project_id = %s::uuid ORDER BY created_at, attempt LIMIT %s"
SQL_LIST_ALL = SEL + " WHERE tenant_id = %s::uuid ORDER BY created_at, attempt LIMIT %s"
SQL_UNPICK = ("UPDATE shot_takes SET picked = false, picked_by = NULL, picked_at = NULL, updated_at = now()"
              " WHERE tenant_id = %s::uuid AND shot_key = %s AND picked AND id <> %s AND project_id = %s::uuid")
SQL_UNPICK_NOPROJ = ("UPDATE shot_takes SET picked = false, picked_by = NULL, picked_at = NULL, updated_at = now()"
                     " WHERE tenant_id = %s::uuid AND shot_key = %s AND picked AND id <> %s AND project_id IS NULL")
_CCOLS = ("id", "tenant_id", "project_id", "status", "segments", "max_retakes", "stop_reason", "export_id",
          "created_at", "updated_at")
CSEL = ("SELECT id, tenant_id, project_id, status, segments, max_retakes, stop_reason, export_id, created_at, updated_at"
        " FROM chain_runs")
SQL_CHAIN_GET = CSEL + " WHERE id = %s AND tenant_id = %s::uuid"

class TakeError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message

def new_id():
    return "tk_" + secrets.token_hex(12)

def new_chain_id():
    return "chr_" + secrets.token_hex(12)

def _json(v, empty):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return empty
    return empty if v is None else v

def _row(row):
    if not row:
        return None
    d = dict(zip(_COLS, row))
    d["qc"] = _json(d.get("qc"), [])
    for k in ("picked",):
        d[k] = bool(d.get(k))
    if d.get("qc_ok") is not None:
        d["qc_ok"] = bool(d["qc_ok"])
    for k in ("tenant_id", "project_id", "charge_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    return d

def public(t):
    if not t:
        return None
    out = {k: t[k] for k in _COLS if k not in ("tenant_id", "error")}
    out["fail_reason"] = t.get("error")
    for k in ("created_at", "updated_at", "picked_at"):
        if out.get(k) is not None and not isinstance(out[k], str):
            out[k] = out[k].isoformat()
    return out

def _check_key(shot_key):
    if not isinstance(shot_key, str) or not SHOT_KEY.match(shot_key):
        raise TakeError(400, "shot_key 要是 1–64 個英數、_、-（分鏡那一鏡的 sid）")

def get(conn, tenant, tid):
    if not ID.match(str(tid or "")):
        return None
    with conn.cursor() as cur:
        cur.execute(SQL_GET, (str(tid), str(tenant)))
        return _row(cur.fetchone())

def by_job(conn, tenant, job_id):
    with conn.cursor() as cur:
        cur.execute(SQL_BY_JOB, (str(job_id), str(tenant)))
        return _row(cur.fetchone())

def list_takes(conn, tenant, project_id=None, shot_key=None, limit=200):
    if shot_key:
        _check_key(shot_key)
    with conn.cursor() as cur:
        if shot_key and project_id:
            cur.execute(SQL_LIST_SHOT, (str(tenant), str(project_id), shot_key, int(limit)))
        elif shot_key:
            cur.execute(SQL_LIST_SHOT_NOPROJ, (str(tenant), shot_key, int(limit)))
        elif project_id:
            cur.execute(SQL_LIST_PROJ, (str(tenant), str(project_id), int(limit)))
        else:
            cur.execute(SQL_LIST_ALL, (str(tenant), int(limit)))
        return [_row(r) for r in cur.fetchall()]

def create(conn, tenant, *, project_id, shot_key, job_id=None, parent_take=None, reason=None, charge_id=None,
           approval_id=None, status="queued"):
    _check_key(shot_key)
    if status not in ("queued", "generating", "ready"):
        raise TakeError(400, "新的 take 只能從 queued／generating／ready 開始")
    if reason is not None and not REASON.match(str(reason)):
        raise TakeError(400, "reason 要是小寫英文代碼（例如 qc:artifacts、seam_jump、generation_failed、manual）")
    if parent_take is not None:
        par = get(conn, tenant, parent_take)
        if not par or par["shot_key"] != shot_key:
            raise TakeError(404, "parent_take 不存在或不是同一鏡")
    if job_id:
        old = by_job(conn, tenant, job_id)
        if old:
            return old
    have = list_takes(conn, tenant, project_id, shot_key)
    if len(have) >= MAX_ATTEMPT:
        raise TakeError(409, "這一鏡已經有 %d 支候選，到上限了" % MAX_ATTEMPT)
    tid = new_id()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO shot_takes (id, tenant_id, project_id, shot_key, job_id, parent_take, reason, attempt,"
            " charge_id, approval_id, status) VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::uuid, %s, %s)",
            (tid, str(tenant), str(project_id) if project_id else None, shot_key, job_id, parent_take, reason,
             len(have) + 1, str(charge_id) if charge_id else None, approval_id, status))
    return get(conn, tenant, tid)

def move(conn, tenant, tid, to, error=None, job_id=None):
    t = get(conn, tenant, tid)
    if not t:
        raise TakeError(404, "沒有這支 take")
    if to not in MOVES.get(t["status"], ()):
        raise TakeError(409, "take 現在是 %s，不能改成 %s" % (t["status"], to))
    with conn.cursor() as cur:
        cur.execute("UPDATE shot_takes SET status = %s, error = %s, job_id = COALESCE(%s, job_id), updated_at = now()"
                    " WHERE id = %s AND tenant_id = %s::uuid AND status = %s RETURNING id",
                    (to, (str(error)[:500] if error else None), job_id, tid, str(tenant), t["status"]))
        if cur.fetchone() is None:
            raise TakeError(409, "take 的狀態剛被改過，請重新讀一次")
    return get(conn, tenant, tid)

UPSTREAM_READY = ("succeeded", "completed", "done", "success")
UPSTREAM_FAILED = ("failed", "error", "cancelled", "canceled", "generation_failed")

def sync_job(conn, tenant, job_id, upstream_state, error=None):
    t = by_job(conn, tenant, job_id) if job_id else None
    if not t:
        return None
    st = str(upstream_state or "").lower()
    to = "ready" if st in UPSTREAM_READY else "failed" if st in UPSTREAM_FAILED else None
    if to is None or t["status"] == to or to not in MOVES.get(t["status"], ()):
        return t, False
    return move(conn, tenant, t["id"], to, error=error), True

def record_qc(conn, tenant, tid, reports):
    if not isinstance(reports, list) or len(reports) > 32 or not all(isinstance(r, dict) and "ok" in r for r in reports):
        raise TakeError(400, "qc 要是最多 32 份報告的陣列，每份都要有 ok")
    t = get(conn, tenant, tid)
    if not t:
        raise TakeError(404, "沒有這支 take")
    clean = [{k: r.get(k) for k in ("block", "subject", "ok", "score", "defects", "redo", "source", "note") if k in r}
             for r in reports]
    blob = json.dumps(clean, ensure_ascii=False)
    if len(blob) > 32 * 1024:
        raise TakeError(400, "qc 報告太大（上限 32 KB）")
    with conn.cursor() as cur:
        cur.execute("UPDATE shot_takes SET qc = %s::jsonb, qc_ok = %s, updated_at = now()"
                    " WHERE id = %s AND tenant_id = %s::uuid", (blob, all(bool(r["ok"]) for r in clean), tid, str(tenant)))
    return get(conn, tenant, tid)

def pick(conn, tenant, tid, by):
    if by not in PICKERS:
        raise TakeError(400, "picked_by 只能是 %s" % "／".join(PICKERS))
    t = get(conn, tenant, tid)
    if not t:
        raise TakeError(404, "沒有這支 take")
    if t["status"] != "ready":
        raise TakeError(409, "這支還沒生成完成（%s），不能定稿" % t["status"])
    with conn.cursor() as cur:
        if t["project_id"]:
            cur.execute(SQL_UNPICK, (str(tenant), t["shot_key"], tid, t["project_id"]))
        else:
            cur.execute(SQL_UNPICK_NOPROJ, (str(tenant), t["shot_key"], tid))
        cur.execute("UPDATE shot_takes SET picked = true, picked_by = %s, picked_at = now(), updated_at = now()"
                    " WHERE id = %s AND tenant_id = %s::uuid", (by, tid, str(tenant)))
    return get(conn, tenant, tid)

def best(takes):
    ready = [t for t in takes if t["status"] == "ready"]
    if not ready:
        return None

    def score(t):
        s = [r.get("score") for r in t.get("qc") or [] if r.get("score") is not None]
        return (t.get("qc_ok") is True, min(s) if s else 0.0, -t.get("attempt", 0))
    return max(ready, key=score)

def retake_plan(takes, reason, max_retakes=1):
    if not REASON.match(str(reason or "")):
        raise TakeError(400, "reason 要是小寫英文代碼")
    if not takes:
        return {"retake": False, "stop": "nothing_to_retake"}
    if any(t.get("picked") for t in takes):
        return {"retake": False, "stop": "already_picked"}
    if any(t["status"] == "ready" and t.get("qc_ok") is True for t in takes) and reason != "manual":
        return {"retake": False, "stop": "already_ok"}
    redone = sum(1 for t in takes if t.get("parent_take"))
    if redone >= int(max_retakes):
        return {"retake": False, "stop": "retakes_exhausted"}
    last = max(takes, key=lambda t: t.get("attempt", 0))
    return {"retake": True, "attempt": last.get("attempt", 0) + 1, "parent": last["id"], "reason": reason}

def retry_plan(take, charge_status, takes_of_shot, max_retakes=1):
    if take["status"] not in ("failed", "refunded"):
        return {"retake": False, "stop": "not_failed"}
    if take["status"] != "refunded" and charge_status not in REFUNDED:
        return {"retake": False, "stop": "waiting_refund"}
    return retake_plan(takes_of_shot, "generation_failed", max_retakes)

def _crow(row):
    if not row:
        return None
    d = dict(zip(_CCOLS, row))
    d["segments"] = _json(d.get("segments"), [])
    for k in ("tenant_id", "project_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    return d

def chain_public(c):
    if not c:
        return None
    out = {k: c[k] for k in _CCOLS if k != "tenant_id"}
    for k in ("created_at", "updated_at"):
        if out.get(k) is not None and not isinstance(out[k], str):
            out[k] = out[k].isoformat()
    return out

def clean_segments(segs, prefix="seg"):
    if not isinstance(segs, list) or not 1 <= len(segs) <= MAX_SEGMENTS:
        raise TakeError(400, "segments 要是 1–%d 段的陣列" % MAX_SEGMENTS)
    out = []
    for i, s in enumerate(segs):
        if not isinstance(s, dict) or set(s) - {"prompt", "seconds", "model", "shot_key"}:
            raise TakeError(400, "第 %d 段只能有 prompt、seconds、model、shot_key" % (i + 1))
        p = s.get("prompt")
        if not isinstance(p, str) or not p.strip() or len(p) > 2000:
            raise TakeError(400, "第 %d 段的 prompt 要是 1–2000 字" % (i + 1))
        sec = s.get("seconds")
        if isinstance(sec, bool) or not isinstance(sec, (int, float)) or not 2 <= sec <= 15:
            raise TakeError(400, "第 %d 段的 seconds 要是 2–15" % (i + 1))
        key = s.get("shot_key") or "%s%d" % (prefix, i + 1)
        _check_key(key)
        seg = {"prompt": p, "seconds": float(sec), "shot_key": key, "take_id": None}
        if s.get("model") is not None:
            if not isinstance(s["model"], str) or len(s["model"]) > 120:
                raise TakeError(400, "第 %d 段的 model 不合法" % (i + 1))
            seg["model"] = s["model"]
        out.append(seg)
    if len({s["shot_key"] for s in out}) != len(out):
        raise TakeError(400, "segments 的 shot_key 不能重複")
    return out

def chain_create(conn, tenant, *, project_id, segments, max_retakes=1):
    if isinstance(max_retakes, bool) or not isinstance(max_retakes, int) or not 0 <= max_retakes <= 5:
        raise TakeError(400, "max_retakes 要是 0–5")
    cid = new_chain_id()
    segs = clean_segments(segments, cid[4:12] + "-seg")
    with conn.cursor() as cur:
        cur.execute("INSERT INTO chain_runs (id, tenant_id, project_id, segments, max_retakes)"
                    " VALUES (%s, %s::uuid, %s::uuid, %s::jsonb, %s)",
                    (cid, str(tenant), str(project_id) if project_id else None, json.dumps(segs, ensure_ascii=False),
                     max_retakes))
    return chain_get(conn, tenant, cid)

def chain_get(conn, tenant, cid):
    if not CHAIN_ID.match(str(cid or "")):
        return None
    with conn.cursor() as cur:
        cur.execute(SQL_CHAIN_GET, (str(cid), str(tenant)))
        return _crow(cur.fetchone())

def chain_move(conn, tenant, cid, to, stop_reason=None, segments=None, export_id=None):
    c = chain_get(conn, tenant, cid)
    if not c:
        raise TakeError(404, "沒有這次接力")
    if to != c["status"] and to not in CHAIN_MOVES.get(c["status"], ()):
        raise TakeError(409, "接力現在是 %s，不能改成 %s" % (c["status"], to))
    if stop_reason is not None and not re.match(r"^[a-z_:]{1,64}$", str(stop_reason)):
        raise TakeError(400, "stop_reason 要是小寫英文代碼")
    segs = c["segments"] if segments is None else segments
    with conn.cursor() as cur:
        cur.execute("UPDATE chain_runs SET status = %s, stop_reason = %s, segments = %s::jsonb,"
                    " export_id = COALESCE(%s, export_id), updated_at = now()"
                    " WHERE id = %s AND tenant_id = %s::uuid AND status = %s RETURNING id",
                    (to, stop_reason, json.dumps(segs, ensure_ascii=False), export_id, cid, str(tenant), c["status"]))
        if cur.fetchone() is None:
            raise TakeError(409, "接力的狀態剛被改過，請重新讀一次")
    return chain_get(conn, tenant, cid)

def chain_next(chain, takes_by_shot):
    prev = None
    for i, seg in enumerate(chain["segments"]):
        ts = takes_by_shot.get(seg["shot_key"]) or []
        chosen = next((t for t in ts if t.get("picked")), None)
        if chosen:
            prev = chosen
            continue
        if not ts:
            return {"action": "generate", "segment": i, "shot_key": seg["shot_key"],
                    "first_frame_from": prev["id"] if prev else None}
        if any(t["status"] in ("queued", "generating") for t in ts):
            return {"action": "wait", "segment": i}
        ok = best(ts)
        if ok and ok.get("qc_ok") is not False:
            return {"action": "pick", "segment": i, "take": ok["id"]}
        failed = [t for t in ts if t["status"] in ("failed", "refunded")]
        if failed and not ok and not any(t["status"] == "refunded" for t in failed):
            return {"action": "wait", "segment": i, "reason": "waiting_refund", "take": failed[-1]["id"]}
        reason = "generation_failed" if failed and not ok else "qc_fail"
        plan = retake_plan(ts, reason, chain.get("max_retakes", 1))
        if plan["retake"]:
            return {"action": "retake", "segment": i, "plan": plan}
        return {"action": "stop", "segment": i, "reason": plan["stop"]}
    return {"action": "export"}

ROUTES = {
    ("GET", "/api/takes"), ("POST", "/api/takes"), ("POST", "/api/takes/move"), ("POST", "/api/takes/qc"),
    ("POST", "/api/takes/pick"), ("POST", "/api/takes/retake-plan"),
    ("GET", "/api/chains"), ("POST", "/api/chains"), ("POST", "/api/chains/next"), ("POST", "/api/chains/move"),
}

def _one(q, k):
    v = q.get(k)
    if isinstance(v, list):
        v = v[0] if v else None
    return v or None

def handle(conn, tenant, method, path, body, query, picker="human"):
    b = body if isinstance(body, dict) else {}
    try:
        if (method, path) == ("GET", "/api/takes"):
            tid = _one(query, "id")
            if tid:
                t = get(conn, tenant, tid)
                return (200, public(t)) if t else (404, {"error": "沒有這支 take"})
            items = list_takes(conn, tenant, _one(query, "project_id"), _one(query, "shot_key"))
            return 200, {"items": [public(t) for t in items], "best": (best(items) or {}).get("id")}
        if (method, path) == ("POST", "/api/takes"):
            t = create(conn, tenant, project_id=b.get("project_id"), shot_key=b.get("shot_key"), job_id=b.get("job_id"),
                       parent_take=b.get("parent_take"), reason=b.get("reason"), approval_id=b.get("approval_id"),
                       status=b.get("status") or "queued")
            return 200, public(t)
        if (method, path) == ("POST", "/api/takes/move"):
            return 200, public(move(conn, tenant, b.get("id"), b.get("status"), b.get("error"), b.get("job_id")))
        if (method, path) == ("POST", "/api/takes/qc"):
            return 200, public(record_qc(conn, tenant, b.get("id"), b.get("reports")))
        if (method, path) == ("POST", "/api/takes/pick"):
            return 200, public(pick(conn, tenant, b.get("id"), picker))
        if (method, path) == ("POST", "/api/takes/retake-plan"):
            shot = list_takes(conn, tenant, b.get("project_id"), b.get("shot_key") or "")
            mr = b.get("max_retakes", 1)
            if isinstance(mr, bool) or not isinstance(mr, int) or not 0 <= mr <= 5:
                raise TakeError(400, "max_retakes 要是 0–5")
            if b.get("failed_take"):
                t = get(conn, tenant, b["failed_take"])
                if not t:
                    raise TakeError(404, "沒有這支 take")
                return 200, retry_plan(t, b.get("charge_status"), shot, mr)
            return 200, retake_plan(shot, b.get("reason") or "manual", mr)
        if (method, path) == ("GET", "/api/chains"):
            c = chain_get(conn, tenant, _one(query, "id"))
            return (200, chain_public(c)) if c else (404, {"error": "沒有這次接力"})
        if (method, path) == ("POST", "/api/chains"):
            return 200, chain_public(chain_create(conn, tenant, project_id=b.get("project_id"), segments=b.get("segments"),
                                                  max_retakes=b.get("max_retakes", 1)))
        if (method, path) == ("POST", "/api/chains/move"):
            return 200, chain_public(chain_move(conn, tenant, b.get("id"), b.get("status"), b.get("stop_reason"),
                                                export_id=b.get("export_id")))
        if (method, path) == ("POST", "/api/chains/next"):
            c = chain_get(conn, tenant, b.get("id"))
            if not c:
                raise TakeError(404, "沒有這次接力")
            by = {s["shot_key"]: list_takes(conn, tenant, c["project_id"], s["shot_key"]) for s in c["segments"]}
            step = chain_next(c, by)
            if step["action"] == "stop" and c["status"] != "stopped":
                chain_move(conn, tenant, c["id"], "stopped", step["reason"])
            elif step["action"] != "stop" and c["status"] in ("planning", "stopped"):
                chain_move(conn, tenant, c["id"], "running")
            return 200, dict(step, chain=chain_public(chain_get(conn, tenant, c["id"])))
    except TakeError as e:
        return e.code, {"error": e.message}
    return 404, {"error": "沒有這支端點"}
