from .base import Block

class MusicDuck(Block):
    id = "music_duck"
    label = "配樂自動壓低"
    stage = "audio"
    optional = True
    params = {"amount": {"type": "enum", "values": ["light", "medium", "strong"], "default": "medium"},
              "release": {"type": "number", "min": 50, "max": 2000, "default": 400}}

    RATIO = {"light": 3, "medium": 6, "strong": 12}

    def filter(self, p):
        return "sidechaincompress=threshold=0.03:ratio=%d:attack=20:release=%d" % (
            self.RATIO[p.get("amount") or "medium"], int(p.get("release") or 400))
