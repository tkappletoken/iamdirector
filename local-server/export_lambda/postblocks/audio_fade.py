from .base import Block

class AudioFade(Block):
    id = "audio_fade"
    label = "聲音淡入淡出"
    stage = "audio"

    def audio_clip(self, p, c, k, a):
        fade = a.get("fade") or 0
        if not fade:
            return ""
        return "afade=t=in:st=0:d=%s,afade=t=out:st=%s:d=%s," % (fade, round(a["dur"] - fade, 3), fade)
