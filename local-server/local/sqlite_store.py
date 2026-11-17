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
"""

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
