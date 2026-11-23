import json
import os
import re
import secrets
import threading
import urllib.error
import urllib.request

from filming import agent_loop, blender, blockout_frames, dir_controls, executor as fexec, frames as ffr, long_plan, qc_report

DONE = ("completed", "succeeded", "success", "done")

def own_key_refunded(s):
    if not isinstance(s, dict):
        return False
    if str(s.get("status") or "").lower() == "refunded":
        return True
    v = s.get("price_charged")
    if v is None or isinstance(v, bool):
        return False
    try:
        return float(v) == 0.0
    except (TypeError, ValueError):
        return False
FAILED = ("failed", "error", "cancelled", "canceled", "generation_failed")

class LocalExecutor:
    def __init__(self, port, secret, *, model, aspect_ratio="9:16", resolution="720p", project_id=None, ids=None,
                 timeout=30, caps=None, frames=None, relay=None, relay_cache=None, extra=None):
        self.base = "http://127.0.0.1:%d" % port
        self._secret = secret
        self.model, self.aspect_ratio, self.resolution = model, aspect_ratio, resolution
        self.extra = {k: v for k, v in (extra or {}).items() if k in PAYLOAD_EXTRA}
        self.project_id = project_id
        self.ids = ids if ids is not None else {}
        self.timeout = timeout
        self.caps = caps if isinstance(caps, dict) else {}
        self._frames = frames
        self.notes = []
        self._relay = relay
        self._relay_cache = relay_cache if relay_cache is not None else {}

    def __repr__(self):
        return "LocalExecutor(%s, model=%s)" % (self.base, self.model)

    def _call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data, method=method)
        r.add_header("Authorization", "Bearer " + self._secret)
        if data is not None:
            r.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(r, timeout=self.timeout) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw[:1] in (b"{", b"[") else {})
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"error": "HTTP %d" % e.code}
        except (urllib.error.URLError, OSError) as e:
            raise fexec.ExecutorError("連不到本機伺服器：%s" % getattr(e, "reason", e)) from None

    def _ok(self, code, obj, what):
        if not 200 <= code < 300:
            raise fexec.ExecutorError("%s 失敗（HTTP %d）：%s" % (what, code, (obj or {}).get("error")))
        return obj

    @staticmethod
    def _amount(card):
        v = card.get("amount")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _blocked(self, card, reason="card_pending"):
        return {"state": "blocked", "reason": reason, "card": card.get("id"), "approve_url": card.get("approve_url"),
                "detail": card.get("note") or "核准卡要你本人在 App 裡核准"}

    def submit(self, req):
        rec = self.ids.setdefault(req["id"], {})
        if rec.get("job"):
            return {"state": "submitted", "job": rec["job"], "take": rec["take"], "cost": rec.get("cost")}
        card = None
        if rec.get("card"):
            code, card = self._call("GET", "/api/approvals?id=" + rec["card"])
            card = self._ok(code, card, "讀核准卡")
            if card.get("status") in ("rejected", "expired", "failed"):
                relay = rec.get("relay")
                rec.clear()
                if relay:
                    rec["relay"] = relay
                card = None
            elif card.get("status") == "pending":
                return self._blocked(card)
        if card is None:
            src = req["first_frame"].get("source")
            relay_ref = None
            if src == "prev_last" and self._relay is not None:
                relay_ref = rec.get("relay") or self._relay_first(req, rec)
            elif src in ("prev_last", "blockout"):
                self._note("first_frame")
            body = self._body(req, relay_first=relay_ref)
            code, sheet = self._call("POST", "/api/generate", body)
            if code in (402, 409) and isinstance(sheet, dict) and sheet.get("direct"):
                card = sheet.get("approval") if isinstance(sheet.get("approval"), dict) else {}
                rec["card"] = card.get("id")
                return self._blocked(dict(card, note=sheet.get("error")), "over_limit")
            sheet = self._ok(code, sheet, what="報價")
            card = sheet.get("approval")
            if not isinstance(card, dict) or not card.get("id"):
                raise fexec.ExecutorError("報價沒有建出核准卡（本機的 Agent 報價一律建卡）")
            rec["card"] = card["id"]
            if card.get("status") != "approved":
                return self._blocked(card)
        cost = self._amount(card)
        if not rec.get("take"):
            t = self._ok(*self._call("POST", "/api/takes", {
                "project_id": self.project_id, "shot_key": req["shot_key"], "parent_take": self._take_of(req["parent"]),
                "reason": req.get("reason"), "approval_id": card["id"], "status": "queued"}), what="記 take")
            rec["take"] = t["id"]
        code, out = self._call("POST", "/api/approvals/submit", {"id": card["id"], "expect_amount": card.get("amount")})
        if code == 409 and isinstance(out, dict) and out.get("repriced"):
            return self._blocked(out.get("approval") or card, "repriced")
        if code == 409 and isinstance(out, dict) and "approval" not in out:
            return self._blocked(dict(card, note=out.get("error")))
        if not 200 <= code < 300 or not out.get("id"):
            self._call("POST", "/api/takes/move", {"id": rec["take"], "status": "failed",
                                                   "error": str((out or {}).get("error") or code)[:200]})
            self._call("POST", "/api/takes/move", {"id": rec["take"], "status": "refunded"})
            failed = {"state": "failed", "refunded": True, "take": rec["take"]}
            rec.clear()
            return failed
        rec.update(job=out["id"], cost=cost)
        self._ok(*self._call("POST", "/api/takes/move", {"id": rec["take"], "status": "generating", "job_id": out["id"]}),
                 what="take 轉 generating")
        return {"state": "submitted", "job": out["id"], "take": rec["take"], "cost": cost}

    def _relay_first(self, req, rec):
        take = req["first_frame"].get("take")
        if not take:
            self._note("frame_relay:fallback:no_prev")
            return None
        if self._relay_cache.get(take):
            rec["relay"] = self._relay_cache[take]
            self._note("frame_relay")
            return rec["relay"]
        try:
            ref, why = self._relay(take)
        except Exception as e:
            ref, why = None, "error:" + type(e).__name__
        if not ref:
            self._note("frame_relay:fallback:" + str(why or "unknown"))
            return None
        rec["relay"] = ref
        self._relay_cache[take] = ref
        self._note("frame_relay")
        return ref

    def _note(self, code):
        if code not in self.notes:
            self.notes.append(code)

    def _body(self, req, relay_first=None):
        body = self._body_base(req)
        if relay_first and not any(k in body for k in ("frame_images", "image_url")):
            if self._frames is None:
                self._note("frame_relay:fallback:no_caps")
                return body
            try:
                extra, notes = self._frames(self.model, relay_first, None)
            except ValueError:
                self._note("frame_relay:fallback:caps")
                return body
            body.update(extra)
            for n in notes:
                self._note("frames:" + n)
        return body

    def _body_base(self, req):
        base = {"model": self.model, "prompt": req["prompt"], "seconds": int(round(req["seconds"])),
                "aspect_ratio": self.aspect_ratio, "resolution": self.resolution, "require_confirmation": True}
        base.update(self.extra)
        desc = req.get("controls")
        if not desc:
            return base
        try:
            comp = dir_controls.compose(desc, self.caps)
        except dir_controls.DirControlsError as e:
            raise fexec.ExecutorError("導演控制的描述檔組不出生成輸入：%s" % e) from None
        b = comp["body"]
        for w in comp["warnings"]:
            self._note("controls:" + w)
        if b.get("model") and b["model"] != self.model:
            self._note("controls:model_ignored")
        body = dict(base, prompt=b["prompt"] or base["prompt"])
        if b.get("resolution"):
            body["resolution"] = b["resolution"]
        for k in ("controls", "cast", "cast_shot", "input_references"):
            if k in b:
                body[k] = b[k]
        if b.get("first_frame") or b.get("last_frame"):
            if self._frames is None:
                raise fexec.ExecutorError("描述檔帶了首尾幀，但沒有 model_caps.frames_payload 可以換欄位")
            try:
                extra, notes = self._frames(self.model, b.get("first_frame"), b.get("last_frame"))
            except ValueError as e:
                raise fexec.ExecutorError(str(e)) from None
            body.update(extra)
            for n in notes:
                self._note("frames:" + n)
        return body

    def _take_of(self, parent):
        return parent if isinstance(parent, str) and parent.startswith("tk_") else None

    def poll(self, req):
        code, s = self._call("GET", "/api/status?id=" + str(req["job"]))
        s = self._ok(code, s, "查進度")
        state = str(s.get("status") or "").lower()
        refunded = own_key_refunded(s)
        if req["purpose"] == "refund":
            if refunded:
                self._call("POST", "/api/takes/move", {"id": req["take"], "status": "refunded"})
            return {"state": "failed", "refunded": refunded}
        if state in DONE:
            self._call("POST", "/api/takes/move", {"id": req["take"], "status": "ready"})
            return {"state": "ready", "take": req["take"]}
        if state in FAILED or state == "refunded":
            self._call("POST", "/api/takes/move", {"id": req["take"], "status": "failed", "error": state})
            if refunded:
                self._call("POST", "/api/takes/move", {"id": req["take"], "status": "refunded"})
            return {"state": "failed", "refunded": refunded}
        return {"state": "running"}

    def record_qc(self, take, reports):
        self._ok(*self._call("POST", "/api/takes/qc", {"id": take, "reports": reports}), what="記品管")

    def deliver(self, req):
        segs = [dict(s) for s in req["chain_segments"]]
        for s in segs:
            s["model"] = self.model
        c = self._ok(*self._call("POST", "/api/chains", {"project_id": self.project_id, "segments": segs}), what="建接力")
        for key, take in req["picks"].items():
            if take:
                self._ok(*self._call("POST", "/api/takes/pick", {"id": take}), what="定稿 %s" % key)
        return {"export": c["id"]}

class AutoQC:

    def __init__(self, local, extras=None):
        self.local = local
        self.submit, self.poll, self.deliver, self.record_qc = local.submit, local.poll, local.deliver, local.record_qc
        self.notes = local.notes
        self._extras = extras

    def _stop(self, code):
        self.local._note("agent_qc:" + code)
        return None

    def qc(self, req):
        L = self.local
        rec = L.ids.setdefault(req["id"], {})
        if rec.get("qc_reports") is not None:
            return rec["qc_reports"]
        job = rec.get("qc_job")
        if not job:
            code, t = L._call("GET", "/api/takes?id=" + str(req["take"]))
            job = t.get("job_id") if 200 <= code < 300 and isinstance(t, dict) else None
            if not job:
                return self._stop("no_job")
            rec["qc_job"] = job
        extra = rec.get("qc_extra")
        if extra is None and self._extras is not None:
            extra, why = self._extras(req, job)
            if extra is None:
                return self._stop(why or "extra_unavailable")
            rec["qc_extra"] = extra
        card = None
        if rec.get("qc_card"):
            code, card = L._call("GET", "/api/approvals?id=" + rec["qc_card"])
            if not (200 <= code < 300 and isinstance(card, dict)) or card.get("status") in ("rejected", "expired", "failed"):
                rec.pop("qc_card", None)
                card = None
            elif card.get("status") == "pending":
                return self._stop("card_pending")
        if card is None:
            code, sheet = L._call("POST", "/api/qc", {"job": job})
            if code == 403:
                return self._stop("scope")
            if code in (402, 409) and isinstance(sheet, dict) and sheet.get("direct"):
                return self._stop("over_limit")
            if not 200 <= code < 300 or not isinstance(sheet, dict):
                return self._stop("quote_failed:%d" % code)
            card = sheet.get("approval") or {}
            if not card.get("id"):
                return self._stop("no_card")
            rec["qc_card"] = card["id"]
            if card.get("status") != "approved":
                return self._stop("card_pending")
        code, out = L._call("POST", "/api/approvals/submit", {"id": card["id"], "expect_amount": card.get("amount")})
        if not 200 <= code < 300 or not isinstance(out, dict) or not isinstance(out.get("verdict"), dict):
            if 200 <= code < 300 or code >= 500:
                rec.pop("qc_card", None)
            return self._stop("submit_failed:%d" % code)
        if not out["verdict"].get("ok"):
            rec.pop("qc_card", None)
            return self._stop("unreadable")
        reports = [qc_report.from_qc_verdict(out["verdict"], job, req["shot_key"])] + list(extra or [])
        L.record_qc(req["take"], reports)
        rec["qc_reports"] = reports
        L._note("agent_qc")
        return reports

class WithQC:

    def __init__(self, local, qc):
        self.local, self._qc = local, qc
        self.submit, self.poll, self.deliver = local.submit, local.poll, local.deliver

    def qc(self, req):
        reports = self._qc(req)
        self.local.record_qc(req["take"], reports)
        return reports

RUN_ID = re.compile(r"^agr_[0-9a-f]{24}$")
NEXT_DRAFT = ("這只是草稿：你只給了一句需求，規劃把整句平均切段、沒有拆鏡。請先把需求拆成鏡頭表，"
              "寫成 input={\"version\":1,\"segments\":[{\"prompt\":…,\"seconds\":…},…]}（request 只是說明），"
              "再呼叫一次 agent_plan 看預算，確定了才 agent_run(action=start)")
START_KEYS = {"request", "input", "caps", "has_cast_refs", "max_retakes", "target_seconds", "model", "aspect_ratio",
              "resolution", "project_id", "budget", "storyboard", "cast", "payload_extra"}
PAYLOAD_EXTRA = ("negative_prompt", "generate_audio")

def clean_extra(v):
    if v is None:
        return {}
    if not isinstance(v, dict) or set(v) - set(PAYLOAD_EXTRA):
        raise ValueError("payload_extra 只收 %s" % "、".join(PAYLOAD_EXTRA))
    out = {}
    if v.get("negative_prompt") is not None:
        if not isinstance(v["negative_prompt"], str) or len(v["negative_prompt"]) > 2000:
            raise ValueError("payload_extra.negative_prompt 要是 2000 字以內的字串")
        out["negative_prompt"] = v["negative_prompt"]
    if v.get("generate_audio") is not None:
        if not isinstance(v["generate_audio"], bool):
            raise ValueError("payload_extra.generate_audio 要是 true／false")
        out["generate_audio"] = v["generate_audio"]
    return out
STEP_KEYS = {"run", "decision", "event"}
CALLER_EVENTS = ("checked", "interrupt", "controls")
_GUARD = threading.Lock()
_BUSY = set()

def _path(data_dir, run):
    d = os.path.join(data_dir, "agent_runs")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return os.path.join(d, run + ".json")

def _load(data_dir, run):
    if not RUN_ID.match(str(run or "")):
        return None
    try:
        with open(_path(data_dir, run), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None

def _save(data_dir, run, rec):
    p = _path(data_dir, run)
    tmp = p + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
    os.replace(tmp, p)

def _reply(run, rec, act, ex):
    st = rec["state"]
    return {"run": run, "action": act, "summary": agent_loop.summary(st), "log_tail": st["log"][-8:],
            "notes": sorted(set(rec.get("notes", []) + (ex.notes if ex else [])))}

def _executor(rec, port, secret, caps_of, frames, relay=None):
    e = rec["exec"]
    return LocalExecutor(port, secret, model=e["model"], aspect_ratio=e["aspect_ratio"], resolution=e["resolution"],
                         project_id=e.get("project_id"), ids=rec["ids"], caps=caps_of(e["model"]) if caps_of else None,
                         frames=frames, relay=relay, relay_cache=rec.setdefault("relay_by_take", {}), extra=e.get("extra"))

_RENDERING = set()

def _bo_dir(data_dir, run):
    return os.path.join(data_dir, "blockout", run)

def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True

def _render_bg(data_dir, run, scenes, *, env, render, caps, ffprobe, ffmpeg):
    with _GUARD:
        if run in _RENDERING:
            return False
        _RENDERING.add(run)
    wd = _bo_dir(data_dir, run)

    def work():
        pids, results = [], {}
        try:
            def rfn(scene, outdir):
                kw = {"on_start": pids.append}
                if render is None:
                    kw["ffmpeg"] = ffmpeg or "ffmpeg"
                return (render or blender.render)(scene, outdir, **kw)
            prep = blockout_frames.preparer(wd, env, rfn, caps, ffprobe)
            for key in sorted(scenes):
                results[key] = prep(key, scenes[key]) if prep else {"mode": "legacy", "first_frame": None,
                                                                      "fallback": "legacy"}
        except Exception as e:
            for key in scenes:
                results.setdefault(key, {"mode": blockout_frames.mode(env), "first_frame": None,
                                         "fallback": "render", "error": str(e)[:200]})
        finally:
            out = {"results": results, "pids": pids, "pids_ended": not any(_alive(p) for p in pids)}
            os.makedirs(wd, mode=0o700, exist_ok=True)
            tmp = os.path.join(wd, "results.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False)
            os.replace(tmp, os.path.join(wd, "results.json"))
            with _GUARD:
                _RENDERING.discard(run)
    threading.Thread(target=work, name="blockout-" + run, daemon=True).start()
    return True

def _blockout_sync(data_dir, run, rec, st, **kw):
    if not st.get("blockout_pending"):
        return
    try:
        with open(os.path.join(_bo_dir(data_dir, run), "results.json"), encoding="utf-8") as f:
            res = json.load(f)
    except (OSError, ValueError):
        res = None
    if res is not None:
        agent_loop.apply_blockout(st, res.get("results") or {})
        rec["blockout"] = {"pids": res.get("pids", []), "pids_ended": res.get("pids_ended")}
        return
    with _GUARD:
        running = run in _RENDERING
    if not running:
        try:
            with open(os.path.join(_bo_dir(data_dir, run), "scenes.json"), encoding="utf-8") as f:
                scenes = json.load(f)
        except (OSError, ValueError):
            agent_loop.apply_blockout(st, {k: {"first_frame": None, "fallback": "lost"} for k in st["blockout_pending"]})
            return
        _render_bg(data_dir, run, scenes, **kw)

def _auto_extras(rec, local, video_of, ffmpeg, env, seam):
    keys = [s["key"] for s in rec["state"]["shots"]]

    def run(act, job):
        out = []
        checks = act.get("checks") or []
        if "seam_check" in checks:
            i = act.get("segment") or 0
            if i <= 0 or seam is None or video_of is None:
                return None, "seam_unavailable"
            code, d = local._call("GET", "/api/takes?project_id=%s&shot_key=%s" % (local.project_id or "", keys[i - 1]))
            prev = next((t for t in (d or {}).get("items", []) if t.get("id") == (d or {}).get("best")), None) \
                if 200 <= code < 300 and isinstance(d, dict) else None
            try:
                score = seam(prev["job_id"], job) if prev and prev.get("job_id") else None
            except Exception:
                score = None
            if score is None:
                return None, "seam_unavailable"
            ok = score >= long_plan.SEAM_THRESHOLD
            out.append(qc_report.report("seam_check", "%s>%s" % (keys[i - 1], act["shot_key"]), ok, round(float(score), 3),
                                        [] if ok else ["seam_jump"], None if ok else {"scope": "shot", "target": act["shot_key"]},
                                        "seam_check", "SSIM %.3f（門檻 %.2f）" % (score, long_plan.SEAM_THRESHOLD)))
        ref = act.get("lock_qc_ref")
        if "lock_qc" in checks and ref and blockout_frames.mode(env) != "legacy":
            try:
                rep = blockout_frames.measure(act["shot_key"], {"first_frame": ref}, video_of(job), env, ffmpeg=ffmpeg)
            except Exception:
                rep = None
            if rep is None or rep.get("score") is None:
                return None, "lock_qc_unavailable"
            out.append(rep)
        return out, None
    return run

def _lock_qc(rec, st, video_of, ffmpeg, env):
    act = st.get("inflight") or {}
    ref = act.get("lock_qc_ref")
    if not ref or blockout_frames.mode(env) == "legacy":
        return None
    job = next((tk.get("job") for s in st["shots"] for tk in s["takes"] if tk["take"] == act.get("take")), None)
    try:
        if not job or video_of is None:
            raise fexec.ExecutorError("這支 take 沒有 job，或沒有取片的方法")
        rep = blockout_frames.measure(act["shot_key"], {"first_frame": ref}, video_of(job), env, ffmpeg=ffmpeg)
        if rep is None or rep.get("score") is None:
            raise fexec.ExecutorError("量不出構圖")
        return rep
    except Exception:
        rec["notes"] = sorted(set(rec.get("notes", []) + ["lock_qc_unavailable"]))
        return None

RUNS_MAX = 20

def runs(data_dir):
    d = os.path.join(data_dir, "agent_runs")
    try:
        names = [n[:-5] for n in os.listdir(d) if n.endswith(".json") and RUN_ID.match(n[:-5])]
    except OSError:
        return []
    def mtime(r):
        try:
            return os.path.getmtime(_path(data_dir, r))
        except OSError:
            return 0
    out = []
    for r in sorted(names, key=mtime, reverse=True):
        rec = _load(data_dir, r)
        if not rec:
            continue
        st = rec.get("state") or {}
        out.append({"run": r, "request": st.get("request"), "phase": st.get("phase"),
                    "pause_reason": (st.get("pause") or {}).get("reason"), "updated": int(mtime(r))})
        if len(out) >= RUNS_MAX:
            break
    return out

def film_shots(data_dir, run):
    rec = _load(data_dir, run)
    if not rec:
        return None
    st = rec["state"]
    segs = {g.get("key"): g for g in ((st.get("plan") or {}).get("segments") or []) if isinstance(g, dict)}
    relayed = sorted({r["take"] for r in (rec.get("ids") or {}).values()
                      if isinstance(r, dict) and r.get("relay") and r.get("take")})
    return {"run": run, "relayed": relayed, "phase": st.get("phase"), "project_id": (rec.get("exec") or {}).get("project_id"),
            "request": st.get("request"), "model": (rec.get("exec") or {}).get("model"),
            "shots": [{"key": s["key"], "takes": [t["take"] for t in s.get("takes") or [] if t.get("take")],
                       "prompt": (segs.get(s["key"]) or {}).get("prompt"), "seconds": (segs.get(s["key"]) or {}).get("seconds")}
                      for s in st.get("shots") or []]}

def handle(op, body, *, data_dir, port, secret, caps_of=None, frames=None, ffmpeg=None, render=None, env=None,
           video_of=None, relay=None, auto_qc=False, seam=None):
    bo_kw = {"env": env, "render": render, "caps": None, "ffprobe": ffr.find_ffprobe(ffmpeg), "ffmpeg": ffmpeg}
    if op == "runs":
        return 200, {"items": runs(data_dir)}
    if op == "get":
        rec = _load(data_dir, body.get("run"))
        if not rec:
            return 404, {"error": "沒有這一次拍片"}
        st = rec["state"]
        if st.get("blockout_pending"):
            done = os.path.exists(os.path.join(_bo_dir(data_dir, body["run"]), "results.json"))
            with _GUARD:
                rendering = body["run"] in _RENDERING
            st = dict(st, blockout_progress={"done": done, "rendering": rendering})
        return 200, dict(st, run=body["run"], blockout_pids=rec.get("blockout"), exec={k: rec["exec"].get(k) for k in ("model", "project_id")})
    if op == "plan":
        extra = set(body) - START_KEYS
        if extra:
            return 400, {"error": "不認得的欄位 %s" % "、".join(sorted(extra))}
        bud = body.get("budget")
        if isinstance(bud, dict) and "auto" in bud:
            return 400, {"error": "這裡沒有 auto：要不要自動核准由核准卡的預先授權決定（你本人在 App 裡設）"}
        try:
            st = agent_loop.start(body.get("request"), body.get("input"), body.get("caps"), budget=bud,
                                  has_cast_refs=body.get("has_cast_refs", False), max_retakes=body.get("max_retakes", 1),
                                  target_seconds=body.get("target_seconds"), gate="cards",
                                  storyboard=body.get("storyboard"), cast=body.get("cast"))
        except agent_loop.LoopError as e:
            return 400, {"error": str(e)}
        p = st["plan"]
        return 200, {"dry_run": True, "summary": agent_loop.summary(st), "totals": p["totals"], "warnings": st["warnings"],
                     "segments": [{k: s.get(k) for k in ("key", "seconds", "prompt", "first_frame")} for s in p["segments"]],
                     "seams": p["seams"], "must_ask": st.get("must_ask") or [], "controls_gaps": st.get("controls_gaps") or {},
                     "next": NEXT_DRAFT if "script_draft" in st["warnings"] else
                     "要開拍就 agent_run(action=start, 同樣的 request／input／storyboard＋model)；花錢照核准卡與上限"}
    if op == "start":
        extra = set(body) - START_KEYS
        if extra:
            return 400, {"error": "不認得的欄位 %s" % "、".join(sorted(extra))}
        model = body.get("model")
        if not isinstance(model, str) or not model.strip() or len(model) > 120:
            return 400, {"error": "要給 model（模型 ref）"}
        bud = body.get("budget")
        if isinstance(bud, dict) and "auto" in bud:
            return 400, {"error": "這裡沒有 auto：要不要自動核准由核准卡的預先授權決定（你本人在 App 裡設）"}
        try:
            extra = clean_extra(body.get("payload_extra"))
        except ValueError as e:
            return 400, {"error": str(e)}
        run = "agr_" + secrets.token_hex(12)
        try:
            st = agent_loop.start(body.get("request"), body.get("input"), body.get("caps"), budget=bud,
                                  has_cast_refs=body.get("has_cast_refs", False), max_retakes=body.get("max_retakes", 1),
                                  target_seconds=body.get("target_seconds"), gate="cards",
                                  storyboard=body.get("storyboard"), cast=body.get("cast"))
        except agent_loop.LoopError as e:
            return 400, {"error": str(e)}
        if blockout_frames.mode(env) != "legacy":
            scenes = agent_loop.mark_blockout_pending(st, body.get("input"))
            if scenes:
                wd = _bo_dir(data_dir, run)
                os.makedirs(wd, mode=0o700, exist_ok=True)
                with open(os.path.join(wd, "scenes.json"), "w", encoding="utf-8") as f:
                    json.dump(scenes, f, ensure_ascii=False)
                _render_bg(data_dir, run, scenes, **bo_kw)
        rec = {"state": st, "ids": {}, "notes": [], "exec": {
            "model": model.strip(), "aspect_ratio": body.get("aspect_ratio") or "9:16",
            "resolution": body.get("resolution") or "720p", "project_id": body.get("project_id")}}
        if extra:
            rec["exec"]["extra"] = extra
        event = None
    elif op == "step":
        extra = set(body) - STEP_KEYS
        if extra:
            return 400, {"error": "不認得的欄位 %s" % "、".join(sorted(extra))}
        run = body.get("run")
        rec = _load(data_dir, run)
        if not rec:
            return 404, {"error": "沒有這一次拍片"}
        event = body.get("event")
        if body.get("decision") is not None:
            if event is not None:
                return 400, {"error": "decision 與 event 一次只給一個"}
            event = {"type": "human", "decision": body["decision"]}
        elif event is not None and (not isinstance(event, dict) or event.get("type") not in CALLER_EVENTS):
            return 400, {"error": "event 只能是 %s（其他結果由執行端產生）" % "、".join(CALLER_EVENTS)}
    else:
        return 404, {"error": "沒有這支端點"}
    with _GUARD:
        if run in _BUSY:
            return 409, {"error": "這一次拍片正在跑，等它這一步回來再送"}
        _BUSY.add(run)
    ex = None
    try:
        ex = _executor(rec, port, secret, caps_of, frames, relay)
        if auto_qc:
            ex = AutoQC(ex, _auto_extras(rec, ex, video_of, ffmpeg or ffr.find_ffmpeg(), env, seam))
        st = rec["state"]
        if op == "step":
            _blockout_sync(data_dir, run, rec, st, **bo_kw)
        try:
            if event is not None and event.get("type") == "checked":
                take = (st.get("inflight") or {}).get("take")
                rep = _lock_qc(rec, st, video_of, ffmpeg or ffr.find_ffmpeg(), env)
                if rep is not None and isinstance(event.get("reports"), list):
                    event = dict(event, reports=[r for r in event["reports"] if (r or {}).get("block") != "lock_qc"] + [rep])
                st, _ = agent_loop.step(st, dict(event, action=(st.get("inflight") or {}).get("id")))
                ex.record_qc(take, event.get("reports"))
                event = None
            st, act = fexec.run(st, ex, max_polls=1, event=event)
        except agent_loop.LoopError as e:
            return 400, {"error": str(e)}
        except fexec.ExecutorError as e:
            _save(data_dir, run, rec)
            return 502, {"error": str(e).replace(secret, "…"), "run": run, "retry": "修好之後用 step 續跑同一個 run"}
        rec["state"], rec["notes"] = st, sorted(set(rec["notes"] + ex.notes))
        _save(data_dir, run, rec)
        return 200, _reply(run, rec, act, ex)
    finally:
        with _GUARD:
            _BUSY.discard(run)
