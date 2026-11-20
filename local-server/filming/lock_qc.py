import math
import subprocess

from . import qc_report

W, H = 36, 64
BLUR = 0.8

def _gray(ffmpeg, path, at, size, timeout):
    w, h = size
    argv = [ffmpeg, "-v", "error"] + (["-ss", "%.3f" % at] if at else []) + [
        "-i", path, "-frames:v", "1", "-vf", "scale=%d:%d:flags=area,format=gray,gblur=sigma=%s" % (w, h, BLUR),
        "-f", "rawvideo", "-"]
    r = subprocess.run(argv, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    return list(r.stdout) if r.returncode == 0 and len(r.stdout) == w * h else None

def gradient(g, size):
    w, h = size
    out = []
    for y in range(h):
        for x in range(w):
            gx = g[y * w + min(x + 1, w - 1)] - g[y * w + max(x - 1, 0)]
            gy = g[min(y + 1, h - 1) * w + x] - g[max(y - 1, 0) * w + x]
            out.append(math.hypot(gx, gy))
    return out

def correlate(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    if not da or not db:
        return 0.0
    return max(0.0, sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (da * db))

def score(ffmpeg, blockout_png, generated, at=0.0, size=(W, H), timeout=60):
    a = _gray(ffmpeg, blockout_png, 0.0, size, timeout)
    b = _gray(ffmpeg, generated, at, size, timeout)
    if a is None or b is None:
        return None
    return round(correlate(gradient(a, size), gradient(b, size)), 3)

def measure(shot_key, blockout_png, generated, ffmpeg="ffmpeg", threshold=None, aspect_size=None, measure=None):
    size = (W, H) if aspect_size is None else aspect_size
    fn = measure or (lambda a, b: score(ffmpeg, a, b, size=size))
    s = fn(blockout_png, generated)
    redo = {"scope": "shot", "target": shot_key}
    if s is None:
        return qc_report.report("lock_qc", shot_key, False, None, ["unreadable"], redo, "lock_qc", "讀不到畫面")
    s = max(0.0, min(1.0, s))
    if threshold is None:
        return qc_report.report("lock_qc", shot_key, True, s, (), None, "lock_qc",
                                "構圖相似度 %.3f（門檻未校準，只量不判）" % s)
    ok = s >= threshold
    return qc_report.report("lock_qc", shot_key, ok, s, () if ok else ["framing_drift"], None if ok else redo,
                            "lock_qc", "構圖相似度 %.3f（門檻 %.2f）" % (s, threshold))
