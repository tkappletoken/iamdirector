from . import ui_actions

STORE_KEY = "ui-desc"
VERSION = 1
MAX_PANELS = 12
MAX_ITEMS = 40
MAX_TEXT = 200
MAX_LABEL = 40
MAX_ID = 32
PANEL_KEYS = {"id", "title", "items"}
ITEM_KEYS = {"text": {"type", "text"}, "step": {"type", "label", "action"}, "button": {"type", "label", "action"}}
TOP_KEYS = {"version", "name", "panels"}

class DescError(ValueError):
    pass

def _str(v, where, limit, empty_ok=False):
    if not isinstance(v, str) or (not empty_ok and not v.strip()) or len(v) > limit:
        raise DescError("%s 要是 1–%d 字的文字" % (where, limit))
    if any(ord(c) < 32 and c not in "\n\t" for c in v):
        raise DescError("%s 不准有控制字元" % where)
    return v

def _keys(d, allowed, where):
    if not isinstance(d, dict):
        raise DescError("%s 要是物件" % where)
    extra = set(d) - allowed
    if extra:
        raise DescError("%s 不認得的欄位 %s" % (where, "、".join(sorted(extra))))

def is_default(desc):
    return desc is None or desc == {} or (isinstance(desc, dict) and not desc.get("panels"))

def store_value(value):
    clean, _summary = validate(value)
    return clean

def strip_local(desc):
    if not desc:
        return desc
    panels = []
    for p in desc["panels"]:
        items = [it for it in p["items"] if it.get("action") not in ui_actions.LOCAL_ONLY]
        if any(it["type"] != "text" for it in items):
            panels.append(dict(p, items=items))
    return dict(desc, panels=panels) if panels else None

def client_actions(local=False):
    return {k: {"call": v["call"], "spend": v["spend"], "label": v["label"]} for k, v in ui_actions.ACTIONS.items()
            if local or not v.get("local")}

def validate(desc):
    if is_default(desc):
        return None, {"actions": [], "confirm_actions": []}
    _keys(desc, TOP_KEYS, "描述檔")
    if desc.get("version") != VERSION:
        raise DescError("version 要是 %d" % VERSION)
    name = _str(desc.get("name", ""), "name", MAX_LABEL, empty_ok=True)
    panels = desc.get("panels")
    if not isinstance(panels, list) or len(panels) > MAX_PANELS:
        raise DescError("panels 要是最多 %d 個的陣列" % MAX_PANELS)
    out, ids, used = [], set(), []
    for i, p in enumerate(panels):
        w = "panels[%d]" % i
        _keys(p, PANEL_KEYS, w)
        pid = _str(p.get("id"), w + ".id", MAX_ID)
        if not all(c.isalnum() or c in "_-" for c in pid) or pid in ids:
            raise DescError("%s.id 要是英數、_、-，而且不重複" % w)
        ids.add(pid)
        items = p.get("items")
        if not isinstance(items, list) or not items or len(items) > MAX_ITEMS:
            raise DescError("%s.items 要是 1–%d 個的陣列" % (w, MAX_ITEMS))
        clean = []
        for j, it in enumerate(items):
            wi = "%s.items[%d]" % (w, j)
            t = it.get("type") if isinstance(it, dict) else None
            if t not in ITEM_KEYS:
                raise DescError("%s.type 只能是 %s" % (wi, "／".join(ITEM_KEYS)))
            _keys(it, ITEM_KEYS[t], wi)
            if t == "text":
                clean.append({"type": t, "text": _str(it.get("text"), wi + ".text", MAX_TEXT)})
                continue
            act = it.get("action")
            if t == "step" and act is None:
                clean.append({"type": t, "label": _str(it.get("label"), wi + ".label", MAX_LABEL)})
                continue
            if not isinstance(act, str) or ui_actions.get(act) is None:
                raise DescError("%s.action 不在動作表裡：%r" % (wi, act))
            used.append(act)
            clean.append({"type": t, "label": _str(it.get("label"), wi + ".label", MAX_LABEL), "action": act})
        out.append({"id": pid, "title": _str(p.get("title"), w + ".title", MAX_LABEL), "items": clean})
    acts = list(dict.fromkeys(used))
    return ({"version": VERSION, "name": name, "panels": out},
            {"actions": acts, "confirm_actions": [a for a in acts if ui_actions.ACTIONS[a]["spend"] == "confirm"]})

PREFS_KEY = "ui-prefs"
PREFS_DEFAULT = {"version": 1, "density": "standard", "lang": "zh-TW", "show_budget": True, "previs": False,
                 "agent_panel": True, "hide": [], "confirm_actions": []}
PREFS_ENUM = {"density": ("simple", "standard", "pro"), "lang": ("zh-TW", "en")}
PREFS_BOOL = ("show_budget", "previs", "agent_panel")
PREFS_LISTS = ("hide", "confirm_actions")

def validate_prefs(prefs):
    if prefs is None or prefs == {}:
        return None
    _keys(prefs, set(PREFS_DEFAULT), "prefs")
    out = dict(PREFS_DEFAULT, hide=[], confirm_actions=[])
    v = prefs.get("version", 1)
    if isinstance(v, bool) or v != 1:
        raise DescError("prefs.version 要是 1")
    for k, allowed in PREFS_ENUM.items():
        if k in prefs:
            if prefs[k] not in allowed:
                raise DescError("prefs.%s 只能是 %s" % (k, "／".join(allowed)))
            out[k] = prefs[k]
    for k in PREFS_BOOL:
        if k in prefs:
            if not isinstance(prefs[k], bool):
                raise DescError("prefs.%s 要是 true／false" % k)
            out[k] = prefs[k]
    for k in PREFS_LISTS:
        if k in prefs:
            v = prefs[k]
            if not isinstance(v, list) or len(v) > len(ui_actions.ACTIONS) or \
                    any(not isinstance(x, str) or ui_actions.get(x) is None for x in v):
                raise DescError("prefs.%s 要是動作表裡的動作名稱" % k)
            out[k] = list(dict.fromkeys(v))
    return out

