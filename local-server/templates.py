import re

MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,79}$")
STYLES = ("meme", "memebox")
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
        "characters": "角色外觀描述（選填，300 字以內；例如「Dudu: a fluffy cream-colored toy poodle; Nini: an orange tabby cat」）",
        "resolution": "解析度（720p 或 1080p，預設 720p；這個模型照解析度計價）",
        "extra_negative": "追加的 negative（選填，200 字以內；接在範本內建的那一份後面，內建的刪不掉）",
        "cap_setup": "前段字卡（選填，40 字以內）",
        "cap_twist": "反轉之後的字卡（選填，40 字以內）",
        "flash_before": "反轉前幾秒閃一下白光（選填，0.3–3 秒；例如拍照的閃光）",
        "style": "字卡樣式：meme（白字黑描邊，預設）或 memebox（黑字白底）",
        "model": "模型（選填，預設 gputw/minimax-h3）",
    },
}
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
    flash = _num(fields, "flash_before", 0.3, 3)
    style = fields.get("style") or "meme"
    if style not in STYLES:
        raise TemplateError(400, "style 只能是 %s" % "／".join(STYLES))
    model = fields.get("model") or MEME["model"]
    if not isinstance(model, str) or not MODEL.match(model):
        raise TemplateError(400, "model 不合法")

    tw = ("%g" % twist_at)
    prompt = " ".join(x for x in (
        "Static locked-off camera, one continuous %d-second shot, full-body wide framing, "
        "no camera movement, no cuts." % seconds,
        ("Characters: %s." % chars.rstrip(".")) if chars else "",
        "For the first %s seconds: %s" % (tw, setup.rstrip(".") + "."),
        ("At %g seconds a bright white camera flash goes off once." % max(0.0, twist_at - flash)) if flash else "",
        "At exactly %s seconds everything suddenly flips: %s, continuing until the end." % (tw, chaos.rstrip(".")),
        "Only natural ambient sound from the scene, no music, no speech.",
        "Photorealistic, funny viral video, no text.") if x)

    negative = MEME["negative_prompt"] + (", " + extra_neg if extra_neg else "")
    shot = {"model": model, "prompt": prompt, "seconds": seconds, "aspect_ratio": MEME["aspect_ratio"],
            "resolution": res, "negative_prompt": negative, "generate_audio": True}
    warnings = []
    if not chars:
        names = sorted({w for w in _NAME.findall(setup + " " + chaos) if w not in _COMMON})
        if names:
            warnings.append("提示詞裡有名字（%s），但 characters 是空的：模型不知道這些名字長什麼樣子，"
                            "請在 characters 寫外觀描述（例如 Dudu: a fluffy cream-colored toy poodle）" % "、".join(names))
    captions = []
    c1, c2 = _text(fields, "cap_setup", 40), _text(fields, "cap_twist", 40)
    if c1:
        captions.append({"text": c1, "start": 0, "end": "twist", "pos": "top", "style": style})
    if c2:
        captions.append({"text": c2, "start": "twist", "end": "end", "pos": "top", "style": style})
    effects = []
    if flash:
        effects.append({"type": "white_flash", "start": "twist-%g" % flash, "end": "twist-%g" % max(0.0, flash - 0.15)})
    post = {"captions": captions, "effects": effects, "twist": {"auto": True, "hint": twist_at},
            "format": {"aspect": "9:16", "resolution": "1080p", "fps": 30, "fit": "crop"}}
    return {"template": "meme", "fields": dict(fields), "shot": shot, "post": post,
            "prompt": prompt, "seconds": seconds, "negative_prompt": negative, "builtin_negative": MEME["negative_prompt"],
            "warnings": warnings}

def build(template, fields):
    t = TEMPLATES.get(template)
    if not t:
        raise TemplateError(400, "沒有這個範本：%s（有 %s）" % (template, "、".join(TEMPLATES)))
    return meme(fields)

