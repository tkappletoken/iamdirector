import re

MOVES = {
    "static": ("static shot", "固定鏡頭"),
    "pan_left": ("pan left", "向左橫搖"), "pan_right": ("pan right", "向右橫搖"),
    "tilt_up": ("tilt up", "向上仰"), "tilt_down": ("tilt down", "向下俯"),
    "dolly_in": ("dolly in", "推近"), "dolly_out": ("dolly out", "拉遠"),
    "zoom_in": ("zoom in", "變焦推近"), "zoom_out": ("zoom out", "變焦拉遠"),
    "truck_left": ("truck left", "向左平移"), "truck_right": ("truck right", "向右平移"),
    "pedestal_up": ("pedestal up", "垂直上升"), "pedestal_down": ("pedestal down", "垂直下降"),
    "arc": ("arc shot around the subject", "弧形繞拍"),
    "tracking": ("tracking shot following the subject", "跟拍"),
    "handheld": ("handheld camera with slight natural shake", "手持"),
    "whip_pan": ("whip pan", "甩鏡"),
    "crane_up": ("crane up", "搖臂上升"), "crane_down": ("crane down", "搖臂下降"),
    "aerial": ("aerial drone shot", "空拍"),
    "tiny_planet": ("tiny planet 360-degree view", "小星球"),
    "orbit_360": ("360-degree orbit around the subject", "環繞一圈"),
    "bullet_time": ("bullet time, time frozen while the camera moves around the subject", "子彈時間"),
    "camera_roll": ("camera roll rotating around the lens axis", "鏡頭旋轉"),
    "dolly_zoom": ("dolly zoom (vertigo effect)", "滑動變焦"),
    "rack_focus": ("rack focus from foreground to background", "移焦"),
    "crash_zoom": ("crash zoom", "急推變焦"),
    "fpv_drone": ("FPV drone flying through the space", "穿越機"),
    "top_down_drop": ("top-down dive dropping toward the subject", "俯衝"),
    "bolt_cam": ("high-speed robotic arm bolt cam move", "高速機械臂"),
}
RARE = ("tiny_planet", "bullet_time", "bolt_cam")
SPEEDS = {"slow": "slow", "medium": "", "fast": "fast"}
TEXT_FIELDS = ("lens", "color", "light", "location", "sound", "style")
LABEL = {"lens": "Lens", "color": "Color", "light": "Light", "location": "Location", "sound": "Sound", "style": "Style"}
KEYS = ("camera_move", "speed", "direction", "end") + TEXT_FIELDS + ("allow_cuts",)
MAX_TEXT = 120
CONTINUOUS = "Single continuous shot from start to end."

class ControlsError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code

def _txt(v):
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(v or "")).strip()
    return re.sub(r"\s{2,}", " ", s)[:MAX_TEXT].rstrip(" .。")

def check(controls):
    if not isinstance(controls, dict):
        raise ControlsError("bad_controls")
    if set(controls) - set(KEYS):
        raise ControlsError("unknown_control")
    out = {}
    mv = controls.get("camera_move")
    if mv not in (None, ""):
        if not isinstance(mv, str) or mv not in MOVES:
            raise ControlsError("unknown_move")
        out["camera_move"] = mv
    sp = controls.get("speed")
    if sp not in (None, ""):
        if not isinstance(sp, str) or sp not in SPEEDS:
            raise ControlsError("bad_speed")
        out["speed"] = sp
    for k in ("direction", "end") + TEXT_FIELDS:
        t = _txt(controls.get(k))
        if t:
            out[k] = t
    if controls.get("allow_cuts") is True:
        out["allow_cuts"] = True
    return out

def camera_line(c):
    mv = c.get("camera_move")
    if not mv:
        return ""
    head = MOVES[mv][0]
    if mv != "static":
        sp = SPEEDS.get(c.get("speed") or "", "")
        head = (sp + " " if sp else "") + head
        if c.get("direction"):
            head += " " + c["direction"]
    line = "Camera: " + head
    if mv != "static" and c.get("end"):
        line += ", ending on " + c["end"] + " and then holding still"
    return line + "."

def apply(prompt, controls):
    c = check(controls)
    segs = [camera_line(c), str(prompt or "").strip()]
    for k in TEXT_FIELDS:
        if c.get(k):
            segs.append("%s: %s." % (LABEL[k], c[k]))
    if c.get("camera_move") and not c.get("allow_cuts"):
        segs.append(CONTINUOUS)
    warn = []
    if c.get("camera_move") in RARE:
        warn.append("rare_move")
    return re.sub(r"\s{2,}", " ", " ".join(s for s in segs if s)).strip(), warn

def catalog():
    return [{"id": k, "en": v[0], "zh": v[1], "rare": k in RARE} for k, v in MOVES.items()]
