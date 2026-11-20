
from .redact import redact

_GUARD_HINTS = {
    401: ("沒有登入身分。三種可能，而 studio 對它們回同一個訊息、分不出來："
          "(1) cookie 沒帶；(2) session 過期——用本站帳號重新登入工作台並更新；"
          "(3) 手上是舊的那顆——studio 已經跟 AppleToken 切割，主站的 "
          "appletoken_session 不再有效，要用本站的 studio_session。"
          "用 at doctor 看它讀到的是哪一個。"),
    403: ("這個帳號不在創作者名單裡。studio 的門由創作者資格控管，"
          "在工作台送出申請，等平台管理後台核准（studio_access_requests）。"),
    503: "studio 那一側的服務或設定有問題（可能是會員資料庫沒設定，也可能是上游暫時不可用）。",
}

class AppleTokenError(Exception):

    def __init__(self, message):
        super().__init__(redact(str(message)))

class ConfigError(AppleTokenError):
    pass

class ValidationError(AppleTokenError):
    pass

class ApiError(AppleTokenError):

    def __init__(self, status, detail, payload=None, notes=None):
        self.status = status
        self.detail = detail
        self.payload = payload or {}
        self.notes = notes or []
        r = self.payload.get("retry") if isinstance(self.payload, dict) else None
        self.retry = r if isinstance(r, dict) and r.get("retryable") is True else None
        parts = ["HTTP %s" % status]
        if detail:
            parts.append(self._flatten(detail))
        local = isinstance(self.payload, dict) and self.payload.get("local") is True
        hint = None if local and status == 403 else _GUARD_HINTS.get(status)
        if hint:
            parts.append("→ %s" % hint)
        for n in self.notes:
            parts.append("（%s）" % n)
        super().__init__("：".join(parts[:2]) + ("  " + "  ".join(parts[2:])
                                                 if len(parts) > 2 else ""))

    @staticmethod
    def _flatten(detail):
        if isinstance(detail, str):
            return detail.strip()[:400]
        if isinstance(detail, dict):
            inner = detail.get("error") if isinstance(
                detail.get("error"), dict) else detail
            code, msg = inner.get("code"), inner.get("message")
            if code and msg:
                return "%s（%s）" % (msg, code)
            if msg or code:
                return str(msg or code)
            for k in ("detail", "reason"):
                if isinstance(inner.get(k), str):
                    return inner[k]
            return str(detail)[:400]
        return str(detail)[:400]

    @classmethod
    def from_response(cls, status, body):
        if isinstance(body, dict):
            return cls(status, body.get("error", body), body,
                       body.get("notes"))
        text = (body or "").strip() if isinstance(body, str) else ""
        if text[:1] == "<" or "<h1>" in text[:200]:
            return cls(status,
                       "studio 回了一頁 HTML 而不是 JSON——"
                       "這通常代表這條路徑不在它的白名單裡（studio 的 GET/POST 404 是 HTML）。")
        return cls(status, text[:400] or None)

class TransportError(AppleTokenError):
    pass
