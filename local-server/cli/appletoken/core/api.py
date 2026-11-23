
import json
import re
import urllib.error
import urllib.request
import uuid

from .errors import ValidationError

JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
QUOTE_REF_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
PP_ID_RE = re.compile(r"^pp_[A-Za-z0-9]{1,64}$")
ASSET_ID_RE = re.compile(r"^ast_[0-9a-f]{20}$")
UPLOAD_ID_RE = re.compile(r"^upl_[0-9a-f]{32}$")
STORE_KEY_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
STORE_KEYS_MAX = 64
USAGE_LIMIT_RE = re.compile(r"^[0-9]{1,4}$")
PROJECT_ID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
SB_QUOTE_RE = re.compile(r"^sb_[0-9a-f]{24}$")
PROJECT_ACTIONS = ("add", "remove")

WALLET_LIMIT_RE = re.compile(r"^[0-9]+$")
WALLET_HISTORY_CLAMP = 500

USAGE_LIMIT_MAX = 500
ASSETS_LIMIT_MAX = 100

BODY_LIMIT_DEFAULT = 512 * 1024
BODY_LIMIT_ASSETS = 24 * 1024 * 1024

TIMEOUT_DEFAULT = 30
TIMEOUT_GENERATE = 150

VIDEO_POLL_START = 4.0
VIDEO_POLL_FACTOR = 1.25
VIDEO_POLL_MAX = 20.0
VIDEO_POLL_429 = 60.0
VIDEO_TERMINAL = ("completed", "failed")

PP_POLL_FAST = 1.5
PP_POLL_SLOW = 3.0
PP_POLL_FAST_COUNT = 5
PP_POLL_MAX_TRIES = 60
PP_STATUSES = ("queued", "processing", "completed", "failed")
PP_TERMINAL = ("completed", "failed")

AUDIO_STYLES = ("phone", "walkie", "radio", "vinyl", "muffled",
                "hall", "lofi_16k", "lofi_24k", "mute")

def _check(value, pattern, what, shape):
    if not isinstance(value, str) or not pattern.match(value):
        raise ValidationError("%s 不合規則：要符合 %s，拿到的是 %r"
                              % (what, shape, value))
    return value

def _check_body(payload, limit, what):
    n = len(json.dumps(payload).encode("utf-8"))
    if n > limit:
        raise ValidationError(
            "%s 的 body 是 %d bytes，超過 studio 的上限 %d bytes。"
            % (what, n, limit))
    return payload

def is_confirmation(d):
    return isinstance(d, dict) and (
        d.get("object") == "video.confirmation"
        or d.get("status") == "needs_confirmation"
        or d.get("status") == "cancelled")

def _no_confirm(payload):
    if isinstance(payload, dict) and ({"quote_id", "confirm"} & set(payload)):
        raise ValidationError("報價不收 quote_id／confirm——要送出請用 *_confirm")

_UNSET = object()

def post_form(url, fields, blob, mime, filename, timeout=TIMEOUT_GENERATE):
    if not str(url).startswith("https://"):
        raise ValidationError("直傳網址要是 https：%s" % url)
    b = "----at%s" % uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (b, k, v)).encode())
    safe = re.sub(r'[^A-Za-z0-9._-]', "_", filename)[:80] or "file"
    parts.append(('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\n'
                  'Content-Type: %s\r\n\r\n' % (b, safe, mime)).encode() + blob + b"\r\n")
    parts.append(("--%s--\r\n" % b).encode())
    req = urllib.request.Request(url, data=b"".join(parts), method="POST",
                                 headers={"Content-Type": "multipart/form-data; boundary=" + b})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        raise ValidationError("上游儲存拒收這個檔案（HTTP %d）：%s"
                              % (e.code, e.read().decode(errors="replace")[:300])) from None

class Workbench:

    def __init__(self, client):
        self.c = client

    def version(self):
        return self.c.get("/api/version")

    def healthz(self):
        return self.c.get("/healthz")

    def model_groups(self):
        return self.c.get("/api/model-groups")

    def me(self):
        return self.c.get("/api/me")

    def usage(self, limit=50):
        limit = str(limit)
        _check(limit, USAGE_LIMIT_RE, "usage 的 limit", "^[0-9]{1,4}$")
        if not 1 <= int(limit) <= USAGE_LIMIT_MAX:
            raise ValidationError(
                "usage 的 limit 要在 1–%d 之間，拿到 %s。"
                "（上限是 gateway 定的，超過會被拒絕而不是縮到上限。）"
                % (USAGE_LIMIT_MAX, limit))
        return self.c.get("/api/usage", params={"limit": limit})

    def assets(self, limit=None, status=None, type=None, tag=None):
        if limit is not None and not 1 <= int(limit) <= ASSETS_LIMIT_MAX:
            raise ValidationError(
                "assets 的 limit 要在 1–%d 之間，拿到 %s。"
                "（注意這跟 usage 的 %d 不是同一個上限。）"
                % (ASSETS_LIMIT_MAX, limit, USAGE_LIMIT_MAX))
        return self.c.get("/api/assets", params={
            "limit": limit, "status": status, "type": type, "tag": tag})

    def assets_support(self):
        return self.c.get("/api/assets/support")

    def projects(self):
        return self.c.get("/api/projects")

    def project_create(self, name):
        n = (name or "").strip() if isinstance(name, str) else ""
        if not n:
            raise ValidationError("專案名稱不可以是空的（studio 會 strip 之後才判斷）")
        return self.c.post("/api/projects/create", {"name": n})

    def project_rename(self, project_id, name):
        _check(project_id, PROJECT_ID_RE, "project id", "^[0-9a-fA-F-]{36}$")
        n = (name or "").strip() if isinstance(name, str) else ""
        if not n:
            raise ValidationError("專案名稱不可以是空的（studio 會 strip 之後才判斷）")
        return self.c.post("/api/projects/rename", {"project_id": project_id, "name": n})

    def project_delete(self, project_id):
        _check(project_id, PROJECT_ID_RE, "project id", "^[0-9a-fA-F-]{36}$")
        return self.c.post("/api/projects/delete", {"project_id": project_id})

    def project_items(self, project_id, item_id, action="add"):
        _check(project_id, PROJECT_ID_RE, "project id", "^[0-9a-fA-F-]{36}$")
        _check(item_id, JOB_ID_RE, "item id", "^[A-Za-z0-9_-]{1,64}$")
        if action not in PROJECT_ACTIONS:
            raise ValidationError(
                "action 只收 %s，拿到 %r。"
                "（console 那側的方法名叫 detach，很容易混——但這裡不收。）"
                % ("／".join(PROJECT_ACTIONS), action))
        return self.c.post("/api/projects/items", {
            "project_id": project_id, "item_id": item_id, "action": action})

    def ffmpeg(self):
        return self.c.get("/api/ffmpeg")

    def job_status(self, job_id, retry=True):
        _check(job_id, JOB_ID_RE, "job id", "^[A-Za-z0-9_-]{1,64}$")
        return self.c.get("/api/status", params={"id": job_id}, retry=retry)

    def charges(self, job_ids):
        ids = list(job_ids or [])
        if not ids or len(ids) > 100:
            raise ValidationError("job_ids 要 1～100 個")
        for j in ids:
            _check(j, JOB_ID_RE, "job id", "^[A-Za-z0-9_-]{1,64}$")
        return self.c.get("/api/charges", params={"ids": ",".join(ids)})

    def qc(self, job_id, frames, expect=None, allow_cuts=False, count=None):
        _check(job_id, JOB_ID_RE, "job id", "^[A-Za-z0-9_-]{1,64}$")
        body = {"job": job_id, "expect": list(expect or [])}
        if frames is not None:
            fr = list(frames)
            if not 1 <= len(fr) <= 4 or not all(isinstance(f, str) and f.startswith("data:image/") for f in fr):
                raise ValidationError("frames 要 1～4 個 data:image/… 畫面")
            body["frames"] = fr
        if allow_cuts is True:
            body["allow_cuts"] = True
        if count:
            body["count"] = dict(count)
        return self.c.post("/api/qc", body)

    def storyboard_ai_quote(self, story, shots=6, style=None, video_model=None, project_id=None,
                            payer=None, dry_run=False, director=False):
        if not isinstance(story, str) or not story.strip() or len(story.strip()) > 3000:
            raise ValidationError("story 要 1～3000 字")
        if isinstance(shots, bool) or not isinstance(shots, int) or not 1 <= shots <= 12:
            raise ValidationError("shots 要是 1～12 的整數")
        body = {"story": story.strip(), "shots": shots}
        if style:
            if len(style) > 80:
                raise ValidationError("style 最多 80 字")
            body["style"] = style
        if video_model:
            body["video_model"] = video_model
        if project_id:
            _check(project_id, PROJECT_ID_RE, "project id", "^[0-9a-fA-F-]{36}$")
            body["project_id"] = project_id
        if payer:
            body["payer"] = payer
        if dry_run:
            body["dry_run"] = True
        if director:
            body["director"] = True
        return self.c.post("/api/storyboard/quote", body)

    def storyboard_ai_confirm(self, quote_id, confirm=True):
        _check(quote_id, SB_QUOTE_RE, "quote id", "^sb_[0-9a-f]{24}$")
        return self.c.post("/api/storyboard", {"quote_id": quote_id, "confirm": bool(confirm)})

    def qc_rate(self, job_id, score, tags=None, comment=None):
        _check(job_id, JOB_ID_RE, "job id", "^[A-Za-z0-9_-]{1,64}$")
        if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
            raise ValidationError("score 要是 1–5 的整數")
        tg = list(tags or [])
        if len(tg) > 10 or not all(isinstance(t, str) and re.match(r"^[a-z0-9_-]{1,32}$", t) for t in tg):
            raise ValidationError("tags 最多 10 個，每個只能是小寫英數、底線、連字號（1–32 字）")
        body = {"job": job_id, "score": score, "tags": tg}
        if comment:
            if len(comment) > 500:
                raise ValidationError("comment 最多 500 字")
            body["comment"] = comment
        return self.c.post("/api/qc/rate", body)

    def qc_rating(self, job_id):
        _check(job_id, JOB_ID_RE, "job id", "^[A-Za-z0-9_-]{1,64}$")
        return self.c.get("/api/qc/rating", params={"job": job_id})

    def qc_estimate(self, job_id, frames=3):
        _check(job_id, JOB_ID_RE, "job id", "^[A-Za-z0-9_-]{1,64}$")
        if isinstance(frames, bool) or not isinstance(frames, int) or not 1 <= frames <= 4:
            raise ValidationError("frames 要是 1–4 的整數")
        return self.c.get("/api/qc/estimate", params={"job": job_id, "frames": str(frames)})

    def download(self, job_id):
        _check(job_id, JOB_ID_RE, "job id", "^[A-Za-z0-9_-]{1,64}$")
        return self.c.get("/api/download", params={"id": job_id}, raw=True)

    def post_process_status(self, pp_id, retry=True):
        _check(pp_id, PP_ID_RE, "post-process id", "^pp_[A-Za-z0-9]{1,64}$")
        return self.c.get("/api/post-process-status", params={"id": pp_id},
                          retry=retry)

    def post_process_content(self, pp_id):
        _check(pp_id, PP_ID_RE, "post-process id", "^pp_[A-Za-z0-9]{1,64}$")
        return self.c.get("/api/post-process-content", params={"id": pp_id},
                          raw=True)

    def store_get(self, key):
        _check(key, STORE_KEY_RE, "store key", "^[a-z0-9_-]{1,32}$")
        return self.c.get("/api/store", params={"key": key})

    def store_get_many(self, keys):
        keys = list(keys)
        if not 1 <= len(keys) <= STORE_KEYS_MAX:
            raise ValidationError("store keys 要 1–%d 個（現在 %d 個）" % (STORE_KEYS_MAX, len(keys)))
        for k in keys:
            _check(k, STORE_KEY_RE, "store key", "^[a-z0-9_-]{1,32}$")
        return self.c.get("/api/store", params={"keys": ",".join(keys)})

    def store_put(self, key, value):
        _check(key, STORE_KEY_RE, "store key", "^[a-z0-9_-]{1,32}$")
        body = _check_body({"value": value}, BODY_LIMIT_DEFAULT, "/api/store")
        return self.c.post("/api/store", body, params={"key": key})

    def store_delete(self, key):
        _check(key, STORE_KEY_RE, "store key", "^[a-z0-9_-]{1,32}$")
        return self.c.delete("/api/store", params={"key": key})

    def parse_shots(self, text, model=None, story=None):
        body = {"text": text} if text or story is None else {"story": story}
        if model:
            body["model"] = model
        return self.c.post("/api/parse-shots",
                           _check_body(body, BODY_LIMIT_DEFAULT, "/api/parse-shots"))

    def check_refs(self, model, input_references):
        return self.c.post("/api/check-refs", _check_body(
            {"model": model, "input_references": input_references},
            BODY_LIMIT_DEFAULT, "/api/check-refs"))

    def check_asset(self, url, kind=None):
        body = {"url": url}
        if kind:
            body["kind"] = kind
        return self.c.post("/api/check-asset", body)

    def captions(self, cues, fmt="srt"):
        if fmt not in ("srt", "vtt"):
            raise ValidationError("captions 的格式只收 srt 或 vtt，拿到 %r" % fmt)
        return self.c.post("/api/captions", _check_body(
            {"cues": cues, "format": fmt}, BODY_LIMIT_DEFAULT, "/api/captions"))

    def estimate(self, payload):
        return self.c.post("/api/estimate",
                           _check_body(payload, BODY_LIMIT_DEFAULT, "/api/estimate"))

    def asset_upload(self, source, name=None, type=None, tags=None):
        body = {"source": source}
        if name:
            body["name"] = name
        if type:
            body["type"] = type
        if tags is not None:
            body["tags"] = list(tags)
        _check_body(body, BODY_LIMIT_ASSETS, "/api/assets")
        return self.c.post("/api/assets", body, timeout=TIMEOUT_GENERATE)

    def asset_content(self, asset_id):
        _check(asset_id, ASSET_ID_RE, "asset id", "^ast_[0-9a-f]{20}$")
        return self.c.get("/api/assets/content", params={"id": asset_id}, raw=True,
                          timeout=TIMEOUT_GENERATE)

    def asset_update(self, asset_id, name=_UNSET, tags=None):
        _check(asset_id, ASSET_ID_RE, "asset id", "^ast_[0-9a-f]{20}$")
        body = {"id": asset_id}
        if name is not _UNSET:
            body["name"] = name
        if tags is not None:
            body["tags"] = list(tags)
        if len(body) == 1:
            raise ValidationError("asset_update 要給 name 或 tags")
        return self.c.post("/api/assets/update", body)

    def asset_upload_start(self, mime, name=None, tags=None):
        body = {"mime": mime}
        if name:
            body["name"] = name
        if tags is not None:
            body["tags"] = list(tags)
        return self.c.post("/api/assets/uploads", body)

    def asset_upload_complete(self, upload_id):
        _check(upload_id, UPLOAD_ID_RE, "upload id", "^upl_[0-9a-f]{32}$")
        return self.c.post("/api/assets/uploads/complete", {"id": upload_id}, timeout=TIMEOUT_GENERATE)

    def asset_upload_direct(self, blob, mime, name=None, tags=None, post=None):
        up = self.asset_upload_start(mime, name=name, tags=tags)
        if len(blob) > int(up.get("max_bytes") or len(blob)):
            raise ValidationError("檔案 %d bytes 超過直傳上限 %s bytes" % (len(blob), up.get("max_bytes")))
        (post or post_form)(up["upload_url"], up.get("fields") or {}, blob, mime, name or "file")
        return self.asset_upload_complete(up["id"])

    def asset_mirror(self, to, items, from_=None):
        if to not in ("own_key", "points"):
            raise ValueError("to 要是 own_key 或 points")
        body = {"to": to, "items": list(items)}
        if from_:
            body["from"] = from_
        _check_body(body, BODY_LIMIT_ASSETS, "/api/assets/mirror")
        return self.c.post("/api/assets/mirror", body, timeout=TIMEOUT_GENERATE)

    def asset_delete(self, asset_id):
        _check(asset_id, ASSET_ID_RE, "asset id", "^ast_[0-9a-f]{20}$")
        return self.c.post("/api/assets/delete", {"id": asset_id})

    def request_confirmation(self, payload):
        body = dict(payload)
        body["require_confirmation"] = True
        _check_body(body, BODY_LIMIT_DEFAULT, "/api/generate")
        return self.c.post("/api/generate", body, spending=True,
                           timeout=TIMEOUT_GENERATE)

    def confirm(self, quote_id):
        return self.c.post("/api/generate", {"quote_id": quote_id, "confirm": True},
                           spending=True, timeout=TIMEOUT_GENERATE)

    def dir_controls_get(self, full=False):
        return self.c.get("/api/dir-controls", params={"full": "1"} if full else None)

    def dir_controls_preview(self, desc):
        return self.c.post("/api/dir-controls/preview", desc)

    def previs_rig(self, scene, spec):
        return self.c.post("/api/previs-rig", {"scene": scene, "spec": spec})

    def work_shot_dirctl(self, body):
        return self.c.post("/api/works/shot-dirctl", body)

    def work_get(self, project_id):
        _check(project_id, PROJECT_ID_RE, "project id", "^[0-9a-fA-F-]{36}$")
        return self.c.get("/api/works/get", params={"project_id": project_id})

    def takes_list(self, project_id=None, shot_key=None, take_id=None):
        params = {k: v for k, v in (("project_id", project_id), ("shot_key", shot_key), ("id", take_id)) if v}
        return self.c.get("/api/takes", params=params)

    def agent_plan(self, body):
        return self.c.post("/api/local/agent/plan", body)

    def agent_start(self, body):
        return self.c.post("/api/local/agent/start", body)

    def agent_step(self, body):
        return self.c.post("/api/local/agent/step", body)

    def agent_get(self, run):
        return self.c.get("/api/local/agent/get", params={"run": run})

    def agent_runs(self):
        return self.c.get("/api/local/agent/runs")

    def work_run(self, body):
        return self.c.post("/api/local/work/run", body)

    def agent_film(self, run):
        return self.c.get("/api/local/agent/film", params={"run": run})

    def ui_desc_get(self, name=None, questions=False, catalog=False, onboarding=False):
        flag = "questions" if questions else "catalog" if catalog else "onboarding" if onboarding else None
        params = {"name": name} if name else ({flag: "1"} if flag else None)
        return self.c.get("/api/local/ui-desc", params=params)

    def ui_desc_post(self, body):
        return self.c.post("/api/local/ui-desc", body)

    def take_add(self, shot_key, project_id=None, job_id=None, parent_take=None, reason=None, approval_id=None,
                 status="queued"):
        body = {"shot_key": shot_key, "status": status}
        for k, v in (("project_id", project_id), ("job_id", job_id), ("parent_take", parent_take), ("reason", reason),
                     ("approval_id", approval_id)):
            if v:
                body[k] = v
        return self.c.post("/api/takes", body)

    def take_update(self, take_id, status, error=None, job_id=None):
        body = {"id": take_id, "status": status}
        if error:
            body["error"] = error
        if job_id:
            body["job_id"] = job_id
        return self.c.post("/api/takes/move", body)

    def take_qc(self, take_id, reports):
        return self.c.post("/api/takes/qc", {"id": take_id, "reports": reports})

    def take_pick(self, take_id):
        return self.c.post("/api/takes/pick", {"id": take_id})

    def take_retake_plan(self, shot_key, reason="manual", project_id=None, max_retakes=1, failed_take=None,
                         charge_status=None):
        body = {"shot_key": shot_key, "reason": reason, "max_retakes": max_retakes}
        for k, v in (("project_id", project_id), ("failed_take", failed_take), ("charge_status", charge_status)):
            if v:
                body[k] = v
        return self.c.post("/api/takes/retake-plan", body)

    def chain_create(self, segments, project_id=None, max_retakes=1):
        body = {"segments": segments, "max_retakes": max_retakes}
        if project_id:
            body["project_id"] = project_id
        return self.c.post("/api/chains", body)

    def chain_next(self, chain_id):
        return self.c.post("/api/chains/next", {"id": chain_id})

    def chain_update(self, chain_id, status, stop_reason=None, export_id=None):
        body = {"id": chain_id, "status": status}
        if stop_reason:
            body["stop_reason"] = stop_reason
        if export_id:
            body["export_id"] = export_id
        return self.c.post("/api/chains/move", body)

    def work_clone(self, project_id, name=None, fields=None, shots=None):
        _check(project_id, PROJECT_ID_RE, "project id", "^[0-9a-fA-F-]{36}$")
        body = {"project_id": project_id}
        if name:
            body["name"] = name
        if fields is not None:
            body["fields"] = fields
        if shots is not None:
            body["shots"] = shots
        _check_body(body, BODY_LIMIT_DEFAULT, "/api/works/clone")
        return self.c.post("/api/works/clone", body)

    def shot_edit(self, project_id, shot, expect, prompt=None, seconds=None, set_seconds=False):
        _check(project_id, PROJECT_ID_RE, "project id", "^[0-9a-fA-F-]{36}$")
        body = {"project_id": project_id, "shot": shot, "expect": expect}
        if prompt is not None:
            body["prompt"] = prompt
        if seconds is not None or set_seconds:
            body["seconds"] = seconds
        _check_body(body, BODY_LIMIT_DEFAULT, "/api/works/shot-edit")
        return self.c.post("/api/works/shot-edit", body)

    def shot_move(self, project_id, shot, to, expect_order):
        _check(project_id, PROJECT_ID_RE, "project id", "^[0-9a-fA-F-]{36}$")
        body = {"project_id": project_id, "shot": shot, "to": to, "expect_order": list(expect_order or [])}
        _check_body(body, BODY_LIMIT_DEFAULT, "/api/works/shot-move")
        return self.c.post("/api/works/shot-move", body)

    def work_create(self, name, shots=None, script=None, model=None, template=None, fields=None, dry_run=False,
                    story=None):
        body = {"name": name}
        if template:
            body["template"] = template
            body["fields"] = fields or {}
        if shots is not None:
            body["shots"] = shots
        if script is not None:
            body["script"] = script
        if story is not None:
            body["story"] = story
        if model:
            body["model"] = model
        if dry_run:
            body["dry_run"] = True
        _check_body(body, BODY_LIMIT_DEFAULT, "/api/works/create")
        return self.c.post("/api/works/create", body)

    def approval_quote(self, payload):
        body = dict(payload)
        body["require_confirmation"] = True
        body["approval_card"] = True
        _check_body(body, BODY_LIMIT_DEFAULT, "/api/generate")
        return self.c.post("/api/generate", body, timeout=TIMEOUT_GENERATE)

    def approval_get(self, approval_id=None, quote_id=None, batch_id=None):
        if batch_id:
            return self.c.get("/api/approvals", params={"batch_id": batch_id})
        params = {"id": approval_id} if approval_id else {"quote_id": quote_id}
        return self.c.get("/api/approvals", params=params)

    def approval_list(self, status=None):
        return self.c.get("/api/approvals", params={"status": status} if status else None)

    def approval_batch(self, quote_ids):
        ids = [str(q) for q in (quote_ids or [])]
        if not 2 <= len(ids) <= 50:
            raise ValueError("quote_ids 要 2–50 件")
        return self.c.post("/api/approvals", {"quote_ids": ids})

    def approval_submit(self, approval_id, expect_amount=None):
        body = {"id": approval_id}
        if expect_amount not in (None, ""):
            body["expect_amount"] = str(expect_amount)
        return self.c.post("/api/approvals/submit", body, spending=True, timeout=TIMEOUT_GENERATE)

    def work_quote(self, project_id):
        return self.c.post("/api/works/quote", {"project_id": project_id}, timeout=TIMEOUT_GENERATE)

    def twist(self, job_id):
        _check(job_id, JOB_ID_RE, "job id", "^[A-Za-z0-9_-]{1,64}$")
        return self.c.get("/api/twist", params={"job": job_id}, timeout=TIMEOUT_GENERATE)

    def work_export(self, project_id, job_id, overrides=None, pipeline=None, dry_run=False, captions=None):
        body = {"project_id": project_id, "job_id": job_id}
        if captions is not None:
            body["captions"] = captions
        if overrides:
            body["overrides"] = overrides
        if pipeline is not None:
            body["pipeline"] = pipeline
        if dry_run:
            body["dry_run"] = True
        return self.c.post("/api/works/export", body)

    def blocks(self):
        return self.c.get("/api/blocks")

    def pipeline_preview(self, snapshot):
        if not isinstance(snapshot, dict):
            raise ValidationError("預覽的內容要是物件（跟匯出同一份請求）")
        return self.c.post("/api/pipeline/preview", snapshot)

    def export_status(self, export_id):
        return self.c.get("/api/export/status", params={"id": export_id})

    LOCAL_SWITCHES = {"agent-loop": "/api/local/agent-loop", "mcp-direct": "/api/local/mcp-direct",
                      "agent-qc": "/api/local/agent-qc", "frame-relay": "/api/local/frame-relay",
                      "agent-scope": "/api/local/agent-scope", "engine": "/api/local/engine",
                      "concat-engine": "/api/local/concat-engine", "ui-profiles": "/api/local/ui-profiles"}

    def local_switch(self, name):
        if name not in self.LOCAL_SWITCHES:
            raise ValueError("沒有這個開關：%s" % name)
        return self.c.get(self.LOCAL_SWITCHES[name])

    def concat(self, job_ids, name=None, mute_model_audio=None):
        for j in job_ids:
            _check(j, JOB_ID_RE, "job id", "^[A-Za-z0-9_-]{1,64}$")
        body = {"files": ["/api/download?id=%s" % j for j in job_ids]}
        if name:
            body["name"] = name
        if mute_model_audio is not None:
            body["mute_model_audio"] = bool(mute_model_audio)
        return self.c.post("/api/concat", body)

    def local_result(self, job_id):
        _check(job_id, JOB_ID_RE, "job id", "^[A-Za-z0-9_-]{1,64}$")
        return self.c.get("/api/local/result", params={"id": job_id})

    def confirm_status(self, quote_id):
        _check(quote_id, QUOTE_REF_RE, "quote_id", "^[A-Za-z0-9_-]{1,128}$")
        return self.c.get("/api/confirm-status", params={"quote_id": quote_id})

    def archive_status(self, job_id=None, kind="video", url=False):
        if job_id is None:
            return self.c.get("/api/archive")
        _check(job_id, JOB_ID_RE, "job_id", "^[A-Za-z0-9_-]{1,64}$")
        if kind not in ("video", "image"):
            raise ValueError("kind 只能是 video 或 image")
        params = {"id": job_id, "kind": kind}
        if url:
            params["url"] = "1"
        return self.c.get("/api/archive", params=params)

    def cancel(self, quote_id):
        return self.c.post("/api/generate", {"quote_id": quote_id, "confirm": False},
                           spending=True, timeout=TIMEOUT_GENERATE)

    def image_generate(self, payload):
        _check_body(payload, BODY_LIMIT_DEFAULT, "/api/image-generate")
        return self.c.post("/api/image-generate", payload, spending=True,
                           timeout=TIMEOUT_GENERATE)

    def image_outpaint(self, payload):
        _check_body(payload, BODY_LIMIT_ASSETS, "/api/image-outpaint")
        quote = isinstance(payload, dict) and bool(payload.get("quote"))
        return self.c.post("/api/image-outpaint", payload, spending=not quote,
                           timeout=TIMEOUT_GENERATE)

    def speech_quote(self, payload):
        _no_confirm(payload)
        _check_body(payload, BODY_LIMIT_DEFAULT, "/api/audio/speech")
        return self.c.post("/api/audio/speech", payload, spending=True, timeout=TIMEOUT_GENERATE)

    def speech_confirm(self, quote_id, confirm=True):
        return self.c.post("/api/audio/speech", {"quote_id": quote_id, "confirm": bool(confirm)},
                           spending=True, timeout=TIMEOUT_GENERATE)

    def music_quote(self, payload):
        _no_confirm(payload)
        _check_body(payload, BODY_LIMIT_DEFAULT, "/api/audio/music")
        return self.c.post("/api/audio/music", payload, spending=True, timeout=TIMEOUT_GENERATE)

    def music_confirm(self, quote_id, confirm=True):
        return self.c.post("/api/audio/music", {"quote_id": quote_id, "confirm": bool(confirm)},
                           spending=True, timeout=TIMEOUT_GENERATE)

    def music_status(self, job_id, retry=True):
        _check(job_id, JOB_ID_RE, "job id", "^[A-Za-z0-9_-]{1,64}$")
        return self.c.get("/api/audio/music-status", params={"id": job_id}, retry=retry)

    def music_content(self, job_id):
        _check(job_id, JOB_ID_RE, "job id", "^[A-Za-z0-9_-]{1,64}$")
        return self.c.get("/api/audio/music-content", params={"id": job_id})

    def audio_content(self, sha):
        if not re.match(r"^[0-9a-f]{64}$", str(sha or "")):
            raise ValidationError("sha 要是 64 個十六進位字元")
        return self.c.get("/api/audio/content", params={"sha": sha}, raw=True)

    EXPORT_ID_RE = re.compile(r"^exp_[a-z0-9]{8,40}$")

    def export_config(self):
        return self.c.get("/api/export/config")

    def export_start(self, snapshot):
        _check_body(snapshot, BODY_LIMIT_DEFAULT, "/api/export")
        return self.c.post("/api/export", snapshot, timeout=TIMEOUT_GENERATE)

    def export_status(self, export_id, retry=True):
        _check(export_id, self.EXPORT_ID_RE, "export id", "^exp_[a-z0-9]{8,40}$")
        return self.c.get("/api/export/status", params={"id": export_id}, retry=retry)

    def export_download(self, export_id):
        _check(export_id, self.EXPORT_ID_RE, "export id", "^exp_[a-z0-9]{8,40}$")
        return self.c.get("/api/export/download", params={"id": export_id})

    YT_PRIVACY = ("private", "unlisted", "public", "scheduled")
    YT_SOURCES = ("video", "export")
    YT_REF_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
    YT_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

    def youtube_status(self):
        return self.c.get("/api/youtube/status")

    def youtube_connect(self, playlists=False):
        return self.c.post("/api/youtube/connect", {"playlists": bool(playlists)})

    def youtube_disconnect(self):
        return self.c.post("/api/youtube/disconnect", {})

    def youtube_playlists(self):
        return self.c.get("/api/youtube/playlists")

    def youtube_playlist_create(self, title, privacy="private"):
        if privacy not in ("private", "unlisted", "public"):
            raise ValidationError("播放清單隱私只收 private／unlisted／public")
        return self.c.post("/api/youtube/playlists", {"title": title, "privacy": privacy}, spending=True)

    def youtube_upload(self, kind, ref, title, description="", tags=None, privacy="private",
                       publish_at=None, playlist_id=None, synthetic=True, made_for_kids=False,
                       thumbnail_asset=None):
        if kind not in self.YT_SOURCES:
            raise ValidationError("kind 只收 video／export")
        _check(ref, self.YT_REF_RE, "ref", "^[A-Za-z0-9_.:-]{1,128}$")
        if privacy not in self.YT_PRIVACY:
            raise ValidationError("privacy 只收 %s" % "／".join(self.YT_PRIVACY))
        if (privacy == "scheduled") != bool(publish_at):
            raise ValidationError("排程（scheduled）一定要給 publish_at，其他隱私不要給")
        body = {"source": {"kind": kind, "ref": ref}, "title": title, "description": description or "",
                "tags": list(tags or []), "privacy": privacy, "synthetic": bool(synthetic),
                "made_for_kids": bool(made_for_kids)}
        for k, v in (("publish_at", publish_at), ("playlist_id", playlist_id), ("thumbnail_asset", thumbnail_asset)):
            if v:
                body[k] = v
        return self.c.post("/api/youtube/uploads", body, spending=True)

    def youtube_uploads(self, upload_id=None, project_id=None):
        params = {}
        if upload_id:
            _check(upload_id, self.YT_ID_RE, "upload id", "UUID")
            params["id"] = upload_id
        if project_id:
            _check(project_id, PROJECT_ID_RE, "project id", "^[0-9a-fA-F-]{36}$")
            params["project_id"] = project_id
        return self.c.get("/api/youtube/uploads", params=params or None)

    def youtube_cancel(self, upload_id):
        _check(upload_id, self.YT_ID_RE, "upload id", "UUID")
        return self.c.post("/api/youtube/uploads/cancel", {"id": upload_id})

    def youtube_retry(self, upload_id):
        _check(upload_id, self.YT_ID_RE, "upload id", "UUID")
        return self.c.post("/api/youtube/uploads/retry", {"id": upload_id}, spending=True)

    def youtube_auto(self, project_id):
        _check(project_id, PROJECT_ID_RE, "project id", "^[0-9a-fA-F-]{36}$")
        return self.c.get("/api/youtube/auto", params={"project_id": project_id})

    def youtube_auto_set(self, project_id, enabled, privacy="private", schedule_delay_hours=None,
                         confirm_public=False, playlist_id=None, synthetic=True, made_for_kids=False,
                         title_template=None, description_template=None, tags=None):
        _check(project_id, PROJECT_ID_RE, "project id", "^[0-9a-fA-F-]{36}$")
        if privacy not in self.YT_PRIVACY:
            raise ValidationError("privacy 只收 %s" % "／".join(self.YT_PRIVACY))
        body = {"project_id": project_id, "enabled": bool(enabled), "privacy": privacy,
                "confirm_public": bool(confirm_public), "synthetic": bool(synthetic),
                "made_for_kids": bool(made_for_kids), "tags": list(tags or [])}
        for k, v in (("schedule_delay_hours", schedule_delay_hours), ("playlist_id", playlist_id),
                     ("title_template", title_template), ("description_template", description_template)):
            if v is not None:
                body[k] = v
        return self.c.post("/api/youtube/auto", body, spending=True)

    PITCH_KINDS = ("export", "video")
    PITCH_REF_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
    PITCH_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    PITCH_COVER_RE = re.compile(r"^ast_[A-Za-z0-9_-]{1,124}$")
    PITCH_LIKENESS = ("none", "consented")
    PITCH_MAX_EPISODES = 200

    def _pitch_episodes(self, episodes):
        if not isinstance(episodes, (list, tuple)) or not episodes:
            raise ValidationError("至少要有一集（episodes）")
        if len(episodes) > self.PITCH_MAX_EPISODES:
            raise ValidationError("最多 %d 集" % self.PITCH_MAX_EPISODES)
        out = []
        for i, e in enumerate(episodes, 1):
            if isinstance(e, str) and ":" in e:
                k, r = e.split(":", 1)
                e = {"kind": k, "ref": r}
            if not isinstance(e, dict) or e.get("kind") not in self.PITCH_KINDS:
                raise ValidationError("第 %d 集：kind 只收 export／video" % i)
            _check(e.get("ref"), self.PITCH_REF_RE, "第 %d 集的 ref" % i, "^[A-Za-z0-9_.:-]{1,128}$")
            out.append({"kind": e["kind"], "ref": e["ref"]})
        return out

    def pitch_platforms(self):
        return self.c.get("/api/pitch/platforms")

    def pitch_preview(self, episodes, cover_asset=None):
        body = {"episodes": self._pitch_episodes(episodes)}
        if cover_asset:
            _check(cover_asset, self.PITCH_COVER_RE, "cover asset", "^ast_…")
            body["cover_asset"] = cover_asset
        return self.c.post("/api/pitch/preview", body)

    def pitch_create(self, title, episodes, language, likeness, signer, materials_ok, ai_disclosure_ok,
                     synopsis="", genres=None, cover_asset=None, project_id=None, likeness_note="",
                     materials_note=""):
        if likeness not in self.PITCH_LIKENESS:
            raise ValidationError("likeness 只收 none／consented")
        if likeness == "consented" and not likeness_note:
            raise ValidationError("有真人肖像（consented）時要寫 likeness_note：是誰、怎麼取得同意")
        if not (materials_ok and ai_disclosure_ok):
            raise ValidationError("要確認素材授權（materials_ok）與 AI 揭露（ai_disclosure_ok）")
        if not signer:
            raise ValidationError("要有聲明人（signer）")
        body = {"title": title, "synopsis": synopsis or "", "language": language,
                "genres": list(genres or []), "episodes": self._pitch_episodes(episodes),
                "declarations": {"likeness": likeness, "likeness_note": likeness_note or "",
                                 "materials_ok": True, "materials_note": materials_note or "",
                                 "ai_disclosure_ok": True, "signer": signer}}
        if cover_asset:
            _check(cover_asset, self.PITCH_COVER_RE, "cover asset", "^ast_…")
            body["cover_asset"] = cover_asset
        if project_id:
            _check(project_id, PROJECT_ID_RE, "project id", "^[0-9a-fA-F-]{36}$")
            body["project_id"] = project_id
        return self.c.post("/api/pitch/packages", body, spending=True)

    def pitch_packages(self, package_id=None):
        if package_id:
            _check(package_id, self.PITCH_ID_RE, "package id", "UUID")
            return self.c.get("/api/pitch/packages", params={"id": package_id})
        return self.c.get("/api/pitch/packages")

    def pitch_download(self, package_id):
        _check(package_id, self.PITCH_ID_RE, "package id", "UUID")
        return self.c.get("/api/pitch/download", params={"id": package_id})

    def post_process(self, job_id, audio_style, intensity=None):
        if audio_style not in AUDIO_STYLES:
            raise ValidationError("audio_style 只收 %s，拿到 %r"
                                  % ("／".join(AUDIO_STYLES), audio_style))
        body = {"job_id": job_id, "audio_style": audio_style}
        if intensity is not None:
            if isinstance(intensity, bool) or not isinstance(intensity, int):
                raise ValidationError("intensity 要是 1–5 的整數（JSON 數字不是字串），"
                                      "拿到 %r" % (intensity,))
            if not 1 <= intensity <= 5:
                raise ValidationError("intensity 要在 1–5 之間，拿到 %d" % intensity)
            body["intensity"] = intensity
        return self.c.post("/api/post-process", body, spending=True,
                           timeout=TIMEOUT_GENERATE)

    def payer_state(self):
        return self.c.get("/api/payer")

    def payer_key_set(self, key, capability="video", provider="appletoken"):
        if not isinstance(key, str) or not key.strip():
            raise ValidationError("金鑰不能是空的")
        return self.c.post("/api/payer/key", {"key": key.strip(), "capability": capability,
                                              "provider": provider})

    def payer_key_delete(self, capability="video"):
        return self.c.post("/api/payer/key/delete", {"capability": capability})

    def payer_choice(self, capability, payer):
        if payer not in ("own_key", "points"):
            raise ValidationError("payer 只能是 own_key 或 points")
        return self.c.post("/api/payer/choice", {"capability": capability, "payer": payer})

    def agent_tokens(self):
        return self.c.get("/api/agent/tokens")

    def agent_token_create(self, name, scopes=("read",), confirm_spend=True,
                           daily_points_limit=None, expires_days=90):
        return self.c.post("/api/agent/tokens", {
            "name": name, "scopes": list(scopes), "confirm_spend": confirm_spend,
            "daily_points_limit": daily_points_limit, "expires_days": expires_days})

    def agent_token_revoke(self, token_id):
        return self.c.post("/api/agent/tokens/revoke", {"id": token_id})

    def agent_token_update(self, token_id, **fields):
        return self.c.post("/api/agent/tokens/update", dict(fields, id=token_id))

    def agent_activity_list(self, since=None, limit=50):
        return self.c.get("/api/agent/activity", params={"since": since, "limit": limit})

    def agent_activity(self, tool, ok=True, note="", ref=None, action=None, args=None):
        return self.c.post("/api/agent/activity", {"tool": tool, "ok": ok, "note": note,
                                                    "ref": ref, "action": action, "args": args})

    def agent_pending(self, pending_id=None, status="pending"):
        if pending_id:
            return self.c.get("/api/agent/pending", params={"id": pending_id})
        return self.c.get("/api/agent/pending", params={"status": status})

    def agent_pending_decide(self, pending_id, approve):
        return self.c.post("/api/agent/pending/decide", {"id": pending_id, "approve": bool(approve)},
                           spending=bool(approve))

    def wallet_balance(self):
        return self.c.get("/api/wallet/balance")

    def wallet_history(self, limit=None):
        params = {}
        if limit is not None:
            limit = str(limit)
            _check(limit, WALLET_LIMIT_RE, "wallet history 的 limit", "^[0-9]+$")
            params["limit"] = limit
        return self.c.get("/api/wallet/history", params=params or None)

    def wallet_options(self):
        return self.c.get("/api/wallet/options")

    def wallet_subscription(self):
        return self.c.get("/api/wallet/subscription")

    def wallet_subscribe(self):
        return self.c.post("/api/wallet/subscribe", {})

    def wallet_intent(self, amount):
        if isinstance(amount, bool) or not isinstance(amount, (int, float, str)):
            raise ValidationError(
                "儲值金額要是數字（或數字字串），拿到 %r" % (amount,))
        try:
            n = float(amount)
        except (TypeError, ValueError):
            raise ValidationError("儲值金額不是數字：%r" % (amount,))
        if not n > 0 or n != n or n in (float("inf"), float("-inf")):
            raise ValidationError("儲值金額要大於 0，拿到 %r" % (amount,))
        return self.c.post("/api/wallet/intent", {"amount": amount})

    def logout(self):
        return self.c.post("/api/logout", {})
