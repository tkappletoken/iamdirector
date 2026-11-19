import os

from .base import Block

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
        c.files[mpath] = render.meme_ass(caps, c.W, c.H)
        c.graph.append("[%s]subtitles=filename='%s':fontsdir='%s'[vmeme]" % (c.last, render._esc(mpath), render._esc(cdir)))
        c.last = "vmeme"
