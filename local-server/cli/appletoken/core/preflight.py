
REF_SECONDS_NOTE = (
    "參考素材裡有影片：成品長度由參考影片決定，而平台用你給的 seconds 估價預扣。"
    "已知這兩者會對不上（實測過報價 0.697 點、結算 3.88 點的案例），"
    "而且結算不夾制、餘額可能被扣成負值。"
    "送正數就好——gateway 自己會把送給上游的值改成 -1，不要跟著工作台前端送 -1。")

FACE_ASSET_NOTE = (
    "有參考素材是直接給網址或 data URI。"
    "**含可辨識真人臉孔的素材一定要先上傳成 asset://**——"
    "直接給網址的話任務會失敗，而且額度照扣。"
    "先跑 `at assets upload <檔案>`，再用回傳的 reference。")

PROCESSING_ASSET_NOTE = (
    "有素材還在 processing。引用還沒 active 的素材會被擋成 400——"
    "先等它變 active 再送。")

def _refs(payload):
    r = payload.get("input_references")
    return r if isinstance(r, list) else []

def has_video_reference(payload):
    for ref in _refs(payload):
        if isinstance(ref, dict) and str(ref.get("type", "")).lower() == "video":
            return True
    return False

def has_inline_reference(payload):
    for ref in _refs(payload):
        if not isinstance(ref, dict):
            continue
        url = str(ref.get("url") or "")
        if url and not url.startswith("asset://"):
            return True
    return False

def warnings_for(payload, assets_by_id=None):
    notes = []
    if has_video_reference(payload):
        notes.append(REF_SECONDS_NOTE)
    if has_inline_reference(payload):
        notes.append(FACE_ASSET_NOTE)
    if assets_by_id:
        for ref in _refs(payload):
            if not isinstance(ref, dict):
                continue
            url = str(ref.get("url") or "")
            if url.startswith("asset://"):
                a = assets_by_id.get(url[len("asset://"):])
                if a and a.get("status") and a["status"] != "active":
                    notes.append(PROCESSING_ASSET_NOTE)
                    break
    return notes
