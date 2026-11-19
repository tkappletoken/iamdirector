
import os
import stat
import tomllib
from pathlib import Path

from .errors import ConfigError
from .redact import fingerprint, register_secret

DEFAULT_BASE_URL = "https://iamdirector.app"
DEFAULT_COOKIE_NAME = "studio_session"
TOKEN_PREFIX = "iad_"
LEGACY_COOKIE_NAME = "appletoken_session"

CONFIG_DIR = Path(os.environ.get("APPLETOKEN_HOME", str(Path.home() / ".appletoken")))
CONFIG_PATH = CONFIG_DIR / "session.toml"

_HOWTO = (
    "跑 `at login`，貼上工作台「Agent 協作」發的權杖（iad_…）；或 export IAMDIRECTOR_TOKEN。"
    "（舊做法：把 %s cookie 寫進 %s 的 session，或 export APPLETOKEN_SESSION。）"
    "權杖與 cookie 都等於你的身分，不要貼進聊天視窗或任何會被記錄的地方。"
    % (DEFAULT_COOKIE_NAME, CONFIG_PATH)
)

class Session:
    def __init__(self, value, base_url=DEFAULT_BASE_URL,
                 cookie_name=DEFAULT_COOKIE_NAME, source="?", profile=None, kind=None,
                 register=True):
        self.value = value
        self.kind = kind or ("token" if str(value).startswith(TOKEN_PREFIX) else "cookie")
        self.base_url = base_url.rstrip("/")
        self.cookie_name = cookie_name
        self.source = source
        self.profile = profile
        if register:
            register_secret(value)

    @property
    def fingerprint(self):
        return fingerprint(self.value)

    def cookie_header(self):
        return "%s=%s" % (self.cookie_name, self.value)

    def auth_headers(self):
        if self.kind == "token":
            return {"Authorization": "Bearer %s" % self.value}
        return {"Cookie": self.cookie_header()}

    def __repr__(self):
        return "<Session %s source=%s>" % (self.fingerprint, self.source)

def _read_config():
    if not CONFIG_PATH.exists():
        return None, None
    try:
        data = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ConfigError("讀不開 %s：%s" % (CONFIG_PATH, e))
    mode = stat.S_IMODE(CONFIG_PATH.stat().st_mode)
    warning = None
    if mode & 0o077:
        warning = ("%s 的權限是 %o，同機器上的其他使用者讀得到——"
                   "而這個檔案裡放的是你的登入身分。請 chmod 600。" % (CONFIG_PATH, mode))
    return data, warning

def resolve(profile=None, base_url=None):
    warnings = []

    tok = os.environ.get("IAMDIRECTOR_TOKEN", "").strip()
    if tok and not profile:
        return Session(tok, base_url or os.environ.get("APPLETOKEN_BASE_URL", DEFAULT_BASE_URL),
                       source="環境變數 IAMDIRECTOR_TOKEN", kind="token"), warnings

    env = os.environ.get("APPLETOKEN_SESSION", "").strip()
    if env and not profile:
        return Session(env,
                       base_url or os.environ.get("APPLETOKEN_BASE_URL", DEFAULT_BASE_URL),
                       os.environ.get("APPLETOKEN_SESSION_COOKIE", DEFAULT_COOKIE_NAME),
                       "環境變數 APPLETOKEN_SESSION"), warnings

    data, warn = _read_config()
    if warn:
        warnings.append(warn)
    if data:
        name = profile or data.get("default")
        profiles = data.get("profiles") or {}
        if not name:
            if len(profiles) == 1:
                name = next(iter(profiles))
            else:
                raise ConfigError(
                    "%s 有 %d 組 profile 但沒設 default，用 --profile 指定一組。"
                    % (CONFIG_PATH, len(profiles)))
        entry = profiles.get(name)
        if entry is None:
            raise ConfigError("%s 裡沒有 profile「%s」（有的是：%s）"
                              % (CONFIG_PATH, name, "、".join(sorted(profiles)) or "無"))
        value = (entry.get("token") or entry.get("session") or "").strip()
        if not value:
            raise ConfigError("profile「%s」沒有 token（也沒有舊的 session）。%s" % (name, _HOWTO))
        return Session(value,
                       base_url or entry.get("base_url", DEFAULT_BASE_URL),
                       entry.get("cookie_name", DEFAULT_COOKIE_NAME),
                       "%s [%s]" % (CONFIG_PATH, name), name), warnings

    if profile:
        raise ConfigError("指定了 --profile %s，但 %s 不存在。%s"
                          % (profile, CONFIG_PATH, _HOWTO))
    raise ConfigError("找不到登入身分。%s" % _HOWTO)

def save_token(token, base_url=None, profile="me"):
    if not str(token).startswith(TOKEN_PREFIX):
        raise ConfigError("這不是工作台發的權杖（要 %s 開頭）" % TOKEN_PREFIX)
    for v in (token, base_url or ""):
        if any(c in v for c in '"\\\n\r'):
            raise ConfigError("權杖或網址裡有不該出現的字元")
    data = {}
    if CONFIG_PATH.exists():
        try:
            data = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as e:
            raise ConfigError("讀不開 %s：%s（不覆寫，先手動修好）" % (CONFIG_PATH, e))
    profiles = dict(data.get("profiles") or {})
    entry = {k: v for k, v in (profiles.get(profile) or {}).items() if k not in ("session", "token")}
    entry["token"] = token
    if base_url:
        entry["base_url"] = base_url
    profiles[profile] = entry
    lines = ['default = "%s"' % (data.get("default") or profile), ""]
    for name, ent in profiles.items():
        lines.append("[profiles.%s]" % name)
        for k, v in ent.items():
            if isinstance(v, str):
                lines.append('%s = "%s"' % (k, v))
        lines.append("")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_PATH)
    return CONFIG_PATH

def forget(profile="me"):
    if not CONFIG_PATH.exists():
        return False
    data = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    profiles = dict(data.get("profiles") or {})
    ent = profiles.get(profile)
    if not ent or not (ent.get("token") or ent.get("session")):
        return False
    profiles[profile] = {k: v for k, v in ent.items() if k not in ("token", "session")}
    lines = ['default = "%s"' % (data.get("default") or profile), ""]
    for name, e in profiles.items():
        lines.append("[profiles.%s]" % name)
        lines += ['%s = "%s"' % (k, v) for k, v in e.items() if isinstance(v, str)]
        lines.append("")
    CONFIG_PATH.write_text("\n".join(lines), encoding="utf-8")
    os.chmod(CONFIG_PATH, 0o600)
    return True
