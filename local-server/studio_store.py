import json
import secrets
import re

MAX_PROJECTS = 200
NAME_MAX = 60
KV_MAX_BYTES = 262144
ITEM_KIND = "job"
KEY_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
ITEM_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

class StoreError(RuntimeError):
    def __init__(self, code, err_code, message):
        super().__init__(message)
        self.code = code
        self.body = {"error": {"code": err_code, "message": message}}

def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v

def list_projects(conn, uid):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.id, p.name, p.created_at, count(i.item_id)"
            "  FROM studio_projects p"
            "  LEFT JOIN studio_project_items i ON i.project_id = p.id"
            " WHERE p.tenant_id = %s"
            " GROUP BY p.id, p.name, p.created_at"
            " ORDER BY p.created_at", (uid,))
        projects = [{"id": str(r[0]), "name": r[1], "created_at": _iso(r[2]),
                     "item_count": int(r[3])} for r in cur.fetchall()]
        cur.execute(
            "SELECT item_id, project_id FROM studio_project_items"
            " WHERE tenant_id = %s AND item_kind = %s", (uid, ITEM_KIND))
        items = {}
        for item_id, pid in cur.fetchall():
            items.setdefault(item_id, []).append(str(pid))
    return {"projects": projects, "items": items}

def create_project(conn, uid, name):
    name = (name or "").strip()
    if not name or len(name) > NAME_MAX:
        raise StoreError(400, "bad_name", "專案名稱要有 1–%d 個字" % NAME_MAX)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM studio_projects WHERE tenant_id = %s", (uid,))
        if cur.fetchone()[0] >= MAX_PROJECTS:
            raise StoreError(409, "too_many", "專案數已達上限 %d 個" % MAX_PROJECTS)
        cur.execute(
            "INSERT INTO studio_projects (tenant_id, name, created_by) VALUES (%s, %s, %s)"
            " ON CONFLICT DO NOTHING RETURNING id", (uid, name, uid))
        row = cur.fetchone()
    if row is None:
        raise StoreError(409, "duplicate_name", "已經有同名的專案了")
    return {"id": str(row[0]), "name": name, "item_count": 0}

def _check_pid(pid):
    if not UUID_RE.match(pid or ""):
        raise StoreError(400, "bad_id", "專案 id 不合法")

def rename_project(conn, uid, pid, name):
    _check_pid(pid)
    name = (name or "").strip()
    if not name or len(name) > NAME_MAX:
        raise StoreError(400, "bad_name", "專案名稱要有 1–%d 個字" % NAME_MAX)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE studio_projects SET name = %s"
            " WHERE tenant_id = %s AND id = %s::uuid"
            "   AND NOT EXISTS (SELECT 1 FROM studio_projects q"
            "                    WHERE q.tenant_id = %s AND q.id <> %s::uuid"
            "                      AND lower(btrim(q.name)) = lower(btrim(%s)))"
            " RETURNING id", (name, uid, pid, uid, pid, name))
        if cur.fetchone() is None:
            cur.execute("SELECT 1 FROM studio_projects WHERE tenant_id = %s AND id = %s::uuid", (uid, pid))
            if cur.fetchone() is None:
                raise StoreError(404, "not_found", "找不到這個專案")
            raise StoreError(409, "duplicate_name", "已經有同名的專案了")
    return {"id": pid, "name": name}

def delete_project(conn, uid, pid):
    _check_pid(pid)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM studio_projects WHERE tenant_id = %s AND id = %s::uuid",
                    (uid, pid))
        if cur.rowcount == 0:
            raise StoreError(404, "not_found", "找不到這個專案")
    return {"ok": True}

def owns_project(conn, uid, pid):
    if not UUID_RE.match(pid or ""):
        return False
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM studio_projects WHERE tenant_id = %s AND id = %s::uuid", (uid, pid))
        return cur.fetchone() is not None

def attach_item(conn, uid, pid, item_id):
    _check_pid(pid)
    if not ITEM_RE.match(item_id or ""):
        raise StoreError(400, "bad_item", "item_id 不合法")
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM studio_projects WHERE tenant_id = %s AND id = %s::uuid",
                    (uid, pid))
        if cur.fetchone() is None:
            raise StoreError(404, "not_found", "找不到這個專案")
        cur.execute(
            "INSERT INTO studio_project_items (project_id, tenant_id, item_kind, item_id, added_by)"
            " VALUES (%s::uuid, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (pid, uid, ITEM_KIND, item_id, uid))
    return {"ok": True}

def detach_item(conn, uid, pid, item_id):
    _check_pid(pid)
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM studio_project_items WHERE tenant_id = %s AND project_id = %s::uuid"
            "   AND item_kind = %s AND item_id = %s", (uid, pid, ITEM_KIND, item_id))
    return {"ok": True}

def _check_key(key):
    if not KEY_RE.match(key or ""):
        raise StoreError(400, "invalid_key", "key 只允許小寫英數與 - _，長度 1–32")

def kv_get(conn, uid, key):
    _check_key(key)
    with conn.cursor() as cur:
        cur.execute("SELECT value, bytes, updated_at FROM studio_kv"
                    " WHERE tenant_id = %s AND key = %s", (uid, key))
        row = cur.fetchone()
    if row is None:
        return {"key": key, "value": None, "bytes": None, "updated_at": None}
    return {"key": key, "value": row[0], "bytes": row[1], "updated_at": _iso(row[2])}

def kv_get_many(conn, uid, keys):
    keys = list(dict.fromkeys(keys))
    for k in keys:
        _check_key(k)
    out = {k: None for k in keys}
    if not keys:
        return out
    with conn.cursor() as cur:
        cur.execute("SELECT key, value FROM studio_kv"
                    " WHERE tenant_id = %s AND key = ANY(%s)", (uid, keys))
        for k, v in cur.fetchall():
            out[k] = v
    return out

def kv_put(conn, uid, key, value):
    _check_key(key)
    blob = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    n = len(blob.encode("utf-8"))
    if n > KV_MAX_BYTES:
        raise StoreError(413, "too_large", "資料 %d bytes，超過 %d bytes 上限" % (n, KV_MAX_BYTES))
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO studio_kv (tenant_id, key, value, bytes, updated_by)"
            " VALUES (%s, %s, %s::jsonb, %s, %s)"
            " ON CONFLICT (tenant_id, key) DO UPDATE SET value = EXCLUDED.value,"
            "   bytes = EXCLUDED.bytes, updated_by = EXCLUDED.updated_by, updated_at = now()",
            (uid, key, blob, n, uid))
    return {"key": key, "bytes": n}

def kv_delete(conn, uid, key):
    _check_key(key)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM studio_kv WHERE tenant_id = %s AND key = %s", (uid, key))
        return {"key": key, "deleted": cur.rowcount > 0}

WORK_SHOTS_MAX = 30
WORK_PROMPT_MAX = 2000

def board_key(pid):
    return "sb_" + str(pid).replace("-", "")[:29]

def normalize_shots(shots):
    if not isinstance(shots, list) or not 1 <= len(shots) <= WORK_SHOTS_MAX:
        raise StoreError(400, "bad_shots", "分鏡要有 1–%d 鏡" % WORK_SHOTS_MAX)
    out = []
    for i, s in enumerate(shots, 1):
        s = s if isinstance(s, dict) else {"prompt": s}
        p = s.get("prompt")
        if not isinstance(p, str) or not p.strip() or len(p) > WORK_PROMPT_MAX:
            raise StoreError(400, "bad_shots", "第 %d 鏡的 prompt 要有 1–%d 個字" % (i, WORK_PROMPT_MAX))
        sec = s.get("seconds")
        if sec not in (None, ""):
            if isinstance(sec, bool) or not isinstance(sec, (int, float)) or not 1 <= sec <= 30:
                raise StoreError(400, "bad_shots", "第 %d 鏡的 seconds 要是 1–30 的數字" % i)
        out.append({"sid": "s%s%02d" % (secrets.token_hex(5), i), "prompt": p.strip(),
                    "seconds": sec if sec not in (None, "") else None, "pick": True})
    return out

def meta_key(pid):
    return "tp_" + str(pid).replace("-", "")[:29]

def create_work(conn, uid, name, shots, meta=None):
    lst = normalize_shots(shots)
    proj = create_project(conn, uid, name)
    kv_put(conn, uid, board_key(proj["id"]), lst)
    out = {"project_id": proj["id"], "name": proj["name"], "shots": len(lst), "board_key": board_key(proj["id"])}
    if meta:
        kv_put(conn, uid, meta_key(proj["id"]), meta)
        out["template"] = meta.get("template")
    return out

def work_meta(conn, uid, pid):
    _check_pid(pid)
    got = kv_get(conn, uid, meta_key(pid))
    v = got.get("value") if isinstance(got, dict) else None
    if not isinstance(v, dict) or not isinstance(v.get("template"), str):
        raise StoreError(404, "no_template", "這部作品不是用範本建的（沒有範本的送件設定）")
    return v
