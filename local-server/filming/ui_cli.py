import argparse
import json
import sys

from . import ui_compose

def main(argv=None, stdin=None, stdout=None):
    out = stdout or sys.stdout
    ap = argparse.ArgumentParser(prog="python3 -m filming.ui_cli", description="先對話、再長出專屬介面（dry-run）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("questions", help="印出訪談題目")
    c = sub.add_parser("compose", help="答案 → 介面描述檔")
    c.add_argument("answers", help="答案 JSON 檔（- 表示 stdin）")
    c.add_argument("--name", help="這份介面的名字（顯示用）")
    a = ap.parse_args(argv)

    def emit(obj, code):
        out.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
        return code
    if a.cmd == "questions":
        return emit({"version": ui_compose.VERSION, "questions": ui_compose.questions()}, 0)
    try:
        if a.answers == "-":
            raw = (stdin or sys.stdin).read()
        else:
            with open(a.answers, encoding="utf-8") as fh:
                raw = fh.read()
    except OSError as e:
        return emit({"error": "unreadable", "detail": "讀不到 %s（%s）" % (a.answers, e.strerror)}, 1)
    try:
        answers = json.loads(raw)
    except ValueError:
        return emit({"error": "bad_input", "detail": "答案不是 JSON"}, 2)
    if isinstance(answers, dict) and isinstance(answers.get("answers"), dict):
        answers = answers["answers"]
    try:
        return emit(dict(ui_compose.compose(answers, a.name), dry_run=True), 0)
    except ui_compose.ComposeError as e:
        return emit({"error": "bad_input", "detail": str(e)}, 2)

if __name__ == "__main__":
    sys.exit(main())
