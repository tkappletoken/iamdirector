from .base import Block

class Encode(Block):
    id = "encode"
    label = "輸出"
    stage = "output"
    locked = True
    params = {"container": {"type": "enum", "values": ["mp4", "webm"], "default": "mp4"},
              "crf": {"type": "number", "min": 14, "max": 32, "default": 20},
              "audio_bitrate": {"type": "enum", "values": ["auto", "128k", "160k", "192k", "256k"], "default": "auto"}}

    def subtitle_map(self, p, c, idx, webm, at=None):
        return ["-map", "%d:s" % (idx if at is None else at), "-c:s", "webvtt" if webm else "mov_text",
                "-metadata:s:s:0", "language=chi"]

    def codec_args(self, p, c, webm):
        import render
        ab = p.get("audio_bitrate") or "auto"
        if webm:
            return render.webm_codec_args(c.H) + ["-pix_fmt", "yuv420p", "-r", str(c.fps),
                                                  "-c:a", "libopus", "-b:a", "160k" if ab == "auto" else ab, "-ar", "48000"]
        v = list(render.video_codec_args(c.caps, c.H))
        crf = p.get("crf", 20)
        if "-crf" in v and crf != 20:
            v[v.index("-crf") + 1] = str(int(crf))
        return v + ["-pix_fmt", "yuv420p", "-r", str(c.fps), "-c:a", "aac", "-b:a", "192k" if ab == "auto" else ab,
                    "-ar", "48000"]

    def tail(self, p, c, webm, out):
        return ["-t", str(c.t["total"]), out] if webm else ["-t", str(c.t["total"]), "-movflags", "+faststart", out]
