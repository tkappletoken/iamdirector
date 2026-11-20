
ACTIONS = {
    "export.open":    {"feature": "export",        "call": "__R7__.open",           "spend": "confirm", "label": "匯出"},
    "blocks.move":    {"feature": "post_blocks",   "call": "__BLOCKS__.move",       "spend": "none",    "label": "調整積木順序"},
    "meme.load":      {"feature": "meme",          "call": "__MEME__.load",         "spend": "none",    "label": "迷因字卡"},
    "sound.open":     {"feature": "tts",           "call": "__R6__.openSound",      "spend": "confirm", "label": "聲音"},
    "cast.turn":      {"feature": "cast",          "call": "__R6__.openTurn",       "spend": "confirm", "label": "角色多角度"},
    "puppet.open":    {"feature": "puppet",        "call": "__R6__.openPuppet",     "spend": "none",    "label": "人偶預演"},
    "previs.open":    {"feature": "previs",        "call": "__R4__.open",           "spend": "none",    "label": "3D 預演"},
    "takes.open":     {"feature": "retake",        "call": "__R5__.openTakes",      "spend": "none",    "label": "挑版本"},
    "gate.pick":      {"feature": "cand_gate",     "call": "__GATE__.pick",         "spend": "none",    "label": "挑定稿"},
    "approve.batch":  {"feature": "approval",      "call": "__BATCH_CONFIRM__.run", "spend": "confirm", "label": "一起確認"},
    "youtube.open":   {"feature": "youtube_upload", "call": "__YT__.open",          "spend": "none",    "label": "上架 YouTube"},
    "pitch.open":     {"feature": "pitch_package", "call": "__PITCH__.open",        "spend": "none",    "label": "投稿包"},
    "agent.open":     {"feature": "agent_activity", "call": "__AGENT_PANEL__.open", "spend": "none",    "label": "Agent 協作"},
    "mode.set":       {"feature": "workflow",      "call": "__SIMPLE__.setMode",    "spend": "none",    "label": "切換模式"},
    "generate.open":  {"feature": "video_quote",   "call": "__GENERATE__.open",     "spend": "confirm", "label": "開拍"},
}

NEVER_FEATURES = ("payer_key", "wallet", "topup", "agent_tokens", "logout", "agent_pending")
SPENDS = ("none", "confirm")

def get(name):
    return ACTIONS.get(name)
