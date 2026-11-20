import argparse
import json
import sys

from . import long_plan

CAPS_KINDS = ("first_frame", "last_frame", "input_references")

TOOL = {
    "name": "long_plan",
    "description": ("（dry-run，不花錢）把 60 秒左右的腳本或鏡頭表排成接續計畫：每段首幀從哪來（上一段尾幀／灰模首幀／"
                    "角色參考圖）、尾幀交給哪一段、哪些接縫要量 seam_check、總秒數、最壞段數、要上傳幾張、成本估計。"
                    "首尾幀能不能用只看 caps（先叫 model_caps 工具，把那個模型的那一列原樣傳進來）的實測結果，"
                    "沒測過或沒給 caps 的退回參考圖並列在 warnings。"
                    "回應的 chain_segments 直接給 chain_create；送件照舊走報價與核准卡。"),
    "input_schema": {
        "type": "object", "required": ["input"], "additionalProperties": False,
        "properties": {
            "input": {"type": "object", "description": "腳本 {version:1, segments:[{prompt, seconds, shot_key?}]} 或"
                                                       "鏡頭表 {version:1, shots:鏡頭描述檔, prompts:{鏡號:提示詞}}"},
            "caps": {"type": "object", "description": "model_caps 工具回的那一列（first_frame／last_frame／input_references…）；"
                                                      "沒給＝全部當沒實測"},
            "model": {"type": "string", "description": "模型 ref（只是標籤，原樣回在結果裡）"},
            "has_cast_refs": {"type": "boolean", "default": False, "description": "專案有沒有角色參考圖"},
            "price_per_second": {"type": ["number", "null"], "minimum": 0, "description": "報價的每秒單價；沒給不估成本"},
            "max_retakes": {"type": "integer", "minimum": 0, "maximum": 5, "default": 1},
            "target_seconds": {"type": ["number", "null"], "minimum": 1, "description": "目標總長，差超過 5 秒會提醒"},
        },
    },
}
_KEYS = set(TOOL["input_schema"]["properties"])

def run(args):
    if not isinstance(args, dict):
        return {"error": "bad_args", "detail": "參數要是物件"}
    extra = set(args) - _KEYS
    if extra:
        return {"error": "bad_args", "detail": "不認得的參數 %s" % "、".join(sorted(extra))}
    model = args.get("model", "")
    if not isinstance(model, str) or len(model) > 80:
        return {"error": "bad_args", "detail": "model 要是最多 80 字的文字"}
    caps = args.get("caps")
    if caps is not None and (not isinstance(caps, dict) or
                             any(not isinstance(caps.get(k), (dict, type(None))) for k in CAPS_KINDS)):
        return {"error": "bad_args", "detail": "caps 要是 model_caps 的那一列（first_frame 這些欄位是物件）"}
    cast = args.get("has_cast_refs", False)
    if not isinstance(cast, bool):
        return {"error": "bad_args", "detail": "has_cast_refs 要是 true／false"}
    target = args.get("target_seconds")
    if target is not None and (isinstance(target, bool) or not isinstance(target, (int, float)) or target < 1):
        return {"error": "bad_args", "detail": "target_seconds 要是 ≥ 1 的數字"}
    try:
        p = long_plan.plan(args.get("input"), caps or {}, has_cast_refs=cast,
                           price_per_second=args.get("price_per_second"), max_retakes=args.get("max_retakes", 1),
                           target_seconds=target)
    except long_plan.PlanError as e:
        return {"error": "bad_input", "detail": str(e)}
    return {"dry_run": True, "model": model.strip(), "caps": "given" if caps else "none", "plan": p}

def main(argv=None, stdin=None, stdout=None):
    out = stdout or sys.stdout
    ap = argparse.ArgumentParser(prog="python3 -m filming.plan_cli", description="長片接續規劃（dry-run）")
    ap.add_argument("input", nargs="?", help="輸入 JSON 檔（- 表示 stdin）")
    ap.add_argument("--caps", help="能力表那一列的 JSON 檔（model_caps 工具的輸出）")
    ap.add_argument("--model", default="", help="模型 ref（只是標籤）")
    ap.add_argument("--cast-refs", action="store_true")
    ap.add_argument("--price", type=float)
    ap.add_argument("--retakes", type=int, default=1)
    ap.add_argument("--target", type=float)
    ap.add_argument("--schema", action="store_true", help="印出 Agent 工具描述")
    a = ap.parse_args(argv)

    def emit(obj, code):
        out.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
        return code
    if a.schema:
        return emit(TOOL, 0)
    if not a.input:
        return emit({"error": "bad_args", "detail": "要給輸入 JSON 檔（或 - 從 stdin 讀）"}, 2)
    try:
        if a.input == "-":
            raw = (stdin or sys.stdin).read()
        else:
            with open(a.input, encoding="utf-8") as fh:
                raw = fh.read()
    except OSError as e:
        return emit({"error": "unreadable", "detail": "讀不到 %s（%s）" % (a.input, e.strerror)}, 1)
    try:
        data = json.loads(raw)
    except ValueError:
        return emit({"error": "bad_input", "detail": "輸入不是 JSON"}, 2)
    caps = None
    if a.caps:
        try:
            with open(a.caps, encoding="utf-8") as fh:
                caps = json.load(fh)
        except OSError as e:
            return emit({"error": "unreadable", "detail": "讀不到 %s（%s）" % (a.caps, e.strerror)}, 1)
        except ValueError:
            return emit({"error": "bad_args", "detail": "--caps 不是 JSON"}, 2)
    res = run({"input": data, "model": a.model, "caps": caps, "has_cast_refs": a.cast_refs,
               "price_per_second": a.price, "max_retakes": a.retakes, "target_seconds": a.target})
    return emit(res, 2 if "error" in res else 0)

if __name__ == "__main__":
    sys.exit(main())
