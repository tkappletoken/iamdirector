
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .errors import ApiError, TransportError

USER_AGENT = "appletoken-cli/0.1 (+python-urllib)"

DEFAULT_TIMEOUT = 60
RETRY_STATUSES = (500, 502, 503, 504)
RETRY_BACKOFF = (1.0, 3.0, 8.0)
RATE_LIMIT_BACKOFF = 60.0
UPSTREAM_RETRY_MAX = 3
UPSTREAM_BACKOFF = (5.0, 15.0, 45.0)
UPSTREAM_WAIT_MAX = 180.0

class _NoRedirect(urllib.request.HTTPRedirectHandler):

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class _StripAuthOnCrossHost(urllib.request.HTTPRedirectHandler):

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        if urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            for h in list(new.headers):
                if h.lower() in ("authorization", "cookie"):
                    del new.headers[h]
        return new

class Client:
    def __init__(self, session, timeout=DEFAULT_TIMEOUT, sleep=time.sleep):
        self.session = session
        self.timeout = timeout
        self._sleep = sleep
        self.last_status = None

    def get(self, path, params=None, raw=False, **kw):
        return self.request("GET", path, params=params, raw=raw, **kw)

    def post(self, path, payload=None, spending=False, **kw):
        return self.request("POST", path, payload=payload, spending=spending, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)

    def request(self, method, path, payload=None, params=None, raw=False,
                spending=False, follow_redirects=False, timeout=None,
                retry=True):
        url = self.session.base_url + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)

        retryable = retry and not spending
        attempts = len(RETRY_BACKOFF) + 1 if retryable else 1
        last = None
        upstream_tries = 0
        i = 0
        while i < attempts:
            try:
                return self._once(method, url, payload, raw, follow_redirects,
                                  timeout or self.timeout)
            except ApiError as e:
                last = e
                wait = self._upstream_wait(e, upstream_tries) if retry else None
                if wait is not None:
                    upstream_tries += 1
                    self._sleep(wait)
                    continue
                if not retryable or i == attempts - 1:
                    raise
                if e.status == 429:
                    self._sleep(RATE_LIMIT_BACKOFF)
                    i += 1
                    continue
                if e.status in RETRY_STATUSES:
                    self._sleep(RETRY_BACKOFF[i])
                    i += 1
                    continue
                raise
            except TransportError as e:
                last = e
                if not retryable or i == attempts - 1:
                    raise
                self._sleep(RETRY_BACKOFF[i])
                i += 1
        raise last

    @staticmethod
    def _upstream_wait(e, tries):
        info = getattr(e, "retry", None)
        if not info or tries >= UPSTREAM_RETRY_MAX:
            return None
        after = info.get("after")
        wait = float(after) if isinstance(after, (int, float)) and after > 0 \
            else UPSTREAM_BACKOFF[min(tries, len(UPSTREAM_BACKOFF) - 1)]
        return wait if wait <= UPSTREAM_WAIT_MAX else None

    def _once(self, method, url, payload, raw, follow_redirects, timeout):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in self.session.auth_headers().items():
            req.add_header(k, v)
        req.add_header("User-Agent", USER_AGENT)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")

        handler = _StripAuthOnCrossHost() if follow_redirects else _NoRedirect()
        opener = urllib.request.build_opener(handler)
        try:
            with opener.open(req, timeout=timeout) as r:
                self.last_status = r.status
                body = r.read()
                return body if raw else self._decode(body)
        except urllib.error.HTTPError as e:
            self.last_status = e.code
            with e:
                body = e.read()
            if e.code in (301, 302, 303, 307, 308) and not follow_redirects:
                raise ApiError(
                    e.code, "unexpected_redirect",
                    "平台回了轉址（Location: %s）。這條路徑原本預期是直接回內容，"
                    "形狀變了就該有人知道，所以這裡不自動跟隨。"
                    % (e.headers.get("Location") or "?"))
            raise ApiError.from_response(e.code, self._decode(body, soft=True))
        except urllib.error.URLError as e:
            raise TransportError("連不上 %s：%s" % (url, e.reason))
        except TimeoutError:
            raise TransportError("等 %s 逾時（%ss）" % (url, timeout))

    @staticmethod
    def _decode(body, soft=False):
        if not body:
            return {}
        try:
            return json.loads(body)
        except (ValueError, UnicodeDecodeError):
            if soft:
                return body.decode("utf-8", "replace")
            raise TransportError(
                "回應不是 JSON（前 120 bytes：%r）。取二進位內容要用 raw=True。"
                % body[:120])
