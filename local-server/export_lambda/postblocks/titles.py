from .base import Block

def title_rows(titles, body):
    out = []
    t = titles or {}
    if t.get("open"):
        out.append({"start": 0.0, "end": round(min(body, t["open"]["seconds"]), 3), "text": t["open"]["text"], "where": "open"})
    if t.get("end"):
        out.append({"start": round(max(0.0, body - t["end"]["seconds"]), 3), "end": round(body, 3),
                    "text": t["end"]["text"], "where": "end"})
    return [x for x in out if x["end"] > x["start"]]

class Titles(Block):
    id = "titles"
    label = "片頭片尾字卡"
    stage = "text"
    params = {"titles": {"type": "object", "default": None, "nullable": True}}

    def text(self, p, c):
        c.text["trows"] = title_rows(p.get("titles"), c.t["body"])
