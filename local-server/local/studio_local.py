import argparse
import datetime
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import secrets
import shutil
import subprocess
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
import approvals
import templates
import twist
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
IMAGE_TIMEOUT = 610
IMAGE_TIMEOUTS_KEPT = 50
CONCAT_MAX = 30
CONCAT_NAME = re.compile(r"(?:^|/)download\?id=([A-Za-z0-9_-]{1,64})$")
CONCAT_FILE = re.compile(r"([A-Za-z0-9_-]{1,64})\.mp4")
CAST_IMAGE_DEFAULT = "gpt-image-2"
ASR_DEFAULT = "qwen3-asr-flash"
ASR_MAX = 10 * 1024 * 1024
IMAGE_MAGIC = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF8", "image/gif"))
JOB_SRC = re.compile(r"^/api/download\?id=([A-Za-z0-9_-]{1,64})$")
SHA_SRC = re.compile(r"^/api/(?:audio/content|local/media)\?sha=([0-9a-f]{64})$")
CONFIRM_BUDGET = 100
MODELS_TTL = 60.0
SB_QUOTE_TTL = 1800
QUOTE_TTL = 3600
BODY_MAX = 512 * 1024
DRAIN_MAX = 64 * 1024 * 1024
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
    "/api/image", "/api/transcribe",
    "/api/check-refs",
    "/api/concat",
    "/api/assets", "/api/assets/support", "/api/assets/content",
    "/api/storyboard/quote", "/api/storyboard", "/api/parse-shots", "/api/captions",
    "/api/store", "/api/projects", "/api/projects/create", "/api/projects/delete",
    "/api/projects/rename", "/api/projects/items",
    "/api/audio/speech", "/api/audio/music", "/api/audio/music-status", "/api/audio/music-content",
    "/api/audio/content", "/api/export", "/api/export/config", "/api/export/status", "/api/export/download",
    "/api/approvals", "/api/approvals/decide", "/api/approvals/submit", "/api/approvals/limits",
    "/api/works/create", "/api/local/mcp", "/api/local/mcp-token", "/api/local/result",
    "/api/works/quote", "/api/works/export", "/api/twist",
)

AGENT_ALLOWED = {
    ("GET", "/api/version"), ("GET", "/api/model-groups"), ("GET", "/api/status"), ("GET", "/api/me"),
    ("GET", "/api/usage"), ("GET", "/api/payer"), ("GET", "/api/projects"), ("GET", "/api/store"),
    ("GET", "/api/charges"), ("GET", "/api/confirm-status"), ("GET", "/api/approvals"),
    ("GET", "/api/approvals/limits"), ("GET", "/api/local/result"), ("GET", "/api/ffmpeg"),
    ("POST", "/api/generate"), ("POST", "/api/estimate"), ("POST", "/api/approvals/submit"),
    ("POST", "/api/works/create"), ("POST", "/api/parse-shots"), ("POST", "/api/check-refs"), ("POST", "/mcp"),
    ("POST", "/api/works/quote"), ("POST", "/api/works/export"), ("GET", "/api/twist"), ("GET", "/api/export/status"),
}
MCP_PACKAGE_FILES = (
    "cli/appletoken/__init__.py",
    "cli/appletoken/core/__init__.py", "cli/appletoken/core/api.py", "cli/appletoken/core/errors.py",
    "cli/appletoken/core/http.py", "cli/appletoken/core/poll.py", "cli/appletoken/core/preflight.py",
    "cli/appletoken/core/redact.py", "cli/appletoken/core/session.py",
    "cli/appletoken/mcp/__init__.py", "cli/appletoken/mcp/activity.py", "cli/appletoken/mcp/tools.py",
)
AGENT_TOKEN_PREFIX = "iadl_"
MCP_FILE = "mcp.json"
JOB_ID_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_LATER = "本機模式還沒有這一項（之後的版本會補上）"
_LOGIN = "登入 iamdirector 帳號後才有這一項"
MISSING = {
    "/api/upload": "本機素材改用下方的「素材」", "/api/uploads": "本機素材改用下方的「素材」",
    "/api/rates": "費率由 AppleToken 決定", "/api/timing": _LATER,
    "/api/image-outpaint": _LATER, "/api/check-asset": _LATER,
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
        self.agent_loop = secrets.token_urlsafe(32)
        self.mcp_token = None
        self.mcp_path = os.path.join(data_dir, MCP_FILE)
        self.sb = {}
        self.desktop = None
        self._page = None
        self.audio = {}
        self.media = os.path.join(data_dir, "media")
        os.makedirs(self.media, mode=0o700, exist_ok=True)
        self.exports_root = os.path.join(data_dir, "exports")
        self.exports = {}
        self.export_lock = threading.Lock()
        self.media_lock = threading.Lock()
        self.landing = {}
        self.ffmpeg = None
        self.ffmpeg_dir = None
        self.openh264_dir = None
        self.ffprobe = None

    def __repr__(self):
        return "State(key=%s)" % ("set" if self._key else "none")

    def mcp_setup(self, port, regenerate=False):
        tok = None
        if not regenerate:
            try:
                with open(self.mcp_path, encoding="utf-8") as f:
                    got = json.load(f).get("token")
                if isinstance(got, str) and got.startswith(AGENT_TOKEN_PREFIX) and len(got) >= 40:
                    tok = got
            except (OSError, ValueError, AttributeError):
                tok = None
        tok = tok or AGENT_TOKEN_PREFIX + secrets.token_urlsafe(32)
        data = json.dumps({"url": "http://127.0.0.1:%d/mcp" % port, "token": tok,
                           "note": "iamdirector 桌面版本機 MCP 的連線設定。權杖等同可以替你報價、送出你核准過的卡，不要分享。"},
                          ensure_ascii=False, indent=2)
        tmp = self.mcp_path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.mcp_path)
        with self.lock:
            self.mcp_token = tok
        return tok

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

MCP_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MCP_INSTRUCTIONS = (
    "這是「我是導演」桌面版（本機模式）的 MCP。花錢的規則：先 quote（免費，同時建一張核准卡），"
    "把 approval.approve_url（iamdirector://approve/<id>）交給使用者，等他本人在 App 裡按核准——你自己核准不了。"
    "核准之後用 submit_approved 送出；卡片只能用一次，失敗不要自動重試，要重做就重新 quote。"
    "status 查進度（排隊再久都不是失敗），result 拿成品在這台電腦上的路徑。付款方一律是使用者自己的 AppleToken 額度。")

def _rpc_err(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

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
        self.who = None
        if st.token and got and hmac.compare_digest(got.encode(), st.token.encode()):
            self.who = "human"
            return True
        auth = self.headers.get("Authorization") or ""
        bearer = auth[7:].strip() if auth.startswith("Bearer ") else ""
        path = parse.urlsplit(self.path).path
        if bearer and hmac.compare_digest(bearer.encode(), st.agent_loop.encode()):
            self.who = "agent"
        elif bearer and path == "/mcp" and st.mcp_token and hmac.compare_digest(bearer.encode(), st.mcp_token.encode()):
            self.who = "agent"
        else:
            return self._plain(401, "missing local token")
        if (self.command if self.command != "HEAD" else "GET", path) not in AGENT_ALLOWED:
            return self._json(403, {"error": "本機的 Agent 只能報價、查詢、建作品和送出已核准的卡；"
                                             "核准、設上限、換金鑰要你本人在 App 裡操作"})
        return True

    def _human(self):
        return getattr(self, "who", None) == "human"

    def _drain(self):
        if getattr(self, "_req_seen", None) is self.raw_requestline:
            return
        self._req_seen = self.raw_requestline
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            self.close_connection = True
            return
        if n <= 0:
            return
        if n > DRAIN_MAX:
            self.close_connection = True
            return
        conn = getattr(self, "connection", None)
        try:
            if conn is not None:
                conn.settimeout(10)
            left = n
            while left > 0:
                chunk = self.rfile.read(min(left, 64 * 1024))
                if not chunk:
                    break
                left -= len(chunk)
            if left > 0:
                self.close_connection = True
        except OSError:
            self.close_connection = True
        finally:
            if conn is not None:
                try:
                    conn.settimeout(None)
                except OSError:
                    pass

    def _mark_read(self):
        self._req_seen = self.raw_requestline

    def _plain(self, code, text):
        self._drain()
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
        self._drain()
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
        self._mark_read()
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
        web = os.environ.get("STUDIO_PUBLIC_ORIGIN", "").strip().rstrip("/")
        if re.match(r"^https?://[A-Za-z0-9.:-]+$", web):
            manifest["web_origin"] = web
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
        if path in ("/", "/projects") or path.startswith("/w/") or \
                (path.startswith("/approve/") and approvals.ID.match(path[len("/approve/"):])):
            return self._workbench()
        if path == "/api/approvals":
            return self._approvals_get(one("id"), one("quote_id"), one("status"))
        if path == "/api/approvals/limits":
            return self._approvals_limits(None)
        if path == "/api/local/mcp":
            tok = st.mcp_token or ""
            return self._json(200, {"url": "http://127.0.0.1:%d/mcp" % self.port, "file": st.mcp_path,
                                    "token_tail": tok[-4:] if tok else None})
        if path == "/api/local/result":
            return self._local_result(one("id"))
        if path == "/api/twist":
            return self._twist(one("job"))
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        if path.startswith("/previs/"):
            return self._previs(path[len("/previs/"):])
        if path == "/api/version":
            return self._json(200, {"build": hashlib.sha256(st.page().encode()).hexdigest()[:12]})
        if path == "/api/ffmpeg":
            return self._json(200, {"available": bool(st.ffmpeg and st.ffprobe)})
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
                    s = st.call("/videos/" + vid)
                    if isinstance(s, dict) and s.get("status") == "completed":
                        self._land_later(vid)
                    return self._json(200, s)
                return self._local_file(self._cache_job(vid))
            except ConsoleError as e:
                return self._err(e, with_hints=False)
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
            extra = {"Content-Security-Policy": "sandbox"}
            if one("download") == "1":
                extra["Content-Disposition"] = 'attachment; filename="%s"' % aid
            local = os.path.join(st.originals, aid)
            if os.path.exists(local):
                try:
                    with open(local + ".json", encoding="utf-8") as f:
                        mime = json.load(f).get("mime") or ""
                except (OSError, ValueError):
                    mime = ""
                mime = mime if ASSET_MIME.match(mime) else "application/octet-stream"
                return self._send_file(local, mime, extra)
            try:
                meta = {}
                resp = st.call("/assets/%s/content" % aid, stream=True, meta=meta)
            except ConsoleError as e:
                return self._err(e, with_hints=False)
            mime = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            mime = mime if ASSET_MIME.match(mime) else "application/octet-stream"
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
        if path == "/mcp":
            return self._mcp(body)
        if path == "/api/approvals/decide":
            if not self._human():
                return self._json(403, {"error": "核准要你本人在 App 裡按"})
            return self._approvals_run(lambda c, u: approvals.public(approvals.decide(c, u, body.get("id"), bool(body.get("approve")))))
        if path == "/api/approvals/limits":
            if not self._human():
                return self._json(403, {"error": "上限要你本人在 App 裡設"})
            return self._approvals_limits(body)
        if path == "/api/approvals/submit":
            return self._approval_submit(body)
        if path == "/api/works/create":
            if body.get("template"):
                try:
                    tp = templates.build(body["template"], body.get("fields") or {})
                except templates.TemplateError as e:
                    return self._json(e.code, {"error": e.msg})
                meta = {"template": tp["template"], "fields": tp["fields"]}
                if body.get("dry_run"):
                    return self._json(200, {"template": tp["template"], "prompt": tp["prompt"], "seconds": tp["seconds"],
                                            "shot": tp["shot"], "post": tp["post"]})
                return self._store(studio_store.create_work, body.get("name"),
                                   [{"prompt": tp["prompt"], "seconds": tp["seconds"]}], meta)
            shots = body.get("shots")
            if shots is None and isinstance(body.get("script"), str):
                shots = studio_tools.parse_shots(body["script"], body.get("model"))
            return self._store(studio_store.create_work, body.get("name"), shots)
        if path == "/api/works/quote":
            tp = self._work_template(body.get("project_id"))
            if not isinstance(tp, dict):
                return tp
            return self._generate(dict(tp["shot"], require_confirmation=True, approval_card=True))
        if path == "/api/works/export":
            return self._work_export(body)
        if path == "/api/local/mcp-token":
            if not self._human():
                return self._json(403, {"error": "權杖要你本人在 App 裡重新產生"})
            tok = st.mcp_setup(self.port, regenerate=True)
            return self._json(200, {"ok": True, "file": st.mcp_path, "token_tail": tok[-4:],
                                    "message": "已重新產生，舊的權杖立刻失效。把新的連線檔重新設定給你的 Agent。"})
        if path == "/api/image-generate":
            return self._image_generate(body)
        if path == "/api/assets":
            return self._asset_upload(body)
        if path == "/api/image":
            return self._cast_image(body)
        if path == "/api/concat":
            return self._concat(body)
        if path == "/api/check-refs":
            refs = body.get("input_references")
            return self._json(200, studio_tools.check_references(body.get("model"), refs if isinstance(refs, list) else []))
        if path == "/api/transcribe":
            return self._transcribe(body)
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
                "sources": [{"id": "appletoken", "name": "AppleToken", "has_key": bool(k),
                             "last4": last4(k) if k else "", "verified_at": st.key_verified_at,
                             "available": True}],
                "payer_choice": {"value": "own_key" if k else None, "mixed": False},
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
        want_card = bool(body.pop("approval_card", False))
        if body.get("quote_id") and "confirm" in body:
            if not self._human() and body.get("confirm"):
                return self._json(409, {"error": "本機的 Agent 不能直接確認：用 quote 建核准卡，使用者核准後用 submit_approved 送出"})
            return self._confirm(str(body.get("quote_id") or "").strip(), bool(body.get("confirm")))
        if not self._human():
            if not body.get("require_confirmation"):
                return self._json(403, {"error": "本機的 Agent 只能報價（require_confirmation）"})
            want_card = True
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
        cost = (sheet.get("estimate") or {}).get("points")
        try:
            st.db.run(lambda c, u: c.cursor().execute(
                "INSERT INTO local_quotes (quote_id, payload, upstream_cost) VALUES (%s, %s, %s) ON CONFLICT (quote_id) DO NOTHING",
                (qid, json.dumps({"open_ended": open_ended}), str(cost) if cost is not None else None)))
        except Exception:
            pass
        if want_sheet:
            out = dict(sheet, payer="own_key", provider="appletoken")
            if want_card:
                out["approval"] = self._card_for_quote(qid, cost, open_ended, body, sheet)
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
        if confirm and not getattr(self, "_via_card", False):
            try:
                carded = st.db.run(lambda c, u: approvals.by_quote(c, u, qid)) is not None
            except Exception:
                carded = False
            if carded:
                return self._json(409, {"error": "這張報價有核准卡：在卡片上按核准之後用 submit_approved 送出"})
        with st.lock:
            q = st.quotes.get(qid)
        if q is None:
            q = self._restore_quote(qid)
        with st.lock:
            q = st.quotes.get(qid) or q
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

    def _restore_quote(self, qid):
        def get(c, u):
            with c.cursor() as cur:
                cur.execute("SELECT payload FROM local_quotes WHERE quote_id = %s", (qid,))
                return cur.fetchone()
        try:
            row = self.state.db.run(get)
        except Exception:
            row = None
        if not row:
            return None
        pl = row[0] if isinstance(row[0], dict) else {}
        q = {"open_ended": bool(pl.get("open_ended")), "status": "quoted", "t": time.monotonic()}
        with self.state.lock:
            self.state.quotes.setdefault(qid, q)
        return q

    def _card_link(self, cid):
        return "iamdirector://approve/%s" % cid

    def _card_for_quote(self, qid, cost, open_ended, body, sheet):
        exp = datetime.datetime.now(datetime.timezone.utc) + approvals.CARD_TTL
        q_exp = approvals._ts(sheet.get("expires_at")) if isinstance(sheet, dict) else None
        if q_exp and q_exp < exp:
            exp = q_exp
        charge = {"id": None, "quote_ref": qid, "kind": "video", "payer": "own_key", "points": None, "upstream_cost": cost}
        summ = dict(approvals.summary_of(body), **({"open_ended": True} if open_ended else {}))
        try:
            card = self.state.db.run(lambda c, u: approvals.create(c, user_id=u, charge=charge, summary=summ, expires_at=exp))
        except Exception as e:
            return {"enabled": False, "error": "核准卡建不起來（%s），請重新報價" % type(e).__name__}
        return dict(approvals.public(card, self._card_link(card["id"])), enabled=True)

    def _approvals_run(self, fn):
        try:
            return self._json(200, self.state.db.run(fn))
        except approvals.ApprovalError as e:
            return self._json(e.code, {"error": e.message})

    def _approvals_get(self, cid, qref, status):
        def go(c, u):
            if cid or qref:
                card = approvals.get(c, u, cid) if cid else approvals.by_quote(c, u, qref)
                if not card:
                    raise approvals.ApprovalError(404, "找不到這張核准卡")
                return approvals.public(card, self._card_link(card["id"]))
            if status and status not in approvals.STATUSES:
                raise approvals.ApprovalError(400, "status 不合法")
            return {"items": [approvals.public(x, self._card_link(x["id"])) for x in approvals.list_cards(c, u, status or None)]}
        return self._approvals_run(go)

    def _approvals_limits(self, body):
        def go(c, u):
            lim = approvals.limits_set(c, u, body) if body is not None else approvals.limits_get(c, u)
            return dict(lim, used_today_points=approvals.fmt(approvals.used_today(c, u, "points")),
                        used_today_upstream=approvals.fmt(approvals.used_today(c, u, "upstream")))
        return self._approvals_run(go)

    def _approval_submit(self, body):
        st = self.state
        try:
            card = st.db.run(lambda c, u: approvals.claim_for_submit(c, u, body.get("id"), body.get("expect_amount")))
        except approvals.ApprovalError as e:
            return self._json(e.code, {"error": e.message})
        sent = {}

        def capture(code, obj):
            sent["code"], sent["obj"] = code, obj

        self._json = capture
        self._via_card = True
        try:
            self._confirm(card["quote_ref"], True)
        finally:
            del self._json
            self._via_card = False
        code, obj = sent.get("code", 500), sent.get("obj") or {"error": "送件沒有回應"}
        ok = 200 <= code < 300
        jid = obj.get("id") if isinstance(obj, dict) else None
        card = st.db.run(lambda c, u: (approvals.mark_result(c, u, card["id"], job_id=jid) if ok else
                                      approvals.mark_result(c, u, card["id"], error=(obj or {}).get("error") or "HTTP %s" % code),
                                      approvals.get(c, u, card["id"]))[1])
        out = dict(obj) if isinstance(obj, dict) else {"data": obj}
        out["approval"] = approvals.public(card, self._card_link(card["id"]))
        return self._json(code, out)

    def _work_template(self, pid):
        if not isinstance(pid, str) or not PROJECT_ID.match(pid):
            return self._json(400, {"error": "project_id 不合法"})
        try:
            meta = self.state.db.run(lambda c, u: studio_store.work_meta(c, u, pid))
            return templates.build(meta.get("template"), meta.get("fields") or {})
        except studio_store.StoreError as e:
            return self._json(e.code, e.body)
        except templates.TemplateError as e:
            return self._json(e.code, {"error": e.msg})

    def _twist(self, jid):
        st = self.state
        if not JOB_ID_OK.match(jid or ""):
            return self._json(400, {"error": "job id 不合法"})
        if not st.ffmpeg:
            return self._json(409, {"error": "這台找不到 ffmpeg，量不了畫面變化"})
        try:
            path = os.path.join(st.media, self._cache_job(jid))
            got = twist.detect(st.ffmpeg, path, env=st.openh264_env())
        except ConsoleError as e:
            return self._err(e, with_hints=False)
        except twist.TwistError as e:
            return self._json(500, {"error": str(e)})
        got["job"] = jid
        if got["at"] is None:
            got["note"] = "找不到明顯的反轉點：匯出時請手動指定 twist.at（第幾秒）"
        return self._json(200, got)

    def _work_export(self, body):
        tp = self._work_template(body.get("project_id"))
        if not isinstance(tp, dict):
            return tp
        jid = body.get("job_id")
        if not isinstance(jid, str) or not JOB_ID_OK.match(jid):
            return self._json(400, {"error": "job_id 不合法"})
        post = dict(tp["post"])
        ov = body.get("overrides") or {}
        if not isinstance(ov, dict) or any(k not in ("captions", "effects", "twist") for k in ov):
            return self._json(400, {"error": "overrides 只收 captions／effects／twist"})
        post.update(ov)
        req = {"project_id": body.get("project_id"), "format": post["format"],
               "video": [{"job": jid, "in": 0, "out": float(tp["seconds"])}], "audio": [{"lane": "A1", "job": jid, "at": 0, "in": 0,
               "dur": float(tp["seconds"])}], "cues": [], "subtitles": "none", "disclosure": {"on": False},
               "captions": post["captions"], "effects": post["effects"], "twist": post["twist"]}
        return self._export_start(req)

    def _local_result(self, jid):
        if not JOB_ID_OK.match(jid or ""):
            return self._json(400, {"error": "job id 不合法"})
        try:
            name = self._cache_job(jid)
        except ConsoleError as e:
            return self._err(e, with_hints=False)
        return self._json(200, {"path": os.path.join(self.state.media, name), "src": "/api/download?id=" + jid})

    def _mcp(self, payload):
        if isinstance(payload, list):
            if not payload or len(payload) > 10 or sum(1 for m in payload if isinstance(m, dict) and m.get("method") == "tools/call") > 1:
                return self._json(400, _rpc_err(None, -32600, "批次最多 10 則、其中最多 1 個 tools/call"))
            outs = [r for r in (self._mcp_one(m) for m in payload) if r is not None]
            return self._json(200, outs) if outs else self._send(202, b"", "application/json")
        out = self._mcp_one(payload)
        return self._send(202, b"", "application/json") if out is None else self._json(200, out)

    def _mcp_registry(self):
        cli = os.path.join(ROOT, "cli")
        if cli not in sys.path:
            sys.path.insert(0, cli)
        from appletoken.core import Client
        from appletoken.core.session import Session
        from appletoken.mcp import tools as mtools
        sess = Session(self.state.agent_loop, base_url="http://127.0.0.1:%d" % self.port, kind="token",
                       source="local-mcp", register=False)
        sess.public_url = sess.base_url
        return mtools, mtools.Registry(sess, allow_spend=True, allow_delete=False, allow_topup=False,
                                       allow_logout=False, max_spend_points=None,
                                       client=Client(sess, timeout=150), remote=True, local=True)

    def _mcp_one(self, msg):
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            return _rpc_err(msg.get("id") if isinstance(msg, dict) else None, -32600, "不是合法的 JSON-RPC 2.0 請求")
        mid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
        if method.startswith("notifications/") or "id" not in msg:
            return None
        if method == "initialize":
            want = params.get("protocolVersion") if isinstance(params, dict) else None
            ver = want if want in MCP_VERSIONS else MCP_VERSIONS[0]
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": ver, "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "iamdirector-local", "version": "dev"}, "instructions": MCP_INSTRUCTIONS}}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": mid, "result": {}}
        if method not in ("tools/list", "tools/call"):
            return _rpc_err(mid, -32601, "不支援的方法：%s" % method)
        try:
            mtools, reg = self._mcp_registry()
        except ImportError:
            return _rpc_err(mid, -32603, "這個版本沒有附 MCP 工具（cli/appletoken 沒有打包進來）")
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [
                {"name": t.name, "description": t.description, "inputSchema": t.schema}
                for t in sorted(reg.list_tools(), key=lambda t: t.name)]}}
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return _rpc_err(mid, -32602, "tools/call 要有 name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return _rpc_err(mid, -32602, "arguments 要是物件")
        try:
            out = reg.call(params["name"], args)
            bad = isinstance(out, dict) and "error" in out
        except Exception as e:
            out, bad = {"error": str(e) or type(e).__name__}, True
        text = json.dumps(out, ensure_ascii=False, default=str).replace(self.state.agent_loop, "…")
        res = {"content": [{"type": "text", "text": text}], "isError": bool(bad)}
        if isinstance(out, dict) and not bad:
            res["structuredContent"] = json.loads(text)
        return {"jsonrpc": "2.0", "id": mid, "result": res}

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
        started = int(time.time())
        try:
            send = self._inline(dict(body))
            r = st.call("/images/generations", payload=send, timeout=IMAGE_TIMEOUT)
        except ConsoleError as e:
            if e.timed_out or e.code == 504:
                return self._image_lost(body, started)
            return self._err(e)
        out = dict(r) if isinstance(r, dict) else {"data": r}
        out["payer"] = "own_key"
        return self._json(200, out)

    def _cast_image(self, body):
        st = self.state
        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return self._json(400, {"error": "先寫外觀描述，或寫要生什麼"})
        n = body.get("n") if isinstance(body.get("n"), int) and 1 <= body.get("n") <= 4 else 1
        model = body.get("model") if isinstance(body.get("model"), str) and body["model"].strip() else CAST_IMAGE_DEFAULT
        name = str(body.get("name") or "ref").strip()[:60] or "ref"
        send = {"model": model.strip(), "prompt": prompt.strip(), "n": n, "response_format": "b64_json"}
        started = int(time.time())
        try:
            r = st.call("/images/generations", payload=send, timeout=IMAGE_TIMEOUT)
        except ConsoleError as e:
            if e.timed_out or e.code == 504:
                return self._image_lost(send, started)
            return self._err(e)
        items = r.get("data") if isinstance(r, dict) else None
        if not isinstance(items, list) or not items:
            return self._json(502, {"error": "上游沒有回圖片"})
        out = []
        try:
            for i, it in enumerate(items[:n]):
                raw = None
                if isinstance(it, dict) and isinstance(it.get("b64_json"), str):
                    raw = base64.b64decode(it["b64_json"])
                elif isinstance(r.get("id"), str) and ID.match(r["id"]):
                    raw = st.call("/images/%s/content/%d" % (r["id"], i), raw=True, timeout=60)
                if not raw or len(raw) > ORIGINAL_MAX:
                    continue
                mime = next((m for sig, m in IMAGE_MAGIC if raw.startswith(sig)),
                            "image/webp" if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP" else "")
                if not mime:
                    continue
                src = "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode())
                a = st.call("/assets", payload={"source": src, "name": "%s-%d" % (name, i + 1)},
                            timeout=GENERATE_TIMEOUT)
                aid = a.get("id") if isinstance(a, dict) else None
                if not (isinstance(aid, str) and ASSET_ID.match(aid)):
                    continue
                self._keep_original(aid, src)
                out.append({"id": aid, "ref": a.get("reference") or "asset://" + aid,
                            "src": "/api/assets/content?id=" + aid})
        except (ConsoleError, ValueError) as e:
            if out:
                return self._json(200, {"images": out, "payer": "own_key", "partial": True})
            return self._err(e) if isinstance(e, ConsoleError) else self._json(502, {"error": "上游回的圖片解不開"})
        if not out:
            return self._json(502, {"error": "上游回的不是看得懂的圖片"})
        return self._json(200, {"images": out, "payer": "own_key"})

    def _transcribe(self, body):
        st = self.state
        src = body.get("src") if isinstance(body.get("src"), str) else ""
        m, ms = JOB_SRC.match(src), SHA_SRC.match(src)
        if not (m or ms):
            return self._json(400, {"error": "只能轉錄這台電腦裡的成片或音檔"})
        if not st.ffmpeg:
            return self._json(409, {"error": "轉錄要先把音軌抽出來，這台找不到 ffmpeg"})
        model = body.get("model") if isinstance(body.get("model"), str) and body["model"].strip() else ASR_DEFAULT
        try:
            sha = self._cache_job(m.group(1)) if m else ms.group(1)
        except ConsoleError as e:
            return self._err(e, with_hints=False)
        path = os.path.join(st.media, sha)
        if not os.path.exists(path):
            return self._json(404, {"error": "本機沒有這個檔案"})
        work = tempfile.mkdtemp(prefix="asr-", dir=st.data_dir)
        try:
            wav = os.path.join(work, "a.wav")
            p = subprocess.run([st.ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", path, "-vn", "-ac", "1",
                                "-ar", "16000", "-c:a", "pcm_s16le", wav], capture_output=True, timeout=120)
            if p.returncode != 0 or not os.path.exists(wav) or os.path.getsize(wav) <= 44:
                return self._json(200, {"text": "", "note": "這支沒有音軌"})
            if os.path.getsize(wav) > ASR_MAX:
                return self._json(413, {"error": "音軌太長（超過上游 10MB 的上限，約 5 分鐘）"})
            with open(wav, "rb") as f:
                data = "data:audio/wav;base64," + base64.b64encode(f.read()).decode()
        except (OSError, subprocess.SubprocessError):
            return self._json(500, {"error": "抽音軌失敗"})
        finally:
            shutil.rmtree(work, ignore_errors=True)
        try:
            r = st.call("/audio/transcriptions", payload={"model": model.strip(), "file": data,
                                                          "response_format": "json"}, timeout=GENERATE_TIMEOUT)
        except ConsoleError as e:
            return self._err(e)
        text = r.get("text") if isinstance(r, dict) else None
        return self._json(200, {"text": text if isinstance(text, str) else "", "payer": "own_key"})

    def _concat(self, body):
        st = self.state
        files = body.get("files")
        if not isinstance(files, list) or not 2 <= len(files) <= CONCAT_MAX:
            return self._json(400, {"error": "要勾 2 到 %d 支" % CONCAT_MAX})
        ids = []
        for f in files:
            m = (CONCAT_NAME.search(f) or CONCAT_FILE.fullmatch(f)) if isinstance(f, str) else None
            if not m:
                return self._json(400, {"error": "只能合併這台電腦裡的成片"})
            ids.append(m.group(1))
        if not (st.ffmpeg and st.ffprobe):
            return self._json(409, {"error": "這台找不到 ffmpeg，沒辦法合併"})
        try:
            paths = [os.path.join(st.media, self._cache_job(j)) for j in ids]
        except ConsoleError as e:
            return self._err(e, with_hints=False)
        name = safe_filename(body.get("name") or "合併", 60) or "合併"
        work = tempfile.mkdtemp(prefix="concat-", dir=st.data_dir)
        env = st.openh264_env()
        run = lambda args, t=600: subprocess.run(args, capture_output=True, timeout=t, env=env, stdin=subprocess.DEVNULL)
        try:
            out = os.path.join(work, "out.mp4")

            def concat(parts):
                lst = os.path.join(work, "list-%d.txt" % len(os.listdir(work)))
                with open(lst, "w", encoding="utf-8") as f:
                    for x in parts:
                        f.write("file '%s'\n" % x.replace("'", "'\\''"))
                return run([st.ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                            "-c", "copy", "-movflags", "+faststart", out]).returncode == 0

            def streams(x):
                r = run([st.ffprobe, "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,"
                         "pix_fmt,sample_rate,channels", "-of", "json", x], 60)
                try:
                    return json.loads(r.stdout or b"{}").get("streams") or []
                except ValueError:
                    return []
            info = [streams(x) for x in paths]
            sig = lambda ss: json.dumps(sorted([sorted(d.items()) for d in ss]))
            lossless = len({sig(x) for x in info}) == 1 and any(d.get("codec_type") == "video" for d in info[0])
            if not (lossless and concat(paths)):
                lossless = False
                v0 = next((d for d in info[0] if d.get("codec_type") == "video"), {})
                W, H = int(v0.get("width") or 1080), int(v0.get("height") or 1920)
                W, H = W - W % 2, H - H % 2
                vc = render.video_codec_args(render.ffmpeg_caps(st.ffmpeg), H)
                norm = []
                for i, (x, ss) in enumerate(zip(paths, info)):
                    y = os.path.join(work, "n%02d.mp4" % i)
                    has_a = any(d.get("codec_type") == "audio" for d in ss)
                    args = [st.ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", x]
                    if not has_a:
                        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
                    args += ["-map", "0:v:0", "-map", "0:a:0" if has_a else "1:a:0",
                             "-vf", "scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2,fps=24,"
                             "format=yuv420p" % (W, H, W, H)] + vc + ["-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", y]
                    if run(args).returncode != 0:
                        return self._json(500, {"error": "第 %d 支重新編碼失敗" % (i + 1)})
                    norm.append(y)
                if not concat(norm):
                    return self._json(500, {"error": "合併失敗"})
            with open(out, "rb") as f:
                sha = self._store_blob(f.read(), "video/mp4")
            kept_dir = os.path.join(st.data_dir, "merged")
            os.makedirs(kept_dir, mode=0o700, exist_ok=True)
            kept = os.path.join(kept_dir, "%s-%s.mp4" % (name, sha[:8]))
            if not os.path.exists(kept):
                shutil.copyfile(out, kept)
        except render.RenderError as e:
            return self._json(409, {"error": str(e)})
        except (OSError, subprocess.SubprocessError):
            return self._json(500, {"error": "合併失敗（ffmpeg 沒跑完）"})
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return self._json(200, {"src": "/api/local/media?sha=" + sha, "file": name + ".mp4", "lossless": lossless, "path": kept})

    def _image_lost(self, body, started):
        model = str(body.get("model") or "")[:120]
        rec = {"at": started, "model": model, "n": body.get("n") if isinstance(body.get("n"), int) else 1}
        try:
            with self.state.media_lock:
                got = self.state.db.run(studio_store.kv_get, "image_timeouts")["value"]
                lst = (got if isinstance(got, list) else []) + [rec]
                self.state.db.run(studio_store.kv_put, "image_timeouts", lst[-IMAGE_TIMEOUTS_KEPT:])
        except studio_store.StoreError:
            pass
        when = time.strftime("%H:%M", time.localtime(started))
        return self._json(504, {
            "error": ("等不到這張圖（%s 送出的 %s）。AppleToken 的生圖沒有可以回頭查的編號，圖拿不回來；"
                      "額度可能已經扣了，請到 AppleToken 的用量紀錄對 %s 之後的圖片那一筆，扣了的話請聯絡 AppleToken。"
                      % (when, model or "圖片", when)),
            "maybe_billed": True, "submitted_at": started, "model": model})

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
            entry = qc.find_entry(listing, storyboard.model_of(q))
            if not storyboard.text_entry_ok(entry) and body.get("text_model"):
                return self._json(400, {"error": "目錄裡沒有你選的文字模型 %s，請到「付款與金鑰」重新選" % storyboard.model_of(q)})
            cap = storyboard.price_cap(entry, q) if entry else None
        except ConsoleError:
            pass
        if body.get("dry_run"):
            return self._json(200, {"object": "storyboard.estimate", "payer": "own_key",
                                    "model": storyboard.model_of(q), "shots": q.get("shots")})
        ref = storyboard.new_ref()
        with st.lock:
            now = time.monotonic()
            for k in [k for k, v in st.sb.items() if now - v["t"] > SB_QUOTE_TTL * 2]:
                st.sb.pop(k, None)
            st.sb[ref] = {"q": q, "t": now, "status": "quoted", "result": None}
        return self._json(200, {
            "object": "storyboard.confirmation", "status": "needs_confirmation", "quote_id": ref,
            "payer": "own_key", "model": storyboard.model_of(q), "shots": q.get("shots"),
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
                  "model": storyboard.model_of(q), "shots": shots, "count": len(shots),
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
                                                container=container,
                                                caption_fontsdir=os.path.join(ROOT, "fonts"))
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
        with st.lock:
            gate = st.landing.setdefault(job_id, threading.Lock())
        with gate:
            sha = self._job_media().get(job_id)
            if sha and os.path.exists(os.path.join(st.media, sha)):
                return sha
            resp = st.call("/videos/%s/content" % job_id, stream=True, timeout=180)
            tmp = os.path.join(st.media, "job-%s.part-%s" % (job_id, secrets.token_hex(4)))
            h, n = hashlib.sha256(), 0
            try:
                with open(tmp, "wb") as f:
                    while True:
                        block = resp.read(1024 * 1024)
                        if not block:
                            break
                        n += len(block)
                        if n > MEDIA_MAX:
                            raise ConsoleError(502, "成片 %s 太大" % job_id)
                        h.update(block)
                        f.write(block)
                if not n:
                    raise ConsoleError(502, "成片 %s 取不回來" % job_id)
                sha = h.hexdigest()
                dest = os.path.join(st.media, sha)
                if not os.path.exists(dest):
                    with open(dest + ".json", "w", encoding="utf-8") as f:
                        json.dump({"mime": "video/mp4", "bytes": n}, f)
                    os.replace(tmp, dest)
            except OSError:
                raise ConsoleError(500, "成片寫不進本機磁碟") from None
            finally:
                resp.close()
                if os.path.exists(tmp):
                    os.remove(tmp)
            with st.media_lock:
                known = self._job_media()
                known[job_id] = sha
                st.db.run(studio_store.kv_put, "job_media", known)
            return sha

    def _land_later(self, job_id):
        def run():
            try:
                self._cache_job(job_id)
            except (ConsoleError, studio_store.StoreError, OSError):
                pass
        if self._job_media().get(job_id) is None:
            threading.Thread(target=run, daemon=True).start()

    def _local_file(self, sha):
        p = os.path.join(self.state.media, sha)
        try:
            with open(p + ".json", encoding="utf-8") as f:
                mime = json.load(f).get("mime") or "application/octet-stream"
        except (OSError, ValueError):
            mime = "application/octet-stream"
        return self._send_file(p, mime, {"Content-Security-Policy": "sandbox"})

    def _send_file(self, path, mime, extra=None):
        size = os.path.getsize(path)
        extra = dict(extra or {}, **{"Accept-Ranges": "bytes"})
        rng = (self.headers.get("Range") or "").strip()
        m = re.match(r"^bytes=(\d*)-(\d*)$", rng) if rng else None
        if not m or not (m.group(1) or m.group(2)):
            return self._relay(_FileResp(open(path, "rb"), size), mime, extra)
        if m.group(1):
            start = int(m.group(1))
            end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
        else:
            start, end = max(0, size - int(m.group(2))), size - 1
        if start >= size or start > end:
            self.send_response(416)
            self.send_header("Content-Range", "bytes */%d" % size)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        f = open(path, "rb")
        f.seek(start)
        n = end - start + 1
        try:
            self.send_response(206)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(n))
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command == "HEAD":
                return None
            while n > 0:
                chunk = f.read(min(n, 65536))
                if not chunk:
                    break
                self.wfile.write(chunk)
                n -= len(chunk)
        except OSError:
            self.close_connection = True
        finally:
            f.close()
        return None

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
        self._mark_read()
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
    st.mcp_setup(handler.port)
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
