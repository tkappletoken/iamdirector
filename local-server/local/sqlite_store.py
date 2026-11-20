import json
import re
import sqlite3

LOCAL_UID = "local"

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS studio_projects (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' ||
       substr(lower(hex(randomblob(2))), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) ||
       substr(lower(hex(randomblob(2))), 2) || '-' || lower(hex(randomblob(6)))),
  tenant_id TEXT NOT NULL,
  name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 60),
  created_by TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS studio_projects_name_uniq ON studio_projects (tenant_id, lower(trim(name)));
CREATE TABLE IF NOT EXISTS studio_project_items (
  project_id TEXT NOT NULL REFERENCES studio_projects(id) ON DELETE CASCADE,
  tenant_id TEXT NOT NULL,
  item_kind TEXT NOT NULL,
  item_id TEXT NOT NULL,
  added_by TEXT,
  added_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  PRIMARY KEY (project_id, item_kind, item_id)
);
CREATE TABLE IF NOT EXISTS studio_kv (
  tenant_id TEXT NOT NULL,
  key TEXT NOT NULL,
  value JSONB NOT NULL,
  bytes INTEGER NOT NULL CHECK (bytes <= 262144),
  updated_by TEXT,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  PRIMARY KEY (tenant_id, key)
);
-- 核准卡與花費上限（P1，跟正式站 034_approvals 同名同欄位；SQL 在根目錄 approvals.py，兩邊共用）
CREATE TABLE IF NOT EXISTS approval_cards (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  charge_id TEXT,
  quote_ref TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL DEFAULT 'video',
  payer TEXT NOT NULL,
  points TEXT,
  upstream_cost TEXT,
  summary JSONB NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending',
  token_id TEXT,
  job_id TEXT,
  error TEXT,
  expires_at TEXT NOT NULL,
  decided_at TEXT,
  submitted_at TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE IF NOT EXISTS user_spend_limits (
  user_id TEXT PRIMARY KEY,
  per_job_points TEXT, daily_points TEXT, per_job_upstream TEXT, daily_upstream TEXT,
  updated_at TEXT
);
-- 本機報價（以前只放在程序記憶體 st.quotes）：App 重開之後核准卡還送得出去
CREATE TABLE IF NOT EXISTS local_quotes (
  quote_id TEXT PRIMARY KEY,
  payload JSONB NOT NULL,
  upstream_cost TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
-- 每鏡候選與定稿、長片接力（M3，跟正式站 036_shot_takes 同名同欄位；SQL 在根目錄 takes.py，兩邊共用）
CREATE TABLE IF NOT EXISTS shot_takes (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  project_id TEXT REFERENCES studio_projects(id) ON DELETE CASCADE,
  shot_key TEXT NOT NULL,
  job_id TEXT,
  parent_take TEXT REFERENCES shot_takes(id) ON DELETE SET NULL,
  reason TEXT,
  attempt INTEGER NOT NULL DEFAULT 1,
  charge_id TEXT,
  approval_id TEXT REFERENCES approval_cards(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'generating', 'ready', 'failed', 'refunded')),
  qc JSONB NOT NULL DEFAULT '[]',
  qc_ok INTEGER,
  picked INTEGER NOT NULL DEFAULT 0,
  picked_by TEXT,
  picked_at TEXT,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS shot_takes_shot_idx ON shot_takes (tenant_id, project_id, shot_key, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS shot_takes_job_uniq ON shot_takes (tenant_id, job_id) WHERE job_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS shot_takes_picked_uniq ON shot_takes (tenant_id, COALESCE(CAST(project_id AS TEXT), ''), shot_key) WHERE picked;
CREATE TABLE IF NOT EXISTS chain_runs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  project_id TEXT REFERENCES studio_projects(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'planning' CHECK (status IN ('planning', 'running', 'done', 'failed', 'stopped')),
  segments JSONB NOT NULL DEFAULT '[]',
  max_retakes INTEGER NOT NULL DEFAULT 1,
  stop_reason TEXT,
  export_id TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""

ADD_COLUMNS = (
    ("approval_cards", "payload", "JSONB"), ("approval_cards", "quote_expires_at", "TEXT"),
    ("approval_cards", "approved_points", "TEXT"), ("approval_cards", "approved_upstream", "TEXT"),
    ("approval_cards", "batch_id", "TEXT"), ("approval_cards", "note", "TEXT"),
    ("approval_cards", "decided_by", "TEXT"),
    ("user_spend_limits", "auto_approve", "INTEGER"), ("user_spend_limits", "limits_version", "INTEGER"),
)

sqlite3.register_converter("JSONB", lambda b: json.loads(b.decode("utf-8")))

_ANY = re.compile(r"=\s*ANY\(%s\)", re.I)

def translate(sql, params):
    params = list(params or ())
    if _ANY.search(sql):
        out, pi, pos = [], 0, 0
        new_params = []
        for m in re.finditer(r"%s", sql):
            out.append(sql[pos:m.start()])
            p = params[pi]
            before = sql[max(0, m.start() - 6):m.start()].upper()
            if before.endswith("ANY(") and isinstance(p, (list, tuple)):
                out.append(",".join("?" * len(p)) if p else "NULL")
                new_params.extend(p)
                out[-2] = re.sub(r"=\s*ANY\($", "IN (", out[-2], flags=re.I)
            else:
                out.append("?")
                new_params.append(p)
            pi += 1
            pos = m.end()
        out.append(sql[pos:])
        sql, params = "".join(out), new_params
    else:
        sql = sql.replace("%s", "?")
    sql = sql.replace("::uuid", "").replace("::jsonb", "")
    sql = re.sub(r"\bbtrim\(", "trim(", sql)
    sql = re.sub(r"\bnow\(\)", "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')", sql)
    return sql, params

class _Cursor:
    def __init__(self, cur):
        self._cur = cur

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._cur.close()

    def execute(self, sql, params=()):
        sql, params = translate(sql, params)
        self._cur.execute(sql, params)
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def rowcount(self):
        return self._cur.rowcount

class Conn:

    def __init__(self, raw):
        self._raw = raw

    def cursor(self):
        return _Cursor(self._raw.cursor())

class LocalDB:
    def __init__(self, path):
        if sqlite3.sqlite_version_info < (3, 35):
            raise RuntimeError("SQLite 版本太舊（需要 3.35 以上才有 RETURNING）：%s" % sqlite3.sqlite_version)
        self.path = path
        raw = self._open()
        raw.executescript(SCHEMA)
        for table, col, typ in ADD_COLUMNS:
            have = {r[1] for r in raw.execute("PRAGMA table_info(%s)" % table)}
            if col not in have:
                raw.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, typ))
        raw.close()

    def _open(self):
        raw = sqlite3.connect(self.path, detect_types=sqlite3.PARSE_DECLTYPES, timeout=10,
                              isolation_level=None)
        raw.execute("PRAGMA foreign_keys = ON")
        raw.execute("PRAGMA journal_mode = WAL")
        return raw

    def run(self, fn, *args):
        raw = self._open()
        try:
            raw.execute("BEGIN IMMEDIATE")
            out = fn(Conn(raw), LOCAL_UID, *args)
            raw.execute("COMMIT")
            return out
        except BaseException:
            raw.execute("ROLLBACK")
            raise
        finally:
            raw.close()

def ensure_project(conn, uid, pid, name):
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM studio_projects WHERE tenant_id = %s AND id = %s", (uid, pid))
        if cur.fetchone() is not None:
            return name
        for cand in (name, (name + "（雲端）")[:60], (name[:50] + "（雲端 %s）" % pid[:4])):
            cur.execute("SELECT 1 FROM studio_projects WHERE tenant_id = %s AND lower(trim(name)) = lower(trim(%s))",
                        (uid, cand))
            if cur.fetchone() is None:
                cur.execute("INSERT INTO studio_projects (id, tenant_id, name, created_by) VALUES (%s, %s, %s, %s)",
                            (pid, uid, cand, uid))
                return cand
    raise RuntimeError("找不到可用的專案名稱")
