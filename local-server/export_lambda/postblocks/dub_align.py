from .base import Block

SLACK = 0.05

class DubAlign(Block):
    id = "dub_align"
    label = "配音對齊"
    stage = "audio"
    optional = True
    params = {"mode": {"type": "enum", "values": ["fit", "trim"], "default": "fit"},
              "max_speed": {"type": "number", "min": 1.0, "max": 1.5, "default": 1.25}}

    @staticmethod
    def window(spec, at):
        end = 0.0
        for v in spec["video"]:
            end += float(v["out"]) - float(v["in"])
            if at < end - 1e-6:
                return round(end - at, 3)
        return None

    def audio_clip(self, p, c, k, a):
        if (a.get("lane") or "A1") != "A1" or a.get("from") == "video":
            return ""
        win = self.window(c.spec, float(a["at"]))
        dur = float(a["dur"])
        if win is None or dur <= win + SLACK:
            return ""
        mode, cap = p.get("mode") or "fit", float(p.get("max_speed") or 1.25)
        if mode == "fit" and dur / win <= cap:
            speed = round(dur / win, 4)
            c.warnings.append("配音第 %d 段比那一鏡長 %.2f 秒，加速 %.2f 倍放進去" % (k + 1, dur - win, speed))
            return "atempo=%s," % speed
        speed = cap if mode == "fit" else 1.0
        cut = round(dur / speed - win, 3)
        c.warnings.append("配音第 %d 段比那一鏡長 %.2f 秒，%s剪掉最後 %.2f 秒" % (
            k + 1, dur - win, ("加速 %.2f 倍之後還是放不下，" % speed) if speed > 1 else "", cut))
        return ("atempo=%s," % speed if speed > 1 else "") + "atrim=end=%s,asetpts=PTS-STARTPTS," % win
