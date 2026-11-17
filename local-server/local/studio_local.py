import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import secrets
import shutil
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT, os.path.join(ROOT, "export_lambda"), os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import export_local
import export_spec
import render

if sys.platform == "darwin":
    render.FONT = "PingFang TC"
elif os.name == "nt":
    render.FONT = "Microsoft JhengHei"
else:
    render.FONT = "Noto Sans TC"

OPENH264_SO = "libopenh264.so.8"
OPENH264_SHA256 = "2f0cde7c6a6abcf5cae76942894ea42897fa677bce4ed6c91a24dd1b041d5f04"

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
import page_strip
import qc
import sqlite_store
import storyboard
import studio_store
import studio_tools
import upstream
from upstream import ConsoleError, Cred, retry_field, with_hint

DEFAULT_BASE = "https://appletoken.app/v2"
TIMEOUT = 15
GENERATE_TIMEOUT = 120
CONFIRM_BUDGET = 100
MODELS_TTL = 60.0
SB_QUOTE_TTL = 1800
QUOTE_TTL = 3600
BODY_MAX = 512 * 1024
BODY_LIMITS = {"/api/assets": 24 * 1024 * 1024, "/api/image-generate": 24 * 1024 * 1024,
               "/api/export": 24 * 1024 * 1024, "/api/local/work-import": 2 * 1024 * 1024}
MEDIA_MAX = 4 * 1024 ** 3
MEDIA_MIME = re.compile(r"^(video/(mp4|quicktime|webm)|audio/(mpeg|mp3|mp4|aac|wav|x-wav|wave|flac|ogg)"
                        r"|image/(png|jpeg|webp|gif))$")
AUDIO_REF = re.compile(r"/api/audio/content\?sha=([0-9a-f]{64})")
IMAGE_INLINE_MAX = 20 * 1024 * 1024
ORIGINAL_MAX = 20 * 1024 * 1024

ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
QID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
ASSET_ID = re.compile(r"^ast_[0-9a-f]{20}$")
ASSET_MIME = re.compile(r"^(image|video|audio)/[A-Za-z0-9.+-]{1,60}$")
PROJECT_ID = re.compile(r"^[0-9a-fA-F-]{36}$")
ASSET_URI = re.compile(r"^asset\s*:\s*/*\s*(ast_[0-9a-f]{20})$", re.I)
DATA_URI = re.compile(r"^data:([a-z]+/[A-Za-z0-9.+-]{1,60});base64,", re.I)
MANIFEST_SLOT = "<!-- STUDIO-MANIFEST -->"

CAPABILITIES = (("video", "影片"), ("image", "圖片"), ("tts", "配音"), ("music", "配樂"), ("lipsync", "對嘴"))
PROVIDED = ("video", "image", "tts", "music")
NEEDS_KEY = "還沒有可用的模型目錄：到「付款與金鑰」貼上你自己的 AppleToken 金鑰"
NO_KEY = {"error": "還沒有付款方式：請貼上你自己的 AppleToken 金鑰", "need_key": True}

LOCAL_API = (
    "/api/version", "/api/ffmpeg", "/api/me", "/api/usage",
    "/api/payer", "/api/payer/key", "/api/payer/key/delete", "/api/payer/choice",
    "/api/model-groups", "/api/estimate", "/api/generate", "/api/status", "/api/download",
    "/api/confirm-status", "/api/charges", "/api/image-generate",
    "/api/assets", "/api/assets/support", "/api/assets/content",
    "/api/storyboard/quote", "/api/storyboard", "/api/parse-shots", "/api/captions",
    "/api/store", "/api/projects", "/api/projects/create", "/api/projects/delete",
    "/api/projects/rename", "/api/projects/items",
    "/api/audio/speech", "/api/audio/music", "/api/audio/music-status", "/api/audio/music-content",
    "/api/audio/content", "/api/export", "/api/export/config", "/api/export/status", "/api/export/download",
)
_LATER = "本機模式還沒有這一項（之後的版本會補上）"
_LOGIN = "登入 iamdirector 帳號後才有這一項"
MISSING = {
    "/api/upload": "本機素材改用下方的「素材」", "/api/uploads": "本機素材改用下方的「素材」",
    "/api/image": _LATER, "/api/transcribe": _LATER, "/api/concat": _LATER,
    "/api/rates": "費率由 AppleToken 決定", "/api/timing": _LATER,
    "/api/image-outpaint": _LATER, "/api/check-asset": _LATER, "/api/check-refs": _LATER,
    "/api/post-process": _LATER, "/api/post-process-status": _LATER, "/api/post-process-content": _LATER,
    "/api/assets/delete": _LATER, "/api/assets/mirror": "本機模式只有你自己的金鑰，不需要複製素材",
    "/api/assets/uploads": _LATER, "/api/assets/uploads/complete": _LATER, "/api/assets/update": _LATER,
    "/api/qc": _LATER, "/api/qc/rate": _LATER, "/api/qc/rating": _LATER,
    "/api/archive": _LATER,
    "/api/youtube/status": _LOGIN, "/api/youtube/connect": _LOGIN, "/api/youtube/disconnect": _LOGIN,
    "/api/youtube/playlists": _LOGIN, "/api/youtube/uploads": _LOGIN,
    "/api/youtube/uploads/cancel": _LOGIN, "/api/youtube/uploads/retry": _LOGIN, "/api/youtube/auto": _LOGIN,
    "/api/pitch/platforms": _LOGIN, "/api/pitch/preview": _LOGIN, "/api/pitch/packages": _LOGIN,
    "/api/pitch/download": _LOGIN,
    "/api/wallet/balance": _LOGIN, "/api/wallet/history": _LOGIN, "/api/wallet/options": _LOGIN,
    "/api/wallet/intent": _LOGIN, "/api/wallet/subscription": _LOGIN, "/api/wallet/subscribe": _LOGIN,
    "/api/agent/tokens": _LATER, "/api/agent/tokens/revoke": _LATER, "/api/agent/tokens/update": _LATER,
    "/api/agent/activity": _LATER, "/api/agent/pending": _LATER, "/api/agent/pending/decide": _LATER,
    "/api/logout": "本機模式不用登入",
}

def last4(key):
    return key[-4:] if isinstance(key, str) and len(key) >= 8 else ""

_BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]+')

def safe_filename(name, limit=80):
    out = _BAD_NAME.sub("_", str(name or "")).strip(" .")
    out = re.sub(r"_+", "_", out)[:limit].strip(" ._")
    if out.upper().split(".")[0] in ("CON", "PRN", "AUX", "NUL") or re.match(r"(?i)^(COM|LPT)[1-9]$", out):
        out = "_" + out
    return out or "iamdirector"

def _uuid4():
    import uuid
    return str(uuid.uuid4())

class _FileResp:

    def __init__(self, f, size):
        self._f = f
        self.headers = {"Content-Length": str(size)}

    def read(self, n):
        return self._f.read(n)

    def close(self):
        self._f.close()

class State:

    def __init__(self, data_dir, base, ui_path):
        self.data_dir = data_dir
        self.base = base
        self.ui_path = ui_path
        self.token = None
        self._key = None
        self.key_verified_at = None
        self.lock = threading.Lock()
        self.db = sqlite_store.LocalDB(os.path.join(data_dir, "studio.db"))
        self.originals = os.path.join(data_dir, "originals")
        os.makedirs(self.originals, mode=0o700, exist_ok=True)
        self.models = None
        self.quotes = {}
        self.sb = {}
        self.desktop = None
        self._page = None
        self.audio = {}
        self.media = os.path.join(data_dir, "media")
        os.makedirs(self.media, mode=0o700, exist_ok=True)
        self.exports_root = os.path.join(data_dir, "exports")
        self.exports = {}
        self.export_lock = threading.Lock()
        self.ffmpeg = None
        self.ffmpeg_dir = None
        self.openh264_dir = None
        self.ffprobe = None

    def __repr__(self):
        return "State(key=%s)" % ("set" if self._key else "none")

    def key(self):
        with self.lock:
            return self._key

    def set_key(self, key):
        with self.lock:
            self._key = key or None
            self.key_verified_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) if key else None
            self.models = None

    def needs_openh264(self):
        return bool(self.ffmpeg_dir) and os.path.isfile(os.path.join(self.ffmpeg_dir, OPENH264_SO))

    def set_openh264(self, d):
        ok = isinstance(d, str) and os.path.isabs(d) and os.path.isfile(os.path.join(d, OPENH264_SO))
        try:
            ok = ok and sha256_file(os.path.join(d, OPENH264_SO)) == OPENH264_SHA256
        except OSError:
            ok = False
        with self.lock:
            self.openh264_dir = d if ok else None

    def h264_state(self):
        if not self.needs_openh264():
            return "builtin"
        return "ready" if self.openh264_dir else "download"

    def openh264_env(self):
        d = self.openh264_dir
        if not d:
            return None
        try:
            good = sha256_file(os.path.join(d, OPENH264_SO)) == OPENH264_SHA256
        except OSError:
            good = False
        if not good:
            self.set_openh264(None)
            return None
        env = dict(os.environ)
        env["LD_LIBRARY_PATH"] = d + (os.pathsep + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
        return env

    def cred(self):
        k = self.key()
        return Cred("own_key", k) if k else None

    def call(self, path, payload=None, method=None, timeout=TIMEOUT, raw=False, meta=None, stream=False, key=None):
        key = key or self.key()
        if not key:
            raise ConsoleError(409, NO_KEY)
        if isinstance(payload, dict) and isinstance(payload.get("model"), str) \
                and upstream.needs_ref(payload["model"]):
            try:
                listing, _ = self.models_cached()
                ref = upstream.ref_from_catalog(payload["model"], listing)
                if ref != payload["model"]:
                    payload = dict(payload, model=ref)
            except ConsoleError:
                pass
        return upstream.request(self.base, path, key, payload=payload, method=method, timeout=timeout,
                                raw=raw, meta=meta, stream=stream, user_agent="iamdirector-local/1.0")

    def models_cached(self):
        now = time.monotonic()
        hit = self.models
        if hit and now - hit[0] < MODELS_TTL:
            return hit[1], False
        try:
            got = upstream.request(self.base, "/models", self.key() or "", timeout=TIMEOUT,
                                   user_agent="iamdirector-local/1.0")
        except ConsoleError:
            if hit:
                return hit[1], True
            raise
        self.models = (now, got)
        return got, False

    def page(self):
        if self._page is None:
            with open(self.ui_path, encoding="utf-8") as f:
                self._page = page_strip.strip_html(f.read())
        return self._page

class Controller:

    def __init__(self, state, stdin, stdout, on_eof):
        self.state = state
        self.stdin = stdin
        self.stdout = stdout
        self.on_eof = on_eof
        self.ready = threading.Event()
        self._seq = 0
        self._wait = {}
        self._wlock = threading.Lock()

    def send(self, obj):
        with self._wlock:
            self.stdout.write(json.dumps(obj) + "\n")
            self.stdout.flush()

    def request(self, obj, timeout=10):
        ev = threading.Event()
        with self._wlock:
            self._seq += 1
            n = self._seq
            self._wait[n] = [ev, None]
        self.send(dict(obj, id=n))
        ev.wait(timeout)
        got = self._wait.pop(n, [None, None])[1]
        return got or {"ok": False, "reason": "desktop_timeout"}

    def run(self):
        for line in self.stdin:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            op = msg.get("op") if isinstance(msg, dict) else None
            if op == "init":
                tok = msg.get("token")
                if isinstance(tok, str) and len(tok) >= 32:
                    self.state.token = tok
                    k = msg.get("key")
                    self.state.set_key(k if isinstance(k, str) and k else None)
                    self.state.set_openh264(msg.get("openh264_dir"))
                    self.ready.set()
            elif op == "set_openh264":
                self.state.set_openh264(msg.get("dir"))
                if msg.get("id") is not None:
                    self.send({"op": "openh264_result", "id": msg.get("id"),
                               "ok": (self.state.openh264_dir is not None) == bool(msg.get("dir"))})
            elif op in ("store_result", "clear_result"):
                w = self._wait.get(msg.get("id"))
                if w:
                    w[1] = msg
                    w[0].set()
        self.on_eof()

class Handler(BaseHTTPRequestHandler):
    server_version = "iamdirector-local"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    state = None
    port = None

    def log_message(self, fmt, *args):
        pass

    def _gate(self):
        st = self.state
        host = (self.headers.get("Host") or "").lower()
        if host not in ("127.0.0.1:%d" % self.port, "localhost:%d" % self.port):
            return self._plain(403, "bad host")
        origin = self.headers.get("Origin")
        if origin is not None and origin not in ("http://127.0.0.1:%d" % self.port,
                                                 "http://localhost:%d" % self.port):
            return self._plain(403, "bad origin")
        got = self.headers.get("X-Local-Token") or ""
        if not st.token or not hmac.compare_digest(got.encode(), st.token.encode()):
            return self._plain(401, "missing local token")
        return True

    def _plain(self, code, text):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        return None

    def _send(self, code, body, ctype, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _err(self, e, with_hints=True, **extra):
        if e.code == 409 and isinstance(e.body, dict) and e.body.get("need_key"):
            return self._json(409, dict(e.body))
        code = e.code if 400 <= e.code < 600 else 502
        return self._json(code, dict(retry_field(e), error=with_hint(e) if with_hints else e.body, **extra))

    def _body(self, path):
        n = int(self.headers.get("Content-Length") or 0)
        if n > BODY_LIMITS.get(path, BODY_MAX):
            self._json(413, {"error": "內容太大"})
            self.close_connection = True
            return None
        raw = self.rfile.read(n) if n else b""
        try:
            got = json.loads(raw or b"{}")
        except ValueError:
            self._json(400, {"error": "body 不是 JSON"})
            return None
        if not isinstance(got, dict):
            self._json(400, {"error": "body 要是物件"})
            return None
        return got

    def _relay(self, resp, ctype, extra=None):
        try:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            cl = resp.headers.get("Content-Length")
            chunked = False
            if cl and cl.isdigit():
                self.send_header("Content-Length", cl)
            else:
                self.send_header("Transfer-Encoding", "chunked")
                chunked = True
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command == "HEAD":
                return
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                if chunked:
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                else:
                    self.wfile.write(chunk)
            if chunked:
                self.wfile.write(b"0\r\n\r\n")
        except OSError:
            self.close_connection = True
        finally:
            resp.close()

    def _workbench(self):
        st = self.state
        page = st.page()
        if MANIFEST_SLOT not in page:
            return self._plain(503, "ui2.html 裡找不到 STUDIO-MANIFEST 插槽")
        manifest = {
            "email": "", "name": "本機", "login_source": "local", "local": True,
            "has_password": False, "subscription_open": False, "points_enabled": False,
            "api_base": st.base, "api_is_public": st.base == DEFAULT_BASE,
            "api": list(LOCAL_API), "missing": dict(MISSING),
        }
        blob = json.dumps(manifest, ensure_ascii=False).replace("</", "<\\/")
        html = page.replace(MANIFEST_SLOT, "<script>window.__STUDIO__=%s;</script>" % blob, 1)
        return self._send(200, html, "text/html; charset=utf-8")

    def do_HEAD(self):
        return self.do_GET()

    def do_GET(self):
        if not self._gate():
            return
        u = parse.urlsplit(self.path)
        path, q = u.path, parse.parse_qs(u.query)
        one = lambda k: (q.get(k) or [""])[0]
        st = self.state
        if path in ("/", "/projects") or path.startswith("/w/"):
            return self._workbench()
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        if path.startswith("/previs/"):
            return self._previs(path[len("/previs/"):])
        if path == "/api/version":
            return self._json(200, {"build": hashlib.sha256(st.page().encode()).hexdigest()[:12]})
        if path == "/api/ffmpeg":
            return self._json(200, {"available": bool(studio_tools.ffmpeg_path())})
        if path == "/api/payer":
            return self._json(200, self._payer_state())
        if path == "/api/me":
            if not st.key():
                return self._json(409, {"error": "還沒有設定自己的 AppleToken 金鑰；到「付款與金鑰」貼上金鑰後，就查得到額度與用量"})
            try:
                return self._json(200, st.call("/me"))
            except ConsoleError as e:
                return self._err(e, with_hints=False)
        if path == "/api/usage":
            lim = one("limit") or "50"
            if not re.match(r"^[0-9]{1,3}$", lim) or not 1 <= int(lim) <= 500:
                return self._json(400, {"error": "limit 要在 1–500 之間"})
            try:
                return self._json(200, {"items": st.call("/usage?limit=%d" % int(lim))})
            except ConsoleError as e:
                return self._err(e, with_hints=False)
        if path == "/api/model-groups":
            return self._model_groups()
        if path == "/api/status" or path == "/api/download":
            vid = one("id")
            if not ID.match(vid):
                return self._json(400, {"error": "id 不合法"})
            if path == "/api/download":
                sha = self._job_media().get(vid)
                if sha and os.path.exists(os.path.join(st.media, sha)):
                    return self._local_file(sha)
            if not st.key():
                return self._json(404, {"error": "找不到這個任務或素材"})
            try:
                if path == "/api/status":
                    return self._json(200, st.call("/videos/" + vid))
                resp = st.call("/videos/%s/content" % vid, stream=True)
            except ConsoleError as e:
                return self._err(e, with_hints=False)
            return self._relay(resp, "video/mp4")
        if path == "/api/confirm-status":
            return self._json(404, {"error": "找不到這張報價"})
        if path == "/api/charges":
            ids = [x for x in one("ids").split(",") if x]
            if len(ids) > 100 or any(not ID.match(x) for x in ids):
                return self._json(400, {"error": "ids 不合法"})
            return self._json(200, {"items": {}, "db": False})
        if path == "/api/assets/support":
            return self._json(200, {"supported": bool(st.key())})
        if path == "/api/assets":
            qs = "&".join("%s=%s" % (k, parse.quote(one(k))) for k in ("limit", "status", "type", "tag") if one(k))
            try:
                return self._json(200, st.call("/assets" + ("?" + qs if qs else "")))
            except ConsoleError as e:
                return self._err(e, with_hints=False)
        if path == "/api/assets/content":
            aid = one("id")
            if not ASSET_ID.match(aid):
                return self._json(400, {"error": "id 不合法"})
            try:
                meta = {}
                resp = st.call("/assets/%s/content" % aid, stream=True, meta=meta)
            except ConsoleError as e:
                return self._err(e, with_hints=False)
            mime = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            mime = mime if ASSET_MIME.match(mime) else "application/octet-stream"
            extra = {"Content-Security-Policy": "sandbox"}
            if one("download") == "1":
                extra["Content-Disposition"] = 'attachment; filename="%s"' % aid
            return self._relay(resp, mime, extra)
        if path == "/api/store":
            return self._store_get(q)
        if path == "/api/audio/content":
            return self._audio_content(one("sha"))
        if path == "/api/local/work-bundle":
            return self._work_bundle(one("project_id"))
        if path == "/api/local/media":
            return self._local_media_get(one("sha"))
        if path in ("/api/audio/music-status", "/api/audio/music-content"):
            return self._music_get(path, one("id"))
        if path == "/api/export/config":
            return self._json(200, self._export_config())
        if path == "/api/export/status":
            return self._export_status(one("id"))
        if path == "/api/export/download":
            return self._export_download(one("id"))
        if path == "/api/export/file":
            return self._export_file(one("id"), one("kind"))
        if path == "/api/projects":
            return self._store(studio_store.list_projects)
        if path in MISSING:
            return self._json(501, {"error": MISSING[path]})
        return self._json(404, {"error": "沒有這個端點"})

    def do_DELETE(self):
        if not self._gate():
            return
        u = parse.urlsplit(self.path)
        if u.path != "/api/store":
            return self._json(404, {"error": "沒有這個端點"})
        key = (parse.parse_qs(u.query).get("key") or [""])[0]
        return self._store(studio_store.kv_delete, key,
                           shape=lambda r: {"ok": True, "deleted": r["deleted"]})

    def do_POST(self):
        if not self._gate():
            return
        u = parse.urlsplit(self.path)
        path = u.path
        if path == "/api/local/media":
            q = parse.parse_qs(u.query)
            return self._local_media_put((q.get("sha") or [""])[0], (q.get("mime") or [""])[0])
        body = self._body(path)
        if body is None:
            return
        st = self.state
        if path == "/api/payer/key":
            return self._payer_key(body)
        if path == "/api/payer/key/delete":
            st.set_key(None)
            if st.desktop:
                st.desktop.request({"op": "clear_key"})
            return self._json(200, dict(self._payer_state(), removed=True))
        if path == "/api/payer/choice":
            return self._json(200, self._payer_state())
        if path == "/api/estimate":
            return self._estimate(body)
        if path == "/api/generate":
            return self._generate(body)
        if path == "/api/image-generate":
            return self._image_generate(body)
        if path == "/api/assets":
            return self._asset_upload(body)
        if path == "/api/storyboard/quote":
            return self._storyboard_quote(body)
        if path == "/api/storyboard":
            return self._storyboard(body)
        if path == "/api/audio/speech":
            return self._audio(body, "tts")
        if path == "/api/audio/music":
            return self._audio(body, "music")
        if path == "/api/export":
            return self._export_start(body)
        if path == "/api/local/work-import":
            return self._work_import(body)
        if path == "/api/parse-shots":
            return self._json(200, {"shots": studio_tools.parse_shots(body.get("text") or "", body.get("model"))})
        if path == "/api/captions":
            try:
                return self._json(200, studio_tools.build_captions(body))
            except studio_tools.ApiError as e:
                return self._json(e.code, {"error": str(e)})
        if path == "/api/store":
            key = (parse.parse_qs(u.query).get("key") or [""])[0]
            if "value" not in body:
                return self._json(400, {"error": "缺少 value"})
            return self._store(studio_store.kv_put, key, body["value"],
                               shape=lambda r: {"ok": True, "bytes": r["bytes"]})
        if path == "/api/projects/create":
            name = (body.get("name") or "").strip() if isinstance(body.get("name"), str) else ""
            if not name:
                return self._json(400, {"error": "缺少 name"})
            return self._store(studio_store.create_project, name)
        if path in ("/api/projects/delete", "/api/projects/rename", "/api/projects/items"):
            pid = body.get("project_id")
            if not isinstance(pid, str) or not PROJECT_ID.match(pid):
                return self._json(400, {"error": "project_id 不合法"})
            if path == "/api/projects/delete":
                return self._store(studio_store.delete_project, pid)
            if path == "/api/projects/rename":
                return self._store(studio_store.rename_project, pid, body.get("name") or "")
            item = body.get("item_id")
            if not isinstance(item, str) or not ID.match(item):
                return self._json(400, {"error": "item_id 不合法"})
            action = body.get("action") or "add"
            if action not in ("add", "remove"):
                return self._json(400, {"error": "action 只能是 add 或 remove"})
            fn = studio_store.attach_item if action == "add" else studio_store.detach_item
            return self._store(fn, pid, item)
        if path in MISSING:
            return self._json(501, {"error": MISSING[path]})
        return self._json(404, {"error": "沒有這個端點"})

    def _store(self, fn, *args, shape=None):
        try:
            r = self.state.db.run(fn, *args)
        except studio_store.StoreError as e:
            return self._json(e.code, e.body)
        return self._json(200, shape(r) if shape else r)

    def _store_get(self, q):
        if "keys" in q:
            keys = [k for k in (q.get("keys") or [""])[0].split(",") if k]
            if not 1 <= len(keys) <= 64:
                return self._json(400, {"error": "keys 要有 1–64 個"})
            return self._store(studio_store.kv_get_many, keys, shape=lambda r: {"values": r})
        key = (q.get("key") or [""])[0]
        return self._store(studio_store.kv_get, key, shape=lambda r: {"value": r["value"]})

    def _payer_state(self):
        st = self.state
        k = st.key()
        caps = []
        for cid, label in CAPABILITIES:
            prov = ["appletoken"] if cid in PROVIDED else []
            caps.append({
                "id": cid, "label": label, "open": bool(prov), "providers": prov,
                "own_key": {"has_key": bool(k) and bool(prov), "provider": "appletoken" if k else None,
                            "last4": last4(k) if prov else "", "verified_at": st.key_verified_at,
                            "available": bool(prov)},
                "points": False, "default": "own_key" if (k and prov) else None, "last_choice": None,
            })
        return {"capabilities": caps,
                "providers": {"appletoken": {"name": "AppleToken", "capabilities": list(PROVIDED)}},
                "points": {"available": False, "reason": "本機模式不使用點數", "enabled": False,
                           "provider": "appletoken"}}

    def _payer_key(self, body):
        st = self.state
        cap = body.get("capability") or "video"
        if cap not in PROVIDED:
            return self._json(400, {"error": "「%s」還沒有可用的供應商串接" % cap})
        if (body.get("provider") or "appletoken") != "appletoken":
            return self._json(400, {"error": "目前只支援 AppleToken"})
        key = body.get("key")
        key = key.strip() if isinstance(key, str) else ""
        if not 8 <= len(key) <= 256 or re.search(r"\s", key):
            return self._json(400, {"error": "金鑰格式不對（8–256 個字元、中間不能有空白）"})
        try:
            upstream.request(st.base, "/me", key, timeout=TIMEOUT, user_agent="iamdirector-local/1.0")
        except ConsoleError as e:
            if e.code in (401, 403):
                return self._json(400, {"error": "AppleToken 不認得這把金鑰（%d），沒有儲存" % e.code})
            return self._json(502, {"error": "現在驗證不了這把金鑰（AppleToken 回 %d），沒有儲存" % e.code})
        st.set_key(key)
        stored = {"ok": False, "reason": "no_desktop"}
        if st.desktop:
            stored = st.desktop.request({"op": "store_key", "key": key})
        out = dict(self._payer_state(), persisted=bool(stored.get("persisted")))
        if not stored.get("persisted"):
            out["persist_note"] = {
                "no_keyring": "這台電腦沒有可用的系統鑰匙圈，金鑰只在這次開著時有效，關掉後要重新貼上",
                "encryption_unavailable": "系統的加密服務不能用，金鑰只在這次開著時有效",
            }.get(stored.get("reason"), "金鑰只在這次開著時有效")
        return self._json(200, out)

    def _model_groups(self):
        st = self.state
        if not st.key():
            return self._json(200, {"video": [], "image": [], "text": [], "audio": [], "model_meta": {},
                                    "fallback": True, "needs_key": True, "error_text": NEEDS_KEY})
        try:
            listing, stale = st.models_cached()
        except ConsoleError as e:
            return self._err(e, with_hints=False)
        out = studio_tools.group_models(studio_tools.catalog_from_public(listing))
        if stale:
            out = dict(out, stale=True)
        return self._json(200, out)

    def _estimate(self, body):
        body = dict(body)
        body.pop("payer", None)
        if upstream.bad_seconds(body):
            return self._json(400, {"error": upstream.SECONDS_HINT})
        try:
            r = self.state.call("/quote", payload=body)
        except ConsoleError as e:
            out = dict(retry_field(e), error=e.body)
            if e.code == 503:
                out["notes"] = [upstream.UPSTREAM_HINT]
            return self._json(e.code if 400 <= e.code < 600 else 502, out)
        out = dict(r) if isinstance(r, dict) else {"data": r}
        out["payer"] = "own_key"
        if body.get("include_video_url") or upstream.has_video_ref(body):
            out["open_ended"] = True
        return self._json(200, out)

    def _generate(self, body):
        st = self.state
        body = dict(body)
        requested = body.pop("payer", None)
        if requested not in (None, "", "own_key"):
            return self._json(409, {"error": "本機模式只能用你自己的金鑰付款"})
        if body.get("quote_id") and "confirm" in body:
            return self._confirm(str(body.get("quote_id") or "").strip(), bool(body.get("confirm")))
        if upstream.bad_seconds(body):
            return self._json(400, {"error": upstream.SECONDS_HINT})
        want_sheet = bool(body.get("require_confirmation"))
        try:
            sheet = st.call("/videos/generations", payload=dict(body, require_confirmation=True),
                            timeout=GENERATE_TIMEOUT)
        except ConsoleError as e:
            return self._err(e)
        if not (isinstance(sheet, dict) and sheet.get("quote_id") and isinstance(sheet.get("estimate"), dict)):
            out = dict(sheet) if isinstance(sheet, dict) else {"data": sheet}
            out["payer"] = "own_key"
            return self._json(200, out)
        qid = str(sheet["quote_id"])
        open_ended = upstream.has_video_ref(body)
        with st.lock:
            now = time.monotonic()
            for k in [k for k, v in st.quotes.items() if now - v["t"] > QUOTE_TTL]:
                st.quotes.pop(k, None)
            st.quotes[qid] = {"open_ended": open_ended, "status": "quoted", "t": now}
        if want_sheet:
            out = dict(sheet, payer="own_key", provider="appletoken")
            if open_ended:
                out["open_ended"] = True
                out["billing_note"] = ("帶參考影片：上游按參考影片秒數＋成品秒數計費，實際可能較高，"
                                       "從你自己的 AppleToken 額度照實際扣。")
            return self._json(200, out)
        return self._confirm(qid, True)

    def _confirm(self, qid, confirm):
        st = self.state
        if not QID.match(qid):
            return self._json(400, {"error": "quote_id 不合法"})
        with st.lock:
            q = st.quotes.get(qid)
            if q is None:
                return self._json(409, {"error": "找不到這張報價，請重新報價"})
            if q["status"] != "quoted":
                return self._json(409, {"error": "這張報價已經送出過了，不能再送一次"})
            q["status"] = "sent" if confirm else "cancelled"
        try:
            r = st.call("/videos/generations", payload={"quote_id": qid, "confirm": confirm},
                        timeout=min(GENERATE_TIMEOUT, CONFIRM_BUDGET))
        except ConsoleError as e:
            if not e.timed_out and confirm and e.code >= 400:
                with st.lock:
                    q["status"] = "quoted"
            return self._err(e)
        if not confirm:
            return self._json(200, r)
        out = dict(r) if isinstance(r, dict) else {"data": r}
        out.update(payer="own_key", provider="appletoken")
        return self._json(200, out)

    def _original(self, aid):
        p = os.path.join(self.state.originals, aid)
        try:
            with open(p + ".json", encoding="utf-8") as f:
                mime = json.load(f).get("mime") or "application/octet-stream"
            with open(p, "rb") as f:
                return f.read(), mime
        except (OSError, ValueError):
            pass
        meta = {}
        resp = self.state.call("/assets/%s/content" % aid, stream=True, meta=meta)
        try:
            raw = resp.read(ORIGINAL_MAX + 1)
            mime = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
        finally:
            resp.close()
        if len(raw) > ORIGINAL_MAX:
            raise ConsoleError(413, "參考圖 %s 超過 20MB" % aid)
        return raw, mime

    def _inline(self, send):
        refs = send.get("image")
        lst = refs if isinstance(refs, list) else [refs] if isinstance(refs, str) else []
        out, total = [], 0
        for r in lst:
            m = ASSET_URI.match(r.strip()) if isinstance(r, str) else None
            if m:
                raw, mime = self._original(m.group(1))
                r = "data:%s;base64,%s" % (mime or "application/octet-stream", base64.b64encode(raw).decode())
            total += len(r) if isinstance(r, str) else 0
            out.append(r)
        if total > IMAGE_INLINE_MAX:
            raise ConsoleError(413, "參考圖合計太大（超過 20MB）")
        if lst:
            send["image"] = out if isinstance(refs, list) else out[0]
        return send

    def _image_generate(self, body):
        st = self.state
        body = dict(body)
        body.pop("payer", None)
        try:
            send = self._inline(dict(body))
            r = st.call("/images/generations", payload=send, timeout=GENERATE_TIMEOUT)
        except ConsoleError as e:
            return self._err(e)
        out = dict(r) if isinstance(r, dict) else {"data": r}
        out["payer"] = "own_key"
        return self._json(200, out)

    def _asset_upload(self, body):
        st = self.state
        src = body.get("source")
        if not isinstance(src, str) or not src:
            return self._json(400, {"error": "缺少 source"})
        payload = {"source": src}
        for k in ("name", "type"):
            if isinstance(body.get(k), str) and body[k].strip():
                payload[k] = body[k].strip()
        if isinstance(body.get("tags"), list):
            payload["tags"] = body["tags"]
        try:
            r = st.call("/assets", payload=payload, timeout=GENERATE_TIMEOUT)
        except ConsoleError as e:
            return self._err(e, with_hints=False)
        out = dict(r) if isinstance(r, dict) else {"data": r}
        out["original"] = self._keep_original(out.get("id"), src)
        return self._json(200, out)

    def _keep_original(self, aid, src):
        m = DATA_URI.match(src)
        if not (isinstance(aid, str) and ASSET_ID.match(aid) and m):
            return "off"
        try:
            raw = base64.b64decode(src[m.end():], validate=True)
        except (ValueError, TypeError):
            return "off"
        if len(raw) > ORIGINAL_MAX:
            return "off"
        p = os.path.join(self.state.originals, aid)
        with open(p, "wb") as f:
            f.write(raw)
        with open(p + ".json", "w", encoding="utf-8") as f:
            json.dump({"mime": m.group(1), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}, f)
        return "local"

    def _storyboard_quote(self, body):
        st = self.state
        try:
            q = storyboard.check_quote(body)
        except storyboard.SBError as e:
            return self._json(e.code, {"error": str(e)})
        if not st.key():
            return self._json(409, NO_KEY)
        cap = None
        try:
            listing, _ = st.models_cached()
            entry = qc.find_entry(listing, storyboard.MODEL)
            cap = storyboard.price_cap(entry, q) if entry else None
        except ConsoleError:
            pass
        if body.get("dry_run"):
            return self._json(200, {"object": "storyboard.estimate", "payer": "own_key",
                                    "model": storyboard.MODEL, "shots": q.get("shots")})
        ref = storyboard.new_ref()
        with st.lock:
            now = time.monotonic()
            for k in [k for k, v in st.sb.items() if now - v["t"] > SB_QUOTE_TTL * 2]:
                st.sb.pop(k, None)
            st.sb[ref] = {"q": q, "t": now, "status": "quoted", "result": None}
        return self._json(200, {
            "object": "storyboard.confirmation", "status": "needs_confirmation", "quote_id": ref,
            "payer": "own_key", "model": storyboard.MODEL, "shots": q.get("shots"),
            "expires_in": SB_QUOTE_TTL,
            "estimate": {"upstream_cost_max": str(cap) if cap is not None else None},
            "note": "用你自己的 AppleToken 金鑰，AppleToken 依實際用量收費"})

    def _storyboard(self, body):
        st = self.state
        qid = body.get("quote_id")
        if not isinstance(qid, str) or not storyboard.QUOTE_ID.match(qid):
            return self._json(400, {"error": "quote_id 不合法"})
        with st.lock:
            s = st.sb.get(qid)
            if s is None:
                return self._json(409, {"error": "找不到這張報價，請重新報價"})
            if s["status"] == "done":
                return self._json(200, dict(s["result"], cached=True))
            if not body.get("confirm"):
                s["status"] = "cancelled"
                return self._json(200, {"status": "cancelled", "quote_id": qid})
            if time.monotonic() - s["t"] > SB_QUOTE_TTL:
                return self._json(409, {"error": "這張報價已逾時，請重新報價"})
            if s["status"] != "quoted":
                return self._json(409, {"error": "這張報價已經送出過了"})
            s["status"] = "running"
        q = s["q"]
        shots, usage, cost = None, {}, None
        try:
            for _ in range(2):
                resp = st.call("/chat/completions", payload=storyboard.chat_payload(q), timeout=GENERATE_TIMEOUT)
                u = resp.get("usage") if isinstance(resp, dict) and isinstance(resp.get("usage"), dict) else {}
                for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    if isinstance(u.get(k), int):
                        usage[k] = usage.get(k, 0) + u[k]
                c = qc.charged_of(resp)
                if c is not None:
                    cost = (cost or 0) + c
                shots = storyboard.parse_shots(resp, q)
                if shots:
                    break
        except ConsoleError as e:
            with st.lock:
                s["status"] = "quoted"
            if e.timed_out:
                return self._json(504, {"error": "AI 分鏡逾時，請再報價一次", "payer": "own_key", "timed_out": True})
            return self._err(e, payer="own_key")
        if not shots:
            with st.lock:
                s["status"] = "failed"
            return self._json(502, {"error": "AI 這次沒有拆出可用的分鏡（試了兩次）；用的是你自己的金鑰，"
                                             "AppleToken 可能已照用量收費，請換個說法再試",
                                    "payer": "own_key", "invalid_output": True})
        result = {"object": "storyboard.result", "quote_id": qid, "payer": "own_key",
                  "model": storyboard.MODEL, "shots": shots, "count": len(shots),
                  "total_seconds": sum(x.get("seconds") or 0 for x in shots if isinstance(x, dict))}
        if usage:
            result["usage"] = usage
        if cost is not None:
            result["upstream_cost"] = str(cost)
        with st.lock:
            s.update(status="done", result=result)
        return self._json(200, result)

    def _audio(self, body, kind):
        st = self.state
        body = dict(body)
        body.pop("payer", None)
        if body.get("quote_id"):
            return self._audio_confirm(str(body.get("quote_id") or "").strip(), bool(body.get("confirm")), kind)
        fields = upstream.TTS_FIELDS if kind == "tts" else upstream.MUSIC_FIELDS
        extra = sorted(set(body) - set(fields))
        if extra:
            return self._json(400, {"error": "%s不收這些欄位：%s" % ("配音" if kind == "tts" else "配樂", "、".join(extra))})
        if kind == "tts":
            text = body.get("input")
            if not isinstance(text, str) or not text.strip():
                return self._json(400, {"error": "缺少要念的台詞（input）"})
            if len(text) > upstream.TTS_MAX_CHARS:
                return self._json(400, {"error": "一次最多 %d 個字" % upstream.TTS_MAX_CHARS})
        if not isinstance(body.get("model"), str) or not upstream.MODEL_ID.match(body["model"]):
            return self._json(400, {"error": "缺少%s模型（model）" % ("配音" if kind == "tts" else "配樂")})
        if kind == "music" and not (isinstance(body.get("lyrics"), str) and body["lyrics"].strip()):
            return self._json(400, {"error": "缺少 lyrics（純配樂請帶 [Instrumental]）"})
        body["model"] = upstream.audio_model_ref(body["model"])
        if not st.key():
            return self._json(409, NO_KEY)
        cost, note = None, None
        try:
            q = st.call("/quote", payload=body)
            cost = q.get("est_cost", q.get("price")) if isinstance(q, dict) else None
        except ConsoleError as e:
            if 400 <= e.code < 500:
                return self._err(e)
            note = ("無法預先報價（上游這次沒回價格：%s）。確認送出後照 AppleToken 實際計費，"
                    "從你自己的 AppleToken 額度扣。" % e.code)
        ref = "au_" + secrets.token_hex(12)
        with st.lock:
            now = time.monotonic()
            for k in [k for k, v in st.audio.items() if now - v["t"] > 15 * 60]:
                st.audio.pop(k, None)
            st.audio[ref] = {"kind": kind, "payload": body, "t": now, "status": "quoted"}
        out = {"object": "audio.confirmation", "status": "needs_confirmation", "quote_id": ref, "kind": kind,
               "payer": "own_key", "provider": "appletoken",
               "estimate": {"upstream_cost": str(cost) if cost is not None else None}, "expires_in": 15 * 60}
        if kind == "tts":
            out["characters"] = len(body["input"])
        if note:
            out.update(quote_unavailable=True, note=note)
        return self._json(200, out)

    def _audio_confirm(self, qid, confirm, kind):
        st = self.state
        if not QID.match(qid):
            return self._json(400, {"error": "quote_id 不合法"})
        with st.lock:
            a = st.audio.get(qid)
            if a is None or a["kind"] != kind:
                return self._json(409, {"error": "找不到這張報價（或它已逾時），請重新報價"})
            if not confirm:
                st.audio.pop(qid, None)
                return self._json(200, {"status": "cancelled", "quote_id": qid})
            if a["status"] != "quoted":
                return self._json(409, {"error": "這張報價已經送出過了，不能再送一次"})
            if time.monotonic() - a["t"] > 15 * 60:
                st.audio.pop(qid, None)
                return self._json(409, {"error": "這張報價已逾時，請重新報價"})
            a["status"] = "sent"
        try:
            if kind == "tts":
                meta = {}
                raw = st.call("/audio/speech", payload=a["payload"], raw=True, timeout=GENERATE_TIMEOUT, meta=meta)
                if not raw:
                    return self._json(502, {"error": "上游沒回音檔", "payer": "own_key"})
                return self._json(200, {"payer": "own_key", "provider": "appletoken", "quote_id": qid,
                                        "audio": self._store_audio(raw, meta.get("content_type")),
                                        "characters": meta.get("x-appletoken-characters")})
            r = st.call("/music/generations", payload=a["payload"], timeout=GENERATE_TIMEOUT)
        except ConsoleError as e:
            return self._err(e, payer="own_key")
        if not (isinstance(r, dict) and r.get("id")) or str(r.get("status")) in ("failed", "cancelled"):
            why = (r or {}).get("status") if isinstance(r, dict) and r.get("id") else "沒回 id"
            return self._json(502, {"error": "上游沒有生成配樂（%s）" % why, "payer": "own_key"})
        out = dict(r, payer="own_key", provider="appletoken", kind="music", quote_id=qid)
        if r.get("status") == "completed":
            try:
                meta = {}
                raw = st.call("/music/%s/content" % r["id"], raw=True, timeout=GENERATE_TIMEOUT, meta=meta)
                out["audio"] = self._store_audio(raw, meta.get("content_type"))
            except ConsoleError as e:
                out["audio_error"] = str(e.body)[:200]
        return self._json(200, out)

    def _music_get(self, path, mid):
        st = self.state
        if not ID.match(mid or ""):
            return self._json(400, {"error": "id 不合法"})
        try:
            if path == "/api/audio/music-status":
                return self._json(200, st.call("/music/" + mid))
            meta = {}
            raw = st.call("/music/%s/content" % mid, raw=True, timeout=GENERATE_TIMEOUT, meta=meta)
        except ConsoleError as e:
            return self._err(e, with_hints=False)
        if not raw:
            return self._json(502, {"error": "上游沒回音檔"})
        return self._json(200, {"id": mid, "audio": self._store_audio(raw, meta.get("content_type"))})

    AUDIO_TYPES = ("audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/wave", "audio/flac",
                   "audio/ogg", "audio/aac", "audio/mp4", "application/octet-stream")

    def _store_audio(self, raw, ctype):
        mime = ((ctype or "").split(";")[0].strip().lower()) or "audio/mpeg"
        mime = mime if mime in self.AUDIO_TYPES else "application/octet-stream"
        sha = hashlib.sha256(raw).hexdigest()
        p = os.path.join(self.state.media, sha)
        if not os.path.exists(p):
            with open(p + ".part", "wb") as f:
                f.write(raw)
            os.replace(p + ".part", p)
            with open(p + ".json", "w", encoding="utf-8") as f:
                json.dump({"mime": mime, "bytes": len(raw)}, f)
        return {"mime": mime, "bytes": len(raw), "ref": "sha256:" + sha,
                "url": "/api/audio/content?sha=" + sha, "storage": "local"}

    def _audio_content(self, sha):
        if not export_spec.SHA.match(sha or ""):
            return self._json(400, {"error": "sha 不合法"})
        p = os.path.join(self.state.media, sha)
        try:
            with open(p + ".json", encoding="utf-8") as f:
                mime = json.load(f).get("mime") or "application/octet-stream"
            with open(p, "rb") as f:
                raw = f.read()
        except (OSError, ValueError):
            return self._json(404, {"error": "找不到這段音檔"})
        if hashlib.sha256(raw).hexdigest() != sha:
            return self._json(404, {"error": "找不到這段音檔"})
        return self._send(200, raw, mime)

    SRC_BUCKET, OUT_BUCKET, USER = "local-src", "local-out", "local"

    def _export_config(self):
        st = self.state
        ok = bool(st.ffmpeg and st.ffprobe)
        return {"enabled": ok, "reason": None if ok else "這台電腦找不到 ffmpeg，暫時只能在瀏覽器預覽。",
                "h264": st.h264_state(), "containers": ["mp4", "webm"] if st.needs_openh264() else ["mp4"],
                "price_points": "0", "preview": True, "aspects": list(export_spec.ASPECTS),
                "resolutions": list(export_spec.RESOLUTIONS), "fps": list(export_spec.FPS_ALLOWED),
                "subtitle_modes": list(export_spec.SUB_MODES), "max_seconds": export_spec.MAX_TOTAL}

    def _export_start(self, body):
        st = self.state
        body = dict(body)
        pid = body.pop("project_id", None)
        container = body.pop("container", None) or "mp4"
        cfg = self._export_config()
        if not cfg["enabled"]:
            return self._json(503, {"error": cfg["reason"], "preview": True})
        if container not in cfg["containers"]:
            return self._json(400, {"error": "這台電腦不支援匯出成 %s" % str(container)[:8]})
        if container == "mp4" and cfg["h264"] == "download":
            return self._json(409, {"error": "匯出 MP4 需要 H.264 編碼器", "h264_needed": True})
        try:
            req = export_spec.normalize(body)
        except export_spec.ExportError as e:
            return self._json(e.code, {"error": e.msg})
        if export_spec.refs(req) and not st.key():
            return self._json(409, NO_KEY)
        eid = "exp_" + secrets.token_hex(10)
        name = req.get("title") or self._project_name(pid) or "作品"
        job = {"id": eid, "state": "staging", "title": req.get("title") or "", "subtitles": req["subtitles"],
               "filename": safe_filename("%s-%s" % (name, time.strftime("%Y%m%d"))),
               "disclosure": bool(req["disclosure"]["on"]), "created_at": int(time.time()), "container": container}
        with st.lock:
            st.exports[eid] = job
        threading.Thread(target=self._export_run, args=(eid, req, container), daemon=True).start()
        return self._json(202, {"id": eid, "state": "staging"})

    def _project_name(self, pid):
        if not isinstance(pid, str) or not PROJECT_ID.match(pid):
            return None
        try:
            got = self.state.db.run(studio_store.list_projects)
        except studio_store.StoreError:
            return None
        return next((p["name"] for p in got["projects"] if p["id"] == pid), None)

    def _export_set(self, eid, **kw):
        with self.state.lock:
            self.state.exports[eid].update(kw)

    def _stage(self, path_up, dst, want):
        resp = self.state.call(path_up, stream=True, timeout=180)
        h = hashlib.sha256()
        try:
            with open(dst, "wb") as f:
                head = b""
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    if len(head) < export_spec.HEAD_MAX:
                        head += chunk[:export_spec.HEAD_MAX - len(head)]
                    h.update(chunk)
                    f.write(chunk)
        finally:
            resp.close()
        kind = export_spec.media_kind(head)
        if kind not in want:
            raise export_spec.ExportError(422, "%s 不是可以用的%s檔" % (os.path.basename(path_up.split("/content")[0]),
                                                                    "影片" if want == ("video",) else "影音"))
        return h.hexdigest(), kind

    def _export_run(self, eid, req, container="mp4"):
        st = self.state
        s3 = os.path.join(st.exports_root)
        src_dir = os.path.join(s3, self.SRC_BUCKET, "originals", self.USER)
        os.makedirs(src_dir, exist_ok=True)
        try:
            refs = export_spec.refs(req)
            video_keys, video_models, staged = {}, {}, 0
            total = len(refs) + len(req["audio"])
            for r in refs:
                tmp = os.path.join(src_dir, ".part-" + secrets.token_hex(6))
                if r.startswith("ast_"):
                    want = ("video",) if any(export_spec._ref(v) == r for v in req["video"]) else ("video", "audio")
                    sha, kind = self._stage("/assets/%s/content" % r, tmp, want)
                else:
                    stv = st.call("/videos/" + r)
                    if str(stv.get("status")) in ("failed", "cancelled", "canceled", "expired", "error"):
                        raise export_spec.ExportError(409, "成片 %s 生成失敗，不能匯出" % r)
                    if stv.get("model"):
                        video_models[r] = str(stv["model"])
                    sha, kind = self._stage("/videos/%s/content" % r, tmp, ("video",))
                os.replace(tmp, os.path.join(src_dir, sha))
                video_keys[r] = "originals/%s/%s" % (self.USER, sha)
                staged += 1
                self._export_set(eid, staged=staged, of=total)
            audio_keys = []
            for a in req["audio"]:
                ref = export_spec._ref(a)
                if ref:
                    audio_keys.append((video_keys[ref], "video" if not ref.startswith("ast_") else "audio"))
                else:
                    if a.get("sha"):
                        p = os.path.join(st.media, a["sha"])
                        if not os.path.exists(p):
                            raise export_spec.ExportError(404, "找不到一段配音／配樂的音檔，請重新生成那一段")
                        with open(p, "rb") as f:
                            raw = f.read()
                    else:
                        raw = base64.b64decode(a["data"].split(",", 1)[1])
                    sha = hashlib.sha256(raw).hexdigest()
                    with open(os.path.join(src_dir, sha), "wb") as f:
                        f.write(raw)
                    audio_keys.append(("originals/%s/%s" % (self.USER, sha), "audio"))
                staged += 1
                self._export_set(eid, staged=staged, of=total)
            spec = export_spec.build_spec(self.USER, eid, req, video_keys, video_models, audio_keys,
                                          self.SRC_BUCKET, self.OUT_BUCKET)
            self._export_set(eid, state="queued", models=spec["models"])
            with st.export_lock:
                self._export_set(eid, state="rendering")
                env = None
                if container == "mp4" and st.needs_openh264():
                    env = st.openh264_env()
                    if env is None:
                        raise export_spec.ExportError(409, "H.264 編碼器的檔案比對不符，已停用；請重新下載或改匯出 WebM")
                fontsdir = os.path.join(st.ffmpeg_dir, "fonts") if st.ffmpeg_dir else None
                work = tempfile.mkdtemp(prefix="iamd-export-")
                try:
                    with ffmpeg_env(env):
                        done = export_local.run(spec, s3, work, strict=False, ffmpeg=st.ffmpeg, ffprobe=st.ffprobe,
                                                fontsdir=fontsdir if fontsdir and os.path.isdir(fontsdir) else None,
                                                container=container)
                finally:
                    shutil.rmtree(work, ignore_errors=True)
            keep = ("state", "error", "duration", "bytes", "srt", "size", "warnings", "models")
            self._export_set(eid, **{k: done[k] for k in keep if k in done})
        except export_spec.ExportError as e:
            self._export_set(eid, state="failed", error=e.msg)
        except ConsoleError as e:
            self._export_set(eid, state="failed", error="取不到成片或素材（AppleToken 回 %s）" % e.code)
        except Exception as e:
            self._export_set(eid, state="failed", error="匯出失敗：%s" % type(e).__name__)

    def _export_status(self, eid):
        if not export_spec.ID.match(eid or ""):
            return self._json(400, {"error": "匯出 id 不合法"})
        with self.state.lock:
            job = self.state.exports.get(eid)
            job = dict(job) if job else None
        if not job:
            return self._json(404, {"error": "找不到這個匯出"})
        job.pop("filename", None)
        out = self._export_paths(eid, job.get("container"))[0]
        if job.get("state") == "done" and os.path.exists(out):
            job["path"] = out
        return self._json(200, job)

    def _export_paths(self, eid, container=None):
        base = os.path.join(self.state.exports_root, self.OUT_BUCKET, "exports", self.USER, eid)
        return base + "." + (container if container == "webm" else "mp4"), base + ".srt"

    def _export_download(self, eid):
        if not export_spec.ID.match(eid or ""):
            return self._json(400, {"error": "匯出 id 不合法"})
        with self.state.lock:
            job = self.state.exports.get(eid)
        if not job:
            return self._json(404, {"error": "找不到這個匯出"})
        if job.get("state") != "done":
            return self._json(409, {"error": "還沒匯出完成"})
        kind = "webm" if job.get("container") == "webm" else "mp4"
        out = {"id": eid, "expires_in": 900, "url": "/api/export/file?id=%s&kind=%s" % (eid, kind), "container": kind}
        if os.path.exists(self._export_paths(eid)[1]):
            out["srt_url"] = "/api/export/file?id=%s&kind=srt" % eid
        return self._json(200, out)

    def _export_file(self, eid, kind):
        if not export_spec.ID.match(eid or "") or kind not in ("mp4", "webm", "srt"):
            return self._json(400, {"error": "參數不合法"})
        with self.state.lock:
            job = self.state.exports.get(eid)
        if not job or job.get("state") != "done":
            return self._json(404, {"error": "找不到這個匯出"})
        if kind in ("mp4", "webm") and kind != (job.get("container") or "mp4"):
            return self._json(404, {"error": "找不到這個檔案"})
        path = self._export_paths(eid, job.get("container"))[0 if kind != "srt" else 1]
        if not os.path.exists(path):
            return self._json(404, {"error": "找不到這個檔案"})
        name = "%s.%s" % (job.get("filename") or eid, kind)
        disp = "attachment; filename=\"%s.%s\"; filename*=UTF-8''%s" % (eid, kind, parse.quote(name))
        ctype = "video/" + kind if kind != "srt" else "application/x-subrip; charset=utf-8"
        f = open(path, "rb")
        resp = _FileResp(f, os.path.getsize(path))
        return self._relay(resp, ctype, {"Content-Disposition": disp})

    @staticmethod
    def _keys_of(pid):
        p8 = pid.replace("-", "")[:8].lower()
        return {"board": "sb_" + pid.replace("-", "")[:29], "canvas": "canvas-" + p8,
                "canvas_hidden": "canvas-hidden-" + p8}

    def _job_media(self):
        try:
            return self.state.db.run(studio_store.kv_get, "job_media")["value"] or {}
        except studio_store.StoreError:
            return {}

    def _store_blob(self, raw, mime):
        mime = mime if MEDIA_MIME.match(mime or "") else "application/octet-stream"
        sha = hashlib.sha256(raw).hexdigest()
        p = os.path.join(self.state.media, sha)
        if not os.path.exists(p):
            with open(p + ".part", "wb") as f:
                f.write(raw)
            os.replace(p + ".part", p)
            with open(p + ".json", "w", encoding="utf-8") as f:
                json.dump({"mime": mime, "bytes": len(raw)}, f)
        return sha

    def _cache_job(self, job_id):
        st = self.state
        if not ID.match(job_id or ""):
            raise ConsoleError(400, "成片 id 不合法")
        known = self._job_media()
        sha = known.get(job_id)
        if sha and os.path.exists(os.path.join(st.media, sha)):
            return sha
        raw = st.call("/videos/%s/content" % job_id, raw=True, timeout=180)
        if not raw or len(raw) > MEDIA_MAX:
            raise ConsoleError(502, "成片 %s 取不回來或太大" % job_id)
        sha = self._store_blob(raw, "video/mp4")
        known[job_id] = sha
        st.db.run(studio_store.kv_put, "job_media", known)
        return sha

    def _local_file(self, sha):
        p = os.path.join(self.state.media, sha)
        try:
            with open(p + ".json", encoding="utf-8") as f:
                mime = json.load(f).get("mime") or "application/octet-stream"
        except (OSError, ValueError):
            mime = "application/octet-stream"
        f = open(p, "rb")
        return self._relay(_FileResp(f, os.path.getsize(p)), mime, {"Content-Security-Policy": "sandbox"})

    def _work_bundle(self, pid):
        st = self.state
        if not PROJECT_ID.match(pid or ""):
            return self._json(400, {"error": "project_id 不合法"})
        projects = st.db.run(studio_store.list_projects)
        proj = next((p for p in projects["projects"] if p["id"] == pid), None)
        if proj is None:
            return self._json(404, {"error": "找不到這部作品"})
        k = self._keys_of(pid)
        kv = st.db.run(studio_store.kv_get_many, ["simple_works", "jobs", k["board"], k["canvas"], k["canvas_hidden"]])
        work = (kv.get("simple_works") or {}).get(pid)
        uids = {j.get("uid") for j in ((work or {}).get("jobs") or []) if isinstance(j, dict)}
        jobs = [j for j in (kv.get("jobs") or []) if isinstance(j, dict) and j.get("uid") in uids]
        media = []
        jobs = [j for j in jobs if not j.get("id") or ID.match(str(j["id"]))]
        try:
            for j in jobs:
                if j.get("id") and j.get("status") == "completed":
                    media.append({"sha": self._cache_job(str(j["id"])), "kind": "video", "job": str(j["id"]),
                                  "mime": "video/mp4"})
        except ConsoleError as e:
            return self._json(502, {"error": "整理作品時取不回成片（AppleToken 回 %s）" % e.code})
        canvas = json.dumps(kv.get(k["canvas"]) or {})
        for sha in dict.fromkeys(AUDIO_REF.findall(canvas)):
            meta = os.path.join(st.media, sha + ".json")
            if os.path.exists(meta):
                with open(meta, encoding="utf-8") as f:
                    mime = json.load(f).get("mime") or "audio/mpeg"
                media.append({"sha": sha, "kind": "audio", "mime": mime})
        items = sorted(i for i, ps in projects["items"].items() if pid in ps)
        manifest = {"version": 1, "pid": pid, "name": proj["name"], "work": work, "jobs": jobs, "items": items,
                    "kv": {"board": kv.get(k["board"]), "canvas": kv.get(k["canvas"]),
                           "canvas_hidden": kv.get(k["canvas_hidden"])},
                    "media": media}
        return self._json(200, {"local_id": pid.replace("-", ""), "name": proj["name"], "manifest": manifest})

    def _local_media_get(self, sha):
        if not export_spec.SHA.match(sha or "") or not os.path.exists(os.path.join(self.state.media, sha)):
            return self._json(404, {"error": "本機沒有這個檔案"})
        return self._local_file(sha)

    def _local_media_put(self, sha, mime):
        n = int(self.headers.get("Content-Length") or 0)
        if not export_spec.SHA.match(sha or ""):
            return self._json(400, {"error": "sha 不合法"})
        if not 0 < n <= MEDIA_MAX:
            self.close_connection = True
            return self._json(413, {"error": "檔案是空的或太大"})
        mime = (mime or "").split(";")[0].strip().lower()
        mime = mime if MEDIA_MIME.match(mime) else "application/octet-stream"
        dest = os.path.join(self.state.media, sha)
        tmp = dest + ".part-" + secrets.token_hex(4)
        h, left = hashlib.sha256(), n
        try:
            with open(tmp, "wb") as f:
                while left:
                    block = self.rfile.read(min(left, 1024 * 1024))
                    if not block:
                        break
                    h.update(block)
                    f.write(block)
                    left -= len(block)
            if left or h.hexdigest() != sha:
                os.remove(tmp)
                self.close_connection = bool(left)
                return self._json(400, {"error": "檔案沒傳完整或內容跟 sha256 對不上"})
            if not os.path.exists(dest):
                os.replace(tmp, dest)
                with open(dest + ".json", "w", encoding="utf-8") as f:
                    json.dump({"mime": mime, "bytes": n}, f)
            else:
                os.remove(tmp)
        except OSError:
            if os.path.exists(tmp):
                os.remove(tmp)
            return self._json(500, {"error": "寫不進本機磁碟"})
        return self._json(200, {"sha": sha, "bytes": n})

    def _work_import(self, body):
        st = self.state
        man = body.get("manifest")
        if not isinstance(man, dict) or man.get("version") != 1 or not PROJECT_ID.match(str(man.get("pid") or "")):
            return self._json(400, {"error": "作品清單格式不對"})
        for m in man.get("media") or []:
            if not (isinstance(m, dict) and export_spec.SHA.match(str(m.get("sha") or ""))
                    and os.path.exists(os.path.join(st.media, m["sha"]))):
                return self._json(409, {"error": "還有媒體沒拉回本機", "missing_media": True})
        pid = man["pid"]
        name = str(man.get("name") or "雲端作品")[:50]
        if body.get("as_new"):
            pid = _uuid4()
            name = (name + "（雲端版）")[:60]
        name = st.db.run(sqlite_store.ensure_project, pid, name)
        k = self._keys_of(pid)
        kv = st.db.run(studio_store.kv_get_many, ["simple_works", "jobs", "job_media"])
        works = kv.get("simple_works") or {}
        if man.get("work") is not None:
            works[pid] = man["work"]
        st.db.run(studio_store.kv_put, "simple_works", works)
        mk = man.get("kv") if isinstance(man.get("kv"), dict) else {}
        for key in ("board", "canvas", "canvas_hidden"):
            if mk.get(key) is not None:
                st.db.run(studio_store.kv_put, k[key], mk[key])
        have = {j.get("uid") for j in (kv.get("jobs") or []) if isinstance(j, dict)}
        jobs = [j for j in (man.get("jobs") or []) if isinstance(j, dict) and j.get("uid") not in have
                and (not j.get("id") or ID.match(str(j["id"])))]
        st.db.run(studio_store.kv_put, "jobs", (jobs + list(kv.get("jobs") or []))[:60])
        jm = kv.get("job_media") or {}
        for m in man.get("media") or []:
            if m.get("job") and ID.match(str(m["job"])):
                jm[str(m["job"])] = m["sha"]
        st.db.run(studio_store.kv_put, "job_media", jm)
        for item in man.get("items") or []:
            if isinstance(item, str) and ID.match(item):
                st.db.run(studio_store.attach_item, pid, item)
        return self._json(200, {"project_id": pid, "name": name})

    PREVIS_FILES = ("editor.js", "core.js", "vendor/three.module.min.js", "vendor/OrbitControls.js",
                    "vendor/TransformControls.js", "vendor/mp4-muxer.mjs")

    def _previs(self, name):
        if name not in self.PREVIS_FILES:
            return self._json(404, {"error": "沒有這個檔案"})
        try:
            with open(os.path.join(ROOT, "previs", name), "rb") as f:
                raw = f.read()
        except OSError:
            return self._json(404, {"error": "沒有這個檔案"})
        return self._send(200, raw, "text/javascript; charset=utf-8")

_env_lock = threading.Lock()

class ffmpeg_env:

    def __init__(self, env):
        self.env, self.old = env, None

    def __enter__(self):
        if self.env is not None:
            _env_lock.acquire()
            self.old = os.environ.get("LD_LIBRARY_PATH")
            os.environ["LD_LIBRARY_PATH"] = self.env["LD_LIBRARY_PATH"]

    def __exit__(self, *exc):
        if self.env is not None:
            if self.old is None:
                os.environ.pop("LD_LIBRARY_PATH", None)
            else:
                os.environ["LD_LIBRARY_PATH"] = self.old
            _env_lock.release()

def find_ffmpeg(ffmpeg_dir=None):
    if ffmpeg_dir:
        ff, fp = os.path.join(ffmpeg_dir, "ffmpeg"), os.path.join(ffmpeg_dir, "ffprobe")
        if os.name == "nt":
            ff, fp = ff + ".exe", fp + ".exe"
        return (ff, fp) if os.path.isfile(ff) and os.path.isfile(fp) else (None, None)
    ff = shutil.which("ffmpeg")
    fp = shutil.which("ffprobe")
    return (ff, fp) if ff and fp else (None, None)

def serve(data_dir, base=DEFAULT_BASE, port=0, ui_path=None, stdin=None, stdout=None, ffmpeg_dir=None):
    os.makedirs(data_dir, mode=0o700, exist_ok=True)
    st = State(data_dir, upstream.v2_base(base.rstrip("/")), ui_path or os.path.join(ROOT, "ui2.html"))
    st.ffmpeg, st.ffprobe = find_ffmpeg(ffmpeg_dir)
    st.ffmpeg_dir = ffmpeg_dir if st.ffmpeg else None
    handler = type("LocalHandler", (Handler,), {"state": st})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    handler.port = httpd.server_address[1]
    if stdin is not None:
        ctl = Controller(st, stdin, stdout, on_eof=lambda: threading.Thread(target=httpd.shutdown, daemon=True).start())
        st.desktop = ctl
        threading.Thread(target=ctl.run, daemon=True).start()
        if not ctl.ready.wait(15):
            raise SystemExit("沒有收到桌面版的 init（權杖）")
    return httpd, st

def main(argv=None):
    ap = argparse.ArgumentParser(description="iamdirector 本機模式後端")
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--ffmpeg-dir", help="桌面版附的 ffmpeg／ffprobe 所在目錄（沒給就找系統的）")
    ap.add_argument("--gateway-base", default=DEFAULT_BASE,
                    help="AppleToken API 位址（只給測試用假上游；不是 https 時只收 127.0.0.1）")
    a = ap.parse_args(argv)
    base = a.gateway_base.rstrip("/")
    u = parse.urlsplit(base)
    if not (u.scheme == "https" or (u.scheme == "http" and u.hostname == "127.0.0.1")):
        raise SystemExit("--gateway-base 只接受 https 或 http://127.0.0.1")
    httpd, st = serve(a.data_dir, base, a.port, stdin=sys.stdin, stdout=sys.stdout, ffmpeg_dir=a.ffmpeg_dir)
    st.desktop.send({"ready": True, "port": httpd.server_address[1]})
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()

if __name__ == "__main__":
    main()
