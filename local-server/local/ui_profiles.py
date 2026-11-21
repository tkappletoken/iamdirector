import json
import os
import re
import time

from filming import ui_compose, ui_edit, ui_schema

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
MAX_PROFILES = 20
HUMAN_ONLY = ("delete",)
STORE_KEY = ui_schema.STORE_KEY
PREFS_KEY = ui_schema.PREFS_KEY

def _dir(data_dir):
    d = os.path.join(data_dir, "ui")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d

def _write(path, obj):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)

def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None

def _names(data_dir):
    return sorted(f[:-5] for f in os.listdir(_dir(data_dir)) if f.endswith(".json") and NAME_RE.match(f[:-5]))

def active(data_dir):
    a = _read(os.path.join(_dir(data_dir), "_active.json"))
    return a if isinstance(a, dict) and a.get("name") else None

def _rec_out(rec):
    return dict(rec, preview=ui_edit.preview_text(rec.get("desc"), rec.get("prefs")))

def _stamp(rec, name, who):
    return dict(rec, name=name, saved_by=who if who in ("agent", "human") else "agent",
                saved_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))

def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")

def onboarding_status(data_dir, enabled):
    act = active(data_dir)
    done = _read(os.path.join(_dir(data_dir), "_onboarding.json")) or {}
    needed = bool(enabled and not act and not done.get("done"))
    return {"enabled": bool(enabled), "needed": needed,
            "active": act["name"] if act else None, "done": done.get("how"), "profiles": len(_names(data_dir)),
            "hint": _onboarding_hint(enabled, needed, act, done)}

def _onboarding_hint(enabled, needed, act, done):
    if not enabled:
        return "這台的介面描述檔沒有開（使用者在 App 設定頁打開）；現在照預設框架。"
    if act:
        return ("已經在用「%s」：要改就 ui_get 看現在這份、ui_edit 細修再 ui_apply；改壞了用 ui_undo 還原，"
                "或 ui_reset 回預設框架。" % act["name"])
    if not needed:
        return ("使用者按了「先用預設框架」，現在照預設框架；他之後想要自己的介面，再用 ui_compose 組、ui_apply 套用。"
                if done.get("done") else "現在照預設框架。")
    return ("使用者還沒建自己的介面：先 ui_actions_list 看積木，問他想怎麼拍、常用哪些步驟，"
            "ui_compose 組起點、ui_edit 細修、ui_apply 套用；他想跳過就到畫面上按「先用預設框架」")

def _set_state(data_dir, put, desc, prefs, act_name, who):
    put(STORE_KEY, desc)
    put(PREFS_KEY, prefs)
    ap = os.path.join(_dir(data_dir), "_active.json")
    if act_name:
        _write(ap, {"name": act_name, "by": who, "at": _now()})
    elif os.path.exists(ap):
        os.remove(ap)

def _snapshot(data_dir, get):
    act = active(data_dir)
    snap = {"desc": get(STORE_KEY), "prefs": get(PREFS_KEY), "active": act["name"] if act else None, "at": _now()}
    _write(os.path.join(_dir(data_dir), "_prev.json"), snap)

def _applied_note():
    return "已套用（描述檔面板開著時 5 秒內重畫）。要回原本的樣子，說「回預設」或到設定按回預設；要回上一版，說「還原」。"

def handle(method, body, *, who, data_dir, put, get=None, query=None, onboarding=False):
    get = get or (lambda k: None)
    if method == "GET":
        if (query or {}).get("onboarding"):
            return 200, onboarding_status(data_dir, onboarding)
        if (query or {}).get("questions"):
            return 200, {"version": ui_compose.VERSION, "questions": ui_compose.questions()}
        if (query or {}).get("catalog"):
            return 200, dict(ui_edit.actions_catalog(), questions=ui_compose.questions())
        name = (query or {}).get("name")
        if name:
            if not NAME_RE.match(str(name)):
                return 400, {"error": "name 只能是 1–32 個英數、_、-（不能用底線開頭）"}
            rec = _read(os.path.join(_dir(data_dir), name + ".json"))
            return (200, _rec_out(rec)) if rec else (404, {"error": "沒有這一份介面"})
        act = active(data_dir)
        items = []
        for n in _names(data_dir):
            rec = _read(os.path.join(_dir(data_dir), n + ".json")) or {}
            items.append({"name": n, "title": ((rec.get("desc") or {}).get("name") or ""), "saved_by": rec.get("saved_by"),
                          "saved_at": rec.get("saved_at"), "panels": len((rec.get("desc") or {}).get("panels") or []),
                          "active": bool(act and act["name"] == n)})
        return 200, {"items": items, "active": act["name"] if act else None, "max": MAX_PROFILES,
                     "can_undo": os.path.exists(os.path.join(_dir(data_dir), "_prev.json"))}
    if not isinstance(body, dict):
        return 400, {"error": "要是物件"}
    op = body.get("op")
    if op == "preview":
        try:
            return 200, dict(ui_compose.compose(body.get("answers"), body.get("title")), dry_run=True)
        except ui_compose.ComposeError as e:
            return 400, {"error": str(e)}
    if op in HUMAN_ONLY and who != "human":
        return 403, {"error": "刪除介面要你本人在 App 裡操作（刪了就找不回來）"}
    if op == "skip_onboarding":
        _write(os.path.join(_dir(data_dir), "_onboarding.json"), {"done": True, "how": "skipped", "by": who, "at": _now()})
        return 200, {"ok": True, "onboarding": onboarding_status(data_dir, onboarding)}
    if op == "reset":
        _snapshot(data_dir, get)
        _set_state(data_dir, put, None, None, None, who)
        return 200, {"ok": True, "active": None, "note": "已回預設框架；要回剛才那一版，說「還原」"}
    if op == "undo":
        prev = _read(os.path.join(_dir(data_dir), "_prev.json"))
        if not prev:
            return 409, {"error": "沒有上一版可以還原"}
        _snapshot(data_dir, get)
        _set_state(data_dir, put, prev.get("desc"), prev.get("prefs"), prev.get("active"), who)
        return 200, {"ok": True, "active": prev.get("active"), "restored_from": prev.get("at"),
                     "note": "已還原到上一版；再還原一次就回到剛才那一版"}
    name = body.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        return 400, {"error": "name 只能是 1–32 個英數、_、-（不能用底線開頭）"}
    path = os.path.join(_dir(data_dir), "%s.json" % name)
    if op == "save":
        extra = set(body) - {"op", "name", "answers", "desc", "prefs", "title"}
        if extra:
            return 400, {"error": "不認得的欄位 %s" % "、".join(sorted(extra))}
        if ("answers" in body) == ("desc" in body):
            return 400, {"error": "answers（先對話再組）與 desc（直接給描述檔）要給其中一個"}
        if not os.path.exists(path) and len(_names(data_dir)) >= MAX_PROFILES:
            return 409, {"error": "最多存 %d 份，先刪掉一份" % MAX_PROFILES}
        try:
            if "answers" in body:
                r = ui_compose.compose(body["answers"], body.get("title"))
            else:
                desc, _summary = ui_schema.validate(body["desc"])
                if desc is None:
                    return 400, {"error": "這是預設框架（空的描述檔）：要回預設請用 reset"}
                r = {"desc": desc, "prefs": ui_schema.validate_prefs(body.get("prefs")), "answers": None, "notes": []}
        except (ui_compose.ComposeError, ui_schema.DescError) as e:
            return 400, {"error": "描述檔不合法：%s" % e}
        rec = _stamp(r, name, who)
        _write(path, rec)
        return 200, {"ok": True, "name": name, "saved_by": rec["saved_by"], "notes": r["notes"],
                     "panels": [p["id"] for p in r["desc"]["panels"]], "desc": rec["desc"], "prefs": rec["prefs"],
                     "preview": ui_edit.preview_text(rec["desc"], rec["prefs"])}
    if op == "edit":
        if set(body) - {"op", "name", "ops"}:
            return 400, {"error": "edit 只收 name、ops"}
        rec = _read(path)
        if not rec:
            return 404, {"error": "沒有這一份介面（先 save 一份，例如用 answers 組出起點）"}
        try:
            desc, prefs = ui_edit.apply_ops(rec.get("desc"), rec.get("prefs"), body.get("ops"))
        except ui_edit.EditError as e:
            return 400, {"error": str(e), "op_index": e.index, "detail": e.detail, "unchanged": True}
        was = (rec.get("desc") or {}).get("version")
        rec = _stamp(dict(rec, desc=desc, prefs=prefs), name, who)
        _write(path, rec)
        out = {"ok": True, "name": name, "saved_by": rec["saved_by"], "desc": desc, "prefs": prefs,
               "preview": ui_edit.preview_text(desc, prefs)}
        if was != ui_schema.VERSION_V2 and (desc or {}).get("version") == ui_schema.VERSION_V2:
            out["upgraded"] = "v1→v2"
        return 200, out
    if op == "copy":
        src = body.get("from")
        if not isinstance(src, str) or not NAME_RE.match(src):
            return 400, {"error": "from 只能是 1–32 個英數、_、-"}
        rec = _read(os.path.join(_dir(data_dir), src + ".json"))
        if not rec:
            return 404, {"error": "沒有 %s 這一份" % src}
        if not os.path.exists(path) and len(_names(data_dir)) >= MAX_PROFILES:
            return 409, {"error": "最多存 %d 份，先刪掉一份" % MAX_PROFILES}
        rec = _stamp(rec, name, who)
        _write(path, rec)
        return 200, {"ok": True, "name": name, "saved_by": rec["saved_by"], "preview": ui_edit.preview_text(rec["desc"], rec["prefs"])}
    if op == "activate":
        rec = _read(path)
        if not rec:
            return 404, {"error": "沒有這一份介面"}
        try:
            desc, _summary = ui_schema.validate(rec.get("desc"))
            prefs = ui_schema.validate_prefs(rec.get("prefs"))
        except ui_schema.DescError as e:
            return 400, {"error": "這一份描述檔壞了：%s" % e}
        _snapshot(data_dir, get)
        _set_state(data_dir, put, desc, prefs, name, who)
        _write(os.path.join(_dir(data_dir), "_onboarding.json"), {"done": True, "how": "applied", "by": who, "at": _now()})
        return 200, {"ok": True, "active": name, "applied": True, "by": who, "note": _applied_note()}
    if op == "delete":
        act = active(data_dir)
        if act and act["name"] == name:
            return 409, {"error": "這一份正在用：先回預設（reset）或切到別份再刪"}
        try:
            os.remove(path)
        except FileNotFoundError:
            return 404, {"error": "沒有這一份介面"}
        return 200, {"ok": True}
    return 400, {"error": "op 只能是 preview／save／edit／copy／activate／reset／undo／delete／skip_onboarding"}
