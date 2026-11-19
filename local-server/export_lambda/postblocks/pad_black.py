from .base import Block

class PadBlack(Block):
    id = "pad_black"
    label = "補黑"
    stage = "timeline"
    locked = True

    def timeline(self, p, c):
        pad = round(c.t["body"] - c.t["v1"], 3)
        if pad > 0.001:
            c.graph.append("[vcat]tpad=stop_mode=add:stop_duration=%s:color=black[vbody]" % pad)
            c.last = "vbody"
