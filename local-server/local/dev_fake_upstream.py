import argparse
import datetime
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GOOD = "-".join(["at", "local", secrets.token_hex(12)])
SEEN = []
RES_PRICED = re.compile(r"(?i)minimax-h3|seedance")
FAKE = {"quote_ttl": 900, "expired": set(), "price": None, "issued": {}, "usage": [], "images": {}, "unique_jobs": False,
        "videos": {}, "assets": [], "models": None,
        "long": False, "long_quotes": {}, "long_jobs": {}, "long_blobs": {}, "verdicts": []}
LONG_MODEL = "gputw/minimax-h3"
LONG_PASS = {"subjects_ok": True, "colors_ok": True, "defects": "", "overall": 8}

def reset_fake():
    FAKE.update(quote_ttl=900, expired=set(), price=None, issued={}, usage=[], images={}, unique_jobs=False, videos={}, assets=[], models=None,
                long=False, long_quotes={}, long_jobs={}, long_blobs={}, verdicts=[])
GONE = set()
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a4c40000000049454e44ae426082")
MEDIA = {"mp4": b"\x00\x00\x00\x18ftypmp42" + b"x" * 100, "mp3": b"ID3" + b"\x00" * 7 + b"\xff\xfb" + b"a" * 400}

def make_media():
    ff = shutil.which("ffmpeg")
    if not ff:
        return False
    d = tempfile.mkdtemp(prefix="lm-media-")
    try:
        subprocess.run([ff, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:d=2:r=24",
                        "-pix_fmt", "yuv420p", os.path.join(d, "v.mp4")], check=True, timeout=60)
        subprocess.run([ff, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=1.5",
                        os.path.join(d, "a.wav")], check=True, timeout=60)
        with open(os.path.join(d, "v.mp4"), "rb") as f:
            MEDIA["mp4"] = f.read()
        with open(os.path.join(d, "a.wav"), "rb") as f:
            MEDIA["wav"] = f.read()
        return True
    finally:
        shutil.rmtree(d, ignore_errors=True)

def _long_first(body):
    fi = body.get("frame_images")
    ref = None
    if isinstance(fi, list) and fi:
        x = next((f for f in fi if not isinstance(f, dict) or f.get("frame_type") in (None, "first_frame")), None)
        ref = x.get("image_url") if isinstance(x, dict) else x
    ref = ref or body.get("image_url")
    m = re.match(r"^asset://(ast_[0-9a-f]{20})$", str(ref or ""))
    return FAKE["long_blobs"].get(m.group(1)) if m else None

def _long_video(jid):
    job = FAKE["long_jobs"][jid]
    if job.get("mp4"):
        return job["mp4"]
    import random
    ff = shutil.which("ffmpeg")
    if not ff:
        return MEDIA["mp4"]
    body = job["body"]
    sec = max(0.5, float(body.get("seconds") or 2))
    rnd = random.Random(jid)
    d = tempfile.mkdtemp(prefix="fake-long-")
    try:
        noise = os.path.join(d, "n.ppm")
        with open(noise, "wb") as f:
            f.write(b"P6 80 60 255\n" + bytes(rnd.randrange(256) for _ in range(80 * 60 * 3)))
        args = [ff, "-loglevel", "error", "-y", "-loop", "1", "-framerate", "12", "-t", str(sec), "-i", noise,
                "-f", "lavfi", "-i", "sine=f=%d:d=%s" % (220 + rnd.randrange(600), sec)]
        first = _long_first(body)
        if first:
            fp = os.path.join(d, "first.png")
            with open(fp, "wb") as f:
                f.write(first)
            args += ["-i", fp, "-filter_complex",
                     "[0:v]scale=320:240:flags=neighbor,setsar=1[b];[2:v]scale=320:240,setsar=1[f];"
                     "[b][f]overlay=enable='lt(n,6)'[v]", "-map", "[v]"]
        else:
            args += ["-vf", "scale=320:240:flags=neighbor,setsar=1", "-map", "0:v"]
        out = os.path.join(d, "v.mp4")
        enc = ["-c:v", "libx264", "-crf", "4"] if _has_x264(ff) else ["-c:v", "h264_videotoolbox", "-b:v", "20M"]
        subprocess.run(args + ["-map", "1:a", "-t", str(sec), "-pix_fmt", "yuv420p"] + enc + ["-c:a", "aac", out],
                       check=True, timeout=120)
        with open(out, "rb") as f:
            job["mp4"] = f.read()
        return job["mp4"]
    finally:
        shutil.rmtree(d, ignore_errors=True)

def _has_x264(ff, _seen={}):
    if ff not in _seen:
        r = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30)
        _seen[ff] = "libx264" in r.stdout
    return _seen[ff]

class FakeUpstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _out(self, code, obj, ctype="application/json"):
        raw = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _auth(self):
        if self.headers.get("Authorization") != "Bearer " + GOOD:
            self._out(401, {"error": {"code": "invalid_api_key", "message": "bad key"}})
            return False
        return True

    def do_GET(self):
        SEEN.append(("GET", self.path, None))
        if not self._auth():
            return
        p = self.path
        if p == "/v2/me":
            return self._out(200, {"available": 12.5})
        if p == "/v2/models" and FAKE.get("models"):
            return self._out(200, {"data": FAKE["models"]})
        if p == "/v2/models":
            data = [{"slug": "siraya/Seedance-2.0", "ref": "siraya/Seedance-2.0", "family": "seedance-2.0",
                     "provider": {"id": "siraya"}, "capabilities": ["video"], "modality": "video", "name": "Seedance-2.0"}]
            if FAKE["long"]:
                data.append({"slug": LONG_MODEL, "ref": LONG_MODEL, "family": "minimax-h3", "provider": {"id": "gputw"},
                             "capabilities": ["video"], "modality": "video", "name": "minimax-h3"})
            return self._out(200, {"data": data})
        if FAKE["long"] and p.startswith("/v2/videos/") and p.endswith("/content") and p.split("/")[3] in FAKE["long_jobs"]:
            return self._out(200, _long_video(p.split("/")[3]), "video/mp4")
        if FAKE["long"] and re.match(r"^/v2/assets/ast_[0-9a-f]{20}/content$", p) and p.split("/")[3] in FAKE["long_blobs"]:
            return self._out(200, FAKE["long_blobs"][p.split("/")[3]], "image/png")
        if p.startswith("/v2/videos/job_tr") and p.endswith("/content"):
            return self._out(200, MEDIA.get("mp4a", MEDIA["mp4"]), "video/mp4")
        if p.startswith("/v2/videos/") and p.endswith("/content"):
            if p.split("/")[3] in GONE:
                return self._out(404, {"error": {"code": "not_found", "message": "gone"}})
            return self._out(200, MEDIA["mp4"], "video/mp4")
        if p.startswith("/v2/videos/"):
            vid = p.rsplit("/", 1)[1]
            if vid in FAKE["videos"]:
                return self._out(200, dict(FAKE["videos"][vid], id=vid))
            return self._out(200, {"id": vid, "status": "completed", "model": "siraya/Seedance-2.0"})
        if p.startswith("/v2/music/") and p.endswith("/content"):
            return self._out(200, MEDIA.get("wav", MEDIA["mp3"]), "audio/wav" if "wav" in MEDIA else "audio/mpeg")
        if p.startswith("/v2/music/"):
            return self._out(200, {"id": p.split("/")[3], "status": "completed"})
        if p == "/v2/images/img_fake1/content/0":
            return self._out(200, PNG, "image/png")
        if p.startswith("/v2/usage"):
            return self._out(200, {"object": "list", "data": FAKE["usage"]})
        if p.startswith("/v2/images/") and p.split("/")[3] in FAKE["images"]:
            if p.count("/") == 5:
                return self._out(200, PNG, "image/png")
            return self._out(200, FAKE["images"][p.split("/")[3]])
        if re.match(r"^/v2/assets/ast_[0-9a-f]{20}/content$", p):
            return self._out(200, PNG, "image/png")
        if p.startswith("/v2/assets"):
            tag = (urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("tag") or [None])[0]
            return self._out(200, {"data": [x for x in (FAKE.get("assets") or []) if not tag or tag in (x.get("tags") or [])]})
        return self._out(404, {"error": "nope"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        SEEN.append(("POST", self.path, body))
        if not self._auth():
            return
        p = self.path
        if p == "/v2/videos/generations":
            if not body.get("quote_id") and RES_PRICED.search(str(body.get("model") or "")) and not body.get("resolution"):
                return self._out(400, {"error": {"code": "validation_error", "message": "這個模型的計價依解析度區分，請指定 resolution"}})
            if body.get("quote_id"):
                if body.get("confirm") and (body["quote_id"] in FAKE["expired"]
                                            or FAKE["issued"].get(body["quote_id"], 1e18) <= time.time()):
                    return self._out(400, {"error": {"code": "validation_error",
                                                     "message": "確認單已過期（有效期 15 分鐘），請重新送出一次請求"}})
                if body.get("confirm") and FAKE["long"]:
                    jid = "job_" + secrets.token_hex(6)
                    FAKE["long_jobs"][jid] = {"body": FAKE["long_quotes"].get(body["quote_id"]) or {}}
                    return self._out(200, {"id": jid, "status": "queued"})
                if body.get("confirm"):
                    jid = "job_" + secrets.token_hex(6) if FAKE["unique_jobs"] else "job_abc123"
                    return self._out(200, {"id": jid, "status": "queued"})
                return self._out(200, {"quote_id": body["quote_id"], "status": "cancelled"})
            qid, exp = "q_" + secrets.token_hex(4), time.time() + FAKE["quote_ttl"]
            FAKE["issued"][qid] = exp
            if FAKE["long"]:
                FAKE["long_quotes"][qid] = body
            return self._out(200, {"quote_id": qid, "estimate": {"points": FAKE["price"] or "3.00"},
                                   "expires_at": datetime.datetime.fromtimestamp(exp, datetime.timezone.utc).isoformat(),
                                   "resolved": {k: v for k, v in body.items() if k != "require_confirmation"},
                                   "status": "needs_confirmation"})
        if p == "/v2/quote":
            return self._out(200, {"est_cost": "1.20"})
        if p == "/v2/audio/speech":
            return self._out(200, MEDIA.get("wav", MEDIA["mp3"]), "audio/wav" if "wav" in MEDIA else "audio/mpeg")
        if p == "/v2/music/generations":
            return self._out(200, {"id": "mus_abc", "status": "completed"})
        if p == "/v2/assets" and FAKE["long"]:
            import base64 as b64
            aid = "ast_" + secrets.token_hex(10)
            m = re.match(r"^data:[^;,]+;base64,(.*)$", str(body.get("source") or ""), re.S)
            FAKE["long_blobs"][aid] = b64.b64decode(m.group(1)) if m else b""
            return self._out(200, {"id": aid, "status": "ready"})
        if p == "/v2/assets":
            return self._out(200, {"id": "ast_" + "a1" * 10, "status": "ready"})
        if p == "/v2/images/generations":
            if body.get("prompt") == "slow":
                time.sleep(1.5)
            if body.get("prompt") == "drop":
                self.close_connection = True
                return
            if body.get("response_format") == "b64_json":
                import base64 as b64
                return self._out(200, {"id": "img_fake1", "data": [{"b64_json": b64.b64encode(PNG).decode()}]})
            if body.get("prompt") == "url-only":
                return self._out(200, {"id": "img_fake1", "data": [{"url": "https://example.invalid/x.png"}]})
            return self._out(200, {"data": [{"url": "https://example.invalid/x.png"}]})
        if p == "/v2/audio/transcriptions":
            ok = isinstance(body.get("file"), str) and body["file"].startswith("data:audio/wav;base64,")
            return self._out(200 if ok else 400, {"text": "雨停之前，我會一直在這裡等。"} if ok else
                             {"error": {"code": "validation_error", "message": "file 只接受音訊"}})
        if p == "/v2/chat/completions" and FAKE["long"]:
            v = FAKE["verdicts"].pop(0) if FAKE["verdicts"] else LONG_PASS
            return self._out(200, {"id": "chatcmpl_long", "usage": {"prompt_tokens": 10, "completion_tokens": 20,
                                                                     "total_tokens": 30},
                                   "choices": [{"message": {"content": json.dumps(v)}}]})
        if p == "/v2/chat/completions":
            shots = [{"prompt": "便利店夜景，店員抬頭", "seconds": 5}, {"prompt": "客人推門進來", "seconds": 5}]
            return self._out(200, {"id": "chatcmpl_1", "usage": {"prompt_tokens": 10, "completion_tokens": 20,
                                                                  "total_tokens": 30},
                                   "choices": [{"message": {"content": json.dumps({"shots": shots}, ensure_ascii=False)}}]})
        if p == "/v2/ratings":
            return self._out(200, {"id": "rat_" + str(body.get("request_id") or "x")[:40], "score": body.get("score"),
                                   "tags": body.get("tags") or []})
        return self._out(404, {"error": "nope"})

def start_fake():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

def write_key(path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, GOOD.encode())
    finally:
        os.close(fd)
    return path

def start(port=0, price=None, key_file=None):
    make_media()
    FAKE["unique_jobs"] = True
    if price is not None:
        FAKE["price"] = price
    srv = ThreadingHTTPServer(("127.0.0.1", port), FakeUpstream)
    key_file = write_key(key_file or os.path.join(tempfile.mkdtemp(prefix="fake-upstream-"), "key"))
    p = srv.server_address[1]
    return srv, {"ready": True, "port": p, "base": "http://127.0.0.1:%d/v2" % p, "key_file": key_file}

def main(argv=None):
    ap = argparse.ArgumentParser(description="開發用的假上游（手動測本機伺服器用）")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--price", help="每次報價的金額（預設 3.00）")
    ap.add_argument("--key-file", help="假金鑰寫到哪裡（0600）")
    a = ap.parse_args(argv)
    srv, ready = start(a.port, a.price, a.key_file)
    print(json.dumps(ready), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()

if __name__ == "__main__":
    main()
