import re
import subprocess

from .base import Block

_STAT = re.compile(r"lavfi\.signalstats\.(YAVG|YLOW|YHIGH)=([0-9.]+)")

class Cover(Block):
    id = "cover"
    label = "封面縮圖"
    stage = "output"
    optional = True
    params = {"at": {"type": "number", "min": 0, "max": 3600, "nullable": True, "default": None},
              "width": {"type": "enum", "values": [320, 480, 720, 1080], "default": 720},
              "format": {"type": "enum", "values": ["jpg", "png"], "default": "jpg"},
              "dark": {"type": "number", "min": 0, "max": 255, "default": 24},
              "flat": {"type": "number", "min": 0, "max": 255, "default": 16}}

    def argv(self, p, src, demuxer, duration, dest, fps=24):
        import render
        if p.get("at") is None:
            at = round(max(0.0, duration * 0.3), 3)
            vf = "thumbnail=%d," % max(2, int(fps * 2))
        else:
            at = round(min(float(p["at"]), max(0.0, duration - 0.05)), 3)
            vf = ""
        vf += "scale=%d:-2,signalstats,metadata=mode=print" % int(p["width"])
        enc = ["-c:v", "mjpeg", "-q:v", "2"] if p["format"] == "jpg" else ["-c:v", "png"]
        return (["-y", "-hide_banner", "-nostats", "-ss", "%.3f" % at] + render.in_args(src, demuxer)
                + ["-frames:v", "1", "-vf", vf] + enc + ["-f", "image2", "-update", "1", dest]), at

    def extract(self, p, src, demuxer, duration, dest, ffmpeg, fps=24, run=None, timeout=120):
        argv, at = self.argv(p, src, demuxer, duration, dest, fps)

        def real(a):
            r = subprocess.run([ffmpeg] + a, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
            return r.returncode, r.stderr or ""
        code, err = (run or real)(argv)
        stats = {k: float(v) for k, v in _STAT.findall(err or "")}
        where = "auto" if p.get("at") is None else "%.3f" % at
        if code != 0 or not {"YAVG", "YLOW", "YHIGH"} <= set(stats):
            return None, report(False, None, ["unreadable"], "取不到封面（%s）" % where)
        defects = []
        if stats["YAVG"] < float(p["dark"]):
            defects.append("cover_dark")
        if stats["YHIGH"] - stats["YLOW"] < float(p["flat"]):
            defects.append("cover_flat")
        score = min(1.0, (stats["YHIGH"] - stats["YLOW"]) / 255.0)
        return dest, report(not defects, score, defects, "亮度 %.0f、範圍 %.0f（%s）"
                            % (stats["YAVG"], stats["YHIGH"] - stats["YLOW"], where))

def report(ok, score, defects, note):
    return {"block": "cover", "subject": "cover", "ok": ok, "score": None if score is None else round(score, 3),
            "defects": list(defects), "redo": None if ok else {"scope": "step", "target": "cover"},
            "source": "cover", "note": note[:120]}
