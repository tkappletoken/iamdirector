import datetime
import decimal
import json
import re
import secrets

ID = re.compile(r"^apv_[A-Za-z0-9]{16,32}$")
BATCH_ID = re.compile(r"^apb_[A-Za-z0-9]{16,32}$")
QUOTE_GUESS = datetime.timedelta(minutes=10)
QUOTE_MARGIN = datetime.timedelta(seconds=30)
STATUSES = ("pending", "approved", "rejected", "expired", "submitted", "failed")
CARD_TTL = datetime.timedelta(hours=24)
TZ = datetime.timezone(datetime.timedelta(hours=8))
NOT_READY = "核准卡尚未啟用（資料庫還沒套用 034_approvals／035_approvals_async）。這段期間 Agent 不能用核准卡送件；工作台其他功能不受影響。"
COLS_035 = {"approval_cards": ("payload", "quote_expires_at", "approved_points", "approved_upstream", "batch_id", "note",
                               "decided_by"),
            "user_spend_limits": ("auto_approve", "limits_version")}
LIMIT_KEYS = ("per_job_points", "daily_points", "per_job_upstream", "daily_upstream")

_COLS = ("id", "user_id", "charge_id", "quote_ref", "kind", "payer", "points", "upstream_cost",
         "summary", "status", "token_id", "job_id", "error", "expires_at", "decided_at", "submitted_at", "created_at",
         "payload", "quote_expires_at", "approved_points", "approved_upstream", "batch_id", "note", "decided_by")

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
    out["batch_id"] = card.get("batch_id")
    out["decided_by"] = card.get("decided_by")
    out["note"] = card.get("note")
    ap = card.get("approved_points") if measure(card.get("payer")) == "points" else card.get("approved_upstream")
    out["approved_amount"] = fmt(ap) if ap is not None else None
    for k in ("expires_at", "decided_at", "submitted_at", "created_at", "quote_expires_at"):
        t = _ts(card.get(k))
        out[k] = iso(t) if t else None
    if link:
        out["approve_url"] = link
    return out

def _row(row):
    if not row:
        return None
    d = dict(zip(_COLS, row))
    for k, empty in (("summary", {}), ("payload", None)):
        if isinstance(d.get(k), str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                d[k] = empty
    return d

SEL = ("SELECT id, user_id, charge_id, quote_ref, kind, payer, points, upstream_cost, summary, status,"
       " token_id, job_id, error, expires_at, decided_at, submitted_at, created_at,"
       " payload, quote_expires_at, approved_points, approved_upstream, batch_id, note, decided_by FROM approval_cards")

def quote_expiry(sheet, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    got = _ts(sheet.get("expires_at")) if isinstance(sheet, dict) else None
    if got is None and isinstance(sheet, dict) and isinstance(sheet.get("expires_at"), (int, float)):
        got = datetime.datetime.fromtimestamp(sheet["expires_at"], datetime.timezone.utc)
    return got or (now + QUOTE_GUESS)

def quote_stale(card, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    exp = _ts(card.get("quote_expires_at"))
    return exp is None or exp - QUOTE_MARGIN <= now

def _amt(charge):
    return (str(charge["points"]) if charge.get("points") is not None else None,
            str(charge["upstream_cost"]) if charge.get("upstream_cost") is not None else None)

def create(conn, *, user_id, charge, summary, expires_at=None, token_id=None, payload=None, quote_expires_at=None):
    cid = new_id()
    now = datetime.datetime.now(datetime.timezone.utc)
    pts, up = _amt(charge)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO approval_cards (id, user_id, charge_id, quote_ref, kind, payer, points, upstream_cost,"
            " summary, status, token_id, expires_at, payload, quote_expires_at)"
            " VALUES (%s, %s::uuid, %s, %s, %s, %s, %s, %s, %s::jsonb, 'pending', %s, %s, %s::jsonb, %s)"
            " ON CONFLICT (quote_ref) DO NOTHING",
            (cid, str(user_id), str(charge["id"]) if charge.get("id") is not None else None, charge["quote_ref"],
             charge.get("kind") or "video", charge["payer"], pts, up,
             json.dumps(summary or {}, ensure_ascii=False), str(token_id) if token_id else None,
             iso(expires_at or (now + CARD_TTL)),
             json.dumps(payload, ensure_ascii=False) if payload is not None else None,
             iso(quote_expires_at) if quote_expires_at else None))
    return by_quote(conn, user_id, charge["quote_ref"])

def replace_quote(conn, user_id, cid, charge, quote_expires_at):
    pts, up = _amt(charge)
    with conn.cursor() as cur:
        cur.execute("UPDATE approval_cards SET quote_ref = %s, charge_id = %s, points = %s, upstream_cost = %s,"
                    " quote_expires_at = %s WHERE id = %s AND user_id = %s::uuid AND status = 'submitted' RETURNING id",
                    (charge["quote_ref"], str(charge["id"]) if charge.get("id") is not None else None, pts, up,
                     iso(quote_expires_at), str(cid), str(user_id)))
        return cur.fetchone() is not None

def reprice(conn, user_id, cid, charge, quote_expires_at, note):
    pts, up = _amt(charge)
    with conn.cursor() as cur:
        cur.execute("UPDATE approval_cards SET status = 'pending', quote_ref = %s, charge_id = %s, points = %s,"
                    " upstream_cost = %s, quote_expires_at = %s, note = %s, decided_at = NULL, submitted_at = NULL,"
                    " approved_points = NULL, approved_upstream = NULL"
                    " WHERE id = %s AND user_id = %s::uuid AND status = 'submitted' RETURNING id",
                    (charge["quote_ref"], str(charge["id"]) if charge.get("id") is not None else None, pts, up,
                     iso(quote_expires_at), str(note)[:500], str(cid), str(user_id)))
        return cur.fetchone() is not None

PAYLOAD_MAX = 64 * 1024
_EXPIRED_HINT = ("已過期", "expired")

def payload_for_card(body):
    if not isinstance(body, dict):
        return None
    pl = {k: v for k, v in body.items() if k not in ("payer", "approval_card", "require_confirmation", "quote_id", "confirm")}
    try:
        raw = json.dumps(pl, ensure_ascii=False)
    except (TypeError, ValueError):
        return None
    return pl if len(raw.encode("utf-8")) <= PAYLOAD_MAX else None

def err_text(x):
    for _ in range(4):
        if not isinstance(x, dict):
            break
        x = x.get("message") if "message" in x else x.get("error")
    return str(x or "")

def upstream_says_expired(code, obj):
    if code != 400 or not isinstance(obj, dict):
        return False
    return any(h in err_text(obj) for h in _EXPIRED_HINT)

def apply_requote(conn, user_id, card, charge, quote_expires_at):
    new = _dec(charge.get("points") if measure(card["payer"]) == "points" else charge.get("upstream_cost"))
    cap = approved_amount(card)
    unit = "點" if measure(card["payer"]) == "points" else "AppleToken 額度"
    if new is None or cap is None or new > cap:
        note = "價格變了：核准的是 %s %s，重新報價是 %s %s，要重新核准" % (fmt(cap), unit, fmt(new), unit)
        reprice(conn, user_id, card["id"], charge, quote_expires_at, note)
        return get(conn, user_id, card["id"]), note
    replace_quote(conn, user_id, card["id"], charge, quote_expires_at)
    return get(conn, user_id, card["id"]), None

def ids_for_batch(conn, user_id, body):
    b = body if isinstance(body, dict) else {}
    if isinstance(b.get("ids"), list):
        return [str(x) for x in b["ids"]]
    if isinstance(b.get("quote_ids"), list):
        out = []
        for q in b["quote_ids"]:
            c = by_quote(conn, user_id, str(q))
            if c is None:
                raise ApprovalError(404, "這張報價沒有核准卡（或不是你的）：%s" % q)
            out.append(c["id"])
        return out
    raise ApprovalError(400, "要給 quote_ids 或 ids（2–50 件）")

def approved_amount(card):
    v = _dec(card.get("approved_points") if measure(card.get("payer")) == "points" else card.get("approved_upstream"))
    return v if v is not None else amount(card)

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
        cur.execute("SELECT per_job_points, daily_points, per_job_upstream, daily_upstream, auto_approve, limits_version"
                    " FROM user_spend_limits WHERE user_id = %s::uuid", (str(user_id),))
        row = cur.fetchone()
    row = row or (None,) * 6
    out = {k: (fmt(v) if v is not None else None) for k, v in zip(LIMIT_KEYS, row[:4])}
    out["auto_approve"] = bool(row[4])
    out["version"] = int(row[5] or 0)
    return out

def auto_ready(lim, m):
    return bool(lim.get("auto_approve")) and lim.get("per_job_" + m) is not None and lim.get("daily_" + m) is not None

def lock_limits(conn, user_id):
    with conn.cursor() as cur:
        cur.execute("UPDATE user_spend_limits SET updated_at = updated_at WHERE user_id = %s::uuid", (str(user_id),))

_RACE_HOOK = None

def used_today_auto(conn, user_id, m, now=None):
    with conn.cursor() as cur:
        cur.execute("SELECT payer, points, upstream_cost FROM approval_cards WHERE user_id = %s::uuid"
                    " AND status IN ('approved', 'submitted') AND decided_at >= %s AND decided_by LIKE 'auto:%%'",
                    (str(user_id), day_start(now)))
        rows = cur.fetchall()
    total = decimal.Decimal(0)
    for payer, pts, up in rows:
        if measure(payer) == m:
            v = _dec(pts if m == "points" else up)
            total += v if v is not None else 0
    return total

def try_auto(conn, user_id, card, now=None):
    if card is None or card.get("status") != "pending":
        return None
    m = measure(card.get("payer"))
    lim = limits_get(conn, user_id)
    if not auto_ready(lim, m):
        return None
    lock_limits(conn, user_id)
    lim = limits_get(conn, user_id)
    if not auto_ready(lim, m):
        return None
    used = used_today(conn, user_id, m, now)
    if _RACE_HOOK:
        _RACE_HOOK()
    why = check_limits(card, lim, used)
    if why:
        with conn.cursor() as cur:
            cur.execute("UPDATE approval_cards SET note = %s WHERE id = %s AND user_id = %s::uuid AND status = 'pending'",
                        ("超過自動核准的上限，要你本人核准：" + why, str(card["id"]), str(user_id)))
        return None
    if not _move(conn, user_id, card["id"], "pending", "approved"):
        return None
    _mark_approved(conn, user_id, card["id"], card, "auto:%d" % lim["version"])
    return get(conn, user_id, card["id"])

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
    auto = (body or {}).get("auto_approve") is True
    if auto and not any(vals[i] is not None and vals[i + 1] is not None for i in (0, 2)):
        raise ApprovalError(400, "自動核准要同時設好單支上限與每日上限")
    ver = limits_get(conn, user_id)["version"] + 1
    with conn.cursor() as cur:
        cur.execute("INSERT INTO user_spend_limits (user_id, per_job_points, daily_points, per_job_upstream,"
                    " daily_upstream, auto_approve, limits_version, updated_at) VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, now())"
                    " ON CONFLICT (user_id) DO UPDATE SET per_job_points = excluded.per_job_points,"
                    " daily_points = excluded.daily_points, per_job_upstream = excluded.per_job_upstream,"
                    " daily_upstream = excluded.daily_upstream, auto_approve = excluded.auto_approve,"
                    " limits_version = excluded.limits_version, updated_at = now()",
                    (str(user_id),) + tuple(vals) + (auto, ver))
        cur.execute("UPDATE approval_cards SET status = 'pending', decided_at = NULL, decided_by = NULL,"
                    " approved_points = NULL, approved_upstream = NULL, note = %s"
                    " WHERE user_id = %s::uuid AND status = 'approved' AND decided_by LIKE 'auto:%%'",
                    ("自動核准已關閉或上限改了：這一張要你本人重新核准", str(user_id)))
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
    lock_limits(conn, user_id)
    why = check_limits(card, limits_get(conn, user_id), used_today(conn, user_id, measure(card["payer"]), now))
    if why:
        raise ApprovalError(422, why)
    if not _move(conn, user_id, cid, "pending", "approved"):
        raise ApprovalError(409, "這張卡剛剛被處理過了")
    _mark_approved(conn, user_id, cid, card, "human")
    return get(conn, user_id, cid)

def _mark_approved(conn, user_id, cid, card, by):
    pts, up = _amt(card)
    with conn.cursor() as cur:
        cur.execute("UPDATE approval_cards SET approved_points = %s, approved_upstream = %s, note = NULL, decided_by = %s"
                    " WHERE id = %s AND user_id = %s::uuid", (pts, up, str(by), str(cid), str(user_id)))

def card_or_batch(x):
    return bool(ID.match(str(x or "")) or BATCH_ID.match(str(x or "")))

def new_batch_id():
    return "apb_" + secrets.token_hex(12)

def make_batch(conn, user_id, card_ids):
    ids = list(dict.fromkeys(card_ids or []))
    if not 2 <= len(ids) <= 50:
        raise ApprovalError(400, "一批要 2–50 件")
    cards = [get(conn, user_id, c) for c in ids]
    if any(c is None for c in cards):
        raise ApprovalError(404, "有一張卡找不到（或不是你的）")
    bad = [c["id"] for c in cards if c.get("batch_id") or not (
        c["status"] == "pending" or (c["status"] == "approved" and str(c.get("decided_by") or "").startswith("auto:")))]
    if bad:
        raise ApprovalError(409, "這幾張不是等核准的卡，或已經在別的批裡：%s" % "、".join(bad))
    bid = new_batch_id()
    with conn.cursor() as cur:
        for c in ids:
            cur.execute("UPDATE approval_cards SET batch_id = %s WHERE id = %s AND user_id = %s::uuid AND status = 'pending'",
                        (bid, c, str(user_id)))
    return bid

def batch_cards(conn, user_id, bid):
    if not BATCH_ID.match(str(bid or "")):
        return []
    with conn.cursor() as cur:
        cur.execute(SEL + " WHERE batch_id = %s AND user_id = %s::uuid ORDER BY created_at", (str(bid), str(user_id)))
        return [_expire(conn, _row(r)) for r in cur.fetchall()]

def batch_public(cards, link=None, link_of=None):
    totals = {}
    for c in cards:
        m, a = measure(c["payer"]), amount(c)
        if a is not None:
            totals[m] = totals.get(m, decimal.Decimal(0)) + a
    sts = sorted({c["status"] for c in cards})
    unit = {"points": "點", "upstream": "AppleToken 額度"}
    out = {"id": cards[0]["batch_id"] if cards else None, "items": [public(c, link_of(c["id"]) if link_of else None) for c in cards],
           "totals": {k: fmt(v) for k, v in totals.items()}, "status": sts[0] if len(sts) == 1 else "mixed",
           "text": "一批 %d 件，共 %s" % (len(cards), "、".join("%s %s" % (fmt(v), unit[k]) for k, v in totals.items()) or "—")}
    if link:
        out["approve_url"] = link
    return out

def decide_batch(conn, user_id, bid, approve, now=None):
    cards = [c for c in batch_cards(conn, user_id, bid) if c["status"] == "pending"]
    if not cards:
        raise ApprovalError(404, "這一批沒有等核准的卡")
    if approve:
        lock_limits(conn, user_id)
        lim = limits_get(conn, user_id)
        for c in cards:
            why = check_limits(c, {k: v for k, v in lim.items() if k.startswith("per_job_")}, 0)
            if why:
                raise ApprovalError(422, "「%s」：%s" % ((c.get("summary") or {}).get("model") or c["id"], why))
        for m in ("points", "upstream"):
            mine = [c for c in cards if measure(c["payer"]) == m]
            if not mine:
                continue
            total = sum((amount(c) or 0) for c in mine)
            fake = {"payer": "points" if m == "points" else "own_key", "points": total, "upstream_cost": total,
                    "summary": {"open_ended": any((c.get("summary") or {}).get("open_ended") for c in mine)}}
            why = check_limits(fake, {"daily_" + m: lim.get("daily_" + m)}, used_today(conn, user_id, m, now))
            if why:
                raise ApprovalError(422, "這一批合計：" + why)
    for c in cards:
        if _move(conn, user_id, c["id"], "pending", "approved" if approve else "rejected") and approve:
            _mark_approved(conn, user_id, c["id"], c, "human")
    return batch_cards(conn, user_id, bid)

def reapply_auto(conn, user_id, cards, now=None):
    lim = limits_get(conn, user_id)
    if not (auto_ready(lim, "points") or auto_ready(lim, "upstream")):
        return cards
    done = {}
    for c in sorted([c for c in cards if c and c.get("status") == "pending"], key=lambda c: str(c.get("created_at") or "")):
        got = try_auto(conn, user_id, c, now)
        if got:
            done[c["id"]] = got
    return [done.get(c["id"], c) for c in cards]

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
    lock_limits(conn, user_id)
    by = str(card.get("decided_by") or "")
    if by.startswith("auto:"):
        lim = limits_get(conn, user_id)
        if not lim["auto_approve"] or by != "auto:%d" % lim["version"]:
            raise ApprovalError(409, "這張卡是自動核准的，但自動核准已關閉或上限改了：請使用者本人重新核准")
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
