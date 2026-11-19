from .base import Block

class ClipTrim(Block):
    id = "clip_trim"
    label = "裁切"
    stage = "source"
    locked = True

    def clip(self, p, c, k, v, chain):
        seg = round(v["out"] - v["in"], 3)
        have = (c.probes.get(v["key"]) or {}).get("duration") or 0
        if have and have - v["in"] < seg - 0.05:
            c.warnings.append("V1 第 %d 段素材只有 %.2f 秒，比宣告的 %.2f 秒短，停在最後一格補齊"
                              % (k + 1, max(0.0, have - v["in"]), seg))
        chain["head"] = "trim=start=%s:end=%s,setpts=PTS-STARTPTS" % (v["in"], v["out"])
        chain["tail"] = "tpad=stop_mode=clone:stop_duration=%s,trim=duration=%s,setpts=PTS-STARTPTS" % (seg, seg)
