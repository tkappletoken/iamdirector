from . import contract

GEN_BLOCKS = (
    {"id": "script", "line": "gen", "stage": "script", "label": "腳本（一句話 → 故事與分句）",
     "spends": False, "preview": "none", "qc": False, "redo": (),
     "api": (("POST", "/api/parse-shots"),), "mcp": ("parse_shots",), "cli": ("shots",), "local_agent": True,
     "front_only": ()},
    {"id": "storyboard", "line": "gen", "stage": "storyboard", "label": "AI 分鏡（故事 → N 鏡）",
     "spends": True, "preview": "quote", "qc": False, "redo": (),
     "api": (("POST", "/api/storyboard/quote"), ("POST", "/api/storyboard")),
     "mcp": ("storyboard_ai_quote", "storyboard_ai"), "cli": ("storyboard",), "local_agent": True,
     "front_only": ()},
    {"id": "cast", "line": "gen", "stage": "cast", "label": "角色一致（角色卡、多角度參考、鎖臉）",
     "spends": True, "preview": "quote", "qc": False, "redo": ("step",),
     "api": (("POST", "/api/image-generate"), ("POST", "/api/check-refs")),
     "mcp": ("character_angles", "check_refs"), "cli": ("image create",), "local_agent": True,
     "front_only": ()},
    {"id": "generate", "line": "gen", "stage": "generate", "label": "報價與送件（確認單、核准卡、預先授權）",
     "spends": True, "preview": "quote", "qc": False, "redo": ("shot",),
     "api": (("POST", "/api/estimate"), ("POST", "/api/generate"), ("POST", "/api/approvals"),
             ("POST", "/api/approvals/submit")),
     "mcp": ("estimate", "video_quote", "video_confirm", "request_approval", "submit_approved"),
     "cli": ("estimate", "video create", "pending"), "local_agent": True, "front_only": ()},
    {"id": "select", "line": "gen", "stage": "select", "label": "選片與重拍（多候選、挑定稿、壞段重抽）",
     "spends": True, "preview": "quote", "qc": False, "redo": (),
     "api": (), "mcp": (), "cli": (), "local_agent": False,
     "front_only": ("ui2 GATE：候選關卡與挑定稿", "ui2 bestOf／bestQc：挑最高分", "ui2 rerollMany／retakeGo：重抽")},
    {"id": "qc", "line": "gen", "stage": "qc", "label": "驗片（抽格評分）",
     "spends": True, "preview": "none", "qc": True, "redo": ("shot",),
     "api": (("POST", "/api/qc"), ("POST", "/api/qc/rate")), "mcp": ("video_qc", "qc_rate"),
     "cli": ("qc check", "qc rate"), "local_agent": True,
     "front_only": ("ui2 qcGate／needRetake：門檻與自動重拍迴圈",)},
    {"id": "sound", "line": "gen", "stage": "sound", "label": "配音與配樂",
     "spends": True, "preview": "quote", "qc": False, "redo": ("line",),
     "api": (("POST", "/api/audio/speech"), ("POST", "/api/audio/music")),
     "mcp": ("audio_speech_quote", "audio_music_quote", "audio_confirm"), "cli": ("audio speech", "audio music"),
     "local_agent": True, "front_only": ("ui2 placeMusic：配樂擺放",)},
    {"id": "publish", "line": "gen", "stage": "publish", "label": "上架準備（投稿包、YouTube）",
     "spends": False, "preview": "dry_run", "qc": True, "redo": ("step",),
     "api": (("POST", "/api/pitch/preview"), ("POST", "/api/youtube/uploads")),
     "mcp": ("pitch_preview", "pitch_create", "youtube_upload"), "cli": ("pitch preview", "youtube upload"),
     "local_agent": False, "front_only": ("ui2 seriesTitles：標題組字",)},
    {"id": "template", "line": "gen", "stage": "template", "label": "片型範本（目前只有迷因）",
     "spends": True, "preview": "quote", "qc": False, "redo": (),
     "api": (("POST", "/api/works/quote"), ("POST", "/api/works/create")),
     "mcp": ("quote_work", "create_work"), "cli": ("work create", "work quote"), "local_agent": True,
     "front_only": ()},
)

def blocks():
    return [contract.check(b) for b in GEN_BLOCKS]

def gaps():
    return {b["id"]: contract.grade(b) for b in GEN_BLOCKS}
