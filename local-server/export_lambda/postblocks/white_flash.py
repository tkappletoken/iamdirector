from .base import Block

class WhiteFlash(Block):
    id = "white_flash"
    label = "白閃"
    stage = "overlay"
    params = {"items": {"type": "list", "default": []}}

    def overlay(self, p, c):
        import render
        fx = render.flash_filters(p.get("items") or [])
        if fx:
            c.graph.append("[%s]%s[vfx]" % (c.last, ",".join(fx)))
            c.last = "vfx"
