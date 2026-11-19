from .base import Block

class Encode(Block):
    id = "encode"
    label = "輸出"
    stage = "output"
    locked = True
    params = {"container": {"type": "enum", "values": ["mp4", "webm"], "default": "mp4"}}
