from .base import Block

class Mix(Block):
    id = "mix"
    label = "混音"
    stage = "audio"
    locked = True

    def silence(self, p, c):
        return "anullsrc=r=48000:cl=stereo,atrim=duration=%s[sil]" % c.t["total"]

    def graph(self, p, c, alabels, lanes, duck=None):
        out = []
        if duck and lanes.get("A1") and lanes.get("A2"):
            def sub(labels, name):
                if len(labels) == 1:
                    out.append("%sanull[%s]" % (labels[0], name))
                else:
                    out.append("%samix=inputs=%d:duration=longest:dropout_transition=0:normalize=0[%s]"
                               % ("".join(labels), len(labels), name))
            sub(lanes["A1"], "voc")
            sub(lanes["A2"], "mus")
            out.append("[voc]asplit=2[voc1][voc2]")
            out.append("[mus][voc2]%s[mduck]" % duck[0].filter(duck[1]))
            out.append("[sil][voc1][mduck]amix=inputs=3:duration=first:dropout_transition=0:normalize=0[aout]")
        elif len(alabels) > 1:
            out.append("%samix=inputs=%d:duration=first:dropout_transition=0:normalize=0[aout]"
                       % ("".join(alabels), len(alabels)))
        else:
            out.append("[sil]anull[aout]")
        return out
