
import re

_SLOT = re.compile(r"^\s*[A-Z][A-Z0-9-]*\s*$")
_OPEN = re.compile(r"<!--|<script\b|<style\b", re.I)
_NON_JS = re.compile(r"""\btype\s*=\s*["']?(?!["']?(?:text/javascript|module|application/javascript))""", re.I)

_RE_AFTER_WORD = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete",
                  "void", "throw", "instanceof", "yield", "await"}
_RE_AFTER_CHAR = set("(,=:[!&|?{};+-*%<>~^")

def _whole_line(src, start, end):
    ls = src.rfind("\n", 0, start) + 1
    le = src.find("\n", end)
    le = len(src) if le < 0 else le
    if src[ls:start].strip() == "" and src[end:le].strip() == "":
        return ls, min(le + 1, len(src)), ""
    return None

def _cut(src, ranges):
    out, pos = [], 0
    for s, e, rep in ranges:
        if s < pos:
            continue
        out.append(src[pos:s])
        out.append(rep)
        pos = e
    out.append(src[pos:])
    return "".join(out)

def _comment_range(src, s, e, block):
    whole = _whole_line(src, s, e)
    if whole:
        return whole
    if block:
        rep = "\n" if "\n" in src[s:e] else " "
        return s, e, rep
    while s > 0 and src[s - 1] in " \t":
        s -= 1
    return s, e, ""

def strip_css(src):
    ranges, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in "\"'":
            i = _skip_string(src, i)
            continue
        if src.startswith("/*", i):
            e = src.find("*/", i + 2)
            e = n if e < 0 else e + 2
            ranges.append(_comment_range(src, i, e, True))
            i = e
            continue
        i += 1
    return _cut(src, ranges)

def _skip_string(src, i):
    q, n = src[i], len(src)
    i += 1
    while i < n:
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == q or c == "\n":
            return i + 1
        i += 1
    return n

def _skip_regex(src, i):
    n, cls = len(src), False
    i += 1
    while i < n:
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "\n":
            return i
        if cls:
            if c == "]":
                cls = False
        elif c == "[":
            cls = True
        elif c == "/":
            i += 1
            while i < n and (src[i].isalnum() or src[i] in "_$"):
                i += 1
            return i
        i += 1
    return n

def _prev_allows_regex(src, i):
    j = i - 1
    while j >= 0 and src[j] in " \t\r\n":
        j -= 1
    if j < 0:
        return True
    c = src[j]
    if c in _RE_AFTER_CHAR or c == "}":
        return True
    if c.isalnum() or c in "_$":
        k = j
        while k >= 0 and (src[k].isalnum() or src[k] in "_$"):
            k -= 1
        return src[k + 1:j + 1] in _RE_AFTER_WORD
    return False

def strip_js(src):
    ranges = []
    _scan_js(src, 0, ranges, None)
    ranges.sort()
    return _cut(src, ranges)

def _scan_js(src, i, ranges, close_depth):
    n, depth = len(src), 0
    while i < n:
        c = src[i]
        if c in "\"'":
            i = _skip_string(src, i)
            continue
        if c == "`":
            i = _skip_template(src, i, ranges)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            if close_depth is not None and depth == 0:
                return i + 1
            depth -= 1
        elif c == "/":
            nx = src[i + 1] if i + 1 < n else ""
            if nx == "/":
                e = src.find("\n", i)
                e = n if e < 0 else e
                ranges.append(_comment_range(src, i, e, False))
                i = e
                continue
            if nx == "*":
                e = src.find("*/", i + 2)
                e = n if e < 0 else e + 2
                ranges.append(_comment_range(src, i, e, True))
                i = e
                continue
            if _prev_allows_regex(src, i):
                i = _skip_regex(src, i)
                continue
        i += 1
    return n

def _skip_template(src, i, ranges):
    n = len(src)
    i += 1
    while i < n:
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "`":
            return i + 1
        if c == "$" and src.startswith("${", i):
            i = _scan_js(src, i + 2, ranges, 0)
            continue
        i += 1
    return n

def strip_html(src):
    out, pos, n = [], 0, len(src)
    while True:
        m = _OPEN.search(src, pos)
        if not m:
            out.append(src[pos:])
            break
        s = m.start()
        tok = m.group(0).lower()
        if tok == "<!--":
            e = src.find("-->", s + 4)
            e = n if e < 0 else e + 3
            body = src[s + 4:e - 3]
            if _SLOT.match(body) or body.startswith("["):
                out.append(src[pos:e])
            else:
                whole = _whole_line(src, s, e)
                if whole:
                    ws, we, _ = whole
                    out.append(src[pos:ws])
                    e = we
                else:
                    out.append(src[pos:s])
            pos = e
            continue
        tag_end = src.find(">", s)
        if tag_end < 0:
            out.append(src[pos:])
            break
        name = "script" if tok.startswith("<script") else "style"
        close = _find_close(src, name, tag_end)
        inner = src[tag_end + 1:close]
        attrs = src[s:tag_end]
        if name == "style":
            inner = strip_css(inner)
        elif not _NON_JS.search(attrs):
            inner = strip_js(inner)
        out.append(src[pos:tag_end + 1])
        out.append(inner)
        pos = close
    return "".join(out)

def _find_close(src, name, start):
    m = re.compile(r"</%s\s*>" % name, re.I).search(src, start)
    return m.start() if m else len(src)
