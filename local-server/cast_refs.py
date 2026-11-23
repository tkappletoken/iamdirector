import os
import re
import sys

import shot_controls
import studio_tools

MODES = ("legacy", "blocks", "shadow")
SHEET_ORDER = ("char", "outfit", "scene", "prop", "style")
STORE_KEY = "characters"
MAX_CARDS = 50
MAX_NAME = 40
MAX_DESC = 1000
MAX_REFS_PER_CARD = 8
MAX_NOTES = 10
MAX_NOTE = 200
MAX_VOICE = 80
REF_OK = re.compile(r"^(asset://|https?://|data:image/)", re.I)

class CastError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code

def mode():
    v = os.environ.get("STUDIO_CAST_REFS", "").strip().lower()
    return v if v in MODES else "legacy"

def _kind(c):
    return c.get("kind") if c.get("kind") in SHEET_ORDER else "char"

def clean_cards(raw):
    if not isinstance(raw, list):
        raise CastError("bad_cards")
    if len(raw) > MAX_CARDS:
        raise CastError("too_many_cards")
    out = []
    for c in raw:
        if not isinstance(c, dict) or not isinstance(c.get("name"), str) or not c["name"].strip():
            continue
        refs = []
        for r in c.get("refs") or []:
            if isinstance(r, dict) and isinstance(r.get("ref"), str) and REF_OK.match(r["ref"].strip()):
                refs.append({"ref": r["ref"].strip(), "role": str(r.get("role") or "")[:20]})
        card = {"name": c["name"].strip()[:MAX_NAME], "desc": str(c.get("desc") or "")[:MAX_DESC],
                "refs": refs[:MAX_REFS_PER_CARD]}
        for k in ("kind", "of", "range"):
            if isinstance(c.get(k), str):
                card[k] = c[k][:MAX_NAME]
        if c.get("auto") is True:
            card["auto"] = True
        if isinstance(c.get("voice"), str) and c["voice"].strip():
            card["voice"] = c["voice"].strip()[:MAX_VOICE]
        notes = [re.sub(r"\s+", " ", n).strip()[:MAX_NOTE] for n in (c.get("notes") or [])
                 if isinstance(n, str) and n.strip()] if isinstance(c.get("notes"), list) else []
        if notes:
            card["notes"] = notes[-MAX_NOTES:]
        out.append(card)
    return out

def expand(text, cards):
    out = str(text or "")
    used = []
    for c in sorted([c for c in cards if c.get("name")], key=lambda c: -len(c["name"])):
        token = "@" + c["name"]
        if token not in out:
            continue
        used.append(c)
        out = out.replace(token, (c.get("desc") or "").strip() or c["name"])
    return re.sub(r"\s{2,}", " ", out).strip(), used

def in_range(spec, n):
    t = str(spec or "").strip()
    if not t:
        return True
    for part in [p for p in re.split(r"[,，、\s]+", t) if p]:
        m = re.match(r"^(\d+)\s*[-~～–]\s*(\d+)$", part)
        if m and int(m.group(1)) <= n <= int(m.group(2)):
            return True
        if part.isdigit() and int(part) == n:
            return True
    return False

def refs_of(used):
    order = sorted(enumerate(used), key=lambda x: (SHEET_ORDER.index(_kind(x[1])), x[0]))
    out = []
    for _i, c in order:
        for r in c.get("refs") or []:
            out.append({"type": "image", "url": r["ref"], "role": "reference_image"})
    return out

def apply(body, cards, shot=None, force=()):
    n = shot if isinstance(shot, int) and not isinstance(shot, bool) and shot >= 1 else 1
    text, used = expand(body.get("prompt"), cards)
    for c in cards:
        if c["name"] in force and c not in used:
            used.append(c)
    segs = [text]
    for c in cards:
        if (c.get("kind") == "outfit" and c.get("of") and c not in used and in_range(c.get("range"), n)
                and any(_kind(u) == "char" and u["name"] == c["of"] for u in used)):
            used.append(c)
            d = (c.get("desc") or "").strip()
            if d:
                segs.append("%s wears %s." % (c["of"], re.sub(r"[.。]+$", "", d)))
    for c in used:
        if _kind(c) == "char" and c.get("notes"):
            segs.append("Performance (%s): %s." % (c["name"], "; ".join(n.rstrip(".。") for n in c["notes"])))
    for c in cards:
        if c.get("kind") == "style" and c.get("auto") and c not in used:
            used.append(c)
            d = (c.get("desc") or "").strip()
            if d:
                segs.append("Style: " + d)
    out = dict(body, prompt=re.sub(r"\s{2,}", " ", " ".join(s for s in segs if s)).strip())
    refs = refs_of(used)
    if refs and not body.get("frame_images"):
        old = [x for x in body.get("input_references") or [] if isinstance(x, dict)]
        have = {x.get("url") for x in old}
        add = []
        for r in refs:
            if r["url"] not in have:
                have.add(r["url"])
                add.append(r)
        if add:
            out["input_references"] = old + add
    return out, [c["name"] for c in used]

def _cards_for(spec, load):
    if spec is True:
        return clean_cards(_load(load)), ()
    if isinstance(spec, list) and spec and all(isinstance(x, str) for x in spec):
        names = {x.strip() for x in spec if x.strip()}
        cards = clean_cards(_load(load))
        if not names <= {c["name"] for c in cards}:
            raise CastError("unknown_name")
        return cards, tuple(names)
    if isinstance(spec, list):
        return clean_cards(spec), ()
    raise CastError("bad_cast")

def _load(load):
    try:
        got = load()
    except Exception:
        raise CastError("store_unavailable")
    return got if isinstance(got, list) else []

def prepare(body, load, mode_now=None):
    body = dict(body)
    spec = body.pop("cast", None)
    shot = body.pop("cast_shot", None)
    controls = body.pop("controls", None)
    if (spec is None or spec is False) and controls is None:
        return body, None, None
    m = mode_now or mode()
    info = {"mode": m, "applied": False}
    if m == "legacy":
        info["reason"] = "off"
        return body, None, info
    try:
        if spec is None or spec is False:
            new, used = dict(body), []
        else:
            cards, force = _cards_for(spec, load)
            new, used = apply(body, cards, shot, force)
        if controls is not None:
            try:
                new["prompt"], warn = shot_controls.apply(new.get("prompt"), controls)
            except shot_controls.ControlsError as e:
                raise CastError(e.code)
            if warn:
                info["warnings"] = warn
        if new.get("input_references") != body.get("input_references") and \
                studio_tools.reference_limits(new.get("model")).get("supported") is False:
            info["note"] = "model_may_not_take_refs"
        chk = studio_tools.check_references(new.get("model"), new.get("input_references") or [])
        if chk.get("errors"):
            raise CastError("too_many_refs")
    except CastError as e:
        sys.stderr.write("[cast_refs] fallback=%s\n" % e.code)
        info["reason"] = e.code
        return body, None, info
    except Exception as e:
        sys.stderr.write("[cast_refs] fallback=error:%s\n" % type(e).__name__)
        info["reason"] = "error"
        return body, None, info
    added = len(new.get("input_references") or []) - len(body.get("input_references") or [])
    info.update(used=used, references_added=max(0, added))
    if m == "shadow":
        info["reason"] = "shadow"
        return body, new, info
    info["applied"] = True
    return new, None, info

_SEG_END = r"(?= Performance \(| Style: | Lens: | Color: | Light: | Location: | Sound: | Single continuous shot|$)"
MIN_DESC = 8

def _perf(c):
    return "Performance (%s): %s." % (c["name"], "; ".join(n.rstrip(".。") for n in c["notes"]))

def refresh_notes(body, raw_cards):
    try:
        cards = [c for c in clean_cards(raw_cards if isinstance(raw_cards, list) else []) if _kind(c) == "char"]
    except CastError:
        return body, []
    prompt = body.get("prompt") if isinstance(body, dict) else None
    if not isinstance(prompt, str) or not prompt:
        return body, []
    out, changed = prompt, []
    for c in cards:
        pat = re.compile(r" ?Performance \(%s\): .*?%s" % (re.escape(c["name"]), _SEG_END))
        new = _perf(c) if c.get("notes") else ""
        if pat.search(out):
            got = pat.sub((" " + new) if new else "", out, count=1)
            if got != out:
                out = got
                changed.append(c["name"])
        elif new and len((c.get("desc") or "").strip()) >= MIN_DESC and c["desc"].strip() in out:
            out = out + " " + new
            changed.append(c["name"])
    out = re.sub(r"\s{2,}", " ", out).strip()
    return (dict(body, prompt=out) if changed else body), changed

def price_of(q):
    if not isinstance(q, dict):
        return None
    est = q.get("estimate")
    if isinstance(est, dict) and est.get("points") is not None:
        return str(est["points"])
    v = q.get("est_cost", q.get("price"))
    return str(v) if v is not None else None

def shadow_log(old_q, new_q, err=None):
    if err is not None:
        code = "error"
    else:
        a, b = price_of(old_q), price_of(new_q)
        code = "price_same" if a == b else "price_diff"
    sys.stderr.write("[cast_refs] shadow=%s\n" % code)
    return code
