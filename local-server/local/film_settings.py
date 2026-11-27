import json
import os

FILE = "film_settings.json"
ON = ("1", "on", "true")
ITEMS = {
    "seam_xfade": ("STUDIO_FILM_SEAM_XFADE", "bool"),
    "seam_xfade_seconds": ("STUDIO_FILM_SEAM_XFADE_SECONDS", "seconds"),
    "seam_afade": ("STUDIO_FILM_SEAM_AFADE", "bool"),
    "seam_trim": ("STUDIO_FILM_SEAM_TRIM", "bool"),
    "seam_redo": ("STUDIO_LONG_FILM_SEAM_REDO", "bool"),
    "long_film": ("STUDIO_LONG_FILM", "bool"),
}
SECONDS_RANGE = (0.05, 1.5)
SECONDS_DEFAULT = 0.2

class SettingsError(ValueError):
    pass

def _path(data_dir):
    return os.path.join(data_dir, FILE)

def _valid(kind, v):
    if kind == "bool":
        return isinstance(v, bool)
    return (not isinstance(v, bool) and isinstance(v, (int, float)) and SECONDS_RANGE[0] <= v <= SECONDS_RANGE[1])

def read(data_dir):
    if not data_dir:
        return {}
    try:
        with open(_path(data_dir), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in ITEMS and _valid(ITEMS[k][1], v)}

def _env_str(kind, v):
    return ("on" if v else "off") if kind == "bool" else str(v)

def effective_env(data_dir, base=None):
    env = dict(os.environ if base is None else base)
    for k, v in read(data_dir).items():
        name, kind = ITEMS[k]
        if not str(env.get(name, "")).strip():
            env[name] = _env_str(kind, v)
    return env

def info(data_dir, base=None):
    base = os.environ if base is None else base
    setting = read(data_dir)
    out = {}
    for k, (name, kind) in ITEMS.items():
        raw = str(base.get(name, "")).strip()
        if raw:
            src = "env"
        elif k in setting:
            src = "file"
        else:
            src = "default"
        row = {"setting": setting.get(k), "env": raw or None, "source": src, "env_name": name}
        if kind == "bool":
            row["on"] = (raw.lower() in ON) if raw else bool(setting.get(k, False))
        else:
            try:
                v = float(raw) if raw else setting.get(k, SECONDS_DEFAULT)
            except ValueError:
                v = SECONDS_DEFAULT
            row["value"] = round(v, 3) if SECONDS_RANGE[0] <= v <= SECONDS_RANGE[1] else SECONDS_DEFAULT
        out[k] = row
    return {"items": out}

def write(data_dir, updates):
    if updates == {"on": None}:
        if os.path.exists(_path(data_dir)):
            os.remove(_path(data_dir))
        return
    if not isinstance(updates, dict) or not updates:
        raise SettingsError("要給 {名稱: 值}，值是 true／false（秒數是 0.05–1.5 的數字），或 null 回到預設")
    for k, v in updates.items():
        if k not in ITEMS:
            raise SettingsError("不認得的設定 %s（認得：%s）" % (k, "、".join(ITEMS)))
        if v is not None and not _valid(ITEMS[k][1], v):
            raise SettingsError("%s 要是 %s，或 null 回到預設" % (k, "true／false" if ITEMS[k][1] == "bool"
                                                              else "%s–%s 的數字" % SECONDS_RANGE))
    cur = read(data_dir)
    for k, v in updates.items():
        if v is None:
            cur.pop(k, None)
        else:
            cur[k] = v
    path = _path(data_dir)
    if not cur:
        if os.path.exists(path):
            os.remove(path)
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f)
    os.replace(tmp, path)

def export_body(body, env):
    xf = str(env.get(ITEMS["seam_xfade"][0], "")).strip().lower() in ON
    af = str(env.get(ITEMS["seam_afade"][0], "")).strip().lower() in ON
    if not (xf or af) or not isinstance(body, dict):
        return body, {}
    try:
        d = float(env.get(ITEMS["seam_xfade_seconds"][0]) or SECONDS_DEFAULT)
    except ValueError:
        d = SECONDS_DEFAULT
    d = round(d, 3) if SECONDS_RANGE[0] <= d <= SECONDS_RANGE[1] else SECONDS_DEFAULT
    out, applied = dict(body), {}
    video = body.get("video") if isinstance(body.get("video"), list) else []
    pipe = body.get("pipeline") if isinstance(body.get("pipeline"), list) else None
    has_tr = any(isinstance(b, dict) and b.get("use") == "transition" for b in pipe or [])
    if xf and len(video) > 1 and not has_tr and (pipe is not None or "pipeline" not in body):
        out["pipeline"] = list(pipe or []) + [{"use": "transition", "params": {"duration": d, "style": "fade"}}]
        applied["seam_xfade"] = d
    if af and isinstance(body.get("audio"), list):
        audio, n = [], 0
        for a in body["audio"]:
            if isinstance(a, dict) and a.get("job") and not a.get("fade"):
                a = dict(a, fade=d)
                n += 1
            audio.append(a)
        if n:
            out["audio"] = audio
            applied["seam_afade"] = d
    return (out, applied) if applied else (body, {})
