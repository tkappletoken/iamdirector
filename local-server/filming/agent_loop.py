import copy
import math

from . import dir_controls, long_plan, qc_report, shots as shots_mod

VERSION = 1
PHASES = ("budget", "execute", "deliver", "done", "stopped")
DECISIONS = ("approve", "raise", "accept_best", "stop", "resume")
GATES = ("loop", "cards")
HUMAN_ONLY = ("approve", "raise")
BLOCKED = ("card_pending", "repriced", "over_limit")
REQUEST_MAX = 500
SEG_TARGET = 15
LOG_MAX = 500
SEAM_REDO_MAX = 1

class LoopError(ValueError):
    pass

def _num(v, where, allow_none=True):
    if v is None and allow_none:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or not math.isfinite(v):
        raise LoopError("%s 要是 ≥ 0 的數字" % where)
    return float(v)

def clean_budget(b):
    b = b or {}
    if not isinstance(b, dict) or set(b) - {"auto", "per_job", "per_run"}:
        raise LoopError("budget 只能有 auto、per_job、per_run")
    auto = b.get("auto", False)
    if not isinstance(auto, bool):
        raise LoopError("budget.auto 要是 true／false")
    return {"auto": auto, "per_job": _num(b.get("per_job"), "budget.per_job"),
            "per_run": _num(b.get("per_run"), "budget.per_run")}

def preauthorized(b):
    return bool(b["auto"]) and b["per_job"] is not None and b["per_run"] is not None

def draft(request, target_seconds=60):
    n = max(1, math.ceil(target_seconds / SEG_TARGET))
    sec = round(target_seconds / n, 3)
    if not long_plan.SEG_MIN <= sec <= long_plan.SEG_MAX or n > long_plan.MAX_SEGMENTS:
        raise LoopError("目標長度要能切成 %d 段以內、每段 %d–%d 秒" % (long_plan.MAX_SEGMENTS, long_plan.SEG_MIN,
                                                                long_plan.SEG_MAX))
    return {"version": 1, "segments": [{"prompt": "%s（第 %d／%d 段）" % (request, i + 1, n), "seconds": sec}
                                       for i in range(n)]}

LONG_SEGS = (6, 10)
LONG_SEG_TARGET = 8
LONG_BEATS = ("開場", "鋪陳", "發展", "轉折", "高潮", "收尾")

def draft_long(request, target_seconds=60):
    n = min(LONG_SEGS[1], max(LONG_SEGS[0], math.ceil(target_seconds / LONG_SEG_TARGET)))
    total = int(target_seconds)
    secs = [total // n + (1 if i < total % n else 0) for i in range(n)]
    if not all(long_plan.SEG_MIN <= x <= long_plan.SEG_MAX for x in secs):
        raise LoopError("長片退路要切成 %d–%d 段、每段 %d–%d 秒：%s 秒切不出來（請 Agent 自己寫腳本）"
                        % (LONG_SEGS[0], LONG_SEGS[1], long_plan.SEG_MIN, long_plan.SEG_MAX, target_seconds))

    def beat(i):
        return LONG_BEATS[-1] if i == n - 1 else LONG_BEATS[min(len(LONG_BEATS) - 2, i * (len(LONG_BEATS) - 1) // n)]
    return {"version": 1, "segments": [{"prompt": "%s（第 %d／%d 段・%s）" % (request, i + 1, n, beat(i)), "seconds": secs[i]}
                                       for i in range(n)]}

def _controls(st, storyboard, cast):
    try:
        dc = dir_controls.from_storyboard_all(storyboard, cast)
    except dir_controls.DirControlsError as e:
        raise LoopError("導演控制：%s" % e) from None
    keys = {s["key"] for s in st["shots"]}
    extra = [x["key"] for x in dc["shots"] if x["key"] not in keys]
    if extra:
        raise LoopError("導演控制的鏡號 %s 不在規劃裡（規劃的鏡號：%s）" % ("、".join(extra), "、".join(sorted(keys))))
    by = {x["key"]: x for x in dc["shots"]}
    for s in st["shots"]:
        x = by.get(s["key"])
        s["controls"] = None if x is None else {"desc": x["desc"], "dur": x["dur"], "ask": x["ask"], "fill": x["fill"]}
        if x and x["fill"]:
            _log(st, "controls_fill", shot_key=s["key"], codes=x["fill"])
    st["must_ask"] = dc["must_ask"]
    st["controls_gaps"] = {c: v for c, v in dc["gaps"].items() if c in dc["must_ask"]}
    _log(st, "controls", must_ask=dc["must_ask"])

def start(request, desc=None, caps=None, *, budget=None, has_cast_refs=False, price_per_second=None, max_retakes=1,
          target_seconds=None, gate="loop", storyboard=None, cast=None, blockout=None, long_film=False,
          seam_redo=False):
    if not isinstance(request, str) or not request.strip() or len(request) > REQUEST_MAX:
        raise LoopError("需求要是 1–%d 字的文字" % REQUEST_MAX)
    request = request.strip()
    if gate not in GATES:
        raise LoopError("gate 要是 %s" % "、".join(GATES))
    bud = clean_budget(budget)
    warnings = []
    if desc is None and long_film:
        desc = draft_long(request, target_seconds or 60)
        warnings += ["script_draft", "script_draft_long"]
    elif desc is None:
        desc = draft(request, target_seconds or 60)
        warnings.append("script_draft")
    try:
        p = long_plan.plan(desc, caps or {}, has_cast_refs=has_cast_refs, price_per_second=price_per_second,
                           max_retakes=max_retakes, target_seconds=target_seconds)
    except long_plan.PlanError as e:
        raise LoopError("規劃失敗：%s" % e) from None
    seam_before = {s["before"] for s in p["seams"]}
    shots = []
    for seg in p["segments"]:
        cost = None if price_per_second is None else round(seg["seconds"] * price_per_second, 2)
        checks = ["qc"] + (["seam_check"] if seg["key"] in seam_before else []) + (["lock_qc"] if "blockout" in seg else [])
        shots.append({"key": seg["key"], "seconds": seg["seconds"], "prompt": seg["prompt"], "refs": seg["refs"],
                      "cost": cost, "checks": checks,
                      "first_frame": seg["first_frame"], "status": "pending", "redos": 0, "reason": None,
                      "takes": [], "picked": None})
    pw = p["totals"]["worst_cost"]
    if pw is not None and bud["per_run"] is not None and pw > bud["per_run"]:
        warnings.append("retakes_may_exceed_budget")
    st = {"version": VERSION, "request": request, "phase": "budget", "gate": gate, "plan": p, "max_retakes": max_retakes,
          "budget": bud, "spent": 0.0, "held": 0.0, "shots": shots, "inflight": None, "pause": None,
          "approved": None, "seq": 0, "log": [], "warnings": warnings + p["warnings"], "must_ask": [],
          "controls_gaps": {}, "cast": cast}
    if seam_redo:
        st["seam_redo"] = {"max": SEAM_REDO_MAX, "threshold": long_plan.SEAM_THRESHOLD, "items": {}}
    if storyboard is not None:
        _controls(st, storyboard, cast)
    if blockout is not None:
        scenes = blockout_scenes(st, desc)
        apply_blockout(st, {k: blockout(k, sc) for k, sc in scenes.items()})
    return st

def blockout_scenes(st, desc):
    if not isinstance(desc, dict) or "shots" not in desc:
        _log(st, "blockout_skip", reason="no_scene")
        return {}
    keys = {s["key"] for s in st["shots"]}
    return {s["key"]: s["scene"] for s in shots_mod.compile(desc["shots"])["shots"] if s["key"] in keys}

def mark_blockout_pending(st, desc):
    scenes = blockout_scenes(st, desc)
    if scenes:
        st["blockout_pending"] = sorted(scenes)
        _log(st, "blockout_pending", shots=sorted(scenes))
    return scenes

def apply_blockout(st, results):
    for s in st["shots"]:
        if s["key"] not in results:
            continue
        r = results[s["key"]] or {}
        s["blockout"] = {"mode": r.get("mode"), "first_frame": r.get("first_frame"), "fallback": r.get("fallback")}
        if r.get("first_frame"):
            _log(st, "blockout_ready", shot_key=s["key"], mode=r.get("mode"))
        else:
            _log(st, "blockout_fallback", shot_key=s["key"], mode=r.get("mode"), code=r.get("fallback"))
    st.pop("blockout_pending", None)
    return st

def _log(st, kind, **kw):
    st["log"].append(dict({"n": len(st["log"]) + 1, "phase": st["phase"], "kind": kind}, **kw))
    if len(st["log"]) > LOG_MAX:
        raise LoopError("log 超過 %d 筆，主迴圈可能在打轉" % LOG_MAX)

def _shot(st, key):
    for s in st["shots"]:
        if s["key"] == key:
            return s
    raise LoopError("沒有這一鏡：%s" % key)

def _issue(st, act):
    st["seq"] += 1
    act = dict(act, id="a%d" % st["seq"])
    st["inflight"] = act
    _log(st, "issue", do=act["do"], action=act["id"], shot_key=act.get("shot_key"), cost=act.get("cost"),
         chain_action=act.get("chain_action"), reason=act.get("reason"))
    return act

def _ask(st, reason, detail, options, blocked=None):
    if st.get("gate") == "cards":
        options = [o for o in options if o not in HUMAN_ONLY]
    st["pause"] = {"reason": reason, "detail": detail, "options": list(options), "blocked": blocked}
    _log(st, "ask", reason=reason, shot_key=(blocked or {}).get("shot_key"))
    return {"do": "ask", "reason": reason, "detail": detail, "options": list(options)}

def _redo(st, s, reason):
    if s["redos"] >= st["max_retakes"]:
        s["status"] = "exhausted"
        return
    s["redos"] += 1
    s["status"], s["reason"] = "pending", reason

def _gate(st, s):
    b, c = st["budget"], s["cost"]
    if st.get("gate") == "cards":
        if c is None and (b["per_job"] is not None or b["per_run"] is not None):
            return "no_price", "這次拍片設了上限，但送件前算不出這一鏡要多少（沒有單價），保證不了上限。"
        if c is not None and b["per_job"] is not None and c > b["per_job"]:
            return "over_per_job", "這一鏡要 %s，超過單鏡上限 %s。" % (c, b["per_job"])
        if c is not None and b["per_run"] is not None and st["spent"] + c > b["per_run"] + 1e-9:
            return "over_per_run", "已經用了 %s，加上這一鏡 %s 會超過這次拍片的上限 %s。" % (st["spent"], c, b["per_run"])
        return None
    if c is None:
        return "no_price", "算不出這一鏡要多少（沒有單價），預先授權保證不了上限，要你本人放行。"
    if not preauthorized(b):
        return "approval_needed", "沒有預先授權（要開 auto 並設好單鏡與總上限），每一鏡都要你本人放行。"
    if c > b["per_job"]:
        return "over_per_job", "這一鏡要 %s，超過單鏡上限 %s。" % (c, b["per_job"])
    if st["spent"] + c > b["per_run"] + 1e-9:
        return "over_per_run", "已經用了 %s，加上這一鏡 %s 會超過這次拍片的上限 %s。" % (st["spent"], c, b["per_run"])
    return None

def _next(st):
    if st["phase"] in ("done", "stopped"):
        return {"do": st["phase"]}
    if st["pause"]:
        p = st["pause"]
        out = {"do": "ask", "reason": p["reason"], "detail": p["detail"], "options": p["options"]}
        if p.get("approve_url"):
            out["approve_url"] = p["approve_url"]
        return out
    if st["inflight"]:
        return st["inflight"]
    if st["phase"] == "budget" and st.get("blockout_pending"):
        return {"do": "wait_blockout", "shots": list(st["blockout_pending"])}
    if st["phase"] == "budget" and st.get("must_ask"):
        return _ask(st, "controls_gap", "分鏡有要你決定的缺口（%s），補好再送回來（controls 事件）。" % "、".join(
            "%s：%s" % (c, "、".join(v)) for c, v in sorted(st["controls_gaps"].items())), ("stop",))
    if st["phase"] == "budget":
        t = st["plan"]["totals"]
        b = st["budget"]
        if t["cost"] is not None and b["per_run"] is not None and t["cost"] > b["per_run"] + 1e-9:
            return _ask(st, "plan_over_budget", "這次規劃要 %s，超過這次拍片的上限 %s。" % (t["cost"], b["per_run"]),
                        ("raise", "stop"))
        st["phase"] = "execute"
        _log(st, "phase", to="execute")
    if st["phase"] == "execute":
        for i, s in enumerate(st["shots"]):
            if s["status"] in ("ok", "accepted"):
                continue
            if s["status"] == "exhausted":
                return _ask(st, "retakes_exhausted", "%s 重做 %d 次還是不合格。" % (s["key"], s["redos"]),
                            ("accept_best", "stop"), {"shot_key": s["key"]})
            if s["status"] == "wait_refund":
                return _issue(st, {"do": "wait_refund", "segment": i, "shot_key": s["key"], "take": s["takes"][-1]["take"],
                                   "job": s["takes"][-1].get("job")})
            if s["status"] == "checking":
                act = {"do": "check", "segment": i, "shot_key": s["key"], "take": s["takes"][-1]["take"],
                       "checks": s["checks"]}
                ref = (s.get("blockout") or {}).get("first_frame")
                if ref:
                    act["lock_qc_ref"] = ref
                return _issue(st, act)
            prev = st["shots"][i - 1]["picked"] if i else None
            act = {"do": "generate", "segment": i, "shot_key": s["key"], "attempt": len(s["takes"]) + 1,
                   "chain_action": "retake" if s["takes"] else "generate", "reason": s["reason"],
                   "parent": s["takes"][-1]["take"] if s["takes"] else None,
                   "first_frame": dict(s["first_frame"], take=prev if s["first_frame"]["source"] == "prev_last" else None),
                   "prompt": s["prompt"], "refs": s["refs"], "seconds": s["seconds"], "cost": s["cost"],
                   "controls": (s.get("controls") or {}).get("desc")}
            key = (s["key"], act["attempt"])
            why = None if st["approved"] == list(key) else _gate(st, s)
            if why:
                return _ask(st, why[0], why[1], ("approve", "raise", "stop"), act)
            if st["approved"] == list(key):
                _log(st, "approved_by_human", shot_key=s["key"], cost=s["cost"])
            st["approved"] = None
            return _issue(st, act)
        st["phase"] = "deliver"
        _log(st, "phase", to="deliver")
    act = {"do": "deliver", "chain_segments": st["plan"]["chain_segments"],
           "picks": {s["key"]: s["picked"] for s in st["shots"]}}
    sr = st.get("seam_redo")
    if sr is not None:
        act["seam_redo"] = {"threshold": sr["threshold"],
                            "seams": [[x["after"], x["before"]] for x in st["plan"]["seams"]],
                            "done": sorted(k for k, v in sr["items"].items() if v["count"] >= sr["max"])}
    return _issue(st, act)

def _reports(rs):
    if not isinstance(rs, list) or not rs:
        raise LoopError("checked 要帶 reports（品管報告陣列）")
    for r in rs:
        if not isinstance(r, dict) or not isinstance(r.get("ok"), bool) or \
                any(d not in qc_report.DEFECTS for d in r.get("defects") or []):
            raise LoopError("reports 要是 qc_report 的形狀（ok 是布林、defects 用 qc_report.DEFECTS）")
    return rs

def _apply_exec(st, ev):
    act = st["inflight"]
    if not act or ev.get("action") != act["id"]:
        raise LoopError("這個結果對不上正在等的動作（%s）" % (act or {}).get("id"))
    t = ev["type"]
    s = _shot(st, act["shot_key"]) if act["do"] != "deliver" else None
    if act["do"] == "generate" and t == "generated":
        take = ev.get("take")
        if not isinstance(take, str) or not take:
            raise LoopError("generated 要帶 take")
        cost = act["cost"] if ev.get("cost") is None else _num(ev["cost"], "cost", False)
        st["spent"] = round(st["spent"] + (cost or 0), 2)
        s["takes"].append({"take": take, "attempt": act["attempt"], "cost": cost, "ok": None, "defects": [],
                           "job": ev.get("job")})
        s["status"] = "checking"
        _log(st, "spend", shot_key=s["key"], take=take, cost=cost, spent=st["spent"])
    elif act["do"] == "generate" and t == "generate_failed":
        take = ev.get("take") or "failed-%s-%d" % (s["key"], act["attempt"])
        s["takes"].append({"take": take, "attempt": act["attempt"], "cost": act["cost"], "ok": False,
                           "defects": [], "failed": True, "job": ev.get("job")})
        if ev.get("refunded") is True:
            _log(st, "generate_failed", shot_key=s["key"], refunded=True)
            _redo(st, s, "generation_failed")
        else:
            st["held"] = round(st["held"] + (act["cost"] or 0), 2)
            st["spent"] = round(st["spent"] + (act["cost"] or 0), 2)
            s["status"] = "wait_refund"
            _log(st, "generate_failed", shot_key=s["key"], refunded=False, held=act["cost"], spent=st["spent"])
    elif act["do"] == "generate" and t == "submit_blocked":
        why = ev.get("reason")
        if why not in BLOCKED:
            raise LoopError("submit_blocked 的 reason 要是 %s" % "、".join(BLOCKED))
        st["pause"] = {"reason": why, "detail": str(ev.get("detail") or "核准卡要你本人核准")[:200],
                       "options": ["resume", "stop"], "blocked": None, "approve_url": ev.get("approve_url")}
        _log(st, "ask", reason=why, shot_key=s["key"], card=ev.get("card"))
        return
    elif act["do"] == "wait_refund" and t == "refunded":
        c = s["takes"][-1]["cost"] or 0
        st["held"] = round(st["held"] - c, 2)
        st["spent"] = round(st["spent"] - c, 2)
        _log(st, "refund", shot_key=s["key"], cost=c, spent=st["spent"])
        _redo(st, s, "generation_failed")
    elif act["do"] == "check" and t == "checked":
        rs = _reports(ev.get("reports"))
        ok = all(r["ok"] for r in rs if r.get("block") != "lock_qc")
        defects = sorted({d for r in rs if not r["ok"] for d in r.get("defects") or []})
        tk = s["takes"][-1]
        tk.update(ok=ok, defects=defects, score=min((r["score"] for r in rs if r.get("score") is not None), default=None))
        _log(st, "qc", shot_key=s["key"], take=tk["take"], ok=ok, defects=defects)
        for r in rs:
            if r.get("block") == "lock_qc":
                tk["lock_qc"] = r.get("score")
                _log(st, "lock_qc", shot_key=s["key"], take=tk["take"], score=r.get("score"), ok=r["ok"])
        if ok:
            s["status"], s["picked"] = "ok", tk["take"]
            _log(st, "pick", shot_key=s["key"], take=tk["take"], by="agent")
        else:
            _redo(st, s, "qc_fail")
    elif act["do"] == "deliver" and t == "seam_failed" and st.get("seam_redo") is not None:
        sr = st["seam_redo"]
        bad = ev.get("seams")
        if not isinstance(bad, list) or not bad:
            raise LoopError("seam_failed 要帶 seams（[{key, score}]）")
        todo = []
        for x in bad:
            key, score = (x or {}).get("key"), (x or {}).get("score")
            s = _shot(st, key)
            it = sr["items"].setdefault(key, {"count": 0, "scores": [], "est_cost": 0.0})
            if it["count"] >= sr["max"]:
                raise LoopError("%s 的接縫已經重做過 %d 次，不再重做" % (key, it["count"]))
            todo.append((s, it, score))
        for s, it, score in todo:
            it["count"] += 1
            it["scores"].append(None if score is None else round(float(score), 3))
            est = s["cost"] if s["cost"] is not None else next((t.get("cost") for t in reversed(s["takes"])
                                                                if t.get("cost") is not None), None)
            it["est_cost"] = round(it["est_cost"] + (est or 0), 2)
            s["status"], s["reason"] = "pending", "seam_jump"
            _log(st, "seam_redo", shot_key=s["key"], score=it["scores"][-1], est_cost=est, count=it["count"])
        st["phase"] = "execute"
        _log(st, "phase", to="execute")
    elif act["do"] == "deliver" and t == "delivered":
        st["phase"] = "done"
        sr = st.get("seam_redo")
        if sr is not None:
            sr["final"] = ev.get("seams")
            _log(st, "phase", to="done", export=ev.get("export"), seam_redo=seam_redo_summary(st))
        else:
            _log(st, "phase", to="done", export=ev.get("export"))
    else:
        raise LoopError("動作 %s 不收 %s" % (act["do"], t))
    st["inflight"] = None

def _apply_human(st, ev):
    d = ev.get("decision")
    p = st["pause"]
    if d not in DECISIONS:
        raise LoopError("decision 要是 %s" % "、".join(DECISIONS))
    if d in HUMAN_ONLY and st.get("gate") == "cards":
        raise LoopError("這一次走核准卡：%s 要你本人在 App 裡做（核准卡、上限設定）" % d)
    if not p:
        raise LoopError("現在沒有在等人決定")
    if d not in p["options"]:
        raise LoopError("現在（%s）只能回 %s" % (p["reason"], "、".join(p["options"])))
    if d == "stop":
        st["phase"], st["pause"] = "stopped", None
        _log(st, "human", decision="stop", reason=p["reason"])
        return
    if d == "raise":
        old = st["budget"]
        st["budget"] = clean_budget(ev.get("budget"))
        _log(st, "human", decision="raise", reason=p["reason"], budget_from=old, budget_to=st["budget"])
    elif d == "approve":
        b = p["blocked"]
        st["approved"] = [b["shot_key"], b["attempt"]]
        _log(st, "human", decision="approve", reason=p["reason"], shot_key=b["shot_key"], cost=b.get("cost"))
    elif d == "accept_best":
        s = _shot(st, p["blocked"]["shot_key"])
        cands = [t for t in s["takes"] if not t.get("failed")]
        if not cands:
            raise LoopError("%s 沒有生成成功的版本可以收" % s["key"])
        best = max(cands, key=lambda t: (t["score"] if t.get("score") is not None else 0.0, -t["attempt"]))
        s["status"], s["picked"] = "accepted", best["take"]
        _log(st, "human", decision="accept_best", shot_key=s["key"], take=best["take"])
    else:
        _log(st, "human", decision="resume")
    st["pause"] = None

def step(state, event=None):
    if not isinstance(state, dict) or state.get("version") != VERSION:
        raise LoopError("state 要是 start() 給的那個形狀")
    st = copy.deepcopy(state)
    if event is not None:
        if not isinstance(event, dict):
            raise LoopError("事件要是物件")
        t = event.get("type")
        if st["phase"] in ("done", "stopped"):
            raise LoopError("已經結束（%s）" % st["phase"])
        if t == "interrupt":
            if not st["pause"]:
                st["pause"] = {"reason": "interrupted", "detail": "你按了中斷；正在跑的那一個動作的結果還是會收。",
                               "options": ["resume", "stop"], "blocked": None}
                _log(st, "interrupt")
        elif t == "human":
            _apply_human(st, event)
        elif t == "controls":
            if not st["pause"] or st["pause"]["reason"] != "controls_gap":
                raise LoopError("現在沒有在等分鏡的缺口")
            st["pause"] = None
            _controls(st, event.get("storyboard"), event.get("cast", st.get("cast")))
            st["cast"] = event.get("cast", st.get("cast"))
        elif t in ("generated", "generate_failed", "submit_blocked", "refunded", "checked", "delivered", "seam_failed"):
            _apply_exec(st, event)
        else:
            raise LoopError("不認得的事件 %s" % t)
    return st, _next(st)

def seam_redo_summary(st):
    sr = st.get("seam_redo")
    if sr is None:
        return None
    items = [dict(v, key=k) for k, v in sorted(sr["items"].items())]
    skipped = [{"key": x.get("key"), "after": x.get("after"), "score": x.get("score"), "reason": x["skipped"]}
               for x in sr.get("final") or [] if isinstance(x, dict) and x.get("skipped")]
    return {"count": sum(v["count"] for v in items), "est_cost": round(sum(v["est_cost"] for v in items), 2),
            "threshold": sr["threshold"], "max_per_seam": sr["max"], "items": items, "final": sr.get("final"),
            "skipped": skipped}

def summary(st):
    out = _summary(st)
    if st.get("seam_redo") is not None:
        out["seam_redo"] = seam_redo_summary(st)
    return out

def _summary(st):
    return {"phase": st["phase"], "spent": st["spent"], "held": st["held"], "budget": st["budget"],
            "pause": {k: v for k, v in (st["pause"] or {}).items() if k != "blocked"} or None,
            "shots": [{"key": s["key"], "status": s["status"], "attempts": len(s["takes"]), "redos": s["redos"],
                       "picked": s["picked"]} for s in st["shots"]],
            "planned_cost": st["plan"]["totals"]["cost"], "worst_cost": st["plan"]["totals"]["worst_cost"],
            "warnings": st["warnings"]}
