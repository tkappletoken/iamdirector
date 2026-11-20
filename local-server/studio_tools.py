import http.client
import ipaddress
import re
import shutil
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

class ApiError(Exception):
    def __init__(self, code, body):
        super().__init__(body)
        self.code = code
        self.body = body

DURATION_RULES = [
    ("SIRAYA-Seedance-2.5", {"min": 4, "max": 30}),
    ("NSFW-Seedance-2.5",   {"min": 4, "max": 30}),
    ("SIRAYA-Seedance-2",   {"min": 4, "max": 15}),
    ("NSFW-Seedance-2",     {"min": 4, "max": 15}),
    ("ByteDance-Seedance",  {"min": 4, "max": 15}),
    ("NSFW-Seedance-1",     {"min": 4, "max": 15}),
    ("veo",                 {"allowed": [4, 6, 8]}),
    ("sora",                {"allowed": [4, 8, 12]}),
    ("happyhorse",          {"min": 3, "max": 10}),
]

SHOT_HEAD = re.compile(
    r"^[\s*#>\-]*"
    r"(?:shot|scene|cut|鏡頭|镜头|場景|场景|分鏡|分镜)"
    r"\s*#?\s*(\d+)"
    r"\s*(?:[｜|:：\-–—、.]\s*(.*?))?"
    r"[\s*#]*$",
    re.IGNORECASE)

TIME_RANGE = re.compile(
    r"(?:(\d{1,2}):)?(\d{1,3}(?:\.\d+)?)\s*(?:s|秒)?"
    r"\s*[-–—~〜到至]\s*"
    r"(?:(\d{1,2}):)?(\d{1,3}(?:\.\d+)?)\s*(?:s|秒)?",
    re.IGNORECASE)

OK_IMAGE = {"image/jpeg", "image/png"}

RISKY_IMAGE = {"image/webp", "image/gif", "image/avif", "image/svg+xml", "image/heic", "image/heif"}

OK_VIDEO = {"video/mp4", "video/quicktime", "video/webm"}

OK_AUDIO = {"audio/mpeg", "audio/wav", "audio/mp4", "audio/x-wav", "audio/aac"}

def duration_rule(model):
    name = (model or "").rsplit("/", 1)[-1].lower()
    for prefix, rule in sorted(DURATION_RULES, key=lambda x: -len(x[0])):
        if name.startswith(prefix.lower()):
            return rule
    return {"min": 4, "max": 15}

def align_seconds(model, wanted):
    rule = duration_rule(model)
    if wanted is None:
        return None, None
    if "allowed" in rule:
        best = min(rule["allowed"], key=lambda v: (abs(v - wanted), v))
        note = None if best == wanted else "%s 只接受 %s 秒，%g → %d" % (
            model or "此模型", "/".join(map(str, rule["allowed"])), wanted, best)
        return best, note
    lo, hi = rule["min"], rule["max"]
    best = max(lo, min(hi, int(round(wanted))))
    note = None
    if best != wanted:
        if wanted < lo:
            note = "最短 %d 秒，%g → %d" % (lo, wanted, best)
        elif wanted > hi:
            note = "最長 %d 秒，%g → %d" % (hi, wanted, best)
        else:
            note = "秒數需為整數，%g → %d" % (wanted, best)
    return best, note

def parse_time_range(text):
    if not text:
        return None, None, None
    m = TIME_RANGE.search(text)
    if not m:
        return None, None, None
    h1, s1, h2, s2 = m.groups()
    start = float(s1) + (int(h1) * 60 if h1 else 0)
    end = float(s2) + (int(h2) * 60 if h2 else 0)
    if end <= start:
        return start, end, None
    return start, end, round(end - start, 3)

def parse_shots(text, model=None):
    lines = (text or "").splitlines()
    shots, cur = [], None
    for line in lines:
        m = SHOT_HEAD.match(line.strip())
        if m:
            if cur:
                shots.append(cur)
            num, rest = m.group(1), (m.group(2) or "").strip()
            start, end, dur = parse_time_range(rest)
            inline = TIME_RANGE.sub("", rest, count=1) if dur else rest
            inline = inline.strip(" 　｜|:：、.-–—*#") or None
            label = re.sub(r"[｜|]", " ", rest).strip(" *#-–—") or None
            cur = {"index": int(num), "label": label, "start": start, "end": end,
                   "duration": dur, "inline": inline, "lines": []}
        elif cur is not None:
            cur["lines"].append(line)
        elif line.strip():
            cur = {"index": 1, "label": None, "start": None, "end": None,
                   "duration": None, "lines": [line]}
    if cur:
        shots.append(cur)

    out = []
    for i, sh in enumerate(shots, 1):
        body = "\n".join(sh.pop("lines")).strip()
        body = re.sub(r"\n{3,}", "\n\n", body)
        inline = sh.pop("inline", None)
        if not body and inline:
            body = inline
            sh["label"] = None
        if not body:
            continue
        if sh["duration"] is None:
            first = body.splitlines()[0]
            st, en, du = parse_time_range(first)
            if du:
                sh.update(start=st, end=en, duration=du)
                rest = "\n".join(body.splitlines()[1:]).strip()
                if rest:
                    body = rest
        secs, note = align_seconds(model, sh["duration"])
        sh.update(id="shot%02d" % i, prompt=body, seconds=secs, adjust_note=note)
        out.append(sh)
    return out

def ffmpeg_path():
    return shutil.which("ffmpeg")

def reference_limits(model):
    m = (model or "").lower()
    if "seedance-2.5" in m:
        return {"total": 50, "image": 30, "video": 10, "audio": 10, "audio_only": True,
                "source": "SIRAYA-Seedance-2.5"}
    if "seedance-2" in m:
        return {"total": 15, "image": 9, "video": 3, "audio": 3, "audio_only": False,
                "source": "Seedance 2.0 家族"}
    if "veo" in m:
        return {"total": None, "supported": True, "source": "Veo（文件未列上限）"}
    return {"total": None, "supported": False,
            "source": "此模型不支援 input_references（僅 Seedance 2.0/2.5 與 Veo）"}

def story_to_script(story):
    parts = [x.strip() for x in re.split(r"(?<=[。！？!?；;])|(?<=\.)\s+|\n+", str(story or "").replace("\r", "")) if x and x.strip()]
    per = max(1, -(-len(parts) // 6))
    out = []
    for i in range(0, len(parts), per):
        acc = ""
        for b in parts[i:i + per]:
            acc += (" " if acc and re.search(r"[\x21-\x7E]$", acc) and re.match(r"[\x21-\x7E]", b) else "") + b
        out.append(acc)
    return "\n\n".join("鏡頭 %d\n%s" % (i + 1, t) for i, t in enumerate(out))

def check_references(model, refs):
    lim = reference_limits(model)
    counts = {"image": 0, "video": 0, "audio": 0}
    for r in refs or []:
        t = (r.get("type") or "image") if isinstance(r, dict) else "image"
        if t in counts:
            counts[t] += 1
    total = sum(counts.values())
    out = {"counts": counts, "total": total, "limits": lim, "errors": [], "warnings": []}
    if not refs:
        return out
    if lim.get("supported") is False:
        out["warnings"].append(lim["source"])
        return out
    if lim.get("total") and total > lim["total"]:
        out["errors"].append("最多 %d 筆參考，目前 %d 筆" % (lim["total"], total))
    for kind in ("image", "video", "audio"):
        cap = lim.get(kind)
        if cap is not None and counts[kind] > cap:
            out["errors"].append("%s 最多 %d 筆，目前 %d 筆" % (kind, cap, counts[kind]))
    if lim.get("audio_only") is False and counts["audio"] and not (counts["image"] or counts["video"]):
        out["errors"].append("%s 不支援純音訊參考，至少要有一張圖或一段影片" % lim["source"])
    return out

def _judge(ct, kind, size, source):
    out = {"content_type": ct, "bytes": size or None, "source": source}
    if ct in ("text/html", "application/xhtml+xml"):
        out.update(ok=False, reason="這是網頁不是檔案",
                   hint="在圖片上按右鍵→「複製圖片網址」，取得直接指向 .jpg/.png 的連結")
        return out
    ok_set = {"image": OK_IMAGE, "video": OK_VIDEO, "audio": OK_AUDIO}.get(kind, OK_IMAGE)
    if ct in ok_set:
        out.update(ok=True)
        return out
    if kind == "image" and ct in RISKY_IMAGE:
        out.update(ok=False, reason="格式是 %s，影片模型通常只吃 JPEG / PNG" % ct,
                   hint="轉存成 .jpg 或 .png 再試")
        return out
    if not ct.startswith(kind + "/"):
        out.update(ok=False, reason="型別是 %s，不是 %s" % (ct or "(未知)", kind),
                   hint="確認這個網址直接指向檔案本身")
        return out
    out.update(ok=True, note="型別 %s 不在已知清單內，可能可用也可能被上游拒絕" % ct)
    return out

class BlockedTarget(OSError):
    pass

def _public_ip(ip):
    try:
        a = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return a.is_global and not a.is_multicast

def _check_peer(sock):
    ip = sock.getpeername()[0]
    if not _public_ip(ip):
        try:
            sock.close()
        except OSError:
            pass
        raise BlockedTarget("對方位址 %s 不是公開網路" % ip)

class _PublicHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        super().connect()
        _check_peer(self.sock)

class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        super().connect()
        _check_peer(self.sock)

class _PublicHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PublicHTTPConnection, req)

class _PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PublicHTTPSConnection, req, context=self._context)

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

_PUBLIC_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), _PublicHTTPHandler, _PublicHTTPSHandler, _NoRedirect)

def _precheck_target(url):
    try:
        u = urllib.parse.urlsplit(url)
        port = u.port
    except ValueError:
        return "網址格式不對"
    if port not in (None, 80, 443):
        return "只接受 80／443 埠的網址"
    host = u.hostname or ""
    if not host:
        return "網址缺少主機名"
    try:
        infos = socket.getaddrinfo(host, port or (443 if u.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return "找不到這個網址的主機"
    if not infos or not all(_public_ip(i[4][0]) for i in infos):
        return "這個網址指向內部網路，不能預檢"
    return None

def _fetch_failed(e, what):
    sys.stderr.write("check_asset：%s（%s: %s）\n" % (what, type(e).__name__, e))
    if isinstance(e, BlockedTarget) or isinstance(getattr(e, "reason", None), BlockedTarget):
        return {"ok": False, "reason": "這個網址指向內部網路，不能預檢"}
    return {"ok": False, "reason": "%s，請確認網址是公開可下載的檔案" % what}

def check_asset(url, kind="image"):
    url = (url or "").strip()
    if not url:
        return {"ok": False, "reason": "沒有填 URL"}
    if url.startswith("asset://"):
        return {"ok": True, "note": "asset:// 由上游解析，這裡無法預檢"}
    if url.startswith("local://"):
        return {"ok": False, "reason": "local:// 是工作台(serve2.py)的本機素材，這個介面不支援"}
    if url.startswith("data:"):
        m = re.match(r"^data:([\w/+.-]+)(;base64)?,", url)
        ct = (m.group(1) if m else "").lower()
        if not ct:
            return {"ok": False, "reason": "data URI 缺少 MIME 型別"}
        return _judge(ct, kind, len(url), source="data URI")
    if not url.lower().startswith(("http://", "https://")):
        return {"ok": False, "reason": "只接受 http(s) 網址、data: 或 asset://"}

    blocked = _precheck_target(url)
    if blocked:
        return {"ok": False, "reason": blocked}

    req = urllib.request.Request(url, method="HEAD")
    req.add_header("User-Agent", "Mozilla/5.0")
    try:
        with _PUBLIC_OPENER.open(req, timeout=15) as r:
            ct = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            size = int(r.headers.get("Content-Length") or 0)
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            return {"ok": False, "reason": "這個網址會轉址，請貼轉址後的檔案網址"}
        if e.code not in (400, 403, 405, 501, 502):
            return {"ok": False, "reason": "抓不到這個網址（HTTP %s）" % e.code}
        ct, size = "", 0
    except Exception as e:
        return _fetch_failed(e, "連不上這個網址")

    if not ct:
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0")
            req.add_header("Range", "bytes=0-1023")
            with _PUBLIC_OPENER.open(req, timeout=15) as r:
                ct = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                size = int(r.headers.get("Content-Range", "/0").split("/")[-1] or 0)
        except urllib.error.HTTPError as e:
            if 300 <= e.code < 400:
                return {"ok": False, "reason": "這個網址會轉址，請貼轉址後的檔案網址"}
            return {"ok": False, "reason": "抓不到這個網址（HTTP %s）" % e.code}
        except Exception as e:
            return _fetch_failed(e, "抓不到這個網址")
    return _judge(ct, kind, size, source="伺服器回報")

def _stamp(t, comma=True):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d%s%03d" % (h, m, sec, "," if comma else ".", ms)

def build_captions(payload):
    cues = payload.get("cues") or []
    if not isinstance(cues, list) or not cues:
        raise ApiError(400, "缺少 cues")
    fmt = (payload.get("format") or "srt").lower()
    if fmt not in ("srt", "vtt"):
        raise ApiError(400, "format 只支援 srt 或 vtt")

    timed, t = [], 0.0
    for c in cues:
        c = c or {}
        text = str(c.get("text") or "").strip()
        if c.get("start") is not None and c.get("end") is not None:
            a, b = float(c["start"]), float(c["end"])
            if b <= a:
                raise ApiError(400, "字幕的結束時間要大於開始時間：%.3f → %.3f" % (a, b))
            t = max(t, b)
        else:
            a = t
            b = t = t + (float(c.get("seconds") or 0) or 5.0)
        if text:
            timed.append((a, b, text))

    if not timed:
        raise ApiError(400, "cues 裡沒有任何文字")
    timed.sort(key=lambda x: (x[0], x[1]))

    lines = []
    for i, (a, b, text) in enumerate(timed, 1):
        sa, sb = _stamp(a, fmt == "srt"), _stamp(b, fmt == "srt")
        if fmt == "srt":
            lines.append("%d\n%s --> %s\n%s\n" % (i, sa, sb, text))
        else:
            lines.append("%s --> %s\n%s\n" % (sa, sb, text))
    body = ("WEBVTT\n\n" if fmt == "vtt" else "") + "\n".join(lines)
    return {"format": fmt, "cues": len(timed),
            "total_seconds": round(max(t, timed[-1][1]), 3), "body": body}

def group_models(catalog):
    models = (catalog or {}).get("models") or []
    groups = {"video": [], "image": [], "text": [], "audio": [], "other": []}
    meta = {}
    for m in models:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or "").strip()
        if not mid:
            continue
        kind = m.get("modality") if m.get("modality") in groups else "other"
        groups[kind].append(mid)
        meta[mid] = {"label": m.get("label"), "desc": m.get("desc"),
                     "family": m.get("family"), "provider": m.get("provider"),
                     "constraints": m.get("constraints") or {},
                     "unit": m.get("unit"), "unit_label": m.get("unit_label"),
                     "from": m.get("from"), "to": m.get("to"), "multi_unit": m.get("multi_unit"),
                     "tiers": m.get("tiers"), "pricing_pending": bool(m.get("pricing_pending"))}
    return {**groups, "total": len(meta), "model_meta": meta}

UNIT_BASIS = {"video_seconds": "每秒", "input_tokens": "每百萬 token",
              "output_tokens": "每百萬 token", "request": "每次"}

def catalog_from_public(models):
    rows = []
    data = models.get("data") if isinstance(models, dict) else None
    for m in data if isinstance(data, list) else []:
        if isinstance(m, dict) and (m.get("ref") or m.get("id")):
            rows.append(m)
    def fam(m):
        cons = m.get("constraints") if isinstance(m.get("constraints"), dict) else {}
        return m.get("family") or cons.get("family")
    def prov(m):
        p = m.get("provider")
        return (p.get("label") or p.get("id")) if isinstance(p, dict) else None
    makers = {}
    for m in rows:
        makers.setdefault(fam(m), set()).add(prov(m))
    out = []
    for m in rows:
        pr = m.get("pricing") if isinstance(m.get("pricing"), dict) else {}
        cons = m.get("constraints") if isinstance(m.get("constraints"), dict) else {}
        unit = pr.get("unit")
        label = UNIT_BASIS.get(unit)
        if unit == "request" and m.get("modality") == "image":
            label = "每張"
        name, who = m.get("label"), prov(m)
        if who and fam(m) and len(makers.get(fam(m)) or ()) > 1:
            name = "%s · %s" % (name or m.get("ref") or m.get("id"), who)
        out.append({
            "id": m.get("ref") or m["id"], "label": name, "desc": m.get("description"),
            "modality": m.get("modality"), "family": fam(m), "provider": who,
            "constraints": cons, "unit": unit, "unit_label": label,
            "from": pr.get("from"), "to": pr.get("to"),
            "multi_unit": bool(pr.get("components")),
            "pricing_pending": pr.get("from") is None,
        })
    return {"models": out}
