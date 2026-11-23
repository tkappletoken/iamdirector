import json
import secrets
import re
import threading
import time

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

_UNSET = object()

def _shot_at(board, shot):
    if isinstance(shot, int) and not isinstance(shot, bool):
        return shot - 1 if 1 <= shot <= len(board) else None
    if isinstance(shot, str) and shot:
        for i, x in enumerate(board):
            if isinstance(x, dict) and x.get("sid") == shot:
                return i
    return None

def _board_read(conn, uid, pid):
    _check_pid(pid)
    key = board_key(pid)
    board = kv_get(conn, uid, key).get("value")
    if not isinstance(board, list) or not board:
        raise StoreError(404, "not_found", "找不到這部作品的分鏡")
    return key, board

def _conflict(message, current):
    e = StoreError(409, "conflict", message)
    e.body["current"] = current
    return e

def _shot_view(board, idx):
    if idx is None or not 0 <= idx < len(board):
        return None
    sh = board[idx] if isinstance(board[idx], dict) else {"prompt": str(board[idx])}
    return {"shot": idx + 1, "sid": sh.get("sid"), "prompt": sh.get("prompt"), "seconds": sh.get("seconds")}

def _order(board):
    return [x.get("sid") if isinstance(x, dict) else None for x in board]

def _board_cas(conn, uid, key, old, new, current_of):
    dump = lambda v: json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    blob = dump(new)
    n = len(blob.encode("utf-8"))
    if n > KV_MAX_BYTES:
        raise StoreError(413, "too_large", "資料 %d bytes，超過 %d bytes 上限" % (n, KV_MAX_BYTES))
    with conn.cursor() as cur:
        cur.execute("UPDATE studio_kv SET value = %s::jsonb, bytes = %s, updated_by = %s, updated_at = now()"
                    " WHERE tenant_id = %s AND key = %s AND value = %s::jsonb",
                    (blob, n, uid, uid, key, dump(old)))
        if cur.rowcount != 1:
            now = kv_get(conn, uid, key).get("value")
            raise _conflict("分鏡在你讀過之後被改過了，沒有寫入；照 current 重新讀過再改",
                            current_of(now if isinstance(now, list) else []))
    return n

def shot_edit(conn, uid, pid, shot, expect, prompt=_UNSET, seconds=_UNSET):
    if prompt is _UNSET and seconds is _UNSET:
        raise StoreError(400, "nothing", "要給 prompt 或 seconds 至少一項")
    if not isinstance(expect, str):
        raise StoreError(400, "bad_expect", "expect 要是你讀到的這一鏡 prompt（字串），用來確認沒有人在你之後改過")
    if prompt is not _UNSET and (not isinstance(prompt, str) or not prompt.strip() or len(prompt) > WORK_PROMPT_MAX):
        raise StoreError(400, "bad_prompt", "prompt 要有 1–%d 個字" % WORK_PROMPT_MAX)
    if seconds is not _UNSET and seconds is not None and (
            isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 1 <= seconds <= 30):
        raise StoreError(400, "bad_seconds", "seconds 要是 1–30 的數字，或 null")
    key, board = _board_read(conn, uid, pid)
    idx = _shot_at(board, shot)
    if idx is None:
        raise StoreError(404, "no_shot", "這部作品沒有這一鏡（shot 用 1 起算的第幾鏡，或 sid）")
    cur_shot = board[idx] if isinstance(board[idx], dict) else {"prompt": str(board[idx])}
    if str(cur_shot.get("prompt") or "") != expect:
        raise _conflict("第 %d 鏡在你讀過之後被改過了，沒有寫入" % (idx + 1), _shot_view(board, idx))
    sh = dict(cur_shot)
    if prompt is not _UNSET:
        sh["prompt"] = prompt.strip()
    if seconds is not _UNSET:
        sh["seconds"] = seconds
    new = list(board)
    new[idx] = sh
    sid = sh.get("sid")
    _board_cas(conn, uid, key, board, new, lambda b: _shot_view(b, _shot_at(b, sid) if sid else idx))
    return {"key": key, "shot": idx + 1, "sid": sh.get("sid"), "prompt": sh.get("prompt"), "seconds": sh.get("seconds"),
            "prev": {"prompt": cur_shot.get("prompt"), "seconds": cur_shot.get("seconds")}}

def shot_move(conn, uid, pid, shot, to, expect_order):
    if not isinstance(expect_order, list) or not all(isinstance(x, str) for x in expect_order):
        raise StoreError(400, "bad_expect", "expect_order 要是你讀到的每一鏡 sid（照順序），用來確認沒有人在你之後改過")
    key, board = _board_read(conn, uid, pid)
    order = [x.get("sid") if isinstance(x, dict) else None for x in board]
    if order != expect_order:
        raise _conflict("分鏡的順序在你讀過之後變了，沒有搬", {"order": order})
    idx = _shot_at(board, shot)
    if idx is None:
        raise StoreError(404, "no_shot", "這部作品沒有這一鏡（shot 用 1 起算的第幾鏡，或 sid）")
    if isinstance(to, bool) or not isinstance(to, int) or not 1 <= to <= len(board):
        raise StoreError(400, "bad_to", "to 要是 1–%d（搬到第幾鏡）" % len(board))
    new = list(board)
    moved = new.pop(idx)
    new.insert(to - 1, moved)
    _board_cas(conn, uid, key, board, new, lambda b: {"order": _order(b)})
    return {"key": key, "sid": moved.get("sid") if isinstance(moved, dict) else None, "from": idx + 1, "to": to,
            "order": [x.get("sid") if isinstance(x, dict) else None for x in new], "prev_order": order}

DC_FIELDS = ("dc", "dc_prev")
DC_PREV = {"dc": "dc_prev"}
TEXT_FIELDS = ("prompt", "seconds")

def merge_shots(value, server, late, touched, fields, prev=None):
    prev = prev or {}
    by = {s.get("sid"): s for s in (server if isinstance(server, list) else []) if isinstance(s, dict) and s.get("sid")}
    out, merged = [], []
    for i, s in enumerate(value):
        sid = s.get("sid") if isinstance(s, dict) else None
        if sid not in late or sid not in by:
            out.append(s)
            continue
        s, a = dict(s), by[sid]
        if sid in touched:
            for k, pk in prev.items():
                if a.get(k) and a.get(k) != s.get(k):
                    s[pk] = a[k]
            kept = "human"
        else:
            for k in fields:
                s.pop(k, None)
                if a.get(k):
                    s[k] = a[k]
            kept = "agent"
        merged.append(dict({"shot": i + 1, "sid": sid, "kept": kept}, **{k: s.get(k) for k in fields}))
        out.append(s)
    return out, merged

def merge_order(value, base_order, agent_order):
    sids = [s.get("sid") if isinstance(s, dict) else None for s in value]
    if not agent_order or sids != list(base_order or []):
        return value, False
    pos = {sid: i for i, sid in enumerate(agent_order)}
    out = sorted(value, key=lambda s: pos.get(s.get("sid") if isinstance(s, dict) else None, len(agent_order)))
    return out, out != value

class AgentWrites:
    TTL = 6 * 3600
    MAX_KEYS = 2000

    def __init__(self):
        self._lock = threading.Lock()
        self._d = {}

    def _slot(self, uid, key):
        k = (str(uid), key)
        slot = self._d.get(k)
        if slot is None:
            if len(self._d) >= self.MAX_KEYS:
                self._d.pop(next(iter(self._d)))
            slot = self._d[k] = {"shots": {}, "order": None}
        return slot

    def _expire(self, slot, now):
        slot["shots"] = {sid: e for sid, e in slot["shots"].items() if now - e["at"] < self.TTL}
        if slot["order"] and now - slot["order"]["at"] >= self.TTL:
            slot["order"] = None

    def edit(self, uid, key, sid, base, agent):
        with self._lock:
            slot = self._slot(uid, key)
            old = slot["shots"].get(sid)
            slot["shots"][sid] = {"base": old["base"] if old else dict(base), "agent": dict(agent), "at": time.time()}

    def move(self, uid, key, base_order, agent_order):
        with self._lock:
            slot = self._slot(uid, key)
            old = slot["order"]
            slot["order"] = {"base": list(old["base"] if old else base_order), "agent": list(agent_order), "at": time.time()}

    def plan(self, uid, key, value):
        if not isinstance(value, list):
            return value, None
        now = time.time()
        with self._lock:
            slot = self._d.get((str(uid), key))
            if not slot:
                return value, None
            self._expire(slot, now)
            pend = {sid: dict(e) for sid, e in slot["shots"].items()}
            order = dict(slot["order"]) if slot["order"] else None
        pick = lambda s: {k: s.get(k) for k in TEXT_FIELDS}
        incoming = {s.get("sid"): s for s in value if isinstance(s, dict) and s.get("sid")}
        late, touched, done = set(), set(), set()
        for sid, e in pend.items():
            s = incoming.get(sid)
            if s is None:
                done.add(sid)
                continue
            cur = pick(s)
            if cur == e["base"]:
                late.add(sid)
            else:
                done.add(sid)
                if cur != e["agent"]:
                    touched.add(sid)
        server = [dict(e["agent"], sid=sid) for sid, e in pend.items()]
        out, merged = merge_shots(value, server, late, set(), TEXT_FIELDS)
        reordered = False
        if order:
            out, reordered = merge_order(out, order["base"], order["agent"])
        with self._lock:
            slot = self._d.get((str(uid), key))
            if slot:
                for sid in done:
                    slot["shots"].pop(sid, None)
                if order and not reordered:
                    slot["order"] = None
        if not merged and not reordered:
            return value, None
        return out, {"merged": merged, "order": reordered, "human": sorted(touched)}

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

def work_get(conn, uid, pid):
    _check_pid(pid)
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM studio_projects WHERE tenant_id = %s AND id = %s::uuid", (uid, pid))
        row = cur.fetchone()
    if row is None:
        raise StoreError(404, "not_found", "找不到這部作品")
    board = kv_get(conn, uid, board_key(pid)).get("value")
    meta = kv_get(conn, uid, meta_key(pid)).get("value")
    out = {"project_id": pid, "name": row[0],
           "shots": [{"sid": s.get("sid"), "prompt": s.get("prompt"), "seconds": s.get("seconds")}
                     for s in (board if isinstance(board, list) else []) if isinstance(s, dict)]}
    if isinstance(meta, dict) and isinstance(meta.get("template"), str):
        out["template"], out["fields"] = meta["template"], meta.get("fields") or {}
    return out

def work_meta(conn, uid, pid):
    _check_pid(pid)
    got = kv_get(conn, uid, meta_key(pid))
    v = got.get("value") if isinstance(got, dict) else None
    if not isinstance(v, dict) or not isinstance(v.get("template"), str):
        raise StoreError(404, "no_template", "這部作品不是用範本建的（沒有範本的送件設定）")
    return v
