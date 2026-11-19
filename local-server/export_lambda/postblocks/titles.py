from .base import Block

class Titles(Block):
    id = "titles"
    label = "片頭片尾字卡"
    stage = "text"
    params = {"titles": {"type": "object", "default": None, "nullable": True}}

    def text(self, p, c):
        import render
        c.text["trows"] = render.title_rows(p.get("titles"), c.t["body"])
