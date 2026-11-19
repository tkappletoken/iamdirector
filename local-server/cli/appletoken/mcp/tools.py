
import base64
import hashlib
import mimetypes
import re
from pathlib import Path

from ..core import (STILL_RUNNING_HINT, ApiError, Workbench, is_confirmation,
                    poll_post_process, poll_video)
from .activity import Feed, describe
from ..core.api import AUDIO_STYLES, PP_POLL_MAX_TRIES, PP_POLL_SLOW
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
            "shots 是 [{prompt, seconds?}]（1–30 鏡）；或給 script（「Shot 1｜0-3s …」那種腳本）讓伺服器拆鏡；"
            "或給 template='meme'（迷因短片：一鏡到底、固定鏡頭、9:16、11–15 秒）＋fields"
            "（setup 前段情境、twist_at 第幾秒反轉、chaos 後段暴走；選填 seconds、resolution＝720p／1080p（預設 720p）、"
            "characters＝角色外觀描述（提示詞裡用到名字就要寫，不然模型不知道長什麼樣子）、extra_negative＝追加的 negative"
            "（接在內建的後面，內建的刪不掉）、props＝道具（120 字內，明確寫進提示詞）、visual_cues＝一定要看得見的元素（120 字內）、"
            "allow_cuts＝允許切鏡頭（預設 false＝一鏡到底）、count_animals（預設 true：characters 寫成「名字: 描述; …」"
            "就自動加 Only N animals in the entire video）、cap_setup、cap_twist、flash_before、style＝meme／memebox）。"
            "範本的 negative 與「只用環境音」由伺服器寫，報價用 quote_work；回應的 warnings 要看。",
            _obj({"name": {"type": "string", "minLength": 1},
                  "shots": {"type": "array", "items": {"type": "object"}},
                  "script": {"type": "string"}, "model": {"type": "string"},
                  "template": {"type": "string", "enum": ["meme"]}, "fields": {"type": "object"}}, ["name"]),
            lambda a: wb.work_create(a["name"], a.get("shots"), a.get("script"), a.get("model"),
                                     a.get("template"), a.get("fields")))

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
            "overrides 可改 captions／effects／twist（例如 {\"twist\": {\"at\": 9.6}}）。回匯出 id，用 result(export_id) 拿檔案。",
            _obj({"project_id": {"type": "string"}, "job_id": {"type": "string"}, "overrides": {"type": "object"}},
                 ["project_id", "job_id"]),
            lambda a: wb.work_export(a["project_id"], a["job_id"], a.get("overrides")))

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
            "你自己核准不了。核准之後用 submit_approved 送出。",
            _obj({"model": {"type": "string"}, "prompt": {"type": "string"},
                  "seconds": {"type": "integer"}, "resolution": {"type": "string"},
                  "aspect_ratio": {"type": "string"}, "negative_prompt": {"type": "string"},
                  "generate_audio": {"type": "boolean"},
                  "input_references": {"type": "array", "items": {"type": "object"}}},
                 ["model", "prompt"]),
            lambda a: wb.approval_quote(dict(a)))

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
            "不建工作、不扣款。要真的送出，把回傳的 quote_id 交給 video_confirm。",
            _obj({"model": {"type": "string"}, "prompt": {"type": "string"},
                  "seconds": {"type": "integer"},
                  "resolution": {"type": "string"},
                  "aspect_ratio": {"type": "string"},
                  "negative_prompt": {"type": "string"},
                  "generate_audio": {"type": "boolean"}},
                 ["model", "prompt"]),
            self._h_quote)

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
            "dry_run=true 只試算、不鎖單。",
            _obj({"story": {"type": "string"}, "shots": {"type": "integer", "minimum": 1, "maximum": 12},
                  "style": {"type": "string"}, "video_model": {"type": "string"},
                  "project_id": {"type": "string"}, "dry_run": {"type": "boolean"}}, ["story"]),
            lambda a: wb.storyboard_ai_quote(a["story"], a.get("shots", 6), a.get("style"), a.get("video_model"),
                                             a.get("project_id"), dry_run=bool(a.get("dry_run"))))

        add("parse_shots",
            "把一整段分鏡腳本切成一顆一顆鏡頭。**純字串處理，不叫 AI、不花錢。**"
            "每顆會回 prompt 與 seconds，那兩個直接就是 video_quote 的參數。"
            "⚠ **seconds 只有在那一顆自己寫了時間範圍時才有值**"
            "（例如「鏡頭1 00:00-00:05」），沒寫的話是 null——"
            "那時候不要把 null 送給 video_quote，讓平台自己決定長度。"
            "帶 model 的話 seconds 會先對齊那個模型收得下的長度，"
            "被調整過時 adjust_note 會說明。",
            _obj({"text": {"type": "string"}, "model": {"type": "string"}},
                 ["text"]),
            lambda a: wb.parse_shots(a["text"], a.get("model")))

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
                "作品是允許切鏡頭的（迷因範本 fields.allow_cuts=true）才帶 allow_cuts=true：切鏡頭不算瑕疵；預設不帶。",
                _obj({"job_id": {"type": "string"},
                      "frames": {"type": "array", "items": {"type": "string"}},
                      "expect": {"type": "array", "items": {"type": "object"}},
                      "allow_cuts": {"type": "boolean"}}, ["job_id", "frames"]),
                lambda a: wb.qc(a["job_id"], a.get("frames"), a.get("expect"), a.get("allow_cuts") is True), spends=True)

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
                      "project_id": {"type": "string"},
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
                "角色多角度參考圖（正面／側面／背面／四分之三）：每一個角度一次 image_generate。"
                "**會扣款**，每一張都要在 max_points_each 以內（先估價，超過就不送）。"
                "生好之後用 asset_upload 放進素材庫，就能當 video_quote 的 input_references。",
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

    def _h_storyboard_quote(self, a):
        out, total, unknown = [], 0.0, False
        for i, sh in enumerate(a["shots"]):
            body = {k: v for k, v in sh.items() if v not in (None, "")}
            body.setdefault("model", a["model"])
            for k in ("resolution", "aspect_ratio"):
                if a.get(k) and k not in body:
                    body[k] = a[k]
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
                "pending": [r.get("pending_id") for r in res if r.get("pending_confirmation")],
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
            if isinstance(r, dict) and r.get("pending_confirmation"):
                out.append({"angle": ang, "pending_id": r.get("pending_id")})
                continue
            urls = [d.get("url") for d in (r or {}).get("data") or [] if isinstance(d, dict)]
            out.append({"angle": ang, "urls": urls, "charged_points": (r or {}).get("charged_points")})
        return {"name": a["name"], "angles": out,
                "next": "要當參考圖：asset_upload(url=…) 拿 asset://，再放進 video_quote 的 input_references"}

    def _h_image(self, a):
        payload = {k: v for k, v in a.items() if k != "max_points"}
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
                            points=(data or {}).get("price_charged"),
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
                                            a.get("project_id"))
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

def _submit_approved(wb, a):
    try:
        return wb.approval_submit(a["approval_id"], a.get("expect_amount"))
    except ApiError as e:
        if e.status == 409 and isinstance(e.payload, dict) and e.payload.get("repriced"):
            return dict(e.payload)
        raise

_SPENDING_NAMES = ("video_confirm", "submit_approved", "image_generate", "audio_confirm", "post_process",
                   "shots_confirm", "character_angles", "storyboard_ai",
                   "youtube_upload", "youtube_retry", "youtube_playlist_create", "youtube_auto_set",
                   "pitch_create")
_DESTRUCTIVE_NAMES = ("project_delete", "asset_delete", "store_delete")
_LOGOUT_NAMES = ("session_logout",)
_TOPUP_NAMES = ("wallet_topup_intent",)
_LOCAL_FILE_TOOLS = ("video_fetch", "post_process_fetch", "audio_music_fetch", "asset_fetch")

class _NoLedger:

    @staticmethod
    def record_job(*a, **k):
        return None

    @staticmethod
    def record_spend(*a, **k):
        return None
