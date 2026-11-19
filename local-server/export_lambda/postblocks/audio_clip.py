from .base import Block

class AudioClip(Block):
    id = "audio_clip"
    label = "聲音段"
    stage = "audio"
    locked = True

    def input_args(self, p, c, a, path, demuxer):
        import render
        return (["-stream_loop", "-1"] if a.get("loop") else []) + render.in_args(path, demuxer)

    def segment(self, p, c, k, a, idx, fade=""):
        ms = int(round(a["at"] * 1000))
        return ("[%d:a]atrim=start=%s:end=%s,asetpts=PTS-STARTPTS,aresample=48000,"
                "aformat=sample_fmts=fltp:channel_layouts=stereo,%svolume=%s,adelay=%d|%d[a%d]"
                % (idx, a["in"], round(a["in"] + a["dur"], 3), fade, a["gain"], ms, ms, k))
