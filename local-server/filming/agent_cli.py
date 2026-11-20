import argparse
import json
import sys

from . import agent_loop, qc_report

MAX_STEPS = 400
OUTCOMES = ("pass", "gen_failed", "gen_failed_held")

TOOL = {
    "name": "agent_loop_dry_run",
    "description": ("（dry-run，不花錢）Filming Agent 主迴圈的模擬：一句需求（或腳本／鏡頭表）→ long_plan 規劃（分鏡＋預算）"
                    "→ 逐鏡模擬生成與品管 → 不合格只重做那一鏡（每鏡最多 max_retakes 次）→ 交片。"
                    "預算閘：budget.auto 開著而且單鏡（per_job）與總上限（per_run）都設了，上限內自己送；"
                    "其他一律停下來問人（回 pause 與可以回的 options）。要續跑就把 state 原樣傳回來並帶 decision。"
                    "simulate 決定每一鏡每一次的模擬結果；沒寫的當通過。"),
    "input_schema": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "request": {"type": "string", "maxLength": agent_loop.REQUEST_MAX, "description": "一句需求（開新的一次要給）"},
            "input": {"type": "object", "description": "腳本或鏡頭表（同 long_plan）；沒給就用需求做草稿腳本"},
            "caps": {"type": "object", "description": "model_caps 工具回的那一列；沒給＝全部當沒實測"},
            "has_cast_refs": {"type": "boolean", "default": False},
            "price_per_second": {"type": ["number", "null"], "minimum": 0},
            "max_retakes": {"type": "integer", "minimum": 0, "maximum": 5, "default": 1},
            "target_seconds": {"type": ["number", "null"], "minimum": 1},
            "budget": {"type": "object", "description": "{auto, per_job, per_run}；預設 auto=false（每一鏡都問人）"},
            "simulate": {"type": "object", "description": "{鏡號: [\"pass\"|\"fail:<缺點>\"|\"gen_failed\"|\"gen_failed_held\"]}"},
            "state": {"type": "object", "description": "上一次回的 state（續跑）"},
            "decision": {"type": "string", "enum": list(agent_loop.DECISIONS)},
        },
    },
}
_KEYS = set(TOOL["input_schema"]["properties"])
_START = {"request", "input", "caps", "has_cast_refs", "price_per_second", "max_retakes", "target_seconds"}

def _clean_sim(sim):
    sim = sim or {}
    if not isinstance(sim, dict):
        raise agent_loop.LoopError("simulate 要是 {鏡號: [結果…]}")
    for k, v in sim.items():
        if not isinstance(v, list):
            raise agent_loop.LoopError("simulate.%s 要是陣列" % k)
        for o in v:
            ok = o in OUTCOMES or (isinstance(o, str) and o.startswith("fail:") and o[5:] in qc_report.DEFECTS)
            if not ok:
                raise agent_loop.LoopError("simulate.%s 的 %r 不認得（pass、fail:<缺點代碼>、gen_failed、gen_failed_held）" % (k, o))
    return sim

def _outcome(sim, key, attempt):
    seq = sim.get(key) or []
    return seq[attempt - 1] if attempt <= len(seq) else "pass"

def drive(st, sim, event=None):
    st, act = agent_loop.step(st, event)
    for _ in range(MAX_STEPS):
        d = act["do"]
        if d in ("ask", "done", "stopped"):
            return st, act
        if d == "generate":
            o = _outcome(sim, act["shot_key"], act["attempt"])
            take = "sim-%s-%d" % (act["shot_key"], act["attempt"])
            if o == "gen_failed":
                ev = {"type": "generate_failed", "take": take, "refunded": True}
            elif o == "gen_failed_held":
                ev = {"type": "generate_failed", "take": take, "refunded": False}
            else:
                ev = {"type": "generated", "take": take}
        elif d == "wait_refund":
            ev = {"type": "refunded"}
        elif d == "check":
            o = _outcome(sim, act["shot_key"], len(_take_list(st, act["shot_key"])))
            bad = None
            if o.startswith("fail:"):
                bad = "seam_check" if o == "fail:seam_jump" and "seam_check" in act["checks"] else "qc"
            ev = {"type": "checked", "reports": [
                qc_report.report(c, act["take"], ok=c != bad, defects=[o[5:]] if c == bad else [], source="simulate")
                for c in act["checks"]]}
        elif d == "deliver":
            ev = {"type": "delivered", "export": "sim-export"}
        else:
            raise agent_loop.LoopError("模擬器不認得動作 %s" % d)
        ev["action"] = act["id"]
        st, act = agent_loop.step(st, ev)
    raise agent_loop.LoopError("跑了 %d 步還沒結束" % MAX_STEPS)

def _take_list(st, key):
    return next(s["takes"] for s in st["shots"] if s["key"] == key)

def run(args):
    if not isinstance(args, dict):
        return {"error": "bad_args", "detail": "參數要是物件"}
    extra = set(args) - _KEYS
    if extra:
        return {"error": "bad_args", "detail": "不認得的參數 %s" % "、".join(sorted(extra))}
    try:
        sim = _clean_sim(args.get("simulate"))
        if args.get("state") is not None:
            if set(args) & _START:
                return {"error": "bad_args", "detail": "續跑只帶 state、decision（raise 再帶 budget）、simulate"}
            d = args.get("decision")
            ev = None
            if d:
                ev = {"type": "human", "decision": d}
                if args.get("budget") is not None:
                    ev["budget"] = args["budget"]
            st, act = drive(args["state"], sim, ev)
        else:
            if args.get("decision"):
                return {"error": "bad_args", "detail": "decision 要跟 state 一起給（續跑）"}
            st0 = agent_loop.start(args.get("request"), args.get("input"), args.get("caps"), budget=args.get("budget"),
                                   has_cast_refs=args.get("has_cast_refs", False),
                                   price_per_second=args.get("price_per_second"),
                                   max_retakes=args.get("max_retakes", 1), target_seconds=args.get("target_seconds"))
            st, act = drive(st0, sim)
    except (agent_loop.LoopError, qc_report.ReportError) as e:
        return {"error": "bad_input", "detail": str(e)}
    return {"dry_run": True, "action": act, "summary": agent_loop.summary(st), "state": st}

def _read(path, stdin):
    if path == "-":
        return json.loads((stdin or sys.stdin).read())
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)

def main(argv=None, stdin=None, stdout=None):
    out = stdout or sys.stdout

    def emit(obj, code):
        out.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
        return code
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--schema"]:
        return emit(TOOL, 0)
    ap = argparse.ArgumentParser(prog="python3 -m filming.agent_cli", description="Filming Agent 主迴圈（dry-run）")
    sub = ap.add_subparsers(dest="cmd")
    s1 = sub.add_parser("start")
    s1.add_argument("input", nargs="?")
    s1.add_argument("--request")
    s1.add_argument("--caps")
    s1.add_argument("--price", type=float)
    s1.add_argument("--retakes", type=int, default=1)
    s1.add_argument("--cast-refs", action="store_true")
    s1.add_argument("--target", type=float)
    s2 = sub.add_parser("resume")
    s2.add_argument("state")
    s2.add_argument("--decision", choices=agent_loop.DECISIONS)
    for p in (s1, s2):
        p.add_argument("--auto", action="store_true")
        p.add_argument("--per-job", type=float)
        p.add_argument("--per-run", type=float)
        p.add_argument("--simulate")
        p.add_argument("--save")
        p.add_argument("--full", action="store_true", help="印出完整 state 與 log")
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return emit({"error": "bad_args", "detail": "參數不對（見 --help）"}, 2)
    if not a.cmd:
        return emit({"error": "bad_args", "detail": "要給 start 或 resume（或 --schema）"}, 2)
    budget = None
    if a.auto or a.per_job is not None or a.per_run is not None:
        budget = {"auto": a.auto, "per_job": a.per_job, "per_run": a.per_run}
    files = {}
    for name in ("input", "caps", "simulate", "state"):
        path = getattr(a, name, None)
        if not path:
            continue
        try:
            files[name] = _read(path, stdin)
        except OSError as e:
            return emit({"error": "unreadable", "detail": "讀不到 %s（%s）" % (path, e.strerror)}, 1)
        except ValueError:
            return emit({"error": "bad_input", "detail": "%s 不是 JSON" % path}, 2)
    args = {"simulate": files.get("simulate")}
    if a.cmd == "start":
        if not a.request:
            return emit({"error": "bad_args", "detail": "start 要給 --request（一句需求）"}, 2)
        args.update(request=a.request, input=files.get("input"), caps=files.get("caps"), has_cast_refs=a.cast_refs,
                    price_per_second=a.price, max_retakes=a.retakes, target_seconds=a.target, budget=budget)
    else:
        args.update(state=files.get("state"), decision=a.decision)
        if budget is not None:
            args["budget"] = budget
    res = run({k: v for k, v in args.items() if v is not None})
    if "error" in res:
        return emit(res, 2)
    if a.save:
        with open(a.save, "w", encoding="utf-8") as fh:
            json.dump(res["state"], fh, ensure_ascii=False)
    shown = res if a.full else {"dry_run": True, "action": res["action"], "summary": res["summary"],
                                "log_tail": res["state"]["log"][-8:], "saved": a.save}
    phase = res["state"]["phase"]
    return emit(shown, 0 if phase == "done" else 4 if phase == "stopped" else 3)

if __name__ == "__main__":
    sys.exit(main())
