import os
import re

from .base import Block, PipelineError
from .subs import ass_text, esc, ts

KEY = re.compile(r"^originals/[A-Za-z0-9_-]{1,64}/[0-9a-f]{64}$")
POS = ("tl", "tr", "bl", "br", "center")
ALIGN = {"tl": 7, "tr": 9, "bl": 1, "br": 3, "center": 5}
IMAGE_DEMUXER = {"png": "png_pipe", "jpeg": "jpeg_pipe"}

def image_kind(path):
    try:
        with open(path, "rb") as f:
            h = f.read(8)
    except OSError:
        return None
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if h.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    return None

class Watermark(Block):
    id = "watermark"
    label = "浮水印／logo"
    stage = "overlay"
    optional = True
    drop_on_fail = True
    params = {"kind": {"type": "enum", "values": ["text", "image"], "default": "text"},
              "text": {"type": "text", "max": 40, "default": ""},
              "logo": {"type": "text", "max": 200, "default": ""},
              "position": {"type": "enum", "values": list(POS), "default": "br"},
              "size": {"type": "number", "min": 0.03, "max": 0.4, "default": 0.12},
              "opacity": {"type": "number", "min": 0.1, "max": 1, "default": 0.6},
              "margin": {"type": "number", "min": 0, "max": 0.2, "default": 0.04},
              "start": {"type": "number", "min": 0, "max": 3600, "default": 0},
              "end": {"type": "number", "min": 0, "max": 3600, "nullable": True, "default": None}}

    def validate(self, p):
        if p["kind"] == "text":
            t = (p.get("text") or "").strip()
            if not t or any(ord(ch) < 32 for ch in t):
                raise PipelineError("watermark.text 要有一行字（不能換行）")
            p["text"] = t
        elif not KEY.match(p.get("logo") or ""):
            raise PipelineError("watermark.logo 要是作品素材（originals/<使用者>/<sha256>）")
        if p.get("end") is not None and p["end"] <= p["start"]:
            raise PipelineError("watermark.end 要比 start 晚")
        return p

    def span(self, p, c):
        body = c.t["body"]
        s = min(float(p["start"]), body)
        e = body if p.get("end") is None else min(float(p["end"]), body)
        if e <= s:
            raise PipelineError("watermark：時間落在本體外面")
        return round(s, 3), round(e, 3)

    def overlay(self, p, c):
        s, e = self.span(p, c)
        if p["kind"] == "text":
            self.text_layer(p, c, s, e)
        else:
            self.image_layer(p, c, s, e)

    def text_layer(self, p, c, s, e):
        import render
        if not c.caps.get("libass"):
            raise PipelineError("watermark：這支 ffmpeg 沒有 libass，文字浮水印燒不了")
        cdir = c.caption_fontsdir or os.environ.get("CAPTION_FONTS_DIR") or c.fontsdir
        render.check_caption_chars([{"text": p["text"]}], render.meme_font(cdir))
        path = os.path.join(c.workdir, "wm.ass")
        c.files[path] = wm_ass(p, c.W, c.H, s, e)
        c.graph.append("[%s]subtitles=filename='%s':fontsdir='%s'[vwm]" % (c.last, esc(path), esc(cdir)))
        c.last = "vwm"

    def image_layer(self, p, c, s, e):
        key = p["logo"]
        if not key.startswith("originals/%s/" % c.spec["user"]):
            raise PipelineError("watermark.logo 不是這個人的素材")
        path = c.paths.get(key)
        kind = (c.probes.get(key) or {}).get("image")
        if not path or kind not in IMAGE_DEMUXER:
            raise PipelineError("watermark：logo 沒有抓到，或不是 png／jpeg")
        c.argv += ["-protocol_whitelist", "file", "-loop", "1", "-f", IMAGE_DEMUXER[kind], "-i", path]
        m = int(min(c.W, c.H) * float(p["margin"]))
        w = max(2, int(c.W * float(p["size"])) // 2 * 2)
        x, y = {"tl": ("%d" % m, "%d" % m), "tr": ("W-w-%d" % m, "%d" % m), "bl": ("%d" % m, "H-h-%d" % m),
                "br": ("W-w-%d" % m, "H-h-%d" % m), "center": ("(W-w)/2", "(H-h)/2")}[p["position"]]
        c.graph.append("[%d:v]scale=%d:-2,format=rgba,colorchannelmixer=aa=%s[wmimg]" % (c.idx, w, round(float(p["opacity"]), 3)))
        c.graph.append("[%s][wmimg]overlay=x=%s:y=%s:shortest=1:enable='between(t,%s,%s)'[vwm]" % (c.last, x, y, s, e))
        c.idx += 1
        c.last = "vwm"

def wm_ass(p, W, H, start, end, font=None):
    if font is None:
        import render
        font = render.MEME_FONT
    a = "%02X" % int(round((1 - float(p["opacity"])) * 255))
    size = max(14, int(min(W, H) * float(p["size"]) * 0.5))
    m = int(min(W, H) * float(p["margin"]))
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 2\n"
            "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Mark,%s,%d,&H%sFFFFFF,&H%sFFFFFF,&H%s000000,&H00000000,-1,0,0,0,100,100,0,0,1,%d,0,%d,%d,%d,%d,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            % (W, H, font, size, a, a, a, max(1, size // 16), ALIGN[p["position"]], m, m, m))
    return head + "Dialogue: 4,%s,%s,Mark,,0,0,0,,%s\n" % (ts(start, "."), ts(end, "."), ass_text(p["text"]))
