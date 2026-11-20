import json
import sys

from . import agent_loop, executor

REQUEST = "小白和橘子在公園追球，30 秒"
SCRIPT = {"version": 1, "segments": [
    {"shot_key": "s1", "seconds": 10, "prompt": "@小白 在公園草地上看到一顆紅球滾過來，耳朵豎起來，鏡頭低角度跟拍"},
    {"shot_key": "s2", "seconds": 10, "prompt": "@小白 和 @橘子 一起追著紅球跑過草地，橘子 跳起來撲球，tracking 跟拍"},
    {"shot_key": "s3", "seconds": 10, "prompt": "球停在樹下，@小白 和 @橘子 一起趴在球旁邊喘氣，鏡頭慢慢拉遠"},
]}
DEMO_CAPS = {"first_frame": {"status": "ok"}, "last_frame": {"status": "untested"}}
BUDGET = {"auto": True, "per_job": 25, "per_run": 100}
PRICE = 2
SCRIPTED = {"s2": ["fail:character_mismatch", "pass"]}

def demo():
    st = agent_loop.start(REQUEST, SCRIPT, DEMO_CAPS, budget=BUDGET, has_cast_refs=True, price_per_second=PRICE,
                          max_retakes=1, target_seconds=30)
    ex = executor.FakeExecutor(SCRIPTED, polls=2)
    st, act = executor.run(st, ex)
    return st, act, ex

def main(argv=None, stdout=None):
    out = stdout or sys.stdout
    argv = sys.argv[1:] if argv is None else argv
    st, act, ex = demo()
    if "--json" in argv:
        out.write(json.dumps({"action": act, "summary": agent_loop.summary(st), "log": st["log"],
                              "executor_calls": ex.calls}, ensure_ascii=False, indent=2) + "\n")
        return 0 if act["do"] == "done" else 3
    sm = agent_loop.summary(st)
    out.write("需求：%s\n" % REQUEST)
    out.write("規劃：%d 鏡、%s 秒、成本 %s（最壞 %s）、預算 單鏡 %s／總共 %s\n" % (
        len(st["shots"]), st["plan"]["totals"]["seconds"], sm["planned_cost"], sm["worst_cost"],
        BUDGET["per_job"], BUDGET["per_run"]))
    out.write("結果：%s，實際花 %s；每鏡：%s\n\n" % (act["do"], sm["spent"], "、".join(
        "%s %s 次（定稿 %s）" % (s["key"], s["attempts"], s["picked"]) for s in sm["shots"])))
    for x in st["log"]:
        rest = {k: v for k, v in x.items() if k not in ("n", "phase", "kind") and v is not None}
        out.write("%3d  %-8s %-18s %s\n" % (x["n"], x["phase"], x["kind"], json.dumps(rest, ensure_ascii=False)))
    return 0 if act["do"] == "done" else 3

if __name__ == "__main__":
    sys.exit(main())
