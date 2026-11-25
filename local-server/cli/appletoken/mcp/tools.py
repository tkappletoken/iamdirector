
import base64
import hashlib
import math
import mimetypes
import os
import re
from pathlib import Path

from ..core import (STILL_RUNNING_HINT, ApiError, ValidationError, Workbench, is_confirmation,
                    poll_post_process, poll_video)
from .activity import Feed, describe
from ..core.api import AUDIO_STYLES, PP_POLL_MAX_TRIES, PP_POLL_SLOW
from ..core import model_caps
try:
    from ..cli import ledger
except ImportError:
    ledger = None

MAX_WAIT_SECONDS = 60

UI_OWNED_STORE_KEYS = ("presets", "jobs", "characters", "shots", "canvas",
                       "canvas-hidden",
                       "fixed-rules", "asset-meta",
                       "r3-project", "asset-rights",
                       "previs",
                       "shoot-prefs",
                       "card-locks",
                       "r6-pending",
                       "tts-say",
                       "r7-exports",
                       "series",
                       "ui_mode", "simple_works",
                       "batch-confirm",
                       "agent-policy")
UI_OWNED_STORE_KEY_PREFIXES = ("canvas-", "previs-", "sb_")

def ui_owned_key(key):
    return key in UI_OWNED_STORE_KEYS or key.startswith(UI_OWNED_STORE_KEY_PREFIXES)

AGENT_OWNED_STORE_KEYS = ("agent-activity",)

UNKNOWN_COST = object()

FORBIDDEN_PARAMS = ("session", "cookie", "api_key", "apikey", "token",
                    "authorization", "base_url")

class SpendBlocked(Exception):
    pass

class Tool:
    def __init__(self, name, description, schema, handler, spends=False):
        self.name = name
        self.description = description
        self.schema = schema
        self.handler = handler
        self.spends = spends

def _obj(props, required=()):
    return {"type": "object", "properties": props,
            "required": list(required), "additionalProperties": False}

class Registry:

    def __init__(self, session, allow_spend=False, max_spend_points=None,
                 download_dir=".", client=None, allow_delete=False,
                 allow_logout=False, allow_topup=False, activity=False,
                 remote=False, feed=None, local=False):
        from ..core import Client
        self.session = session
        self.remote = remote
        self.local = local
        self.ledger = _NoLedger if remote else ledger
        self.wb = Workbench(client or Client(session))
        self.allow_spend = allow_spend
        self.allow_delete = allow_delete
        self.allow_logout = allow_logout
        self.allow_topup = allow_topup
        self.max_spend_points = max_spend_points
        self.spent = 0.0
        self._quoted = {}
        self._spent_unknown = False
        self.download_dir = Path(download_dir)
        self.feed = feed or Feed(self.wb, session, enabled=activity)
        self._tools = self._build()
        if remote:
            self._go_remote()

    def _charge(self, points, what):
        if self.max_spend_points is None:
            return
        if self._spent_unknown:
            raise SpendBlocked(
                "這個 session 先前有一趟花了錢但**金額不可知**"
                "（平台沒回確認單、直接把工作建掉了），"
                "上限 %.4f 點已經保證不了。沒有送出任何請求。"
                % self.max_spend_points)
        if points is None or points is UNKNOWN_COST:
            raise SpendBlocked(
                "%s 查不到這一趟要花多少點，而你設了上限 %.4f 點。"
                "看不到金額就不能保證不超過——沒有送出任何請求。"
                "（影片請先用 video_quote 拿確認單，金額在那上面。）"
                % (what, self.max_spend_points))
        p = float(points)
        if self.spent + p > self.max_spend_points:
            raise SpendBlocked(
                "%s 要花 %.4f 點，加上這個 session 已花的 %.4f 點會超過上限 %.4f 點。"
                "沒有送出任何請求。" % (what, p, self.spent, self.max_spend_points))
        self.spent += p

    def list_tools(self):
        return list(self._tools.values())

    def names(self):
        return sorted(self._tools)

    def call(self, name, arguments=None):
        t = self._tools.get(name)
        if t is None:
            out = self._refuse(name)
            self.feed.record(name, ok=False, note=out["error"])
            return out
        return self._call_and_tell(t, arguments or {})

    def _go_remote(self):
        for name in _LOCAL_FILE_TOOLS:
            self._tools.pop(name, None)
        if not self.local:
            for name in _LOCAL_UI_TOOLS + _LOCAL_AGENT_TOOLS + _LOCAL_MEDIA_TOOLS:
                self._tools.pop(name, None)
        self._tools.pop("session_logout", None)
        base = getattr(self.session, "public_url", None) or self.session.base_url

        def url_tool(name, desc, key, path, param):
            self._tools[name] = Tool(
                name, desc, _obj({key: {"type": "string"}}, [key]),
                lambda a: {"url": "%s%s?%s=%s" % (base, path, param, a[key]),
                           "auth": "GET 這個網址時帶同一把權杖：Authorization: Bearer <你的權杖>",
                           "note": "伺服器不替你存檔；要落地就自己下載。"})
        url_tool("video_download_url", "影片成品的下載網址（mp4）。帶同一把權杖 GET 它。",
                 "job_id", "/api/download", "id")
        url_tool("post_process_download_url", "後處理成品的下載網址（mp4，pp_ 開頭的 id）。",
                 "pp_id", "/api/post-process-content", "id")
        url_tool("asset_download_url", "素材原檔的下載網址（ast_ 開頭的 id）。帶同一把權杖 GET 它。",
                 "asset_id", "/api/assets/content", "id")
        url_tool("audio_music_download_url",
                 "配樂的取檔資訊（JSON，裡面的 audio.url 帶同一把權杖再 GET 一次）。",
                 "job_id", "/api/audio/music-content", "id")
        t = self._tools["asset_upload"]
        self._tools["asset_upload"] = Tool(
            "asset_upload",
            "把素材放進素材庫，回一個 asset:// 參照，可以直接放進 video_quote 的 input_references。"
            "**不扣點數。** 遠端模式給 url（http(s)，平台自己去抓）或 data_uri（data:image/png;base64,…）"
            "**二選一**；這個 MCP 跑在伺服器上，讀不到你電腦的檔案。",
            _obj({"url": {"type": "string"}, "data_uri": {"type": "string"},
                  "name": {"type": "string"}, "type": {"type": "string"},
                  "tags": {"type": "array", "items": {"type": "string"}}}),
            self._h_asset_upload_remote, t.spends)
        if not self.local:
            for name in _LOCAL_DIRCTL_TOOLS:
                self._tools.pop(name, None)
        else:
            for name in _LOCAL_UNREACHABLE:
                self._tools.pop(name, None)

    def _h_asset_upload_remote(self, a):
        url, data = a.get("url"), a.get("data_uri")
        if bool(url) == bool(data):
            return {"error": "asset_upload 要給 url 或 data_uri **其中一個**（%s）。"
                             % ("兩個都給了，我不會替你挑" if url else "一個都沒給")}
        if data and not re.match(r"^data:[a-z0-9.+-]+/[a-z0-9.+-]+;base64,", data, re.I):
            return {"error": "data_uri 要長得像 data:image/png;base64,…"}
        if url:
            from urllib.parse import urlparse
            p = urlparse(str(url))
            if p.scheme not in ("http", "https") or not p.hostname:
                return {"error": "url 只收 http(s):// 開頭的網址"}
        return self.wb.asset_upload(url or data, name=a.get("name"), type=a.get("type"), tags=a.get("tags"))

    def _refuse(self, name):
        out = self._refuse_local(name)
        if self.remote and name in _SPENDING_NAMES + _DESTRUCTIVE_NAMES + _TOPUP_NAMES + _LOGOUT_NAMES:
            flag = {"--allow-spend": "spend", "--allow-delete": "delete",
                    "--allow-topup": "topup", "--allow-logout": "logout"}
            for k, v in flag.items():
                out["error"] = out["error"].replace(k, "權杖的「%s」權限" % v)
            out["error"] += "（遠端 MCP：到工作台「Agent 協作」發一把有這個權限的權杖。）"
        return out

    def _refuse_local(self, name):
        if name in _SPENDING_NAMES:
            return {"error": "工具 %s 需要 --allow-spend 才會啟用。"
                             "這是刻意的：預設的工具表裡沒有任何能花錢的東西。" % name}
        if name in _DESTRUCTIVE_NAMES:
            return {"error": "工具 %s 需要 --allow-delete 才會啟用。"
                             "這是另一道閘，不是 --allow-spend——"
                             "刪除不花錢，但也救不回來。" % name}
        if name in _LOGOUT_NAMES:
            return {"error": "工具 %s 需要 --allow-logout 才會啟用。"
                             "**這是第三道閘，跟 --allow-delete 也是分開的。**"
                             "登出殺掉的是共用的 SSO session：這個 MCP server "
                             "自己接下來每一次呼叫都會 401，而且使用者正開著的"
                             "瀏覽器分頁也會一起被登出。" % name}
        if name in _TOPUP_NAMES:
            return {"error": "工具 %s 需要 --allow-topup 才會啟用。"
                             "**這是第四道閘，不是 --allow-spend。**"
                             "--allow-spend 是花掉已經有的額度，這一支是反方向："
                             "它會在 Stripe 那邊產生一筆真的待付款。" % name}
        return {"error": "沒有這個工具：%s" % name}

    def _call_and_tell(self, t, args):
        try:
            out = t.handler(args)
        except Exception as e:
            self.feed.record(t.name, ok=False, note="失敗：%s" % e)
            raise
        ok = not (isinstance(out, dict) and "error" in out)
        note = (out.get("error") if not ok and isinstance(out, dict)
                else describe(t.name, args, out))
        ref = out.get("id") if isinstance(out, dict) else None
        self.feed.record(t.name, ok=ok, note=note, ref=ref, args=args, result=out)
        return out

    def _build(self):
        wb = self.wb
        tools = {}

        def add(name, desc, schema, handler, spends=False):
            tools[name] = Tool(name, desc, schema, handler, spends)

        add("workbench_health",
            "檢查 studio 服務層是否正常。這一支不需要創作者資格，"
            "所以它是「服務掛了」與「身分有問題」的分離器。",
            _obj({}), lambda a: wb.version())

        add("list_models",
            "列出工作台可用的模型（依 modality 分組）。"
            "constraints 是空的代表目錄還沒填，不代表不支援。",
            _obj({}), lambda a: wb.model_groups())

        add("get_balance",
            "查 **AppleToken 帳戶**的額度（總額／已用／保留／可用），單位是**點**。"
            "這是生成影片與圖片實際扣的那一筆。"
            "⚠ 跟 wallet_balance **不是同一筆錢**，而且兩者欄位名一模一樣——"
            "那一支是使用者付給這個站的錢（幣別金額）。兩個數字不可以相減。",
            _obj({}), lambda a: wb.me())

        add("list_usage", "最近的扣款明細。",
            _obj({"limit": {"type": "integer", "minimum": 1, "maximum": 9999}}),
            lambda a: wb.usage(a.get("limit", 50)))

        add("list_assets", "列出素材庫。tag 只列有這個標籤的。",
            _obj({"limit": {"type": "string"}, "status": {"type": "string"},
                  "type": {"type": "string"}, "tag": {"type": "string"}}),
            lambda a: wb.assets(a.get("limit"), a.get("status"), a.get("type"), a.get("tag")))

        add("asset_update",
            "改素材的名稱或標籤（沒給的欄位不動；tags 給了就整組換掉，[] 是清空）。"
            "**不扣點數、不影響引用與計費**，只方便整理。標籤最多 20 個、每個 40 字以內。",
            _obj({"asset_id": {"type": "string"}, "name": {"type": "string"},
                  "tags": {"type": "array", "items": {"type": "string"}}}, ["asset_id"]),
            lambda a: wb.asset_update(a["asset_id"], **({"name": a["name"]} if "name" in a else {}),
                                      tags=a.get("tags")))

        add("asset_fetch",
            "把素材原檔寫成檔案，回檔案路徑與 sha256。**不回位元組**。",
            _obj({"asset_id": {"type": "string"}, "filename": {"type": "string"}}, ["asset_id"]),
            self._h_asset_fetch)

        add("video_status", "查一支影片工作的狀態。便宜、可以重複呼叫。",
            _obj({"job_id": {"type": "string"}}, ["job_id"]),
            lambda a: wb.job_status(a["job_id"]))

        add("qc_rating", "讀回一支影片在 AppleToken 的評分（沒評過是 null）。",
            _obj({"job_id": {"type": "string"}}, ["job_id"]),
            lambda a: wb.qc_rating(a["job_id"]))

        add("video_confirm_status",
            "video_confirm 回 status=pending_confirm（上游確認逾時、點數已預扣）時用這個查結果："
            "state=submitted 帶 id（接著用 video_status／video_wait）、released＝上游沒收到、點數已退回、"
            "pending＝還在對帳。**不要重送 video_confirm**。",
            _obj({"quote_id": {"type": "string"}}, ["quote_id"]),
            lambda a: wb.confirm_status(a["quote_id"]))

        add("video_archive_status",
            "成片存檔狀態：每支生成完成後伺服器在背景存進 S3（不花錢、唯讀）。給 job_id 查一件"
            "（status=waiting／saving／saved／failed／gave_up／gone／no_output；url=true 且 saved 時附預簽網址），"
            "不給列出自己最近 50 件。kind 是 video（預設）或 image。",
            _obj({"job_id": {"type": "string"}, "kind": {"type": "string", "enum": ["video", "image"]},
                  "url": {"type": "boolean"}}),
            lambda a: wb.archive_status(a.get("job_id"), a.get("kind", "video"), bool(a.get("url"))))

        add("video_wait",
            "等一支影片工作，最多 %d 秒。逾時回 still_processing——"
            "那**不是失敗**，用 video_status 繼續查即可。" % MAX_WAIT_SECONDS,
            _obj({"job_id": {"type": "string"},
                  "timeout_seconds": {"type": "integer", "minimum": 1,
                                      "maximum": MAX_WAIT_SECONDS}},
                 ["job_id"]),
            self._h_wait)

        add("video_fetch",
            "把成品 mp4 寫成檔案，回檔案路徑與 sha256。"
            "**不回位元組**——那會把 agent 的上下文塞爆。",
            _obj({"job_id": {"type": "string"}, "filename": {"type": "string"}},
                 ["job_id"]),
            self._h_fetch)

        add("create_work",
            "建一部作品：新的專案＋它自己的分鏡（主線打開就看得到）。**免費**。"
            "shots 是 [{prompt, seconds?}]（1–30 鏡）；或給 script（「Shot 1｜0-3s …」那種腳本）讓伺服器拆鏡；或給 story（一段故事，照句子拆）；"
            "或給 template='meme'（迷因短片：一鏡到底、固定鏡頭、9:16、11–15 秒）＋fields"
            "（setup 前段情境、twist_at 第幾秒反轉、chaos 後段暴走；選填 seconds、resolution＝720p／1080p（預設 720p）、"
            "characters＝角色外觀描述（提示詞裡用到名字就要寫，不然模型不知道長什麼樣子）、extra_negative＝追加的 negative"
            "（接在內建的後面，內建的刪不掉）、first_frame／last_frame＝首尾幀（網址或 asset://，依模型能力表換欄位）、props＝道具（120 字內，明確寫進提示詞）、visual_cues＝一定要看得見的元素（120 字內）、"
            "allow_cuts＝允許切鏡頭（預設 false＝一鏡到底）、count_animals（預設 true：characters 寫成「名字: 描述; …」"
            "就自動加 Only N animals in the entire video）、cap_setup、cap_twist、flash_before、style＝meme／memebox）。"
            "範本的 negative 與「只用環境音」由伺服器寫，報價用 quote_work；回應的 warnings 要看。"
            "dry_run=true（只限 template）＝只驗欄位、回組好的提示詞與警告，不建作品。count_animals 也可以給 1–9 的數字。",
            _obj({"name": {"type": "string", "minLength": 1},
                  "shots": {"type": "array", "items": {"type": "object"}},
                  "script": {"type": "string"}, "model": {"type": "string"},
                  "template": {"type": "string", "enum": ["meme"]}, "fields": {"type": "object"},
                  "dry_run": {"type": "boolean"}, "story": {"type": "string"}}, ["name"]),
            lambda a: _work_create(wb, a))

        if self.local:
            self._add_ui_tools(add)
            self._add_agent_tools(add)
            self._add_local_media_tools(add)

        add("take_list",
            "列一鏡（shot_key）或整個專案的候選（take）：狀態、品管報告、是不是定稿；best＝品管最好的那支。免費。",
            _obj({"project_id": {"type": "string"}, "shot_key": {"type": "string"}, "take_id": {"type": "string"}}),
            lambda a: wb.takes_list(a.get("project_id"), a.get("shot_key"), a.get("take_id")))
        add("take_add",
            "記一支候選：送件之後把 job_id 記在那一鏡底下；重抽的帶 parent_take（重抽哪一支）＋reason（品管缺點代碼、"
            "seam_jump、generation_failed、manual）。同一個 job_id 只會有一支。免費。",
            _obj({"shot_key": {"type": "string"}, "project_id": {"type": "string"}, "job_id": {"type": "string"},
                  "parent_take": {"type": "string"}, "reason": {"type": "string"}, "approval_id": {"type": "string"},
                  "status": {"type": "string", "enum": ["queued", "generating", "ready"]}}, ["shot_key"]),
            lambda a: wb.take_add(a["shot_key"], a.get("project_id"), a.get("job_id"), a.get("parent_take"),
                                  a.get("reason"), a.get("approval_id"), a.get("status") or "queued"))
        add("take_update",
            "候選的狀態往前走：queued → generating → ready／failed → refunded（只能往前，不合法回 409）。免費。",
            _obj({"take_id": {"type": "string"}, "status": {"type": "string",
                  "enum": ["generating", "ready", "failed", "refunded"]}, "error": {"type": "string"},
                  "job_id": {"type": "string"}}, ["take_id", "status"]),
            lambda a: wb.take_update(a["take_id"], a["status"], a.get("error"), a.get("job_id")))
        add("take_qc",
            "存一支候選的品管報告（video_qc 的判定、接縫 SSIM…：每份要有 ok，可帶 score 0–1、defects、redo）。"
            "qc_ok＝全部過才 true。免費。",
            _obj({"take_id": {"type": "string"}, "reports": {"type": "array", "items": {"type": "object"}}},
                 ["take_id", "reports"]),
            lambda a: wb.take_qc(a["take_id"], a["reports"]))
        add("take_pick",
            "定稿：這一鏡用這一支（同一鏡最多一支，換人選會把舊的取消）。只有 ready 的能定稿；記成 picked_by=agent。免費。",
            _obj({"take_id": {"type": "string"}}, ["take_id"]),
            lambda a: wb.take_pick(a["take_id"]))
        add("take_retake_plan",
            "該不該重抽這一鏡（不花錢、不送件）：回 retake＋attempt＋parent，或 stop 的原因（retakes_exhausted、"
            "already_ok、already_picked）。生成失敗的帶 failed_take＋charge_status：錢退了（refunded／released／"
            "cancelled）才准重送，沒退回 waiting_refund。要重抽就照舊報價→核准卡（上限照算）→送件，再 take_add。",
            _obj({"shot_key": {"type": "string"}, "reason": {"type": "string"}, "project_id": {"type": "string"},
                  "max_retakes": {"type": "integer", "minimum": 0, "maximum": 5}, "failed_take": {"type": "string"},
                  "charge_status": {"type": "string"}}, ["shot_key"]),
            lambda a: wb.take_retake_plan(a["shot_key"], a.get("reason") or "manual", a.get("project_id"),
                                          a.get("max_retakes", 1), a.get("failed_take"), a.get("charge_status")))
        add("chain_create",
            "開一次長片接力（例如 4 段 × 15 秒 = 1 分鐘）：segments＝[{prompt, seconds 2–15, model?, shot_key?}]。"
            "之後一直叫 chain_next 照它說的做。免費。",
            _obj({"segments": {"type": "array", "items": {"type": "object"}}, "project_id": {"type": "string"},
                  "max_retakes": {"type": "integer", "minimum": 0, "maximum": 5}}, ["segments"]),
            lambda a: wb.chain_create(a["segments"], a.get("project_id"), a.get("max_retakes", 1)))
        add("chain_next",
            "接力的下一步（不花錢、不送件，只告訴你該做什麼）：generate（first_frame_from＝上一段定稿的 take，"
            "拿它的最後一幀當首幀）、wait、pick、retake（附重抽計畫）、stop（停下來要人決定，附原因）、export。",
            _obj({"chain_id": {"type": "string"}}, ["chain_id"]),
            lambda a: wb.chain_next(a["chain_id"]))
        add("chain_update",
            "改接力的狀態：running、done（帶 export_id）、failed、stopped（帶 stop_reason 代碼）。免費。",
            _obj({"chain_id": {"type": "string"}, "status": {"type": "string",
                  "enum": ["running", "done", "failed", "stopped"]}, "stop_reason": {"type": "string"},
                  "export_id": {"type": "string"}}, ["chain_id", "status"]),
            lambda a: wb.chain_update(a["chain_id"], a["status"], a.get("stop_reason"), a.get("export_id")))

        add("work_get",
            "讀回一部作品：名字、分鏡（prompt、seconds）；範本作品再帶 template 與 fields（create_work 時給的那一份）。免費。",
            _obj({"project_id": {"type": "string"}}, ["project_id"]),
            lambda a: wb.work_get(a["project_id"]))

        add("work_clone",
            "複製一部作品成新的一部（新專案、自己的分鏡）。免費。範本作品給 fields＝只改這幾欄（值給 null 拿掉那一欄），"
            "伺服器用範本重新組（negative、固定鏡頭照舊），回 warnings；一般作品可以給 shots 換掉分鏡。"
            "用來做「同一支迷因換一個 twist」「長片接力換首幀（fields.first_frame）」。name 不給＝原名＋「副本」。",
            _obj({"project_id": {"type": "string"}, "name": {"type": "string"}, "fields": {"type": "object"},
                  "shots": {"type": "array", "items": {"type": "object"}}}, ["project_id"]),
            lambda a: wb.work_clone(a["project_id"], a.get("name"), a.get("fields"), a.get("shots")))

        add("quote_work",
            "用範本建的作品**只報價，不扣款**：送件的 payload 由伺服器照範本組（你改不掉 negative 與環境音），"
            "同時建一張核准卡，跟 quote 一樣回 approval.approve_url——等使用者本人核准後用 submit_approved 送出。",
            _obj({"project_id": {"type": "string"}}, ["project_id"]),
            lambda a: wb.work_quote(a["project_id"]))

        add("twist_detect",
            "量一支成片的反轉點（畫面突然暴走的那一刻，秒數）與閃光的位置。唯讀、不花錢。"
            "at 是 null＝沒把握：看 candidates（最多 3 個 {t, score}，第一個是建議），請使用者確認之後用 "
            "overrides.twist.at 指定。只在桌面版本機模式。",
            _obj({"job_id": {"type": "string"}}, ["job_id"]),
            lambda a: wb.twist(a["job_id"]))

        add("meme_export",
            "迷因短片一鍵匯出 mp4（桌面版本機，不花錢）：作品的字卡＋白閃，自動對齊反轉點，裁成 1080×1920、faststart。"
            "overrides 可改 captions／effects／twist（例如 {\"twist\": {\"at\": 9.6}}）。"
            "captions=\"none\"＝無字版（不燒字卡，白閃與反轉點照常；不帶＝照範本的字卡）。"
            "這支 ffmpeg 沒有 libass 時會自動輸出無字版並在 warnings 說明，不會整支失敗。回匯出 id，用 result(export_id) 拿檔案。",
            _obj({"project_id": {"type": "string"}, "job_id": {"type": "string"}, "overrides": {"type": "object"},
                  "captions": {"type": "string", "enum": ["none"]}},
                 ["project_id", "job_id"]),
            lambda a: wb.work_export(a["project_id"], a["job_id"], a.get("overrides"), captions=a.get("captions")))

        add("blocks_list",
            "後製積木目錄（唯讀、不花錢）：每一塊的 id、名稱、階段（stage）、必要與否（locked）、"
            "能不能換順序（sortable，只有 overlay 階段）、參數表，以及 templates（範本的預設組合）。",
            _obj({}),
            lambda a: wb.blocks())

        add("pipeline_from_template",
            "範本的預設積木組合（例如 meme）：回一份 pipeline 陣列，可以直接改開關／順序／參數後交給 "
            "pipeline_preview／pipeline_export。字卡內容、白閃時間照舊來自作品（create_work 的範本）。",
            _obj({"template": {"type": "string", "enum": ["meme"]}}, ["template"]),
            lambda a: {"template": a["template"], "pipeline": (wb.blocks().get("templates") or {}).get(a["template"])})

        add("pipeline_validate",
            "驗一份積木組合（不匯出、不花錢）：放錯階段、必要的積木被關掉、參數不對都會回錯誤並說明是哪一塊。"
            "沒錯就回 ok 與整理過的組合。",
            _obj({"project_id": {"type": "string"}, "job_id": {"type": "string"}, "snapshot": {"type": "object"},
                  "pipeline": {"type": "array", "items": {"type": "object"}}, "overrides": {"type": "object"}},
                 ["pipeline"]),
            lambda a: {"ok": True, "blocks": self._pipeline_dry(a).get("blocks")})

        add("pipeline_preview",
            "預覽一份積木組合（dry_run：只編譯、不跑 ffmpeg、不下載素材、不花錢）：回 filtergraph、總長、警告、"
            "每塊積木在成片上的位置（placements）。custom＝true 表示跟範本預設不同。"
            "給 project_id＋job_id（作品，桌面版）或 snapshot（跟匯出同一份請求，網頁版與桌面版都可以）。",
            _obj({"project_id": {"type": "string"}, "job_id": {"type": "string"}, "snapshot": {"type": "object"},
                  "pipeline": {"type": "array", "items": {"type": "object"}}, "overrides": {"type": "object"}}),
            self._pipeline_dry)

        add("pipeline_export",
            "照一份積木組合匯出 mp4（桌面版本機，不花錢；網頁版請用 export_request 請導演按匯出）。"
            "回匯出 id，用 result(export_id) 拿檔案。開關 POSTBLOCKS_ENGINE 不是 blocks 時會照原本的流程匯出（積木的自訂不採用）。",
            _obj({"project_id": {"type": "string"}, "job_id": {"type": "string"},
                  "pipeline": {"type": "array", "items": {"type": "object"}}, "overrides": {"type": "object"}},
                 ["project_id", "job_id", "pipeline"]),
            lambda a: wb.work_export(a["project_id"], a["job_id"], a.get("overrides"), a["pipeline"]))

        add("quote",
            "**只報價，不扣款、不建工作**。同時建一張核准卡（pending）：回 quote_id、金額、付款方，"
            "approval.id 與 approval.approve_url。把連結交給使用者，**等他本人在 App 或網頁按核准**——"
            "你自己核准不了。核准之後用 submit_approved 送出。" + _SHOT_INPUTS_DOC,
            _obj(dict({"model": {"type": "string"}, "prompt": {"type": "string"},
                       "seconds": {"type": "integer"}, "resolution": {"type": "string"},
                       "aspect_ratio": {"type": "string"}, "negative_prompt": {"type": "string"},
                       "generate_audio": {"type": "boolean"}}, **_SHOT_INPUTS),
                 ["model", "prompt"]),
            lambda a: wb.approval_quote(_shot_payload(a)))

        add("request_approval",
            "取得一張報價的核准卡：卡片 id、給人點的連結（approve_url）、付款方、金額、模型、秒數、狀態。"
            "狀態 pending＝還沒有人核准；approved＝可以 submit_approved；rejected／expired＝重新報價。"
            "卡片 24 小時有效，跟上游報價脫鉤：人晚一點才核准也沒關係，送出時報價過期會自動重新報價"
            "（不超過核准金額才送，漲了卡片退回 pending、note 寫原因，要使用者重新核准）。"
            "一次報了好幾支：給 quote_ids（2–50 個）合成**一批一張卡**（回 batch id、每一件與總額、一個 approve_url），"
            "人一次核准全部；之後用 batch_id 查進度，送出還是每一件各自 submit_approved。"
            "使用者若開了自動核准（預先授權，只有他本人能開），上限內的卡一報價就是 approved（decided_by＝auto:…），"
            "直接 submit_approved；超過上限的照舊 pending、note 寫原因，要他本人核准。",
            _obj({"quote_id": {"type": "string"}, "approval_id": {"type": "string"},
                  "quote_ids": {"type": "array", "items": {"type": "string"}}, "batch_id": {"type": "string"}}),
            lambda a: (wb.approval_batch(a["quote_ids"]) if a.get("quote_ids") else
                       wb.approval_get(a.get("approval_id"), a.get("quote_id"), a.get("batch_id"))))

        add("status",
            "查一張核准卡或一支影片的進度。**排隊再久都不是失敗**：queued／processing 就繼續查，"
            "只有 failed 才是失敗（而且不會自動重抽，要重做請重新 quote）。",
            _obj({"approval_id": {"type": "string"}, "job_id": {"type": "string"}}),
            self._h_status)

        add("result",
            "取得成品：本機模式回這台電腦上的檔案路徑，網頁版回下載網址（帶同一把權杖 GET）。還沒好就回 still_processing。",
            _obj({"job_id": {"type": "string"}, "approval_id": {"type": "string"}, "export_id": {"type": "string"}}),
            self._h_result)

        add("video_quote",
            "**免費**取得一張官方確認單：解析後的參數、要花幾點、餘額夠不夠、有效期限。"
            "不建工作、不扣款。要真的送出，把回傳的 quote_id 交給 video_confirm。" + _SHOT_INPUTS_DOC,
            _obj({"model": {"type": "string"}, "prompt": {"type": "string"},
                  "seconds": {"type": "integer"},
                  "resolution": {"type": "string"},
                  "aspect_ratio": {"type": "string"},
                  "negative_prompt": {"type": "string"},
                  "generate_audio": {"type": "boolean"}, **_SHOT_INPUTS},
                 ["model", "prompt"]),
            lambda a: self._h_quote(_shot_payload(a)))

        if gate_on("lipsync_shot"):
            add("lipsync_shot",
                "**免費**替一鏡對嘴影片報價：定裝圖 keyframe（asset:// 或網址）＋配音 audio（voice_line 回的音檔）當參考，"
                "seconds 照 audio_seconds 無條件進位（不到模型下限就用下限）；配音比這個模型一鏡的上限還長就回錯、不截音"
                "（先把台詞拆短）。cast=[\"名字\"] 沒給 keyframe 時用角色卡的參考圖（換裝那張優先）。回確認單，"
                "要生成交給 video_confirm。",
                _obj({"model": {"type": "string"}, "prompt": {"type": "string"}, "keyframe": {"type": "string"},
                      "audio": {"type": "string"}, "audio_seconds": {"type": "number", "exclusiveMinimum": 0},
                      "resolution": {"type": "string"}, "aspect_ratio": {"type": "string"},
                      "cast": {"type": "array", "items": {"type": "string"}}},
                     ["model", "prompt", "audio", "audio_seconds"]),
                self._h_lipsync_shot)

        add("audio_speech_quote",
            "**免費**替一句台詞報價（配音）：回 quote_id、要花幾點、付款方。不送件、不扣款。"
            "要真的生成，把 quote_id 交給 audio_confirm（kind=tts）。報價 15 分鐘內有效。",
            _obj({"model": {"type": "string"}, "input": {"type": "string"},
                  "voice": {"type": "string"}, "speed": {"type": "number"},
                  "response_format": {"type": "string"}},
                 ["model", "input"]),
            lambda a: self._h_audio_quote(a, "tts"))

        add("audio_music_quote",
            "**免費**替一段配樂取得確認單：回 quote_id 與點數，不建工作。"
            "純配樂的 lyrics 帶 \"[Instrumental]\"。要送出交給 audio_confirm（kind=music）。",
            _obj({"model": {"type": "string"}, "lyrics": {"type": "string"},
                  "prompt": {"type": "string"}, "response_format": {"type": "string"}},
                 ["model", "lyrics"]),
            lambda a: self._h_audio_quote(a, "music"))

        add("audio_music_status", "查一段配樂的狀態。便宜、可以重複呼叫。",
            _obj({"job_id": {"type": "string"}}, ["job_id"]),
            lambda a: wb.music_status(a["job_id"]))

        add("audio_music_fetch",
            "配樂完成後取檔：studio 先存進 S3，這支再把位元組下載到本機。回路徑、大小與 sha256。",
            _obj({"job_id": {"type": "string"}, "filename": {"type": "string"}}, ["job_id"]),
            self._h_audio_fetch)

        add("post_process_status", "查一筆音軌後處理的狀態。便宜、可以重複呼叫。",
            _obj({"pp_id": {"type": "string"}}, ["pp_id"]),
            lambda a: wb.post_process_status(a["pp_id"]))

        add("post_process_wait",
            "等一筆音軌後處理，最多 %d 秒。逾時回 still_processing——"
            "那**不是失敗**，用 post_process_status 繼續查即可。" % MAX_WAIT_SECONDS,
            _obj({"pp_id": {"type": "string"},
                  "timeout_seconds": {"type": "integer", "minimum": 1,
                                      "maximum": MAX_WAIT_SECONDS}},
                 ["pp_id"]),
            self._h_pp_wait)

        add("post_process_fetch",
            "把後處理完的 mp4 寫成檔案，回檔案路徑與 sha256。"
            "**不回位元組**——那會把 agent 的上下文塞爆。"
            "（這是 post-process 那條路的取件，跟 video_fetch 不是同一支："
            "後處理的 id 是 pp_ 開頭，餵給 video_fetch 會打到影片的下載端點。）",
            _obj({"pp_id": {"type": "string"}, "filename": {"type": "string"}},
                 ["pp_id"]),
            self._h_pp_fetch)

        add("list_projects",
            "列出所有專案分組，以及每個分組裡有哪些作品。"
            "回傳的 projects 與 items 在**同一個回應**裡——"
            "拿到歸屬關係不需要再打第二次。",
            _obj({}), lambda a: wb.projects())

        add("project_create",
            "開一個新的專案分組。免費。名稱會被 strip，空白字串會被拒絕。",
            _obj({"name": {"type": "string", "minLength": 1}}, ["name"]),
            lambda a: wb.project_create(a["name"]))

        add("project_rename",
            "改專案分組（＝簡易模式的一部作品）的名稱。免費、可逆（再改回來就好）。"
            "名稱會被 strip，1–60 字；同一個帳號底下不分大小寫不能重名（重名回 409）。",
            _obj({"project_id": {"type": "string"},
                  "name": {"type": "string", "minLength": 1}}, ["project_id", "name"]),
            lambda a: wb.project_rename(a["project_id"], a["name"]))

        add("project_add_item",
            "把一件作品放進專案分組。免費、可逆（用 project_remove_item 移出）。"
            "重複加入不會出錯（那一側是 insertOrIgnore）。",
            _obj({"project_id": {"type": "string"}, "item_id": {"type": "string"}},
                 ["project_id", "item_id"]),
            lambda a: wb.project_items(a["project_id"], a["item_id"], "add"))

        add("project_remove_item",
            "把一件作品移出專案分組。**只解除歸屬，作品本身不會被刪。**"
            "免費、可逆。",
            _obj({"project_id": {"type": "string"}, "item_id": {"type": "string"}},
                 ["project_id", "item_id"]),
            lambda a: wb.project_items(a["project_id"], a["item_id"], "remove"))

        add("workbench_capabilities",
            "問這個部署做得到什麼：租戶有沒有掛上游憑證（assets_supported）、"
            "伺服器上有沒有 ffmpeg。**估價或送件回 503 時先打這一支**——"
            "assets_supported 是 false 就是這個帳號還沒開通，不是服務掛了。",
            _obj({}), self._h_capabilities)

        add("check_asset",
            "上傳前先驗一個素材網址：拿得到嗎、是什麼型別、多大。"
            "只認 http(s)、data: 與 asset://。"
            "ok 是 false 時 reason 會說為什麼。下一步是 asset_upload。",
            _obj({"url": {"type": "string"},
                  "kind": {"type": "string", "enum": ["image", "video", "audio"]}},
                 ["url"]),
            lambda a: wb.check_asset(a["url"], a.get("kind")))

        add("check_refs",
            "送件前先驗參考素材的組成：這個模型最多收幾張圖／幾段影片／幾段音訊。"
            "回 errors 非空就是會被拒，先修再 video_quote。"
            "**errors 空而 warnings 非空**代表清單裡沒有這個模型，不是它不支援——"
            "那種情況照送，真正不支援時上游才會回錯。",
            _obj({"model": {"type": "string"},
                  "input_references": {"type": "array", "items": {"type": "object"}}},
                 ["model", "input_references"]),
            lambda a: wb.check_refs(a["model"], a["input_references"]))

        add("asset_upload",
            "把素材放進素材庫，回一個 asset:// 參照，可以直接放進 "
            "video_quote 的 input_references。**不扣點數。**"
            "給 path（這台機器上的檔案，會讀進來轉成 data URI）"
            "或 url（http(s) 網址，交給平台自己抓）**二選一**。"
            "檔案有大小上限：整個請求 24MB，而 base64 會膨脹約 1/3，"
            "所以本機檔案大約 18MB 以內。"
            "給 path 時可加 direct=true 走預簽直傳（檔案直接傳到上游儲存，不轉 base64，上限 20MB）。",
            _obj({"path": {"type": "string"}, "url": {"type": "string"},
                  "name": {"type": "string"},
                  "type": {"type": "string"},
                  "tags": {"type": "array", "items": {"type": "string"}},
                  "direct": {"type": "boolean"}}),
            self._h_asset_upload)

        add("storyboard_ai_quote",
            "AI 產生分鏡的**報價**（不花錢）：把故事或一句話構想交給文字模型拆成 N 鏡（1–12），先回確認單"
            "（quote_id、payer、charge_points＝預扣上限）。要真的拆，開 --allow-spend 用 storyboard_ai。"
            "dry_run=true 只試算、不鎖單。director=true＝每鏡多給導演控制七欄（cast、style、lens、color、light、location、sound），"
            "可以直接當 video_quote 的 controls。",
            _obj({"story": {"type": "string"}, "shots": {"type": "integer", "minimum": 1, "maximum": 12},
                  "style": {"type": "string"}, "video_model": {"type": "string"},
                  "project_id": {"type": "string"}, "dry_run": {"type": "boolean"},
                  "director": {"type": "boolean"}}, ["story"]),
            lambda a: wb.storyboard_ai_quote(a["story"], a.get("shots", 6), a.get("style"), a.get("video_model"),
                                             a.get("project_id"), dry_run=bool(a.get("dry_run")),
                                             director=a.get("director") is True))

        add("model_caps",
            "模型能力表（實測過的才算）：哪個模型真的吃首幀、尾幀、參考圖，各家吃哪個欄位、首幀時鏡頭會不會漂移、"
            "證據（job id、接縫 SSIM）與日期。報價收下參數不代表上游會吃。給 model 只回那一列。不花錢、不打伺服器。",
            _obj({"model": {"type": "string"}}),
            lambda a: ({"model": a["model"], **{k: (model_caps.caps(a["model"]).get(k) or {"status": "untested"})
                                                 for k in model_caps.KINDS}} if a.get("model") else
                       {"models": model_caps.table()}))

        add("parse_shots",
            "把一整段分鏡腳本切成一顆一顆鏡頭。**純字串處理，不叫 AI、不花錢。**"
            "每顆會回 prompt 與 seconds，那兩個直接就是 video_quote 的參數。"
            "⚠ **seconds 只有在那一顆自己寫了時間範圍時才有值**"
            "（例如「鏡頭1 00:00-00:05」），沒寫的話是 null——"
            "那時候不要把 null 送給 video_quote，讓平台自己決定長度。"
            "帶 model 的話 seconds 會先對齊那個模型收得下的長度，"
            "被調整過時 adjust_note 會說明。"
            "沒有腳本只有故事：給 story（一段話），伺服器先照句子拆成「鏡頭 N」（每句或幾句一鏡、最多約 6 鏡）再切，"
            "跟工作台主線「依照故事拆」一樣；要 AI 拆用 storyboard_ai_quote。text 與 story 給一個。",
            _obj({"text": {"type": "string"}, "model": {"type": "string"}, "story": {"type": "string"}}),
            lambda a: _parse_shots(wb, a))

        add("build_captions",
            "把每顆鏡頭的台詞組成 SRT 或 VTT，回在 body 欄位。"
            "**純字串組裝，不叫 ASR、不花錢**（名字聽起來像會，實際不會）。"
            "cues 兩種寫法：{text, seconds} 依序接龍，或 {text, start, end} 絕對時間。",
            _obj({"cues": {"type": "array", "items": {"type": "object"}},
                  "format": {"type": "string", "enum": ["srt", "vtt"]}},
                 ["cues"]),
            lambda a: wb.captions(a["cues"], a.get("format", "srt")))

        add("store_get",
            "讀工作台的 KV。沒存過回 {\"value\": null}，**那不是錯誤**。"
            "工作台自己在用的鍵讀得到而且很有用："
            "shots（人排好的分鏡）、jobs（作品清單）、characters（角色卡）、"
            "presets（參數組）、canvas（畫布與剪輯軌）。",
            _obj({"key": {"type": "string"}}, ["key"]),
            lambda a: wb.store_get(a["key"]))

        add("store_put",
            "寫工作台的 KV。**沒有版本、沒有 undo，同名就是覆蓋。**"
            "工作台自己在用的那五個鍵（%s）預設寫不進去——"
            "覆蓋它們會在使用者的畫面上把東西換掉而他不會收到通知。"
            "真的要覆蓋請開 --allow-delete。"
            % "、".join(UI_OWNED_STORE_KEYS),
            _obj({"key": {"type": "string"}, "value": {}}, ["key", "value"]),
            self._h_store_put)

        add("wallet_subscription",
            "月度訂閱的狀態與方案：這個部署有沒有開訂閱（configured）、"
            "每期給多少點（points_per_period）、方案名稱，以及使用者目前的訂閱。"
            "**`active` 這個布林值是服務端算好的，直接用它**——不要自己比對 "
            "status 字串：Stripe 的狀態不只 active／canceled，還有 trialing／"
            "past_due／incomplete，兩邊各自判會分岔。沒訂過時 subscription 是 null。",
            _obj({}), lambda a: wb.wallet_subscription())

        add("payer_state",
            "這個帳號能用哪些付款方：own_key（創作者自己的 AppleToken 金鑰，"
            "扣他自己的 AppleToken 額度）與 points（本站點數）。回自帶金鑰的末四碼"
            "與預設付款方，**永遠不含金鑰明文**。報價時可以在 payload 帶 payer 指定；"
            "確認那一趟沿用報價時鎖定的付款方，不能更改。",
            _obj({}), lambda a: wb.payer_state())

        add("wallet_balance",
            "查**這個站自己的錢包**：使用者付錢給 studio 的餘額。"
            "金額是**字串**（後端是 NUMERIC(18,6)，轉成 JSON 數字會失真），"
            "而且一定要跟著回傳的 currency 一起解讀。"
            "⚠ 跟 get_balance **不是同一筆錢**：那一支是 AppleToken 帳戶的**點數**，"
            "這一支是使用者儲值進來的**錢**。四個欄位名一模一樣，不要相減。"
            "503＝這個部署沒開儲值，409＝這個帳號在本站還沒有身分，兩者都不是故障。",
            _obj({}), lambda a: wb.wallet_balance())

        add("wallet_history",
            "本站錢包的異動明細（加值與消耗合在一條時間軸，新到舊）。"
            "kind 是 grant（加值）或 usage（消耗），amount 是字串、消耗是負數。"
            "points 是同一筆換算成本站點數的字串（跟餘額同一條換算），沒設換算率時是 null。"
            "⚠ 跟 list_usage 不是同一份帳：那一支是 gateway 的扣點明細，"
            "這一支是本站帳本，兩邊的數字不會相等也不該相減。"
            "limit 超過 500 不會出錯，會被**靜默夾**成 500。",
            _obj({"limit": {"type": "integer", "minimum": 1}}),
            lambda a: wb.wallet_history(a.get("limit")))

        add("wallet_options",
            "查儲值方案：幣別、快捷金額、單筆上下限。"
            "**上下限是這個部署設的環境變數，不是固定值**——"
            "要儲值就得先問這一支，不能把金額範圍寫死。"
            "不是 200 就代表這個部署沒開儲值（前端也是這樣 fail closed 的）。"
            "⚠ 那種部署上這三支 wallet 工具**每一次都要等約 12 秒才失敗**："
            "503 在 client 這一層是可重試的狀態，會退避三次。"
            "而 wallet 的 503 只有一個來源（部署沒設定），重試一定得到同樣的答案——"
            "所以先打這一支，不是 200 就別再打另外兩支了。",
            _obj({}), lambda a: wb.wallet_options())

        add("youtube_status",
            "查 YouTube 連結狀態：有沒有連、頻道名、能不能用播放清單（can_playlists）。"
            "沒連的話請導演在工作台「上架 YouTube」按「連結 YouTube」。",
            _obj({}), lambda a: wb.youtube_status())
        add("youtube_uploads",
            "查上傳佇列：不給 id 回最近 50 件（可用 project_id 篩）；給 id 回那一件。"
            "state：awaiting（自動上架在等匯出完成）／queued／uploading／done（url 是影片連結）／failed／cancelled；"
            "waiting=quota 表示 YouTube 今日配額用完，next_attempt_at（太平洋時間午夜後）會自動續傳。",
            _obj({"id": {"type": "string"}, "project_id": {"type": "string"}}),
            lambda a: wb.youtube_uploads(a.get("id"), a.get("project_id")))
        add("youtube_cancel", "取消一件還沒傳完的上傳（awaiting／queued／uploading）。",
            _obj({"id": {"type": "string"}}, ["id"]), lambda a: wb.youtube_cancel(a["id"]))
        add("youtube_playlists", "列出導演頻道的播放清單（要先在工作台授權播放清單）。",
            _obj({}), lambda a: wb.youtube_playlists())
        add("youtube_auto_get",
            "查專案的自動上架設定（預設關）。開著時，這個專案的匯出一完成就自動排入上傳；單鏡生成不觸發。",
            _obj({"project_id": {"type": "string"}}, ["project_id"]),
            lambda a: wb.youtube_auto(a["project_id"]))

        _eps = {"type": "array", "items": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["export", "video"]}, "ref": {"type": "string"}},
            "required": ["kind", "ref"]}}
        add("pitch_platforms",
            "各短劇／影音平台的投稿規格（單集長度、集數、比例）與出處；官方查不到的照實標「無法判定」。",
            _obj({}), lambda a: wb.pitch_platforms())
        add("pitch_preview",
            "投稿包預覽（不打包）：每集長度、寬高、比例、有沒有字幕，各平台規格檢查表，以及從生成紀錄帶出的"
            " AI 使用說明。episodes 依集數排序：kind=export（ref=exp_…，匯出成品）或 video（ref=上游 job id，成片存檔）。",
            _obj({"episodes": _eps, "cover_asset": {"type": "string"}}, ["episodes"]),
            lambda a: wb.pitch_preview(a["episodes"], a.get("cover_asset")))
        add("pitch_packages",
            "查投稿包：不給 id 回最近 30 件；給 id 回那一件（state queued／building／done／failed，"
            "done 時有 checks、ai_usage、files）。",
            _obj({"id": {"type": "string"}}), lambda a: wb.pitch_packages(a.get("id")))
        add("pitch_download", "打好的投稿包 zip → 15 分鐘的下載網址（給導演本人）。",
            _obj({"id": {"type": "string"}}, ["id"]), lambda a: wb.pitch_download(a["id"]))

        if self.allow_spend:
            if gate_on("voice_line"):
                add("voice_line",
                    "替一句台詞配音（報價＋送出一次做完），回 {audio, seconds}——seconds 給 lipsync_shot 的 audio_seconds。"
                    "**會花錢**：本站點數件報價要在 max_points 以內才送；自帶金鑰件扣自己的 AppleToken 額度。"
                    "桌面本機要人核准時回核准卡（quote_id、approval，不是失敗、不要重送），核准後用 submit_approved(approval_id=approval.id) 送出。"
                    "cast=true＋speaker：沒給 voice 時用角色卡的 voice（伺服器 STUDIO_CAST_REFS=blocks 才套）。"
                    "**model 必填**，要寫供應商（provider/name）：沒寫供應商的名稱伺服器會補成 gmi/，那一家目前不能配音，"
                    "送之前就擋（看補完之後實際送出的名稱），錯誤訊息會附一個目錄裡可用的模型。",
                    _obj({"model": {"type": "string"}, "text": {"type": "string"}, "voice": {"type": "string"},
                          "speed": {"type": "number"}, "speaker": {"type": "string"}, "cast": {"type": "boolean"},
                          "max_points": {"type": "number", "exclusiveMinimum": 0}},
                         ["model", "text"]),
                    self._h_voice_line, spends=True)
            if gate_on("dub_lipsync_shot"):
                add("dub_lipsync_shot",
                    "先配音、再替對嘴影片報價，一次做完：text 用 tts_model 配音（要 mp3，**會花錢**，同 voice_line 的規則與"
                    " max_points）→ 音檔上傳成 asset:// → 秒數照配音長度無條件進位 → 定裝圖 keyframe＋這段配音當參考報價"
                    "（免費）。回 {stage, audio_ref, seconds, quote}；stage=quoted 時把 quote 交給 video_confirm 生成。"
                    "其他 stage 都沒有報影片價：voice_pending（桌面本機配音要人核准：核准後 submit_approved 會回 audio，"
                    "再呼叫一次並帶 audio＝那個 audio.url，不會重配）、upload_failed／need_seconds／too_long"
                    "（配音已經做好、交回 audio 或 audio_ref，帶回來續跑就好，不要重配）。"
                    "已經有配音時帶 audio（asset://、網址或 /api/audio/content?sha=）與 audio_seconds，就不再配音。"
                    "cast=true＋speaker：沒給 voice 用角色卡的 voice、沒給 keyframe 用角色卡的參考圖（STUDIO_CAST_REFS=blocks 才套）。",
                    _obj({"model": {"type": "string"}, "prompt": {"type": "string"}, "keyframe": {"type": "string"},
                          "tts_model": {"type": "string"}, "text": {"type": "string"}, "voice": {"type": "string"},
                          "speed": {"type": "number"}, "speaker": {"type": "string"}, "cast": {"type": "boolean"},
                          "max_points": {"type": "number", "exclusiveMinimum": 0},
                          "audio": {"type": "string"}, "audio_seconds": {"type": "number", "exclusiveMinimum": 0},
                          "resolution": {"type": "string"}, "aspect_ratio": {"type": "string"}},
                         ["model", "prompt"]),
                    self._h_dub_lipsync_shot, spends=True)
            add("pitch_create",
                "建立投稿包（背景打包成 zip：分集 mp4、字幕、封面、作品資料、AI 使用說明、授權聲明、規格檢查表）。"
                "聲明要導演本人確認：likeness=none（沒有可辨識的真人肖像）或 consented（已取得書面同意，"
                "要寫 likeness_note）；materials_ok 與 ai_disclosure_ok 必須是 true；signer 是聲明人。"
                "language 用語言代碼（zh-Hant、ja、en）。AI 使用說明由伺服器從紀錄帶出，不用填。用 pitch_packages 查進度。",
                _obj({"title": {"type": "string"}, "episodes": _eps, "language": {"type": "string"},
                      "synopsis": {"type": "string"}, "genres": {"type": "array", "items": {"type": "string"}},
                      "cover_asset": {"type": "string"}, "project_id": {"type": "string"},
                      "likeness": {"type": "string", "enum": ["none", "consented"]},
                      "likeness_note": {"type": "string"}, "materials_ok": {"type": "boolean"},
                      "materials_note": {"type": "string"}, "ai_disclosure_ok": {"type": "boolean"},
                      "signer": {"type": "string"}},
                     ["title", "episodes", "language", "likeness", "materials_ok", "ai_disclosure_ok", "signer"]),
                lambda a: wb.pitch_create(a["title"], a["episodes"], a["language"], a["likeness"], a["signer"],
                                          a["materials_ok"], a["ai_disclosure_ok"], a.get("synopsis") or "",
                                          a.get("genres"), a.get("cover_asset"), a.get("project_id"),
                                          a.get("likeness_note") or "", a.get("materials_note") or ""))
            add("youtube_upload",
                "把成片（kind=video，ref=上游 job id）或匯出成品（kind=export，ref=exp_…）上傳到導演自己的 YouTube。"
                "**對外發布**：privacy 預設 private；public／scheduled（要給 publish_at，ISO 8601 含時區、15 分鐘以後）"
                "請先跟導演確認。synthetic（AI 揭露 containsSyntheticMedia）預設 true。回那一件，用 youtube_uploads 查進度。",
                _obj({"kind": {"type": "string", "enum": ["video", "export"]}, "ref": {"type": "string"},
                      "title": {"type": "string"}, "description": {"type": "string"},
                      "tags": {"type": "array", "items": {"type": "string"}},
                      "privacy": {"type": "string", "enum": ["private", "unlisted", "public", "scheduled"]},
                      "publish_at": {"type": "string"}, "playlist_id": {"type": "string"},
                      "synthetic": {"type": "boolean"}, "made_for_kids": {"type": "boolean"},
                      "thumbnail_asset": {"type": "string"}}, ["kind", "ref", "title"]),
                lambda a: wb.youtube_upload(a["kind"], a["ref"], a["title"], a.get("description") or "",
                                            a.get("tags"), a.get("privacy") or "private", a.get("publish_at"),
                                            a.get("playlist_id"), a.get("synthetic", True),
                                            a.get("made_for_kids", False), a.get("thumbnail_asset")))
            add("youtube_retry", "重試一件失敗的上傳。",
                _obj({"id": {"type": "string"}}, ["id"]), lambda a: wb.youtube_retry(a["id"]))
            add("youtube_playlist_create", "在導演頻道建一個播放清單（多集用）。",
                _obj({"title": {"type": "string"},
                      "privacy": {"type": "string", "enum": ["private", "unlisted", "public"]}}, ["title"]),
                lambda a: wb.youtube_playlist_create(a["title"], a.get("privacy") or "private"))
            add("youtube_auto_set",
                "開關專案的自動上架（匯出完成即上傳）。privacy 預設 private；public／scheduled 要 confirm_public=true，"
                "**先問過導演**。scheduled 用 schedule_delay_hours（匯出完成後幾小時公開）。"
                "標題／說明範本可用 {project} {episode} {title} {date}。",
                _obj({"project_id": {"type": "string"}, "enabled": {"type": "boolean"},
                      "privacy": {"type": "string", "enum": ["private", "unlisted", "public", "scheduled"]},
                      "schedule_delay_hours": {"type": "integer", "minimum": 1, "maximum": 720},
                      "confirm_public": {"type": "boolean"}, "playlist_id": {"type": "string"},
                      "synthetic": {"type": "boolean"}, "made_for_kids": {"type": "boolean"},
                      "title_template": {"type": "string"}, "description_template": {"type": "string"},
                      "tags": {"type": "array", "items": {"type": "string"}}}, ["project_id", "enabled"]),
                lambda a: wb.youtube_auto_set(
                    a["project_id"], a["enabled"], a.get("privacy") or "private", a.get("schedule_delay_hours"),
                    a.get("confirm_public", False), a.get("playlist_id"), a.get("synthetic", True),
                    a.get("made_for_kids", False), a.get("title_template"), a.get("description_template"),
                    a.get("tags")))
            add("video_qc",
                "驗一支影片：給 1–4 格畫面（data:image/jpeg;base64,…，同一支影片依時間取）與預期角色，"
                "回 verdict（subjects_ok、colors_ok、defects、overall 1–10）與建議評分。**會花錢**："
                "付款方跟那一支影片一樣，本站點數件照實收扣點（每支約 0.3 點），自帶金鑰件扣自己的 AppleToken 額度。"
                "同一支、同樣畫面重送回同一筆結果，不重扣。"
                "作品是允許切鏡頭的（迷因範本 fields.allow_cuts=true）才帶 allow_cuts=true：切鏡頭不算瑕疵；預設不帶。"
                "桌面本機可以不帶 frames，由本機取 15%／50%／90% 三格；網頁版一定要帶。"
                "要數動物就帶 count（英文物種 → 預期幾隻，例如 {\"dog\": 1, \"cat\": 1}）：數量不對或多了別的動物，"
                "verdict.count_ok=false 並算不合格（實測案例：畫面裡多出一隻同樣的角色）。",
                _obj({"job_id": {"type": "string"},
                      "frames": {"type": "array", "items": {"type": "string"}},
                      "expect": {"type": "array", "items": {"type": "object"}},
                      "allow_cuts": {"type": "boolean"},
                      "count": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0, "maximum": 9}}},
                     ["job_id"]),
                lambda a: wb.qc(a["job_id"], a.get("frames"), a.get("expect"), a.get("allow_cuts") is True, a.get("count")),
                spends=True)

            add("qc_rate",
                "把一支影片的評分寫回 AppleToken（/v2/ratings；同一件重評會覆蓋）。score 1–5；"
                "tags 例：accurate、character_mismatch、artifacts。評分本身不花錢，金鑰由伺服器照那一件的付款方決定。",
                _obj({"job_id": {"type": "string"}, "score": {"type": "integer"},
                      "tags": {"type": "array", "items": {"type": "string"}}, "comment": {"type": "string"}},
                     ["job_id", "score"]),
                lambda a: wb.qc_rate(a["job_id"], a["score"], a.get("tags"), a.get("comment")), spends=True)

            add("submit_approved",
                "送出一張**使用者已經核准**的核准卡（quote 建的那張）。**這一步會扣款。**"
                "只收 approved 的卡；卡片只能送一次；帶 expect_amount 時金額要跟卡片一致，對不上就拒絕。"
                "報價過期會先自動重新報價（付款方不變）；漲價就不送、回 repriced，卡片退回 pending 等使用者重新核准。"
                "被拒或失敗都**不要自動重試**：重做請重新 quote、讓使用者再核准一次。",
                _obj({"approval_id": {"type": "string"}, "expect_amount": {"type": "string"}}, ["approval_id"]),
                lambda a: _submit_approved(wb, a), spends=True)

            add("video_confirm",
                "把一張確認單正式送出。**這一步會扣款。**"
                "只收 quote_id——生成參數在確認單裡已經定死了。",
                _obj({"quote_id": {"type": "string"}}, ["quote_id"]),
                self._h_confirm, spends=True)

            add("image_generate",
                "生成圖片。**送出即扣款，沒有兩階段。**"
                "必須帶 max_points 作為你願意付的上限。",
                _obj({"model": {"type": "string"}, "prompt": {"type": "string"},
                      "size": {"type": "string"},
                      "n": {"type": "integer", "minimum": 1},
                      "max_points": {"type": "number", "exclusiveMinimum": 0}},
                     ["model", "prompt", "max_points"]),
                self._h_image, spends=True)

            add("image_outpaint",
                "改比例只外擴兩邊：把一張圖（asset://ast_… 或 PNG／JPEG data URI）補成 9:16 或 16:9，"
                "只補兩側、中間原圖一個像素不變，產出一份新素材（回 reference 與原圖 from）。"
                "**送出即扣款，沒有兩階段。** 必須帶 max_points 作為你願意付的上限（先估價，超過就不送）。",
                _obj({"source": {"type": "string"},
                      "aspect": {"type": "string", "enum": ["9:16", "16:9"]},
                      "prompt": {"type": "string"},
                      "max_points": {"type": "number", "exclusiveMinimum": 0}},
                     ["source", "aspect", "max_points"]),
                self._h_outpaint, spends=True)

            add("storyboard_ai",
                "用 AI 把故事拆成 N 鏡（1–12），回 shots[{prompt, seconds, shot_size, camera}]。**會花錢**："
                "本站點數件先依上限預扣、完成照實際用量結算（6 鏡約 0.3 點），失敗或輸出不合法全額退回；"
                "自帶金鑰件扣自己的 AppleToken 額度。必須帶 max_points。",
                _obj({"story": {"type": "string"}, "shots": {"type": "integer", "minimum": 1, "maximum": 12},
                      "style": {"type": "string"}, "video_model": {"type": "string"},
                      "project_id": {"type": "string"}, "director": {"type": "boolean"},
                      "max_points": {"type": "number", "exclusiveMinimum": 0}},
                     ["story", "max_points"]),
                self._h_storyboard_ai, spends=True)

            add("shots_confirm",
                "把 storyboard_quote 的確認單**逐張**送出（每一張都是一次 video_confirm）。**這一步會扣款。**"
                "只收 quote_id 清單；確認模式下每一張都會變成待人核准。回每一張的結果，失敗的不重送。",
                _obj({"quote_ids": {"type": "array", "minItems": 1, "maxItems": 12,
                                    "items": {"type": "string"}}}, ["quote_ids"]),
                self._h_shots_confirm, spends=True)

            add("character_angles",
                "角色多角度參考圖：每一個角度各自一次 image_generate（文生圖，只靠提示詞描述同一個角色，"
                "不拿前一張當參考，所以長相不保證一致，生好要自己看過）。沒帶 angles 預設 front、side、back、three-quarter"
                "（正面／側面／背面／四分之三）；另外可選 close-up、full-body。"
                + ("桌面本機：不估價、不扣本站點數，每一張只建一張核准卡（回 quote_id 與 approval，不是失敗、不要重送），"
                   "人核准或預先授權之後用 submit_approved(approval_id=approval.id) 送出；錢由核准卡的上限把關。"
                   "max_points_each 仍然必填，但本機不拿它擋。"
                   if self.local else
                   "**會扣款**，每一張都要在 max_points_each 以內（先估價，超過就不送）：某一張超過就停在那一張，"
                   "後面的角度不送、也不會出現在回傳裡；其他錯誤記在那一張、繼續下一張。開了確認模式時那一張回 pending_id（待人核准）。")
                + "這支只回每個角度的圖片網址（urls），不存角色庫、也不放進素材庫。要當 video_quote／quote 的 input_references，"
                "先用 asset_upload 拿 asset://（[{type: image, url: asset://ast_…, role: reference_image}]）；"
                "要給送件時的 cast=true 用，另外把它寫進角色庫。",
                _obj({"model": {"type": "string"}, "name": {"type": "string"},
                      "description": {"type": "string"},
                      "angles": {"type": "array", "minItems": 1, "maxItems": 6,
                                 "items": {"type": "string", "enum": ["front", "side", "back", "three-quarter",
                                                                      "close-up", "full-body"]}},
                      "size": {"type": "string"},
                      "max_points_each": {"type": "number", "exclusiveMinimum": 0}},
                     ["model", "name", "description", "max_points_each"]),
                self._h_character_angles, spends=True)

            add("audio_confirm",
                "把配音（kind=tts）或配樂（kind=music）的報價正式送出。**這一步會扣款。**"
                "只收 quote_id——參數在報價時已經定死了。",
                _obj({"quote_id": {"type": "string"},
                      "kind": {"type": "string", "enum": ["tts", "music"]}},
                     ["quote_id", "kind"]),
                self._h_audio_confirm, spends=True)

            add("post_process",
                "對一支已完成的影片套用音軌風格。必須帶 max_points。",
                _obj({"job_id": {"type": "string"},
                      "audio_style": {"type": "string",
                                      "enum": list(AUDIO_STYLES)},
                      "intensity": {"type": "integer", "minimum": 1,
                                    "maximum": 5},
                      "max_points": {"type": "number", "exclusiveMinimum": 0}},
                     ["job_id", "audio_style", "max_points"]),
                self._h_post_process, spends=True)

        if self.allow_delete:
            add("project_delete",
                "刪掉一個專案分組。**分組沒了，但裡面的作品都還在**——"
                "這一支不會刪任何成品，也不是清理成品的手段。"
                "刪掉之後救不回來：要復原得重新建立並逐件加回去。",
                _obj({"project_id": {"type": "string"}}, ["project_id"]),
                lambda a: wb.project_delete(a["project_id"]))

            add("asset_delete",
                "把一個素材從素材庫刪掉。**救不回來。**"
                "⚠ 它可能正被別的作品當參考素材引用——這一支不會檢查，"
                "也沒有任何東西會告訴你哪些作品用到它。"
                "先用 list_assets 看清楚再刪。",
                _obj({"asset_id": {"type": "string"}}, ["asset_id"]),
                lambda a: wb.asset_delete(a["asset_id"]))

            add("store_delete",
                "刪掉一個 KV 的鍵。**救不回來。**"
                "鍵本來就不存在也回 ok（deleted 會是 false）——"
                "那不是錯誤，「本來就沒有」跟「刪掉了」對呼叫端是同一件事。"
                "工作台自己在用的鍵（%s）刪掉會讓使用者的分鏡／角色卡／畫布"
                "在下次重整時消失。"
                % "、".join(UI_OWNED_STORE_KEYS),
                _obj({"key": {"type": "string"}}, ["key"]),
                lambda a: wb.store_delete(a["key"]))

        if self.allow_logout:
            add("session_logout",
                "結束登入。**這會結束這顆 session 本身，不只是這個工具的連線。**"
                "按下去之後：這個 server 接下來每一支工具都會 401（還沒取件的"
                "影片也拿不回來了）；這顆 session 若是從瀏覽器複製來的，那個工作台"
                "分頁也會一起被登出。"
                "只有在「借用的帳號用完要還」這種情況下才用它，"
                "而且要放在所有取件動作**之後**。",
                _obj({}), lambda a: wb.logout())

        if self.allow_topup:
            add("wallet_topup_intent",
                "建立一張 Stripe 付款頁，回 checkout_url。"
                "**這一趟不會扣任何卡**——卡號不經過這個網域，"
                "要有人用瀏覽器打開那個網址、自己輸入付款資訊，錢才會動。"
                "但它**確實在外部產生了東西**：一個真的 Stripe checkout session "
                "與一列 payments，所以它不是唯讀的。"
                "金額的合法範圍是這個部署設的，**先用 wallet_options 問**，不要寫死。"
                "入帳靠 webhook，可能比付完款晚幾秒——付完之後用 wallet_balance 確認。",
                _obj({"amount": {"type": ["number", "string"]}}, ["amount"]),
                lambda a: wb.wallet_intent(a["amount"]))

            add("wallet_subscribe",
                "建立一張**月度訂閱**的 Stripe 付款頁，回 checkout_url。"
                "跟 wallet_topup_intent 同一道閘、同一個性質（這一趟不扣卡，"
                "但確實在外部建立了一個真的 Stripe session）。"
                "**差別是後果更重：付款完成之後每個月會自動扣款**，直到使用者"
                "自己取消——一次性儲值不會。所以要按之前先用 wallet_subscription "
                "確認他還沒有訂閱，並且讓使用者知道這是週期性扣款。"
                "已經在訂閱中時服務端回 409，不會建出第二張單。",
                _obj({}), lambda a: wb.wallet_subscribe())

        add("agent_pending_status",
            "查一張待確認（確認模式下花錢的請求）的狀態：pending／approved／rejected／expired／failed，"
            "approved 時 result 裡就是送件的結果（job id 等）。人在工作台按核准之前一直是 pending。",
            _obj({"pending_id": {"type": "string"}}, ["pending_id"]),
            lambda a: wb.agent_pending(a["pending_id"]))
        add("timeline_place",
            "請開著的工作台把幾支作品放進下排剪輯軌（照順序接在最後）。"
            "工作台沒開時會等到下次打開才放。回這一筆動態的 id。",
            _obj({"job_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 50}},
                 ["job_ids"]),
            lambda a: wb.agent_activity("timeline_place", ref=a["job_ids"][0], action="place",
                                        args={"job_ids": a["job_ids"]},
                                        note="放進剪輯軌：%d 支" % len(a["job_ids"])))
        add("timeline_trim",
            "請工作台裁切剪輯軌上某一支的入點／出點（秒）。只改剪輯軌，不動原片。",
            _obj({"job_id": {"type": "string"}, "in_seconds": {"type": "number", "minimum": 0},
                  "out_seconds": {"type": "number", "minimum": 0}}, ["job_id"]),
            lambda a: wb.agent_activity("timeline_trim", ref=a["job_id"], action="trim",
                                        args={k: a[k] for k in ("job_id", "in_seconds", "out_seconds") if k in a},
                                        note="裁切 %s" % a["job_id"]))
        add("export_status",
            "查一次匯出的狀態（export_id＝exp_…）：state 是 staging／processing／done／failed，done 時有長度與大小。免費。",
            _obj({"export_id": {"type": "string"}}, ["export_id"]),
            lambda a: wb.export_status(a["export_id"]))
        add("export_download",
            "拿匯出好的成片下載網址（export_id＝exp_…）：回 {url, srt_url?, expires_in}，預簽網址 15 分鐘內有效；"
            "還沒匯出完成回 409。免費。",
            _obj({"export_id": {"type": "string"}}, ["export_id"]),
            lambda a: wb.export_download(a["export_id"]))
        add("shot_edit",
            "精準改作品分鏡的一鏡（prompt 或 seconds），**不整份覆蓋**。先用 work_get 讀分鏡，把讀到的這一鏡 prompt 原樣放進 expect；"
            "這一鏡在你讀過之後被人或別的 Agent 改過就回 409 conflict（current 是它現在的樣子），什麼都不寫——照 current 重新決定再改。"
            "shot＝1 起算的第幾鏡或 sid。免費。",
            _obj({"project_id": {"type": "string"}, "shot": {"type": ["integer", "string"]}, "expect": {"type": "string"},
                  "prompt": {"type": "string"}, "seconds": {"type": ["number", "null"]}}, ["project_id", "shot", "expect"]),
            lambda a: _shot_conflict(lambda: wb.shot_edit(a["project_id"], a["shot"], a["expect"], a.get("prompt"), a.get("seconds"),
                                                         set_seconds="seconds" in a)))
        add("shot_move",
            "把作品分鏡的一鏡搬到第 to 鏡（1 起算），**不整份覆蓋**。expect_order＝你用 work_get 讀到的每一鏡 sid（照順序）；"
            "順序在你讀過之後變了就回 409 conflict（current.order 是現在的順序），什麼都不搬。免費。",
            _obj({"project_id": {"type": "string"}, "shot": {"type": ["integer", "string"]}, "to": {"type": "integer", "minimum": 1},
                  "expect_order": {"type": "array", "items": {"type": "string"}}}, ["project_id", "shot", "to", "expect_order"]),
            lambda a: _shot_conflict(lambda: wb.shot_move(a["project_id"], a["shot"], a["to"], a["expect_order"])))
        add("export_request",
            "請導演匯出剪輯軌成 mp4。**Agent 不直接送匯出**：工作台會打開匯出面板、列出授權警告"
            "（第三方素材、沒標可商用的），由人看過再按送出（r2-13）。回這一筆動態的 id。",
            _obj({"title": {"type": "string"}}),
            lambda a: wb.agent_activity("export_request", action="export",
                                        args={"title": a.get("title") or ""},
                                        note="請導演匯出：%s" % (a.get("title") or "剪輯軌")))
        add("director_plan",
            "**先呼叫這一支**：回導演工作流的步驟、每一步用哪支工具，以及工作台現在的狀態"
            "（分鏡草稿、角色卡、剪輯軌有幾段）。唯讀、免費。",
            _obj({}), self._h_director_plan)
        add("storyboard_quote",
            "**免費**替整份分鏡逐鏡報價（每一鏡一張確認單、鎖定付款方）：給 shots=[{prompt, seconds?, model?}]，"
            "回每一鏡的 quote_id 與點數，以及合計。不建工作、不扣款。"
            "把合計告訴使用者，再交給 shots_confirm。最多 12 鏡。",
            _obj({"model": {"type": "string"},
                  "shots": {"type": "array", "minItems": 1, "maxItems": 12, "items": _obj(
                      {"prompt": {"type": "string"}, "seconds": {"type": "integer"},
                       "model": {"type": "string"}, "resolution": {"type": "string"},
                       "aspect_ratio": {"type": "string"}}, ["prompt"])},
                  "resolution": {"type": "string"}, "aspect_ratio": {"type": "string"}},
                 ["model", "shots"]),
            self._h_storyboard_quote)
        add("estimate",
            "**免費**估價（不鎖付款方、不建確認單）：給一組生成參數，回點數與秒數。"
            "要送件仍然要 video_quote → video_confirm。",
            _obj({"model": {"type": "string"}, "prompt": {"type": "string"},
                  "seconds": {"type": "integer"}, "resolution": {"type": "string"},
                  "size": {"type": "string"}, "n": {"type": "integer"}}, ["model"]),
            lambda a: wb.estimate(dict(a)))
        if self.local:
            self._add_dirctl_tools(add)
        return tools

    def _h_capabilities(self, a):
        out = {}
        try:
            out["assets_supported"] = bool(self.wb.assets_support().get("supported"))
        except Exception as e:
            out["assets_supported"] = None
            out["assets_error"] = str(e)
        try:
            out["ffmpeg_on_server"] = bool(self.wb.ffmpeg().get("available"))
        except Exception as e:
            out["ffmpeg_on_server"] = None
            out["ffmpeg_error"] = str(e)
        if out.get("assets_supported") is False:
            out["hint"] = ("assets_supported 是 false：這個部署沒有接上 gateway"
                           "（或沒啟用每租戶憑證），是平台端的設定，不是你的描述或帳號設定造成的。"
                           "估價與送件走同一個 gateway，多半也不能用——請聯絡我們。")
        if out.get("ffmpeg_on_server"):
            out["ffmpeg_note"] = ("伺服器上有 ffmpeg，但**合併影片這件事仍然做不到**："
                                  "/api/concat 回 501，合併邏輯不在這個部署裡。"
                                  "這一欄現在唯一的意思是「那支執行檔存在」。")
        return out

    def _h_asset_upload(self, a):
        path, url = a.get("path"), a.get("url")
        if bool(path) == bool(url):
            return {"error": "asset_upload 要給 path 或 url **其中一個**："
                             "path 是這台機器上的檔案，url 是讓平台自己去抓的網址。"
                             "%s" % ("兩個都給了，我不會替你挑。" if path
                                     else "一個都沒給。")}
        if url:
            return self.wb.asset_upload(url, name=a.get("name"), type=a.get("type"), tags=a.get("tags"))
        f = Path(path)
        if not f.is_file():
            return {"error": "讀不到檔案：%s（要的是這台機器上的路徑，"
                             "不是工作台裡的素材 id）" % path}
        blob = f.read_bytes()
        mime = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        if a.get("direct"):
            return self.wb.asset_upload_direct(blob, mime, name=a.get("name") or f.name, tags=a.get("tags"))
        source = "data:%s;base64,%s" % (mime, base64.b64encode(blob).decode())
        return self.wb.asset_upload(source, name=a.get("name") or f.name,
                                    type=a.get("type"), tags=a.get("tags"))

    def _h_store_put(self, a):
        key = a["key"]
        if ui_owned_key(key) and not self.allow_delete:
            return {"error": "`%s` 是工作台前端自己在用的鍵，覆蓋它會直接改掉"
                             "使用者畫面上的東西（分鏡／角色卡／作品清單／參數組／"
                             "畫布），而且沒有版本可以退回去。"
                             "⚠ 更糟的一種：即使開了閘寫進去了，**多數情況下它會"
                             "靜默消失**——工作台的 saveAll() 是 900ms debounce 而"
                             "/api/store 是整包覆寫不是合併，所以使用者只要拖曳"
                             "任何一個節點，你寫的整包就被蓋回去，而且沒有任何訊號。"
                             "（2026-09-11 由工作台那條線獨立驗過。）"
                             "要覆蓋請開 --allow-delete。**沒有寫進去任何東西。**"
                             "（工作台自己在用的鍵：%s）"
                             % (key, "、".join(UI_OWNED_STORE_KEYS))}
        return self.wb.store_put(key, a["value"])

    def _h_wait(self, a):
        t = min(int(a.get("timeout_seconds") or MAX_WAIT_SECONDS), MAX_WAIT_SECONDS)
        r = poll_video(self.wb, a["job_id"], timeout=t)
        if r.timed_out:
            return {"status": "still_processing", "job_id": a["job_id"],
                    "hint": STILL_RUNNING_HINT}
        return r.data

    def _h_pp_wait(self, a):
        t = min(int(a.get("timeout_seconds") or MAX_WAIT_SECONDS), MAX_WAIT_SECONDS)
        tries = max(1, min(PP_POLL_MAX_TRIES, int(t / PP_POLL_SLOW) + 1))
        r = poll_post_process(self.wb, a["pp_id"], max_tries=tries)
        if r.timed_out:
            return {"status": "still_processing", "pp_id": a["pp_id"],
                    "hint": STILL_RUNNING_HINT}
        return r.data

    def _dl_path(self, name):
        if not isinstance(name, str) or not name or Path(name).name != name or name in (".", ".."):
            raise ValueError("filename 只能是檔名，不能帶路徑：%r" % (name,))
        path = (self.download_dir / name).resolve()
        if not path.is_relative_to(self.download_dir.resolve()):
            raise ValueError("filename 會寫到下載目錄外面：%r" % name)
        return path

    def _h_pp_fetch(self, a):
        path = self._dl_path(a.get("filename") or "%s.mp4" % a["pp_id"])
        blob = self.wb.post_process_content(a["pp_id"])
        self.download_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        return {"path": str(path), "bytes": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest()}

    def _h_asset_fetch(self, a):
        path = self._dl_path(a.get("filename") or a["asset_id"])
        blob = self.wb.asset_content(a["asset_id"])
        self.download_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        return {"path": str(path), "bytes": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest()}

    def _h_fetch(self, a):
        path = self._dl_path(a.get("filename") or "%s.mp4" % a["job_id"])
        blob = self.wb.download(a["job_id"])
        self.download_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        return {"path": str(path), "bytes": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest()}

    def _price_of(self, quote_id):
        return self._quoted.get(quote_id, UNKNOWN_COST)

    def _pipeline_dry(self, a):
        wb = self.wb
        if isinstance(a.get("snapshot"), dict):
            snap = dict(a["snapshot"])
            if a.get("pipeline") is not None:
                snap["pipeline"] = a["pipeline"]
            return wb.pipeline_preview(snap)
        if not (a.get("project_id") and a.get("job_id")):
            raise ValueError("要給 snapshot，或 project_id＋job_id")
        return wb.work_export(a["project_id"], a["job_id"], a.get("overrides"), a.get("pipeline"), dry_run=True)

    def _h_status(self, a):
        out = {}
        jid = a.get("job_id")
        if a.get("approval_id"):
            card = self.wb.approval_get(a["approval_id"])
            out["approval"] = card
            jid = jid or (card.get("job_id") if isinstance(card, dict) else None)
        if jid:
            st = self.wb.job_status(jid)
            out["job"] = st
            s = str((st or {}).get("status") or "").lower() if isinstance(st, dict) else ""
            out["state"] = "failed" if s == "failed" else "done" if s in ("completed", "succeeded", "done") else "processing"
        elif not out:
            return {"error": "給 approval_id 或 job_id"}
        else:
            out["state"] = (out["approval"] or {}).get("status")
        return out

    def _h_result(self, a):
        if a.get("export_id"):
            st = self.wb.export_status(a["export_id"])
            state = (st or {}).get("state") if isinstance(st, dict) else None
            if state == "done":
                return {"state": "done", "path": st.get("path"), "duration": st.get("duration"), "export": st}
            if state == "failed":
                return {"state": "failed", "error": st.get("error"), "export": st}
            return {"state": state or "processing", "still_processing": True, "export": st}
        jid = a.get("job_id")
        if not jid and a.get("approval_id"):
            card = self.wb.approval_get(a["approval_id"])
            jid = card.get("job_id") if isinstance(card, dict) else None
            if not jid:
                return {"state": (card or {}).get("status"), "still_processing": True,
                        "note": "這張卡還沒送出或還沒拿到工作 id"}
        if not jid:
            return {"error": "給 job_id 或 approval_id"}
        st = self.wb.job_status(jid)
        s = str((st or {}).get("status") or "").lower() if isinstance(st, dict) else ""
        if s == "failed":
            return {"state": "failed", "job": st}
        if s not in ("completed", "succeeded", "done"):
            return {"state": "processing", "still_processing": True, "job": st}
        if self.local:
            return dict(self.wb.local_result(jid), state="done")
        base = getattr(self.session, "public_url", None) or self.session.base_url
        return {"state": "done", "url": "%s/api/download?id=%s" % (base, jid),
                "auth": "GET 這個網址時帶同一把權杖：Authorization: Bearer <你的權杖>"}

    def _add_ui_tools(self, add):
        wb = self.wb
        s = lambda v: {"type": "string"} if v is None else v
        add("ui_actions_list",
            "列出介面上可以擺的積木：動作（action、按鈕文字、會不會花錢）、項目種類（text／step／button）、上限、"
            "prefs 能設的鍵，以及 ui_edit 能用的 op。先看這個再組介面。免費。",
            _obj({}), lambda a: self._ui_catalog())
        add("ui_get",
            "讀介面描述檔。沒給 name：目前正在用的那份（desc、prefs）、所有 profile（誰存的、何時）、"
            "「允許 Agent 直接套用介面」開了沒。給 name：讀那一份（含文字預覽）。免費。",
            _obj({"name": s(None)}), self._h_ui_get)
        add("ui_compose",
            "用訪談的 8 題答案組出起點（answers 可以只給一部分，缺的用預設補、notes 會寫），存成工作稿（預設 name=draft）。"
            "題目：genre（meme／short／long／ad／other）、steps（script／storyboard／cast／generate／select／post／sound／publish）、"
            "budget、previs、agent（true／false）、publish（youtube／pitch／none）、density（simple／standard／pro）、lang（zh-TW／en）。免費。",
            _obj({"answers": {"type": "object"}, "name": s(None), "title": s(None)}),
            lambda a: wb.ui_desc_post({"op": "save", "name": a.get("name") or "draft", "answers": a.get("answers") or {},
                                       **({"title": a["title"]} if a.get("title") else {})}))
        add("ui_edit",
            "細部編輯一份介面（預設 draft）：ops 照順序套用，每一步都過驗證器，任何一步不合法就整批不套用（回 op_index）。"
            "op：add_panel {id,title,items,at?}、remove_panel {panel}、add_item {panel,item,at?}、remove_item {panel,index|action}、"
            "move {panel,to}／{panel,item,to,to_panel?}、rename {name}／{panel,title}／{panel,item,label}、set_pref {key,value}；"
            "版面（桌面版）：set_layout {panel,dock?,size?,collapsible?,collapsed?}（dock＝left／right／bottom／float、size＝s／m／l）、"
            "set_main {split,slots}（split＝single／two／three，slots 數量要等於欄數、第一欄是 {component:'stage'}；能放的元件看 ui_actions_list 的 layout）。"
            "版面的 op 會把 v1 描述檔升成 v2（回應帶 upgraded）。免費。",
            _obj({"ops": {"type": "array", "items": {"type": "object"}}, "name": s(None)}, ["ops"]), self._h_ui_edit)
        add("ui_preview",
            "一份介面的文字預覽（由上往下：面板 → 按鈕，花錢的標出來，最後是偏好）。截圖要等 e2e（還沒開放）。免費。",
            _obj({"name": s(None)}),
            lambda a: self._ui_preview(a.get("name") or "draft"))
        add("ui_save",
            "把工作稿（from，預設 draft）存成一份正式的介面（name）；或直接給一份完整的描述檔（desc，可以是 version 2，"
            "帶 layout／theme／flow，格式見 docs/ui-v2.md），伺服器照同一個驗證器整份驗過才存。記成 Agent 存的。免費。",
            _obj({"name": s(None), "from": s(None), "desc": {"type": "object"}}, ["name"]),
            lambda a: wb.ui_desc_post({"op": "save", "name": a["name"], "desc": a["desc"]}) if isinstance(a.get("desc"), dict)
            else wb.ui_desc_post({"op": "copy", "name": a["name"], "from": a.get("from") or "draft"}))
        add("ui_apply",
            "套用一份介面：直接生效（描述檔面板開著時 5 秒內重畫），不需要使用者另外允許。套用前會自動存一份上一版的快照，"
            "所以隨時可以 ui_undo 還原、ui_reset 回預設。免費。",
            _obj({"name": s(None)}, ["name"]),
            lambda a: wb.ui_desc_post({"op": "activate", "name": a["name"]}))
        add("ui_reset",
            "回預設框架（清掉自訂的介面與偏好）。使用者說「回預設」「回原本的樣子」就用這個；之後可以 ui_undo 回到剛才那一版。免費。",
            _obj({}), lambda a: wb.ui_desc_post({"op": "reset"}))
        add("ui_undo",
            "還原到上一版介面（每次套用、回預設、還原之前都會留快照；連按兩次就回到原本那一版）。免費。",
            _obj({}), lambda a: wb.ui_desc_post({"op": "undo"}))
        add("ui_onboarding_status",
            "使用者是不是還沒建自己的介面（第一次進導演台要先「打造你的介面」）。needed=true 時請主動開始對話："
            "問他想怎麼拍、常用哪些步驟，用 ui_compose／ui_edit／ui_apply 建好。他也可以在畫面上按「先用預設框架」跳過。免費。",
            _obj({}), lambda a: wb.ui_desc_get(onboarding=True))

    def _add_agent_tools(self, add):
        wb = self.wb
        S = {"type": "string"}
        plan_props = {"request": S, "input": {"type": "object"}, "storyboard": {"type": "array", "items": {"type": "object"}},
                      "cast": {"type": "array"}, "budget": {"type": "object"}, "model": S, "caps": {"type": "object"},
                      "has_cast_refs": {"type": "boolean"}, "max_retakes": {"type": "integer", "minimum": 0, "maximum": 5},
                      "target_seconds": {"type": "number"}}
        add("agent_plan",
            "Filming Agent 只規劃、不花錢：一句需求（request）＋分鏡（storyboard，可省；或 input＝腳本／鏡頭表）→ 每一鏡的計畫、"
            "接縫、總秒數、預算（totals）、要先問人的缺口（must_ask／controls_gaps）。要開拍再用 agent_run。",
            _obj(plan_props, ["request"]), lambda a: wb.agent_plan(dict(a)))
        add("agent_run",
            "Filming Agent 主迴圈。action=start：開拍（request＋model，可帶 storyboard／input／budget／project_id）→ run id；"
            "action=step：往下跑一步（Agent 自己看片的話帶 event={type:'checked', reports:[品管報告]}）；action=get：讀整份狀態；action=list：最近的 run（新的在前，最多 20 筆），找回「目前那一次」用。"
            "錢照既有規則：Agent 直送開著就在上限內直接送，超過上限或沒有預先授權就停下來（ask），等人處理後用 agent_answer 續跑。"
            "Agent 不能自己改上限。",
            _obj(dict(plan_props, action={"type": "string", "enum": ["start", "step", "get", "list"]}, run=S,
                      event={"type": "object"}, project_id=S, resolution=S, aspect_ratio=S), ["action"]),
            self._h_agent_run, spends=True)
        add("agent_answer",
            "回覆主迴圈的提問（動作是 ask 時）：decision＝resume（人處理好了，例如在 App 裡核准了卡）／stop（停）／"
            "accept_best（重做用完了，挑最好的那支）；或 controls＝{storyboard, cast} 補好分鏡的缺口（controls_gap）。"
            "不收 approve／raise：放行與改上限只有人在 App 裡能做。",
            _obj({"run": S, "decision": {"type": "string", "enum": ["resume", "stop", "accept_best"]},
                  "controls": {"type": "object"}}, ["run"]), self._h_agent_answer, spends=True)
        add("agent_film_preview",
            "交片預覽（不花錢）：這一次拍片每一鏡有哪些版本（versions：第幾版、品管、狀態、能不能播）、哪一版是定稿、誰挑的"
            "（picked_by：agent／human），以及每一鏡定稿依序接好的成片（film.path＝這台電腦上的檔案；本機 ffmpeg 接）。"
            "有一鏡還沒定稿就不接（missing 列出鏡號）。人在 App 的「Agent 拍片進度」面板上看得到同一份。",
            _obj({"run": S}, ["run"]), lambda a: wb.agent_film(a["run"]))
        add("agent_pick",
            "替人挑一鏡的定稿（不花錢）：take 要是 agent_film_preview 列出的這一次拍片、這一鏡的版本。直接生效，記成 Agent 挑的"
            "（面板上寫「Agent 挑的」）；原本的定稿自動取消。挑錯了人可以在面板上再挑回來。回挑完之後的交片預覽（成片照新定稿重接）。",
            _obj({"run": S, "shot_key": S, "take": S}, ["run", "shot_key", "take"]), self._h_agent_pick)
        add("work_run",
            "一條龍：從一部作品一路拍到成片（報價 → 送件 → 等片 → 品管 → 交片），就是 Filming Agent 主迴圈的便利入口。"
            "開拍給 project_id（範本作品的模型、解析度、送件設定照範本；一般作品要給 model）；續跑給 run（自己看片的話帶 "
            "event={type:'checked', reports}；回覆提問帶 decision＝resume／stop／accept_best）。每次呼叫往下跑幾步就回："
            "phase（done／running／needs_check／waiting_human／failed）、reason、next（下一步怎麼做，例如要人核准哪張卡：approve_url）；"
            "done 時附交片預覽。錢照既有規則（核准卡、預先授權、Agent 直送和上限），Agent 改不了上限。",
            _obj({"project_id": S, "model": S, "run": S, "event": {"type": "object"},
                  "decision": {"type": "string", "enum": ["resume", "stop", "accept_best"]}}),
            lambda a: wb.work_run(dict(a)), spends=True)

    def _h_agent_run(self, a):
        act = a.get("action")
        if act == "list":
            return self.wb.agent_runs()
        if act == "get":
            if not a.get("run"):
                return {"error": "get 要帶 run"}
            return self.wb.agent_get(a["run"])
        if act == "step":
            if not a.get("run"):
                return {"error": "step 要帶 run"}
            return self.wb.agent_step({"run": a["run"], **({"event": a["event"]} if a.get("event") is not None else {})})
        if act == "start":
            body = {k: v for k, v in a.items() if k not in ("action", "run", "event")}
            return self.wb.agent_start(body)
        return {"error": "action 只能是 start／step／get／list"}

    def _h_agent_answer(self, a):
        if (a.get("decision") is None) == (a.get("controls") is None):
            return {"error": "decision 與 controls 要給其中一個"}
        if a.get("decision") is not None:
            return self.wb.agent_step({"run": a["run"], "decision": a["decision"]})
        c = a["controls"] if isinstance(a["controls"], dict) else {}
        return self.wb.agent_step({"run": a["run"], "event": dict({"type": "controls"},
                                   **{k: c[k] for k in ("storyboard", "cast") if k in c})})

    def _h_agent_pick(self, a):
        cur = self.wb.agent_film(a["run"])
        shot = next((s for s in cur.get("shots") or [] if s.get("key") == a["shot_key"]), None)
        if shot is None:
            return {"error": "這一次拍片沒有 %s 這一鏡" % a["shot_key"]}
        v = next((x for x in shot.get("versions") or [] if x.get("take") == a["take"]), None)
        if v is None:
            return {"error": "%s 不是這一次拍片 %s 的版本（先用 agent_film_preview 看清單）" % (a["take"], a["shot_key"])}
        if not v.get("src"):
            return {"error": "這一版沒有生成好的片（%s），不能當定稿" % v.get("status")}
        self.wb.take_pick(a["take"])
        return dict(self.wb.agent_film(a["run"]), picked={"shot_key": a["shot_key"], "take": a["take"], "by": "agent"},
                    undo="挑錯了：人在 App 的「Agent 拍片進度」面板上按「用這一版當定稿」就改回來")

    def _add_local_media_tools(self, add):
        wb = self.wb
        add("video_concat",
            "把幾支拍好的片（job id，照順序，2–30 支）接成一支，用這台電腦的 ffmpeg，**不花錢**。回 path（這台電腦上的檔案）"
            "與 lossless（規格一致時無損直接接）。要接「這一次拍片的定稿」用 agent_film_preview 比較方便。",
            _obj({"jobs": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 30},
                  "name": {"type": "string"}, "mute_model_audio": {"type": "boolean"}}, ["jobs"]),
            lambda a: wb.concat(a["jobs"], a.get("name"), a.get("mute_model_audio")))
        add("agent_settings",
            "讀這台 App 的各個開關現在是什麼（主迴圈、Agent 直送、自動驗片、首幀接力、Agent 範圍、匯出引擎、接片引擎、介面描述檔）。"
            "只能讀；切換只有使用者本人在 App 的設定頁「Agent」區塊裡做（打不開的功能就請他去那裡打開）。免費。",
            _obj({}), self._h_agent_settings)

    def _h_agent_settings(self, _a):
        out = {}
        for name in self.wb.LOCAL_SWITCHES:
            try:
                out[name] = self.wb.local_switch(name)
            except Exception as e:
                out[name] = {"error": str(e)[:200]}
        return {"switches": out, "how_to_change": "只有使用者本人能切：請他打開 App 的設定頁，在「Agent」區塊或「匯出引擎」那一格改。"}

    def _ui_catalog(self):
        return self.wb.ui_desc_get(catalog=True)

    def _h_ui_get(self, a):
        if a.get("name"):
            return self.wb.ui_desc_get(name=a["name"])
        lst = self.wb.ui_desc_get()
        out = {"profiles": lst.get("items"), "active": lst.get("active"), "can_undo": lst.get("can_undo")}
        if lst.get("active"):
            rec = self.wb.ui_desc_get(name=lst["active"])
            out.update(desc=rec.get("desc"), prefs=rec.get("prefs"), preview=rec.get("preview"))
        else:
            out["preview"] = "（預設框架：沒有自訂面板）"
        return out

    def _h_ui_edit(self, a):
        try:
            return self.wb.ui_desc_post({"op": "edit", "name": a.get("name") or "draft", "ops": a["ops"]})
        except ApiError as e:
            p = e.payload if isinstance(e.payload, dict) else {}
            if "op_index" in p:
                return {"error": p.get("error"), "op_index": p["op_index"], "unchanged": True}
            raise

    def _ui_preview(self, name):
        rec = self.wb.ui_desc_get(name=name)
        return {"name": name, "text": rec.get("preview"), "screenshot": None,
                "note": "截圖要起瀏覽器，等 e2e 的 A／B 決定後才開放；文字預覽就是面板由上往下的樣子"}

    def _h_quote(self, a):
        sheet = self.wb.request_confirmation(dict(a))
        if not is_confirmation(sheet):
            jid = sheet.get("id") if isinstance(sheet, dict) else None
            if jid:
                self.ledger.record_job(jid, "video", self.session,
                                  {"via": "no-confirmation"})
                self.ledger.record_spend("video", self.session, ref=jid)
            self._spent_unknown = True
            return {"warning": "平台沒有回確認單——工作已經被直接建立，"
                               "這一趟就扣款了。要讓它先出確認單，"
                               "請在後台為這個帳戶開啟確認模式。",
                    "job": sheet}
        qid = sheet.get("quote_id")
        if qid is not None:
            pts = (sheet.get("estimate") or {}).get("points")
            self._quoted[qid] = pts if isinstance(pts, (int, float)) else None
        return sheet

    def _h_confirm(self, a):
        self._charge(self._price_of(a["quote_id"]), "video_confirm")
        data = self.wb.confirm(a["quote_id"])
        jid = data.get("id") if isinstance(data, dict) else None
        if jid:
            self.ledger.record_job(jid, "video", self.session,
                              {"quote_id": a["quote_id"], "via": "mcp"})
        self.ledger.record_spend("video", self.session, quote_id=a["quote_id"], ref=jid)
        return data

    _ANGLE_TEXT = {"front": "front view", "side": "side profile view", "back": "back view",
                   "three-quarter": "three-quarter view", "close-up": "close-up portrait",
                   "full-body": "full-body view"}

    def _h_director_plan(self, a):
        state = {}
        try:
            vals = (self.wb.store_get_many(["shots", "characters", "canvas"]) or {}).get("values") or {}
            shots, chars, canvas = vals.get("shots"), vals.get("characters"), vals.get("canvas")
            state = {"shots": len(shots) if isinstance(shots, list) else 0,
                     "characters": len(chars) if isinstance(chars, list) else 0,
                     "timeline_clips": len((canvas or {}).get("clips") or []) if isinstance(canvas, dict) else 0}
        except Exception as e:
            state = {"error": "讀不到工作台狀態：%s" % e}
        steps = [
            ("1 分鏡", "把劇本拆成鏡頭：parse_shots（或自己寫好 shots），想讓人在工作台看到就 store_put shots"),
            ("2 角色", "角色多角度參考圖：character_angles（扣款）→ asset_upload 放進素材庫"),
            ("3 預演", "3D 預演在工作台的編輯器裡做（store_get previs-* 讀得到存檔）；運鏡寫進每一鏡的 prompt"),
            ("4 報價", "storyboard_quote（免費）→ 把合計點數告訴使用者"),
            ("5 生成", "shots_confirm（扣款；確認模式下等人核准，用 agent_pending_status 查）→ video_wait"),
            ("6 剪輯", "timeline_place 依序放進剪輯軌 → timeline_trim 修入出點；人在工作台可以直接接手重抽"),
            ("7 匯出", "export_request：工作台打開匯出面板，授權警告由人看過再按匯出"),
        ]
        return {"state": state, "steps": [{"step": k, "how": v} for k, v in steps],
                "rules": ["花錢的每一步先報價、把金額告訴使用者",
                          "付款方在報價那一刻鎖定，確認時不能改",
                          "pending_confirmation 不是失敗，不要重送"]}

    def _add_dirctl_tools(self, add):
        wb = self.wb
        add("dirctl_catalog",
            "導演控制的選項表：運鏡 id（30 種，含中文與冷門標記）、速度、六欄（lens／style／color／light／location／sound）、"
            "景別、角度、走位（x：left／center／right，depth：front／mid／back，facing）、對準角色的機位與景別、各欄上限，"
            "以及 shot_dirctl_set 的 dc 欄位。先看這個再填。免費。",
            _obj({}), lambda a: wb.dir_controls_get(full=True))
        add("dirctl_compose",
            "導演控制描述檔（dir_controls version 1：{version:1, prompt, camera:{move,speed,direction,end,size,angle,allow_cuts,rig}, "
            "blocking:[{name, at:{x,depth}, facing, to, action}], performance:[{name, notes:[…]}], lens…sound}）→ "
            "送件時組出來的完整提示詞與 warnings。只預覽、不送件。免費。",
            _obj({"desc": {"type": "object"}}, ["desc"]), lambda a: wb.dir_controls_preview(a["desc"]))
        add("previs_rig",
            "3D 預演的對準角色機位：spec＝{rig: ots|two_shot, over/at（過肩：越過 over 看 at；反打＝兩個對調）或 a/b（雙人）, "
            "size（ots：cu／mcu／ms；two_shot：ms／ws）, t（取第幾秒的站位）, side（front／back）}。"
            "場景給 scene（previs v1 物件）或 scene_key（store 裡 previs- 開頭的鍵）。回固定機位 cam 與 notes；只算不寫。免費。",
            _obj({"spec": {"type": "object"}, "scene": {"type": "object"}, "scene_key": {"type": "string"}}, ["spec"]),
            self._h_previs_rig)
        add("shot_dirctl_set",
            "寫一部作品某一鏡的導演控制（dc）：直接生效、不需要使用者允許；送件時這一鏡有 dc 就帶（跟畫面開關無關），"
            "開著的導演台幾秒內自動重讀這一格。dc 欄位：move、speed、direction、end、allow_cuts、lens、style、color、light、"
            "location、sound、blocking[{name,x,depth,facing,tox,todepth,action}]、perf[{name,notes}]（見 dirctl_catalog）。"
            "安全網：dc=null 清掉（回預設）；undo=true 換回上一版（每次寫入前都留一份）。shot 是第幾鏡（1 起算）或 sid。免費。",
            _obj({"project_id": {"type": "string"}, "shot": {"type": ["integer", "string"]},
                  "dc": {"type": ["object", "null"]}, "undo": {"type": "boolean"}}, ["project_id", "shot"]),
            self._h_shot_dirctl)

    def _h_previs_rig(self, a):
        scene = a.get("scene")
        if scene is None:
            key = a.get("scene_key") or ""
            if not key.startswith("previs"):
                raise ValidationError("要給 scene，或 scene_key（previs- 開頭的 store 鍵）")
            scene = self.wb.store_get(key).get("value")
            if not isinstance(scene, dict):
                raise ValidationError("store 裡沒有這個預演場景：%s" % key)
        return self.wb.previs_rig(scene, a["spec"])

    def _h_shot_dirctl(self, a):
        body = {"project_id": a["project_id"], "shot": a["shot"]}
        if a.get("undo") is True:
            body["undo"] = True
        elif "dc" in a:
            body["dc"] = a["dc"]
        else:
            raise ValidationError("要給 dc（物件，或 null＝清掉），或 undo: true")
        return self.wb.work_shot_dirctl(body)

    def _h_storyboard_quote(self, a):
        out, total, unknown = [], 0.0, False
        for i, sh in enumerate(a["shots"]):
            body = {k: v for k, v in sh.items() if v not in (None, "")}
            body.setdefault("model", a["model"])
            for k in ("resolution", "aspect_ratio"):
                if a.get(k) and k not in body:
                    body[k] = a[k]
            model_caps.with_res_default(body)
            try:
                sheet = self._h_quote(body)
            except Exception as e:
                out.append({"shot": i + 1, "error": str(e)})
                continue
            if "warning" in sheet:
                out.append({"shot": i + 1, **sheet})
                return {"shots": out, "stopped": "平台沒有回確認單，已直接建立工作；後面幾鏡沒有送"}
            pts = sheet.get("charge_points") or (sheet.get("estimate") or {}).get("points")
            try:
                total += float(pts)
            except (TypeError, ValueError):
                unknown = True
            out.append({"shot": i + 1, "quote_id": sheet.get("quote_id"), "points": pts,
                        "payer": sheet.get("payer"), "model": body["model"],
                        "seconds": (sheet.get("resolved") or {}).get("seconds", body.get("seconds"))})
        return {"shots": out, "total_points": None if unknown else round(total, 2),
                "next": "把合計告訴使用者，同意後 shots_confirm(quote_ids)"}

    def _h_shots_confirm(self, a):
        res = []
        for qid in a["quote_ids"]:
            try:
                res.append({"quote_id": qid, **(self._h_confirm({"quote_id": qid}) or {})})
            except SpendBlocked as e:
                res.append({"quote_id": qid, "error": str(e)})
                break
            except Exception as e:
                res.append({"quote_id": qid, "error": str(e)})
        return {"results": res,
                "pending": [w.get("pending_id") or w.get("quote_id") for w in map(needs_human, res) if w],
                "jobs": [r.get("id") for r in res if r.get("id")]}

    def _h_character_angles(self, a):
        angles = a.get("angles") or ["front", "side", "back", "three-quarter"]
        out = []
        for ang in angles:
            prompt = "character reference sheet, %s, %s. %s. neutral grey background, consistent design" % (
                a["name"], self._ANGLE_TEXT.get(ang, ang), a["description"])
            body = {"model": a["model"], "prompt": prompt, "max_points": a["max_points_each"]}
            if a.get("size"):
                body["size"] = a["size"]
            try:
                r = self._h_image(body)
            except SpendBlocked as e:
                out.append({"angle": ang, "error": str(e)})
                break
            except Exception as e:
                out.append({"angle": ang, "error": str(e)})
                continue
            wait = needs_human(r)
            if wait:
                out.append(dict(wait, angle=ang))
                continue
            urls = [d.get("url") for d in (r or {}).get("data") or [] if isinstance(d, dict)]
            out.append({"angle": ang, "urls": urls, "charged_points": (r or {}).get("charged_points"),
                        "payer": (r or {}).get("payer")})
        return {"name": a["name"], "angles": out,
                "next": "要當參考圖：asset_upload(url=…) 拿 asset://，再放進 video_quote 的 input_references"}

    def _cast_cards(self):
        try:
            got = self.wb.store_get("characters")
        except Exception:
            return []
        v = got.get("value") if isinstance(got, dict) and "value" in got else got
        return [c for c in v if isinstance(c, dict) and isinstance(c.get("name"), str)] if isinstance(v, list) else []

    def _tts_alternatives(self):
        try:
            ids = (self.wb.model_groups() or {}).get("audio") or []
        except Exception:
            return []
        ok = [m for m in ids if isinstance(m, str) and m and not model_caps.tts_blocked(m)]
        return sorted(ok, key=lambda m: not any(k in m.lower() for k in ("speech", "tts")))

    def _h_voice_line(self, a, fmt=None):
        model = str(a.get("model") or "").strip()
        if not model or model_caps.tts_blocked(model):
            alt = self._tts_alternatives()
            hint = ("請改用 %s" % alt[0]) if alt else "目錄裡目前沒有可用的配音模型（請使用者到設定頁確認金鑰與目錄）"
            if not model:
                raise ValidationError("voice_line 的 model 必填：沒寫供應商的名稱會補成 %s，那一家目前不能用來配音。%s。"
                                      "沒有送出任何請求。" % (model_caps.AUDIO_MODEL_PREFIX, hint))
            sent = model_caps.tts_effective(model)
            prov = sent.split("/", 1)[0] + "/"
            via = ("在伺服器會補成 %s、走 %s 供應商" % (sent, prov)) if sent != model else ("走 %s 供應商" % prov)
            raise ValidationError("%s %s，這一家目前不能用來配音，%s。沒有送出任何請求。" % (model, via, hint))
        body = {"model": model, "input": a["text"]}
        for k in ("voice", "speed"):
            if a.get(k) is not None:
                body[k] = a[k]
        if fmt:
            body["response_format"] = fmt
        cast_note = None
        if a.get("cast") is True and not body.get("voice"):
            card = next((c for c in self._cast_cards() if c["name"] == a.get("speaker")), None)
            voice = card.get("voice") if card and isinstance(card.get("voice"), str) and card["voice"].strip() else None
            mode = cast_mode()
            if mode == "blocks" and voice:
                body["voice"] = voice.strip()
            cast_note = {"mode": mode, "applied": mode == "blocks" and bool(voice)}
            if mode == "shadow":
                cast_note["reason"] = "voice_diff" if voice else "voice_same"
        sheet = self._h_audio_quote(body, "tts")
        wait = needs_human(sheet)
        qid = (sheet or {}).get("quote_id") if isinstance(sheet, dict) else None
        if not qid:
            return sheet
        if wait:
            return dict(wait, next="請使用者核准這張配音卡，再用 submit_approved(approval_id=approval.id) 送出",
                        cast_voice=cast_note)
        if a.get("max_points") is not None and sheet.get("payer") != "own_key":
            price = self._quoted.get(qid)
            if price is None or price > float(a["max_points"]):
                self.wb.speech_confirm(qid, confirm=False)
                raise SpendBlocked("配音報價 %s 點超過（或看不到）你給的 max_points %.4f。沒有送出任何請求。"
                                   % (price, float(a["max_points"])))
        data = self._h_audio_confirm({"quote_id": qid, "kind": "tts"}) or {}
        out = {"quote_id": qid, "audio": data.get("audio"), "seconds": data.get("seconds"), "payer": data.get("payer")}
        if cast_note:
            out["cast_voice"] = cast_note
        return out

    def _h_lipsync_shot(self, a):
        kf = a.get("keyframe")
        if not kf and a.get("cast") and cast_mode() == "blocks":
            names = [n for n in a["cast"] if isinstance(n, str)]
            for c in [c for c in self._cast_cards() if c["name"] in names]:
                refs = [r for r in c.get("refs") or [] if isinstance(r, dict) and r.get("ref")]
                pick = next((r for r in refs if r.get("role") == "outfit"), refs[0] if refs else None)
                if pick:
                    kf = pick["ref"]
                    break
        if not kf:
            raise ValidationError("對嘴要一張定裝圖（keyframe）：只有音訊、沒有臉，模型對不了嘴。沒有送出任何請求。")
        secs = float(a["audio_seconds"])
        rule = _duration_rule(a["model"])
        if secs > rule["max"]:
            raise ValidationError("配音 %.2f 秒比這個模型一鏡的上限 %d 秒還長：先把台詞拆成幾句、各拍一鏡（不截音）。"
                                  "沒有送出任何請求。" % (secs, rule["max"]))
        body = {"model": a["model"], "prompt": a["prompt"], "seconds": max(int(rule["min"]), int(math.ceil(secs - 1e-9))),
                "input_references": [{"type": "image", "url": kf, "role": "reference_image"},
                                     {"type": "audio", "url": a["audio"], "role": "reference_audio"}]}
        for k in ("resolution", "aspect_ratio"):
            if a.get(k):
                body[k] = a[k]
        return self._h_quote(_shot_payload(body))

    def _dub_keyframe(self, keyframe, cast, speaker):
        if keyframe or not (cast and speaker and cast_mode() == "blocks"):
            return keyframe
        for c in [c for c in self._cast_cards() if c["name"] == speaker]:
            refs = [r for r in c.get("refs") or [] if isinstance(r, dict) and r.get("ref")]
            pick = next((r for r in refs if r.get("role") == "outfit"), refs[0] if refs else None)
            if pick:
                return pick["ref"]
        return None

    def _dub_upload(self, audio):
        url = audio.get("url") if isinstance(audio, dict) else audio
        url = str(url or "").strip()
        if url.startswith("asset://") or re.match(r"^https?://", url):
            return url, None
        m = re.match(r"^/api/audio/content\?sha=([0-9a-f]{64})$", url)
        d = re.match(r"^data:(audio/[A-Za-z0-9.+-]+)?(?:;[^,]*)?;base64,(.*)$", url, re.S)
        if m:
            raw = self.wb.audio_content(m.group(1))
        elif d:
            raw = base64.b64decode(d.group(2))
        else:
            raise ValidationError("audio 要是 asset://、網址、/api/audio/content?sha= 或 data: 音檔。沒有送出任何請求。")
        if not isinstance(raw, (bytes, bytearray)) or not raw:
            raise ApiError(502, "讀不到配音的音檔")
        got = self.wb.asset_upload("data:%s;base64,%s" % (_audio_mime(raw, d and d.group(1)),
                                                          base64.b64encode(raw).decode()), name="voice_line")
        aid = got.get("id") if isinstance(got, dict) else None
        if not aid:
            raise ApiError(502, "上傳配音沒有回素材 id")
        return "asset://" + aid, bytes(raw)

    def _h_dub_lipsync_shot(self, a):
        keyframe = self._dub_keyframe(a.get("keyframe"), a.get("cast"), a.get("speaker"))
        if not keyframe:
            raise ValidationError("對嘴要一張定裝圖（keyframe）：只有音訊、沒有臉，模型對不了嘴。還沒配音，沒有花錢。")
        audio, secs, voice = a.get("audio"), a.get("audio_seconds"), None
        if not audio:
            if not (a.get("text") and a.get("tts_model")):
                raise ValidationError("沒帶 audio 時 text 與 tts_model 必填（要先配音）。沒有送出任何請求。")
            voice = self._h_voice_line({"model": a.get("tts_model"), "text": a.get("text"), "voice": a.get("voice"),
                                        "speed": a.get("speed"), "speaker": a.get("speaker"), "cast": a.get("cast"),
                                        "max_points": a.get("max_points")}, fmt="mp3")
            if isinstance(voice, dict) and voice.get("approval"):
                return dict(voice, stage="voice_pending",
                            next="請使用者核准這張配音卡；submit_approved(approval_id=approval.id) 會回 audio，"
                                 "再呼叫 dub_lipsync_shot 帶 audio=那個 audio.url（不會重配）")
            audio = (voice or {}).get("audio")
            secs = (voice or {}).get("seconds")
            if not audio:
                return {"stage": "voice_failed", "voice": voice}
        try:
            ref, raw = self._dub_upload(audio)
        except ApiError as e:
            return {"stage": "upload_failed", "audio": audio, "seconds": secs, "error": str(e),
                    "next": "配音已經做好：之後帶 audio=這個音檔再呼叫一次就好，不要重配"}
        if not secs and raw:
            secs = _audio_seconds(raw)
        out = {"audio_ref": ref, "seconds": secs}
        if voice:
            out["voice"] = {k: voice[k] for k in ("quote_id", "payer", "cast_voice") if voice.get(k) is not None}
        if not secs:
            return dict(out, stage="need_seconds", next="量不到配音秒數：帶 audio=audio_ref 與 audio_seconds 再呼叫一次")
        rule = _duration_rule(a["model"])
        if float(secs) > rule["max"]:
            return dict(out, stage="too_long", next="配音 %.2f 秒比這個模型一鏡的上限 %d 秒還長：把台詞拆短再配（不截音）"
                                                     % (float(secs), rule["max"]))
        args = {"model": a["model"], "prompt": a["prompt"], "keyframe": keyframe, "audio": ref, "audio_seconds": secs}
        for k in ("resolution", "aspect_ratio"):
            if a.get(k):
                args[k] = a[k]
        sheet = self._h_lipsync_shot(args)
        return dict(out, stage="quoted", quote=sheet, next="要生成就把 quote 交給 video_confirm")

    def _h_image(self, a):
        payload = {k: v for k, v in a.items() if k != "max_points"}
        if self.local:
            return self.wb.image_generate(payload)
        quote = None
        try:
            quote = self.wb.estimate(payload)
        except Exception:
            quote = None
        pts = (quote or {}).get("points")
        try:
            price = float(pts) if pts is not None else None
        except (TypeError, ValueError):
            price = None
        if price is None:
            raise SpendBlocked("估價沒有回本站點數，max_points %.4f 保證不了。沒有送出任何請求。"
                               % float(a["max_points"]))
        if price > float(a["max_points"]):
            raise SpendBlocked(
                "報價 %.4f 點超過你給的 max_points %.4f。沒有送出任何請求。"
                % (price, float(a["max_points"])))
        self._charge(price, "image_generate")
        data = self.wb.image_generate(payload)
        self.ledger.record_spend("image", self.session,
                            points=(data or {}).get("charged_points"),
                            ref=(data or {}).get("id"))
        return data

    def _h_outpaint(self, a):
        payload = {k: a[k] for k in ("source", "aspect", "prompt") if k in a}
        try:
            quote = self.wb.image_outpaint(dict(payload, quote=True))
        except Exception:
            quote = None
        pts = (quote or {}).get("points")
        try:
            price = float(pts) if pts is not None else None
        except (TypeError, ValueError):
            price = None
        if price is None:
            raise SpendBlocked("外擴的估價沒有回本站點數，max_points %.4f 保證不了。沒有送出任何請求。"
                               % float(a["max_points"]))
        if price > float(a["max_points"]):
            raise SpendBlocked("報價 %.4f 點超過你給的 max_points %.4f。沒有送出任何請求。"
                               % (price, float(a["max_points"])))
        self._charge(price, "image_outpaint")
        data = self.wb.image_outpaint(payload)
        self.ledger.record_spend("image", self.session,
                                 points=(data or {}).get("charged_points"),
                                 ref=(data or {}).get("upstream_id"))
        return data

    def _h_storyboard_ai(self, a):
        sheet = self.wb.storyboard_ai_quote(a["story"], a.get("shots", 6), a.get("style"), a.get("video_model"),
                                            a.get("project_id"), director=a.get("director") is True)
        qid = (sheet or {}).get("quote_id")
        if not qid:
            return sheet
        pts = (sheet or {}).get("charge_points")
        try:
            price = float(pts) if pts is not None else None
        except (TypeError, ValueError):
            price = None
        try:
            if price is None and sheet.get("payer") != "own_key":
                raise SpendBlocked("AI 分鏡的報價沒有回本站點數，max_points %.4f 保證不了。沒有送出任何請求。"
                                   % float(a["max_points"]))
            if price is not None and price > float(a["max_points"]):
                raise SpendBlocked("預扣上限 %.4f 點超過你給的 max_points %.4f。沒有送出任何請求。"
                                   % (price, float(a["max_points"])))
            self._charge(price, "storyboard_ai")
        except SpendBlocked:
            self.wb.storyboard_ai_confirm(qid, confirm=False)
            raise
        data = self.wb.storyboard_ai_confirm(qid)
        self.ledger.record_spend("storyboard", self.session, quote_id=qid,
                                 points=(data or {}).get("charged_points"))
        return data

    _AUDIO_QUOTE_KEYS = {"tts": ("model", "input", "voice", "speed", "response_format"),
                         "music": ("model", "lyrics", "prompt", "response_format")}

    def _h_audio_quote(self, a, kind):
        body = {k: a[k] for k in self._AUDIO_QUOTE_KEYS[kind] if k in a}
        sheet = (self.wb.speech_quote if kind == "tts" else self.wb.music_quote)(body)
        qid = sheet.get("quote_id") if isinstance(sheet, dict) else None
        if qid is None and kind == "music":
            jid = sheet.get("id") if isinstance(sheet, dict) else None
            if jid:
                self.ledger.record_job(jid, "music", self.session, {"via": "no-confirmation"})
                self.ledger.record_spend("music", self.session, ref=jid)
            self._spent_unknown = True
            return {"warning": "平台沒有回確認單——配樂工作已經被直接建立，這一趟就扣款了。",
                    "job": sheet}
        if qid is not None:
            pts = sheet.get("charge_points")
            if pts is None:
                pts = (sheet.get("estimate") or {}).get("points")
            try:
                self._quoted[qid] = float(pts) if pts is not None else None
            except (TypeError, ValueError):
                self._quoted[qid] = None
        return sheet

    def _h_audio_confirm(self, a):
        self._charge(self._price_of(a["quote_id"]), "audio_confirm")
        if a["kind"] == "tts":
            data = self.wb.speech_confirm(a["quote_id"])
        else:
            data = self.wb.music_confirm(a["quote_id"])
            jid = data.get("id") if isinstance(data, dict) else None
            if jid:
                self.ledger.record_job(jid, "music", self.session,
                                  {"quote_id": a["quote_id"], "via": "mcp"})
        self.ledger.record_spend(a["kind"], self.session, quote_id=a["quote_id"],
                            ref=(data or {}).get("id") if isinstance(data, dict) else None)
        return data

    def _h_audio_fetch(self, a):
        got = self.wb.music_content(a["job_id"])
        url = ((got or {}).get("audio") or {}).get("url") or ""
        m = re.match(r"^/api/audio/content\?sha=([0-9a-f]{64})$", url)
        if not m:
            if url.startswith("data:"):
                blob = base64.b64decode(url.split(",", 1)[1])
            else:
                return {"error": "studio 沒回可下載的音檔", "detail": got}
        else:
            blob = self.wb.audio_content(m.group(1))
        self.download_dir.mkdir(parents=True, exist_ok=True)
        path = self._dl_path(a.get("filename") or "%s.mp3" % a["job_id"])
        path.write_bytes(blob)
        return {"path": str(path), "bytes": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest()}

    def _h_post_process(self, a):
        self._charge(a["max_points"], "post_process")
        data = self.wb.post_process(a["job_id"], a["audio_style"],
                                    a.get("intensity"))
        pid = data.get("id") if isinstance(data, dict) else None
        if pid:
            self.ledger.record_job(pid, "post-process", self.session,
                              {"of": a["job_id"], "via": "mcp"})
        self.ledger.record_spend("post-process", self.session, ref=pid)
        return data

def _shot_conflict(call):
    try:
        return call()
    except ApiError as e:
        p = e.payload if isinstance(e.payload, dict) else {}
        err = p.get("error") if isinstance(p.get("error"), dict) else {}
        if e.status == 409 and err.get("code") == "conflict" and "current" in p:
            return {"error": err.get("message") or "被改過了，沒有寫入", "code": "conflict", "current": p["current"], "written": False}
        raise

def _submit_approved(wb, a):
    try:
        return wb.approval_submit(a["approval_id"], a.get("expect_amount"))
    except ApiError as e:
        if e.status == 409 and isinstance(e.payload, dict) and e.payload.get("repriced"):
            return dict(e.payload)
        raise

_SHOT_INPUTS = {
    "first_frame": {"type": "string"},
    "image_url": {"type": "string"},
    "last_frame": {"type": "string"},
    "input_references": {"type": "array", "items": {"type": "object"}},
    "cast": {"anyOf": [{"type": "boolean"}, {"type": "array", "items": {}}]},
    "cast_shot": {"type": "integer", "minimum": 1},
    "controls": {"type": "object"},
}
_SHOT_INPUTS_DOC = (
    "首幀 first_frame（或 image_url）、尾幀 last_frame（圖片網址、data URI 或 asset://）：依 model_caps 換成那一家吃的欄位"
    "（gputw 是 frame_images 字串陣列、sailflow 是 image_url；沒實測的照工作台預設送、回應的 frames_note 會寫 untested）；"
    "參考圖 input_references＝[{type: image|video|audio, url, role}]。首尾幀跟參考圖互斥（跟工作台一樣），兩種都帶會回錯。"
    "cast=true＝用角色庫：提示詞裡的 @名字 換成外觀描述、角色卡的參考圖接進 input_references（鎖臉）；"
    "cast=[\"名字\",…]＝角色庫裡這幾個（沒 @ 也附）；cast_shot＝第幾鏡（換裝的範圍用）。"
    "controls＝導演控制：camera_move（static、pan_left、pan_right、tilt_up、tilt_down、dolly_in、dolly_out、zoom_in、zoom_out、truck_left、truck_right、pedestal_up、pedestal_down、arc、tracking、handheld、whip_pan、crane_up、crane_down、aerial、tiny_planet、orbit_360、bullet_time、camera_roll、dolly_zoom、rack_focus、crash_zoom、fpv_drone、top_down_drop、bolt_cam 其中一個；一鏡只放一種）、speed（slow／medium／fast）、direction、end（停在哪）、"
    "lens、color、light、location、sound、style、allow_cuts；運鏡寫在提示詞最前面，有運鏡就加一鏡到底。"
    "角色卡的 notes（表演筆記）在 cast 時自動帶進提示詞。"
    "回應的 cast_refs 會寫有沒有套上（applied）與原因代碼；伺服器的 STUDIO_CAST_REFS 沒開時 applied=false。")

def _work_create(wb, a):
    if a.get("dry_run") and not a.get("template"):
        raise ValidationError("dry_run 只給範本作品用（template）：一般分鏡沒有預覽，會真的建作品")
    return wb.work_create(a["name"], a.get("shots"), a.get("script"), a.get("model"),
                          a.get("template"), a.get("fields"), dry_run=a.get("dry_run") is True, story=a.get("story"))

def _parse_shots(wb, a):
    if bool(a.get("text")) == bool(a.get("story")):
        raise ValidationError("text（腳本）與 story（故事）給一個")
    return wb.parse_shots(a.get("text"), a.get("model"), story=a.get("story"))

def _shot_payload(a):
    body = dict(a)
    first = body.pop("first_frame", None) or body.pop("image_url", None)
    body.pop("image_url", None)
    last = body.pop("last_frame", None)
    if (first or last) and body.get("input_references"):
        raise ValidationError("首尾幀（first_frame／last_frame）跟參考圖（input_references）只能選一種")
    try:
        extra, _notes = model_caps.frames_payload(body.get("model"), first, last)
    except model_caps.CapsError as e:
        raise ValidationError(str(e))
    body.update(extra)
    return model_caps.with_res_default(body)

_GATED_TOOLS = {"voice_line": "STUDIO_VOICE_LINE", "lipsync_shot": "STUDIO_LIPSYNC_SHOT",
                "dub_lipsync_shot": "STUDIO_TTS_FIRST"}

_MP3_BITRATE = {1: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
                2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)}
_MP3_RATE = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}

def _audio_mime(raw, hint=None):
    if raw[:4] == b"RIFF":
        return "audio/wav"
    if raw[:3] == b"ID3" or (len(raw) > 1 and raw[0] == 0xFF and raw[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    return hint or "audio/mpeg"

def _audio_seconds(raw):
    raw = bytes(raw or b"")
    if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
        i, rate, size = 12, None, None
        while i + 8 <= len(raw):
            cid, n = raw[i:i + 4], int.from_bytes(raw[i + 4:i + 8], "little")
            if cid == b"fmt " and n >= 12:
                rate = int.from_bytes(raw[i + 16:i + 20], "little")
            elif cid == b"data":
                size = min(n, len(raw) - i - 8)
                break
            i += 8 + n + (n & 1)
        return round(size / rate, 3) if rate and size else None
    i = 0
    if raw[:3] == b"ID3" and len(raw) >= 10:
        i = 10 + ((raw[6] & 0x7F) << 21 | (raw[7] & 0x7F) << 14 | (raw[8] & 0x7F) << 7 | (raw[9] & 0x7F))
        i += 10 if raw[5] & 0x10 else 0
    total = 0.0
    while i + 4 <= len(raw):
        h = int.from_bytes(raw[i:i + 4], "big")
        ver, layer = (h >> 19) & 3, (h >> 17) & 3
        br_i, sr_i, pad = (h >> 12) & 15, (h >> 10) & 3, (h >> 9) & 1
        if (h >> 21) != 0x7FF or ver == 1 or layer != 1 or br_i in (0, 15) or sr_i == 3:
            break
        br = _MP3_BITRATE[1 if ver == 3 else 2][br_i] * 1000
        rate = _MP3_RATE[ver][sr_i]
        samples = 1152 if ver == 3 else 576
        total += samples / rate
        i += samples // 8 * br // rate + pad
    return round(total, 3) if total else None

def gate_on(name):
    return os.environ.get(_GATED_TOOLS[name], "").strip().lower() in ("1", "on", "true")

def cast_mode():
    v = os.environ.get("STUDIO_CAST_REFS", "").strip().lower()
    return v if v in ("legacy", "blocks", "shadow") else "legacy"

def _duration_rule(model):
    try:
        import studio_tools
    except ImportError:
        return {"min": 4, "max": 15}
    return studio_tools.duration_rule(model)

def needs_human(r):
    if not isinstance(r, dict):
        return None
    if r.get("pending_confirmation"):
        return {"pending_id": r.get("pending_id")}
    if r.get("status") == "needs_confirmation" and r.get("quote_id") and r.get("approval"):
        out = {"status": "needs_confirmation", "quote_id": r["quote_id"], "approval": r.get("approval")}
        if r.get("note"):
            out["note"] = r["note"]
        return out
    return None

_SPENDING_NAMES = ("video_confirm", "submit_approved", "image_generate", "audio_confirm", "post_process",
                   "shots_confirm", "character_angles", "storyboard_ai",
                   "voice_line",
                   "dub_lipsync_shot",
                   "youtube_upload", "youtube_retry", "youtube_playlist_create", "youtube_auto_set",
                   "pitch_create")
_DESTRUCTIVE_NAMES = ("project_delete", "asset_delete", "store_delete")
_LOCAL_DIRCTL_TOOLS = ("dirctl_catalog", "dirctl_compose", "previs_rig", "shot_dirctl_set")
_LOCAL_UNREACHABLE = ("export_request", "agent_pending_status", "export_download",
                      "image_outpaint", "post_process", "post_process_status", "post_process_fetch",
                      "video_download_url", "post_process_download_url", "asset_download_url", "audio_music_download_url")
_LOGOUT_NAMES = ("session_logout",)
_TOPUP_NAMES = ("wallet_topup_intent",)
_LOCAL_FILE_TOOLS = ("video_fetch", "post_process_fetch", "audio_music_fetch", "asset_fetch")
_LOCAL_UI_TOOLS = ("ui_actions_list", "ui_get", "ui_compose", "ui_edit", "ui_preview", "ui_save", "ui_apply", "ui_reset",
                   "ui_undo", "ui_onboarding_status")
_LOCAL_AGENT_TOOLS = ("agent_plan", "agent_run", "agent_answer", "agent_film_preview", "agent_pick", "work_run")
_LOCAL_MEDIA_TOOLS = ("video_concat", "agent_settings")

class _NoLedger:

    @staticmethod
    def record_job(*a, **k):
        return None

    @staticmethod
    def record_spend(*a, **k):
        return None
