from .base import Block, PipelineError

class Speed(Block):
    id = "speed"
    label = "變速"
    stage = "output"
    optional = True
    drop_on_fail = True
    params = {"factor": {"type": "number", "min": 0.5, "max": 2, "default": 1.25}}

    def validate(self, p):
        if p["factor"] == 1:
            raise PipelineError("speed.factor 是 1，等於沒變速")
        return p

    def finish(self, p, c):
        if c.soft:
            raise PipelineError("speed：有軟字幕軌時不能變速（字幕時間不會跟著變）")
        f = round(float(p["factor"]), 4)
        c.graph.append("[%s]setpts=PTS/%s[vspd]" % (c.last, f))
        c.graph.append("[%s]atempo=%s[aspd]" % (c.alast, f))
        c.last, c.alast = "vspd", "aspd"
        c.t = dict(c.t, total=round(c.t["total"] / f, 3))
