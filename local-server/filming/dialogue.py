import os

ENV = "STUDIO_DIALOGUE_TEMPLATE"
VERSION = 1
MAX_ROWS = 60
LINE_MAX = 500
EMOJI_MAX = 8
BLOCKED = {
    "voice_line": "voice_line 還沒開放（對嘴第二階段 a：要等 MCP 工具表改完）",
    "lipsync_shot": "lipsync_shot 還沒開放（對嘴第二階段 b：要等 MCP 工具表改完）",
}
OFF = "對白長片範本沒開（%s 預設關）" % ENV

class DialogueError(ValueError):
    pass

def enabled():
    return os.environ.get(ENV, "").strip().lower() in ("1", "on", "true")

def _text(v, where, limit, required=False):
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise DialogueError("%s 不能是空的" % where)
        return None
    if not isinstance(v, str):
        raise DialogueError("%s 要是字串" % where)
    v = v.strip()
    if len(v) > limit:
        raise DialogueError("%s 最多 %d 字" % (where, limit))
    return v

def _row(r, i):
    where = "第 %d 列" % (i + 1)
    if not isinstance(r, dict):
        raise DialogueError("%s 要是 {shot, speaker, line, emoji}" % where)
    extra = set(r) - {"shot", "speaker", "line", "emoji"}
    if extra:
        raise DialogueError("%s 有不認得的欄位 %s" % (where, "、".join(sorted(extra))))
    shot = r.get("shot")
    if isinstance(shot, bool) or not isinstance(shot, (str, int)) or str(shot).strip() == "":
        raise DialogueError("%s 的 shot 要是鏡頭編號或名字" % where)
    line = _text(r.get("line"), where + " 的 line", LINE_MAX)
    speaker = _text(r.get("speaker"), where + " 的 speaker", 40, required=bool(line))
    emoji = r.get("emoji") or []
    if not isinstance(emoji, list) or not all(isinstance(e, str) and e.strip() for e in emoji) or len(emoji) > EMOJI_MAX:
        raise DialogueError("%s 的 emoji 要是最多 %d 個字串" % (where, EMOJI_MAX))
    return {"shot": str(shot).strip(), "speaker": speaker, "line": line, "emoji": [e.strip() for e in emoji]}

def expand(rows, voices=None):
    if not enabled():
        raise DialogueError(OFF)
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise DialogueError("分鏡表要是 1–%d 列的清單" % MAX_ROWS)
    if voices is not None and not (isinstance(voices, dict)
                                   and all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in voices.items())):
        raise DialogueError("voices 要是 {speaker: voice}")
    given = {k.strip(): v.strip() for k, v in (voices or {}).items()}
    cast, needs, steps = {}, [], []
    for i, raw in enumerate(rows):
        r = _row(raw, i)
        if not r["line"]:
            steps.append({"n": len(steps) + 1, "step": "video_quote", "shot": r["shot"], "speaker": r["speaker"],
                          "emoji": r["emoji"], "tool": "video_quote", "available": True, "spends": True})
            continue
        sp = r["speaker"]
        if sp not in cast:
            cast[sp] = given.get(sp)
            if cast[sp] is None:
                needs.append(sp)
        voice = {"n": len(steps) + 1, "step": "voice_line", "shot": r["shot"], "speaker": sp, "voice": cast[sp],
                 "text": r["line"], "tool": None, "available": False, "blocked": BLOCKED["voice_line"], "spends": True}
        steps.append(voice)
        steps.append({"n": len(steps) + 1, "step": "lipsync_shot", "shot": r["shot"], "speaker": sp, "voice": cast[sp],
                      "emoji": r["emoji"], "audio_from": voice["n"], "seconds": "from_audio",
                      "tool": None, "available": False, "blocked": BLOCKED["lipsync_shot"], "spends": True})
    blocked = sorted({s["step"] for s in steps if not s["available"]})
    return {"version": VERSION, "runnable": not blocked, "steps": steps, "voices": cast, "needs_voice": needs,
            "blocked": blocked}
