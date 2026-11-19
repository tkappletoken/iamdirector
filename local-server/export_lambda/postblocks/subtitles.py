from .base import Block
from .subs import SUB_STYLE

class Subtitles(Block):
    id = "subtitles"
    label = "字幕"
    stage = "text"
    params = {"mode": {"type": "enum", "values": ["burn", "srt", "both", "none"], "default": "none"},
              "font_scale": {"type": "number", "min": 0.03, "max": 0.09, "default": SUB_STYLE["font_scale"]},
              "margin_v": {"type": "number", "min": 0.02, "max": 0.3, "default": SUB_STYLE["margin_v"]}}

    def text(self, p, c):
        c.text["mode"] = p.get("mode") or "none"
        c.text["style"] = {k: p[k] for k in SUB_STYLE if p.get(k) is not None}
