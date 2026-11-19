import json
import re

SOURCES = ("shadow", "qc", "assistant")
STEPS = ("script", "storyboard", "cast", "generate", "select", "qc", "sound", "post", "publish", "template", "ui", "other")
STEP_WORDS = {"腳本": "script", "分鏡": "storyboard", "角色一致": "cast", "角色": "cast", "生成": "generate",
              "選片": "select", "品管": "qc", "驗片": "qc", "配音": "sound", "配樂": "sound", "聲音": "sound",
              "後製": "post", "匯出": "post", "上架": "publish", "範本": "template", "介面": "ui"}
FREQ = {"每支": 3, "偶爾": 2, "一次": 1}
IMPACT = {"要人手補": 3, "多花點數": 3, "品質": 2}
SUMMARY_MAX = 120
_SECRET = re.compile(r"(sk-[A-Za-z0-9]{8,}|iadl?_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY|"
                     r"(?i:api[_-]?key|token|secret|password)\s*[:=]\s*\S{6,})")
_URL = re.compile(r"https?://\S+")

class InboxError(ValueError):
    pass

def _summary(text):
    t = _URL.sub("〔網址已移除〕", str(text or "")).strip()
    return re.sub(r"\s+", " ", t)[:SUMMARY_MAX]

def item(source, step, code, summary="", freq="", impact=""):
    if source not in SOURCES:
        raise InboxError("source 只能是 %s" % "／".join(SOURCES))
    if step not in STEPS:
        step = "other"
    for v in (code, summary, freq, impact):
        if _SECRET.search(str(v or "")):
            raise InboxError("內容看起來有金鑰或密碼，整則拒收")
    code = str(code or "").strip()[:64]
    if not code:
        raise InboxError("要有 code")
    return {"source": source, "step": step, "code": code, "summary": _summary(summary),
            "freq": freq if freq in FREQ else "", "impact": impact if impact in IMPACT else "", "count": 1}

def from_postblocks_lines(lines):
    out = []
    for ln in lines:
        i = ln.find("[postblocks] ")
        if i < 0:
            continue
        try:
            ev = json.loads(ln[i + len("[postblocks] "):])
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        event, reason = ev.get("event"), ev.get("reason")
        if event == "fallback":
            out.append(item("shadow", "post", "fallback:%s" % reason, "積木退回舊路（%s）" % ev.get("engine")))
        elif event == "shadow" and reason not in (None, "same"):
            out.append(item("shadow", "post", "shadow_diff:%s" % reason, "shadow 比對不一致"))
    return out

def from_qc_report(rep, step="qc"):
    if not rep or rep.get("ok"):
        return None
    return item("qc", step, "%s:%s" % (rep.get("block"), "+".join(rep.get("defects") or ["fail"])),
                rep.get("note", ""))

_FIELD = re.compile(r"^\s*(卡點｜步驟|卡點\|步驟|步驟|現象|它的腳本怎麼做|頻率|影響)\s*[:：]\s*(.*)$")

def from_assistant_msg(text):
    f = {}
    for ln in str(text or "").splitlines():
        m = _FIELD.match(ln)
        if m:
            f[m.group(1).replace("卡點｜", "").replace("卡點|", "")] = m.group(2).strip()
    if not f.get("步驟") or not f.get("現象"):
        raise InboxError("卡點要有「步驟」與「現象」兩欄")
    step = next((v for k, v in STEP_WORDS.items() if k in f["步驟"]), "other")
    how = f.get("它的腳本怎麼做", "")
    code = "missing_step" if how else "stuck"
    summ = f["現象"] + (("｜它的做法：" + how) if how else "")
    return item("assistant", step, "%s:%s" % (code, step), summ, f.get("頻率", ""), f.get("影響", ""))

def triage(items):
    groups = {}
    for it in items:
        k = (it["step"], it["code"])
        g = groups.setdefault(k, {"step": it["step"], "code": it["code"], "count": 0, "sources": set(),
                                  "examples": [], "weight": 1})
        g["count"] += it.get("count", 1)
        g["sources"].add(it["source"])
        if it["summary"] and it["summary"] not in g["examples"] and len(g["examples"]) < 3:
            g["examples"].append(it["summary"])
        g["weight"] = max(g["weight"], FREQ.get(it.get("freq"), 1) * IMPACT.get(it.get("impact"), 1))
    out = []
    for g in groups.values():
        g["sources"] = sorted(g["sources"])
        g["priority"] = g["count"] * g["weight"]
        g["todo"] = "〔%s〕%s ×%d：%s" % (g["step"], g["code"], g["count"], (g["examples"] or ["（無摘要）"])[0])
        out.append(g)
    return sorted(out, key=lambda g: (-g["priority"], g["step"], g["code"]))

def append(path, items):
    with open(path, "a", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")

def load(path):
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if ln:
                    out.append(json.loads(ln))
    except FileNotFoundError:
        pass
    return out
