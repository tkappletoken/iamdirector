import copy

from . import ui_actions, ui_schema

MAX_OPS = 50
OPS = {
    "add_panel": {"op", "id", "title", "items", "at"},
    "remove_panel": {"op", "panel"},
    "add_item": {"op", "panel", "item", "at"},
    "remove_item": {"op", "panel", "index", "action"},
    "move": {"op", "panel", "item", "to", "to_panel"},
    "rename": {"op", "name", "panel", "title", "item", "label"},
    "set_pref": {"op", "key", "value"},
}
PREF_KEYS = ("density", "lang", "show_budget", "previs", "agent_panel", "hide")

class EditError(ValueError):
    def __init__(self, index, detail):
        super().__init__("第 %d 個 op：%s" % (index, detail))
        self.index, self.detail = index, detail

def _panel(desc, pid, i):
    for n, p in enumerate(desc["panels"]):
        if p["id"] == pid:
            return n, p
    raise EditError(i, "沒有面板 %r（有 %s）" % (pid, "、".join(p["id"] for p in desc["panels"]) or "沒有面板"))

def _item(p, ref, i):
    if isinstance(ref, bool):
        raise EditError(i, "item 要是索引或動作名稱")
    if isinstance(ref, int):
        if not 0 <= ref < len(p["items"]):
            raise EditError(i, "面板 %s 沒有第 %d 項（共 %d 項）" % (p["id"], ref, len(p["items"])))
        return ref
    for n, it in enumerate(p["items"]):
        if it.get("action") == ref:
            return n
    raise EditError(i, "面板 %s 裡沒有動作 %r" % (p["id"], ref))

def _at(v, n, i):
    if v is None:
        return n
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= n:
        raise EditError(i, "at／to 要是 0–%d 的整數" % n)
    return v

def _one(desc, prefs, op, i):
    if not isinstance(op, dict) or op.get("op") not in OPS:
        raise EditError(i, "op 只能是 %s" % "／".join(OPS))
    kind = op["op"]
    extra = set(op) - OPS[kind]
    if extra:
        raise EditError(i, "%s 不認得的欄位 %s" % (kind, "、".join(sorted(extra))))
    panels = desc["panels"]
    if kind == "add_panel":
        if any(p["id"] == op.get("id") for p in panels):
            raise EditError(i, "已經有面板 %r" % op.get("id"))
        panels.insert(_at(op.get("at"), len(panels), i), {"id": op.get("id"), "title": op.get("title"), "items": op.get("items")})
    elif kind == "remove_panel":
        n, _p = _panel(desc, op.get("panel"), i)
        panels.pop(n)
    elif kind == "add_item":
        _n, p = _panel(desc, op.get("panel"), i)
        p["items"].insert(_at(op.get("at"), len(p["items"]), i), op.get("item"))
    elif kind == "remove_item":
        _n, p = _panel(desc, op.get("panel"), i)
        ref = op.get("index") if "index" in op else op.get("action")
        p["items"].pop(_item(p, ref, i))
    elif kind == "move":
        n, p = _panel(desc, op.get("panel"), i)
        if "item" not in op:
            panels.insert(_at(op.get("to"), len(panels) - 1, i), panels.pop(n))
        else:
            it = p["items"].pop(_item(p, op["item"], i))
            dest = _panel(desc, op["to_panel"], i)[1] if op.get("to_panel") is not None else p
            dest["items"].insert(_at(op.get("to"), len(dest["items"]), i), it)
    elif kind == "rename":
        if "name" in op:
            desc["name"] = op["name"]
        else:
            _n, p = _panel(desc, op.get("panel"), i)
            if "item" in op:
                it = p["items"][_item(p, op["item"], i)]
                if it["type"] == "text":
                    raise EditError(i, "說明文字沒有 label；要改字請 remove_item 再 add_item")
                it["label"] = op.get("label")
            else:
                p["title"] = op.get("title")
    elif kind == "set_pref":
        if op.get("key") not in PREF_KEYS:
            raise EditError(i, "set_pref 的 key 只能是 %s" % "／".join(PREF_KEYS))
        prefs = dict(prefs or ui_schema.PREFS_DEFAULT)
        prefs[op["key"]] = op.get("value")
    return desc, prefs

def apply_ops(desc, prefs, ops):
    if not isinstance(ops, list) or not 0 < len(ops) <= MAX_OPS:
        raise EditError(-1, "ops 要是 1–%d 個 op 的陣列" % MAX_OPS)
    cur = copy.deepcopy(desc) if desc else {"version": ui_schema.VERSION, "name": "", "panels": []}
    pf = copy.deepcopy(prefs) if prefs else None
    for i, op in enumerate(ops):
        cur, pf = _one(cur, pf, copy.deepcopy(op), i)
        try:
            if not cur["panels"]:
                raise ui_schema.DescError("至少要留一個面板（要回預設請用 reset）")
            cur = ui_schema.validate(cur)[0]
            pf = ui_schema.validate_prefs(pf)
        except ui_schema.DescError as e:
            raise EditError(i, str(e)) from None
    if pf is not None:
        pf["confirm_actions"] = ui_schema.validate(cur)[1]["confirm_actions"]
    return cur, pf

def preview_text(desc, prefs=None):
    if not desc or not desc.get("panels"):
        return "（預設框架：沒有自訂面板）"
    lines = ["《%s》" % (desc.get("name") or "自訂介面")]
    hide = set((prefs or {}).get("hide") or [])
    for p in desc["panels"]:
        parts = []
        for it in p["items"]:
            if it["type"] == "text":
                parts.append("「%s」" % it["text"])
                continue
            a = it.get("action")
            tag = "（會先跳確認）" if a and ui_actions.ACTIONS[a]["spend"] == "confirm" else ""
            tag += "（被 prefs 藏起來）" if a in hide else ""
            parts.append(it["label"] + tag)
        lines.append("■ %s：%s" % (p["title"], " → ".join(parts)))
    if prefs:
        lines.append("偏好：密度 %s、語言 %s、顯示花費 %s、藏起來 %s" % (
            prefs["density"], prefs["lang"], "是" if prefs["show_budget"] else "否",
            "、".join(prefs["hide"]) or "（沒有）"))
    return "\n".join(lines)

def actions_catalog():
    return {"actions": [{"action": k, "label": v["label"], "spend": v["spend"], "feature": v["feature"]}
                        for k, v in ui_actions.ACTIONS.items()],
            "item_types": {"text": "說明文字（text）", "step": "步驟標籤（label，可以不帶 action）", "button": "按鈕（label＋action）"},
            "limits": {"panels": ui_schema.MAX_PANELS, "items": ui_schema.MAX_ITEMS, "label": ui_schema.MAX_LABEL,
                       "text": ui_schema.MAX_TEXT, "ops_per_edit": MAX_OPS},
            "prefs": {"density": list(ui_schema.PREFS_ENUM["density"]), "lang": list(ui_schema.PREFS_ENUM["lang"]),
                      "show_budget": "true／false", "previs": "true／false", "agent_panel": "true／false",
                      "hide": "動作名稱的陣列"},
            "ops": sorted(OPS)}
