import copy

from . import ui_actions, ui_schema, ui_v2

MAX_OPS = 50
OPS = {
    "add_panel": {"op", "id", "title", "items", "at"},
    "remove_panel": {"op", "panel"},
    "add_item": {"op", "panel", "item", "at"},
    "remove_item": {"op", "panel", "index", "action"},
    "move": {"op", "panel", "item", "to", "to_panel"},
    "rename": {"op", "name", "panel", "title", "item", "label"},
    "set_pref": {"op", "key", "value"},
    "set_layout": {"op", "panel"} | ui_v2.PANEL_LAYOUT_KEYS,
    "set_main": {"op"} | ui_v2.MAIN_KEYS,
}
LAYOUT_OPS = ("set_layout", "set_main")
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
        n, p = _panel(desc, op.get("panel"), i)
        panels.pop(n)
        lay = desc.get("layout")
        if lay and p["id"] in (lay.get("panels") or {}):
            del lay["panels"][p["id"]]
            if not lay["panels"]:
                del lay["panels"]
            if not lay:
                del desc["layout"]
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
    elif kind == "set_layout":
        _panel(desc, op.get("panel"), i)
        cfg = {k: op[k] for k in ui_v2.PANEL_LAYOUT_KEYS if k in op}
        if not cfg:
            raise EditError(i, "set_layout 至少要給 %s 其中一個" % "／".join(sorted(ui_v2.PANEL_LAYOUT_KEYS)))
        desc["version"] = ui_schema.VERSION_V2
        desc.setdefault("layout", {}).setdefault("panels", {}).setdefault(op["panel"], {}).update(cfg)
    elif kind == "set_main":
        desc["version"] = ui_schema.VERSION_V2
        desc.setdefault("layout", {})["main"] = {k: op.get(k) for k in ("split", "slots")}
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

DOCK_LABEL = {"float": "浮動", "left": "左側", "right": "右側", "bottom": "底部"}
SIZE_LABEL = {"s": "小", "m": "中", "l": "大"}
SPLIT_LABEL = {"single": "單欄", "two": "兩欄", "three": "三欄"}
BASE_LABEL = {"dark": "暗色", "light": "亮色"}
STEP_LABEL = {"story": "故事", "cast": "角色", "board": "分鏡", "generate": "生成", "sound": "聲音", "edit": "剪輯字幕",
              "publish": "上架"}

def _v2_lines(desc):
    if not isinstance(desc, dict) or desc.get("version") != ui_schema.VERSION_V2:
        return []
    out = []
    lay = desc.get("layout") or {}
    if lay.get("panels"):
        parts, rest = [], False
        for p in desc.get("panels") or []:
            cfg = lay["panels"].get(p["id"])
            if not cfg:
                rest = True
                continue
            bits = [DOCK_LABEL[cfg.get("dock", "float")]] + ([SIZE_LABEL[cfg["size"]]] if "size" in cfg else [])
            bits += (["不可收合"] if cfg.get("collapsible") is False else []) + (["一開始收著"] if cfg.get("collapsed") else [])
            parts.append("%s → %s" % (p["title"], "・".join(bits)))
        out.append("版面：" + "；".join(parts + (["其他面板：浮動"] if rest else [])))
    if lay.get("main"):
        m = lay["main"]
        slots = ["%s%s" % (ui_actions.COMPONENTS[s["component"]]["label"], "（%s）" % SIZE_LABEL[s["size"]] if "size" in s else "")
                 for s in m["slots"]]
        out.append("主區：%s｜%s" % (SPLIT_LABEL[m["split"]], "｜".join(slots)))
    th = desc.get("theme")
    if th is not None:
        bits = [BASE_LABEL[th.get("base") or "dark"]]
        if "font_scale" in th:
            bits.append("字級 %s" % th["font_scale"])
        if "spacing" in th:
            bits.append("間距 %s" % th["spacing"])
        if th.get("colors"):
            bits.append("改了 %s" % "／".join(k for k in ui_v2.COLOR_KEYS if k in th["colors"]))
        low = min(ui_v2.contrast_report(th), key=lambda r: r["ratio"] / r["min"])
        out.append("主題：%s；離門檻最近的對比 %.1f（%s，門檻 %g）" % ("、".join(bits), low["ratio"], low["pair"], low["min"]))
    fl = desc.get("flow")
    if fl and fl.get("steps"):
        groups, used, dflt = [], set(), []
        for s in fl["steps"]:
            name = s.get("label") or STEP_LABEL[s["step"]]
            used.add(s["step"])
            if s.get("merge_with") and groups:
                groups[-1] += "＋" + name
            else:
                groups.append(name)
            if s.get("defaults"):
                kv = ["%s=%s" % (k, "、".join(map(str, v)) if isinstance(v, list) else v) for k, v in s["defaults"].items()]
                dflt.append("%s %s" % (name, "、".join(kv)))
        line = "流程：" + " → ".join(groups)
        skip = [STEP_LABEL[x] for x in ui_v2.STEPS if x not in used]
        line += ("；跳過：%s" % "、".join(skip)) if skip else ""
        line += ("；預設：%s" % "；".join(dflt)) if dflt else ""
        out.append(line)
    return out

def preview_text(desc, prefs=None):
    v2 = _v2_lines(desc)
    if not desc or (not desc.get("panels") and not v2):
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
    lines += v2
    if prefs:
        lines.append("偏好：密度 %s、語言 %s、顯示花費 %s、藏起來 %s" % (
            prefs["density"], prefs["lang"], "是" if prefs["show_budget"] else "否",
            "、".join(prefs["hide"]) or "（沒有）"))
    return "\n".join(lines)

def actions_catalog():
    return {"actions": [dict({"action": k, "label": v["label"], "spend": v["spend"], "feature": v["feature"]},
                             **({"context": ui_actions.ARG_KINDS[v["args"]]} if v.get("args") else {}))
                        for k, v in ui_actions.ACTIONS.items()],
            "item_types": {"text": "說明文字（text）", "step": "步驟標籤（label，可以不帶 action）", "button": "按鈕（label＋action）"},
            "limits": {"panels": ui_schema.MAX_PANELS, "items": ui_schema.MAX_ITEMS, "label": ui_schema.MAX_LABEL,
                       "text": ui_schema.MAX_TEXT, "ops_per_edit": MAX_OPS},
            "prefs": {"density": list(ui_schema.PREFS_ENUM["density"]), "lang": list(ui_schema.PREFS_ENUM["lang"]),
                      "show_budget": "true／false", "previs": "true／false", "agent_panel": "true／false",
                      "hide": "動作名稱的陣列"},
            "ops": sorted(OPS),
            "layout": {"dock": list(ui_v2.DOCKS), "size": list(ui_v2.SIZES), "split": list(ui_v2.SPLITS),
                       "components": sorted(k for k, v in ui_actions.COMPONENTS.items() if v["mount"] == "inline"),
                       "first_slot": ui_v2.MAIN_FIRST,
                       "note": "set_layout／set_main 會把 v1 的描述檔升成 v2；網頁版存檔時只留面板（版面只在桌面版）"}}
