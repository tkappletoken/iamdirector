from .base import STAGES, PipelineError
from .compile import compile_pipeline

SIMPLE = ("bool", "enum", "number", "text")

TEMPLATE_PIPELINES = {
    "meme": [{"use": "fit", "params": {"mode": "crop"}}, {"use": "fps", "params": {"fps": 30}},
             {"use": "white_flash"}, {"use": "meme_captions"}, {"use": "disclosure", "on": False},
             {"use": "subtitles", "params": {"mode": "none"}}],
}

def catalog():
    from . import REGISTRY
    out = []
    for cls in REGISTRY.values():
        out.append({"id": cls.id, "label": cls.label, "stage": cls.stage, "locked": cls.locked,
                    "sortable": cls.stage == "overlay", "optional": cls.optional, "passes": cls.passes,
                    "params": {k: dict(v) for k, v in cls.params.items() if not v.get("from_spec")},
                    "doc": (cls.__doc__ or "").strip().split("\n")[0]})
    return {"stages": list(STAGES), "blocks": out,
            "templates": {k: [dict(b) for b in v] for k, v in TEMPLATE_PIPELINES.items()}}

def clean_user(blocks):
    from . import REGISTRY
    if not isinstance(blocks, list) or len(blocks) > 64:
        raise PipelineError("pipeline 要是最多 64 塊積木的陣列")
    out, seen = [], set()
    for i, b in enumerate(blocks):
        if not isinstance(b, dict) or set(b) - {"use", "on", "params"}:
            raise PipelineError("第 %d 塊積木只能有 use、on、params" % (i + 1))
        cls = REGISTRY.get(b.get("use"))
        if cls is None:
            raise PipelineError("第 %d 塊積木不認得：%r" % (i + 1, b.get("use")))
        if cls.id in seen:
            raise PipelineError("同一種積木只能放一塊：%s" % cls.id)
        seen.add(cls.id)
        on = b.get("on", True)
        if not isinstance(on, bool):
            raise PipelineError("%s.on 要是 true／false" % cls.id)
        if cls.locked and not on:
            raise PipelineError("%s（%s）是必要的積木，不能關" % (cls.id, cls.label))
        params = b.get("params") or {}
        if not isinstance(params, dict):
            raise PipelineError("%s.params 要是物件" % cls.id)
        for k in params:
            spec = cls.params.get(k)
            if spec is None:
                raise PipelineError("%s：不認得的參數 %s" % (cls.id, k))
            if spec.get("type") not in SIMPLE or spec.get("from_spec"):
                raise PipelineError("%s.%s 請用原本的欄位設定（不能經 pipeline 改）" % (cls.id, k))
        cls().check(params)
        out.append({"use": cls.id, "on": on, "params": dict(params)})
    return out

def merge(spec, user, container="mp4"):
    from . import REGISTRY, normalize, pipeline_from_spec
    default = pipeline_from_spec(spec, container)
    if not user:
        return default, False
    base = {b["use"]: b for b in default["blocks"]}
    rank = {s: i for i, s in enumerate(STAGES)}
    out = []
    for u in user:
        d = base.get(u["use"], {"use": u["use"], "params": {}})
        out.append({"use": u["use"], "on": u.get("on", True), "params": dict(d["params"], **(u.get("params") or {}))})
    mentioned = {b["use"] for b in out}
    for d in default["blocks"]:
        if d["use"] in mentioned:
            continue
        r = rank[REGISTRY[d["use"]].stage]
        at = next((i for i, b in enumerate(out) if rank[REGISTRY[b["use"]].stage] > r), len(out))
        out.insert(at, dict(d, on=True))
    pipe = normalize(dict(default, blocks=out))
    plain = normalize(default)
    return pipe, pipe["blocks"] != plain["blocks"]

def preview(spec, user=None, caps=None, container="mp4", caption_fontsdir=None, fontsdir=None):
    import twist as tw
    pipe, custom = merge(spec, user, container)
    warnings = []
    body = None
    try:
        import render
        body = render.timing(spec)["body"]
    except Exception:
        pass
    tcfg = spec.get("twist") or {}
    at = tcfg.get("at") if tcfg.get("at") is not None else tcfg.get("hint")
    placements = []
    blocks = []
    for b in pipe["blocks"]:
        p = dict(b["params"])
        if b["use"] in ("meme_captions", "white_flash") and p.get("items"):
            try:
                p["items"] = [dict(x, start=tw.resolve(x["start"], at, body), end=tw.resolve(x["end"], at, body))
                              for x in p["items"]]
                p["items"] = [x for x in p["items"] if x["end"] > x["start"]]
            except tw.TwistError:
                warnings.append("反轉點要偵測之後才知道，預覽先不放字卡與白閃")
                p["items"] = []
            if b.get("on", True):
                placements += [{"use": b["use"], "start": x["start"], "end": x["end"],
                                "text": x.get("text")} for x in p["items"]]
        blocks.append(dict(b, params=p))
    files = {}
    probes = {}
    for v in spec["video"] + spec["audio"]:
        files[v["key"]] = "/preview/" + v["key"].replace("/", "_")
        probes[v["key"]] = {"has_video": True, "has_audio": True, "demuxer": "mov", "duration": 0}
    caps = caps if caps is not None else {"libass": True, "encoders": {"libx264"}}
    try:
        got = compile_pipeline(dict(pipe, blocks=blocks), files, probes, caps, "/preview", strict=False,
                               fontsdir=fontsdir, container=container, caption_fontsdir=caption_fontsdir)
    except Exception as e:
        msg = str(e) if isinstance(e, PipelineError) or type(e).__name__ == "RenderError" else type(e).__name__
        return {"blocks": pipe["blocks"], "custom": custom, "total": None, "warnings": warnings + [msg],
                "filtergraph": None, "placements": placements}
    argv = got["argv"]
    graph = argv[argv.index("-filter_complex") + 1] if "-filter_complex" in argv else None
    t = got["total"]
    for b in pipe["blocks"]:
        if b["use"] == "disclosure" and b.get("on", True) and body is not None and t and t > body:
            placements.append({"use": "disclosure", "start": body, "end": t})
    return {"blocks": pipe["blocks"], "custom": custom, "total": t, "warnings": warnings + got["warnings"],
            "filtergraph": graph, "placements": placements}

