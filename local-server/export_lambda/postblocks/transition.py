from .base import Block

STYLES = ("drop_first", "fade", "dissolve", "fadeblack", "fadewhite", "smoothleft", "smoothright")

class Transition(Block):
    id = "transition"
    label = "轉場"
    stage = "timeline"
    optional = True
    params = {"duration": {"type": "number", "min": 0.05, "max": 1.5, "default": 0.2},
              "style": {"type": "enum", "values": list(STYLES), "default": "drop_first"}}

    def setup(self, p, c):
        c.transition = {"duration": float(p.get("duration") or 0.2), "style": p.get("style") or "drop_first"}

    def chain(self, c, segs):
        if c.transition["style"] == "drop_first":
            return self.drop_first(c, segs)
        return self.xfade(c, segs)

    def drop_first(self, c, segs):
        n = len(segs)
        out, labels = [], [c.vlabels[0]]
        for k in range(1, n):
            out.append("%strim=start_frame=1,setpts=PTS-STARTPTS[vd%d]" % (c.vlabels[k], k))
            labels.append("[vd%d]" % k)
        out.append("%sconcat=n=%d:v=1:a=0[vdc]" % ("".join(labels), n))
        out.append("[vdc]tpad=stop_mode=clone:stop_duration=%s,trim=duration=%s,setpts=PTS-STARTPTS[vcat]"
                   % (round((n - 1) / float(c.fps), 3), round(sum(segs), 3)))
        return out

    def xfade(self, c, segs):
        d, style = c.transition["duration"], c.transition["style"]
        n = len(segs)
        short = {k for k in range(1, n) if min(segs[k - 1], segs[k]) < 2 * d}
        if short:
            c.warnings.append("轉場 %s 秒比第 %s 個接縫兩邊片段的一半還長，這幾個接縫照舊硬切"
                              % (d, "、".join(str(k) for k in sorted(short))))
        out = []
        pad = []
        for k, lab in enumerate(c.vlabels):
            if k < n - 1:
                out.append("%stpad=stop_mode=clone:stop_duration=%s[vt%d]" % (lab, d, k))
                pad.append("[vt%d]" % k)
            else:
                pad.append(lab)
        acc, cum = pad[0], 0.0
        for k in range(1, n):
            cum = round(cum + segs[k - 1], 3)
            tag = "vx%d" % k
            if k in short:
                out.append("%strim=duration=%s,setpts=PTS-STARTPTS[%sc]" % (acc, cum, tag))
                out.append("[%sc]%sconcat=n=2:v=1:a=0[%s]" % (tag, pad[k], tag))
            else:
                out.append("%s%sxfade=transition=%s:duration=%s:offset=%s[%s]" % (acc, pad[k], style, d, cum, tag))
            acc = "[%s]" % tag
        out.append("%snull[vcat]" % acc)
        return out
