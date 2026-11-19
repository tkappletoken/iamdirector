from .base import Block

class Loudness(Block):
    id = "loudness"
    label = "音量標準化"
    stage = "output"
    optional = True
    passes = 2
    params = {"target": {"type": "enum", "values": ["youtube", "broadcast", "podcast"], "default": "youtube"}}

    TARGET = {"youtube": (-14, -1.0, 11), "broadcast": (-23, -1.0, 15), "podcast": (-16, -1.5, 11)}

    def measure_filter(self, p):
        i, tp, lra = self.TARGET[p.get("target") or "youtube"]
        return "loudnorm=I=%s:TP=%s:LRA=%s:print_format=json" % (i, tp, lra)

    def apply_filter(self, p):
        i, tp, lra = self.TARGET[p.get("target") or "youtube"]
        return ("loudnorm=I=%s:TP=%s:LRA=%s:measured_I=@@input_i@@:measured_TP=@@input_tp@@:"
                "measured_LRA=@@input_lra@@:measured_thresh=@@input_thresh@@:offset=@@target_offset@@:linear=true"
                % (i, tp, lra))
