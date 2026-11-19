from .base import Block

class TwistDetect(Block):
    id = "twist_detect"
    label = "反轉點"
    stage = "analyze"
    params = {"twist": {"type": "object", "default": {}},
              "hint_weight": {"type": "number", "min": 0, "max": 5, "default": 0},
              "hint_fallback": {"type": "bool", "default": False}}
    DEFAULTS = {"hint_weight": 0, "hint_fallback": False}

    def analyze(self, p, spec, files, detect, body):
        import render
        import twist as tw
        self.warnings = []
        caps, effs = spec.get("captions") or [], spec.get("effects") or []
        tcfg = spec.get("twist") or {}
        at = tcfg.get("at")
        if at is None and tcfg.get("auto") and (caps or effs) and spec.get("video"):
            v = spec["video"][0]
            try:
                got = detect(files[v["key"]])
            except tw.TwistError as e:
                raise render.RenderError("偵測反轉點失敗：%s" % e) from None
            pick = got.get("at")
            hint = tcfg.get("hint")
            w = float(p.get("hint_weight") or 0)
            if w > 0 and hint is not None and got.get("candidates"):
                src_hint = float(hint) + v["in"]
                best = max(got["candidates"], key=lambda q: (q.get("score") or 0) / (1 + w * abs(q["t"] - src_hint)))
                pick = best["t"]
            if pick is not None:
                at = round(pick - v["in"], 3)
            elif p.get("hint_fallback") and hint is not None:
                at = round(float(hint), 3)
                self.warnings.append("偵測不到反轉點，改用作品設定的 %s 秒（source: fallback）" % at)
        try:
            out_c = [dict(q, start=tw.resolve(q["start"], at, body), end=tw.resolve(q["end"], at, body)) for q in caps]
            out_e = [dict(e, start=tw.resolve(e["start"], at, body), end=tw.resolve(e["end"], at, body)) for e in effs]
        except tw.TwistError as e:
            raise render.RenderError(str(e)) from None
        return ([q for q in out_c if q["end"] > q["start"]], [e for e in out_e if e["end"] > e["start"]], at)
