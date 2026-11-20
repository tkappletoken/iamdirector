from .base import Block, PipelineError

PRESETS = {
    "none": ("", 1, 1),
    "warm": ("colorbalance=rs=0.08:bs=-0.08:rm=0.05:bm=-0.05", 1, 1),
    "cool": ("colorbalance=rs=-0.08:bs=0.08:rm=-0.05:bm=0.05", 1, 1),
    "vivid": ("", 1.08, 1.35),
    "mono": ("", 1, 0),
    "film": ("colorbalance=rs=0.04:bs=-0.03:rh=0.03:bh=-0.03", 1.1, 0.85),
}
NEUTRAL = {"brightness": 0, "contrast": 1, "saturation": 1, "gamma": 1}

class ColorGrade(Block):
    id = "color_grade"
    label = "調色"
    stage = "overlay"
    optional = True
    drop_on_fail = True
    params = {"preset": {"type": "enum", "values": list(PRESETS), "default": "warm"},
              "brightness": {"type": "number", "min": -0.3, "max": 0.3, "default": 0},
              "contrast": {"type": "number", "min": 0.5, "max": 2, "default": 1},
              "saturation": {"type": "number", "min": 0, "max": 3, "default": 1},
              "gamma": {"type": "number", "min": 0.5, "max": 2, "default": 1}}

    def validate(self, p):
        if p["preset"] == "none" and all(p[k] == v for k, v in NEUTRAL.items()):
            raise PipelineError("color_grade：預設是 none 而且數值都沒動，等於沒調")
        return p

    def filters(self, p):
        bal, pc, ps = PRESETS[p["preset"]]
        c = round(pc * float(p["contrast"]), 3)
        s = round(ps * float(p["saturation"]), 3)
        b, g = round(float(p["brightness"]), 3), round(float(p["gamma"]), 3)
        out = [bal] if bal else []
        if (b, c, g) != (0, 1, 1):
            out.append("lutyuv=y='clip(minval+((pow((val-minval)/(maxval-minval),%s)-0.5)*%s+0.5+%s)*(maxval-minval),"
                       "minval,maxval)'" % (round(1 / g, 4), c, b))
        if s != 1:
            out.append("hue=s=%s" % s)
        return ",".join(out)

    def overlay(self, p, c):
        c.graph.append("[%s]%s[vgrade]" % (c.last, self.filters(p)))
        c.last = "vgrade"
