import re
import subprocess

from .base import Block

_SSIM = re.compile(r"All:(-?[0-9.]+)")

class SeamCheck(Block):
    id = "seam_check"
    label = "接縫品管"
    stage = "analyze"
    optional = True
    params = {"threshold": {"type": "number", "min": 0, "max": 1, "default": 0.5}}

    @staticmethod
    def ssim(ffmpeg, a, at_a, b, at_b, timeout=60):
        argv = [ffmpeg, "-hide_banner", "-nostats", "-ss", "%.3f" % max(0.0, at_a), "-i", a, "-ss", "%.3f" % max(0.0, at_b),
                "-i", b, "-frames:v", "1", "-lavfi",
                "[0:v]scale=320:180,format=gray[x];[1:v]scale=320:180,format=gray[y];[x][y]ssim", "-f", "null", "-"]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        m = _SSIM.search(r.stderr or "")
        return float(m.group(1)) if (r.returncode == 0 and m) else None

    def measure(self, p, spec, files, ffmpeg, measure=None):
        th = float(p.get("threshold", 0.5))
        fps = float(spec["format"]["fps"])
        fn = measure or (lambda a, ta, b, tb: self.ssim(ffmpeg, a, ta, b, tb))
        out = []
        vs = spec["video"]
        for k in range(len(vs) - 1):
            a, b = vs[k], vs[k + 1]
            score = fn(files[a["key"]], a["out"] - 1.0 / fps, files[b["key"]], b["in"])
            seam = "seam%d" % (k + 1)
            if score is None:
                out.append(_report(seam, False, None, ["unreadable"], k + 2, "讀不到接縫畫面"))
                continue
            ok = score >= th
            out.append(_report(seam, ok, score, [] if ok else ["seam_jump"], None if ok else k + 2,
                               "SSIM %.3f（門檻 %.2f）" % (score, th)))
        return out

def _report(subject, ok, score, defects, redo_shot, note):
    return {"block": "seam_check", "subject": subject, "ok": ok, "score": None if score is None else round(score, 3),
            "defects": defects, "redo": None if redo_shot is None else {"scope": "shot", "target": str(redo_shot)},
            "source": "seam_check", "note": note[:120]}
