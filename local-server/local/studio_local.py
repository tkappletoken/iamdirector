import argparse
import base64
import binascii
import datetime
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
import cast_refs
import templates
import twist
import page_strip
import qc
import sqlite_store
import storyboard
import studio_store
import film_settings
import work_frames
import studio_tools
import takes
import gen_retry
import upstream
from upstream import ConsoleError, Cred, retry_field, with_hint

DEFAULT_BASE = "https://appletoken.app/v2"
TIMEOUT = 15
GENERATE_TIMEOUT = 120
IMAGE_TIMEOUT = 610
IMAGE_TIMEOUTS_KEPT = 50
IMAGE_RECOVER_KEPT = 50
image_recover_mode = upstream.image_recover_mode
_dropped = upstream.dropped
CONCAT_MAX = 30
CONCAT_ENGINES = ("legacy", "shadow", "blocks")
FILM_SEAM_TRIM_ENV = "STUDIO_FILM_SEAM_TRIM"
FILM_SEAM_XFADE_ENV = "STUDIO_FILM_SEAM_XFADE"
FILM_SEAM_XFADE_SECONDS_ENV = "STUDIO_FILM_SEAM_XFADE_SECONDS"
FILM_SEAM_XFADE_DEFAULT = 0.2
FILM_SEAM_AFADE_ENV = "STUDIO_FILM_SEAM_AFADE"
MUTE_MODEL_AUDIO_ENV = "STUDIO_MUTE_MODEL_AUDIO"

def film_seam_afade(env=None):
    env = os.environ if env is None else env
    if env.get(FILM_SEAM_AFADE_ENV, "").strip().lower() not in ("1", "on", "true"):
        return None
    try:
        d = float(env.get(FILM_SEAM_XFADE_SECONDS_ENV) or FILM_SEAM_XFADE_DEFAULT)
    except ValueError:
        return FILM_SEAM_XFADE_DEFAULT
    return round(d, 3) if 0.05 <= d <= 1.5 else FILM_SEAM_XFADE_DEFAULT

def film_seam_xfade(env=None):
    env = os.environ if env is None else env
    if env.get(FILM_SEAM_XFADE_ENV, "").strip().lower() not in ("1", "on", "true"):
        return None
    try:
        d = float(env.get(FILM_SEAM_XFADE_SECONDS_ENV) or FILM_SEAM_XFADE_DEFAULT)
    except ValueError:
        return FILM_SEAM_XFADE_DEFAULT
    return round(d, 3) if 0.05 <= d <= 1.5 else FILM_SEAM_XFADE_DEFAULT

def mute_model_audio(asked):
    if os.environ.get(MUTE_MODEL_AUDIO_ENV, "").strip().lower() not in ("1", "on", "true"):
        return False
    return asked is not False

CONCAT_SHADOW_LOAD = 30.0
_CONCAT_SHADOW = threading.Lock()
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
AUDIO_DATA = re.compile(r"^data:audio/(webm|ogg|wav|x-wav|wave)(?:;codecs=[A-Za-z0-9.,\"-]{1,40})?;base64,([A-Za-z0-9+/=]+)$")
AUDIO_EXT = {"webm": ".webm", "ogg": ".ogg", "wav": ".wav", "x-wav": ".wav", "wave": ".wav"}
DRAIN_MAX = 64 * 1024 * 1024
BODY_LIMITS = {"/api/assets": 24 * 1024 * 1024, "/api/image-generate": 24 * 1024 * 1024,
               "/api/export": 24 * 1024 * 1024, "/api/local/work-import": 2 * 1024 * 1024,
               "/api/qc": 3 * 1024 * 1024,
               "/api/transcribe": 14 * 1024 * 1024}
MEDIA_MAX = 4 * 1024 ** 3
MEDIA_MIME = re.compile(r"^(video/(mp4|quicktime|webm)|audio/(mpeg|mp3|mp4|aac|wav|x-wav|wave|flac|ogg)"
                        r"|image/(png|jpeg|webp|gif))$")
AUDIO_REF = re.compile(r"/api/audio/content\?sha=([0-9a-f]{64})")
IMAGE_INLINE_MAX = 20 * 1024 * 1024
ORIGINAL_MAX = 20 * 1024 * 1024

ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
QID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
ASSET_ID = re.compile(r"^ast_[0-9a-f]{20}$")
UPLOAD_ID = re.compile(r"^upl_[0-9a-f]{32}$")
OUTPAINT_MAX = 20 * 1024 * 1024
ASSET_MIME = re.compile(r"^(image|video|audio)/[A-Za-z0-9.+-]{1,60}$")
PROJECT_ID = re.compile(r"^[0-9a-fA-F-]{36}$")
ASSET_URI = re.compile(r"^asset\s*:\s*/*\s*(ast_[0-9a-f]{20})$", re.I)
DATA_URI = re.compile(r"^data:([a-z]+/[A-Za-z0-9.+-]{1,60});base64,", re.I)
MANIFEST_SLOT = "<!-- STUDIO-MANIFEST -->"

CAPABILITIES = (("video", "影片"), ("image", "圖片"), ("tts", "配音"), ("music", "配樂"), ("lipsync", "對嘴"))
PROVIDED = ("video", "image", "tts", "music")
ENGINE_CHOICES = ("legacy", "blocks", "shadow")
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
    "/api/assets/update", "/api/check-asset", "/api/qc/rating",
    "/api/qc/estimate",
    "/api/assets/delete", "/api/assets/uploads", "/api/assets/uploads/complete",
    "/api/image-outpaint", "/api/post-process", "/api/post-process-status", "/api/post-process-content",
    "/api/storyboard/quote", "/api/storyboard", "/api/parse-shots", "/api/captions",
    "/api/store", "/api/projects", "/api/projects/create", "/api/projects/delete",
    "/api/projects/rename", "/api/projects/items",
    "/api/audio/speech", "/api/audio/music", "/api/audio/music-status", "/api/audio/music-content",
    "/api/audio/content", "/api/export", "/api/export/config", "/api/export/status", "/api/export/download",
    "/api/approvals", "/api/approvals/decide", "/api/approvals/submit", "/api/approvals/limits",
    "/api/works/create", "/api/local/mcp", "/api/local/mcp-token", "/api/local/result",
    "/api/works/quote", "/api/works/export", "/api/twist",
    "/api/works/get", "/api/works/clone",
    "/api/works/shot-edit", "/api/works/shot-move",
    "/api/local/engine",
    "/api/local/concat-engine",
    "/api/blocks", "/api/pipeline/preview",
    "/api/dir-controls", "/api/dir-controls/preview",
    "/api/previs-rig",
    "/api/works/shot-dirctl",
    "/api/works/shot-blocking", "/api/previs-from-dc",
    "/api/local/agent-scope",
    "/api/takes", "/api/takes/move", "/api/takes/qc", "/api/takes/pick", "/api/takes/retake-plan",
    "/api/chains", "/api/chains/next", "/api/chains/move",
    "/api/local/agent/start", "/api/local/agent/step", "/api/local/agent/get", "/api/local/agent-loop", "/api/local/agent/plan",
    "/api/local/agent/runs", "/api/local/agent/film",
    "/api/local/work/run",
    "/api/local/agent-qc",
    "/api/local/frame-relay",
    "/api/local/film-settings",
    "/api/local/ui-desc", "/api/local/ui-profiles",
    "/api/local/mcp-direct",
)

AGENT_ALLOWED = {
    ("GET", "/api/version"), ("GET", "/api/model-groups"), ("GET", "/api/status"), ("GET", "/api/me"),
    ("GET", "/api/usage"), ("GET", "/api/payer"), ("GET", "/api/projects"), ("GET", "/api/store"),
    ("GET", "/api/charges"), ("GET", "/api/confirm-status"), ("GET", "/api/approvals"),
    ("GET", "/api/approvals/limits"), ("GET", "/api/local/result"), ("GET", "/api/ffmpeg"),
    ("POST", "/api/generate"), ("POST", "/api/estimate"), ("POST", "/api/approvals/submit"), ("POST", "/api/approvals"),
    ("POST", "/api/works/create"), ("POST", "/api/parse-shots"), ("POST", "/api/check-refs"), ("POST", "/mcp"),
    ("POST", "/api/works/quote"), ("POST", "/api/works/export"), ("GET", "/api/twist"), ("GET", "/api/export/status"),
    ("GET", "/api/blocks"), ("POST", "/api/pipeline/preview"),
    ("GET", "/api/works/get"), ("POST", "/api/works/clone"),
}
AGENT_ALLOWED |= set(takes.ROUTES)
AGENT_ALLOWED |= {("GET", "/api/agent/activity"), ("POST", "/api/agent/activity")}
AGENT_ALLOWED |= {("POST", "/api/local/agent/start"), ("POST", "/api/local/agent/step"), ("GET", "/api/local/agent/get"),
                  ("POST", "/api/local/agent/plan"), ("GET", "/api/local/agent/runs"), ("GET", "/api/local/agent/film"),
                  ("GET", "/api/local/agent-loop"), ("POST", "/api/local/work/run")}
AGENT_ALLOWED |= {("GET", "/api/local/frame-relay")}
AGENT_ALLOWED |= {("GET", "/api/local/film-settings")}
AGENT_ALLOWED |= {("GET", "/api/local/ui-desc"), ("POST", "/api/local/ui-desc")}
UI_PROFILES_OFF = "介面描述檔沒有開（設定 ui_profiles.json 或 STUDIO_LOCAL_UI_PROFILES=on）"
AGENT_ALLOWED |= {("GET", "/api/local/mcp-direct")}
AGENT_ALLOWED |= {("GET", "/api/local/agent-qc")}
AGENT_ALLOWED |= {("GET", "/api/dir-controls"), ("POST", "/api/dir-controls/preview"), ("POST", "/api/previs-rig"),
                  ("POST", "/api/works/shot-dirctl")}
AGENT_ALLOWED |= {("POST", "/api/works/shot-blocking")}
AGENT_ALLOWED |= {("POST", "/api/concat"), ("GET", "/api/assets"), ("POST", "/api/assets"), ("GET", "/api/assets/support"),
                  ("POST", "/api/projects/create"), ("POST", "/api/projects/rename"), ("POST", "/api/projects/items"),
                  ("POST", "/api/captions"), ("POST", "/api/assets/update"), ("POST", "/api/check-asset"),
                  ("GET", "/api/qc/rating"), ("GET", "/api/qc/estimate"),
                  ("GET", "/api/local/agent-scope"), ("GET", "/api/local/engine"), ("GET", "/api/local/concat-engine"),
                  ("GET", "/api/local/ui-profiles")}
FRAME_RELAY_ENV = "STUDIO_LOCAL_FRAME_RELAY"

def frame_relay_on():
    return os.environ.get(FRAME_RELAY_ENV, "").strip().lower() in ("on", "1", "true")

def frame_relay(st, video_of, take_id):
    from filming import frames as ffr
    try:
        t = st.db.run(lambda c, u: takes.get(c, u, take_id))
    except Exception:
        return None, "take_unreadable"
    job = (t or {}).get("job_id")
    if not job:
        return None, "no_job"
    try:
        path = video_of(job)
    except Exception:
        return None, "no_video"
    ff = st.ffmpeg or ffr.find_ffmpeg()
    if not ff:
        return None, "no_ffmpeg"
    tmp = tempfile.mkdtemp(prefix="iamd-relay-")
    try:
        png = os.path.join(tmp, "last.png")
        try:
            ffr.last(path, png, ffmpeg=ff)
            with open(png, "rb") as f:
                raw = f.read()
        except (ffr.FramesError, OSError, subprocess.SubprocessError):
            return None, "extract_failed"
        if not raw or len(raw) > 20 * 1024 * 1024:
            return None, "extract_failed"
        try:
            r = st.call("/assets", payload={"source": "data:image/png;base64," + base64.b64encode(raw).decode(),
                                            "name": "relay-%s" % take_id}, timeout=GENERATE_TIMEOUT)
        except ConsoleError:
            return None, "upload_failed"
        aid = r.get("id") if isinstance(r, dict) else None
        if not (isinstance(aid, str) and ASSET_ID.match(aid)):
            return None, "upload_failed"
        return "asset://" + aid, None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def seam_ssim(st, video_of, prev_job, job):
    from filming import frames as ffr
    import postblocks.seam_check as sc
    ff = st.ffmpeg or ffr.find_ffmpeg()
    if not ff:
        return None
    tmp = tempfile.mkdtemp(prefix="iamd-seam-")
    try:
        png = os.path.join(tmp, "prev_last.png")
        ffr.last(video_of(prev_job), png, ffmpeg=ff)
        return sc.SeamCheck.ssim(ff, png, 0.0, video_of(job), 0.0)
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

AGENT_LOOP_OFF = "Filming Agent 主迴圈沒有開（設定 agent_loop.json 或 STUDIO_LOCAL_AGENT_LOOP=on）"
AGENT_RUN = re.compile(r"^agr_[0-9a-f]{24}$")
AGENT_SCOPES = ("basic", "full")
AGENT_FULL = {
    ("POST", "/api/storyboard/quote"), ("POST", "/api/storyboard"),
    ("POST", "/api/audio/speech"), ("POST", "/api/audio/music"), ("GET", "/api/audio/music-status"),
    ("GET", "/api/audio/music-content"), ("GET", "/api/audio/content"),
    ("POST", "/api/image-generate"), ("POST", "/api/image"), ("POST", "/api/qc"),
    ("POST", "/api/qc/rate"),
    ("POST", "/api/works/shot-edit"), ("POST", "/api/works/shot-move"),
}
AGENT_SWITCHES = ("/api/local/agent-loop", "/api/local/mcp-direct", "/api/local/agent-qc", "/api/local/frame-relay",
                  "/api/local/agent-scope", "/api/local/engine", "/api/local/concat-engine", "/api/local/ui-profiles",
                  "/api/local/film-settings")
if {("POST", p) for p in AGENT_SWITCHES} & (AGENT_ALLOWED | AGENT_FULL):
    raise RuntimeError("開關的 POST 不准放進 AGENT_ALLOWED／AGENT_FULL（只有人能切）")
SPEND_TTL = 30 * 60
MCP_PACKAGE_FILES = (
    "cli/appletoken/__init__.py",
    "cli/appletoken/core/__init__.py", "cli/appletoken/core/api.py", "cli/appletoken/core/errors.py",
    "cli/appletoken/core/model_caps.py",
    "cli/appletoken/core/http.py", "cli/appletoken/core/poll.py", "cli/appletoken/core/preflight.py",
    "cli/appletoken/core/redact.py", "cli/appletoken/core/session.py",
    "cli/appletoken/mcp/__init__.py", "cli/appletoken/mcp/activity.py", "cli/appletoken/mcp/tools.py",
)
AGENT_TOKEN_PREFIX = "iadl_"
_AGENT_NO_CONFIRM = "本機的 Agent 不能直接確認：這張報價已經附了核准卡，使用者核准後用 submit_approved 送出"
MCP_FILE = "mcp.json"
JOB_ID_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_LATER = "本機模式還沒有這一項（之後的版本會補上）"
DIRCTL_OFF = "導演控制的預覽送出句已關閉（STUDIO_LOCAL_DIRCTL=off）"
DC_KEYS = ("move", "speed", "direction", "end", "allow_cuts", "lens", "style", "color", "light", "location", "sound",
           "blocking", "perf", "by")
DC_BY = ("agent", "human")
DC_BLOCK_KEYS = ("name", "x", "depth", "facing", "tox", "todepth", "action")

def dc_clean(dc):
    if not isinstance(dc, dict):
        raise ValueError("dc 要是物件")
    extra = set(dc) - set(DC_KEYS)
    if extra:
        raise ValueError("不認得的欄位 %s" % "、".join(sorted(extra)))
    out = {}
    for k, v in dc.items():
        if k == "blocking":
            if not isinstance(v, list):
                raise ValueError("blocking 要是清單")
            rows = []
            for i, b in enumerate(v):
                if not isinstance(b, dict) or set(b) - set(DC_BLOCK_KEYS):
                    raise ValueError("blocking[%d] 只收 %s" % (i, "、".join(DC_BLOCK_KEYS)))
                rows.append({kk: vv for kk, vv in b.items() if vv not in (None, "")})
            v = rows
        elif k == "perf":
            if not isinstance(v, list) or not all(isinstance(p, dict) and set(p) <= {"name", "notes"} for p in v):
                raise ValueError("perf 要是 [{name, notes}]")
            v = [{"name": p.get("name"), "notes": "\n".join(p["notes"]) if isinstance(p.get("notes"), list) else p.get("notes")}
                 for p in v]
        elif k == "by":
            if v not in DC_BY:
                raise ValueError("by 只能是 %s" % "／".join(DC_BY))
        elif k == "allow_cuts":
            if not isinstance(v, bool):
                raise ValueError("allow_cuts 要是 true／false")
        elif v is not None and not isinstance(v, str):
            raise ValueError("%s 要是字串" % k)
        if v in (None, "", [], False):
            continue
        out[k] = v
    if not set(out) - {"by"}:
        raise ValueError("dc 是空的（要清掉請給 null）")
    return out

def dc_controls(dc):
    c = {"camera_move": dc.get("move"), "speed": dc.get("speed"), "direction": dc.get("direction"), "end": dc.get("end")}
    if dc.get("allow_cuts"):
        c["allow_cuts"] = True
    for k in ("lens", "style", "color", "light", "location", "sound"):
        c[k] = dc.get(k)
    return {k: v for k, v in c.items() if v not in (None, "")}

def dc_desc(dc):
    cam = {k: dc[k] for k in ("move", "speed", "direction", "end") if dc.get(k)}
    if dc.get("allow_cuts"):
        cam["allow_cuts"] = True
    blocking = []
    for b in dc.get("blocking") or []:
        one = {"name": b.get("name"), "at": {k: v for k, v in (("x", b.get("x")), ("depth", b.get("depth"))) if v}}
        if b.get("facing"):
            one["facing"] = b["facing"]
        to = {k: v for k, v in (("x", b.get("tox")), ("depth", b.get("todepth"))) if v}
        if to:
            one["to"] = to
        if b.get("action"):
            one["action"] = b["action"]
        blocking.append(one)
    perf = [{"name": p.get("name"), "notes": [n for n in str(p.get("notes") or "").split("\n") if n.strip()]}
            for p in dc.get("perf") or []]
    d = {"version": 1, "prompt": "x", "camera": cam, "blocking": blocking, "performance": perf}
    d.update({k: dc[k] for k in ("lens", "style", "color", "light", "location", "sound") if dc.get(k)})
    return d

def _shot_index(board, shot):
    if isinstance(shot, int) and not isinstance(shot, bool):
        return shot - 1 if 1 <= shot <= len(board) else None
    if isinstance(shot, str) and shot:
        for i, s in enumerate(board):
            if isinstance(s, dict) and s.get("sid") == shot:
                return i
    return None
PREVIS_RIG_OFF = "3D 預演的對準角色已關閉（STUDIO_LOCAL_PREVIS_RIG=off）"
BLOCKING_SYNC_OFF = "預演站位換算成導演控制還沒開（STUDIO_LOCAL_BLOCKING_SYNC=on 才有，預設關）"
_PREVIS_KEY = re.compile(r"^[a-z0-9_-]{1,32}$")
_PREVIS_SID = re.compile(r"^[a-z0-9]{4,}$")

def blocking_sync_on():
    return os.environ.get("STUDIO_LOCAL_BLOCKING_SYNC", "").strip().lower() in ("1", "on", "true")

def previs_keys(pid, sid):
    seg = re.sub(r"[^0-9a-z]", "", str(pid or ""), flags=re.I)[:8].lower()
    suffix = "-" + seg if seg else ""
    k = "previs" + suffix + "-" + str(sid or "")
    return (k if _PREVIS_KEY.match(k) and _PREVIS_SID.match(str(sid or "")) else ""), "previs" + suffix
_LOGIN = "登入 iamdirector 帳號後才有這一項"
ACTIVITY_MAX = 200
OPEN_FRESH = 45
ACTIVITY_TOOLS = {"timeline_place": "place", "timeline_trim": "trim", "export_request": "export"}

MISSING = {
    "/api/upload": "本機素材改用下方的「素材」", "/api/uploads": "本機素材改用下方的「素材」",
    "/api/rates": "費率由 AppleToken 決定", "/api/timing": "測試站自用的生成耗時統計，本機不收集",
    "/api/image-task": "本機生圖不需要輪詢",
    "/api/assets/mirror": "本機模式只有你自己的金鑰，不需要複製素材",
    "/api/archive": "雲端封存只在網頁版（作品存在你這台電腦，備份用「同步到雲端」）",
    "/api/youtube/status": _LOGIN, "/api/youtube/connect": _LOGIN, "/api/youtube/disconnect": _LOGIN,
    "/api/youtube/playlists": _LOGIN, "/api/youtube/uploads": _LOGIN,
    "/api/youtube/uploads/cancel": _LOGIN, "/api/youtube/uploads/retry": _LOGIN, "/api/youtube/auto": _LOGIN,
    "/api/pitch/platforms": _LOGIN, "/api/pitch/preview": _LOGIN, "/api/pitch/packages": _LOGIN,
    "/api/pitch/download": _LOGIN,
    "/api/wallet/balance": _LOGIN, "/api/wallet/history": _LOGIN, "/api/wallet/options": _LOGIN,
    "/api/wallet/intent": _LOGIN, "/api/wallet/subscription": _LOGIN, "/api/wallet/subscribe": _LOGIN,
    "/api/agent/tokens": "本機的 Agent 用 MCP 連線檔，在設定頁「MCP」那一格看或重新產生",
    "/api/agent/tokens/revoke": "本機的 Agent 用 MCP 連線檔，在設定頁「MCP」那一格重新產生權杖就等於撤銷",
    "/api/agent/tokens/update": "本機的 Agent 用 MCP 連線檔，在設定頁「MCP」那一格看或重新產生",
    "/api/agent/pending": "本機花錢一律走核准卡（request_approval／status），沒有網頁版的確認模式",
    "/api/agent/pending/decide": "本機花錢一律走核准卡（request_approval／status），沒有網頁版的確認模式",
    "/api/logout": "本機模式不用登入",
}

UI_DESC_KEY = "ui-desc"

def ui_desc_value(value):
    try:
        from filming import ui_schema
    except ImportError:
        return None, (503, {"error": "這一版沒有介面描述檔的驗證器，描述檔先不能存"})
    try:
        return ui_schema.store_value(value), None
    except ui_schema.DescError as e:
        return None, (400, {"error": "描述檔不合法：%s" % e})

def ui_desc_actions():
    try:
        from filming import ui_schema
        return ui_schema.client_actions(local=True)
    except Exception:
        return None

def ui_desc_components():
    from filming import ui_schema
    return ui_schema.client_components(local=True)

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
        self.dirctl_revs = {}
        self.dirctl_writes = {}
        self.dirctl_lock = threading.Lock()
        self.mcp_path = os.path.join(data_dir, MCP_FILE)
        self.sb = {}
        self.desktop = None
        self._page = None
        self.audio = {}
        self.spend = {}
        self.media = os.path.join(data_dir, "media")
        os.makedirs(self.media, mode=0o700, exist_ok=True)
        self.exports_root = os.path.join(data_dir, "exports")
        self.exports = {}
        self.workbench_open = None
        self.activity = []
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

    def engine_setting(self):
        try:
            with open(os.path.join(self.data_dir, "postblocks.json"), encoding="utf-8") as f:
                v = json.load(f).get("engine")
            return v if v in ENGINE_CHOICES else None
        except (OSError, ValueError, AttributeError):
            return None

    def set_engine(self, value):
        path = os.path.join(self.data_dir, "postblocks.json")
        try:
            if value is None:
                if os.path.exists(path):
                    os.remove(path)
                return True
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"engine": value}, f)
            os.replace(tmp, path)
            return True
        except OSError:
            return False

    def engine_now(self):
        v = self.engine_setting()
        env = os.environ.get("POSTBLOCKS_ENGINE", "").strip().lower()
        return v or (env if env in ENGINE_CHOICES else "legacy")

    def engine_info(self):
        env = os.environ.get("POSTBLOCKS_ENGINE", "").strip().lower() or None
        return {"engine": self.engine_now(), "setting": self.engine_setting(), "env": env,
                "choices": list(ENGINE_CHOICES)}

    def concat_engine_setting(self):
        try:
            with open(os.path.join(self.data_dir, "concat.json"), encoding="utf-8") as f:
                v = json.load(f).get("engine")
            return v if v in CONCAT_ENGINES else None
        except (OSError, ValueError, AttributeError):
            return None

    def concat_engine(self):
        v = self.concat_engine_setting()
        env = os.environ.get("STUDIO_LOCAL_CONCAT_ENGINE", "").strip().lower()
        return v or (env if env in CONCAT_ENGINES else "legacy")

    def set_concat_engine(self, value):
        path = os.path.join(self.data_dir, "concat.json")
        try:
            if value is None:
                if os.path.exists(path):
                    os.remove(path)
                return True
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"engine": value}, f)
            os.replace(tmp, path)
            return True
        except OSError:
            return False

    def concat_engine_info(self):
        env = os.environ.get("STUDIO_LOCAL_CONCAT_ENGINE", "").strip().lower() or None
        return {"engine": self.concat_engine(), "setting": self.concat_engine_setting(), "env": env,
                "choices": list(CONCAT_ENGINES)}

    def agent_scope_setting(self):
        try:
            with open(os.path.join(self.data_dir, "agent_scope.json"), encoding="utf-8") as f:
                v = json.load(f).get("scope")
            return v if v in AGENT_SCOPES else None
        except (OSError, ValueError, AttributeError):
            return None

    def agentloop_setting(self):
        try:
            with open(os.path.join(self.data_dir, "agent_loop.json"), encoding="utf-8") as f:
                v = json.load(f).get("on")
            return v if isinstance(v, bool) else None
        except (OSError, ValueError, AttributeError):
            return None

    def agentloop_on(self):
        v = self.agentloop_setting()
        if v is not None:
            return v
        return os.environ.get("STUDIO_LOCAL_AGENT_LOOP", "").strip().lower() in ("on", "1", "true")

    AGENT_RUNS_SCAN = 50

    def agent_run_ids(self):
        d = os.path.join(self.data_dir, "agent_runs")
        if not os.path.isdir(d):
            return frozenset()
        ents = [e for e in os.scandir(d) if e.is_file() and e.name.startswith("agr_") and e.name.endswith(".json")]
        ents.sort(key=lambda e: e.stat().st_mtime_ns, reverse=True)
        cache = self.__dict__.setdefault("_run_ids", {})
        out = set()
        for e in ents[:self.AGENT_RUNS_SCAN]:
            stt = e.stat()
            sig = (stt.st_mtime_ns, stt.st_size)
            got = cache.get(e.name)
            if not got or got[0] != sig:
                with open(e.path, encoding="utf-8") as f:
                    rec = json.load(f)
                ids = set()
                for r in ((rec.get("ids") or {}).values() if isinstance(rec, dict) else ()):
                    if isinstance(r, dict):
                        ids.update(str(r[k]) for k in ("card", "take", "job") if r.get(k))
                got = cache[e.name] = (sig, frozenset(ids))
            out |= got[1]
        for gone in set(cache) - {e.name for e in ents}:
            cache.pop(gone, None)
        return frozenset(out)

    def agent_loop_owns(self, take):
        if not take or not self.agentloop_on():
            return False
        if not os.path.isdir(os.path.join(self.data_dir, "agent_runs")):
            return False
        try:
            ids = self.agent_run_ids()
        except Exception as e:
            gen_retry.log("agent_runs_unreadable", type(e).__name__)
            return True
        return any(str(take.get(k)) in ids for k in ("id", "job_id", "approval_id") if take.get(k))

    def uiprofiles_setting(self):
        try:
            with open(os.path.join(self.data_dir, "ui_profiles.json"), encoding="utf-8") as f:
                v = json.load(f).get("on")
            return v if isinstance(v, bool) else None
        except (OSError, ValueError, AttributeError):
            return None

    def uiprofiles_on(self):
        v = self.uiprofiles_setting()
        if v is not None:
            return v
        return os.environ.get("STUDIO_LOCAL_UI_PROFILES", "").strip().lower() in ("on", "1", "true")

    def uiprofiles_onboarding(self):
        try:
            with open(os.path.join(self.data_dir, "ui_profiles.json"), encoding="utf-8") as f:
                v = json.load(f).get("onboarding")
            if isinstance(v, bool):
                return v
        except (OSError, ValueError, AttributeError):
            pass
        return os.environ.get("STUDIO_LOCAL_UI_ONBOARDING", "").strip().lower() in ("on", "1", "true")

    def uiprofiles_info(self):
        env = os.environ.get("STUDIO_LOCAL_UI_PROFILES", "").strip().lower() or None
        return {"on": self.uiprofiles_on(), "setting": self.uiprofiles_setting(), "env": env,
                "onboarding": self.uiprofiles_onboarding()}

    _KEEP = object()

    def bump_dirctl(self, key, sid=None):
        with self.dirctl_lock:
            self.dirctl_revs[key] = self.dirctl_revs.get(key, 0) + 1
            if sid:
                self.dirctl_writes.setdefault(key, {})[sid] = self.dirctl_revs[key]
            return self.dirctl_revs[key]

    def dirctl_rev_of(self, key):
        key = key if isinstance(key, str) and key.startswith("sb_") and len(key) <= 40 else ""
        with self.dirctl_lock:
            return {"key": key, "rev": self.dirctl_revs.get(key, 0)}

    def set_uiprofiles(self, value=_KEEP, onboarding=_KEEP):
        path = os.path.join(self.data_dir, "ui_profiles.json")
        try:
            cur = {}
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    cur = json.load(f)
            cur = cur if isinstance(cur, dict) else {}
            if value is None:
                cur.pop("on", None)
            elif value is not self._KEEP:
                cur["on"] = bool(value)
            cur.pop("agent_apply", None)
            if onboarding is not self._KEEP:
                cur["onboarding"] = bool(onboarding)
            if "on" not in cur and "onboarding" not in cur:
                if os.path.exists(path):
                    os.remove(path)
                return True
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cur, f)
            os.replace(tmp, path)
            return True
        except (OSError, ValueError):
            return False

    def frame_relay_setting(self):
        try:
            with open(os.path.join(self.data_dir, "frame_relay.json"), encoding="utf-8") as f:
                v = json.load(f).get("on")
            return v if isinstance(v, bool) else None
        except (OSError, ValueError, AttributeError):
            return None

    def frame_relay_on(self):
        v = self.frame_relay_setting()
        return v if v is not None else frame_relay_on()

    def agent_qc_setting(self):
        try:
            with open(os.path.join(self.data_dir, "agent_qc.json"), encoding="utf-8") as f:
                v = json.load(f).get("on")
            return v if isinstance(v, bool) else None
        except (OSError, ValueError, AttributeError):
            return None

    def agent_qc_on(self):
        v = self.agent_qc_setting()
        if v is not None:
            return v
        return os.environ.get("STUDIO_LOCAL_AGENT_QC", "").strip().lower() in ("on", "1", "true")

    def agent_qc_info(self):
        env = os.environ.get("STUDIO_LOCAL_AGENT_QC", "").strip().lower() or None
        return {"on": self.agent_qc_on(), "setting": self.agent_qc_setting(), "env": env}

    def set_agent_qc(self, value):
        path = os.path.join(self.data_dir, "agent_qc.json")
        try:
            if value is None:
                if os.path.exists(path):
                    os.remove(path)
                return True
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"on": bool(value)}, f)
            os.replace(tmp, path)
            return True
        except OSError:
            return False

    def set_film_settings(self, updates):
        try:
            film_settings.write(self.data_dir, updates)
            return True
        except OSError:
            return False

    def frame_relay_info(self):
        env = os.environ.get(FRAME_RELAY_ENV, "").strip().lower() or None
        return {"on": self.frame_relay_on(), "setting": self.frame_relay_setting(), "env": env}

    def set_frame_relay(self, value):
        path = os.path.join(self.data_dir, "frame_relay.json")
        try:
            if value is None:
                if os.path.exists(path):
                    os.remove(path)
                return True
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"on": bool(value)}, f)
            os.replace(tmp, path)
            return True
        except OSError:
            return False

    def agentloop_info(self):
        env = os.environ.get("STUDIO_LOCAL_AGENT_LOOP", "").strip().lower() or None
        return {"on": self.agentloop_on(), "setting": self.agentloop_setting(), "env": env}

    def set_agentloop(self, value):
        path = os.path.join(self.data_dir, "agent_loop.json")
        try:
            if value is None:
                if os.path.exists(path):
                    os.remove(path)
                return True
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"on": bool(value)}, f)
            os.replace(tmp, path)
            return True
        except OSError:
            return False

    def mcp_direct_setting(self):
        try:
            with open(os.path.join(self.data_dir, "mcp_direct.json"), encoding="utf-8") as f:
                v = json.load(f).get("on")
            return v if isinstance(v, bool) else None
        except (OSError, ValueError, AttributeError):
            return None

    def mcp_direct_on(self):
        v = self.mcp_direct_setting()
        if v is not None:
            return v
        return os.environ.get("STUDIO_LOCAL_MCP_DIRECT", "").strip().lower() in ("on", "1", "true")

    def mcp_direct_info(self):
        env = os.environ.get("STUDIO_LOCAL_MCP_DIRECT", "").strip().lower() or None
        return {"on": self.mcp_direct_on(), "setting": self.mcp_direct_setting(), "env": env}

    def set_mcp_direct(self, value):
        path = os.path.join(self.data_dir, "mcp_direct.json")
        try:
            if value is None:
                if os.path.exists(path):
                    os.remove(path)
                return True
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"on": bool(value)}, f)
            os.replace(tmp, path)
            return True
        except OSError:
            return False

    def set_agent_scope(self, value):
        path = os.path.join(self.data_dir, "agent_scope.json")
        try:
            if value is None:
                if os.path.exists(path):
                    os.remove(path)
                return True
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"scope": value}, f)
            os.replace(tmp, path)
            return True
        except OSError:
            return False

    def agent_scope_now(self):
        v = self.agent_scope_setting()
        env = os.environ.get("STUDIO_LOCAL_AGENT_SCOPE", "").strip().lower()
        return v or (env if env in AGENT_SCOPES else "basic")

    def agent_scope_info(self):
        env = os.environ.get("STUDIO_LOCAL_AGENT_SCOPE", "").strip().lower() or None
        return {"scope": self.agent_scope_now(), "setting": self.agent_scope_setting(), "env": env,
                "choices": list(AGENT_SCOPES), "full_adds": sorted("%s %s" % x for x in AGENT_FULL)}

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

    def models_peek(self):
        hit = self.models
        return hit[1] if hit and time.monotonic() - hit[0] < MODELS_TTL else None

    def model_constraints(self, model):
        listing = self.models_peek()
        if listing is None or not model:
            return None
        try:
            meta = studio_tools.group_models(studio_tools.catalog_from_public(listing)).get("model_meta") or {}
        except Exception:
            return None
        return (meta.get(model) or {}).get("constraints")

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
    "status 查進度（排隊再久都不是失敗），result 拿成品在這台電腦上的路徑。付款方一律是使用者自己的 AppleToken 額度。"
    "第一次連上：先 ui_onboarding_status，needed=true 就照 ui_actions_list 的訪談題目問使用者、ui_compose 組出介面、ui_apply 套用。"
    "要一路拍到交片：create_work 建作品（帶分鏡），再 work_run 一步一步往下跑，每一步的回應都會寫下一步（next）。")

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
        allowed = AGENT_ALLOWED | AGENT_FULL if st.agent_scope_now() == "full" else AGENT_ALLOWED
        want = (self.command if self.command != "HEAD" else "GET", path)
        if want not in allowed:
            if want in AGENT_FULL:
                return self._json(403, {"error": "這一項要到設定開「Agent 可用全部功能」才能用（目前是基本範圍）",
                                        "agent_scope": "basic"})
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
        if code == 403 and isinstance(obj, dict):
            obj = dict(obj, local=True)
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
            "cast_refs": cast_refs.mode(),
        }
        if os.environ.get("STUDIO_LOCAL_MOTION_PICK", "on").strip().lower() != "off":
            manifest["motion_model_pick"] = True
        acts = ui_desc_actions()
        if acts:
            manifest["ui_actions"] = acts
            manifest["ui_components"] = ui_desc_components()
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
                (path.startswith("/approve/") and approvals.card_or_batch(path[len("/approve/"):])):
            return self._workbench()
        if ("GET", path) in takes.ROUTES:
            return self._takes("GET", path, {}, q)
        if path == "/api/approvals" and one("batch_id"):
            return self._approvals_batch_get(one("batch_id"))
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
        if path in ("/api/post-process-status", "/api/post-process-content"):
            pid = one("id") or ""
            if not re.match(r"^pp_[A-Za-z0-9]{1,64}$", pid):
                return self._json(400, {"error": "id 不合法"})
            try:
                if path == "/api/post-process-status":
                    return self._json(200, st.call("/post-process/" + pid))
                return self._relay(st.call("/post-process/%s/content" % pid, stream=True, timeout=180), "video/mp4")
            except ConsoleError as e:
                return self._err(e, with_hints=False)
        if path == "/api/agent/activity":
            since, lim = one("since"), one("limit")
            since = since.replace(" ", "+") if since else since
            if since and not re.match(r"^[0-9T:.+\- ]{10,40}$", since):
                return self._json(400, {"error": "since 要是 ISO 時間"})
            try:
                lim = max(1, min(200, int(lim or 50)))
            except ValueError:
                return self._json(400, {"error": "limit 要是整數"})
            if "open" in q:
                op = one("open")
                if op != "-" and not PROJECT_ID.match(op):
                    return self._json(400, {"error": "open 要是作品 id 或 -"})
                st.workbench_open = ("" if op == "-" else op.lower(), time.monotonic())
            with st.lock:
                items = [dict(x) for x in st.activity if not since or x["at"] > since]
            return self._json(200, {"items": items[-lim:]})
        if path == "/api/local/engine":
            return self._json(200, st.engine_info())
        if path == "/api/local/concat-engine":
            return self._json(200, st.concat_engine_info())
        if path == "/api/local/agent-scope":
            return self._json(200, st.agent_scope_info())
        if path == "/api/local/agent-loop":
            return self._json(200, st.agentloop_info())
        if path == "/api/local/frame-relay":
            return self._json(200, st.frame_relay_info())
        if path == "/api/local/film-settings":
            return self._json(200, film_settings.info(st.data_dir))
        if path == "/api/local/agent-qc":
            return self._json(200, st.agent_qc_info())
        if path == "/api/local/ui-profiles":
            return self._json(200, st.uiprofiles_info())
        if path == "/api/local/ui-desc":
            return self._uiprofiles("GET", None, {"name": one("name"), "questions": one("questions"), "catalog": one("catalog"),
                                                  "onboarding": one("onboarding")})
        if path == "/api/local/mcp-direct":
            return self._json(200, st.mcp_direct_info())
        if path == "/api/local/agent/get":
            return self._agentloop("get", {"run": one("run")})
        if path == "/api/local/agent/runs":
            return self._agentloop("runs", {})
        if path == "/api/local/agent/film":
            return self._agent_film(one("run"))
        if path == "/api/blocks":
            import postblocks
            return self._json(200, postblocks.catalog())
        if path == "/api/dir-controls":
            import shot_controls
            if one("full") == "1":
                return self._dirctl_catalog_full(shot_controls.director_catalog())
            return self._json(200, shot_controls.director_catalog())
        if path == "/api/works/shot-dirctl":
            return self._json(200, self.state.dirctl_rev_of(one("key")))
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
                    retry = self._gen_retry_hook(vid, s)
                    if retry is not None:
                        s = dict(s, retry=retry)
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
            try:
                return self._json(200, {"items": self._charges(ids)})
            except studio_store.StoreError:
                return self._json(200, {"items": {}, "db": False})
        if path == "/api/assets/support":
            return self._json(200, {"supported": bool(st.key())})
        if path == "/api/assets":
            qs = "&".join("%s=%s" % (k, parse.quote(one(k))) for k in ("limit", "status", "type") if one(k))
            try:
                got = st.call("/assets" + ("?" + qs if qs else ""))
            except ConsoleError as e:
                return self._err(e, with_hints=False)
            return self._json(200, self._asset_overlay(got, one("tag")))
        if path == "/api/qc/rating":
            return self._qc_rating_local(one("job"))
        if path == "/api/qc/estimate":
            return self._qc_estimate_local(one("frames") or "3")
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
        if path == "/api/works/get":
            return self._store(studio_store.work_get, one("project_id"))
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
        if ("POST", path) in takes.ROUTES:
            return self._takes("POST", path, body, {})
        if path == "/api/agent/activity":
            return self._agent_activity(body)
        if path == "/api/payer/key":
            if not self._human():
                return self._json(403, {"error": "金鑰要你本人在 App 裡設定"})
            return self._payer_key(body)
        if path == "/api/payer/key/delete":
            if not self._human():
                return self._json(403, {"error": "刪除金鑰要你本人在 App 裡做"})
            st.set_key(None)
            if st.desktop:
                st.desktop.request({"op": "clear_key"})
            return self._json(200, dict(self._payer_state(), removed=True))
        if path == "/api/pipeline/preview":
            return self._pipeline_preview(body)
        if path == "/api/dir-controls/preview":
            return self._dirctl_preview(body)
        if path == "/api/previs-rig":
            return self._previs_rig(body)
        if path == "/api/works/shot-dirctl":
            return self._shot_dirctl(body)
        if path == "/api/works/shot-blocking":
            return self._shot_blocking(body)
        if path == "/api/previs-from-dc":
            return self._previs_from_dc(body)
        if path == "/api/local/ui-profiles":
            if not self._human():
                return self._json(403, {"error": "介面描述檔的開關要你本人在 App 裡切"})
            v, ob = body.get("on"), body.get("onboarding")
            if v is not None and not isinstance(v, bool):
                return self._json(400, {"error": "on 要是 true／false，或 null（回到預設）"})
            if ob is not None and not isinstance(ob, bool):
                return self._json(400, {"error": "onboarding 要是 true／false"})
            kw = {}
            if "on" in body:
                kw["value"] = v
            if ob is not None:
                kw["onboarding"] = ob
            if not st.set_uiprofiles(**kw):
                return self._json(500, {"error": "設定寫不進本機資料夾"})
            return self._json(200, st.uiprofiles_info())
        if path == "/api/local/ui-desc":
            return self._uiprofiles("POST", body, None)
        if path == "/api/local/agent-loop":
            if not self._human():
                return self._json(403, {"error": "Agent 主迴圈的開關要你本人在 App 裡切"})
            v = body.get("on")
            if v is not None and not isinstance(v, bool):
                return self._json(400, {"error": "on 要是 true／false，或 null（回到預設）"})
            if not st.set_agentloop(v):
                return self._json(500, {"error": "設定寫不進本機資料夾"})
            return self._json(200, st.agentloop_info())
        if path == "/api/local/mcp-direct":
            if not self._human():
                return self._json(403, {"error": "Agent 直送要你本人在 App 裡切"})
            v = body.get("on")
            if v is not None and not isinstance(v, bool):
                return self._json(400, {"error": "on 要是 true／false，或 null（回到預設）"})
            if not st.set_mcp_direct(v):
                return self._json(500, {"error": "設定寫不進本機資料夾"})
            out = st.mcp_direct_info()
            if not out["on"]:
                try:
                    out["revoked"] = st.db.run(lambda c, u: approvals.revoke_direct(c, u))
                except Exception as e:
                    sys.stderr.write("[mcp_direct] revoke_failed %s\n" % type(e).__name__)
            return self._json(200, out)
        if path == "/api/local/agent-qc":
            if not self._human():
                return self._json(403, {"error": "主迴圈自動驗片（每鏡多一張驗片卡）要你本人在 App 裡切"})
            v = body.get("on")
            if v is not None and not isinstance(v, bool):
                return self._json(400, {"error": "on 要是 true／false，或 null（回到預設）"})
            if not st.set_agent_qc(v):
                return self._json(500, {"error": "設定寫不進本機資料夾"})
            return self._json(200, st.agent_qc_info())
        if path == "/api/local/frame-relay":
            if not self._human():
                return self._json(403, {"error": "首幀接力（會用你的金鑰上傳）要你本人在 App 裡切"})
            v = body.get("on")
            if v is not None and not isinstance(v, bool):
                return self._json(400, {"error": "on 要是 true／false，或 null（回到預設）"})
            if not st.set_frame_relay(v):
                return self._json(500, {"error": "設定寫不進本機資料夾"})
            return self._json(200, st.frame_relay_info())
        if path == "/api/local/film-settings":
            if not self._human():
                return self._json(403, {"error": "長片與接縫的開關（會影響花費與成片）要你本人在 App 裡切"})
            try:
                if not st.set_film_settings(body):
                    return self._json(500, {"error": "設定寫不進本機資料夾"})
            except film_settings.SettingsError as e:
                return self._json(400, {"error": str(e)})
            return self._json(200, film_settings.info(st.data_dir))
        if path in ("/api/local/agent/start", "/api/local/agent/step", "/api/local/agent/plan"):
            return self._agentloop(path.rsplit("/", 1)[1], body)
        if path == "/api/local/work/run":
            return self._work_run(body)
        if path == "/api/local/engine":
            if not self._human():
                return self._json(403, {"error": "匯出引擎要你本人在 App 裡切"})
            v = body.get("engine")
            if v is not None and v not in ENGINE_CHOICES:
                return self._json(400, {"error": "engine 只能是 %s，或 null（回到預設）" % "／".join(ENGINE_CHOICES)})
            if not st.set_engine(v):
                return self._json(500, {"error": "設定寫不進本機資料夾"})
            return self._json(200, st.engine_info())
        if path == "/api/local/concat-engine":
            if not self._human():
                return self._json(403, {"error": "接片引擎要你本人在 App 裡切"})
            v = body.get("engine")
            if v is not None and v not in CONCAT_ENGINES:
                return self._json(400, {"error": "engine 只能是 %s，或 null（回到預設）" % "／".join(CONCAT_ENGINES)})
            if not st.set_concat_engine(v):
                return self._json(500, {"error": "設定寫不進本機資料夾"})
            return self._json(200, st.concat_engine_info())
        if path == "/api/local/agent-scope":
            if not self._human():
                return self._json(403, {"error": "Agent 範圍要你本人在 App 裡切"})
            v = body.get("scope")
            if v is not None and v not in AGENT_SCOPES:
                return self._json(400, {"error": "scope 只能是 %s，或 null（回到預設）" % "／".join(AGENT_SCOPES)})
            if not st.set_agent_scope(v):
                return self._json(500, {"error": "設定寫不進本機資料夾"})
            return self._json(200, st.agent_scope_info())
        if path == "/api/qc" and (self._human() or st.agent_scope_now() == "full"):
            return self._qc(body)
        if path == "/api/qc/rate" and (self._human() or st.agent_scope_now() == "full"):
            return self._qc_rate(body)
        if path == "/api/payer/choice":
            return self._json(200, self._payer_state())
        if path == "/api/estimate":
            return self._estimate(body)
        if path == "/api/generate":
            return self._generate(body)
        if path == "/mcp":
            return self._mcp(body)
        if path == "/api/approvals":
            def batch(c, u):
                bid = approvals.make_batch(c, u, approvals.ids_for_batch(c, u, body))
                return approvals.batch_public(approvals.batch_cards(c, u, bid), self._card_link(bid), self._card_link)
            return self._approvals_run(batch)
        if path == "/api/approvals/decide":
            if not self._human():
                return self._json(403, {"error": "核准要你本人在 App 裡按"})
            if body.get("batch_id"):
                return self._approvals_run(lambda c, u: approvals.batch_public(
                    approvals.decide_batch(c, u, body["batch_id"], bool(body.get("approve"))),
                    self._card_link(body["batch_id"]), self._card_link))
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
                                            "shot": tp["shot"], "post": tp["post"], "negative_prompt": tp["negative_prompt"],
                                            "builtin_negative": tp["builtin_negative"], "warnings": tp["warnings"]})
                return self._store(studio_store.create_work, body.get("name"),
                                   [{"prompt": tp["prompt"], "seconds": tp["seconds"]}], meta)
            shots = body.get("shots")
            if shots is None and isinstance(body.get("script"), str):
                shots = studio_tools.parse_shots(body["script"], body.get("model"))
            if shots is None and isinstance(body.get("story"), str):
                shots = studio_tools.parse_shots(studio_tools.story_to_script(body["story"]), body.get("model"))
            if work_frames.on() and isinstance(shots, list):
                try:
                    per = work_frames.clean(shots)
                except work_frames.FramesError as e:
                    return self._json(400, {"error": str(e)})
                if any(per):
                    return self._work_create_framed(body.get("name"), shots, per)
            return self._store(studio_store.create_work, body.get("name"), shots)
        if path in ("/api/works/shot-edit", "/api/works/shot-move"):
            pid = str(body.get("project_id") or "")
            try:
                if path == "/api/works/shot-edit":
                    kw = {k: body[k] for k in ("prompt", "seconds") if k in body}
                    out = self.state.db.run(lambda c, u: studio_store.shot_edit(c, u, pid, body.get("shot"), body.get("expect"), **kw))
                    tool, args, note = "shot_edit", {"project_id": pid, "sids": [out["sid"]]}, "改了第 %d 鏡" % out["shot"]
                else:
                    out = self.state.db.run(studio_store.shot_move, pid, body.get("shot"), body.get("to"), body.get("expect_order"))
                    tool, args, note = "shot_move", {"project_id": pid, "order": out["order"]}, "第 %d 鏡搬到第 %d 鏡" % (out["from"], out["to"])
            except studio_store.StoreError as e:
                return self._json(e.code, e.body)
            if not self._human():
                self._activity_record(tool, note, out.get("sid"), args)
            return self._json(200, out)
        if path == "/api/works/clone":
            def go(c, u):
                src = studio_store.work_get(c, u, str(body.get("project_id") or ""))
                name, shots, meta, warn = templates.clone_plan(src, body.get("name"), body.get("fields"), body.get("shots"))
                return dict(studio_store.create_work(c, u, name, shots, meta), cloned_from=src["project_id"], warnings=warn)
            try:
                return self._json(200, self.state.db.run(go))
            except studio_store.StoreError as e:
                return self._json(e.code, e.body)
            except templates.TemplateError as e:
                return self._json(e.code, {"error": e.msg})
        if path == "/api/works/quote":
            tp = self._work_template(body.get("project_id"))
            if not isinstance(tp, dict):
                return tp
            sent = {}

            def capture(code, obj):
                sent["code"], sent["obj"] = code, obj
            self._json = capture
            try:
                self._generate(dict(tp["shot"], require_confirmation=True, approval_card=True))
            finally:
                del self._json
            out = sent.get("obj") if isinstance(sent.get("obj"), dict) else {"data": sent.get("obj")}
            out = dict(out, negative_prompt=tp["negative_prompt"], builtin_negative=tp["builtin_negative"],
                       warnings=tp["warnings"], resolution=tp["shot"]["resolution"], aspect_ratio=tp["shot"]["aspect_ratio"])
            return self._json(sent.get("code", 500), out)
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
            if "audio" in body:
                return self._transcribe_audio(body)
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
            text = body.get("text") or ""
            if not text and isinstance(body.get("story"), str):
                text = studio_tools.story_to_script(body["story"])
            return self._json(200, {"shots": studio_tools.parse_shots(text, body.get("model"))})
        if path == "/api/assets/update":
            return self._asset_update(body)
        if path in ("/api/assets/delete", "/api/assets/uploads", "/api/assets/uploads/complete"):
            return self._asset_upstream(path, body)
        if path in ("/api/image-outpaint", "/api/post-process"):
            if not self._human():
                return self._json(403, {"error": "畫面外擴、後處理的 Agent 版還沒開放：等使用者決定；請人在 App 裡按"})
            if path == "/api/post-process":
                try:
                    return self._json(200, st.call("/post-process", payload=body if isinstance(body, dict) else {},
                                                   timeout=GENERATE_TIMEOUT))
                except ConsoleError as e:
                    return self._err(e)
            return self._image_outpaint(body)
        if path == "/api/check-asset":
            return self._json(200, studio_tools.check_asset(body.get("url") or "", body.get("kind") or "image"))
        if path == "/api/captions":
            try:
                return self._json(200, studio_tools.build_captions(body))
            except studio_tools.ApiError as e:
                return self._json(e.code, {"error": str(e)})
        if path == "/api/store":
            key = (parse.parse_qs(u.query).get("key") or [""])[0]
            if "value" not in body:
                return self._json(400, {"error": "缺少 value"})
            value = body["value"]
            if key == UI_DESC_KEY:
                value, bad = ui_desc_value(value)
                if bad:
                    return self._json(*bad)
            if key.startswith("sb_") and isinstance(body.get("dirctl"), dict) and isinstance(value, list):
                if self._board_merge(key, value, body["dirctl"]):
                    return
            return self._store(studio_store.kv_put, key, value,
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

    def _cast_prepare(self, body):
        if body.get("cast") is None and "cast_shot" not in body and "controls" not in body:
            return body, None, None
        return cast_refs.prepare(body, lambda: self.state.db.run(
            lambda c, u: studio_store.kv_get(c, u, cast_refs.STORE_KEY))["value"])

    def _cast_shadow(self, shadow, got, path):
        try:
            pl = dict(shadow, require_confirmation=True) if path == "/videos/generations" else shadow
            q = self.state.call(path, payload=pl, timeout=GENERATE_TIMEOUT)
        except Exception as e:
            return cast_refs.shadow_log(got, None, err=type(e).__name__)
        return cast_refs.shadow_log(got, q)

    def _estimate(self, body):
        body = dict(body)
        body.pop("payer", None)
        if upstream.bad_seconds(body):
            return self._json(400, {"error": upstream.SECONDS_HINT})
        body, shadow, cast_info = self._cast_prepare(body)
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
        if cast_info is not None:
            if shadow is not None:
                cast_info["shadow"] = self._cast_shadow(shadow, r, "/quote")
            out["cast_refs"] = cast_info
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
        body, shadow, cast_info = self._cast_prepare(body)
        want_sheet = bool(body.get("require_confirmation"))
        try:
            sheet = st.call("/videos/generations", payload=dict(body, require_confirmation=True),
                            timeout=GENERATE_TIMEOUT)
        except ConsoleError as e:
            return self._err(e)
        if shadow is not None:
            cast_info["shadow"] = self._cast_shadow(shadow, sheet, "/videos/generations")
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
            if cast_info is not None:
                out["cast_refs"] = cast_info
            if want_card:
                out["approval"] = self._card_for_quote(qid, cost, open_ended, body, sheet)
                if self._direct_refused(out["approval"]):
                    return None
                if out["approval"].get("direct"):
                    out["direct"] = True
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
        self._record_charge(out.get("id"), qid)
        self._auto_take(out.get("id"), qid)
        return self._json(200, out)

    def _record_charge(self, job_id, qid):
        if not (isinstance(job_id, str) and JOB_ID_OK.match(job_id)):
            return

        def put(c, _u):
            with c.cursor() as cur:
                cur.execute("SELECT upstream_cost FROM local_quotes WHERE quote_id = %s", (qid,))
                row = cur.fetchone()
                cur.execute("INSERT INTO local_charges (job_id, quote_id, upstream_cost) VALUES (%s, %s, %s) "
                            "ON CONFLICT (job_id) DO NOTHING", (job_id, qid, row[0] if row else None))
        try:
            self.state.db.run(put)
        except Exception as e:
            sys.stderr.write("[charges] record_failed %s\n" % type(e).__name__)

    def _charges(self, ids):
        if not ids:
            return {}
        marks = ",".join(["%s"] * len(ids))

        def get(c, _u):
            with c.cursor() as cur:
                cur.execute("SELECT job_id, upstream_cost FROM local_charges WHERE job_id IN (%s)" % marks, tuple(ids))
                rows = {r[0]: r[1] for r in cur.fetchall()}
                cur.execute("SELECT job_id, status FROM approval_cards WHERE job_id IN (%s)" % marks, tuple(ids))
                cards = {r[0]: r[1] for r in cur.fetchall()}
            return rows, cards
        rows, cards = self.state.db.run(get)
        out = {}
        for j in ids:
            if j not in rows and j not in cards:
                continue
            st = {"failed": "released", "rejected": "released", "expired": "released"}.get(cards.get(j), "charged")
            out[j] = {"points": None, "status": st, "payer": "own_key", "upstream_cost": rows.get(j),
                      "reserved": None, "hold_status": None, "charged": None, "refunded": None}
        return out

    def _auto_take(self, job_id, qid):
        m = gen_retry.auto_mode()
        if m == "off" or not isinstance(job_id, str) or not job_id:
            return
        if not self._human():
            gen_retry.log("auto_take skipped:agent", job_id)
            return
        st = self.state
        try:
            card = st.db.run(lambda c, u: approvals.by_quote(c, u, qid))
            cid = (card or {}).get("id")
            if st.agent_loop_owns({"job_id": job_id, "approval_id": cid}):
                gen_retry.log("auto_take skipped:agent_loop", job_id)
                return
            r = st.db.run(lambda c, u: gen_retry.auto_take(c, u, job_id, cid, None, apply=(m == "on")))
        except Exception as e:
            gen_retry.log("auto_take error", type(e).__name__)
            return
        gen_retry.log("auto_take " + " ".join("%s=%s" % kv for kv in sorted(r.items())), job_id)

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

    def _decide_card(self, c, u, card):
        if not self._human() and self.state.mcp_direct_on():
            got, stop = approvals.try_direct(c, u, card)
            return dict(got, _direct_stop=stop) if stop else dict(got, _direct=True)
        return approvals.try_auto(c, u, card) or approvals.get(c, u, card["id"])

    def _card_public(self, card):
        out = dict(approvals.public(card, self._card_link(card["id"])), enabled=True)
        if card.get("_direct_stop"):
            out["direct_stop"] = list(card["_direct_stop"])
        elif card.get("_direct"):
            out["direct"] = True
        return out

    def _direct_refused(self, card):
        stop = (card or {}).get("direct_stop") if isinstance(card, dict) else None
        if not stop:
            return False
        self._json(stop[0], {"error": stop[1], "direct": True,
                             "approval": {k: v for k, v in card.items() if k != "direct_stop"}})
        return True

    def _card_for_quote(self, qid, cost, open_ended, body, sheet):
        charge = {"id": None, "quote_ref": qid, "kind": "video", "payer": "own_key", "points": None, "upstream_cost": cost}
        summ = dict(approvals.summary_of(body), **({"open_ended": True} if open_ended else {}))
        pl, q_exp = approvals.payload_for_card(body), approvals.quote_expiry(sheet)
        try:
            def go(c, u):
                card = approvals.create(c, user_id=u, charge=charge, summary=summ, payload=pl, quote_expires_at=q_exp)
                return self._decide_card(c, u, card)
            card = self.state.db.run(go)
        except Exception as e:
            return {"enabled": False, "error": "核准卡建不起來（%s），請重新報價" % type(e).__name__}
        return self._card_public(card)

    def _agent_card(self, kind, ref, cost, ttl, summary):
        charge = {"id": None, "quote_ref": ref, "kind": kind, "payer": "own_key", "points": None, "upstream_cost": cost}
        exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=ttl)
        summ = {k: v for k, v in (summary or {}).items() if v not in (None, "")}
        try:
            def go(c, u):
                card = approvals.create(c, user_id=u, charge=charge, summary=summ, expires_at=exp)
                return self._decide_card(c, u, card)
            card = self.state.db.run(go)
        except Exception as e:
            return {"enabled": False, "error": "核准卡建不起來（%s），請重新報價" % type(e).__name__}
        return self._card_public(card)

    def _spend_hold(self, kind, body, cost=None, summary=None):
        st = self.state
        if not st.key():
            return self._json(409, NO_KEY)
        ref = "sp_" + secrets.token_hex(12)
        with st.lock:
            now = time.monotonic()
            for k in [k for k, v in st.spend.items() if now - v["t"] > SPEND_TTL]:
                st.spend.pop(k, None)
            st.spend[ref] = {"kind": kind, "body": body, "t": now, "status": "quoted"}
        summ = summary or {"model": body.get("model"), "prompt": str(body.get("prompt") or "")[:280],
                           "n": body.get("n")}
        card = self._agent_card(kind, ref, cost, SPEND_TTL, summ)
        if self._direct_refused(card):
            with st.lock:
                st.spend.pop(ref, None)
            return None
        out = {"object": "%s.confirmation" % kind, "status": "needs_confirmation", "quote_id": ref,
               "kind": kind, "payer": "own_key", "expires_in": SPEND_TTL,
               "estimate": {"upstream_cost": str(cost) if cost is not None else None},
               "approval": card,
               "note": "要使用者核准這張卡（或在預先授權上限內），再用 submit_approved 送出"}
        if card.get("direct"):
            out["direct"] = True
            out["note"] = "Agent 直送：已在你設的上限內核准，直接用 submit_approved 送出"
        return self._json(200, out)

    def _spend_run(self, ref, kind):
        st = self.state
        with st.lock:
            got = st.spend.get(ref)
            if got is None or got["kind"] != kind or time.monotonic() - got["t"] > SPEND_TTL:
                return self._json(409, {"error": "找不到這張請求（或它已逾時、App 重開過），請重新報價"})
            if got["status"] != "quoted":
                return self._json(409, {"error": "這張請求已經送出過了，不能再送一次"})
            got["status"] = "sent"
        body = got["body"]
        if kind == "image":
            return self._image_generate(body)
        if kind == "cast_image":
            return self._cast_image(body)
        return self._qc_send(body)

    def _qc_frames(self, jid):
        st = self.state
        if not (st.ffmpeg and st.ffprobe):
            return None, "no_ffmpeg"
        try:
            path = os.path.join(st.media, self._cache_job(jid))
        except ConsoleError:
            return None, "no_video"
        env = st.openh264_env()
        try:
            r = subprocess.run([st.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
                               capture_output=True, timeout=60, env=env, stdin=subprocess.DEVNULL)
            dur = float((json.loads(r.stdout or b"{}").get("format") or {}).get("duration") or 0)
        except (OSError, ValueError, TypeError, subprocess.SubprocessError):
            dur = 0
        if dur <= 0:
            return None, "no_duration"
        frames = []
        for t in (0.15, 0.5, 0.9):
            try:
                r = subprocess.run([st.ffmpeg, "-nostdin", "-loglevel", "error", "-ss", "%.3f" % (dur * t), "-i", path,
                                    "-frames:v", "1", "-vf", "scale=512:512:force_original_aspect_ratio=decrease",
                                    "-q:v", "5", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                                   capture_output=True, timeout=60, env=env, stdin=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                return None, "ffmpeg_failed"
            if r.returncode != 0 or not r.stdout:
                return None, "ffmpeg_failed"
            f = "data:image/jpeg;base64," + base64.b64encode(r.stdout).decode()
            if len(f) > qc.MAX_FRAME_BYTES:
                return None, "frame_too_big"
            frames.append(f)
        return frames, None

    def _qc(self, body):
        body = dict(body) if isinstance(body, dict) else {}
        auto = None
        if "frames" not in body and isinstance(body.get("job"), str) and qc.JOB.match(body["job"]):
            frames, why = self._qc_frames(body["job"])
            if frames:
                body["frames"], auto = frames, "ok"
            else:
                sys.stderr.write("[qc] frames_auto=%s\n" % why)
                auto = why
        try:
            job, frames, expect = qc.check_request(body)
            cuts = qc.allow_cuts_of(body)
            count = qc.count_of(body)
        except qc.QCError as e:
            out = {"error": e.message}
            if auto:
                out["frames_auto"] = auto
            return self._json(e.code, out)
        send = {"job": job, "frames": frames, "expect": expect, "allow_cuts": cuts}
        if count:
            send["count"] = count
        if not self._human() and not getattr(self, "_via_card", False):
            cap = None
            try:
                listing, _ = self.state.models_cached()
                cap = qc.price_cap(qc.find_entry(listing, qc.MODEL), len(frames))
            except ConsoleError:
                pass
            return self._spend_hold("qc", send, cap, {"model": qc.MODEL, "prompt": "驗片 %s（%d 格）" % (job, len(frames)),
                                                      "frames": len(frames)})
        return self._qc_send(send)

    def _qc_rate(self, body):
        try:
            job, score, tags, comment = qc.check_rating(body)
        except qc.QCError as e:
            return self._json(e.code, {"error": e.message})
        send = {"request_id": job, "score": score, "tags": list(tags or [])}
        if comment:
            send["comment"] = comment
        try:
            got = self.state.call("/ratings", payload=send)
        except ConsoleError as e:
            return self._err(e)
        return self._json(200, {"job": job, "payer": "own_key", "rating": got})

    def _qc_send(self, send):
        st = self.state
        if not st.key():
            return self._json(409, NO_KEY)
        try:
            resp = st.call("/chat/completions", payload=qc.chat_payload(send["frames"], send["expect"],
                                                                        allow_cuts=send["allow_cuts"],
                                                                        count=send.get("count")),
                           timeout=GENERATE_TIMEOUT)
        except ConsoleError as e:
            return self._err(e, payer="own_key")
        v = qc.check_count(qc.parse_verdict(resp), send.get("count"))
        out = {"job": send["job"], "payer": "own_key", "model": qc.MODEL, "verdict": v}
        if v.get("ok"):
            out["rating"] = qc.to_rating(v)
        usage = resp.get("usage") if isinstance(resp, dict) and isinstance(resp.get("usage"), dict) else None
        if usage:
            out["usage"] = {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
        actual = qc.charged_of(resp)
        if actual is not None:
            out["upstream_cost"] = str(actual)
        retry = self._qc_retry_hook(send["job"], v)
        if retry is not None:
            out["retry"] = retry
        return self._json(200, out)

    def _takes(self, method, path, body, q):
        picker = "human" if self._human() else "agent"
        code, out = self.state.db.run(lambda c, u: takes.handle(c, u, method, path, body, q, picker))
        return self._json(code, out)

    def _dirctl_preview(self, body):
        if os.environ.get("STUDIO_LOCAL_DIRCTL", "on") == "off":
            return self._json(501, {"error": DIRCTL_OFF})
        from filming import dir_controls
        import shot_controls
        try:
            out = dir_controls.compose(body if isinstance(body, dict) else {}, apply_controls=shot_controls.apply)
        except (dir_controls.DirControlsError, shot_controls.ControlsError) as e:
            return self._json(400, {"error": str(e)})
        return self._json(200, {"prompt": out["prompt"], "warnings": out["warnings"]})

    def _dirctl_catalog_full(self, base):
        from filming import dir_controls as D
        base = dict(base, director={
            "sizes": dict(D.SIZE_IDS), "angles": dict(D.ANGLES), "xs": dict(D.XS), "depths": dict(D.DEPTHS),
            "facings": dict(D.FACINGS), "rigs": {k: list(v) for k, v in D.RIG_SIZES.items()},
            "limits": {"name": D.MAX_NAME, "note": D.MAX_NOTE, "notes": D.MAX_NOTES, "actors": D.MAX_ACTORS,
                       "prompt": D.MAX_PROMPT},
            "dc_keys": list(DC_KEYS), "blocking_keys": list(DC_BLOCK_KEYS)})
        return self._json(200, base)

    def _shot_dirctl(self, body):
        from filming import dir_controls as D
        import shot_controls
        body = body if isinstance(body, dict) else {}
        pid, shot = body.get("project_id"), body.get("shot")
        undo = body.get("undo") is True
        if not undo and "dc" not in body:
            return self._json(400, {"error": "要給 dc（物件，或 null＝清掉），或 undo: true"})
        new = body.get("dc")
        if not undo and new is not None:
            try:
                new = dict(dc_clean(new), by="agent")
                D.check(dc_desc(new))
                shot_controls.check(dc_controls(new))
            except (ValueError, shot_controls.ControlsError) as e:
                return self._json(400, {"error": "dc 不合法：%s" % e})

        def tx(conn, uid):
            studio_store._check_pid(pid)
            key = studio_store.board_key(pid)
            board = studio_store.kv_get(conn, uid, key).get("value")
            if not isinstance(board, list) or not board:
                raise studio_store.StoreError(404, "not_found", "找不到這部作品的分鏡")
            idx = _shot_index(board, shot)
            if idx is None:
                raise studio_store.StoreError(404, "no_shot", "這部作品沒有這一鏡（shot 用 1 起算的第幾鏡，或 sid）")
            sh = dict(board[idx])
            prev = sh.get("dc")
            nxt = sh.get("dc_prev") if undo else new
            sh.pop("dc", None)
            sh.pop("dc_prev", None)
            if nxt:
                sh["dc"] = nxt
            if prev:
                sh["dc_prev"] = prev
            board = list(board)
            board[idx] = sh
            studio_store.kv_put(conn, uid, key, board)
            return {"key": key, "shot": idx + 1, "sid": sh.get("sid"), "dc": sh.get("dc"), "prev": prev}
        try:
            out = self.state.db.run(tx)
        except studio_store.StoreError as e:
            return self._json(e.code, e.body)
        out["rev"] = self.state.bump_dirctl(out["key"], out.get("sid"))
        out["note"] = "已寫入這一鏡；送件時有 dc 就帶（跟畫面開關無關）。開著的導演台幾秒內自動重讀這一格"
        return self._json(200, out)

    def _shot_blocking(self, body):
        if not blocking_sync_on():
            return self._json(501, {"error": BLOCKING_SYNC_OFF})
        from filming import dir_controls as D, previs_blocking as PB
        import shot_controls
        body = body if isinstance(body, dict) else {}
        pid, shot, t = body.get("project_id"), body.get("shot"), body.get("t", 0)
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not 0 <= t <= 30:
            return self._json(400, {"error": "t 是第幾秒（0–30）"})

        def tx(conn, uid):
            studio_store._check_pid(pid)
            board = studio_store.kv_get(conn, uid, studio_store.board_key(pid)).get("value")
            if not isinstance(board, list) or not board:
                raise studio_store.StoreError(404, "not_found", "找不到這部作品的分鏡")
            idx = _shot_index(board, shot)
            if idx is None:
                raise studio_store.StoreError(404, "no_shot", "這部作品沒有這一鏡（shot 用 1 起算的第幾鏡，或 sid）")
            sh = board[idx] if isinstance(board[idx], dict) else {}
            key, legacy = previs_keys(pid, sh.get("sid"))
            scene = studio_store.kv_get(conn, uid, key).get("value") if key else None
            if not isinstance(scene, dict):
                old = studio_store.kv_get(conn, uid, legacy).get("value")
                scene = old.get(sh.get("sid")) if isinstance(old, dict) and sh.get("sid") else None
                key = legacy if isinstance(scene, dict) else key
            return idx, sh, key, scene
        try:
            idx, sh, key, scene = self.state.db.run(tx)
        except studio_store.StoreError as e:
            return self._json(e.code, e.body)
        if not isinstance(scene, dict):
            return self._json(404, {"error": "這一鏡還沒有 3D 預演場景（先在畫面上開 3D 預演擺好人偶）", "sid": sh.get("sid")})
        res = PB.blocking_from_scene(scene, t)
        prev = sh.get("dc") if isinstance(sh.get("dc"), dict) else None
        out = {"shot": idx + 1, "sid": sh.get("sid"), "scene_key": key, "t": t, "blocking": res["blocking"],
               "notes": res["notes"], "dc": None, "prev": prev}
        if not res["blocking"]:
            out["error"] = "預演裡沒有看得到、有名字的人偶" + ("：" + "、".join(res["notes"]) if res["notes"] else "")
            return self._json(200, out)
        dc = {k: v for k, v in (prev or {}).items() if k != "by"}
        dc["blocking"] = PB.merge((prev or {}).get("blocking"), PB.flat(res["blocking"]))
        try:
            dc = dc_clean(dc)
            D.check(dc_desc(dc))
            shot_controls.check(dc_controls(dc))
        except (ValueError, shot_controls.ControlsError) as e:
            out["error"] = "合併後的導演控制不合法：%s" % e
            return self._json(200, out)
        out["dc"] = dc
        return self._json(200, out)

    def _previs_from_dc(self, body):
        from filming import dir_controls as D
        body = body if isinstance(body, dict) else {}
        dur, aspect = body.get("dur", 5), body.get("aspect") or "16:9"
        if isinstance(dur, bool) or not isinstance(dur, (int, float)) or not 1 <= dur <= 30:
            return self._json(400, {"error": "dur 是秒數（1–30）"})
        if not isinstance(aspect, str) or not re.match(r"^\d{1,2}:\d{1,2}$", aspect):
            return self._json(400, {"error": "aspect 要像 16:9"})
        try:
            dc = dc_clean(body.get("dc"))
            if not dc.get("blocking"):
                return self._json(400, {"error": "這一鏡的導演控制沒有站位（blocking）"})
            scene = D.to_scene(dc_desc(dc), dur=dur, aspect=aspect)
        except (ValueError, KeyError, TypeError) as e:
            return self._json(400, {"error": str(e) or type(e).__name__})
        return self._json(200, {"scene": scene})

    def _board_merge(self, key, value, meta):
        st = self.state
        sent = meta.get("rev")
        touched = {x for x in (meta.get("touched") or []) if isinstance(x, str)}
        with st.dirctl_lock:
            cur = st.dirctl_revs.get(key, 0)
            written = dict(st.dirctl_writes.get(key) or {})
        if not isinstance(sent, int) or isinstance(sent, bool) or sent >= cur:
            return False
        late = {sid for sid, r in written.items() if r > sent}

        def tx(conn, uid):
            srv = studio_store.kv_get(conn, uid, key).get("value")
            out, merged = studio_store.merge_shots(value, srv, late, touched, studio_store.DC_FIELDS, studio_store.DC_PREV)
            r = studio_store.kv_put(conn, uid, key, out)
            return {"ok": True, "bytes": r["bytes"], "rev": cur, "merged": merged}
        try:
            self._json(200, st.db.run(tx))
        except studio_store.StoreError as e:
            self._json(e.code, e.body)
        return True

    def _previs_rig(self, body):
        if os.environ.get("STUDIO_LOCAL_PREVIS_RIG", "on") == "off":
            return self._json(501, {"error": PREVIS_RIG_OFF})
        from filming import camera_rigs
        body = body if isinstance(body, dict) else {}
        scene, spec = body.get("scene"), body.get("spec")
        if not isinstance(scene, dict) or not isinstance(scene.get("objs"), list):
            return self._json(400, {"error": "scene 要是 3D 預演的場景"})
        try:
            return self._json(200, camera_rigs.rig(scene, spec))
        except (ValueError, KeyError, TypeError, IndexError) as e:
            return self._json(400, {"error": str(e) or type(e).__name__})

    def _uiprofiles(self, method, body, query):
        st = self.state
        if not st.uiprofiles_on():
            return self._json(501, {"error": UI_PROFILES_OFF})
        import ui_profiles
        code, out = ui_profiles.handle(method, body, who="human" if self._human() else "agent", data_dir=st.data_dir,
                                       put=lambda k, v: st.db.run(studio_store.kv_put, k, v),
                                       get=lambda k: st.db.run(studio_store.kv_get, k)["value"],
                                       query=query, onboarding=st.uiprofiles_onboarding())
        return self._json(code, out)

    def _agentloop(self, op, body):
        if not self.state.agentloop_on():
            return self._json(501, {"error": AGENT_LOOP_OFF})
        return self._json(*self._agentloop_call(op, body))

    def _agentloop_call(self, op, body):
        code, out = self._agentloop_call0(op, body)
        if code == 200 and isinstance(out, dict):
            self._check_media(out.get("action"))
            if (out.get("summary") or {}).get("phase") == "done" and out.get("run"):
                self._film_sync_run(out)
        return code, out

    def _film_sync_run(self, out):
        try:
            got = self._film_picks(out["run"])
            if got:
                sync = self._film_sync(got[0], got[2], got[1])
                if sync:
                    out["mainline"] = sync
        except Exception as e:
            out["mainline"] = {"synced": 0, "unmatched": 0, "error": "寫回主線失敗：%s" % e}

    def _check_media(self, act):
        if not (isinstance(act, dict) and act.get("do") == "check" and isinstance(act.get("take"), str)):
            return
        try:
            t = self.state.db.run(lambda c, u: takes.get(c, u, act["take"]))
            job = (t or {}).get("job_id")
            if not (isinstance(job, str) and JOB_ID_OK.match(job)):
                return
            act["job_id"] = job
            act["path"] = self._media_named(self._cache_job(job))[0]
        except Exception as e:
            sys.stderr.write("[agent] check_media %s\n" % type(e).__name__)

    def _agentloop_call0(self, op, body):
        if op in ("plan", "start") and isinstance(body, dict) and isinstance(body.get("model"), str) and body["model"].strip():
            if op == "plan":
                code, out = self._agentloop_raw("plan", body)
                return (self._seconds_gate(body["model"].strip(), out) if code == 200 else (code, out))
            code, out = self._agentloop_raw("plan", {k: v for k, v in body.items() if k not in ("payload_extra", "shot_frames")})
            if code == 200:
                code2, gated = self._seconds_gate(body["model"].strip(), out)
                if code2 != 200:
                    return code2, gated
                body, made = self._agent_project(body)
                code, out = self._agentloop_raw("start", body)
                if code == 200 and made:
                    out = dict(out, project_id=made, project_created=True)
                if code == 200 and gated.get("seconds_warning"):
                    out = dict(out, seconds_rule=gated["seconds_rule"], seconds_warning=gated["seconds_warning"])
                return code, out
            return code, out
        return self._agentloop_raw(op, body)

    def _agent_project(self, body):
        if isinstance(body.get("project_id"), str) and body["project_id"].strip():
            return body, None
        stamp = datetime.datetime.now().strftime("%m-%d %H:%M:%S")
        name = "Agent 拍片：%s（%s）" % (str(body.get("request") or "").strip()[:30] or "未命名", stamp)
        try:
            got = self.state.db.run(studio_store.create_project, name)
        except studio_store.StoreError as e:
            sys.stderr.write("[agent] project_create_failed %s\n" % type(e).__name__)
            return body, None
        pid = (got or {}).get("id") if isinstance(got, dict) else None
        return (dict(body, project_id=pid), pid) if pid else (body, None)

    def _seconds_gate(self, model, planned):
        cons = self.state.model_constraints(model)
        bad, rule = [], None
        for i, seg in enumerate(planned.get("segments") or [], 1):
            why, rule = studio_tools.check_seconds(model, seg.get("seconds"), cons)
            if why:
                bad.append("第 %d 鏡 %g 秒：%s" % (i, float(seg["seconds"]), why))
        rule = rule or studio_tools.seconds_rule(model, cons)
        if bad:
            return 400, {"error": "；".join(bad), "seconds_rule": rule}
        out = dict(planned, seconds_rule=rule)
        if rule["source"] == "table-default":
            out["seconds_warning"] = "目錄裡讀不到 %s 收幾秒，先照一般的 4–15 秒；送件時上游會再檢查一次" % model
        return 200, out

    def _agentloop_raw(self, op, body):
        st = self.state
        import agent_exec
        cli = os.path.join(ROOT, "cli")
        if cli not in sys.path:
            sys.path.insert(0, cli)
        from appletoken.core import model_caps
        try:
            vid_of = lambda job: os.path.join(st.media, self._cache_job(job))
            code, out = agent_exec.handle(op, body if isinstance(body, dict) else {}, data_dir=st.data_dir,
                                          env=film_settings.effective_env(st.data_dir),
                                          port=self.port, secret=st.agent_loop, caps_of=model_caps.caps,
                                          frames=model_caps.frames_payload, ffmpeg=st.ffmpeg, video_of=vid_of,
                                          relay=(lambda take: frame_relay(st, vid_of, take)) if st.frame_relay_on() else None,
                                          auto_qc=st.agent_qc_on(), seam=lambda prev, job: seam_ssim(st, vid_of, prev, job))
        except agent_exec.fexec.ExecutorError as e:
            return 502, {"error": str(e).replace(st.agent_loop, "…")}
        return code, out

    WORK_RUN_STEPS = 6

    def _work_run(self, body):
        st = self.state
        if not st.agentloop_on():
            return self._json(501, {"error": AGENT_LOOP_OFF})
        b = body if isinstance(body, dict) else {}
        bad = set(b) - {"project_id", "model", "run", "event", "decision"}
        if bad:
            return self._json(400, {"error": "work_run 不收這些欄位：%s" % "、".join(sorted(bad))})
        if b.get("run"):
            if b.get("project_id") or b.get("model"):
                return self._json(400, {"error": "續跑只帶 run（和 event 或 decision），不再帶 project_id／model"})
            if b.get("event") is not None and b.get("decision") is not None:
                return self._json(400, {"error": "event 與 decision 一次只給一個"})
            step = {k: b[k] for k in ("run", "event", "decision") if b.get(k) is not None}
            code, out = self._agentloop_call("step", step)
        else:
            start, why = self._work_start_body(b)
            if why:
                return self._json(*why)
            code, out = self._agentloop_call("start", start)
            if code == 400 and isinstance(out.get("error"), str):
                out = dict(out, error=re.sub(r"segments\[(\d+)\]", lambda m: "第 %d 鏡" % (int(m.group(1)) + 1), out["error"]))
        if code != 200:
            return self._json(code, out)
        for _ in range(self.WORK_RUN_STEPS):
            if (out.get("action") or {}).get("do") not in ("generate", "wait_refund", "wait_blockout"):
                break
            code, nxt = self._agentloop_call("step", {"run": out["run"]})
            if code != 200:
                return self._json(code, dict(nxt, run=out["run"]))
            out = nxt
        return self._json(200, self._work_reply(out))

    def _work_create_framed(self, name, shots, per):
        def go(c, u):
            out = studio_store.create_work(c, u, name, shots)
            board = studio_store.kv_get(c, u, out["board_key"]).get("value")
            got = work_frames.by_sid(board, per)
            studio_store.kv_put(c, u, work_frames.key(out["project_id"]), got)
            return dict(out, frames=len(got))
        try:
            return self._json(200, self.state.db.run(go))
        except studio_store.StoreError as e:
            return self._json(e.code, e.body)

    def _work_start_body(self, b):
        pid = b.get("project_id")
        if not isinstance(pid, str) or not pid:
            return None, (400, {"error": "要給 project_id（作品）或 run（續跑）"})
        try:
            work = self.state.db.run(lambda c, u: studio_store.work_get(c, u, pid))
        except studio_store.StoreError as e:
            return None, (e.code, e.body)
        name = work.get("name") or "作品"
        if work.get("template"):
            try:
                tp = templates.build(work["template"], work.get("fields") or {})
            except templates.TemplateError as e:
                return None, (e.code, {"error": e.msg})
            shot = tp["shot"]
            extra = {k: shot[k] for k in ("negative_prompt", "generate_audio") if shot.get(k) is not None}
            if work_frames.on():
                extra.update({k: shot[k] for k in work_frames.FRAME_KEYS if shot.get(k) is not None})
            return {"request": "拍「%s」" % name, "project_id": pid, "model": shot["model"],
                    "resolution": shot.get("resolution"), "aspect_ratio": shot.get("aspect_ratio"),
                    "input": {"version": 1, "segments": [{"prompt": shot["prompt"], "seconds": shot["seconds"]}]},
                    "payload_extra": extra}, None
        model = b.get("model")
        if not isinstance(model, str) or not model.strip():
            return None, (400, {"error": "這部作品不是範本作品：要給 model（模型 ref，例如 list_models 列出來的）"})
        shots = work.get("shots") or []
        if not shots:
            return None, (400, {"error": "這部作品還沒有分鏡"})
        segs = []
        for i, s in enumerate(shots, 1):
            if not str(s.get("prompt") or "").strip():
                return None, (400, {"error": "第 %d 鏡沒有提示詞" % i})
            if s.get("seconds") is None or upstream.bad_seconds({"seconds": s.get("seconds")}):
                return None, (400, {"error": "第 %d 鏡的秒數不對（%r）" % (i, s.get("seconds"))})
            segs.append({"prompt": s["prompt"], "seconds": s["seconds"]})
        out = {"request": "拍「%s」" % name, "project_id": pid, "model": model.strip(),
               "input": {"version": 1, "segments": segs}}
        if work_frames.on():
            try:
                stored = self.state.db.run(lambda c, u: studio_store.kv_get(c, u, work_frames.key(pid))).get("value")
            except studio_store.StoreError as e:
                return None, (e.code, e.body)
            frames = work_frames.for_run(shots, stored)
            if frames:
                out["shot_frames"] = frames
        return out, None

    def _work_reply(self, out):
        run, act = out.get("run"), out.get("action") or {}
        do = act.get("do")
        rep = {"run": run, "summary": out.get("summary"), "notes": out.get("notes") or []}
        if do == "done":
            code, film = self._capture(self._agent_film, run)
            rep.update(phase="done", next="拍完了：每一鏡的版本、定稿與接好的成片在 film（換定稿用 agent_pick）")
            rep["film"] = film if code == 200 else {"error": film.get("error")}
        elif do == "stopped":
            rep.update(phase="failed", reason="stopped", next="這一次拍片停了；要重來就用 project_id 再開一次")
        elif do == "check":
            rep.update({k: act[k] for k in ("job_id", "path") if act.get(k)})
            rep.update(phase="needs_check", reason="check", shot_key=act.get("shot_key"),
                       next="看這一鏡的片（take %s）之後回報：work_run(run, event={type:'checked', reports:[{block:'qc', ok:true／false, "
                            "defects:[…]}]})；或請使用者打開自動驗片" % act.get("take"))
        elif do == "ask":
            reason = act.get("reason")
            rep.update(phase="waiting_human", reason=reason, options=act.get("options"))
            if act.get("approve_url"):
                rep["approve_url"] = act["approve_url"]
            if reason == "card_pending":
                rep["next"] = "請使用者在 App 核准這張卡（approve_url）之後，再呼叫 work_run(run, decision='resume')"
            elif reason == "over_limit":
                rep["next"] = "Agent 直送被上限擋下：把原因（detail）原話轉給使用者，請他到設定調高上限，再 work_run(run, decision='resume')"
            elif reason == "retakes_exhausted":
                rep["next"] = "這一鏡重做用完了：work_run(run, decision='accept_best') 用最好的那一版，或 decision='stop'"
            else:
                rep["next"] = "照 options 回覆：work_run(run, decision=…)"
            rep["detail"] = act.get("detail")
        else:
            reason = {"wait_refund": "waiting_refund", "wait_blockout": "waiting_blockout"}.get(do, "generating")
            rep.update(phase="running", reason=reason, next="還在跑：過一會兒再呼叫 work_run(run) 繼續")
        return rep

    def _capture(self, fn, *args):
        sent = {}
        saved = self.__dict__.pop("_json", None)
        self._json = lambda code, obj, *a, **k: sent.update(code=code, obj=obj)
        try:
            fn(*args)
        finally:
            del self._json
            if saved is not None:
                self._json = saved
        return sent.get("code", 500), sent.get("obj") or {}

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
                card = approvals.try_auto(c, u, card) or card
                return approvals.public(card, self._card_link(card["id"]))
            if status and status not in approvals.STATUSES:
                raise approvals.ApprovalError(400, "status 不合法")
            items = approvals.reapply_auto(c, u, approvals.list_cards(c, u, status or None))
            return {"items": [approvals.public(x, self._card_link(x["id"])) for x in items]}
        return self._approvals_run(go)

    def _approvals_batch_get(self, bid):
        def go(c, u):
            cards = approvals.batch_cards(c, u, bid)
            if not cards:
                raise approvals.ApprovalError(404, "找不到這一批")
            return approvals.batch_public(cards, self._card_link(bid), self._card_link)
        return self._approvals_run(go)

    def _approvals_limits(self, body):
        def go(c, u):
            lim = approvals.limits_set(c, u, body) if body is not None else approvals.limits_get(c, u)
            return dict(lim, used_today_points=approvals.fmt(approvals.used_today(c, u, "points")),
                        used_today_upstream=approvals.fmt(approvals.used_today(c, u, "upstream")),
                        auto_today_points=approvals.fmt(approvals.used_today_auto(c, u, "points")),
                        auto_today_upstream=approvals.fmt(approvals.used_today_auto(c, u, "upstream")))
        return self._approvals_run(go)

    def _approval_submit(self, body):
        st = self.state
        try:
            card = st.db.run(lambda c, u: approvals.claim_for_submit(c, u, body.get("id"), body.get("expect_amount"),
                                                                      direct_on=st.mcp_direct_on()))
        except approvals.ApprovalError as e:
            return self._json(e.code, {"error": e.message})
        if card.get("payload") and approvals.quote_stale(card):
            card, stop = self._approval_requote(card)
            if stop is not None:
                return self._json(*stop)
        code, obj = self._approval_confirm(card)
        if card.get("payload") and approvals.upstream_says_expired(code, obj):
            card, stop = self._approval_requote(card)
            if stop is not None:
                return self._json(*stop)
            code, obj = self._approval_confirm(card)
        ok = 200 <= code < 300
        jid = obj.get("id") if isinstance(obj, dict) else None
        card = st.db.run(lambda c, u: (approvals.mark_result(c, u, card["id"], job_id=jid) if ok else
                                      approvals.mark_result(c, u, card["id"], error=(obj or {}).get("error") or "HTTP %s" % code),
                                      approvals.get(c, u, card["id"]))[1])
        out = dict(obj) if isinstance(obj, dict) else {"data": obj}
        out["approval"] = approvals.public(card, self._card_link(card["id"]))
        return self._json(code, out)

    def _gen_retry_hook(self, vid, s):
        m = gen_retry.mode()
        if m == "off" or not gen_retry.terminal(s):
            return None
        try:
            cs = "released" if gen_retry.own_key_refunded(s) else None
            if self._agent_loop_skip(vid):
                return None
            p = self.state.db.run(lambda c, u: gen_retry.plan(c, u, vid, s, cs))
        except Exception as e:
            gen_retry.log("error", type(e).__name__)
            return None
        return self._gen_retry_after(m, p)

    def _gen_retry_after(self, m, p):
        if p is None:
            return None
        if not p.get("retake"):
            gen_retry.log("stop=" + p["stop"], p.get("take") or "")
            return gen_retry.public(dict(p, state="stopped")) if m == "on" else None
        if m == "shadow":
            gen_retry.log("shadow would_retry", "%s %s" % (p["take"]["id"], p.get("reason") or ""))
            return None
        try:
            out = self._gen_retry_send(p)
        except Exception as e:
            gen_retry.log("error", type(e).__name__)
            return None
        gen_retry.log("state=" + out.get("state", "?"), p["take"]["id"])
        return gen_retry.public(out)

    def _agent_loop_skip(self, job):
        st = self.state
        if not st.agentloop_on():
            return False
        t = st.db.run(lambda c, u: takes.by_job(c, u, job))
        if st.agent_loop_owns(t):
            gen_retry.log("skipped:agent_loop", t["id"])
            return True
        return False

    def _qc_retry_hook(self, job, verdict):
        m = gen_retry.qc_mode()
        if m == "off":
            return None
        try:
            if self._agent_loop_skip(job):
                return None
            p = self.state.db.run(lambda c, u: gen_retry.qc_plan(c, u, job, verdict))
        except Exception as e:
            gen_retry.log("error", type(e).__name__)
            return None
        saved = {k: self.__dict__.pop(k) for k in ("_json", "_via_card") if k in self.__dict__}
        try:
            return self._gen_retry_after(m, p)
        finally:
            self.__dict__.update(saved)

    def _gen_retry_send(self, p):
        st = self.state
        sent = {}

        def capture(code, obj):
            sent["code"], sent["obj"] = code, obj
        self._json = capture
        try:
            self._generate(dict(p["payload"], require_confirmation=True, approval_card=True))
        finally:
            del self._json
        card = (sent.get("obj") or {}).get("approval") if isinstance(sent.get("obj"), dict) else None
        if not (isinstance(card, dict) and card.get("id")):
            return {"state": "stopped", "stop": "quote_failed", "take": p["take"]["id"]}
        jid = None
        if card.get("status") == "approved":
            try:
                c = st.db.run(lambda cn, u: approvals.claim_for_submit(cn, u, card["id"], card.get("amount"),
                                                                       direct_on=st.mcp_direct_on()))
                stop = None
                if c.get("payload") and approvals.quote_stale(c):
                    c, stop = self._approval_requote(c)
                code, obj = stop if stop is not None else self._approval_confirm(c)
                ok = 200 <= code < 300 and stop is None
                jid = obj.get("id") if ok and isinstance(obj, dict) else None
                if ok:
                    st.db.run(lambda cn, u: approvals.mark_result(cn, u, c["id"], job_id=jid))
                elif stop is None:
                    st.db.run(lambda cn, u: approvals.mark_result(cn, u, c["id"], error=(obj or {}).get("error") or "HTTP %s" % code))
                card = approvals.public(st.db.run(lambda cn, u: approvals.get(cn, u, c["id"])), self._card_link(c["id"]))
            except approvals.ApprovalError as e:
                gen_retry.log("submit_refused", str(e.code))
        t = st.db.run(lambda cn, u: gen_retry.record(cn, u, p["take"], card["id"], jid, p.get("reason") or gen_retry.GEN_REASON))
        return {"state": "resubmitted" if jid else "waiting_approval", "take": t["id"], "reason": p.get("reason"),
                "approval_id": card["id"],
                "approval_status": card.get("status"), "job_id": jid, "approve_url": card.get("approve_url")}

    def _approval_confirm(self, card):
        sent = {}

        def capture(code, obj):
            sent["code"], sent["obj"] = code, obj

        self._json = capture
        self._via_card = True
        kind = card.get("kind") or "video"
        try:
            if kind == "video":
                self._confirm(card["quote_ref"], True)
            elif kind == "storyboard":
                self._storyboard({"quote_id": card["quote_ref"], "confirm": True})
            elif kind in ("tts", "music"):
                self._audio_confirm(card["quote_ref"], True, kind)
            elif kind in ("image", "cast_image", "qc"):
                self._spend_run(card["quote_ref"], kind)
            else:
                capture(409, {"error": "本機不認得這種核准卡（%s）" % kind})
        finally:
            del self._json
            self._via_card = False
        return sent.get("code", 500), sent.get("obj") or {"error": "送件沒有回應"}

    def _approval_requote(self, card):
        st = self.state

        def fail(code, msg):
            msg = approvals.err_text(msg)
            c = st.db.run(lambda c, u: (approvals.mark_result(c, u, card["id"], error="重新報價失敗：" + msg),
                                        approvals.get(c, u, card["id"]))[1])
            return c, (code, {"error": "報價過期了，重新報價失敗：" + msg,
                              "approval": approvals.public(c, self._card_link(c["id"]))})
        if card["payer"] != "own_key":
            return fail(409, "本機模式只能用你自己的金鑰付款")
        pl = card["payload"]
        try:
            sheet = st.call("/videos/generations", payload=dict(pl, require_confirmation=True), timeout=GENERATE_TIMEOUT)
        except ConsoleError as e:
            return fail(e.code if 400 <= e.code < 600 else 502, getattr(e, "body", None) or str(e))
        if not (isinstance(sheet, dict) and sheet.get("quote_id") and isinstance(sheet.get("estimate"), dict)):
            return fail(502, "上游沒有回確認單")
        qid, cost = str(sheet["quote_id"]), (sheet.get("estimate") or {}).get("points")
        open_ended = upstream.has_video_ref(pl)
        with st.lock:
            st.quotes[qid] = {"open_ended": open_ended, "status": "quoted", "t": time.monotonic()}
            old = st.quotes.get(card["quote_ref"])
            if old is not None and old["status"] == "quoted":
                old["status"] = "cancelled"
        charge = {"id": None, "quote_ref": qid, "kind": "video", "payer": "own_key", "points": None, "upstream_cost": cost}

        def go(c, u):
            c.cursor().execute("INSERT INTO local_quotes (quote_id, payload, upstream_cost) VALUES (%s, %s, %s)"
                               " ON CONFLICT (quote_id) DO NOTHING",
                               (qid, json.dumps({"open_ended": open_ended}), str(cost) if cost is not None else None))
            return approvals.apply_requote(c, u, card, charge, approvals.quote_expiry(sheet))
        c, why = st.db.run(go)
        if why:
            return c, (409, {"error": why, "repriced": True, "approval": approvals.public(c, self._card_link(c["id"]))})
        return c, None

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
        if got["at"] is None and got.get("candidates"):
            got["note"] = ("沒把握：最可能是 %.2f 秒（candidates 第一個），請讓使用者確認，匯出時用 overrides.twist.at 指定"
                           % got["candidates"][0]["t"])
        elif got["at"] is None:
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
        if ov.get("captions") == "none":
            ov = {k: v for k, v in ov.items() if k != "captions"}
            body = dict(body, captions="none")
        post.update(ov)
        if "captions" in body:
            if body["captions"] != "none":
                return self._json(400, {"error": "captions 只能是 \"none\"（不燒字卡）；要改字卡內容請用 overrides.captions"})
            post["captions"] = []
        req = {"project_id": body.get("project_id"), "format": post["format"],
               "video": [{"job": jid, "in": 0, "out": float(tp["seconds"])}], "audio": [{"lane": "A1", "job": jid, "at": 0, "in": 0,
               "dur": float(tp["seconds"])}], "cues": [], "subtitles": "none", "disclosure": {"on": False},
               "captions": post["captions"], "effects": post["effects"], "twist": post["twist"]}
        if "pipeline" in body:
            req["pipeline"] = body["pipeline"]
        if body.get("dry_run") is True:
            req.pop("project_id", None)
            return self._pipeline_preview(req)
        return self._export_start(req)

    def _local_result(self, jid):
        if not JOB_ID_OK.match(jid or ""):
            return self._json(400, {"error": "job id 不合法"})
        try:
            name = self._cache_job(jid)
        except ConsoleError as e:
            return self._err(e, with_hints=False)
        path, ctype = self._media_named(name)
        return self._json(200, {"path": path, "content_type": ctype, "src": "/api/download?id=" + jid})

    MEDIA_EXT = {"video/mp4": ".mp4", "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav", "image/png": ".png",
                 "image/jpeg": ".jpg", "image/webp": ".webp"}

    def _media_named(self, sha):
        base = os.path.join(self.state.media, sha)
        ctype = "video/mp4"
        try:
            with open(base + ".json", encoding="utf-8") as f:
                ctype = json.load(f).get("mime") or ctype
        except (OSError, ValueError, AttributeError):
            pass
        ext = self.MEDIA_EXT.get(ctype)
        if not ext:
            return base, ctype
        named = base + ext
        try:
            if not os.path.exists(named):
                os.link(base, named)
        except FileExistsError:
            pass
        except OSError:
            return base, ctype
        return named, ctype

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
            bad = isinstance(out, dict) and bool(out.get("error"))
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
        if not self._human() and not getattr(self, "_via_card", False):
            return self._spend_hold("image", body)
        started = int(time.time())
        try:
            send = self._inline(dict(body))
            r = st.call("/images/generations", payload=send, timeout=IMAGE_TIMEOUT)
        except ConsoleError as e:
            lost = e.timed_out or e.code == 504
            if lost or _dropped(e):
                got, outcome = self._image_recover(body, started)
                if got is None:
                    return self._image_lost(body, started, outcome) if lost or outcome else self._err(e)
                r = dict(got, recovered=True)
            else:
                return self._err(e)
        out = dict(r) if isinstance(r, dict) else {"data": r}
        out["payer"] = "own_key"
        return self._json(200, out)

    def _cast_image(self, body):
        st = self.state
        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return self._json(400, {"error": "先寫外觀描述，或寫要生什麼"})
        if not self._human() and not getattr(self, "_via_card", False):
            return self._spend_hold("cast_image", dict(body))
        n = body.get("n") if isinstance(body.get("n"), int) and 1 <= body.get("n") <= 4 else 1
        model = body.get("model") if isinstance(body.get("model"), str) and body["model"].strip() else CAST_IMAGE_DEFAULT
        name = str(body.get("name") or "ref").strip()[:60] or "ref"
        send = {"model": model.strip(), "prompt": prompt.strip(), "n": n, "response_format": "b64_json"}
        started = int(time.time())
        try:
            r = st.call("/images/generations", payload=send, timeout=IMAGE_TIMEOUT)
        except ConsoleError as e:
            lost = e.timed_out or e.code == 504
            if lost or _dropped(e):
                r, outcome = self._image_recover(send, started)
                if r is None:
                    return self._image_lost(send, started, outcome) if lost or outcome else self._err(e)
            else:
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

    def _transcribe_audio(self, body):
        st = self.state
        m = AUDIO_DATA.match(body["audio"]) if isinstance(body.get("audio"), str) else None
        if not m:
            return self._json(400, {"error": "錄音要是 audio/webm、audio/ogg 或 audio/wav 的 data URL"})
        try:
            raw = base64.b64decode(m.group(2), validate=True)
        except (binascii.Error, ValueError):
            return self._json(400, {"error": "錄音的內容解不開"})
        if not raw:
            return self._json(400, {"error": "錄音是空的"})
        if len(raw) > ASR_MAX:
            return self._json(413, {"error": "錄音太長（超過上游 10MB 的上限，約 5 分鐘）"})
        if not st.ffmpeg:
            return self._json(409, {"error": "轉錄要先把錄音轉成 wav，這台找不到 ffmpeg"})
        model = body.get("model") if isinstance(body.get("model"), str) and body["model"].strip() else ASR_DEFAULT
        work = tempfile.mkdtemp(prefix="asr-", dir=st.data_dir)
        try:
            src = os.path.join(work, "in" + AUDIO_EXT[m.group(1)])
            with open(src, "wb") as f:
                f.write(raw)
            wav = os.path.join(work, "a.wav")
            p = subprocess.run([st.ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", src, "-vn", "-ac", "1",
                                "-ar", "16000", "-c:a", "pcm_s16le", wav], capture_output=True, timeout=120)
            if p.returncode != 0 or not os.path.exists(wav):
                return self._json(400, {"error": "錄音讀不出來（格式不對或檔案壞了）"})
            if os.path.getsize(wav) <= 44:
                return self._json(200, {"text": "", "note": "錄音裡沒有聲音"})
            if os.path.getsize(wav) > ASR_MAX:
                return self._json(413, {"error": "錄音太長（超過上游 10MB 的上限，約 5 分鐘）"})
            with open(wav, "rb") as f:
                data = "data:audio/wav;base64," + base64.b64encode(f.read()).decode()
        except (OSError, subprocess.SubprocessError):
            return self._json(500, {"error": "處理錄音失敗"})
        finally:
            shutil.rmtree(work, ignore_errors=True)
        try:
            r = st.call("/audio/transcriptions", payload={"model": model.strip(), "file": data,
                                                          "response_format": "json"}, timeout=GENERATE_TIMEOUT)
        except ConsoleError as e:
            return self._err(e)
        text = r.get("text") if isinstance(r, dict) else None
        return self._json(200, {"text": text if isinstance(text, str) else "", "payer": "own_key"})

    def _place_blocked(self, ids):
        st = self.state
        seen = st.workbench_open
        if not seen or time.monotonic() - seen[1] > OPEN_FRESH:
            return None
        open_pid = seen[0]
        try:
            kv = st.db.run(studio_store.kv_get_many, ["simple_works", "jobs"])
            projects = st.db.run(studio_store.list_projects)
        except studio_store.StoreError:
            return None
        uids = {}
        for j in kv.get("jobs") or []:
            if isinstance(j, dict) and j.get("id") and j.get("uid"):
                uids.setdefault(str(j["id"]), set()).add(str(j["uid"]))
        owners = {}
        for pid, w in (kv.get("simple_works") or {}).items():
            for x in (w.get("jobs") if isinstance(w, dict) and isinstance(w.get("jobs"), list) else []):
                if isinstance(x, dict) and x.get("uid"):
                    owners.setdefault(str(x["uid"]), set()).add(str(pid).lower())
        names = {str(p.get("id", "")).lower(): p.get("name") or "未命名" for p in projects.get("projects") or [] if isinstance(p, dict)}
        for jid in ids:
            pids = set().union(*[owners.get(u, set()) for u in uids.get(jid, ())])
            if not pids or open_pid in pids:
                continue
            pid = sorted(pids)[0]
            name = names.get(pid, "未命名")
            where = "工作台現在沒有開著作品" if not open_pid else "工作台現在開著的是另一部作品"
            return {"error": "這支片（%s）屬於作品「%s」，%s：請先開啟「%s」再放進剪輯軌" % (jid, name, where, name),
                    "project_id": pid, "project_name": name}
        return None

    def _agent_activity(self, body):
        tool, action = body.get("tool"), body.get("action")
        if ACTIVITY_TOOLS.get(tool) != action:
            return self._json(400, {"error": "只收 %s" % "、".join("%s（action=%s）" % kv for kv in ACTIVITY_TOOLS.items())})
        if action == "export" and not self._human():
            return self._json(403, {"error": "Agent 請人匯出（export_request）在桌面本機還沒開放：等使用者決定；"
                                             "要匯出請人在工作台按「匯出」"})
        a = body.get("args") if isinstance(body.get("args"), dict) else {}
        if action == "place":
            ids = a.get("job_ids")
            if not isinstance(ids, list) or not 1 <= len(ids) <= 50 or not all(isinstance(x, str) and JOB_ID_OK.match(x) for x in ids):
                return self._json(400, {"error": "job_ids 要是 1–50 個成片 id"})
            blocked = self._place_blocked(ids)
            if blocked:
                return self._json(409, blocked)
            args = {"job_ids": ids}
        elif action == "trim":
            if not (isinstance(a.get("job_id"), str) and JOB_ID_OK.match(a["job_id"])):
                return self._json(400, {"error": "要給 job_id"})
            args = {"job_id": a["job_id"]}
            for k in ("in_seconds", "out_seconds"):
                v = a.get(k)
                if v is None:
                    continue
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 3600:
                    return self._json(400, {"error": "%s 要是 0–3600 的秒數" % k})
                args[k] = v
            if "in_seconds" in args and "out_seconds" in args and args["out_seconds"] <= args["in_seconds"]:
                return self._json(400, {"error": "out_seconds 要大於 in_seconds"})
        else:
            args = {"title": str(a.get("title") or "")[:80]}
        st = self.state
        it = {"id": "act_" + secrets.token_hex(8), "at": None,
              "tool": tool, "ok": True, "note": str(body.get("note") or "")[:200], "ref": body.get("ref") if isinstance(body.get("ref"), str) else None,
              "action": action, "args": args, "token_name": "你" if self._human() else "Agent"}
        with st.lock:
            now = datetime.datetime.now(datetime.timezone.utc)
            if st.activity:
                last = datetime.datetime.fromisoformat(st.activity[-1]["at"])
                if now <= last:
                    now = last + datetime.timedelta(microseconds=1)
            it["at"] = now.isoformat(timespec="microseconds")
            st.activity.append(it)
            del st.activity[:-ACTIVITY_MAX]
        return self._json(200, {"id": it["id"], "at": it["at"]})

    def _activity_record(self, tool, note, ref, args):
        st = self.state
        it = {"id": "act_" + secrets.token_hex(8), "at": None, "tool": tool, "ok": True, "note": str(note or "")[:200],
              "ref": ref if isinstance(ref, str) else None, "action": None, "args": args, "token_name": "Agent"}
        with st.lock:
            now = datetime.datetime.now(datetime.timezone.utc)
            if st.activity:
                last = datetime.datetime.fromisoformat(st.activity[-1]["at"])
                if now <= last:
                    now = last + datetime.timedelta(microseconds=1)
            it["at"] = now.isoformat(timespec="microseconds")
            st.activity.append(it)
            del st.activity[:-ACTIVITY_MAX]

    def _concat(self, body):
        files = body.get("files")
        if not isinstance(files, list) or not 2 <= len(files) <= CONCAT_MAX:
            return self._json(400, {"error": "要勾 2 到 %d 支" % CONCAT_MAX})
        ids = []
        for f in files:
            m = (CONCAT_NAME.search(f) or CONCAT_FILE.fullmatch(f)) if isinstance(f, str) else None
            if not m:
                return self._json(400, {"error": "只能合併這台電腦裡的成片"})
            ids.append(m.group(1))
        try:
            code, out = self._concat_jobs(ids, body.get("name") or "合併", mute=mute_model_audio(body.get("mute_model_audio")))
        except ConsoleError as e:
            return self._err(e, with_hints=False)
        return self._json(code, out)

    def _concat_jobs(self, ids, name, mute=False):
        code, out = self._concat_engines(ids, name, mute)
        return (code, dict(out, muted=True)) if mute and code == 200 else (code, out)

    def _concat_engines(self, ids, name, mute):
        eng = self.state.concat_engine()
        if eng == "blocks":
            try:
                code, out = self._concat_blocks(ids, name, mute)
                reason = None if code == 200 else "status_%d" % code
            except ConsoleError:
                raise
            except Exception as e:
                code, out, reason = 0, None, "error:" + type(e).__name__
            if reason is None:
                return code, dict(out, engine="blocks")
            sys.stderr.write("[postblocks] %s\n" % json.dumps({"event": "fallback", "what": "concat", "engine": "blocks",
                                                               "reason": reason}))
            code, out = self._concat_legacy(ids, name, mute)
            return code, (dict(out, engine="legacy(fallback)") if code == 200 else out)
        code, out = self._concat_legacy(ids, name, mute)
        if eng == "shadow" and code == 200:
            self._concat_shadow(ids, out.get("path"), out.get("lossless"), mute)
        return code, out

    def _concat_shadow(self, ids, legacy_path, lossless=False, mute=False):
        def log(ev):
            sys.stderr.write("[postblocks] %s\n" % json.dumps(dict(ev, what="concat"), ensure_ascii=False))

        def go():
            try:
                load = os.getloadavg()[0]
            except OSError:
                load = 0.0
            if load > CONCAT_SHADOW_LOAD:
                return log({"event": "shadow_skipped", "reason": "load", "load": round(load, 1)})
            if not _CONCAT_SHADOW.acquire(blocking=False):
                return log({"event": "shadow_skipped", "reason": "busy"})
            work = None
            try:
                work, path = self._concat_blocks_render(ids, mute)
                a, b = self._concat_probe(legacy_path), self._concat_probe(path)
                diffs = [k for k in ("audio", "aspect") if a.get(k) != b.get(k)]
                if abs((a.get("duration") or 0) - (b.get("duration") or 0)) > 0.1:
                    diffs.append("duration")
                if not lossless and a.get("frames") != b.get("frames"):
                    diffs.append("frames")
                log({"event": "shadow", "reason": "+".join(diffs) or "same", "legacy": a, "blocks": b})
            except Exception as e:
                log({"event": "shadow", "reason": "blocks_error:" + type(e).__name__})
            finally:
                _CONCAT_SHADOW.release()
                if work:
                    shutil.rmtree(work, ignore_errors=True)
        t = threading.Timer(1.0, go)
        t.daemon = True
        t.start()
        return t

    def _concat_probe(self, path):
        st = self.state
        r = subprocess.run([st.ffprobe, "-v", "error", "-count_packets", "-show_entries",
                            "format=duration:stream=codec_type,width,height,nb_read_packets", "-of", "json", path],
                           capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
        d = json.loads(r.stdout or b"{}")
        ss = d.get("streams") or []
        v = next((x for x in ss if x.get("codec_type") == "video"), {})
        w, h = int(v.get("width") or 0), int(v.get("height") or 0)
        return {"duration": round(float((d.get("format") or {}).get("duration") or 0), 3),
                "frames": int(v.get("nb_read_packets") or 0), "aspect": round(w / h, 3) if h else None,
                "audio": any(x.get("codec_type") == "audio" for x in ss)}

    def _concat_spec_body(self, ids, paths, mute=False, drop=(), xfade=None, afade=None):
        infos = [self._concat_probe(p) for p in paths]
        st = self.state
        r = subprocess.run([st.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "json", paths[0]], capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
        v0 = (json.loads(r.stdout or b"{}").get("streams") or [{}])[0]
        w, h = int(v0.get("width") or 1080), int(v0.get("height") or 1920)
        ratio = lambda a: int(a.split(":")[0]) / int(a.split(":")[1])
        aspect = min(export_spec.ASPECTS, key=lambda a: abs(ratio(a) - w / h))
        short = min(w, h)
        res = min(export_spec.RESOLUTIONS, key=lambda x: abs(int(x[:-1]) - short))
        video, audio, at = [], [], 0.0
        for k, (j, info) in enumerate(zip(ids, infos)):
            dur = info["duration"]
            cut = round(dur / info["frames"], 3) if k in drop and info["frames"] else 0
            video.append({"job": j, "in": cut, "out": dur})
            if info["audio"] and not mute:
                a = {"lane": "A1", "job": j, "at": round(at, 3), "in": cut, "dur": round(dur - cut, 3), "gain": 1.0}
                if afade is not None:
                    a["fade"] = afade
                audio.append(a)
            at += dur - cut
        body = {"format": {"aspect": aspect, "resolution": res, "fps": 24, "fit": "pad"}, "video": video, "audio": audio,
                "subtitles": "none", "disclosure": {"on": False}}
        if xfade is not None:
            body["pipeline"] = [{"use": "transition", "params": {"duration": xfade, "style": "fade"}}]
        return body

    def _concat_blocks_render(self, ids, mute=False, drop=(), xfade=None, afade=None):
        st = self.state
        if not (st.ffmpeg and st.ffprobe):
            raise render.RenderError("這台找不到 ffmpeg，沒辦法合併")
        paths = [os.path.join(st.media, self._cache_job(j)) for j in ids]
        req = export_spec.normalize(self._concat_spec_body(ids, paths, mute, drop, xfade, afade))
        eid = "exp_" + secrets.token_hex(10)
        work = tempfile.mkdtemp(prefix="concat-blocks-", dir=st.data_dir)
        try:
            s3 = os.path.join(work, "s3")
            src_dir = os.path.join(s3, self.SRC_BUCKET, "originals", self.USER)
            os.makedirs(src_dir)
            keys = {}
            for j, p in zip(ids, paths):
                k = os.path.basename(p)
                dst = os.path.join(src_dir, k)
                if not os.path.exists(dst):
                    try:
                        os.link(p, dst)
                    except OSError:
                        shutil.copyfile(p, dst)
                keys[j] = "originals/%s/%s" % (self.USER, k)
            audio_keys = [(keys[a["job"]], "video") for a in req["audio"]]
            spec = export_spec.build_spec(self.USER, eid, req, keys, {}, audio_keys, self.SRC_BUCKET, self.OUT_BUCKET)
            r = os.path.join(work, "render")
            os.makedirs(r)
            with ffmpeg_env(st.openh264_env() if st.needs_openh264() else None):
                done = export_local.run(spec, s3, r, strict=False, ffmpeg=st.ffmpeg, ffprobe=st.ffprobe,
                                        container="mp4", engine="blocks")
            if done.get("state") not in (None, "done"):
                raise render.RenderError(done.get("error") or "積木沒有跑完")
            out = os.path.join(s3, self.OUT_BUCKET, render.out_keys(self.USER, eid)["mp4"])
            if not os.path.exists(out):
                raise render.RenderError("積木沒有產出成品")
            return work, out
        except BaseException:
            shutil.rmtree(work, ignore_errors=True)
            raise

    def _concat_blocks(self, ids, name, mute=False, drop=(), xfade=None, afade=None):
        st = self.state
        name = safe_filename(name, 60) or "合併"
        work, out = self._concat_blocks_render(ids, mute, drop, xfade, afade)
        try:
            with open(out, "rb") as f:
                sha = self._store_blob(f.read(), "video/mp4")
            kept_dir = os.path.join(st.data_dir, "merged")
            os.makedirs(kept_dir, mode=0o700, exist_ok=True)
            kept = os.path.join(kept_dir, "%s-%s.mp4" % (name, sha[:8]))
            if not os.path.exists(kept):
                shutil.copyfile(out, kept)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return 200, {"src": "/api/local/media?sha=" + sha, "file": name + ".mp4", "lossless": False, "path": kept}

    def _concat_legacy(self, ids, name, mute=False):
        st = self.state
        if not (st.ffmpeg and st.ffprobe):
            return 409, {"error": "這台找不到 ffmpeg，沒辦法合併"}
        paths = [os.path.join(st.media, self._cache_job(j)) for j in ids]
        name = safe_filename(name, 60) or "合併"
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
                        return 500, {"error": "第 %d 支重新編碼失敗" % (i + 1)}
                    norm.append(y)
                if not concat(norm):
                    return 500, {"error": "合併失敗"}
            if mute:
                quiet = os.path.join(work, "muted.mp4")
                if run([st.ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", out, "-f", "lavfi", "-i",
                        "anullsrc=r=48000:cl=stereo", "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                        "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", "-movflags", "+faststart",
                        quiet]).returncode != 0:
                    return 500, {"error": "影片原聲靜音失敗"}
                out = quiet
            with open(out, "rb") as f:
                sha = self._store_blob(f.read(), "video/mp4")
            kept_dir = os.path.join(st.data_dir, "merged")
            os.makedirs(kept_dir, mode=0o700, exist_ok=True)
            kept = os.path.join(kept_dir, "%s-%s.mp4" % (name, sha[:8]))
            if not os.path.exists(kept):
                shutil.copyfile(out, kept)
        except render.RenderError as e:
            return 409, {"error": str(e)}
        except (OSError, subprocess.SubprocessError):
            return 500, {"error": "合併失敗（ffmpeg 沒跑完）"}
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return 200, {"src": "/api/local/media?sha=" + sha, "file": name + ".mp4", "lossless": lossless, "path": kept}

    def _agent_film(self, run):
        st = self.state
        if not st.agentloop_on():
            return self._json(501, {"error": AGENT_LOOP_OFF})
        got = self._film_picks(run)
        if not got:
            return self._json(404, {"error": "沒有這一次拍片"})
        plan, rows, shots, files, missing = got
        out = {"run": run, "phase": plan["phase"], "project_id": plan["project_id"], "shots": shots, "film": None,
               "missing": missing}
        sync = self._film_sync(plan, shots, rows)
        if sync:
            out["mainline"] = sync
        if plan.get("seam_redo") is not None:
            out["seam_redo"] = plan["seam_redo"]
            warn = ["%s 跟上一鏡 %s 的接縫沒有接上（SSIM %s）：因為你指定了首幀，所以沒有接上，也沒有自動重做；要接上就換掉那張首幀再拍這一鏡"
                    % (x["key"], x["after"], "—" if x.get("score") is None else "%.3f" % x["score"])
                    for x in plan["seam_redo"].get("skipped") or [] if x.get("reason") == "user_frame"]
            if warn:
                out["seam_warnings"] = warn
        if files and not missing:
            try:
                if len(files) == 1:
                    path, ctype = self._media_named(self._cache_job(files[0]))
                    out["film"] = {"src": "/api/download?id=" + files[0], "path": path, "content_type": ctype}
                else:
                    eff = film_settings.effective_env(st.data_dir)
                    mute, xf, af = mute_model_audio(None), film_seam_xfade(eff), film_seam_afade(eff)
                    code, f = (self._film_trimmed(files, plan, shots, mute, xf, af, env=eff)
                               or self._concat_jobs(files, "agent-film", mute=mute))
                    if code == 200 and xf is not None:
                        qc_rep = self._film_seam_qc(files, shots, f)
                        f = dict(f, seam_qc=qc_rep) if qc_rep else f
                    if code == 200:
                        out["film"] = f
                    else:
                        out["film_error"] = f.get("error")
            except ConsoleError as e:
                out["film_error"] = str(e)
        return self._json(200, out)

    def _film_trimmed(self, files, plan, shots, mute, xfade=None, afade=None, env=None):
        relayed = set(plan.get("relayed") or ())
        picked = [s for s in shots if s.get("picked")]
        drop = [i for i, s in enumerate(picked) if i and s["picked"] in relayed]
        if (os.environ if env is None else env).get(FILM_SEAM_TRIM_ENV, "").strip().lower() not in ("1", "on", "true"):
            drop = []
        if not drop and xfade is None and afade is None:
            return None
        try:
            code, out = self._concat_blocks(files, "agent-film", mute, drop, xfade, afade)
            reason = None if code == 200 else "status_%d" % code
        except ConsoleError:
            raise
        except Exception as e:
            code, out, reason = 0, None, "error:" + type(e).__name__
        if reason is None:
            out = dict(out, engine="blocks")
            if drop:
                out["seams_trimmed"] = [picked[i]["key"] for i in drop]
            if xfade is not None:
                out["seam_xfade"] = xfade
            if afade is not None:
                out["seam_afade"] = afade
            return code, (dict(out, muted=True) if mute else out)
        sys.stderr.write("[postblocks] %s\n" % json.dumps({"event": "fallback", "what": "film_seam", "reason": reason}))
        return None

    def _film_seam_qc(self, files, shots, film):
        import postblocks.seam_check as sc
        st = self.state
        try:
            picked = [s for s in shots if s.get("picked")]
            drop = [i for i in range(1, len(files)) if picked[i]["key"] in (film.get("seams_trimmed") or ())]
            xf = film.get("seam_xfade")
            paths = [os.path.join(st.media, self._cache_job(j)) for j in files]
            video = self._concat_spec_body(files, paths, drop=drop)["video"]
            frames = [self._concat_probe(p)["frames"] for p in paths]
            th = float(sc.SeamCheck.params["threshold"]["default"])
            img_dir = os.path.splitext(film["path"])[0] + "-seams"
            os.makedirs(img_dir, mode=0o700, exist_ok=True)
            seams, at = [], 0.0
            for k in range(len(files) - 1):
                a, b = video[k], video[k + 1]
                at += a["out"] - a["in"]
                last = max(0.0, a["out"] - (a["out"] / frames[k] if frames[k] else 1.0 / 24))
                score = sc.SeamCheck.ssim(st.ffmpeg, paths[k], last, paths[k + 1], b["in"])
                name = "seam%d" % (k + 1)
                img = os.path.join(img_dir, name + ".png")
                mid = at + (xf / 2.0 if xf else 0.0)
                r = subprocess.run([st.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                    "-ss", "%.3f" % last, "-i", paths[k], "-ss", "%.3f" % mid, "-i", film["path"],
                                    "-ss", "%.3f" % b["in"], "-i", paths[k + 1], "-filter_complex",
                                    "[0:v]scale=-2:180,setsar=1[a];[1:v]scale=-2:180,setsar=1[m];[2:v]scale=-2:180,setsar=1[b];"
                                    "[a][m][b]hstack=inputs=3", "-frames:v", "1", img],
                                   capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
                ok = score is not None and score >= th
                seams.append({"seam": name, "from": picked[k]["key"], "to": picked[k + 1]["key"],
                              "ssim": None if score is None else round(score, 3), "ok": ok,
                              "defects": [] if ok else (["unreadable"] if score is None else ["seam_jump"]),
                              "image": img if r.returncode == 0 and os.path.exists(img) else None})
            return {"threshold": th, "xfade": xf, "seams": seams, "redo": "none",
                    "note": "只量不重抽：不合格的接縫只列出來，要不要重拍由人或 Agent 另外決定"}
        except Exception as e:
            sys.stderr.write("[postblocks] %s\n" % json.dumps({"event": "fallback", "what": "seam_qc",
                                                               "reason": "error:" + type(e).__name__}))
            return None

    def _film_picks(self, run):
        st = self.state
        import agent_exec
        plan = agent_exec.film_shots(st.data_dir, run)
        if not plan:
            return None
        mine = {t for s in plan["shots"] for t in s["takes"]}
        rows = []
        if plan["project_id"] and mine:
            rows = [r for r in st.db.run(lambda c, u: takes.list_takes(c, u, plan["project_id"], limit=500)) if r["id"] in mine]
        shots, files, missing = [], [], []
        for n, s in enumerate(plan["shots"], 1):
            ts = sorted((r for r in rows if r["shot_key"] == s["key"]), key=lambda r: r.get("attempt") or 0)
            vs = [{"take": r["id"], "attempt": r.get("attempt"), "status": r["status"], "qc_ok": r.get("qc_ok"),
                   "picked": bool(r.get("picked")), "picked_by": r.get("picked_by") if r.get("picked") else None,
                   "job_id": r.get("job_id"),
                   "src": "/api/download?id=" + r["job_id"] if r.get("job_id") and r["status"] == "ready" else None}
                  for r in ts]
            pick = next((v for v in vs if v["picked"] and v["src"]), None)
            shots.append({"n": n, "key": s["key"], "picked": pick and pick["take"], "picked_by": pick and pick["picked_by"],
                          "versions": vs})
            if pick:
                files.append(pick["job_id"])
            else:
                missing.append(s["key"])
        return plan, rows, shots, files, missing

    def _film_sync(self, plan, shots, rows):
        pid = plan.get("project_id")
        picks = [(n, s, next((r for r in rows if r["id"] == s.get("picked")), None)) for n, s in enumerate(shots)]
        picks = [(n, s, r) for n, s, r in picks if r and r.get("job_id")]
        if not pid or not picks:
            return None
        segs = plan.get("shots") or []
        request, model = str(plan.get("request") or ""), str(plan.get("model") or "")

        def run_sync(c, u):
            bkey = studio_store.board_key(pid)
            board = studio_store.kv_get(c, u, bkey).get("value")
            made = False
            if not (isinstance(board, list) and board):
                board = studio_store.normalize_shots([{"prompt": str(g.get("prompt") or request or "（Agent 拍片）")[:studio_store.WORK_PROMPT_MAX],
                                                        "seconds": g.get("seconds")} for g in segs])
                studio_store.kv_put(c, u, bkey, board)
                made = True
            matched = len(board) == len(segs)
            jobs = studio_store.kv_get(c, u, "jobs").get("value")
            jobs = jobs if isinstance(jobs, list) else []
            works = studio_store.kv_get(c, u, "simple_works").get("value")
            works = works if isinstance(works, dict) else {}
            w = works.get(pid) if isinstance(works.get(pid), dict) else {"v": 2, "step": 1, "story": "", "aspect": "9:16",
                                                                          "shots": [], "jobs": [], "exported": False, "done": {}}
            wj = w.get("jobs") if isinstance(w.get("jobs"), list) else []
            before = json.dumps([board, jobs, works.get(pid)], sort_keys=True, ensure_ascii=False, default=str)
            synced = 0
            for n, s, r in (picks if matched else []):
                sid = board[n].get("sid") if isinstance(board[n], dict) else None
                if not sid:
                    continue
                job, uid = r["job_id"], "agent_" + r["id"]
                for j in jobs:
                    if isinstance(j, dict) and str(j.get("uid", "")).startswith("agent_") and j.get("uid") != uid \
                            and (j.get("applied") or {}).get("sid") == sid:
                        j.pop("applied", None)
                hit = next((j for j in jobs if isinstance(j, dict) and j.get("id") == job), None)
                if hit is None:
                    g = segs[n] if n < len(segs) else {}
                    jobs.insert(0, {"uid": uid, "id": job, "status": "completed", "src": "/api/download?id=" + job,
                                    "file": job + ".mp4", "model": model,
                                    "payload": {"model": model, "prompt": g.get("prompt") or "", "seconds": g.get("seconds")},
                                    "ts": int(time.time() * 1000), "applied": {"sid": sid},
                                    "agent": {"run": plan.get("run"), "take": r["id"]}})
                elif str(hit.get("uid", "")).startswith("agent_"):
                    hit["applied"] = {"sid": sid}
                    uid = hit["uid"]
                else:
                    uid = hit.get("uid") or uid
                if not any(isinstance(x, dict) and x.get("uid") == uid and x.get("sid") == sid for x in wj):
                    wj.insert(0, {"uid": uid, "sid": sid})
                synced += 1
            w["jobs"] = wj
            if not str(w.get("story") or "").strip() and request:
                w["story"] = request
            if synced and isinstance(w.get("step"), int) and w["step"] < 5:
                w["step"] = 5
            works[pid] = w
            changed = made or before != json.dumps([board, jobs, w], sort_keys=True, ensure_ascii=False, default=str)
            if changed:
                studio_store.kv_put(c, u, "jobs", jobs)
                studio_store.kv_put(c, u, "simple_works", works)
            return synced, (0 if matched else len(segs)), made, changed
        try:
            synced, unmatched, made, changed = self.state.db.run(run_sync)
        except studio_store.StoreError as e:
            return {"synced": 0, "unmatched": 0, "error": "寫回主線失敗：%s" % e}
        out = {"synced": synced, "unmatched": unmatched}
        if made:
            out["board_created"] = True
        if unmatched:
            out["message"] = "有 %d 鏡沒對上分鏡（這部作品的分鏡鏡數跟 Agent 拍的不一樣），請到主線第 4 步手動指定" % unmatched
        if changed:
            st = self.state
            with st.lock:
                now = datetime.datetime.now(datetime.timezone.utc)
                if st.activity and datetime.datetime.fromisoformat(st.activity[-1]["at"]) >= now:
                    now = datetime.datetime.fromisoformat(st.activity[-1]["at"]) + datetime.timedelta(microseconds=1)
                st.activity.append({"id": "act_" + secrets.token_hex(8), "at": now.isoformat(timespec="microseconds"),
                                    "tool": "agent_film", "ok": True, "note": "Agent 拍的 %d 鏡接進主線" % synced, "ref": pid,
                                    "action": "film_sync", "args": {"project_id": pid, "run": plan.get("run")},
                                    "token_name": "Agent"})
                del st.activity[:-ACTIVITY_MAX]
        return out

    def _image_names(self, model):
        names = {model}
        if upstream.needs_ref(model):
            try:
                names.add(upstream.ref_from_catalog(model, self.state.models_cached()[0]))
            except ConsoleError:
                pass
        return names

    def _image_recover(self, body, started):
        mode = image_recover_mode()
        if mode == "off":
            return None, None
        model = str(body.get("model") or "")[:120]
        got, outcome, iid = upstream.recover_image(lambda p: self.state.call(p, timeout=TIMEOUT),
                                                   self._image_names(model), started, int(time.time()))
        rec = {"at": started, "model": model, "mode": mode, "outcome": outcome}
        if iid:
            rec["id"] = iid
        try:
            with self.state.media_lock:
                old = self.state.db.run(studio_store.kv_get, "image_recover_log")["value"]
                lst = (old if isinstance(old, list) else []) + [rec]
                self.state.db.run(studio_store.kv_put, "image_recover_log", lst[-IMAGE_RECOVER_KEPT:])
        except studio_store.StoreError:
            pass
        if mode != "on":
            return None, None
        return (got, None) if got is not None else (None, outcome)

    def _image_lost(self, body, started, outcome=None):
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
        if outcome:
            return self._json(504, {
                "error": ("等不到這張圖（%s 送出的 %s）。可能已經生成了，但用量紀錄裡找不到唯一對得上的一筆，不替你猜；"
                          "請到 AppleToken 的用量頁查 %s 之後的圖片紀錄。" % (when, model or "圖片", when)),
                "maybe_billed": True, "submitted_at": started, "model": model, "recover": outcome})
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

    ASSET_TAGS_MAX, ASSET_TAG_LEN, ASSET_NAME_LEN = 20, 40, 120

    def _image_outpaint(self, body):
        import outpaint
        st = self.state
        if st.ffmpeg and st.ffprobe:
            outpaint.FFMPEG, outpaint.FFPROBE = st.ffmpeg, st.ffprobe
        body = dict(body) if isinstance(body, dict) else {}
        body.pop("payer", None)
        try:
            req = outpaint.check_request(body)
        except outpaint.OutpaintError as e:
            return self._json(e.code, {"error": e.message})
        if not outpaint.available():
            return self._json(503, {"error": "這台找不到 ffmpeg，外擴做不了"})
        try:
            listing, _stale = st.models_cached()
            entry = qc.find_entry(listing, outpaint.MODEL)
        except ConsoleError:
            entry = None
        if entry is None:
            return self._json(503, {"error": "目前可用的模型裡沒有畫面外擴（%s），所以沒有送出" % outpaint.MODEL,
                                    "payer": "own_key"})
        cost = outpaint.request_price(entry)
        try:
            if req["asset_id"]:
                resp = st.call("/assets/%s/content" % req["asset_id"], stream=True, timeout=60)
                try:
                    src_raw = resp.read(OUTPAINT_MAX + 1)
                finally:
                    resp.close()
            else:
                m = re.match(r"^data:image/(?:png|jpe?g);base64,(.*)$", req["source"], re.S | re.I)
                src_raw = base64.b64decode(m.group(1)) if m else b""
            if not src_raw or len(src_raw) > OUTPAINT_MAX:
                return self._json(413 if src_raw else 400, {"error": "原圖讀不出來或太大（上限 %d MB）" % (OUTPAINT_MAX >> 20)})
            geo, canvas, mask = outpaint.prepare(src_raw, req["aspect"])
        except ConsoleError as e:
            return self._json(e.code if 400 <= e.code < 600 else 502, {"error": "原圖拿不到：%s" % e.body})
        except (binascii.Error, ValueError):
            return self._json(400, {"error": "原圖讀不出來（要是 PNG 或 JPEG 的 data URI）"})
        except outpaint.OutpaintError as e:
            return self._json(e.code, {"error": e.message})
        shape = {"aspect": req["aspect"], "model": outpaint.MODEL, "sides": geo["sides"],
                 "source_size": {"w": geo["w"], "h": geo["h"]}, "canvas": {"w": geo["W"], "h": geo["H"]},
                 "offset": {"x": geo["x"], "y": geo["y"]}, "payer": "own_key"}
        if body.get("quote"):
            return self._json(200, dict(shape, est_cost=cost, unit="request"))
        uri = lambda raw: "data:image/png;base64," + base64.b64encode(raw).decode()
        try:
            out = st.call("/images/edits", payload=dict(req["extra"], model=outpaint.MODEL, prompt=req["prompt"],
                                                         image=uri(canvas), mask=uri(mask)), timeout=GENERATE_TIMEOUT)
        except ConsoleError as e:
            return self._err(e)
        it = (out.get("data") or [None])[0] if isinstance(out, dict) else None
        it = it if isinstance(it, dict) else {}
        try:
            if isinstance(it.get("b64_json"), str) and it["b64_json"]:
                result = base64.b64decode(it["b64_json"])
            elif isinstance(it.get("url"), str) and it["url"].startswith("data:"):
                result = base64.b64decode(it["url"].split(",", 1)[1])
            else:
                return self._json(502, {"error": "上游沒有回圖片", "payer": "own_key"})
            final = outpaint.paste_back(result, src_raw, geo)
        except (binascii.Error, ValueError):
            return self._json(502, {"error": "上游回的圖片解不開", "payer": "own_key"})
        except outpaint.OutpaintError as e:
            return self._json(502, {"error": "外擴已完成，但貼回原圖失敗：%s" % e.message, "payer": "own_key"})
        payload = {"source": uri(final), "name": outpaint.asset_name(req["aspect"], req["asset_id"]),
                   "tags": outpaint.asset_tags(req["aspect"], req["asset_id"])}
        try:
            try:
                asset = st.call("/assets", payload=payload, timeout=GENERATE_TIMEOUT)
            except ConsoleError as e:
                if e.code != 400:
                    raise
                payload.pop("tags")
                asset = st.call("/assets", payload=payload, timeout=GENERATE_TIMEOUT)
        except ConsoleError as e:
            return self._json(502, {"error": "外擴已完成，但存成素材失敗：%s" % with_hint(e), "payer": "own_key"})
        aid = str(asset.get("id") or "") if isinstance(asset, dict) else ""
        res = dict(shape, asset=asset, reference="asset://" + aid if aid else "")
        if isinstance(out.get("id"), str):
            res["upstream_id"] = out["id"]
        res["from"] = {"asset": req["asset_id"], "reference": "asset://" + req["asset_id"] if req["asset_id"] else "",
                       "sha256": hashlib.sha256(src_raw).hexdigest()}
        return self._json(200, res)

    def _asset_upstream(self, path, body):
        st = self.state
        try:
            if path == "/api/assets/delete":
                if not self._human():
                    return self._json(403, {"error": "刪除素材要你本人在 App 裡按"})
                aid = str(body.get("id") or "").strip()
                if not ASSET_ID.match(aid):
                    return self._json(400, {"error": "素材 id 的格式不對"})
                st.call("/assets/" + aid, method="DELETE")

                def drop(c, _u):
                    with c.cursor() as cur:
                        cur.execute("DELETE FROM local_asset_meta WHERE asset_id = %s", (aid,))
                try:
                    st.db.run(drop)
                except studio_store.StoreError:
                    pass
                return self._json(200, {"ok": True, "id": aid})
            if path == "/api/assets/uploads":
                mime = body.get("mime")
                if not isinstance(mime, str) or not mime.strip() or len(mime) > 100:
                    return self._json(400, {"error": "缺少 mime（例如 image/png、video/mp4）"})
                payload = {"mime": mime.strip()}
                if isinstance(body.get("name"), str) and body["name"].strip():
                    payload["name"] = body["name"].strip()[:self.ASSET_NAME_LEN]
                if isinstance(body.get("tags"), list):
                    payload["tags"] = [t for t in body["tags"] if isinstance(t, str)][:self.ASSET_TAGS_MAX]
                r = st.call("/assets/uploads", payload=payload)
                if not (isinstance(r, dict) and UPLOAD_ID.match(str(r.get("id") or ""))):
                    raise ConsoleError(502, "上游沒回直傳 id")
                return self._json(201, r)
            upid = str(body.get("id") or "").strip()
            if not UPLOAD_ID.match(upid):
                return self._json(400, {"error": "直傳 id 的格式不對"})
            return self._json(200, st.call("/assets/uploads/%s/complete" % upid, payload={}))
        except ConsoleError as e:
            return self._err(e, with_hints=False)

    def _asset_update(self, body):
        aid = str(body.get("id") or "").strip()
        if not ASSET_ID.match(aid):
            return self._json(400, {"error": "素材 id 的格式不對"})
        patch = {}
        if "name" in body and (body["name"] is None or isinstance(body["name"], str)):
            patch["name"] = None if body["name"] is None else body["name"].strip()[:self.ASSET_NAME_LEN]
        if isinstance(body.get("tags"), list):
            tags = [t.strip() for t in body["tags"] if isinstance(t, str) and t.strip()]
            if len(tags) > self.ASSET_TAGS_MAX or any(len(t) > self.ASSET_TAG_LEN for t in tags):
                return self._json(400, {"error": "標籤最多 %d 個、每個 %d 字以內" % (self.ASSET_TAGS_MAX, self.ASSET_TAG_LEN)})
            patch["tags"] = list(dict.fromkeys(tags))
        if not patch:
            return self._json(400, {"error": "要帶 name 或 tags"})

        def put(c, _u):
            with c.cursor() as cur:
                cur.execute("SELECT patch FROM local_asset_meta WHERE asset_id = %s", (aid,))
                row = cur.fetchone()
                merged = dict((row[0] if row else None) or {}, **patch)
                cur.execute("INSERT INTO local_asset_meta (asset_id, patch) VALUES (%s, %s) ON CONFLICT (asset_id) DO UPDATE "
                            "SET patch = excluded.patch, updated_at = now()",
                            (aid, json.dumps(merged, ensure_ascii=False)))
                return merged
        merged = self.state.db.run(put)
        return self._json(200, dict({"id": aid, "local": True}, **merged))

    def _asset_overlay(self, got, tag=None):
        if not isinstance(got, dict) or not isinstance(got.get("data"), list):
            return got

        def read(c, _u):
            with c.cursor() as cur:
                cur.execute("SELECT asset_id, patch FROM local_asset_meta")
                return {r[0]: r[1] for r in cur.fetchall()}
        meta = self.state.db.run(read)
        items = [dict(x, **meta[x["id"]]) if isinstance(x, dict) and x.get("id") in meta else x for x in got["data"]]
        if tag:
            items = [x for x in items if isinstance(x, dict) and tag in (x.get("tags") or [])]
        return dict(got, data=items)

    def _qc_estimate_local(self, frames):
        n = qc.estimate_frames(frames)
        if n is None:
            return self._json(400, {"error": "frames 要 1～%d" % qc.MAX_FRAMES})
        try:
            listing, _ = self.state.models_cached()
            cap = qc.price_cap(qc.find_entry(listing, qc.MODEL), n)
        except ConsoleError:
            cap = None
        if cap is None:
            return self._json(503, {"error": "查不到驗片模型 %s 的單價" % qc.MODEL, "payer": "own_key"})
        return self._json(200, {"payer": "own_key", "model": qc.MODEL, "frames": n, "cap_usd": cap, "upper_bound": True})

    def _qc_rating_local(self, job):
        if not isinstance(job, str) or not ID.match(job):
            return self._json(400, {"error": "job 不合法（上游的影片 id）"})
        t = self.state.db.run(lambda c, u: takes.by_job(c, u, job))
        if not t:
            return self._json(404, {"error": "本機沒有這支片的品管紀錄（還沒驗過，或不是在這台拍的）"})
        return self._json(200, {"job": job, "source": "local", "take": t["id"], "shot_key": t.get("shot_key"),
                                "rating": {"ok": t.get("qc_ok"), "reports": t.get("qc") or []}})

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
        out = {
            "object": "storyboard.confirmation", "status": "needs_confirmation", "quote_id": ref,
            "payer": "own_key", "model": storyboard.model_of(q), "shots": q.get("shots"),
            "expires_in": SB_QUOTE_TTL,
            "estimate": {"upstream_cost_max": str(cap) if cap is not None else None},
            "note": "用你自己的 AppleToken 金鑰，AppleToken 依實際用量收費"}
        if not self._human():
            out["approval"] = self._agent_card("storyboard", ref, cap, SB_QUOTE_TTL, {
                "model": storyboard.model_of(q), "prompt": str(q.get("story") or "")[:280], "shots": q.get("shots")})
            if self._direct_refused(out["approval"]):
                return None
            if out["approval"].get("direct"):
                out["direct"] = True
        return self._json(200, out)

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
            if not self._human() and not getattr(self, "_via_card", False):
                return self._json(409, {"error": _AGENT_NO_CONFIRM})
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
        if not self._human():
            summ = {"model": body["model"], "prompt": str(body.get("input") or body.get("prompt") or body.get("lyrics") or "")[:280]}
            out["approval"] = self._agent_card(kind, ref, cost, 15 * 60, summ)
            if self._direct_refused(out["approval"]):
                return None
            if out["approval"].get("direct"):
                out["direct"] = True
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
            if not self._human() and not getattr(self, "_via_card", False):
                return self._json(409, {"error": _AGENT_NO_CONFIRM})
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
                audio = self._store_audio(raw, meta.get("content_type"))
                return self._json(200, {"payer": "own_key", "provider": "appletoken", "quote_id": qid, "audio": audio,
                                        "characters": meta.get("x-appletoken-characters"),
                                        "seconds": self._audio_seconds(audio)})
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

    def _audio_seconds(self, audio):
        st = self.state
        m = re.search(r"sha=([0-9a-f]{64})$", str((audio or {}).get("url") or ""))
        if not (m and st.ffprobe):
            return None
        try:
            r = subprocess.run([st.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                os.path.join(st.media, m.group(1))], capture_output=True, text=True, timeout=30,
                               stdin=subprocess.DEVNULL)
            v = float(r.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
        return round(v, 3) if v > 0 else None

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

    def _pipeline_preview(self, body):
        import postblocks
        body = dict(body)
        body.pop("project_id", None)
        container = body.pop("container", None) or "mp4"
        if container not in ("mp4", "webm"):
            return self._json(400, {"error": "container 只能是 mp4／webm"})
        body, stop = self._resolve_logos(body)
        if stop:
            return self._json(*stop)
        try:
            req = export_spec.normalize(body)
        except export_spec.ExportError as e:
            return self._json(e.code, {"error": e.msg})
        try:
            got = postblocks.preview(export_spec.preview_spec(req), req.get("pipeline"),
                                     container=container, caption_fontsdir=os.path.join(ROOT, "fonts"))
        except postblocks.PipelineError as e:
            return self._json(400, {"error": str(e)})
        return self._json(200, got)

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
        body, stop = self._resolve_logos(body)
        if stop:
            return self._json(*stop)
        body, seam_applied = film_settings.export_body(body, film_settings.effective_env(st.data_dir))
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
        out = {"id": eid, "state": "staging"}
        if seam_applied:
            out["film_settings"] = seam_applied
        try:
            note = export_spec.pipeline_note(req, st.engine_now(), container, os.path.join(ROOT, "fonts"))
        except Exception as e:
            note = {"pipeline_ignored": "unchecked", "pipeline_error": type(e).__name__} if req.get("pipeline") else None
        if note:
            out.update(note)
        return self._json(202, out)

    def _resolve_logos(self, body):
        st = self.state
        aids = export_spec.logo_assets(body)
        if not aids:
            return body, None
        if not st.key():
            return None, (409, NO_KEY)
        src_dir = os.path.join(st.exports_root, self.SRC_BUCKET, "originals", self.USER)
        os.makedirs(src_dir, exist_ok=True)
        keys = {}
        for aid in aids:
            try:
                resp = st.call("/assets/%s/content" % aid, stream=True, timeout=60)
            except ConsoleError as e:
                if e.code in (403, 404):
                    return None, (404, {"error": "找不到這個素材（logo）：%s" % aid})
                return None, (e.code if 400 <= e.code < 600 else 502, {"error": "取不到 logo（AppleToken 回 %s）" % e.code})
            try:
                raw = resp.read(export_spec.LOGO_MAX + 1)
            finally:
                resp.close()
            if len(raw) > export_spec.LOGO_MAX or export_spec.image_kind(raw[:8]) is None:
                return None, (400, {"error": "logo 要是 png 或 jpeg，而且小於 20 MB（%s）" % aid})
            sha = hashlib.sha256(raw).hexdigest()
            dst = os.path.join(src_dir, sha)
            if not os.path.exists(dst):
                tmp = os.path.join(src_dir, ".part-" + secrets.token_hex(6))
                with open(tmp, "wb") as f:
                    f.write(raw)
                os.replace(tmp, dst)
            keys[aid] = "originals/%s/%s" % (self.USER, sha)
        return export_spec.with_logo_keys(body, keys), None

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
                                                caption_fontsdir=os.path.join(ROOT, "fonts"),
                                                engine=st.engine_now())
                finally:
                    shutil.rmtree(work, ignore_errors=True)
            keep = ("state", "error", "duration", "bytes", "srt", "size", "warnings", "models", "captions_burned", "qc")
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
