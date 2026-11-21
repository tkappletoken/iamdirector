
ACTIONS = {
    "export.open":    {"feature": "export",        "call": "__R7__.open",           "spend": "confirm", "label": "匯出"},
    "blocks.move":    {"feature": "post_blocks",   "call": "__BLOCKS__.move",       "spend": "none",    "label": "調整積木順序"},
    "meme.load":      {"feature": "meme",          "call": "__MEME__.load",         "spend": "none",    "label": "迷因字卡",
                       "args": "current_work"},
    "sound.open":     {"feature": "tts",           "call": "__R6__.openSound",      "spend": "confirm", "label": "聲音"},
    "cast.turn":      {"feature": "cast",          "call": "__R6__.openTurn",       "spend": "confirm", "label": "角色多角度",
                       "args": "current_cast"},
    "puppet.open":    {"feature": "puppet",        "call": "__R6__.openPuppet",     "spend": "none",    "label": "人偶預演",
                       "args": "current_shot"},
    "previs.open":    {"feature": "previs",        "call": "__R4__.open",           "spend": "none",    "label": "3D 預演"},
    "takes.open":     {"feature": "retake",        "call": "__R5__.openTakes",      "spend": "none",    "label": "挑版本",
                       "args": "current_clip"},
    "gate.pick":      {"feature": "cand_gate",     "call": "__R5__.openTakes",      "spend": "none",    "label": "挑定稿",
                       "args": "pending_clip"},
    "approve.batch":  {"feature": "approval",      "call": "__BATCH_CONFIRM__.run", "spend": "confirm", "label": "一起確認"},
    "youtube.open":   {"feature": "youtube_upload", "call": "__YT__.open",          "spend": "none",    "label": "上架 YouTube"},
    "pitch.open":     {"feature": "pitch_package", "call": "__PITCH__.open",        "spend": "none",    "label": "投稿包"},
    "agent.open":     {"feature": "agent_activity", "call": "__AGENT_PANEL__.open", "spend": "none",    "label": "Agent 協作"},
    "mode.set":       {"feature": "workflow",      "call": "__SIMPLE__.setMode",    "spend": "none",    "label": "切換模式",
                       "args": "toggle_mode"},
    "generate.open":  {"feature": "video_quote",   "call": "__GENERATE__.open",     "spend": "confirm", "label": "開拍"},
    "agent.panel":    {"feature": "agent_activity", "call": "__AGENTRUN__.open",    "spend": "none",    "label": "Agent 拍片進度",
                       "local": True},
}
LOCAL_ONLY = tuple(k for k, v in ACTIONS.items() if v.get("local"))
ARG_KINDS = {
    "current_clip": "時間軸上選中的那一格（要有兩個以上版本）；沒選就用第一個有多個版本的格子",
    "pending_clip": "還在等人挑定稿的那一格；沒有就同 current_clip",
    "current_cast": "正在編輯的角色卡（要有照片）；沒有就用第一張有照片的角色卡",
    "current_shot": "正在編輯的那一鏡（要有參考影片、還沒轉人偶）；沒有就用第一個符合的鏡頭",
    "current_work": "目前打開的作品",
    "toggle_mode": "切到另一個模式（主線 ↔ 進階工作台）",
}

COMPONENTS = {
    "stage":        {"label": "主線目前這一步", "mount": "inline", "hook": "__SIMPLE__"},
    "agent_run":    {"label": "Agent 拍片進度", "mount": "inline", "hook": "__AGENTRUN__", "local": True},
    "film_preview": {"label": "交片預覽",       "mount": "inline", "hook": "__AGENTRUN__", "local": True},
    "approvals":    {"label": "核准卡",         "mount": "inline", "hook": "__APPROVALS__"},
}

NEVER_FEATURES = ("payer_key", "wallet", "topup", "agent_tokens", "logout", "agent_pending")
SPENDS = ("none", "confirm")

def get(name):
    return ACTIONS.get(name)
