
STAGES = ("analyze", "source", "timeline", "overlay", "append", "text", "audio", "output")

class PipelineError(ValueError):
    pass

class Block:
    id = ""
    label = ""
    stage = ""
    locked = False
    params = {}
    optional = False
    passes = 1
    capture = None

    def defaults(self):
        return {k: v.get("default") for k, v in self.params.items() if "default" in v}

    def check(self, p):
        out = self.defaults()
        for k, v in (p or {}).items():
            spec = self.params.get(k)
            if spec is None:
                raise PipelineError("%s：不認得的參數 %s" % (self.id, k))
            out[k] = _check_value(self.id, k, spec, v)
        return self.validate(out)

    def validate(self, p):
        return p

def _check_value(bid, name, spec, v):
    t = spec.get("type")
    where = "%s.%s" % (bid, name)
    if v is None and spec.get("nullable"):
        return None
    if t == "bool":
        if not isinstance(v, bool):
            raise PipelineError("%s 要是 true／false" % where)
        return v
    if t == "enum":
        if v not in spec["values"]:
            raise PipelineError("%s 只能是 %s" % (where, "／".join(map(str, spec["values"]))))
        return v
    if t == "number":
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise PipelineError("%s 要是數字" % where)
        if ("min" in spec and v < spec["min"]) or ("max" in spec and v > spec["max"]):
            raise PipelineError("%s 要在 %s–%s 之間" % (where, spec.get("min"), spec.get("max")))
        return v
    if t == "text":
        if not isinstance(v, str) or len(v) > spec.get("max", 10000):
            raise PipelineError("%s 要是最多 %d 字的文字" % (where, spec.get("max", 10000)))
        return v
    if t in ("list", "object", "time"):
        return v
    raise PipelineError("%s：參數表寫了不認得的型別 %r" % (where, t))
