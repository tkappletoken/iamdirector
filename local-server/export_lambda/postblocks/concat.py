from .base import Block

class Concat(Block):
    id = "concat"
    label = "拼接"
    stage = "timeline"
    locked = True

    def timeline(self, p, c):
        c.graph.append("%sconcat=n=%d:v=1:a=0[vcat]" % ("".join(c.vlabels), len(c.vlabels)))
        c.last = "vcat"
