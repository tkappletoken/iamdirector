import contextlib
import importlib
import json
import os
import subprocess
import sys
import tempfile

MCP_NEED = ("agent_plan", "agent_run", "ui_compose", "ui_apply", "dirctl_compose", "work_run")
SWITCH_ENV = ("STUDIO_", "GEN_RETRY", "POSTBLOCKS_ENGINE")
SWITCHES_OFF = {"agentloop_on": False, "uiprofiles_on": False, "frame_relay_on": False, "agent_qc_on": False,
                "mcp_direct_on": False, "engine_now": "legacy", "agent_scope_now": "basic",
                "gen_retry.mode": "off", "gen_retry.qc_mode": "off", "gen_retry.auto_mode": "off",
                "blockout_frames.mode": "legacy"}
MAC_H264 = ("h264_videotoolbox", "libx264")
LINUX_WEBM = ("libvpx-vp9", "libopus")

def paths(root):
    return [os.path.join(root, p) for p in ("local", "", "export_lambda", "scripts", "cli")]

def module_name(rel):
    rel = rel[:-3]
    for prefix in ("local/", "export_lambda/", "scripts/", "cli/"):
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    if rel.endswith("/__init__"):
        rel = rel[:-len("/__init__")]
    return rel.replace("/", ".")

def manifest(root):
    sys.path.insert(0, os.path.join(root, "local"))
    import server_manifest
    return server_manifest.server_files(root)

def check_python():
    return None if sys.version_info >= (3, 11) else "直譯器是 %d.%d，至少要 3.11" % sys.version_info[:2]

def check_files(root, files):
    missing = [f for f in files if not os.path.isfile(os.path.join(root, f))]
    return "缺檔：%s" % "、".join(missing) if missing else None

def check_imports(root, files):
    for p in reversed(paths(root)):
        if p not in sys.path:
            sys.path.insert(0, p)
    bad = []
    for f in files:
        if f.endswith(".py") and f != "local/smoke_packaged.py":
            try:
                importlib.import_module(module_name(f))
            except Exception as e:
                bad.append("%s（%s: %s）" % (f, type(e).__name__, e))
    return "import 失敗：%s" % "；".join(bad) if bad else None

def check_no_sdk():
    hit = sorted(m for m in sys.modules if m == "mcp" or m.startswith("mcp.") or m == "appletoken.mcp.server")
    return "載入了 MCP SDK：%s" % "、".join(hit) if hit else None

def check_mcp():
    from appletoken.core import Client
    from appletoken.core.session import Session
    from appletoken.mcp import tools
    s = Session("x" * 40, base_url="http://127.0.0.1:1", kind="token", register=False)
    names = set(tools.Registry(s, allow_spend=True, remote=True, local=True, client=Client(s)).names())
    lack = [n for n in MCP_NEED if n not in names]
    return "/mcp 工具表少了：%s" % "、".join(lack) if lack else None

SWITCH_PROBE = r"""
import json, sys
sys.path[:0] = sys.argv[1].split("\n")
import studio_local, gen_retry
from filming import blockout_frames
st = studio_local.State(sys.argv[2], "http://127.0.0.1:1", None)
got = {k: getattr(st, k)() for k in ("agentloop_on", "uiprofiles_on", "frame_relay_on", "agent_qc_on", "mcp_direct_on",
                                    "engine_now", "agent_scope_now")}
got.update({"gen_retry.mode": gen_retry.mode(), "gen_retry.qc_mode": gen_retry.qc_mode(),
            "gen_retry.auto_mode": gen_retry.auto_mode(), "blockout_frames.mode": blockout_frames.mode()})
print(json.dumps(got))
"""

def check_switches(root):
    env = {k: v for k, v in os.environ.items() if not k.startswith(SWITCH_ENV)}
    with tempfile.TemporaryDirectory() as data:
        r = subprocess.run([sys.executable, "-I", "-B", "-c", SWITCH_PROBE, "\n".join(paths(root)), data],
                           capture_output=True, text=True, env=env, timeout=120, stdin=subprocess.DEVNULL)
    if r.returncode:
        return "問不到開關：%s" % (r.stderr.strip().splitlines() or ["(沒有訊息)"])[-1]
    got = json.loads(r.stdout.strip().splitlines()[-1])
    wrong = ["%s=%r（要 %r）" % (k, got.get(k), v) for k, v in SWITCHES_OFF.items() if got.get(k) != v]
    return "開關預設不是關的：%s" % "、".join(wrong) if wrong else None

def check_ffmpeg(ffmpeg, platform=None):
    import render
    enc = render.ffmpeg_caps(ffmpeg).get("encoders")
    if not enc:
        return "問不出這支 ffmpeg 的編碼器：%s" % ffmpeg
    if (platform or sys.platform) == "darwin":
        return None if any(e in enc for e in MAC_H264) else "macOS 的 ffmpeg 沒有 %s" % "／".join(MAC_H264)
    if (platform or sys.platform).startswith("linux"):
        miss = [e for e in LINUX_WEBM if e not in enc]
        return "Linux 的 ffmpeg 沒有 %s（WebM 匯出要它）" % "／".join(miss) if miss else None
    try:
        render.video_codec_args({"encoders": enc}, 720)
    except render.RenderError as e:
        return str(e)
    return None

USAGE = "用法：python -I -B local/smoke_packaged.py <伺服器資料夾> [--ffmpeg <路徑>] [--json]"

def parse(argv):
    rest, ffmpeg, as_json = list(argv), None, False
    if "--json" in rest:
        rest.remove("--json")
        as_json = True
    if "--ffmpeg" in rest:
        i = rest.index("--ffmpeg")
        if i + 1 >= len(rest):
            return None
        ffmpeg = rest.pop(i + 1)
        rest.pop(i)
    if len(rest) != 1 or rest[0].startswith("-"):
        return None
    return os.path.abspath(rest[0]), ffmpeg, as_json

def run(root, ffmpeg=None):
    try:
        files = manifest(root)
    except Exception as e:
        return {"ok": False, "files": 0, "checks": [{"name": "manifest", "ok": False, "detail": "%s: %s" % (type(e).__name__, e)}]}
    checks = [("python", check_python), ("files", lambda: check_files(root, files)), ("imports", lambda: check_imports(root, files)),
              ("no_sdk", check_no_sdk), ("mcp", check_mcp), ("switches", lambda: check_switches(root))]
    if ffmpeg is not None:
        checks.append(("ffmpeg", lambda: check_ffmpeg(ffmpeg)))
    out = []
    for name, fn in checks:
        try:
            why = fn()
        except Exception as e:
            why = "%s: %s" % (type(e).__name__, e)
        out.append({"name": name, "ok": not why, "detail": why})
    return {"ok": all(c["ok"] for c in out), "files": len(files), "checks": out}

def main(argv):
    args = parse(argv)
    if args is None:
        print(USAGE, file=sys.stderr)
        return 2
    root, ffmpeg, as_json = args
    if as_json:
        with contextlib.redirect_stdout(sys.stderr):
            res = run(root, ffmpeg)
        print(json.dumps(res, ensure_ascii=False))
    else:
        res = run(root, ffmpeg)
        for c in res["checks"]:
            print(("FAIL %s：%s" % (c["name"], c["detail"])) if not c["ok"] else "ok %s" % c["name"])
        print("冒煙檢查：%d 項，%d 項失敗（%d 個檔）" % (len(res["checks"]), sum(not c["ok"] for c in res["checks"]), res["files"]))
    return 0 if res["ok"] else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
