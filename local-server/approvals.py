import datetime
import decimal
import json
import re
import secrets

ID = re.compile(r"^apv_[A-Za-z0-9]{16,32}$")
STATUSES = ("pending", "approved", "rejected", "expired", "submitted", "failed")
CARD_TTL = datetime.timedelta(hours=24)
TZ = datetime.timezone(datetime.timedelta(hours=8))
NOT_READY = "核准卡尚未啟用（資料庫還沒套用 034_approvals）。這段期間 Agent 不能用核准卡送件；工作台其他功能不受影響。"
LIMIT_KEYS = ("per_job_points", "daily_points", "per_job_upstream", "daily_upstream")

_COLS = ("id", "user_id", "charge_id", "quote_ref", "kind", "payer", "points", "upstream_cost",
         "summary", "status", "token_id", "job_id", "error", "expires_at", "decided_at", "submitted_at", "created_at")

class ApprovalError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message

def new_id():
    return "apv_" + secrets.token_hex(12)

def _dec(x):
    if x is None or x == "":
        return None
    try:
        return decimal.Decimal(str(x))
    except (decimal.InvalidOperation, ValueError):
        return None

def measure(payer):
    return "points" if payer == "points" else "upstream"

def amount(card):
    return _dec(card.get("points") if measure(card.get("payer")) == "points" else card.get("upstream_cost"))

def fmt(x):
    d = _dec(x)
    if d is None:
        return "—"
    s = format(d.normalize(), "f")
    return s if "." not in s else s.rstrip("0").rstrip(".") or "0"

def payer_text(payer):
    return "你自己的 AppleToken 額度" if payer == "own_key" else "本站點數"

def summary_of(body):
    b = body if isinstance(body, dict) else {}
    out = {}
    for k in ("model", "seconds", "aspect_ratio", "resolution", "generate_audio"):
        if b.get(k) not in (None, ""):
            out[k] = b[k]
    p = b.get("prompt")
    if isinstance(p, str) and p.strip():
        out["prompt"] = p.strip()[:280]
    refs = b.get("input_references")
    if isinstance(refs, list) and refs:
        out["references"] = len(refs)
    return out

def describe(card):
    s = card.get("summary") or {}
    unit = "點" if measure(card.get("payer")) == "points" else "AppleToken 額度"
    bits = ["付款方：" + payer_text(card.get("payer")),
            "金額：%s %s%s" % (fmt(amount(card)), unit, "（帶參考影片，實際可能較高）" if s.get("open_ended") else ""),
            "模型：%s" % (s.get("model") or "—"),
            "秒數：%s" % (("%s 秒" % s["seconds"]) if s.get("seconds") not in (None, "") else "—")]
    return "；".join(bits)

def day_start(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    local = now.astimezone(TZ)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

def iso(t):
    return t.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

def _ts(x):
    if x is None:
        return None
    if isinstance(x, datetime.datetime):
        return x if x.tzinfo else x.replace(tzinfo=datetime.timezone.utc)
    s = str(x).replace("Z", "+00:00").replace(" ", "T")
    try:
        t = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)

def check_limits(card, limits, used_today):
    m = measure(card.get("payer"))
    amt = amount(card)
    lim = limits or {}
    per, daily = _dec(lim.get("per_job_" + m)), _dec(lim.get("daily_" + m))
    unit = "點" if m == "points" else "AppleToken 額度"
    if (per is not None or daily is not None) and amt is None:
        return "這張卡算不出金額，你設了上限，所以不能核准。請重新報價。"
    if (per is not None or daily is not None) and (card.get("summary") or {}).get("open_ended"):
        return "這一支帶參考影片，實際費用可能比報價高，保證不了你設的上限，所以不能用核准卡送出。"
    if per is not None and amt > per:
        return "這一支要 %s %s，超過你設的單支上限 %s。" % (fmt(amt), unit, fmt(per))
    if daily is not None and (used_today or 0) + amt > daily:
        return "今天已核准 %s %s，加上這一支 %s 會超過每日上限 %s。" % (fmt(used_today or 0), unit, fmt(amt), fmt(daily))
    return None

def public(card, link=None):
    out = {k: card.get(k) for k in ("id", "quote_ref", "kind", "payer", "status", "job_id", "error")}
    out["points"] = fmt(card.get("points")) if card.get("points") is not None else None
    out["upstream_cost"] = fmt(card.get("upstream_cost")) if card.get("upstream_cost") is not None else None
    out["amount"] = fmt(amount(card)) if amount(card) is not None else None
    out["unit"] = "點" if measure(card.get("payer")) == "points" else "AppleToken 額度"
    out["payer_text"] = payer_text(card.get("payer"))
    out["summary"] = card.get("summary") or {}
    out["text"] = describe(card)
    for k in ("expires_at", "decided_at", "submitted_at", "created_at"):
        t = _ts(card.get(k))
        out[k] = iso(t) if t else None
    if link:
        out["approve_url"] = link
    return out

def _row(row):
    if not row:
        return None
    d = dict(zip(_COLS, row))
    if isinstance(d.get("summary"), str):
        try:
            d["summary"] = json.loads(d["summary"])
        except ValueError:
            d["summary"] = {}
    return d

SEL = ("SELECT id, user_id, charge_id, quote_ref, kind, payer, points, upstream_cost, summary, status,"
       " token_id, job_id, error, expires_at, decided_at, submitted_at, created_at FROM approval_cards")

def create(conn, *, user_id, charge, summary, expires_at, token_id=None):
    cid = new_id()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO approval_cards (id, user_id, charge_id, quote_ref, kind, payer, points, upstream_cost,"
            " summary, status, token_id, expires_at)"
            " VALUES (%s, %s::uuid, %s, %s, %s, %s, %s, %s, %s::jsonb, 'pending', %s, %s)"
            " ON CONFLICT (quote_ref) DO NOTHING",
            (cid, str(user_id), str(charge["id"]) if charge.get("id") is not None else None, charge["quote_ref"],
             charge.get("kind") or "video", charge["payer"],
             str(charge["points"]) if charge.get("points") is not None else None,
             str(charge["upstream_cost"]) if charge.get("upstream_cost") is not None else None,
             json.dumps(summary or {}, ensure_ascii=False), str(token_id) if token_id else None, iso(expires_at)))
    return by_quote(conn, user_id, charge["quote_ref"])

def get(conn, user_id, cid):
    if not ID.match(str(cid or "")):
        return None
    with conn.cursor() as cur:
        cur.execute(SEL + " WHERE id = %s AND user_id = %s::uuid", (str(cid), str(user_id)))
        return _expire(conn, _row(cur.fetchone()))

def by_quote(conn, user_id, quote_ref):
    with conn.cursor() as cur:
        cur.execute(SEL + " WHERE quote_ref = %s AND user_id = %s::uuid", (str(quote_ref), str(user_id)))
        return _expire(conn, _row(cur.fetchone()))

def list_cards(conn, user_id, status=None, limit=50):
    with conn.cursor() as cur:
        if status:
            cur.execute(SEL + " WHERE user_id = %s::uuid AND status = %s ORDER BY created_at DESC LIMIT %s",
                        (str(user_id), status, int(limit)))
        else:
            cur.execute(SEL + " WHERE user_id = %s::uuid ORDER BY created_at DESC LIMIT %s",
                        (str(user_id), int(limit)))
        return [_expire(conn, _row(r)) for r in cur.fetchall()]

def _expire(conn, card, now=None):
    if not card or card["status"] not in ("pending", "approved"):
        return card
    exp = _ts(card.get("expires_at"))
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if exp and exp <= now:
        with conn.cursor() as cur:
            cur.execute("UPDATE approval_cards SET status = 'expired' WHERE id = %s AND status = %s",
                        (card["id"], card["status"]))
        card = dict(card, status="expired")
    return card

def _move(conn, user_id, cid, frm, to):
    with conn.cursor() as cur:
        if to == "submitted":
            cur.execute("UPDATE approval_cards SET status = %s, submitted_at = now()"
                        " WHERE id = %s AND user_id = %s::uuid AND status = %s RETURNING id",
                        (to, str(cid), str(user_id), frm))
        else:
            cur.execute("UPDATE approval_cards SET status = %s, decided_at = now()"
                        " WHERE id = %s AND user_id = %s::uuid AND status = %s RETURNING id",
                        (to, str(cid), str(user_id), frm))
        return cur.fetchone() is not None

def used_today(conn, user_id, m, now=None):
    with conn.cursor() as cur:
        cur.execute("SELECT payer, points, upstream_cost FROM approval_cards WHERE user_id = %s::uuid"
                    " AND status IN ('approved', 'submitted') AND decided_at >= %s",
                    (str(user_id), day_start(now)))
        rows = cur.fetchall()
    total = decimal.Decimal(0)
    for payer, pts, up in rows:
        if measure(payer) != m:
            continue
        v = _dec(pts if m == "points" else up)
        if v is not None:
            total += v
    return total

def limits_get(conn, user_id):
    with conn.cursor() as cur:
        cur.execute("SELECT per_job_points, daily_points, per_job_upstream, daily_upstream"
                    " FROM user_spend_limits WHERE user_id = %s::uuid", (str(user_id),))
        row = cur.fetchone()
    return {k: (fmt(v) if v is not None else None) for k, v in zip(LIMIT_KEYS, row or (None,) * 4)}

def limits_set(conn, user_id, body):
    vals = []
    for k in LIMIT_KEYS:
        v = (body or {}).get(k)
        if v in (None, ""):
            vals.append(None)
            continue
        d = _dec(v)
        if d is None or d <= 0 or d > decimal.Decimal("1000000"):
            raise ApprovalError(400, "%s 要是大於 0 的數字（或留空表示不設上限）" % k)
        vals.append(str(d))
    with conn.cursor() as cur:
        cur.execute("INSERT INTO user_spend_limits (user_id, per_job_points, daily_points, per_job_upstream,"
                    " daily_upstream, updated_at) VALUES (%s::uuid, %s, %s, %s, %s, now())"
                    " ON CONFLICT (user_id) DO UPDATE SET per_job_points = excluded.per_job_points,"
                    " daily_points = excluded.daily_points, per_job_upstream = excluded.per_job_upstream,"
                    " daily_upstream = excluded.daily_upstream, updated_at = now()",
                    (str(user_id),) + tuple(vals))
    return limits_get(conn, user_id)

def decide(conn, user_id, cid, approve, now=None):
    card = get(conn, user_id, cid)
    if not card:
        raise ApprovalError(404, "找不到這張核准卡")
    if card["status"] != "pending":
        raise ApprovalError(409, "這張卡已經是「%s」了，不能再核准或拒絕" % card["status"])
    if not approve:
        _move(conn, user_id, cid, "pending", "rejected")
        return dict(card, status="rejected")
    why = check_limits(card, limits_get(conn, user_id), used_today(conn, user_id, measure(card["payer"]), now))
    if why:
        raise ApprovalError(422, why)
    if not _move(conn, user_id, cid, "pending", "approved"):
        raise ApprovalError(409, "這張卡剛剛被處理過了")
    return get(conn, user_id, cid)

def claim_for_submit(conn, user_id, cid, expect_amount=None, now=None):
    card = get(conn, user_id, cid)
    if not card:
        raise ApprovalError(404, "找不到這張核准卡")
    if card["status"] != "approved":
        hint = {"pending": "還沒有人核准，請使用者打開卡片按核准",
                "rejected": "使用者拒絕了這一張", "expired": "報價過期了，請重新報價、重新核准",
                "submitted": "這張卡已經送出過了，卡片只能用一次", "failed": "這張卡送件失敗過，請重新報價、重新核准"}
        raise ApprovalError(409, "這張卡不能送出：" + hint.get(card["status"], card["status"]))
    if expect_amount not in (None, ""):
        if _dec(expect_amount) is None or amount(card) is None or _dec(expect_amount) != amount(card):
            raise ApprovalError(409, "金額跟核准卡不一致（卡上是 %s %s）：請重新報價、重新核准"
                                % (fmt(amount(card)), "點" if measure(card["payer"]) == "points" else "AppleToken 額度"))
    used = used_today(conn, user_id, measure(card["payer"]), now)
    dec_at = _ts(card.get("decided_at"))
    if dec_at and iso(dec_at) >= day_start(now):
        used -= (amount(card) or 0)
    why = check_limits(card, limits_get(conn, user_id), used)
    if why:
        raise ApprovalError(422, why)
    if not _move(conn, user_id, cid, "approved", "submitted"):
        raise ApprovalError(409, "這張卡剛剛被送出過了")
    return get(conn, user_id, cid)

def mark_result(conn, user_id, cid, job_id=None, error=None):
    with conn.cursor() as cur:
        if error:
            cur.execute("UPDATE approval_cards SET status = 'failed', error = %s WHERE id = %s AND user_id = %s::uuid",
                        (str(error)[:500], str(cid), str(user_id)))
        else:
            cur.execute("UPDATE approval_cards SET job_id = %s WHERE id = %s AND user_id = %s::uuid",
                        (str(job_id)[:128] if job_id else None, str(cid), str(user_id)))
