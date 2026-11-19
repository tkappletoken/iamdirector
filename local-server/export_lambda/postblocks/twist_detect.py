from .base import Block

class TwistDetect(Block):
    id = "twist_detect"
    label = "反轉點"
    stage = "analyze"
    params = {"twist": {"type": "object", "default": {}}}
