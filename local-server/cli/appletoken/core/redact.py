
import hashlib
import urllib.parse

MASK = "***"

_secrets = []

def register_secret(value):
    if not isinstance(value, str) or len(value) < 8:
        return
    for form in (value, urllib.parse.quote(value, safe=""),
                 urllib.parse.quote_plus(value)):
        if form not in _secrets:
            _secrets.append(form)

def clear_secrets():
    _secrets.clear()

def redact(text):
    if not isinstance(text, str):
        return text
    for v in _secrets:
        if v in text:
            text = text.replace(v, MASK)
    return text

def redact_obj(obj):
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v) for v in obj]
    return obj

def fingerprint(value, n=8):
    if not isinstance(value, str) or not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:n]

def leak_probe(value, n=12):
    if not isinstance(value, str) or len(value) < n:
        return None
    return value[:n]
