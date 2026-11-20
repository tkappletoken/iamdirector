from . import agent_loop, qc_report

MAX_STEPS = 400
MAX_POLLS = 60

class ExecutorError(RuntimeError):
    pass

def _poll(ex, req, max_polls, sleep):
    for n in range(max_polls):
        r = ex.poll(req)
        if not isinstance(r, dict) or r.get("state") not in ("running", "ready", "failed"):
            raise ExecutorError("poll 回了看不懂的東西：%r" % (r,))
        if (r.get("refunded") is True) if req["purpose"] == "refund" else r["state"] != "running":
            return r
        if sleep and n + 1 < max_polls:
            sleep()
    return None

def _generate(ex, act, max_polls, sleep):
    r = ex.submit(act)
    s = (r or {}).get("state")
    if s == "blocked":
        return {"type": "submit_blocked", "reason": r.get("reason"), "detail": r.get("detail"),
                "approve_url": r.get("approve_url"), "card": r.get("card")}
    if s == "failed":
        return {"type": "generate_failed", "refunded": r.get("refunded") is True, "take": r.get("take"), "job": r.get("job")}
    if s != "submitted" or not r.get("job") or not r.get("take"):
        raise ExecutorError("submit 要回 submitted（帶 job、take）、blocked 或 failed：%r" % (r,))
    p = _poll(ex, {"job": r["job"], "take": r["take"], "shot_key": act["shot_key"], "purpose": "generate"},
              max_polls, sleep)
    if p is None:
        return None
    if p["state"] == "failed":
        return {"type": "generate_failed", "refunded": p.get("refunded") is True, "take": r["take"], "job": r["job"]}
    return {"type": "generated", "take": p.get("take") or r["take"], "job": r["job"], "cost": r.get("cost")}

def run(state, executor, *, max_steps=MAX_STEPS, max_polls=MAX_POLLS, sleep=None, event=None):
    st, act = agent_loop.step(state, event)
    for _ in range(max_steps):
        d = act["do"]
        if d in ("ask", "done", "stopped", "wait_blockout"):
            return st, act
        if d == "generate":
            ev = _generate(executor, act, max_polls, sleep)
        elif d == "wait_refund":
            p = _poll(executor, {"job": act.get("job"), "take": act["take"], "shot_key": act["shot_key"],
                                 "purpose": "refund"}, max_polls, sleep)
            ev = None if p is None else {"type": "refunded"}
        elif d == "check":
            if not hasattr(executor, "qc"):
                return st, act
            reports = executor.qc(act)
            if reports is None:
                return st, act
            ev = {"type": "checked", "reports": reports}
        elif d == "deliver":
            if not hasattr(executor, "deliver"):
                return st, act
            ev = {"type": "delivered", "export": (executor.deliver(act) or {}).get("export")}
        else:
            raise ExecutorError("不認得的動作 %s" % d)
        if ev is None:
            return st, act
        ev["action"] = act["id"]
        st, act = agent_loop.step(st, ev)
    raise ExecutorError("跑了 %d 步還沒結束" % max_steps)

class FakeExecutor:

    def __init__(self, script=None, polls=1, price_per_second=None):
        self.script = script or {}
        self.polls = polls
        self.price = price_per_second
        self.calls = []
        self.jobs = {}
        self._state = {}
        self._blocked = set()
        self._attempt = {}
        self._foreign = {}
        self.spent = 0.0

    def _outcome(self, key, attempt):
        seq = self.script.get(key) or []
        return seq[attempt - 1] if attempt <= len(seq) else "pass"

    def submit(self, req):
        self.calls.append(("submit", req["id"], req["shot_key"], req["attempt"]))
        o = self._outcome(req["shot_key"], req["attempt"])
        if o.startswith("blocked:") and req["id"] not in self._blocked:
            self._blocked.add(req["id"])
            return {"state": "blocked", "reason": o[8:], "detail": "模擬：核准卡等人核准",
                    "approve_url": "iamdirector://approve/apv_fake%s" % req["id"], "card": "apv_fake%s" % req["id"]}
        if req["id"] in self.jobs:
            j = self.jobs[req["id"]]
            return {"state": "submitted", "job": j, "take": self._state[j]["take"], "cost": req.get("cost")}
        j = "job-%s-%d" % (req["shot_key"], req["attempt"])
        take = "tk-%s-%d" % (req["shot_key"], req["attempt"])
        self.jobs[req["id"]] = j
        self._attempt[take] = req["attempt"]
        self._state[j] = {"left": self.polls, "outcome": o, "take": take, "refund_left": 2, "cost": req.get("cost") or 0}
        if o == "gen_failed":
            return {"state": "failed", "refunded": True, "take": take, "job": j}
        self.spent += self._state[j]["cost"]
        return {"state": "submitted", "job": j, "take": take, "cost": req.get("cost")}

    def poll(self, req):
        self.calls.append(("poll", req["job"], req["purpose"]))
        s = self._state[req["job"]]
        if req["purpose"] == "refund":
            s["refund_left"] -= 1
            if s["refund_left"] <= 0 and not s.get("refunded"):
                self.spent -= s["cost"]
                s["refunded"] = True
            return {"state": "failed", "refunded": bool(s.get("refunded"))}
        s["left"] -= 1
        if s["left"] > 0:
            return {"state": "running"}
        if s["outcome"] == "gen_failed_held":
            return {"state": "failed", "refunded": False}
        return {"state": "ready", "take": s["take"]}

    def qc(self, req):
        self.calls.append(("qc", req["id"], req["shot_key"], req["take"]))
        attempt = self._attempt.get(req["take"])
        if attempt is None:
            seen = self._foreign.setdefault(req["shot_key"], [])
            if req["take"] not in seen:
                seen.append(req["take"])
            attempt = seen.index(req["take"]) + 1
        o = self._outcome(req["shot_key"], attempt)
        bad = None
        if o.startswith("fail:"):
            bad = "seam_check" if o == "fail:seam_jump" and "seam_check" in req["checks"] else "qc"
        return [qc_report.report(c, req["take"], c != bad, defects=[o[5:]] if c == bad else [], source="fake")
                for c in req["checks"]]

    def deliver(self, req):
        self.calls.append(("deliver", req["id"]))
        return {"export": "exp-fake"}
