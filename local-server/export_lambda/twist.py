import os
import re
import statistics
import subprocess
import tempfile

FLASH_DELTA = 12.0
FLASH_HOLD = 0.45
FLASH_BACK = 0.6
SMOOTH = 0.33
SUSTAIN = 1.0
MULT, ADD = 5.0, 2.0
TIME_EXPR = re.compile(r"^(twist|end)([+-]\d{1,2}(\.\d{1,3})?)?$")

class TwistError(Exception):
    pass

def _series(path):
    t, out = None, []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            a = re.search(r"pts_time:([0-9.]+)", line)
            if a:
                t = float(a.group(1))
            b = re.search(r"YAVG=([0-9.]+)", line)
            if b and t is not None:
                out.append((t, float(b.group(1))))
    return out

def _measure(ffmpeg, src, vf, work, name, env=None):
    meta = os.path.join(work, name)
    cmd = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", src, "-an",
           "-vf", vf + ",metadata=print:key=lavfi.signalstats.YAVG:file=" + meta, "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=300, env=env, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise TwistError("量不到畫面變化（ffmpeg 失敗）：%s" % r.stderr.decode("utf-8", "replace")[-300:])
    return _series(meta)

def analyse(motion, luma):
    if len(motion) < 10:
        return {"at": None, "flash": None, "base": None, "threshold": None}
    ts = [t for t, _ in motion]
    mv = [v for _, v in motion]
    span = ts[-1] - ts[0]
    fps = (len(ts) - 1) / span if span > 0 else 24.0
    lum = dict(luma)
    lv = [lum.get(t, lum.get(round(t, 6), 0.0)) for t in ts]
    flash = [False] * len(ts)
    k = max(1, int(fps * 0.3))
    hold = max(1, int(fps * FLASH_HOLD))
    back = max(1, int(fps * FLASH_BACK))
    for i in range(len(ts)):
        ref = statistics.median(lv[max(0, i - k):i] or [lv[i]])
        if abs(lv[i] - ref) > FLASH_DELTA and any(abs(lv[j] - ref) <= FLASH_DELTA for j in range(i + 1, min(len(ts), i + back + 1))):
            for j in range(i, min(len(ts), i + hold)):
                flash[j] = True
    w = max(1, int(fps * SMOOTH))
    sm = [statistics.mean(mv[max(0, i - w + 1):i + 1]) for i in range(len(mv))]
    base = statistics.median(mv[:max(1, int(len(mv) * 0.4))])
    thr = max(base * MULT, base + ADD)
    win = max(1, int(fps * SUSTAIN))
    at = None
    for i in range(len(ts)):
        if flash[i] or sm[i] < thr:
            continue
        seg = [sm[j] for j in range(i, min(len(ts), i + win)) if not flash[j]]
        if len(seg) >= win * 0.8 and min(seg) >= thr * 0.7:
            at = round(max(0.0, ts[i] - SMOOTH / 2), 3)
            break
    fl = [ts[i] for i in range(len(ts)) if flash[i]]
    return {"at": at, "flash": [round(fl[0], 3), round(fl[-1], 3)] if fl else None,
            "base": round(base, 3), "threshold": round(thr, 3)}

def detect(ffmpeg, src, env=None):
    with tempfile.TemporaryDirectory(prefix="twist-") as work:
        motion = _measure(ffmpeg, src, "scale=180:-2,format=gray,tblend=all_mode=difference,signalstats", work, "m.txt", env)
        luma = _measure(ffmpeg, src, "scale=180:-2,format=gray,signalstats", work, "l.txt", env)
    return analyse(motion, luma)

def resolve(v, twist, total):
    if isinstance(v, bool):
        raise TwistError("時間要是數字或 twist／end 的相對寫法")
    if isinstance(v, (int, float)):
        x = float(v)
    else:
        m = TIME_EXPR.match(str(v or ""))
        if not m:
            raise TwistError("時間要是數字或 twist／end 的相對寫法（例如 twist+0.3）：%r" % (v,))
        if m.group(1) == "twist":
            if twist is None:
                raise TwistError("找不到反轉點：請手動指定 twist.at（第幾秒）")
            x = float(twist)
        else:
            x = float(total)
        x += float(m.group(2) or 0)
    return round(min(max(0.0, x), float(total)), 3)

CAPTION_MAX, EFFECT_MAX, CAPTION_TEXT_MAX = 20, 10, 40
POSITIONS, STYLES, SIZES = ("top", "middle", "bottom"), ("meme", "memebox"), ("l", "xl")

def _time(v, name):
    if isinstance(v, bool):
        raise TwistError("%s 要是數字或 twist／end 的相對寫法" % name)
    if isinstance(v, (int, float)):
        if v != v or not 0 <= v <= 30 * 60:
            raise TwistError("%s 超出範圍" % name)
        return round(float(v), 3)
    if isinstance(v, str) and TIME_EXPR.match(v):
        return v
    raise TwistError("%s 要是數字或 twist／end 的相對寫法（例如 twist+0.3）" % name)

def clean_meme(spec):
    caps = spec.get("captions") or []
    effs = spec.get("effects") or []
    tw = spec.get("twist") or {}
    if not isinstance(caps, list) or len(caps) > CAPTION_MAX:
        raise TwistError("captions 要是陣列，最多 %d 段" % CAPTION_MAX)
    if not isinstance(effs, list) or len(effs) > EFFECT_MAX:
        raise TwistError("effects 要是陣列，最多 %d 個" % EFFECT_MAX)
    if not isinstance(tw, dict) or any(k not in ("auto", "at", "hint") for k in tw):
        raise TwistError("twist 只收 auto／at／hint")
    out_c = []
    for i, q in enumerate(caps, 1):
        if not isinstance(q, dict):
            raise TwistError("第 %d 段字卡要是物件" % i)
        text = q.get("text")
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > CAPTION_TEXT_MAX:
            raise TwistError("第 %d 段字卡的文字要有 1–%d 字" % (i, CAPTION_TEXT_MAX))
        pos = q.get("pos", "top")
        if isinstance(pos, dict):
            y = pos.get("y")
            if set(pos) != {"y"} or isinstance(y, bool) or not isinstance(y, (int, float)) or not 0 <= y <= 1:
                raise TwistError("第 %d 段字卡的 pos 要是 top／middle／bottom 或 {y: 0–1}" % i)
            pos = {"y": round(float(y), 3)}
        elif pos not in POSITIONS:
            raise TwistError("第 %d 段字卡的 pos 要是 top／middle／bottom 或 {y: 0–1}" % i)
        style, size = q.get("style", "meme"), q.get("size", "l")
        if style not in STYLES or size not in SIZES:
            raise TwistError("第 %d 段字卡的 style 要是 meme／memebox、size 要是 l／xl" % i)
        out_c.append({"text": text.strip(), "start": _time(q.get("start", 0), "第 %d 段字卡的開始" % i),
                      "end": _time(q.get("end", "end"), "第 %d 段字卡的結束" % i), "pos": pos, "style": style, "size": size})
    out_e = []
    for i, e in enumerate(effs, 1):
        if not isinstance(e, dict) or e.get("type") != "white_flash":
            raise TwistError("第 %d 個特效只支援 white_flash" % i)
        out_e.append({"type": "white_flash", "start": _time(e.get("start"), "第 %d 個特效的開始" % i),
                      "end": _time(e.get("end"), "第 %d 個特效的結束" % i)})
    out_t = {}
    if tw.get("auto") is True:
        out_t["auto"] = True
    if tw.get("at") is not None:
        out_t["at"] = _time(tw["at"], "twist.at")
        if not isinstance(out_t["at"], float):
            raise TwistError("twist.at 要是秒數")
    if tw.get("hint") is not None:
        out_t["hint"] = _time(tw["hint"], "twist.hint")
    return {"captions": out_c, "effects": out_e, "twist": out_t}
