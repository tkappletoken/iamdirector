from .base import Block

class Subtitles(Block):
    id = "subtitles"
    label = "字幕"
    stage = "text"
    params = {"mode": {"type": "enum", "values": ["burn", "srt", "both", "none"], "default": "none"}}

    def text(self, p, c):
        c.text["mode"] = p.get("mode") or "none"
