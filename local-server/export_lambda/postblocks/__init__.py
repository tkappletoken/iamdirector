import os

from .audio_clip import AudioClip
from .audio_fade import AudioFade
from .base import STAGES, Block, PipelineError
from .clip_trim import ClipTrim
from .compile import check_order, compile_pipeline
from .concat import Concat
from .disclosure import Disclosure
from .encode import Encode
from .fit import Fit
from .format import Format
from .transition import Transition
from .seam_check import SeamCheck
from .fps import Fps
from .meme_captions import MemeCaptions
from .mix import Mix
from .pad_black import PadBlack
from .pure import catalog, clean_user, merge, preview
from .subtitles import Subtitles
from .titles import Titles
from .twist_detect import TwistDetect
from .white_flash import WhiteFlash
from .video_fade import VideoFade
from .music_duck import MusicDuck
from .loudness import Loudness
from .watermark import Watermark
from .color_grade import ColorGrade
from .speed import Speed
from .cover import Cover
from .dub_align import DubAlign

REGISTRY = {b.id: b for b in (TwistDetect, SeamCheck, Format, ClipTrim, Fps, Fit, Transition, Concat, PadBlack, WhiteFlash, MemeCaptions, VideoFade,
                              Disclosure, Subtitles, Titles, AudioClip, AudioFade, MusicDuck, Mix, Loudness, Encode)}
for _b in (ColorGrade, Watermark, Speed, Cover, DubAlign):
    REGISTRY[_b.id] = _b
del _b

ENGINES = ("legacy", "blocks", "shadow")
ENGINE_ENV = "POSTBLOCKS_ENGINE"

def engine_of(explicit=None):
    for v in (explicit, os.environ.get(ENGINE_ENV)):
        if isinstance(v, str) and v.strip():
            v = v.strip().lower()
            return v if v in ENGINES else "legacy"
    return "legacy"

def pipeline_from_spec(spec, container="mp4"):
    fmt = spec["format"]
    blocks = [
        {"use": "twist_detect", "params": {"twist": dict(spec.get("twist") or {})}},
        {"use": "format", "params": {"aspect": fmt["aspect"], "resolution": fmt["resolution"]}},
        {"use": "clip_trim", "params": {}},
        {"use": "fps", "params": {"fps": fmt["fps"]}},
        {"use": "fit", "params": {"mode": "crop" if fmt.get("fit") == "crop" else "pad"}},
        {"use": "concat", "params": {}},
        {"use": "pad_black", "params": {}},
        {"use": "white_flash", "params": {"items": list(spec.get("effects") or [])}},
        {"use": "meme_captions", "params": {"items": list(spec.get("captions") or [])}},
        {"use": "disclosure", "params": {"disclosure": dict(spec.get("disclosure") or {"on": False})}},
        {"use": "subtitles", "params": {"mode": spec["subtitles"]["mode"]}},
        {"use": "titles", "params": {"titles": spec.get("titles")}},
        {"use": "audio_clip", "params": {}},
        {"use": "audio_fade", "params": {}},
        {"use": "mix", "params": {}},
        {"use": "encode", "params": {"container": container}},
    ]
    return {"version": 1, "spec": spec, "blocks": blocks}

def normalize(pipe):
    if not isinstance(pipe, dict) or not isinstance(pipe.get("blocks"), list):
        raise PipelineError("管線要有 blocks 陣列")
    out = []
    for i, b in enumerate(pipe["blocks"]):
        if not isinstance(b, dict) or b.get("use") not in REGISTRY:
            raise PipelineError("第 %d 塊積木不認得：%r" % (i + 1, b.get("use") if isinstance(b, dict) else b))
        cls = REGISTRY[b["use"]]
        on = b.get("on", True)
        if not isinstance(on, bool):
            raise PipelineError("%s.on 要是 true／false" % cls.id)
        if cls.locked and not on:
            raise PipelineError("%s（%s）是必要的積木，不能關" % (cls.id, cls.label))
        out.append({"use": cls.id, "on": on, "params": cls().check(b.get("params") or {})})
    used = {b["use"] for b in out}
    missing = [cid for cid, cls in REGISTRY.items() if cls.locked and cid not in used]
    if missing:
        raise PipelineError("缺了必要的積木：%s" % "、".join(missing))
    dup = [u for u in used if sum(1 for b in out if b["use"] == u) > 1]
    if dup:
        raise PipelineError("同一種積木只能放一塊：%s" % "、".join(sorted(dup)))
    check_order(out)
    return dict(pipe, blocks=out)

def compile_spec(spec, files, probes, caps, workdir, strict=True, fontsdir=None, container="mp4",
                 caption_fontsdir=None):
    pipe = normalize(pipeline_from_spec(spec, container))
    return compile_pipeline(pipe, files, probes, caps, workdir, strict=strict, fontsdir=fontsdir,
                            container=container, caption_fontsdir=caption_fontsdir)

def analyze_spec(spec, files, detect, body, pipeline=None):
    params = {}
    for b in clean_user(pipeline or []):
        if b["use"] == "twist_detect":
            params = b.get("params") or {}
    blk = TwistDetect()
    p = blk.check(params)
    custom = any(p.get(k) != v for k, v in TwistDetect.DEFAULTS.items())
    caps, effs, at = blk.analyze(p, spec, files, detect, body)
    return caps, effs, at, blk.warnings, custom

def seam_reports(pipeline, spec, files, ffmpeg):
    for b in clean_user(pipeline or []):
        if b["use"] == "seam_check" and b.get("on", True):
            cls = REGISTRY["seam_check"]
            return cls().measure(cls().check(b.get("params") or {}), spec, files, ffmpeg)
    return None

def compile_custom(pipe, files, probes, caps, workdir, **kw):
    try:
        return compile_pipeline(pipe, files, probes, caps, workdir, **kw), []
    except Exception as e:
        first = e
    why = type(first).__name__
    cand = [b["use"] for b in pipe["blocks"] if b.get("on", True) and getattr(REGISTRY[b["use"]], "drop_on_fail", False)]
    tries = [[bid] for bid in cand] + ([cand] if len(cand) > 1 else [])
    for drop in tries:
        trial = dict(pipe, blocks=[b for b in pipe["blocks"] if b["use"] not in drop])
        try:
            got = compile_pipeline(trial, files, probes, caps, workdir, **kw)
        except Exception:
            continue
        got["warnings"] = list(got["warnings"]) + ["%s 沒做成，已拿掉，其他照常" % REGISTRY[bid].label for bid in drop]
        return got, [(bid, why) for bid in drop]
    raise first

def _on(pipeline, bid):
    for b in clean_user(pipeline or []):
        if b["use"] == bid and b.get("on", True):
            cls = REGISTRY[bid]
            return cls, cls().check(b.get("params") or {})
    return None

def extra_inputs(pipeline, spec):
    got = _on(pipeline, "watermark")
    if not got or got[1]["kind"] != "image":
        return []
    key = got[1]["logo"]
    return [key] if key.startswith("originals/%s/" % spec["user"]) else []

def cover_output(pipeline, src, demuxer, duration, dest, ffmpeg, fps=24):
    got = _on(pipeline, "cover")
    if not got:
        return None
    path, rep = got[0]().extract(got[1], src, demuxer, duration, dest, ffmpeg, fps=fps)
    return path, got[1]["format"], rep
