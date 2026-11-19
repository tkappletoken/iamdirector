import os

from . import subs
from .base import STAGES, PipelineError

CHAIN_SLOTS = ("head", "rate", "frame", "tail")

class Ctx:
    def __init__(self, spec, files, probes, caps, workdir, strict, fontsdir, container, caption_fontsdir, size=None):
        import render
        self.spec = spec
        self.paths = files
        self.probes = probes
        self.caps = caps
        self.workdir = workdir
        self.strict = strict
        self.fontsdir = fontsdir
        self.container = container
        self.caption_fontsdir = caption_fontsdir
        self.W, self.H = size or render.frame_size(spec["format"]["aspect"], spec["format"]["resolution"])
        self.fps = spec["format"]["fps"]
        self.t = render.timing(spec)
        self.warnings = []
        self.argv = ["-y", "-hide_banner", "-loglevel", "error"]
        self.graph = []
        self.idx = 0
        self.vlabels = []
        self.last = None
        self.files = {}
        self.text = {"mode": "none", "card": [], "trows": [], "style": {}}

def compile_pipeline(pipe, files, probes, caps, workdir, strict=True, fontsdir=None, container="mp4",
                     caption_fontsdir=None):
    import render
    from . import REGISTRY
    spec = pipe["spec"]
    blocks = [(REGISTRY[b["use"]](), b["params"]) for b in pipe["blocks"] if b.get("on", True)]
    container = _param(blocks, "encode", "container", container)
    fmt = _block(blocks, "format")
    c = Ctx(spec, files, probes, caps, workdir, strict, fontsdir, container, caption_fontsdir,
            size=fmt[0].size(fmt[1]) if fmt else None)

    def each(hook, *args):
        for blk, p in blocks:
            fn = getattr(blk, hook, None)
            if fn is not None:
                fn(p, c, *args)

    each("setup")
    each("text")
    mode, cues = c.text["mode"], spec["subtitles"]["cues"]
    card, trows = c.text["card"], c.text["trows"]
    want_burn = mode in ("burn", "both")
    want_soft = mode in ("srt", "both")
    need_ass = want_burn or bool(card) or bool(trows)
    soft_card, soft_titles = None, []
    if need_ass and not caps.get("libass"):
        if strict:
            raise render.RenderError("這支 ffmpeg 沒有 libass（subtitles 濾鏡），燒不了字幕與片尾文字")
        c.warnings.append("本機 ffmpeg 沒有 libass：字幕改成軟字幕軌，片尾文字放進字幕軌（Lambda 上會燒進畫面）")
        if want_burn:
            want_soft, want_burn = True, False
        if card:
            soft_card = {"start": c.t["body"], "end": c.t["total"], "text": " / ".join(card)}
        if trows:
            c.warnings.append("本機 ffmpeg 沒有 libass：片頭／片尾字卡放進字幕軌")
            soft_titles = [{"start": q["start"], "end": q["end"], "text": q["text"]} for q in trows]
        need_ass = False

    for k, v in enumerate(spec["video"]):
        if not (probes.get(v["key"]) or {}).get("has_video"):
            raise render.RenderError("V1 第 %d 段讀不到影像（素材壞了或不是影片）" % (k + 1))
        c.argv += render.in_args(files[v["key"]], (probes.get(v["key"]) or {}).get("demuxer"))
        chain = {}
        each("clip", k, v, chain)
        missing = [s for s in CHAIN_SLOTS if s not in chain]
        if missing:
            raise PipelineError("每段處理缺了 %s（clip_trim／fps／fit 三塊都要有）" % "、".join(missing))
        c.graph.append("[%d:v]%s[v%d]" % (c.idx, ",".join(chain[s] for s in CHAIN_SLOTS), k))
        c.vlabels.append("[v%d]" % k)
        c.idx += 1

    each("timeline")
    meme = [x for blk, p in blocks if blk.id in ("meme_captions", "white_flash") for x in (p.get("items") or [])]
    if any(not isinstance(x.get(k), float) for x in meme for k in ("start", "end")):
        raise render.RenderError("字卡／特效的時間還沒解析成秒數（要先跑 resolve_meme）")
    each("overlay")
    each("append")

    if need_ass:
        ass_path = os.path.join(workdir, "subs.ass")
        c.files[ass_path] = subs.ass(cues, card, c.W, c.H, c.t["body"], c.t["card"], burn_cues=want_burn, titles=trows,
                                     style=c.text["style"])
        opt = "subtitles=filename='%s'" % subs.esc(ass_path)
        if fontsdir:
            opt += ":fontsdir='%s'" % subs.esc(fontsdir)
        c.graph.append("[%s]%s[vout]" % (c.last, opt))
        c.last = "vout"

    clip, mixer = _block(blocks, "audio_clip"), _block(blocks, "mix")
    if not clip or not mixer:
        raise PipelineError("聲音要有 audio_clip 與 mix 兩塊")
    alabels = ["[sil]"]
    c.graph.append(mixer[0].silence(mixer[1], c))
    fader = next((blk for blk, _p in blocks if blk.id == "audio_fade"), None)
    duck = _block(blocks, "music_duck")
    lanes = {}
    for k, a in enumerate(spec["audio"]):
        pr = probes.get(a["key"]) or {}
        if not pr.get("has_audio"):
            c.warnings.append("聲音第 %d 段沒有音軌，略過" % (k + 1))
            continue
        c.argv += clip[0].input_args(clip[1], c, a, files[a["key"]], pr.get("demuxer"))
        fl = fader.audio_clip({}, c, k, a) if fader else ""
        c.graph.append(clip[0].segment(clip[1], c, k, a, c.idx, fl))
        alabels.append("[a%d]" % k)
        lanes.setdefault(a.get("lane") or "A1", []).append("[a%d]" % k)
        c.idx += 1
    c.graph += mixer[0].graph(mixer[1], c, alabels, lanes, duck)

    soft_idx = None
    if want_soft or soft_card or soft_titles:
        srt_text = subs.srt(sorted((cues if want_soft else []) + soft_titles, key=lambda q: q["start"]), soft_card)
        srt_path = os.path.join(workdir, "subs.srt")
        c.files[srt_path] = srt_text
        c.argv += render.in_args(srt_path, "srt")
        soft_idx = c.idx
        c.idx += 1

    if container not in ("mp4", "webm"):
        raise render.RenderError("不支援的輸出格式：%r" % container)
    enc = _block(blocks, "encode")
    if not enc:
        raise PipelineError("缺了輸出（encode）積木")
    webm = container == "webm"
    out = os.path.join(workdir, "out." + container)
    total = c.t["total"]
    c.argv += ["-filter_complex", ";".join(c.graph), "-map", "[%s]" % c.last, "-map", "[aout]"]
    if soft_idx is not None:
        c.argv += enc[0].subtitle_map(enc[1], c, soft_idx, webm)
    c.argv += enc[0].codec_args(enc[1], c, webm) + enc[0].tail(enc[1], c, webm, out)
    sidecar = subs.srt(cues) if mode in ("srt", "both") and cues else None
    result = {"argv": c.argv, "total": total, "warnings": c.warnings, "srt_text": sidecar,
              "out": out, "size": [c.W, c.H], "files": c.files}
    multi = [(blk, p) for blk, p in blocks if blk.passes > 1]
    if multi:
        result["steps"] = _segments(c, multi, soft_idx, webm, enc, out)
    return result

def _segments(c, multi, soft_idx, webm, enc, out):
    import os as _os
    import render
    argv = list(c.argv)
    cut = argv.index("-filter_complex")
    head = argv[:cut]
    srt_in = []
    if soft_idx is not None:
        srt_in = render.in_args(_os.path.join(c.workdir, "subs.srt"), "srt")
        if head[-len(srt_in):] != srt_in:
            raise RuntimeError("切段時找不到軟字幕的輸入")
        head = head[:-len(srt_in)]
    total = str(c.t["total"])
    mid = _os.path.join(c.workdir, "stage1.mkv")
    steps = [{"argv": head + ["-filter_complex", argv[cut + 1], "-map", argv[argv.index("-map") + 1], "-map", "[aout]",
                              "-c:v", "ffv1", "-c:a", "pcm_s16le", "-t", total, mid]}]
    for n, (blk, p) in enumerate(multi, 1):
        prefix = "" if n == 1 else "p%d." % n
        apply_f = _prefix_holes(blk.apply_filter(p), prefix) if prefix else blk.apply_filter(p)
        steps.append({"argv": ["-hide_banner", "-nostats", "-i", mid, "-vn", "-af", blk.measure_filter(p), "-f", "null", "-"],
                      "capture": blk.capture, "prefix": prefix})
        if n < len(multi):
            nxt = _os.path.join(c.workdir, "stage%d.mkv" % (n + 1))
            steps.append({"argv": ["-y", "-hide_banner", "-loglevel", "error", "-i", mid, "-map", "0:v", "-map", "0:a",
                                   "-c:v", "copy", "-af", apply_f, "-c:a", "pcm_s16le", "-t", total, nxt]})
            mid = nxt
            continue
        last = ["-y", "-hide_banner", "-loglevel", "error", "-i", mid] + srt_in + ["-map", "0:v", "-map", "0:a"]
        if soft_idx is not None:
            last += enc[0].subtitle_map(enc[1], c, soft_idx, webm, at=1)
        last += ["-af", apply_f] + enc[0].codec_args(enc[1], c, webm) + enc[0].tail(enc[1], c, webm, out)
        steps.append({"argv": last})
    return steps

def _prefix_holes(text, prefix):
    import re
    return re.sub(r"@@([A-Za-z0-9_]+)@@", lambda m: "@@%s%s@@" % (prefix, m.group(1)), text)

def _block(blocks, bid):
    for blk, p in blocks:
        if blk.id == bid:
            return blk, p
    return None

def _param(blocks, bid, name, fallback):
    for blk, p in blocks:
        if blk.id == bid and p.get(name) is not None:
            return p[name]
    return fallback

def check_order(blocks):
    from . import REGISTRY
    rank = {s: i for i, s in enumerate(STAGES)}
    prev = -1
    for b in blocks:
        st = REGISTRY[b["use"]].stage
        if rank[st] < prev:
            raise PipelineError("%s（%s）放錯位置：%s 階段要排在前面" % (b["use"], REGISTRY[b["use"]].label, st))
        prev = rank[st]
