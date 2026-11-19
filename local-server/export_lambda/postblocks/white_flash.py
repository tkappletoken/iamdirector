from .base import Block

def flash_filters(effects):
    return ["drawbox=x=0:y=0:w=iw:h=ih:color=white@1:t=fill:enable='between(t,%s,%s)'" % (e["start"], e["end"])
            for e in effects if e.get("type") == "white_flash"]

class WhiteFlash(Block):
    id = "white_flash"
    label = "白閃"
    stage = "overlay"
    params = {"items": {"type": "list", "default": []}}

    def overlay(self, p, c):
        fx = flash_filters(p.get("items") or [])
        if fx:
            c.graph.append("[%s]%s[vfx]" % (c.last, ",".join(fx)))
            c.last = "vfx"
