import json
import os
import re
import shutil
import subprocess
import sys

SPEC_VERSION = 1

ASPECTS = ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9")
RESOLUTIONS = {"480p": 480, "720p": 720, "1080p": 1080}
FPS_ALLOWED = (24, 25, 30)
SUB_MODES = ("burn", "srt", "both", "none")
LANES = ("A1", "A2")

MAX_VIDEO = 200
MAX_AUDIO = 200
MAX_CUES = 2000
MAX_TOTAL = 30 * 60
MAX_TEXT = 300
MAX_DISCLOSE = 200
MAX_MODELS = 30
MAX_TITLE = 160
FITS = ("pad", "crop")

ID = re.compile(r"^exp_[a-z0-9]{8,40}$")
USER = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,79}$")
BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")

class SpecError(ValueError):
    pass

class RenderError(RuntimeError):
    pass

def out_keys(user, export_id):
    base = "exports/%s/%s" % (user, export_id)
    return {"mp4": base + ".mp4", "webm": base + ".webm", "srt": base + ".srt", "status": base + ".status.json"}

def frame_size(aspect, resolution):
    a, b = (int(x) for x in aspect.split(":"))
    short = RESOLUTIONS[resolution]
    if a >= b:
        w, h = short * a / b, short
    else:
        w, h = short, short * b / a
    return int(round(w / 2)) * 2, int(round(h / 2)) * 2

def _num(v, name, lo=0.0, hi=float(MAX_TOTAL)):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SpecError("%s 要是數字" % name)
    v = float(v)
    if v != v or v < lo or v > hi:
        raise SpecError("%s 超出範圍（%s～%s）：%r" % (name, lo, hi, v))
    return round(v, 3)

def _text(v, name, limit):
    if not isinstance(v, str):
        raise SpecError("%s 要是字串" % name)
    v = v.replace("\r", " ").strip()
    if len(v) > limit:
        raise SpecError("%s 太長（最多 %d 字）" % (name, limit))
    return v

def _src_key(user, key, name):
    if not isinstance(key, str):
        raise SpecError("%s 的 key 要是字串" % name)
    parts = key.split("/")
    if len(parts) != 3 or parts[0] != "originals" or parts[1] != user or not SHA.match(parts[2]):
        raise SpecError("%s 的 key 不在這個使用者的素材前綴底下：%r" % (name, key))
    return key

def validate(spec):
    if not isinstance(spec, dict):
        raise SpecError("規格要是物件")
    if spec.get("version") != SPEC_VERSION:
        raise SpecError("不認得的規格版本：%r" % spec.get("version"))
    eid, user = spec.get("id"), spec.get("user")
    if not isinstance(eid, str) or not ID.match(eid):
        raise SpecError("匯出 id 不合法")
    if not isinstance(user, str) or not USER.match(user):
        raise SpecError("使用者 id 不合法")
    out = {"version": SPEC_VERSION, "id": eid, "user": user}
    for b in ("src_bucket", "out_bucket"):
        v = spec.get(b)
        if not isinstance(v, str) or not BUCKET.match(v):
            raise SpecError("%s 不合法" % b)
        out[b] = v

    fmt = spec.get("format") or {}
    aspect, res = fmt.get("aspect", "16:9"), fmt.get("resolution", "1080p")
    fps = fmt.get("fps", 24)
    if aspect not in ASPECTS:
        raise SpecError("畫面比例只能是 %s" % "／".join(ASPECTS))
    if res not in RESOLUTIONS:
        raise SpecError("解析度只能是 %s" % "／".join(RESOLUTIONS))
    if fps not in FPS_ALLOWED:
        raise SpecError("影格率只能是 %s" % "／".join(map(str, FPS_ALLOWED)))
    fit = fmt.get("fit", "pad")
    if fit not in FITS:
        raise SpecError("畫面填法只能是 %s" % "／".join(FITS))
    out["format"] = {"aspect": aspect, "resolution": res, "fps": fps, "fit": fit}

    vids = spec.get("video")
    if not isinstance(vids, list) or not vids:
        raise SpecError("V1 是空的：至少要有一段影片")
    if len(vids) > MAX_VIDEO:
        raise SpecError("V1 最多 %d 段" % MAX_VIDEO)
    out["video"] = []
    for k, v in enumerate(vids):
        name = "V1 第 %d 段" % (k + 1)
        if not isinstance(v, dict):
            raise SpecError("%s 要是物件" % name)
        a, b = _num(v.get("in", 0), name + " 的入點"), _num(v.get("out"), name + " 的出點")
        if b - a < 0.2:
            raise SpecError("%s 太短（出點要比入點晚至少 0.2 秒）" % name)
        item = {"key": _src_key(user, v.get("key"), name), "in": a, "out": b}
        for f in ("job", "model"):
            if isinstance(v.get(f), str) and MODEL.match(v[f]):
                item[f] = v[f]
        out["video"].append(item)

    auds = spec.get("audio") or []
    if not isinstance(auds, list) or len(auds) > MAX_AUDIO:
        raise SpecError("聲音段最多 %d 段" % MAX_AUDIO)
    out["audio"] = []
    for k, v in enumerate(auds):
        name = "聲音第 %d 段" % (k + 1)
        if not isinstance(v, dict):
            raise SpecError("%s 要是物件" % name)
        lane = v.get("lane", "A1")
        if lane not in LANES:
            raise SpecError("%s 的軌只能是 A1／A2" % name)
        frm = v.get("from", "audio")
        if frm not in ("audio", "video"):
            raise SpecError("%s 的 from 只能是 audio／video" % name)
        dur = _num(v.get("dur"), name + " 的長度", 0.05)
        item = {"lane": lane, "key": _src_key(user, v.get("key"), name),
                "at": _num(v.get("at", 0), name + " 的起點"),
                "in": _num(v.get("in", 0), name + " 的入點"), "dur": dur,
                "gain": _num(v.get("gain", 1.0), name + " 的音量", 0.0, 2.0), "from": frm}
        fade = _num(v.get("fade", 0), name + " 的淡入淡出", 0.0, 1.0)
        if fade:
            item["fade"] = round(min(fade, dur / 4), 3)
        if v.get("loop") is True:
            item["loop"] = True
        out["audio"].append(item)

    subs = spec.get("subtitles") or {}
    mode = subs.get("mode", "none")
    if mode not in SUB_MODES:
        raise SpecError("字幕模式只能是 %s" % "／".join(SUB_MODES))
    cues = subs.get("cues") or []
    if not isinstance(cues, list) or len(cues) > MAX_CUES:
        raise SpecError("字幕最多 %d 句" % MAX_CUES)
    clean = []
    for k, q in enumerate(cues):
        name = "第 %d 句字幕" % (k + 1)
        if not isinstance(q, dict):
            raise SpecError("%s 要是物件" % name)
        s, e = _num(q.get("start"), name + " 的起點"), _num(q.get("end"), name + " 的迄點")
        t = _text(q.get("text", ""), name, MAX_TEXT)
        if e > s and t:
            clean.append({"start": s, "end": e, "text": t})
    clean.sort(key=lambda q: (q["start"], q["end"]))
    out["subtitles"] = {"mode": mode if clean or mode == "none" else "none", "cues": clean}

    models = spec.get("models") or []
    if not isinstance(models, list) or len(models) > MAX_MODELS:
        raise SpecError("模型清單最多 %d 個" % MAX_MODELS)
    seen = []
    for m in models:
        if not isinstance(m, str) or not MODEL.match(m):
            raise SpecError("模型名稱不合法：%r" % (m,))
        if m not in seen:
            seen.append(m)
    out["models"] = seen

    d = spec.get("disclosure") or {}
    on = d.get("on") is True
    dtext = _text(d.get("text", ""), "揭露文字", MAX_DISCLOSE) if on else ""
    dsec = _num(d.get("seconds", 4), "片尾秒數", 2, 8) if on else 0
    dmodels = []
    for m in (d.get("models") or seen) if on else []:
        if not isinstance(m, str) or not MODEL.match(m):
            raise SpecError("片尾的模型名稱不合法：%r" % (m,))
        if m not in dmodels:
            dmodels.append(m)
    out["disclosure"] = {"on": on, "text": dtext, "models": dmodels[:MAX_MODELS], "seconds": dsec}

    titles = spec.get("titles") or {}
    if not isinstance(titles, dict) or any(k not in ("open", "end") for k in titles):
        raise SpecError("titles 只收 open／end")
    out["titles"] = {}
    for k, v in titles.items():
        if not isinstance(v, dict):
            raise SpecError("字卡 %s 要是物件" % k)
        t = _text(v.get("text", ""), "字卡文字", MAX_TITLE)
        if t:
            out["titles"][k] = {"text": t, "seconds": _num(v.get("seconds", 3), "字卡秒數", 1, 8)}

    import twist as _tw
    try:
        out.update(_tw.clean_meme(spec))
    except _tw.TwistError as e:
        raise SpecError(str(e)) from None
    if timing(out)["total"] > MAX_TOTAL:
        raise SpecError("整部超過 %d 分鐘" % (MAX_TOTAL // 60))
    return out

def timing(spec):
    v1 = round(sum(v["out"] - v["in"] for v in spec["video"]), 3)
    end = v1
    for a in spec.get("audio") or []:
        end = max(end, a["at"] + a["dur"])
    for q in (spec.get("subtitles") or {}).get("cues") or []:
        end = max(end, q["end"])
    card = spec["disclosure"]["seconds"] if spec.get("disclosure", {}).get("on") else 0
    body = round(end, 3)
    return {"v1": v1, "body": body, "card": card, "total": round(body + card, 3)}

def _ts(t, sep):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    if sep == ",":
        return "%02d:%02d:%02d,%03d" % (h, m, s, ms)
    return "%d:%02d:%02d.%02d" % (h, m, s, ms // 10)

def card_lines(disclosure):
    if not disclosure.get("on"):
        return []
    lines = [disclosure.get("text") or ""]
    if disclosure.get("models"):
        lines.append("使用的 AI 模型：" + "、".join(disclosure["models"]))
    return [x for x in lines if x]

def srt(cues, extra=None):
    rows = list(cues) + ([extra] if extra else [])
    out = []
    for k, q in enumerate(rows, 1):
        out.append("%d\n%s --> %s\n%s\n" % (k, _ts(q["start"], ","), _ts(q["end"], ","),
                                             q["text"].replace("\n", " ")))
    return "\n".join(out)

def _ass_text(t):
    return t.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", "\\N")

FONT = "WenQuanYi Zen Hei"

MEME_FONT = "Noto Sans TC"
MEME_FONT_FILE = "NotoSansTC-Bold.otf"
CAPTION_MAX, EFFECT_MAX = 20, 10
_CMAP = {}

def font_chars(path):
    if path in _CMAP:
        return _CMAP[path]
    import struct
    with open(path, "rb") as f:
        data = f.read()
    num = struct.unpack(">H", data[4:6])[0]
    off = None
    for i in range(num):
        tag, _c, o, _l = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
        if tag == b"cmap":
            off = o
    if off is None:
        raise RenderError("字型檔沒有 cmap：%s" % os.path.basename(path))
    n = struct.unpack(">H", data[off + 2:off + 4])[0]
    subs = []
    for i in range(n):
        pid, eid, so = struct.unpack(">HHI", data[off + 4 + 8 * i:off + 12 + 8 * i])
        subs.append((pid, eid, off + so))
    chars = set()
    for _pid, _eid, so in subs:
        fmt = struct.unpack(">H", data[so:so + 2])[0]
        if fmt == 12:
            ng = struct.unpack(">I", data[so + 12:so + 16])[0]
            for g in range(ng):
                a, b, _ = struct.unpack(">III", data[so + 16 + 12 * g:so + 28 + 12 * g])
                chars.update(range(a, b + 1))
        elif fmt == 4:
            seg = struct.unpack(">H", data[so + 6:so + 8])[0] // 2
            ends = struct.unpack(">%dH" % seg, data[so + 14:so + 14 + 2 * seg])
            starts = struct.unpack(">%dH" % seg, data[so + 16 + 2 * seg:so + 16 + 4 * seg])
            for a, b in zip(starts, ends):
                if a != 0xFFFF:
                    chars.update(range(a, b + 1))
    _CMAP[path] = chars
    return chars

def meme_font(fontsdir):
    path = os.path.join(fontsdir or "", MEME_FONT_FILE)
    if not fontsdir or not os.path.isfile(path):
        raise RenderError("字卡字型找不到：%s（要 fonts/%s，不改用別的字型）" % (path, MEME_FONT_FILE))
    return path

def check_caption_chars(captions, font_path):
    have = font_chars(font_path)
    miss = sorted({c for q in captions for c in q["text"] if not c.isspace() and ord(c) not in have})
    if miss:
        raise RenderError("字卡裡有字型沒有的字：%s（字型 %s 只含繁中常用字與標點；換個寫法，或換用完整字型）"
                          % ("".join(miss[:20]), MEME_FONT_FILE))

def resolve_meme(spec, files, ffmpeg, body, env=None, detect=None):
    import twist as tw
    caps, effs = spec.get("captions") or [], spec.get("effects") or []
    tcfg = spec.get("twist") or {}
    at = tcfg.get("at")
    if at is None and tcfg.get("auto") and (caps or effs) and spec.get("video"):
        v = spec["video"][0]
        try:
            got = detect(files[v["key"]]) if detect else tw.detect(ffmpeg, files[v["key"]], env=env)
        except tw.TwistError as e:
            raise RenderError("偵測反轉點失敗：%s" % e) from None
        if got.get("at") is not None:
            at = round(got["at"] - v["in"], 3)
    try:
        out_c = [dict(q, start=tw.resolve(q["start"], at, body), end=tw.resolve(q["end"], at, body)) for q in caps]
        out_e = [dict(e, start=tw.resolve(e["start"], at, body), end=tw.resolve(e["end"], at, body)) for e in effs]
    except tw.TwistError as e:
        raise RenderError(str(e)) from None
    return ([q for q in out_c if q["end"] > q["start"]], [e for e in out_e if e["end"] > e["start"]], at)

def meme_ass(captions, W, H):
    def size(q):
        return max(18, int(H * {"xl": 0.055, "xxl": 0.075}.get(q.get("size"), 0.041)))
    base = max(18, int(H * 0.041))
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Meme,%s,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,%d,0,8,%d,%d,%d,1\n"
            "Style: MemeBox,%s,%d,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,%d,0,8,%d,%d,%d,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            % (W, H, MEME_FONT, base, max(2, round(H / 240)), int(W * 0.06), int(W * 0.06), int(H * 0.12),
               MEME_FONT, base, max(4, round(H / 110)), int(W * 0.06), int(W * 0.06), int(H * 0.12)))
    rows = []
    for q in captions:
        st = "MemeBox" if q.get("style") == "memebox" else "Meme"
        pos = q.get("pos") or "top"
        if isinstance(pos, dict):
            tag = "{\\an5\\pos(%d,%d)\\fs%d}" % (W // 2, int(H * float(pos["y"])), size(q))
        else:
            an = {"top": 8, "middle": 5, "bottom": 2}[pos]
            mv = {"top": int(H * 0.12), "middle": 0, "bottom": int(H * 0.2)}[pos]
            tag = "{\\an%d\\fs%d}" % (an, size(q))
            rows.append("Dialogue: 3,%s,%s,%s,,0,0,%d,,%s%s" % (_ts(q["start"], "."), _ts(q["end"], "."), st, mv, tag,
                                                                _ass_text(q["text"])))
            continue
        rows.append("Dialogue: 3,%s,%s,%s,,0,0,0,,%s%s" % (_ts(q["start"], "."), _ts(q["end"], "."), st, tag,
                                                            _ass_text(q["text"])))
    return head + "\n".join(rows) + ("\n" if rows else "")

def flash_filters(effects):
    return ["drawbox=x=0:y=0:w=iw:h=ih:color=white@1:t=fill:enable='between(t,%s,%s)'" % (e["start"], e["end"])
            for e in effects if e.get("type") == "white_flash"]

def title_rows(titles, body):
    out = []
    t = titles or {}
    if t.get("open"):
        out.append({"start": 0.0, "end": round(min(body, t["open"]["seconds"]), 3), "text": t["open"]["text"], "where": "open"})
    if t.get("end"):
        out.append({"start": round(max(0.0, body - t["end"]["seconds"]), 3), "end": round(body, 3),
                    "text": t["end"]["text"], "where": "end"})
    return [x for x in out if x["end"] > x["start"]]

def ass(cues, card, W, H, card_at=0.0, card_dur=0.0, burn_cues=True, titles=None):
    size = max(18, int(H * 0.055))
    csize = max(16, int(H * 0.045))
    osize, esize = max(18, int(min(W, H) * 0.062)), max(16, int(min(W, H) * 0.052))
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Sub,%s,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,%d,0,2,%d,%d,%d,1\n"
            "Style: Card,%s,%d,&H00E6E6E6,&H00E6E6E6,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,0,0,5,%d,%d,0,1\n"
            "Style: Open,%s,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,1,0,0,0,100,100,1,0,1,%d,0,8,%d,%d,%d,1\n"
            "Style: End,%s,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,1,0,0,0,100,100,0,0,1,%d,0,2,%d,%d,%d,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            % (W, H, FONT, size, max(1, size // 14), int(W * 0.06), int(W * 0.06), int(H * 0.06),
               FONT, csize, int(W * 0.12), int(W * 0.12),
               FONT, osize, max(2, osize // 10), int(W * 0.06), int(W * 0.06), int(H * 0.08),
               FONT, esize, max(2, esize // 12), int(W * 0.06), int(W * 0.06), int(H * 0.2)))
    rows = []
    if burn_cues:
        for q in cues:
            rows.append("Dialogue: 0,%s,%s,Sub,,0,0,0,,%s" % (_ts(q["start"], "."), _ts(q["end"], "."),
                                                             _ass_text(q["text"])))
    for q in titles or []:
        rows.append("Dialogue: 2,%s,%s,%s,,0,0,0,,%s" % (_ts(q["start"], "."), _ts(q["end"], "."),
                                                        "Open" if q["where"] == "open" else "End", _ass_text(q["text"])))
    if card:
        rows.append("Dialogue: 1,%s,%s,Card,,0,0,0,,%s" % (
            _ts(card_at, "."), _ts(card_at + card_dur, "."), "\\N\\N".join(_ass_text(x) for x in card)))
    return head + "\n".join(rows) + ("\n" if rows else "")

HEAD_MAX = 8 * 1024 * 1024

def demuxer_of(path):
    try:
        with open(path, "rb") as f:
            h = f.read(16)
            if h.startswith(b"ID3") and len(h) >= 10 and not any(b & 0x80 for b in h[6:10]):
                end = 10 + ((h[6] << 21) | (h[7] << 14) | (h[8] << 7) | h[9]) + (10 if h[5] & 0x10 else 0)
                if end + 2 > HEAD_MAX:
                    return None
                f.seek(end)
                s = f.read(2)
                return "mp3" if len(s) == 2 and s[0] == 0xFF and (s[1] & 0xE0) == 0xE0 else None
    except OSError:
        return None
    if len(h) >= 12 and h[4:8] == b"ftyp":
        return "mov"
    if h.startswith(b"\x1a\x45\xdf\xa3"):
        return "matroska"
    if h.startswith(b"RIFF") and h[8:12] == b"WAVE":
        return "wav"
    if h.startswith(b"OggS"):
        return "ogg"
    if h.startswith(b"fLaC"):
        return "flac"
    if len(h) >= 2 and h[0] == 0xFF and (h[1] & 0xF6) == 0xF0:
        return "aac"
    if len(h) >= 2 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0:
        return "mp3"
    return None

def in_args(path, demuxer):
    if not demuxer:
        raise RenderError("素材不是認得的影音格式（只收 mp4／mov／webm／mkv／mp3／wav／ogg／flac／aac）")
    return ["-protocol_whitelist", "file", "-f", demuxer, "-i", path]

def probe(ffprobe, path, demuxer=None):
    demuxer = demuxer or demuxer_of(path)
    if not demuxer:
        return {"has_audio": False, "has_video": False, "duration": 0.0, "demuxer": None}
    try:
        r = subprocess.run([ffprobe, "-v", "error", "-protocol_whitelist", "file", "-f", demuxer,
                            "-show_entries", "stream=codec_type:format=duration",
                            "-of", "json", path], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL)
        d = json.loads(r.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"has_audio": False, "has_video": False, "duration": 0.0, "demuxer": demuxer}
    kinds = {s.get("codec_type") for s in d.get("streams") or []}
    try:
        dur = float((d.get("format") or {}).get("duration") or 0)
    except ValueError:
        dur = 0.0
    return {"has_audio": "audio" in kinds, "has_video": "video" in kinds, "duration": dur, "demuxer": demuxer}

def ffmpeg_caps(ffmpeg):
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return {"libass": False}
    caps = {"libass": bool(re.search(r"^\s*\S+\s+subtitles\s", r.stdout, re.M))}
    try:
        e = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30,
                           stdin=subprocess.DEVNULL)
        caps["encoders"] = set(re.findall(r"^\s*V\S*\s+(\S+)", e.stdout, re.M))
    except (OSError, subprocess.TimeoutExpired):
        pass
    return caps

H264_BITRATE = {480: "2500k", 720: "5M", 1080: "10M"}

def video_codec_args(caps, height):
    enc = caps.get("encoders")
    if enc is None or "libx264" in enc:
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    rate = H264_BITRATE[min(H264_BITRATE, key=lambda h: abs(h - height))]
    if "h264_videotoolbox" in enc:
        return ["-c:v", "h264_videotoolbox", "-b:v", rate, "-allow_sw", "1"]
    if "h264_mf" in enc:
        return ["-c:v", "h264_mf", "-b:v", rate, "-rate_control", "cbr"]
    if "libopenh264" in enc:
        return ["-c:v", "libopenh264", "-b:v", rate, "-allow_skip_frames", "0"]
    raise RenderError("這支 ffmpeg 沒有可用的 H.264 編碼器")

def webm_codec_args(height):
    rate = H264_BITRATE[min(H264_BITRATE, key=lambda h: abs(h - height))]
    return ["-c:v", "libvpx-vp9", "-b:v", rate, "-deadline", "good", "-cpu-used", "4", "-row-mt", "1"]

def _esc(path):
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

def plan(spec, files, probes, caps, workdir, strict=True, fontsdir=None, container="mp4", caption_fontsdir=None):
    W, H = frame_size(spec["format"]["aspect"], spec["format"]["resolution"])
    fps = spec["format"]["fps"]
    t = timing(spec)
    warnings = []
    mode = spec["subtitles"]["mode"]
    cues = spec["subtitles"]["cues"]
    card = card_lines(spec["disclosure"])
    trows = title_rows(spec.get("titles"), t["body"])
    want_burn = mode in ("burn", "both")
    want_soft = mode in ("srt", "both")
    need_ass = want_burn or bool(card) or bool(trows)
    soft_card = None
    soft_titles = []
    if need_ass and not caps.get("libass"):
        if strict:
            raise RenderError("這支 ffmpeg 沒有 libass（subtitles 濾鏡），燒不了字幕與片尾文字")
        warnings.append("本機 ffmpeg 沒有 libass：字幕改成軟字幕軌，片尾文字放進字幕軌（Lambda 上會燒進畫面）")
        if want_burn:
            want_soft, want_burn = True, False
        if card:
            soft_card = {"start": t["body"], "end": t["total"], "text": " / ".join(card)}
        if trows:
            warnings.append("本機 ffmpeg 沒有 libass：片頭／片尾字卡放進字幕軌")
            soft_titles = [{"start": q["start"], "end": q["end"], "text": q["text"]} for q in trows]
        need_ass = False

    argv = ["-y", "-hide_banner", "-loglevel", "error"]
    graph = []
    idx = 0
    vlabels = []
    for k, v in enumerate(spec["video"]):
        if not (probes.get(v["key"]) or {}).get("has_video"):
            raise RenderError("V1 第 %d 段讀不到影像（素材壞了或不是影片）" % (k + 1))
        argv += in_args(files[v["key"]], (probes.get(v["key"]) or {}).get("demuxer"))
        seg = round(v["out"] - v["in"], 3)
        have = (probes.get(v["key"]) or {}).get("duration") or 0
        if have and have - v["in"] < seg - 0.05:
            warnings.append("V1 第 %d 段素材只有 %.2f 秒，比宣告的 %.2f 秒短，停在最後一格補齊"
                            % (k + 1, max(0.0, have - v["in"]), seg))
        if spec["format"].get("fit") == "crop":
            fitf = "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (W, H, W, H)
        else:
            fitf = "scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black" % (W, H, W, H)
        graph.append("[%d:v]trim=start=%s:end=%s,setpts=PTS-STARTPTS,fps=%d,%s,setsar=1,format=yuv420p,"
                     "tpad=stop_mode=clone:stop_duration=%s,trim=duration=%s,setpts=PTS-STARTPTS[v%d]"
                     % (idx, v["in"], v["out"], fps, fitf, seg, seg, k))
        vlabels.append("[v%d]" % k)
        idx += 1
    graph.append("%sconcat=n=%d:v=1:a=0[vcat]" % ("".join(vlabels), len(vlabels)))
    last = "vcat"
    pad = round(t["body"] - t["v1"], 3)
    if pad > 0.001:
        graph.append("[vcat]tpad=stop_mode=add:stop_duration=%s:color=black[vbody]" % pad)
        last = "vbody"
    meme_caps, meme_raw_fx = spec.get("captions") or [], spec.get("effects") or []
    if any(not isinstance(x.get(k), float) for x in meme_caps + meme_raw_fx for k in ("start", "end")):
        raise RenderError("字卡／特效的時間還沒解析成秒數（要先跑 resolve_meme）")
    meme_fx = flash_filters(meme_raw_fx)
    if meme_fx:
        graph.append("[%s]%s[vfx]" % (last, ",".join(meme_fx)))
        last = "vfx"
    if meme_caps:
        if not caps.get("libass"):
            raise RenderError("這支 ffmpeg 沒有 libass（subtitles 濾鏡），燒不了迷因字卡")
        cdir = caption_fontsdir or os.environ.get("CAPTION_FONTS_DIR") or fontsdir
        fpath = meme_font(cdir)
        check_caption_chars(meme_caps, fpath)
        mpath = os.path.join(workdir, "meme.ass")
        with open(mpath, "w", encoding="utf-8") as f:
            f.write(meme_ass(meme_caps, W, H))
        graph.append("[%s]subtitles=filename='%s':fontsdir='%s'[vmeme]" % (last, _esc(mpath), _esc(cdir)))
        last = "vmeme"
    if t["card"]:
        graph.append("color=c=black:s=%dx%d:r=%d:d=%s,format=yuv420p,setsar=1[vcard]" % (W, H, fps, t["card"]))
        graph.append("[%s][vcard]concat=n=2:v=1:a=0[vall]" % last)
        last = "vall"
    ass_path = None
    if need_ass:
        ass_path = os.path.join(workdir, "subs.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass(cues, card, W, H, t["body"], t["card"], burn_cues=want_burn, titles=trows))
        opt = "subtitles=filename='%s'" % _esc(ass_path)
        if fontsdir:
            opt += ":fontsdir='%s'" % _esc(fontsdir)
        graph.append("[%s]%s[vout]" % (last, opt))
        last = "vout"

    alabels = ["[sil]"]
    graph.append("anullsrc=r=48000:cl=stereo,atrim=duration=%s[sil]" % t["total"])
    for k, a in enumerate(spec["audio"]):
        pr = probes.get(a["key"]) or {}
        if not pr.get("has_audio"):
            warnings.append("聲音第 %d 段沒有音軌，略過" % (k + 1))
            continue
        argv += (["-stream_loop", "-1"] if a.get("loop") else []) + in_args(files[a["key"]], pr.get("demuxer"))
        ms = int(round(a["at"] * 1000))
        fade = a.get("fade") or 0
        fl = ("afade=t=in:st=0:d=%s,afade=t=out:st=%s:d=%s," % (fade, round(a["dur"] - fade, 3), fade)) if fade else ""
        graph.append("[%d:a]atrim=start=%s:end=%s,asetpts=PTS-STARTPTS,aresample=48000,"
                     "aformat=sample_fmts=fltp:channel_layouts=stereo,%svolume=%s,adelay=%d|%d[a%d]"
                     % (idx, a["in"], round(a["in"] + a["dur"], 3), fl, a["gain"], ms, ms, k))
        alabels.append("[a%d]" % k)
        idx += 1
    if len(alabels) > 1:
        graph.append("%samix=inputs=%d:duration=first:dropout_transition=0:normalize=0[aout]"
                     % ("".join(alabels), len(alabels)))
    else:
        graph.append("[sil]anull[aout]")

    srt_text = None
    soft_idx = None
    if want_soft or soft_card or soft_titles:
        srt_text = srt(sorted((cues if want_soft else []) + soft_titles, key=lambda q: q["start"]), soft_card)
        srt_path = os.path.join(workdir, "subs.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_text)
        argv += in_args(srt_path, "srt")
        soft_idx = idx
        idx += 1

    if container not in ("mp4", "webm"):
        raise RenderError("不支援的輸出格式：%r" % container)
    webm = container == "webm"
    out = os.path.join(workdir, "out." + container)
    argv += ["-filter_complex", ";".join(graph), "-map", "[%s]" % last, "-map", "[aout]"]
    if soft_idx is not None:
        argv += ["-map", "%d:s" % soft_idx, "-c:s", "webvtt" if webm else "mov_text", "-metadata:s:s:0", "language=chi"]
    if webm:
        argv += webm_codec_args(H) + ["-pix_fmt", "yuv420p", "-r", str(fps),
                 "-c:a", "libopus", "-b:a", "160k", "-ar", "48000", "-t", str(t["total"]), out]
    else:
        argv += video_codec_args(caps, H) + ["-pix_fmt", "yuv420p", "-r", str(fps),
                 "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", str(t["total"]),
                 "-movflags", "+faststart", out]
    sidecar = srt(cues) if mode in ("srt", "both") and cues else None
    return {"argv": argv, "total": t["total"], "warnings": warnings, "srt_text": sidecar,
            "out": out, "size": [W, H]}

def _engine_note(event, engine, reason=None):
    print("[postblocks] " + json.dumps({"event": event, "engine": engine, "reason": reason}, ensure_ascii=False),
          file=sys.stderr, flush=True)

def _diff(new, old):
    for k in ("argv", "total", "warnings", "srt_text", "out", "size"):
        if new.get(k) != old.get(k):
            return k
    for path, text in sorted(new.get("files", {}).items()):
        try:
            with open(path, encoding="utf-8") as f:
                if f.read() != text:
                    return "file:" + os.path.basename(path)
        except OSError:
            return "file:" + os.path.basename(path)
    for name in ("meme.ass", "subs.ass", "subs.srt"):
        path = os.path.join(os.path.dirname(old["out"]), name)
        if os.path.exists(path) and path not in new.get("files", {}):
            return "file:" + name
    return None

def plan_select(spec, files, probes, caps, workdir, strict=True, fontsdir=None, container="mp4",
                caption_fontsdir=None, engine=None, note=None, pipeline=None):
    note = note or _engine_note
    try:
        import postblocks
        mode = postblocks.engine_of(engine)
    except Exception as e:
        note("fallback", engine or "?", "import:%s" % type(e).__name__)
        mode, postblocks = "legacy", None
    kw = dict(strict=strict, fontsdir=fontsdir, container=container, caption_fontsdir=caption_fontsdir)
    if mode == "legacy":
        if pipeline:
            note("pipeline_ignored", mode, None)
        return plan(spec, files, probes, caps, workdir, **kw)
    if pipeline:
        try:
            pipe, custom = postblocks.merge(spec, postblocks.clean_user(pipeline), container)
        except Exception as e:
            pipe, custom = None, True
            why0 = "pipeline:%s" % type(e).__name__
        else:
            why0 = None
        if custom:
            if mode == "shadow" or why0:
                note("shadow" if mode == "shadow" else "fallback", mode, why0 or "custom")
                return plan(spec, files, probes, caps, workdir, **kw)
            try:
                new, dropped = postblocks.compile_custom(pipe, files, probes, caps, workdir, **kw)
            except Exception as e:
                note("fallback", mode, "exception:%s" % type(e).__name__)
                return plan(spec, files, probes, caps, workdir, **kw)
            for path, text in new["files"].items():
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
            for bid, why in dropped:
                note("dropped", mode, "%s:%s" % (bid, why))
            note("used_custom", mode, None)
            out = {k: v for k, v in new.items() if k != "files"}
            if dropped:
                out["dropped"] = [bid for bid, _w in dropped]
            m6 = [b["use"] for b in pipe["blocks"] if b.get("on", True) and b["use"] not in out.get("dropped", [])
                  and getattr(postblocks.REGISTRY[b["use"]], "drop_on_fail", False)]
            if m6:
                out["m6_blocks"] = m6
            return out
    new, why = None, None
    try:
        new = postblocks.compile_spec(spec, files, probes, caps, workdir, **kw)
    except postblocks.PipelineError as e:
        why = "pipeline:%s" % (str(e).split("：")[0].split(".")[0][:40])
    except Exception as e:
        why = "exception:%s" % type(e).__name__
    old = plan(spec, files, probes, caps, workdir, **kw)
    if why is None:
        why = _diff(new, old)
    if mode == "shadow":
        note("shadow", mode, why or "same")
        return old
    if why is not None:
        note("fallback", mode, why)
        return old
    for path, text in new["files"].items():
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    note("used", mode, None)
    return {k: v for k, v in new.items() if k != "files"}

def _resolve_select(spec, files, ffmpeg, body, engine=None, note=None, pipeline=None):
    note = note or _engine_note
    try:
        import postblocks
        mode = postblocks.engine_of(engine)
    except Exception as e:
        note("fallback", engine or "?", "import:%s" % type(e).__name__)
        return resolve_meme(spec, files, ffmpeg, body) + ([],)
    if mode == "legacy":
        return resolve_meme(spec, files, ffmpeg, body) + ([],)
    import twist as tw
    memo = {}

    def detect(src):
        if src not in memo:
            memo[src] = tw.detect(ffmpeg, src)
        return memo[src]
    new, why = None, None
    try:
        new = postblocks.analyze_spec(spec, files, detect, body, pipeline if mode == "blocks" else None)
    except Exception as e:
        why = "analyze:%s" % type(e).__name__
    if new is not None and new[4] and mode == "blocks":
        note("used_custom", mode, "analyze")
        return new[0], new[1], new[2], list(new[3])
    old = resolve_meme(spec, files, ffmpeg, body, detect=detect)
    if why is None and tuple(new[:3]) != tuple(old):
        why = "analyze"
    if mode == "shadow":
        note("shadow", mode, why or "same")
    elif why:
        note("fallback", mode, why)
    return old + ([],)

def _captions_burned(spec, pipeline, engine=None):
    if not spec.get("captions"):
        return False
    try:
        import postblocks
        if postblocks.engine_of(engine) == "blocks" and pipeline:
            off = [b for b in postblocks.clean_user(pipeline) if b["use"] == "meme_captions" and not b.get("on", True)]
            return not off
    except Exception:
        pass
    return True

def _seam_qc(pipeline, spec, files, ffmpeg, engine=None, note=None):
    if not pipeline:
        return None
    note = note or _engine_note
    try:
        import postblocks
        if postblocks.engine_of(engine) != "blocks":
            return None
        return postblocks.seam_reports(pipeline, spec, files, ffmpeg)
    except Exception as e:
        note("fallback", "blocks", "seam_check:%s" % type(e).__name__)
        return None

def _blocks_on(pipeline, engine):
    if not pipeline:
        return None
    try:
        import postblocks
        return postblocks if postblocks.engine_of(engine) == "blocks" else None
    except Exception:
        return None

def _extra_fetch(pipeline, spec, fetch, workdir, files, probes, engine=None, note=None):
    pb = _blocks_on(pipeline, engine)
    if pb is None:
        return
    note = note or _engine_note
    try:
        for n, key in enumerate(pb.extra_inputs(pipeline, spec)):
            if key in files:
                continue
            path = os.path.join(workdir, "extra_%03d" % n)
            fetch(spec["src_bucket"], key, path)
            from postblocks.watermark import image_kind
            files[key] = path
            probes[key] = {"image": image_kind(path), "has_video": False, "has_audio": False}
    except Exception as e:
        note("fallback", "blocks", "extra_input:%s" % type(e).__name__)

def _cover(pipeline, out_path, container, duration, fps, put, bucket, video_key, ffmpeg, engine=None, note=None):
    pb = _blocks_on(pipeline, engine)
    if pb is None:
        return None, None
    note = note or _engine_note
    try:
        dest = os.path.join(os.path.dirname(out_path), "cover.img")
        got = pb.cover_output(pipeline, out_path, "matroska" if container == "webm" else "mov", duration, dest, ffmpeg, fps)
        if got is None:
            return None, None
        path, fmt, rep = got
        if not path or not os.path.exists(path):
            return None, rep
        key = video_key.rsplit(".", 1)[0] + ".cover." + fmt
        put(bucket, key, path, "image/jpeg" if fmt == "jpg" else "image/png")
        return {"key": key, "format": fmt}, rep
    except Exception as e:
        note("fallback", "blocks", "cover:%s" % type(e).__name__)
        return None, None

def _run_steps(ffmpeg, p):
    vals = {}
    for k, st in enumerate(p["steps"]):
        argv = []
        for a in st["argv"]:
            for name, v in vals.items():
                a = a.replace("@@%s@@" % name, v)
            argv.append(a)
        if any("@@" in a for a in argv):
            raise RenderError("後製積木第 %d 段還有沒填的值" % (k + 1))
        r = subprocess.run([ffmpeg] + argv, capture_output=True, text=True, timeout=14 * 60, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            raise RenderError("ffmpeg 第 %d 段失敗（%d）：%s" % (k + 1, r.returncode, (r.stderr or "")[-600:]))
        if st.get("capture") == "loudnorm":
            m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr or "", re.S)
            if not m:
                raise RenderError("量不到響度（loudnorm 沒有回量測值）")
            got = json.loads(m.group(0))
            for name in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
                v = str(got.get(name, ""))
                if not re.match(r"^-?(\d+(\.\d+)?|inf)$", v):
                    raise RenderError("響度量測值看不懂：%s" % name)
                vals[st.get("prefix", "") + name] = v
    if not os.path.exists(p["out"]):
        raise RenderError("ffmpeg 沒有產生成片")

NO_LIBASS_CAPTIONS = "這支 ffmpeg 沒有 libass（subtitles 濾鏡）：迷因字卡沒有燒進畫面，先輸出無字版（白閃照常）"

def _captions_fallback(spec, caps):
    if spec.get("captions") and not caps.get("libass"):
        print("[captions] " + json.dumps({"event": "fallback", "reason": "no_libass", "count": len(spec["captions"])}),
              file=sys.stderr, flush=True)
        return dict(spec, captions=[]), [NO_LIBASS_CAPTIONS]
    return spec, []

def run(spec, fetch, put, workdir, ffmpeg=None, ffprobe=None, strict=True, fontsdir=None, status=None,
        container="mp4", caption_fontsdir=None, engine=None):
    ffmpeg = ffmpeg or shutil.which("ffmpeg") or "ffmpeg"
    ffprobe = ffprobe or shutil.which("ffprobe") or "ffprobe"
    report = status or (lambda d: None)
    eid = spec.get("id") if isinstance(spec, dict) else None
    pipeline = spec.get("pipeline") if isinstance(spec, dict) and isinstance(spec.get("pipeline"), list) else None
    try:
        spec = validate(spec)
    except SpecError as e:
        st = {"state": "failed", "id": eid, "error": "規格不合法：%s" % e}
        report(st)
        return st
    keys = out_keys(spec["user"], spec["id"])
    report({"state": "rendering", "id": spec["id"]})
    try:
        os.makedirs(workdir, exist_ok=True)
        files, probes = {}, {}
        wanted = [v["key"] for v in spec["video"]] + [a["key"] for a in spec["audio"]]
        for n, key in enumerate(dict.fromkeys(wanted)):
            path = os.path.join(workdir, "src_%03d" % n)
            fetch(spec["src_bucket"], key, path)
            files[key] = path
            probes[key] = probe(ffprobe, path)
        _extra_fetch(pipeline, spec, fetch, workdir, files, probes, engine)
        if spec.get("captions") or spec.get("effects"):
            caps_, effs_, at_, twist_warn = _resolve_select(spec, files, ffmpeg, timing(spec)["body"], engine,
                                                            pipeline=pipeline)
            spec = dict(spec, captions=caps_, effects=effs_, twist=dict(spec.get("twist") or {}, resolved=at_))
        else:
            twist_warn = []
        fcaps = ffmpeg_caps(ffmpeg)
        spec, extra_warn = _captions_fallback(spec, fcaps)
        extra_warn = twist_warn + extra_warn
        p = plan_select(spec, files, probes, fcaps, workdir, strict=strict, fontsdir=fontsdir,
                        container=container, caption_fontsdir=caption_fontsdir, engine=engine, pipeline=pipeline)
        p = dict(p, warnings=list(p["warnings"]) + extra_warn)
        if p.get("steps"):
            try:
                _run_steps(ffmpeg, p)
            except (RenderError, OSError, subprocess.TimeoutExpired) as e:
                _engine_note("fallback", "blocks", "steps:%s" % type(e).__name__)
                p = plan(spec, files, probes, ffmpeg_caps(ffmpeg), workdir, strict=strict, fontsdir=fontsdir,
                         container=container, caption_fontsdir=caption_fontsdir)
        if not p.get("steps"):
            r = subprocess.run([ffmpeg] + p["argv"], capture_output=True, text=True, timeout=14 * 60,
                               stdin=subprocess.DEVNULL)
            if (r.returncode != 0 or not os.path.exists(p["out"])) and p.get("m6_blocks"):
                _engine_note("fallback", "blocks", "runtime:ffmpeg%d" % r.returncode)
                gone = list(p.get("dropped") or []) + p["m6_blocks"]
                p = plan(spec, files, probes, ffmpeg_caps(ffmpeg), workdir, strict=strict, fontsdir=fontsdir,
                         container=container, caption_fontsdir=caption_fontsdir)
                p = dict(p, warnings=list(p["warnings"]) + extra_warn, dropped=gone)
                r = subprocess.run([ffmpeg] + p["argv"], capture_output=True, text=True, timeout=14 * 60,
                                   stdin=subprocess.DEVNULL)
            if r.returncode != 0 or not os.path.exists(p["out"]):
                raise RenderError("ffmpeg 失敗（%d）：%s" % (r.returncode, (r.stderr or "")[-600:]))
        put(spec["out_bucket"], keys[container], p["out"], "video/" + container)
        if p["srt_text"]:
            put(spec["out_bucket"], keys["srt"], p["srt_text"].encode("utf-8"), "application/x-subrip")
        got = probe(ffprobe, p["out"], "matroska" if container == "webm" else "mov")
        st = {"state": "done", "id": spec["id"], "duration": round(got["duration"], 3),
              "bytes": os.path.getsize(p["out"]), "srt": bool(p["srt_text"]), "size": p["size"],
              "warnings": p["warnings"], "models": spec["models"], "container": container}
        st["captions_burned"] = _captions_burned(spec, pipeline, engine)
        qc = _seam_qc(pipeline, spec, files, ffmpeg, engine)
        extra_qc = [{"block": bid, "subject": bid, "ok": False, "score": None, "defects": ["blocks_fallback"],
                     "redo": {"scope": "step", "target": bid}, "source": "compile", "note": "編譯失敗，已拿掉"}
                    for bid in p.get("dropped") or []]
        cov, crep = _cover(pipeline, p["out"], container, st["duration"], spec["format"]["fps"], put,
                           spec["out_bucket"], keys[container], ffmpeg, engine)
        if cov is not None:
            st["cover"] = cov
        if crep is not None:
            extra_qc.append(crep)
        if extra_qc:
            qc = (qc or []) + extra_qc
        if qc is not None:
            st["qc"] = qc
    except (RenderError, OSError, subprocess.TimeoutExpired) as e:
        st = {"state": "failed", "id": spec["id"], "error": str(e)[:800]}
    report(st)
    return st
