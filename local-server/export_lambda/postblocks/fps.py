from .base import Block

class Fps(Block):
    id = "fps"
    label = "影格率"
    stage = "source"
    locked = True
    params = {"fps": {"type": "enum", "values": [24, 25, 30], "default": 24}}

    def clip(self, p, c, k, v, chain):
        chain["rate"] = "fps=%d" % c.fps
