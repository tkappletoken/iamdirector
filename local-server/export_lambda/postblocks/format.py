from .base import Block

class Format(Block):
    id = "format"
    label = "畫面格式"
    stage = "source"
    locked = True
    params = {"aspect": {"type": "enum", "values": ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"], "default": "16:9",
                         "from_spec": True},
              "resolution": {"type": "enum", "values": ["480p", "720p", "1080p"], "default": "1080p", "from_spec": True}}

    def size(self, p):
        import render
        return render.frame_size(p.get("aspect") or "16:9", p.get("resolution") or "1080p")
