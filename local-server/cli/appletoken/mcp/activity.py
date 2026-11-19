
import json
import sys
import time

from ..core import redact_obj

KEY = "agent-activity"

MAX_EVENTS = 30

SCHEMA = 1

def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")

class Feed:

    def __init__(self, wb, session=None, enabled=True, max_events=MAX_EVENTS):
        self.wb = wb
        self.enabled = enabled
        self.max_events = max_events
        self.who = getattr(session, "fingerprint", None)
        self.events = []
        self._warned = False
        self._loaded = False

    def _warn(self, why):
        if self._warned:
            return
        self._warned = True
        print("⚠  動態寫不進工作台（%s）。工具本身不受影響；"
              "要關掉這個功能用 --no-activity。" % why, file=sys.stderr)

    def _load_once(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            got = self.wb.store_get(KEY)
        except Exception:
            return
        val = (got or {}).get("value")
        if isinstance(val, dict) and val.get("v") == SCHEMA:
            old = val.get("events")
            if isinstance(old, list):
                self.events = [e for e in old if isinstance(e, dict)][-self.max_events:]

    def _flush(self):
        try:
            self.wb.store_put(KEY, {"v": SCHEMA, "events": self.events})
        except Exception as e:
            self._warn(e)

    def record(self, tool, ok=True, note=None, ref=None, args=None, result=None):
        if not self.enabled:
            return None
        self._load_once()
        row = {"at": _now(), "tool": tool, "ok": bool(ok)}
        if note:
            row["note"] = redact_obj(str(note))[:200]
        if ref:
            row["ref"] = str(ref)[:80]
        if self.who:
            row["who"] = self.who
        self.events.append(row)
        del self.events[:-self.max_events]
        self._flush()
        return row

    def clear(self):
        if not self.enabled:
            return
        self.events = []
        self._loaded = True
        self._flush()

def describe(tool, arguments, result):
    a = arguments or {}
    r = result if isinstance(result, dict) else {}

    def _short(s, n=60):
        s = str(s or "").strip().replace("\n", " ")
        return (s[:n] + "…") if len(s) > n else s

    if tool == "video_quote":
        pts = ((r.get("estimate") or {}).get("points")
               if isinstance(r.get("estimate"), dict) else None)
        return ("報價：%s／%s%s" % (
            a.get("model") or "?", _short(a.get("prompt")),
            "　%s 點" % pts if pts is not None else ""))
    if tool == "video_confirm":
        return "送出影片（確認單 %s）" % _short(a.get("quote_id"), 24)
    if tool == "image_generate":
        return "生成圖片：%s／%s" % (a.get("model") or "?", _short(a.get("prompt")))
    if tool == "post_process":
        return "音軌後處理：%s → %s" % (_short(a.get("job_id"), 24),
                                        a.get("audio_style") or "?")
    if tool in ("video_fetch", "post_process_fetch"):
        return "取件：%s（%s bytes）" % (_short(r.get("path"), 40), r.get("bytes"))
    if tool == "asset_upload":
        return "上傳素材：%s" % _short(a.get("name") or a.get("path") or a.get("url"), 40)
    if tool == "asset_delete":
        return "刪除素材 %s" % _short(a.get("asset_id"), 30)
    if tool == "parse_shots":
        n = len(r.get("shots") or []) if isinstance(r.get("shots"), list) else "?"
        return "拆分鏡：%s 顆" % n
    if tool == "build_captions":
        return "產字幕：%s 句（%s）" % (r.get("cues"), r.get("format") or "?")
    if tool in ("store_put", "store_delete"):
        return "%s KV：%s" % ("寫入" if tool == "store_put" else "刪除",
                              _short(a.get("key"), 32))
    if tool in ("project_create", "project_rename", "project_delete",
                "project_add_item", "project_remove_item"):
        return {"project_create": "建立專案分組：%s" % _short(a.get("name"), 30),
                "project_rename": "專案分組改名：%s" % _short(a.get("name"), 30),
                "project_delete": "刪除專案分組",
                "project_add_item": "把作品放進分組",
                "project_remove_item": "把作品移出分組"}[tool]
    if tool == "wallet_topup_intent":
        return "建立付款頁：%s" % a.get("amount")
    if tool == "session_logout":
        return "登出"
    if tool == "storyboard_quote":
        n = len(r.get("shots") or []) if isinstance(r.get("shots"), list) else "?"
        tot = r.get("total_points")
        return "分鏡報價：%s 鏡%s" % (n, "，合計 %s 點" % tot if tot is not None else "")
    if tool == "storyboard_ai_quote":
        return "AI 分鏡報價：%s 鏡%s" % (a.get("shots", 6), "，最多 %s 點" % r.get("charge_points")
                                       if r.get("charge_points") is not None else "")
    if tool == "storyboard_ai":
        return "AI 拆成 %s 鏡%s" % (len(r.get("shots") or []) if isinstance(r.get("shots"), list) else "?",
                                  "，實扣 %s 點" % r.get("charged_points") if r.get("charged_points") is not None else "")
    if tool == "shots_confirm":
        return "逐張送出：%s 張送件、%s 張等你核准" % (len(r.get("jobs") or []), len(r.get("pending") or []))
    if tool == "character_angles":
        return "角色多角度：%s（%s 個角度）" % (_short(a.get("name"), 20), len(a.get("angles") or []) or 4)
    plain = {"director_plan": "讀導演工作流與工作台現況", "list_models": "看模型目錄",
             "get_balance": "看額度", "list_assets": "看素材庫", "list_projects": "看專案分組",
             "estimate": "估價（免費）", "payer_state": "看付款方", "agent_pending_status": "查待核准的結果",
             "video_status": "查影片狀態", "video_wait": "等影片完成", "wallet_balance": "看本站點數"}
    if tool in plain:
        return plain[tool]
    return tool
