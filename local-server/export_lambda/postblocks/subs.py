
SUB_STYLE = {"font_scale": 0.055, "margin_v": 0.06}

def esc(path):
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

def ts(t, sep):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    if sep == ",":
        return "%02d:%02d:%02d,%03d" % (h, m, s, ms)
    return "%d:%02d:%02d.%02d" % (h, m, s, ms // 10)

def ass_text(t):
    return t.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", "\\N")

def srt(cues, extra=None):
    rows = list(cues) + ([extra] if extra else [])
    out = []
    for k, q in enumerate(rows, 1):
        out.append("%d\n%s --> %s\n%s\n" % (k, ts(q["start"], ","), ts(q["end"], ","), q["text"].replace("\n", " ")))
    return "\n".join(out)

def ass(cues, card, W, H, card_at=0.0, card_dur=0.0, burn_cues=True, titles=None, style=None, font=None):
    if font is None:
        import render
        font = render.FONT
    st = dict(SUB_STYLE, **(style or {}))
    size = max(18, int(H * st["font_scale"]))
    csize = max(16, int(H * 0.045))
    osize, esize = max(18, int(min(W, H) * 0.062)), max(16, int(min(W, H) * 0.052))
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Sub,%s,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,%d,0,2,%d,%d,%d,1\n"
            "Style: Card,%s,%d,&H00E6E6E6,&H00E6E6E6,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,0,0,5,%d,%d,0,1\n"
            "Style: Open,%s,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,1,0,0,0,100,100,1,0,1,%d,0,8,%d,%d,%d,1\n"
            "Style: End,%s,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,1,0,0,0,100,100,0,0,1,%d,0,2,%d,%d,%d,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            % (W, H, font, size, max(1, size // 14), int(W * 0.06), int(W * 0.06), int(H * st["margin_v"]),
               font, csize, int(W * 0.12), int(W * 0.12),
               font, osize, max(2, osize // 10), int(W * 0.06), int(W * 0.06), int(H * 0.08),
               font, esize, max(2, esize // 12), int(W * 0.06), int(W * 0.06), int(H * 0.2)))
    rows = []
    if burn_cues:
        for q in cues:
            rows.append("Dialogue: 0,%s,%s,Sub,,0,0,0,,%s" % (ts(q["start"], "."), ts(q["end"], "."), ass_text(q["text"])))
    for q in titles or []:
        rows.append("Dialogue: 2,%s,%s,%s,,0,0,0,,%s" % (ts(q["start"], "."), ts(q["end"], "."),
                                                        "Open" if q["where"] == "open" else "End", ass_text(q["text"])))
    if card:
        rows.append("Dialogue: 1,%s,%s,Card,,0,0,0,,%s" % (
            ts(card_at, "."), ts(card_at + card_dur, "."), "\\N\\N".join(ass_text(x) for x in card)))
    return head + "\n".join(rows) + ("\n" if rows else "")
