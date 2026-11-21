import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = (
    "local/studio_local.py", "local/sqlite_store.py", "local/agent_exec.py", "local/ui_profiles.py",
    "local/server_manifest.py", "local/smoke_packaged.py",
    "upstream.py", "studio_store.py", "studio_tools.py", "storyboard.py", "qc.py", "page_strip.py",
    "export_spec.py", "templates.py", "cast_refs.py", "shot_controls.py", "takes.py", "gen_retry.py", "approvals.py",
    "outpaint.py",
    "export_lambda/render.py", "export_lambda/twist.py", "scripts/export_local.py",
    "ui2.html",
    "previs/editor.js", "previs/core.js", "previs/vendor/three.module.min.js", "previs/vendor/OrbitControls.js",
    "previs/vendor/TransformControls.js", "previs/vendor/mp4-muxer.mjs",
    "fonts/NotoSansTC-Bold.otf", "fonts/OFL.txt", "fonts/README.md",
)
PACKAGES = ("filming", "export_lambda/postblocks", "cli/appletoken")
NOT_PACKED = {
    "local/dev_fake_upstream.py": "開發用，不進 App（手動測試與測試用的假上游；export-oss 另外帶）",
    "cli/appletoken/mcp/server.py": "stdio MCP 伺服器要 MCP SDK，桌面版附的 Python 沒有；本機 /mcp 只用 tools.py",
    "cli/appletoken/cli/__init__.py": "命令列（appletoken 指令），桌面版不用",
    "cli/appletoken/cli/commands.py": "命令列，桌面版不用",
    "cli/appletoken/cli/doctor.py": "命令列，桌面版不用",
    "cli/appletoken/cli/ledger.py": "命令列，桌面版不用",
    "cli/appletoken/cli/main.py": "命令列，桌面版不用",
    "cli/appletoken/cli/output.py": "命令列，桌面版不用",
}

def package_files(root=ROOT):
    out = set()
    for pkg in PACKAGES:
        for base, dirs, names in os.walk(os.path.join(root, pkg)):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            out |= {os.path.relpath(os.path.join(base, n), root).replace(os.sep, "/") for n in names if n.endswith(".py")}
    return out

def server_files(root=ROOT):
    return sorted((set(FILES) | package_files(root)) - set(NOT_PACKED))

if __name__ == "__main__":
    if sys.argv[1:] != ["--json"]:
        sys.exit("用法：python -I local/server_manifest.py --json")
    print(json.dumps({"files": server_files(), "not_packed": NOT_PACKED}, ensure_ascii=False))
