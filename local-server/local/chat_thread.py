import json
import os
import re

ENV = "STUDIO_UI_V2_CHAT"
TEXT_MAX = 4000
LIST_MAX = 200
ARGS_MAX = 8
ARG_LEN = 200
_ARG_KEY = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
AUTHORS = ("human", "agent")
OFF = "對話區沒有開（STUDIO_UI_V2_CHAT=on 才有）"

class ChatError(ValueError):
    pass

def on(env=None):
    env = os.environ if env is None else env
    return str(env.get(ENV, "")).strip().lower() in ("1", "on", "true")

def clean_text(text, required=True):
    if text is None:
        text = ""
    if not isinstance(text, str):
        raise ChatError("text 要是字串")
    text = text.strip()
    if required and not text:
        raise ChatError("text 不能是空的")
    if len(text) > TEXT_MAX:
        raise ChatError("text 最多 %d 字" % TEXT_MAX)
    return text

def clean_card(card, components):
    if card is None:
        return None
    if not isinstance(card, dict):
        raise ChatError("card 要是物件 {component, args?}")
    extra = set(card) - {"component", "args"}
    if extra:
        raise ChatError("card 只收 component 與 args，不認得：%s" % "、".join(sorted(extra)))
    cid = card.get("component")
    comp = (components or {}).get(cid) if isinstance(cid, str) else None
    if not comp or comp.get("mount") != "inline":
        ok = sorted(k for k, v in (components or {}).items() if v.get("mount") == "inline")
        raise ChatError("card.component 要是元件表裡能放進卡片的其中一個：%s" % "、".join(ok))
    args = card.get("args", {})
    if args is None:
        args = {}
    if not isinstance(args, dict) or len(args) > ARGS_MAX:
        raise ChatError("card.args 要是物件、最多 %d 個鍵" % ARGS_MAX)
    for k, v in args.items():
        if not _ARG_KEY.match(k):
            raise ChatError("card.args 的鍵只收小寫英數與底線：%s" % k)
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            continue
        if not isinstance(v, str) or len(v) > ARG_LEN or "<" in v or "://" in v:
            raise ChatError("card.args.%s 要是 %d 字以內的短字串、數字或布林（不收網址、標籤）" % (k, ARG_LEN))
    return {"component": cid, "args": args}

def add(db, author, text, card=None):
    if author not in AUTHORS:
        raise ChatError("author 不對")

    def put(c, _u):
        with c.cursor() as cur:
            cur.execute("INSERT INTO local_chat_messages (author, text, card) VALUES (%s, %s, %s)",
                        (author, text, json.dumps(card, ensure_ascii=False) if card else None))
            cur.execute("SELECT id, author, text, card, created_at FROM local_chat_messages ORDER BY id DESC LIMIT 1")
            return _row(cur.fetchone())
    return db.run(put)

def listing(db, after=0, author=None, limit=LIST_MAX):
    limit = max(1, min(int(limit or LIST_MAX), LIST_MAX))

    def read(c, _u):
        with c.cursor() as cur:
            where, params = ["id > %s"], [int(after or 0)]
            if author:
                where.append("author = %s")
                params.append(author)
            cur.execute("SELECT id, author, text, card, created_at FROM local_chat_messages WHERE " + " AND ".join(where)
                        + " ORDER BY id DESC LIMIT %d" % limit, tuple(params))
            rows = [_row(r) for r in cur.fetchall()]
            cur.execute("SELECT COALESCE(MAX(id), 0) FROM local_chat_messages")
            last = cur.fetchone()[0]
        return {"messages": rows[::-1], "last_id": int(last or 0)}
    return db.run(read)

def _row(r):
    card = r[3]
    if isinstance(card, str):
        card = json.loads(card)
    return {"id": int(r[0]), "author": r[1], "text": r[2], "card": card or None, "at": r[4]}
