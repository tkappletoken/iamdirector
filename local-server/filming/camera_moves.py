
PREVIS = {
    "static": "static",
    "pan_left": "pan_l", "pan_right": "pan_r",
    "tilt_up": "tilt_up", "tilt_down": "tilt_down",
    "dolly_in": "dolly_in", "dolly_out": "dolly_out",
    "zoom_in": "zoom_in", "zoom_out": "zoom_out",
    "truck_left": "truck_l", "truck_right": "truck_r",
    "pedestal_up": "crane_up", "pedestal_down": "crane_down",
    "arc": "arc",
    "tracking": "track",
    "handheld": "handheld",
    "whip_pan": "whip",
    "crane_up": "crane_up", "crane_down": "crane_down",
    "aerial": "drone_rise",
    "tiny_planet": None,
    "orbit_360": "orbit_360",
    "bullet_time": "orbit_360",
    "camera_roll": "roll",
    "dolly_zoom": "dolly_zoom",
    "rack_focus": "rack",
    "crash_zoom": "zoom_in",
    "fpv_drone": None,
    "top_down_drop": "crane_down",
    "bolt_cam": None,
}
EDITOR_ONLY = ("orbit_l", "orbit_r")
SPEED = {"slow": "slow", "medium": "steady", "fast": "fast", None: "steady", "": "steady"}
SIZES = ("ews", "ws", "ms", "mcu", "cu", "ecu")
ANGLES = ("eye", "high", "low", "top", "dutch")

class MoveError(ValueError):
    pass

def previs_cam(move, speed=None, size="ms", angle="eye"):
    if move not in PREVIS:
        raise MoveError("不認得的運鏡：%r（用 shot_controls 的 id）" % move)
    if speed not in SPEED:
        raise MoveError("speed 只能是 slow／medium／fast")
    if size not in SIZES or angle not in ANGLES:
        raise MoveError("size 只能是 %s；angle 只能是 %s" % ("／".join(SIZES), "／".join(ANGLES)))
    pid = PREVIS[move]
    return None if pid is None else {"move": pid, "speed": SPEED[speed], "size": size, "angle": angle}
