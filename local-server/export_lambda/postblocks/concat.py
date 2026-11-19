from .base import Block

class Concat(Block):
    id = "concat"
    label = "拼接"
    stage = "timeline"
    locked = True

    def timeline(self, p, c):
        tr = getattr(c, "transition", None)
        if tr and len(c.vlabels) > 1:
            from .transition import Transition
            c.graph += Transition().chain(c, [round(v["out"] - v["in"], 3) for v in c.spec["video"]])
        else:
            c.graph.append("%sconcat=n=%d:v=1:a=0[vcat]" % ("".join(c.vlabels), len(c.vlabels)))
        c.last = "vcat"
