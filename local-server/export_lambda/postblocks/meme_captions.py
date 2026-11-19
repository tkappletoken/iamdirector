import os

from .base import Block
from .subs import ass_text, esc, ts

def meme_ass(captions, W, H, font=None):
    if font is None:
        import render
        font = render.MEME_FONT

    def size(q):
        return max(18, int(H * {"xl": 0.055, "xxl": 0.075}.get(q.get("size"), 0.041)))
    base = max(18, int(H * 0.041))
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Meme,%s,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,%d,0,8,%d,%d,%d,1\n"
            "Style: MemeBox,%s,%d,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,%d,0,8,%d,%d,%d,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            % (W, H, font, base, max(2, round(H / 240)), int(W * 0.06), int(W * 0.06), int(H * 0.12),
               font, base, max(4, round(H / 110)), int(W * 0.06), int(W * 0.06), int(H * 0.12)))
    rows = []
    for q in captions:
        st = "MemeBox" if q.get("style") == "memebox" else "Meme"
        pos = q.get("pos") or "top"
        if isinstance(pos, dict):
            tag = "{\\an5\\pos(%d,%d)\\fs%d}" % (W // 2, int(H * float(pos["y"])), size(q))
            rows.append("Dialogue: 3,%s,%s,%s,,0,0,0,,%s%s" % (ts(q["start"], "."), ts(q["end"], "."), st, tag,
                                                                ass_text(q["text"])))
            continue
        an = {"top": 8, "middle": 5, "bottom": 2}[pos]
        mv = {"top": int(H * 0.12), "middle": 0, "bottom": int(H * 0.2)}[pos]
        tag = "{\\an%d\\fs%d}" % (an, size(q))
        rows.append("Dialogue: 3,%s,%s,%s,,0,0,%d,,%s%s" % (ts(q["start"], "."), ts(q["end"], "."), st, mv, tag,
                                                             ass_text(q["text"])))
    return head + "\n".join(rows) + ("\n" if rows else "")

class MemeCaptions(Block):
    id = "meme_captions"
    label = "迷因字卡"
    stage = "overlay"
    params = {"items": {"type": "list", "default": []}}

    def overlay(self, p, c):
        import render
        caps = p.get("items") or []
        if not caps:
            return
        if not c.caps.get("libass"):
            raise render.RenderError("這支 ffmpeg 沒有 libass（subtitles 濾鏡），燒不了迷因字卡")
        cdir = c.caption_fontsdir or os.environ.get("CAPTION_FONTS_DIR") or c.fontsdir
        fpath = render.meme_font(cdir)
        render.check_caption_chars(caps, fpath)
        mpath = os.path.join(c.workdir, "meme.ass")
        c.files[mpath] = meme_ass(caps, c.W, c.H)
        c.graph.append("[%s]subtitles=filename='%s':fontsdir='%s'[vmeme]" % (c.last, esc(mpath), esc(cdir)))
        c.last = "vmeme"
