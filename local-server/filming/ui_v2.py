import math
import re

from . import ui_actions

SECTIONS = ("layout", "theme", "flow")

DOCKS = ("float", "left", "right", "bottom")
SIZES = ("s", "m", "l")
SPLITS = {"single": 1, "two": 2, "three": 3}
LAYOUT_KEYS = {"panels", "main"}
PANEL_LAYOUT_KEYS = {"dock", "size", "collapsible", "collapsed"}
MAIN_KEYS = {"split", "slots"}
SLOT_KEYS = {"component", "size"}
MAIN_FIRST = "stage"

COLOR_KEYS = ("surface", "text", "accent", "good", "bad")
THEME_KEYS = {"base", "colors", "font_scale", "spacing"}
FONT_SCALES = {"s": 0.9, "m": 1.0, "l": 1.15, "xl": 1.3}
SPACINGS = ("compact", "standard", "comfortable")
BASES = {
    "dark": {"surface": "#14171c", "text": "#e4e7eb", "accent": "#e8a33d", "good": "#79be6b", "bad": "#e0705c"},
    "light": {"surface": "#f6f4ef", "text": "#1b1f26", "accent": "#a15c00", "good": "#2e7d32", "bad": "#b3261e"},
}
COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
DERIVE = {"ink": ("surface", "#000000", {"dark": 0.3, "light": 0.05}), "riser": ("surface", "text", 0.06),
          "pencil": ("text", "surface", 0.3), "faint": ("text", "surface", 0.42)}
CONTRAST = (("text/surface", "text", "surface", 4.5), ("text/ink", "text", "ink", 4.5), ("text/riser", "text", "riser", 4.5),
            ("pencil/surface", "pencil", "surface", 4.5), ("faint/surface", "faint", "surface", 3.0),
            ("accent/surface", "accent", "surface", 3.0), ("on_accent/accent", "on_accent", "accent", 4.5),
            ("good/surface", "good", "surface", 3.0), ("bad/surface", "bad", "surface", 3.0))

STEPS = ("story", "cast", "board", "generate", "sound", "edit", "publish")
REQUIRED_STEPS = ("board", "generate", "edit")
ORDER = (("story", "board"), ("cast", "generate"), ("board", "generate"), ("generate", "sound"), ("generate", "edit"),
         ("sound", "edit"), ("edit", "publish"))
STEP_KEYS = {"step", "label", "merge_with", "defaults"}
MAX_STEP_LABEL = 20
ASPECTS = ("9:16", "16:9", "1:1")
TEMPLATES = ("meme", "drama", "talk", "product", "unbox", "story", "news")
RESOLUTIONS = ("480p", "720p", "1080p")
DEFAULT_KEYS = {"story": ("aspect",), "board": ("template", "aspect"), "generate": ("model", "resolution"),
                "edit": ("blocks",)}
MODEL_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")
BLOCK_ID = re.compile(r"^[a-z0-9_]{1,32}$")
MAX_BLOCKS = 20

class V2Error(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

def _fail(code, message):
    raise V2Error(code, message)

def _obj(v, keys, section, where):
    if not isinstance(v, dict):
        _fail(section + ":not_object", "%s 要是物件" % where)
    extra = set(v) - set(keys)
    if extra:
        _fail(section + ":unknown_key", "%s 不認得的欄位 %s" % (where, "、".join(sorted(extra))))

def _enum(v, allowed, code, where):
    if not isinstance(v, str) or v not in allowed:
        _fail(code, "%s 只能是 %s" % (where, "／".join(allowed)))
    return v

def _bool(v, code, where):
    if not isinstance(v, bool):
        _fail(code, "%s 要是 true／false" % where)
    return v

def _layout(v, panel_ids):
    _obj(v, LAYOUT_KEYS, "layout", "layout")
    out = {}
    if "panels" in v:
        ps = v["panels"]
        if not isinstance(ps, dict):
            _fail("layout:not_object", "layout.panels 要是物件 {面板 id: 設定}")
        out["panels"] = {}
        for pid, cfg in ps.items():
            w = "layout.panels.%s" % pid
            if pid not in panel_ids:
                _fail("layout:bad_panel", "%s：描述檔裡沒有這個面板" % w)
            _obj(cfg, PANEL_LAYOUT_KEYS, "layout", w)
            c = {}
            if "dock" in cfg:
                c["dock"] = _enum(cfg["dock"], DOCKS, "layout:bad_dock", w + ".dock")
            if "size" in cfg:
                c["size"] = _enum(cfg["size"], SIZES, "layout:bad_size", w + ".size")
            for k in ("collapsible", "collapsed"):
                if k in cfg:
                    c[k] = _bool(cfg[k], "layout:bad_bool", "%s.%s" % (w, k))
            out["panels"][pid] = c
    if "main" in v:
        m = v["main"]
        _obj(m, MAIN_KEYS, "layout", "layout.main")
        split = _enum(m.get("split"), tuple(SPLITS), "layout:bad_split", "layout.main.split")
        slots = m.get("slots")
        if not isinstance(slots, list) or len(slots) != SPLITS[split]:
            _fail("layout:bad_slots", "layout.main.slots 要剛好 %d 個（split＝%s）" % (SPLITS[split], split))
        seen, clean = set(), []
        for i, s in enumerate(slots):
            w = "layout.main.slots[%d]" % i
            _obj(s, SLOT_KEYS, "layout", w)
            comp = s.get("component")
            c = ui_actions.COMPONENTS.get(comp) if isinstance(comp, str) else None
            if c is None or c["mount"] != "inline":
                _fail("layout:bad_component", "%s.component 要是元件表裡能放進版面的（inline）：%r" % (w, comp))
            if comp in seen:
                _fail("layout:dup_component", "%s.component 重複：%s" % (w, comp))
            if i == 0 and comp != MAIN_FIRST:
                _fail("layout:first_slot", "layout.main 的第一欄要是 %s（主線目前那一步）" % MAIN_FIRST)
            seen.add(comp)
            one = {"component": comp}
            if "size" in s:
                one["size"] = _enum(s["size"], SIZES, "layout:bad_size", w + ".size")
            clean.append(one)
        out["main"] = {"split": split, "slots": clean}
    return out

def _hex6(h):
    h = h.lower()
    return "#" + "".join(c * 2 for c in h[1:]) if len(h) == 4 else h

def _rgb(h):
    h = _hex6(h)
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))

def _round(x, nd=0):
    f = 10 ** nd
    return math.floor(x * f + 0.5) / f

def mix(a, b, t):
    ra, rb = _rgb(a), _rgb(b)
    return "#" + "".join("%02x" % int(_round(x * (1 - t) + y * t)) for x, y in zip(ra, rb))

def luminance(h):
    def lin(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def ratio(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return _round((hi + 0.05) / (lo + 0.05), 2)

def palette(theme):
    base = (theme or {}).get("base") or "dark"
    p = dict(BASES[base])
    p.update({k: _hex6(v) for k, v in ((theme or {}).get("colors") or {}).items()})
    for k, (a, b, t) in DERIVE.items():
        p[k] = mix(p[a], p.get(b, b), t[base] if isinstance(t, dict) else t)
    p["on_accent"] = "#000000" if ratio("#000000", p["accent"]) >= ratio("#ffffff", p["accent"]) else "#ffffff"
    return p

def contrast_report(theme):
    p = palette(theme)
    return [{"pair": n, "ratio": ratio(p[f], p[b]), "min": m, "ok": ratio(p[f], p[b]) >= m} for n, f, b, m in CONTRAST]

def _theme(v):
    _obj(v, THEME_KEYS, "theme", "theme")
    out = {}
    if "base" in v:
        out["base"] = _enum(v["base"], tuple(BASES), "theme:bad_base", "theme.base")
    if "colors" in v:
        cs = v["colors"]
        _obj(cs, COLOR_KEYS, "theme", "theme.colors")
        out["colors"] = {}
        for k in COLOR_KEYS:
            if k in cs:
                if not isinstance(cs[k], str) or not COLOR.match(cs[k]):
                    _fail("theme:bad_color", "theme.colors.%s 只收 #RGB 或 #RRGGBB" % k)
                out["colors"][k] = _hex6(cs[k])
    if "font_scale" in v:
        out["font_scale"] = _enum(v["font_scale"], tuple(FONT_SCALES), "theme:bad_font_scale", "theme.font_scale")
    if "spacing" in v:
        out["spacing"] = _enum(v["spacing"], SPACINGS, "theme:bad_spacing", "theme.spacing")
    bad = [r for r in contrast_report(out) if not r["ok"]]
    if bad:
        _fail("theme:contrast", "theme 的對比不夠，字會看不清楚：" + "；".join(
            "%s %.2f < %.1f" % (r["pair"], r["ratio"], r["min"]) for r in bad))
    return out

def _defaults(step, d, where):
    allowed = DEFAULT_KEYS.get(step, ())
    _obj(d, allowed, "flow", where)
    out = {}
    for k in allowed:
        if k not in d:
            continue
        v, w = d[k], "%s.%s" % (where, k)
        if k == "aspect":
            out[k] = _enum(v, ASPECTS, "flow:bad_default", w)
        elif k == "template":
            out[k] = _enum(v, TEMPLATES, "flow:bad_default", w)
        elif k == "resolution":
            out[k] = _enum(v, RESOLUTIONS, "flow:bad_default", w)
        elif k == "model":
            if not isinstance(v, str) or not MODEL_REF.match(v):
                _fail("flow:bad_default", "%s 要是模型 ref（例如 provider/name）" % w)
            out[k] = v
        elif k == "blocks":
            if not isinstance(v, list) or len(v) > MAX_BLOCKS or len(set(map(str, v))) != len(v) or \
                    not all(isinstance(x, str) and BLOCK_ID.match(x) for x in v):
                _fail("flow:bad_default", "%s 要是最多 %d 個、不重複的積木 id" % (w, MAX_BLOCKS))
            out[k] = list(v)
    return out

def _flow(v):
    _obj(v, {"steps"}, "flow", "flow")
    steps = v.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= len(STEPS):
        _fail("flow:bad_steps", "flow.steps 要是 1–%d 步的陣列" % len(STEPS))
    out, at = [], {}
    for i, s in enumerate(steps):
        w = "flow.steps[%d]" % i
        _obj(s, STEP_KEYS, "flow", w)
        sid = _enum(s.get("step"), STEPS, "flow:bad_step", w + ".step")
        if sid in at:
            _fail("flow:dup_step", "%s：%s 出現兩次" % (w, sid))
        at[sid] = i
        one = {"step": sid}
        if "label" in s:
            lab = s["label"]
            if not isinstance(lab, str) or not lab.strip() or len(lab) > MAX_STEP_LABEL or \
                    any(ord(c) < 32 for c in lab):
                _fail("flow:bad_label", "%s.label 要是 1–%d 字的文字" % (w, MAX_STEP_LABEL))
            one["label"] = lab
        if "merge_with" in s:
            prev = out[-1] if out else None
            if prev is None or s["merge_with"] != prev["step"] or "merge_with" in prev:
                _fail("flow:bad_merge", "%s.merge_with 只能是前一步，而且一頁最多合兩步" % w)
            one["merge_with"] = prev["step"]
        if "defaults" in s:
            one["defaults"] = _defaults(sid, s["defaults"], w + ".defaults")
        out.append(one)
    miss = [x for x in REQUIRED_STEPS if x not in at]
    if miss:
        _fail("flow:required", "flow 少了不能跳過的步驟：%s（少了就交不出片）" % "、".join(miss))
    for a, b in ORDER:
        if a in at and b in at and at[a] > at[b]:
            _fail("flow:order", "flow 的順序：%s 要在 %s 前面" % (a, b))
    return {"steps": out}

def validate_section(name, value, panel_ids=()):
    if name == "layout":
        return _layout(value, set(panel_ids))
    if name == "theme":
        return _theme(value)
    if name == "flow":
        return _flow(value)
    raise ValueError("沒有這個區塊：%s" % name)

def json_schema():
    from . import ui_schema as S
    text = lambda n, empty=False: {"type": "string", "minLength": 0 if empty else 1, "maxLength": n}
    acts = sorted(ui_actions.ACTIONS)
    item = {"oneOf": [
        {"type": "object", "additionalProperties": False, "required": ["type", "text"],
         "properties": {"type": {"const": "text"}, "text": text(S.MAX_TEXT)}},
        {"type": "object", "additionalProperties": False, "required": ["type", "label"],
         "properties": {"type": {"const": "step"}, "label": text(S.MAX_LABEL), "action": {"enum": acts}}},
        {"type": "object", "additionalProperties": False, "required": ["type", "label", "action"],
         "properties": {"type": {"const": "button"}, "label": text(S.MAX_LABEL), "action": {"enum": acts}}}]}
    panel = {"type": "object", "additionalProperties": False, "required": ["id", "title", "items"],
             "properties": {"id": {"type": "string", "minLength": 1, "maxLength": S.MAX_ID, "pattern": r"^[\p{L}\p{N}_-]+$"},
                            "title": text(S.MAX_LABEL),
                            "items": {"type": "array", "minItems": 1, "maxItems": S.MAX_ITEMS, "items": item}}}
    inline = sorted(k for k, v in ui_actions.COMPONENTS.items() if v["mount"] == "inline")
    layout = {"type": "object", "additionalProperties": False, "properties": {
        "panels": {"type": "object", "additionalProperties": {
            "type": "object", "additionalProperties": False, "properties": {
                "dock": {"enum": list(DOCKS)}, "size": {"enum": list(SIZES)},
                "collapsible": {"type": "boolean"}, "collapsed": {"type": "boolean"}}}},
        "main": {"type": "object", "additionalProperties": False, "required": ["split", "slots"], "properties": {
            "split": {"enum": list(SPLITS)},
            "slots": {"type": "array", "minItems": 1, "maxItems": 3, "items": {
                "type": "object", "additionalProperties": False, "required": ["component"],
                "properties": {"component": {"enum": inline}, "size": {"enum": list(SIZES)}}}}}}}}
    color = {"type": "string", "pattern": COLOR.pattern}
    theme = {"type": "object", "additionalProperties": False, "properties": {
        "base": {"enum": list(BASES)},
        "colors": {"type": "object", "additionalProperties": False, "properties": {k: color for k in COLOR_KEYS}},
        "font_scale": {"enum": list(FONT_SCALES)}, "spacing": {"enum": list(SPACINGS)}}}
    dflt = {"type": "object", "additionalProperties": False, "properties": {
        "aspect": {"enum": list(ASPECTS)}, "template": {"enum": list(TEMPLATES)}, "resolution": {"enum": list(RESOLUTIONS)},
        "model": {"type": "string", "pattern": MODEL_REF.pattern},
        "blocks": {"type": "array", "maxItems": MAX_BLOCKS, "uniqueItems": True,
                   "items": {"type": "string", "pattern": BLOCK_ID.pattern}}}}
    flow = {"type": "object", "additionalProperties": False, "required": ["steps"], "properties": {
        "steps": {"type": "array", "minItems": 1, "maxItems": len(STEPS), "items": {
            "type": "object", "additionalProperties": False, "required": ["step"], "properties": {
                "step": {"enum": list(STEPS)}, "label": text(MAX_STEP_LABEL), "merge_with": {"enum": list(STEPS)},
                "defaults": dflt}}}}}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "介面描述檔（ui-desc）v1／v2",
        "description": "規格見 docs/ui-v2.md。對比度、流程順序、每一步能預設哪些鍵、版面引用的面板 id 由驗證器檢查（Schema 表達不了）。",
        "type": "object", "required": ["version", "panels"],
        "oneOf": [
            {"additionalProperties": False, "properties": {"version": {"const": 1}, "name": text(S.MAX_LABEL, True),
                                                           "panels": {"type": "array", "maxItems": S.MAX_PANELS,
                                                                      "items": panel}}},
            {"additionalProperties": False, "properties": {"version": {"const": 2}, "name": text(S.MAX_LABEL, True),
                                                           "panels": {"type": "array", "maxItems": S.MAX_PANELS,
                                                                      "items": panel},
                                                           "layout": layout, "theme": theme, "flow": flow}}]}
