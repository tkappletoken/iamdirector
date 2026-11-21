import json
import math
import os
import re
import shutil
import subprocess
import tempfile

MODEL = os.environ.get("STUDIO_OUTPAINT_MODEL", "gmi/bria-genfill").strip() or "gmi/bria-genfill"
FFMPEG, FFPROBE = "ffmpeg", "ffprobe"

ASPECTS = {"9:16": (9, 16), "16:9": (16, 9)}

MAX_SIDE = 4096
MIN_SIDE = 64
FFMPEG_TIMEOUT = 60
PROMPT_MAX = 1000

DEFAULT_PROMPT = ("Extend the scene naturally beyond the frame edges: continue the existing background, "
                  "lighting, perspective and colors seamlessly. Do not add new people, text or logos.")

_SOURCE_DATA = re.compile(r"^data:image/(png|jpeg|jpg);base64,", re.I)
_SOURCE_ASSET = re.compile(r"^\s*asset\s*:\s*/*\s*(ast_[0-9a-f]{20})\s*$")

class OutpaintError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message

def available():
    return bool(shutil.which(FFMPEG) and shutil.which(FFPROBE))

def check_request(body):
    b = body if isinstance(body, dict) else {}
    src = b.get("source")
    if not isinstance(src, str) or not src.strip():
        raise OutpaintError(400, "缺少 source（asset://ast_… 或 PNG／JPEG 的 data URI）")
    m = _SOURCE_ASSET.match(src)
    if not m and not _SOURCE_DATA.match(src):
        raise OutpaintError(400, "source 只收 asset://ast_… 或 PNG／JPEG 的 data URI，不收外部網址")
    aspect = b.get("aspect")
    if aspect not in ASPECTS:
        raise OutpaintError(400, "aspect 只能是 %s" % "、".join(ASPECTS))
    out = {"source": src.strip(), "asset_id": m.group(1) if m else None, "aspect": aspect, "extra": {}}
    prompt = b.get("prompt")
    if prompt is not None and not isinstance(prompt, str):
        raise OutpaintError(400, "prompt 要是文字")
    prompt = (prompt or "").strip()
    if len(prompt) > PROMPT_MAX:
        raise OutpaintError(400, "prompt 最多 %d 字" % PROMPT_MAX)
    out["prompt"] = prompt or DEFAULT_PROMPT
    neg = b.get("negative_prompt")
    if neg is not None:
        if not isinstance(neg, str) or len(neg) > PROMPT_MAX:
            raise OutpaintError(400, "negative_prompt 要是 %d 字以內的文字" % PROMPT_MAX)
        if neg.strip():
            out["extra"]["negative_prompt"] = neg.strip()
    g = b.get("guidance_scale")
    if g is not None:
        if isinstance(g, bool) or not isinstance(g, (int, float)) or not 1 <= g <= 20:
            raise OutpaintError(400, "guidance_scale 要是 1–20 的數字")
        out["extra"]["guidance_scale"] = g
    n = b.get("num_inference_steps")
    if n is not None:
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 100:
            raise OutpaintError(400, "num_inference_steps 要是 1–100 的整數")
        out["extra"]["num_inference_steps"] = n
    return out

def request_price(entry):
    if not isinstance(entry, dict):
        return None
    pr = entry.get("pricing") if isinstance(entry.get("pricing"), dict) else {}
    if pr.get("unit") != "request":
        return None
    v = pr.get("to") if pr.get("to") is not None else pr.get("from")
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
        return None
    return float(v)

def geometry(w, h, aspect):
    if w < MIN_SIDE or h < MIN_SIDE:
        raise OutpaintError(400, "原圖太小（至少 %dpx）" % MIN_SIDE)
    aw, ah = ASPECTS[aspect]
    target = aw / ah
    have = w / h
    if abs(have - target) / target < 0.01:
        raise OutpaintError(400, "原圖已經是 %s，不用外擴" % aspect)
    even = lambda v: int(math.ceil(v / 2.0)) * 2
    if have < target:
        W, H, sides = even(h * target), h, "left_right"
    else:
        W, H, sides = w, even(w / target), "top_bottom"
    if max(W, H) > MAX_SIDE:
        raise OutpaintError(413, "外擴後畫布 %dx%d 超過 %dpx 上限；原圖不縮放（縮了主體就變了），請換小一點的圖"
                                 % (W, H, MAX_SIDE))
    return {"w": w, "h": h, "W": W, "H": H, "x": (W - w) // 2, "y": (H - h) // 2, "sides": sides}

def image_demuxer(raw):
    b = raw[:16] if isinstance(raw, (bytes, bytearray)) else b""
    if b.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png_pipe"
    if b.startswith(b"\xff\xd8\xff"):
        return "jpeg_pipe"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp_pipe"
    raise OutpaintError(422, "不是 PNG／JPEG／WebP 圖片")

def _in(raw, path):
    return ["-protocol_whitelist", "file", "-f", image_demuxer(raw), "-i", path]

def _run(args, timeout=FFMPEG_TIMEOUT):
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise OutpaintError(500, "影像處理失敗：%s" % str(e)[:200])
    if p.returncode != 0:
        raise OutpaintError(422, "影像處理失敗：%s" % p.stderr.decode(errors="replace").strip()[-300:])
    return p.stdout

def probe(path, raw):
    out = _run([FFPROBE, "-v", "error", "-protocol_whitelist", "file", "-f", image_demuxer(raw),
                "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", path])
    try:
        s = json.loads(out or b"{}")["streams"][0]
        return int(s["width"]), int(s["height"])
    except (ValueError, KeyError, IndexError, TypeError):
        raise OutpaintError(422, "讀不出原圖尺寸，請確認是 PNG 或 JPEG")

def _write(d, name, raw):
    p = os.path.join(d, name)
    with open(p, "wb") as f:
        f.write(raw)
    return p

def _read(p):
    with open(p, "rb") as f:
        return f.read()

def _ff():
    return [FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]

def prepare(src_raw, aspect):
    with tempfile.TemporaryDirectory(prefix="outpaint-") as d:
        src = _write(d, "src", src_raw)
        geo = geometry(*probe(src, src_raw), aspect)
        canvas, mask = os.path.join(d, "canvas.png"), os.path.join(d, "mask.png")
        _run(_ff() + _in(src_raw, src) + ["-vf", "format=rgba,pad=%d:%d:%d:%d:color=white" % (geo["W"], geo["H"], geo["x"], geo["y"]),
                    "-frames:v", "1", canvas])
        _run(_ff() + ["-f", "lavfi", "-i", "color=c=white:s=%dx%d" % (geo["W"], geo["H"]),
                    "-vf", "drawbox=x=%d:y=%d:w=%d:h=%d:color=black:t=fill,format=gray"
                    % (geo["x"], geo["y"], geo["w"], geo["h"]),
                    "-frames:v", "1", mask])
        return geo, _read(canvas), _read(mask)

def paste_back(result_raw, src_raw, geo):
    with tempfile.TemporaryDirectory(prefix="outpaint-") as d:
        res, src = _write(d, "result", result_raw), _write(d, "src", src_raw)
        out = os.path.join(d, "out.png")
        _run(_ff() + _in(result_raw, res) + _in(src_raw, src) + ["-filter_complex",
                    "[0:v]scale=%d:%d:flags=bicubic,format=rgba[b];[1:v]format=rgba[s];"
                    "[b][s]overlay=%d:%d:format=rgb,format=rgba" % (geo["W"], geo["H"], geo["x"], geo["y"]),
                    "-frames:v", "1", out])
        return _read(out)

def asset_name(aspect, src_id):
    return "外擴%s-%s.png" % (aspect.replace(":", "x"), src_id or "上傳圖")

def asset_tags(aspect, src_id):
    tags = ["外擴", "外擴" + aspect.replace(":", "x")]
    if src_id:
        tags.append("原圖-" + src_id)
    return tags
