import os
import shutil
import subprocess

class FramesError(RuntimeError):
    pass

def find_ffmpeg(env=None):
    env = os.environ if env is None else env
    for p in (env.get("FFMPEG"), shutil.which("ffmpeg")):
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None

def find_ffprobe(ffmpeg=None):
    if ffmpeg:
        p = os.path.join(os.path.dirname(ffmpeg), "ffprobe")
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return shutil.which("ffprobe")

def _run(argv, out_png, timeout):
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not os.path.isfile(out_png) or os.path.getsize(out_png) == 0:
        raise FramesError("取格失敗（exit %s）：%s" % (r.returncode, (r.stderr or "")[-300:]))
    return out_png

def first(video, out_png, ffmpeg=None, timeout=60):
    ff = ffmpeg or find_ffmpeg()
    if not ff:
        raise FramesError("找不到 ffmpeg")
    return _run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", video, "-frames:v", "1", out_png], out_png, timeout)

def last(video, out_png, ffmpeg=None, timeout=60):
    ff = ffmpeg or find_ffmpeg()
    if not ff:
        raise FramesError("找不到 ffmpeg")
    return _run([ff, "-hide_banner", "-loglevel", "error", "-y", "-sseof", "-1", "-i", video, "-update", "1", out_png],
                out_png, timeout)
