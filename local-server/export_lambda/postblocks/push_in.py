import os

from .base import Block, PipelineError

ENV = "STUDIO_POSTBLOCK_PUSH_IN"

def enabled():
    return os.environ.get(ENV, "").strip().lower() in ("1", "on", "true")

class PushIn(Block):
    id = "push_in"
    label = "裁切推近"
    stage = "overlay"
    optional = True
    drop_on_fail = True
    params = {"amount": {"type": "number", "min": 1.02, "max": 1.3, "default": 1.1},
              "ease": {"type": "enum", "values": ["linear", "in_out"], "default": "linear"}}

    def validate(self, p):
        return p

    @staticmethod
    def zoom(p, body):
        a = round(float(p["amount"]) - 1, 4)
        u = "min(t/%s\\,1)" % round(float(body), 3)
        if p["ease"] == "in_out":
            u = "(0.5-0.5*cos(PI*%s))" % u
        return "(1+%s*%s)" % (a, u)

    def filters(self, p, W, H, body):
        if not body or body <= 0:
            raise PipelineError("push_in：本體長度是 0，沒辦法推近")
        z = self.zoom(p, body)
        return ("scale=w='trunc(%d*%s/2)*2':h='trunc(%d*%s/2)*2':eval=frame,crop=%d:%d:(iw-%d)/2:(ih-%d)/2,setsar=1"
                % (W, z, H, z, W, H, W, H))

    def overlay(self, p, c):
        c.graph.append("[%s]%s[vpush]" % (c.last, self.filters(p, c.W, c.H, c.t["body"])))
        c.last = "vpush"
