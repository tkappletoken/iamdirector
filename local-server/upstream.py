import json
import re
import urllib.error
import urllib.request

V1_PROVIDER = "siraya"

class ConsoleError(RuntimeError):

    def __init__(self, code, body, timed_out=False, headers=None):
        super().__init__(body)
        self.code = code
        self.body = body
        self.headers = headers or {}
        self.timed_out = timed_out

UPSTREAM_HINT = ("這是平台端的上游服務暫時異常，不是你的描述或帳號設定造成的——"
                 "請稍後再試；持續發生請聯絡我們。")

RETRY_AFTER_DEFAULT = {"upstream_busy": 60, "upstream_unavailable": 300, "maintenance": 120}

def _secs(v):
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if 0 < n <= 3600 else None

def retry_info(e):
    if not isinstance(e, ConsoleError) or e.timed_out:
        return None
    inner = e.body.get("error") if isinstance(e.body, dict) else None
    inner = inner if isinstance(inner, dict) else {}
    code, why = inner.get("code"), inner.get("reason")
    after = _secs(inner.get("retry_after")) or _secs((e.headers or {}).get("retry-after"))
    if e.code == 429:
        reason = "rate_limited" if code == "rate_limited" else "upstream_busy"
    elif e.code == 503 and (code == "maintenance" or why == "maintenance"):
        reason = "maintenance"
    elif e.code == 503 and why in ("circuit_open", "upstream_unavailable"):
        reason = why
    else:
        return None
    return {"retryable": True, "after": after or RETRY_AFTER_DEFAULT.get(reason), "reason": reason}

def retry_field(e):
    info = retry_info(e)
    return {"retry": info} if info else {}

def with_hint(e):
    if isinstance(e.body, dict) and isinstance(e.body.get("error"), dict) \
            and e.body["error"].get("code") == "model_ref_required":
        return model_ref_hint(e.body)
    if e.code != 503:
        return e.body
    if isinstance(e.body, dict):
        out = dict(e.body)
        inner = out.get("error")
        if isinstance(inner, dict) and inner.get("message"):
            inner = dict(inner)
            inner["message"] = "%s（%s）" % (inner["message"], UPSTREAM_HINT)
            out["error"] = inner
        elif out.get("message"):
            out["message"] = "%s（%s）" % (out["message"], UPSTREAM_HINT)
        else:
            out["hint"] = UPSTREAM_HINT
        return out
    return "%s（%s）" % (e.body, UPSTREAM_HINT)

def model_ref_hint(body):
    inner = body.get("error") or {}
    cands = inner.get("candidates") or body.get("candidates") or []
    cands = [str(c.get("ref") or c.get("id") or "") if isinstance(c, dict) else str(c)
             for c in cands if isinstance(c, (dict, str))]
    cands = [c for c in cands if c][:6]
    msg = "上游認不得這個模型名稱，需要帶供應商前綴的完整名稱"
    msg += ("，請改用：" + "、".join(cands)) if cands else "（上游沒有給候選，請重新選一次模型）"
    out = dict(inner, message=msg, upstream_message=inner.get("message"))
    return dict(body, error=out)

class Cred:
    __slots__ = ("payer", "key")

    def __init__(self, payer, key=None):
        self.payer = payer
        self.key = key

    def __repr__(self):
        return "Cred(%s)" % self.payer

def v2_base(base):
    return re.sub(r"/v1$", "/v2", base) if base else base

SECONDS_HINT = ("seconds 必須是正數：上游不再接受 -1（帶參考影片時也一樣，報價與凍結都靠它）。"
                "這通常是舊的頁面送出來的，請重新整理後再送")

def has_video_ref(body):
    refs = body.get("input_references") if isinstance(body, dict) else None
    return isinstance(refs, list) and any(isinstance(r, dict) and r.get("type") == "video" for r in refs)

def bad_seconds(body):
    if not isinstance(body, dict) or "seconds" not in body or body["seconds"] is None:
        return False
    v = body["seconds"]
    return isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0

TTS_FIELDS = ("model", "input", "voice", "response_format", "speed")
MUSIC_FIELDS = ("model", "lyrics", "prompt", "response_format", "lyrics_optimizer")
TTS_MAX_CHARS = 4096
MODEL_ID = re.compile(r"^[A-Za-z0-9._/:-]{1,128}$")

AUDIO_MODEL_PREFIX = "gmi/"

def audio_model_ref(model):
    if isinstance(model, str) and model and "/" not in model:
        return AUDIO_MODEL_PREFIX + model
    return model

def request(base, path, key, payload=None, method=None, timeout=15.0, raw=False, meta=None,
            stream=False, user_agent="iamdirector/1.0 (+python-urllib)"):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=data,
                                 method=method or ("POST" if data else "GET"))
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("User-Agent", user_agent)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        if stream:
            return urllib.request.urlopen(req, timeout=timeout)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if meta is not None:
                meta["content_type"] = r.headers.get("Content-Type") or ""
                meta.update({k.lower(): v for k, v in r.headers.items()
                             if k.lower().startswith("x-appletoken-")})
            return r.read() if raw else json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:1200]
        try:
            body = json.loads(body)
        except ValueError:
            pass
        ra = e.headers.get("Retry-After") if e.headers is not None else None
        raise ConsoleError(e.code, body, headers={"retry-after": ra} if ra else None) from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        timed_out = isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError)
        raise ConsoleError(502, "連不上 Gateway：%s" % e, timed_out=timed_out) from None

def needs_ref(model):
    return bool(model) and "/" not in model and not model.startswith("mdl_")

def ref_from_catalog(model, listing):
    rows = listing.get("data") if isinstance(listing, dict) else None
    rows = [m for m in rows if isinstance(m, dict)] if isinstance(rows, list) else []
    if any(m.get("slug") == model for m in rows):
        return model
    for m in rows:
        p = m.get("provider") if isinstance(m.get("provider"), dict) else {}
        if m.get("family") == model and p.get("id") == V1_PROVIDER and m.get("ref"):
            return m["ref"]
    return model
