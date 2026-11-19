from .base import Block, PipelineError

class VideoFade(Block):
    id = "video_fade"
    label = "畫面淡入淡出"
    stage = "overlay"
    optional = True
    params = {"fade_in": {"type": "number", "min": 0, "max": 3, "default": 0.5},
              "fade_out": {"type": "number", "min": 0, "max": 3, "default": 0.5}}

    def validate(self, p):
        if not (p.get("fade_in") or p.get("fade_out")):
            raise PipelineError("video_fade：淡入和淡出至少要有一個大於 0")
        return p

    def overlay(self, p, c):
        body = c.t["body"]
        fi, fo = min(p.get("fade_in") or 0, body / 2), min(p.get("fade_out") or 0, body / 2)
        parts = []
        if fi > 0:
            parts.append("fade=t=in:st=0:d=%s" % round(fi, 3))
        if fo > 0:
            parts.append("fade=t=out:st=%s:d=%s" % (round(body - fo, 3), round(fo, 3)))
        c.graph.append("[%s]%s[vfade]" % (c.last, ",".join(parts)))
        c.last = "vfade"
