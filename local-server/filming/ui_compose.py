from . import ui_actions, ui_schema

VERSION = 1

QUESTIONS = [
    {"id": "genre", "ask": "你主要做哪一種片？", "type": "one", "default": "short",
     "options": {"meme": "迷因短片（範本＋字卡＋白閃，一鍵匯出）", "short": "短劇（15–30 秒、幾個鏡頭）",
                 "long": "1 分鐘長片（多段接續）", "ad": "廣告", "other": "其他"}},
    {"id": "steps", "ask": "你常用哪些步驟？（可以複選）", "type": "many",
     "default": ["script", "storyboard", "generate", "select", "post"],
     "options": {"script": "腳本", "storyboard": "分鏡", "cast": "角色", "generate": "生成", "select": "挑版本",
                 "post": "後製", "sound": "聲音", "publish": "上架"}},
    {"id": "budget", "ask": "要不要在介面上看預算、一起確認花費？", "type": "bool", "default": True,
     "options": {True: "要（顯示核准卡與一起確認）", False: "不要（花錢時照舊會跳確認單）"}},
    {"id": "previs", "ask": "要不要用 3D 預演（擺位、運鏡）？", "type": "bool", "default": False,
     "options": {True: "要", False: "不要"}},
    {"id": "agent", "ask": "要不要 Agent 協作面板（讓 Agent 幫你跑流程）？", "type": "bool", "default": True,
     "options": {True: "要", False: "不要"}},
    {"id": "agent_run", "ask": "要不要讓 Agent 幫你從頭拍到尾（你看進度、回答它的提問）？", "type": "bool", "default": False,
     "options": {True: "要（放上 Agent 拍片進度與 Agent 協作）", False: "不要（自己一步一步拍）"}},
    {"id": "publish", "ask": "做好之後通常上架到哪裡？", "type": "one", "default": "none",
     "options": {"youtube": "YouTube", "pitch": "投稿包（短劇平台）", "none": "先不用"}},
    {"id": "density", "ask": "介面要多精簡？", "type": "one", "default": "standard",
     "options": {"simple": "精簡（只留最常用的）", "standard": "標準", "pro": "專業（全部都放出來）"}},
    {"id": "lang", "ask": "介面語言？", "type": "one", "default": "zh-TW",
     "options": {"zh-TW": "繁體中文", "en": "English"}},
]
QMAP = {q["id"]: q for q in QUESTIONS}

TEXT = {
    "zh-TW": {"meme": "迷因", "plan": "規劃", "previs": "預演", "make": "生成", "pick": "挑版本與定稿", "post": "後製與匯出",
              "publish": "上架", "assist": "協作", "agentrun": "Agent 拍片",
              "agentrun_hint": "Agent 從頭拍到尾：這裡看進度、回答它的提問；花錢照舊走核准卡",
              "meme_hint": "挑範本 → 改字卡 → 匯出", "plan_hint": "先寫腳本、拆分鏡（照下面的順序）",
              "step_script": "1. 腳本", "step_board": "2. 分鏡", "step_cast": "角色", "previs_hint": "站位與運鏡用 3D 鎖住再生成",
              "make_hint": "按開拍照舊先報價、再確認"},
    "en": {"meme": "Meme", "plan": "Plan", "previs": "Previs", "make": "Generate", "pick": "Takes", "post": "Post & export",
           "publish": "Publish", "assist": "Assist", "agentrun": "Agent shoot",
           "agentrun_hint": "The Agent shoots end to end: watch progress and answer its questions here; spending still goes through approval cards",
           "meme_hint": "Pick a template → edit captions → export", "plan_hint": "Script first, then storyboard",
           "step_script": "1. Script", "step_board": "2. Storyboard", "step_cast": "Cast",
           "previs_hint": "Lock blocking and camera in 3D", "make_hint": "Shooting still quotes first, then asks you"},
}
LABEL_EN = {"export.open": "Export", "blocks.move": "Reorder blocks", "meme.load": "Meme captions", "sound.open": "Sound",
            "cast.turn": "Cast turnaround", "puppet.open": "Puppet previs", "previs.open": "3D previs", "takes.open": "Takes",
            "gate.pick": "Pick final", "approve.batch": "Confirm together", "youtube.open": "Upload to YouTube",
            "pitch.open": "Pitch package", "agent.open": "Agent", "mode.set": "Switch mode", "generate.open": "Shoot",
            "agent.panel": "Agent run"}
ADVANCED = ("blocks.move", "puppet.open", "cast.turn", "previs.open")

class ComposeError(ValueError):
    pass

def questions():
    out = []
    for q in QUESTIONS:
        opts = [{"value": k, "label": v} for k, v in q["options"].items()]
        out.append({"id": q["id"], "ask": q["ask"], "type": q["type"], "default": q["default"], "options": opts})
    return out

def _answer(q, v):
    if v is None:
        return q["default"], "%s 沒回答，用預設：%s" % (q["id"], _show(q, q["default"]))
    if q["type"] == "bool":
        if isinstance(v, bool):
            return v, None
        if isinstance(v, str) and v.strip().lower() in ("true", "yes", "要", "是"):
            return True, None
        if isinstance(v, str) and v.strip().lower() in ("false", "no", "不要", "否"):
            return False, None
    elif q["type"] == "one":
        if isinstance(v, str) and v in q["options"]:
            return v, None
    elif q["type"] == "many":
        if isinstance(v, list) and v:
            ok = [x for x in v if isinstance(x, str) and x in q["options"]]
            bad = [x for x in v if x not in ok]
            if ok:
                ok = list(dict.fromkeys(ok))
                return ok, ("%s 有不認得的選項 %s，略過" % (q["id"], bad) if bad else None)
    return q["default"], "%s 的答案 %r 不認得，用預設：%s" % (q["id"], v, _show(q, q["default"]))

def _show(q, v):
    if isinstance(v, list):
        return "、".join(q["options"].get(x, str(x)) for x in v)
    return q["options"].get(v, str(v))

def _label(act, lang):
    return LABEL_EN[act] if lang == "en" else ui_actions.ACTIONS[act]["label"]

def compose(answers=None, name=None):
    if answers is not None and not isinstance(answers, dict):
        raise ComposeError("answers 要是物件 {題號: 答案}")
    answers = answers or {}
    extra = set(answers) - set(QMAP)
    notes = ["不認得的題目 %s，略過" % "、".join(sorted(map(str, extra)))] if extra else []
    a = {}
    for q in QUESTIONS:
        v, n = _answer(q, answers.get(q["id"]))
        a[q["id"]] = v
        if n:
            notes.append(n)
    lang = a["lang"]
    T = TEXT[lang]
    simple, pro = a["density"] == "simple", a["density"] == "pro"
    steps = set(a["steps"])
    hide = list(ADVANCED) if simple else []
    if not a["previs"] and not pro:
        hide = list(dict.fromkeys(hide + ["previs.open", "puppet.open"]))

    def button(act):
        return {"type": "button", "label": _label(act, lang), "action": act}

    def step(label, act=None):
        return {"type": "step", "label": label, **({"action": act} if act else {})}
    panels = []
    if a["agent_run"]:
        panels.append({"id": "agentrun", "title": T["agentrun"], "items": [
            {"type": "text", "text": T["agentrun_hint"]}, button("agent.panel"), button("agent.open")]})
    if a["genre"] == "meme":
        panels.append({"id": "meme", "title": T["meme"], "items": [
            {"type": "text", "text": T["meme_hint"]}, step(_label("meme.load", lang), "meme.load"), button("export.open")]})
    else:
        plan = []
        if "script" in steps:
            plan.append(step(T["step_script"]))
        if "storyboard" in steps:
            plan.append(step(T["step_board"]))
        if "cast" in steps or pro:
            plan.append(step(T["step_cast"]) if "cast.turn" in hide else button("cast.turn"))
        if plan:
            panels.append({"id": "plan", "title": T["plan"], "items": [{"type": "text", "text": T["plan_hint"]}] + plan})
        if (a["previs"] or pro) and "previs.open" not in hide:
            pv = [{"type": "text", "text": T["previs_hint"]}, button("previs.open")]
            if "puppet.open" not in hide:
                pv.append(button("puppet.open"))
            panels.append({"id": "previs", "title": T["previs"], "items": pv})
        if "generate" in steps or pro:
            panels.append({"id": "make", "title": T["make"], "items": [{"type": "text", "text": T["make_hint"]},
                                                                       button("generate.open")]})
        if "select" in steps or a["genre"] == "long" or pro:
            panels.append({"id": "pick", "title": T["pick"], "items": [button("takes.open"), button("gate.pick")]})
        post = []
        if "blocks.move" not in hide and ("post" in steps or pro):
            post.append(button("blocks.move"))
        if "sound" in steps or a["genre"] in ("long", "ad") or pro:
            post.append(button("sound.open"))
        post.append(button("export.open"))
        panels.append({"id": "post", "title": T["post"], "items": post})
    if a["publish"] != "none" or "publish" in steps:
        pub = [button("youtube.open")] if a["publish"] in ("youtube", "none") else []
        if a["publish"] == "pitch" or pro:
            pub.append(button("pitch.open"))
        if pub:
            panels.append({"id": "publish", "title": T["publish"], "items": pub})
    side = []
    if a["budget"]:
        side.append(button("approve.batch"))
    if a["agent"] and not a["agent_run"]:
        side.append(button("agent.open"))
    if simple or pro:
        side.append(button("mode.set"))
    if side:
        panels.append({"id": "assist", "title": T["assist"], "items": side})
    desc = {"version": ui_schema.VERSION, "name": (name or _default_name(a))[:ui_schema.MAX_LABEL], "panels": panels}
    try:
        desc, summary = ui_schema.validate(desc)
    except ui_schema.DescError as e:
        raise ComposeError("組出來的描述檔過不了驗證：%s" % e) from None
    prefs = ui_schema.validate_prefs({"version": VERSION, "density": a["density"], "lang": lang, "show_budget": a["budget"],
                                      "previs": a["previs"], "agent_panel": a["agent"] or a["agent_run"], "hide": hide,
                                      "confirm_actions": summary["confirm_actions"]})
    return {"desc": desc, "prefs": prefs, "answers": a, "notes": notes}

def _default_name(a):
    g = QMAP["genre"]["options"][a["genre"]].split("（")[0]
    return ("%s workspace" % a["genre"]) if a["lang"] == "en" else "%s工作台" % g
