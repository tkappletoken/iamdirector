from .base import Block

def card_lines(disclosure):
    if not disclosure.get("on"):
        return []
    lines = [disclosure.get("text") or ""]
    if disclosure.get("models"):
        lines.append("使用的 AI 模型：" + "、".join(disclosure["models"]))
    return [x for x in lines if x]

class Disclosure(Block):
    id = "disclosure"
    label = "AI 揭露片尾"
    stage = "append"
    params = {"disclosure": {"type": "object", "default": {"on": False}}}

    def append(self, p, c):
        if c.t["card"]:
            c.graph.append("color=c=black:s=%dx%d:r=%d:d=%s,format=yuv420p,setsar=1[vcard]" % (c.W, c.H, c.fps, c.t["card"]))
            c.graph.append("[%s][vcard]concat=n=2:v=1:a=0[vall]" % c.last)
            c.last = "vall"

    def text(self, p, c):
        c.text["card"] = card_lines(p.get("disclosure") or {})
