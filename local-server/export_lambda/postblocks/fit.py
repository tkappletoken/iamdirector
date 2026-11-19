from .base import Block

class Fit(Block):
    id = "fit"
    label = "畫面"
    stage = "source"
    locked = True
    params = {"mode": {"type": "enum", "values": ["pad", "crop"], "default": "pad"}}

    def clip(self, p, c, k, v, chain):
        W, H = c.W, c.H
        if p.get("mode") == "crop":
            fitf = "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (W, H, W, H)
        else:
            fitf = "scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black" % (W, H, W, H)
        chain["frame"] = fitf + ",setsar=1,format=yuv420p"
