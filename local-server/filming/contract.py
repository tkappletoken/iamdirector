
GEN_STAGES = ("script", "storyboard", "cast", "generate", "select", "qc", "sound", "publish", "template")
POST_STAGES = ("analyze", "source", "timeline", "overlay", "append", "text", "audio", "output")
UI_STAGES = ("panel",)
LINES = {"gen": GEN_STAGES, "post": POST_STAGES, "ui": UI_STAGES}
PREVIEWS = ("quote", "dry_run", "none")
REDO_SCOPES = ("shot", "line", "step")
METHODS = ("GET", "POST")
KEYS = ("id", "line", "stage", "label", "spends", "preview", "qc", "redo", "api", "mcp", "cli",
        "local_agent", "front_only")

class ContractError(ValueError):
    pass

def _need(cond, bid, msg):
    if not cond:
        raise ContractError("%s：%s" % (bid or "?", msg))

def check(spec):
    _need(isinstance(spec, dict), None, "宣告要是 dict")
    bid = spec.get("id")
    _need(isinstance(bid, str) and bid and bid == bid.lower() and len(bid) <= 40
          and all(c.isalnum() or c in "_-" for c in bid), bid, "id 要是小寫英數、_ 或 -")
    extra = set(spec) - set(KEYS)
    _need(not extra, bid, "不認得的欄位 %s" % "、".join(sorted(extra)))
    line = spec.get("line")
    _need(line in LINES, bid, "line 只能是 %s" % "／".join(LINES))
    _need(spec.get("stage") in LINES[line], bid, "stage 不在 %s 線的階段表裡" % line)
    _need(isinstance(spec.get("label"), str) and spec["label"].strip(), bid, "要有 label")
    for k in ("spends", "qc", "local_agent"):
        _need(isinstance(spec.get(k, False), bool), bid, "%s 要是 true／false" % k)
    prev = spec.get("preview", "none")
    _need(prev in PREVIEWS, bid, "preview 只能是 %s" % "／".join(PREVIEWS))
    redo = tuple(spec.get("redo") or ())
    _need(all(r in REDO_SCOPES for r in redo), bid, "redo 只能是 %s" % "／".join(REDO_SCOPES))
    api = tuple(tuple(a) for a in spec.get("api") or ())
    _need(all(len(a) == 2 and a[0] in METHODS and isinstance(a[1], str) and a[1].startswith("/")
              for a in api), bid, "api 要是 (GET|POST, /路徑)")
    for k in ("mcp", "cli", "front_only"):
        v = spec.get(k) or ()
        _need(isinstance(v, (list, tuple)) and all(isinstance(x, str) and x.strip() for x in v),
              bid, "%s 要是字串清單" % k)
    out = dict(spec, spends=bool(spec.get("spends")), preview=prev, qc=bool(spec.get("qc")), redo=redo, api=api,
               mcp=tuple(spec.get("mcp") or ()), cli=tuple(spec.get("cli") or ()),
               local_agent=bool(spec.get("local_agent")), front_only=tuple(spec.get("front_only") or ()))
    return out

def grade(spec):
    s = check(spec)
    gaps = []
    if not s["api"]:
        gaps.append("no_api")
    if not s["mcp"]:
        gaps.append("no_mcp")
    if not s["cli"]:
        gaps.append("no_cli")
    if not s["local_agent"]:
        gaps.append("no_local_agent")
    if s["front_only"]:
        gaps.append("front_only")
    if s["spends"] and s["preview"] == "none":
        gaps.append("no_preview")
    a_gaps = list(gaps)
    if not s["qc"]:
        gaps.append("no_qc")
    if not s["redo"]:
        gaps.append("no_redo")
    b_gaps = [g for g in gaps if g in ("no_qc", "no_redo")]
    have_any = bool(s["api"] or s["mcp"] or s["cli"])
    a = "ok" if not a_gaps else ("part" if have_any else "no")
    b = "ok" if not b_gaps else ("part" if len(b_gaps) == 1 else "no")
    return {"A": a, "B": b, "gaps": gaps}
