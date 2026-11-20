import re

MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,79}$")
STYLES = ("meme", "memebox")
CAP_SIZES = ("l", "xl", "xxl")
RESOLUTIONS = ("720p", "1080p")
_NAME = re.compile(r"\b[A-Z][a-z]{1,}\b")
_COMMON = {"The", "A", "An", "At", "In", "On", "For", "Then", "When", "They", "He", "She", "It", "We", "His", "Her",
           "Their", "This", "That", "After", "Before", "Suddenly", "Both", "Two", "One", "First", "Finally", "And", "But",
           "Static", "Only", "Photorealistic", "Characters", "Everything", "With", "While", "As", "Its", "Our", "There"}

class TemplateError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg

MEME = {
    "id": "meme",
    "name": "迷因短片",
    "aspect_ratio": "9:16",
    "seconds": (11, 15),
    "model": "gputw/minimax-h3",
    "negative_prompt": ("humans, hands, extra animals, collar, leash, text, watermark, subtitles, camera movement, "
                        "camera shake, zoom, cuts, scene change, music"),
    "resolution": "720p",
    "fields": {
        "setup": "前段情境（反轉之前，畫面上在做什麼）",
        "twist_at": "第幾秒反轉",
        "chaos": "後段暴走的內容（反轉之後到結尾）",
        "seconds": "總長 11–15 秒（預設 15）",
        "characters": "角色外觀描述（選填，300 字以內；例如「小白: a fluffy cream-colored toy poodle; 橘子: an orange tabby cat」）",
        "resolution": "解析度（720p 或 1080p，預設 720p；這個模型照解析度計價）",
        "extra_negative": "追加的 negative（選填，200 字以內；接在範本內建的那一份後面，內建的刪不掉）",
        "props": "道具（選填，120 字以內；明確寫進提示詞，例如 she wears a headband and a whistle clearly visible）",
        "visual_cues": "一定要看得見的元素（選填，120 字以內；例如 visible rain streaks and puddles）",
        "allow_cuts": "允許切鏡頭（選填，預設 false＝一鏡到底；true＝提示詞不寫一鏡到底、negative 拿掉 cuts／scene change）",
        "count_animals": "characters 寫了幾個角色就加一句「Only N animals in the entire video」（預設 true；false＝不加；"
                         "1–9 的數字＝直接用這個數，characters 數不出來也加）",
        "cap_setup": "前段字卡（選填，40 字以內）",
        "cap_twist": "反轉之後的字卡（選填，40 字以內）",
        "flash_before": "反轉前幾秒閃一下白光（選填，0.3–3 秒；例如拍照的閃光）",
        "style": "字卡樣式：meme（白字黑描邊，預設）或 memebox（黑字白底）",
        "cap_size": "字卡字級：l（預設，畫面高度 4.1%）、xl（5.5%）、xxl（7.5%，手機上最清楚）",
        "model": "模型（選填，預設 gputw/minimax-h3）",
        "first_frame": "首幀（選填；圖片網址或 asset://，不收 data URI——欄位存在作品裡；長片接力的上一段最後一格）",
        "last_frame": "尾幀（選填；同上。模型能力表沒實測過的寫法會直接擋）",
    },
}
FRAME_MAX = 2000
FRAME_OK = re.compile(r"^(https?://|asset://)\S+$", re.I)

def _model_caps():
    import importlib.util
    import os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cli", "appletoken", "core", "model_caps.py")
    spec = importlib.util.spec_from_file_location("_iamdirector_model_caps", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
TEMPLATES = {"meme": MEME}

def _text(fields, k, limit, required=False):
    v = fields.get(k)
    if v is None or v == "":
        if required:
            raise TemplateError(400, "%s 要填（%s）" % (k, MEME["fields"][k]))
        return ""
    if not isinstance(v, str):
        raise TemplateError(400, "%s 要是字串" % k)
    v = " ".join(v.split())
    if len(v) > limit:
        raise TemplateError(400, "%s 太長（最多 %d 字）" % (k, limit))
    return v

def _num(fields, k, lo, hi, default=None):
    v = fields.get(k, default)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise TemplateError(400, "%s 要是 %s–%s 之間的數字" % (k, lo, hi))
    return round(float(v), 2)

def _flag(fields, k, default):
    v = fields.get(k, default)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise TemplateError(400, "%s 要是 true 或 false" % k)
    return v

def count_characters(chars):
    parts = [p.strip() for p in re.split(r"[;；\n]", chars or "") if p.strip()]
    if not parts or len(parts) > 9 or not all(re.match(r"^[^:：]{1,40}[:：]\s*\S", p) for p in parts):
        return None
    return len(parts)

def meme(fields):
    if not isinstance(fields, dict):
        raise TemplateError(400, "fields 要是物件")
    unknown = sorted(k for k in fields if k not in MEME["fields"])
    if unknown:
        raise TemplateError(400, "迷因短片範本沒有這些欄位：%s" % "、".join(unknown))
    lo, hi = MEME["seconds"]
    seconds = int(_num(fields, "seconds", lo, hi, default=hi))
    setup = _text(fields, "setup", 600, required=True)
    chaos = _text(fields, "chaos", 600, required=True)
    if fields.get("twist_at") is None:
        raise TemplateError(400, "twist_at 要填（%s）" % MEME["fields"]["twist_at"])
    twist_at = _num(fields, "twist_at", 2, seconds - 2)
    chars = _text(fields, "characters", 300)
    res = fields.get("resolution") or MEME["resolution"]
    if res not in RESOLUTIONS:
        raise TemplateError(400, "resolution 只能是 %s" % "／".join(RESOLUTIONS))
    extra_neg = _text(fields, "extra_negative", 200).strip(" ,，")
    props = _text(fields, "props", 120)
    cues = _text(fields, "visual_cues", 120)
    allow_cuts = _flag(fields, "allow_cuts", False)
    ca = fields.get("count_animals")
    if isinstance(ca, int) and not isinstance(ca, bool):
        if not 1 <= ca <= 9:
            raise TemplateError(400, "count_animals 要是 true／false，或 1–9 的數字")
        n_animals = ca
    else:
        n_animals = count_characters(chars) if _flag(fields, "count_animals", True) else None
    flash = _num(fields, "flash_before", 0.3, 3)
    style = fields.get("style") or "meme"
    if style not in STYLES:
        raise TemplateError(400, "style 只能是 %s" % "／".join(STYLES))
    cap_size = fields.get("cap_size")
    if cap_size is not None and cap_size not in CAP_SIZES:
        raise TemplateError(400, "cap_size 只能是 %s" % "／".join(CAP_SIZES))
    model = fields.get("model") or MEME["model"]
    if not isinstance(model, str) or not MODEL.match(model):
        raise TemplateError(400, "model 不合法")

    tw = ("%g" % twist_at)
    opening = ("Static locked-off camera, %d-second video, full-body wide framing, no camera movement." % seconds
               if allow_cuts else
               "Static locked-off camera, one continuous %d-second shot, full-body wide framing, "
               "no camera movement, no cuts." % seconds)
    prompt = " ".join(x for x in (
        opening,
        ("Characters: %s." % chars.rstrip(".")) if chars else "",
        ("Only %d %s in the entire video." % (n_animals, "animal" if n_animals == 1 else "animals")) if n_animals else "",
        ("Props: %s." % props.rstrip(".")) if props else "",
        ("Clearly visible: %s." % cues.rstrip(".")) if cues else "",
        "For the first %s seconds: %s" % (tw, setup.rstrip(".") + "."),
        ("At %g seconds a bright white camera flash goes off once." % max(0.0, twist_at - flash)) if flash else "",
        "At exactly %s seconds everything suddenly flips: %s, continuing until the end." % (tw, chaos.rstrip(".")),
        "Only natural ambient sound from the scene, no music, no speech.",
        "Photorealistic, funny viral video, no text.") if x)

    builtin = MEME["negative_prompt"]
    if allow_cuts:
        builtin = builtin.replace(", cuts, scene change", "")
    if n_animals:
        builtin += ", third animal"
    negative = builtin + (", " + extra_neg if extra_neg else "")
    shot = {"model": model, "prompt": prompt, "seconds": seconds, "aspect_ratio": MEME["aspect_ratio"],
            "resolution": res, "negative_prompt": negative, "generate_audio": True}
    frames = {}
    for k in ("first_frame", "last_frame"):
        v = fields.get(k)
        if v in (None, ""):
            continue
        if not isinstance(v, str) or len(v) > FRAME_MAX or not FRAME_OK.match(v.strip()):
            raise TemplateError(400, "%s 要是圖片網址或 asset://（%d 字內；不收 data URI，先用 asset_upload）" % (k, FRAME_MAX))
        frames[k] = v.strip()
    if frames:
        mc = _model_caps()
        try:
            extra, notes = mc.frames_payload(model, frames.get("first_frame"), frames.get("last_frame"))
        except mc.CapsError as e:
            raise TemplateError(400, str(e))
        shot.update(extra)
    warnings = []
    if frames and notes:
        warnings.append("%s 的首尾幀還沒實測過（%s）：照工作台預設的寫法送，結果不保證" % (model, "、".join(notes)))
    if not chars:
        names = sorted({w for w in _NAME.findall(setup + " " + chaos) if w not in _COMMON})
        if names:
            warnings.append("提示詞裡有名字（%s），但 characters 是空的：模型不知道這些名字長什麼樣子，"
                            "請在 characters 寫外觀描述（例如 Max: a fluffy cream-colored toy poodle）" % "、".join(names))
    captions = []
    c1, c2 = _text(fields, "cap_setup", 40), _text(fields, "cap_twist", 40)
    if c1:
        captions.append(dict({"text": c1, "start": 0, "end": "twist", "pos": "top", "style": style},
                             **({"size": cap_size} if cap_size else {})))
    if c2:
        captions.append(dict({"text": c2, "start": "twist", "end": "end", "pos": "top", "style": style},
                             **({"size": cap_size} if cap_size else {})))
    effects = []
    if flash:
        effects.append({"type": "white_flash", "start": "twist-%g" % flash, "end": "twist-%g" % max(0.0, flash - 0.15)})
    post = {"captions": captions, "effects": effects, "twist": {"auto": True, "hint": twist_at},
            "format": {"aspect": "9:16", "resolution": "1080p", "fps": 30, "fit": "crop"}}
    return {"template": "meme", "fields": dict(fields), "shot": shot, "post": post,
            "prompt": prompt, "seconds": seconds, "negative_prompt": negative, "builtin_negative": builtin,
            "warnings": warnings}

def clone_plan(src, name=None, fields=None, shots=None):
    new_name = (name or "").strip() or ((src.get("name") or "作品")[:56] + " 副本")
    if src.get("template"):
        if shots is not None:
            raise TemplateError(400, "範本作品的分鏡由範本組：要改請給 fields")
        merged = dict(src.get("fields") or {})
        for k, v in (fields or {}).items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        tp = build(src["template"], merged)
        return new_name, [{"prompt": tp["prompt"], "seconds": tp["seconds"]}], \
            {"template": tp["template"], "fields": tp["fields"]}, tp["warnings"]
    if fields:
        raise TemplateError(400, "這部作品不是用範本建的，沒有 fields 可以改：要改請給 shots")
    return new_name, shots if shots is not None else src.get("shots") or [], None, []

def build(template, fields):
    t = TEMPLATES.get(template)
    if not t:
        raise TemplateError(400, "沒有這個範本：%s（有 %s）" % (template, "、".join(TEMPLATES)))
    return meme(fields)

