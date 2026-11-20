import json
import math
import os
import shutil
import subprocess

from . import blockout, camera_path, shots

FPS = 24
APP = "/Applications/Blender.app/Contents/MacOS/Blender"
FIG = {"lower": (0.22, 0.48, 0.13), "upper": (0.27, 0.36, 0.15), "head": (0.14, 0.14, 0.14)}
GAP = 0.01

class BlenderError(RuntimeError):
    pass

def find(env=None):
    env = os.environ if env is None else env
    for p in (env.get("BLENDER"), shutil.which("blender"), APP):
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None

def figure_parts(height):
    H = max(0.3, float(height or 1.72))
    g = GAP * H
    lo, up, hd = [tuple(v * H for v in FIG[k]) for k in ("lower", "upper", "head")]
    y_lo = lo[1] / 2
    y_up = lo[1] + g + up[1] / 2
    y_hd = lo[1] + g + up[1] + g + hd[1] / 2
    return [("lower", lo, y_lo), ("upper", up, y_up), ("head", hd, y_hd)]

def to_b(p):
    return [p[0], -p[2], p[1]]

def _rot_b(r):
    return [math.radians(r[0]), math.radians(-r[2]), math.radians(r[1])]

def _parts(o):
    w, h, d = o["size"]
    k = o["kind"]
    if k == "char":
        return [{"shape": "box", "size": [pw, pd, ph], "z": y} for _n, (pw, ph, pd), y in figure_parts(h)]
    if k == "floor":
        return [{"shape": "box", "size": [w, d, h], "z": -h / 2}]
    if k == "cyl":
        return [{"shape": "cyl", "size": [w, w, h], "z": h / 2}]
    if k == "ramp":
        vs = []
        for ze in (-w / 2, w / 2):
            for (sx, sy) in ((-d / 2, 0), (d / 2, 0), (d / 2, h)):
                vs.append(to_b([-ze, sy, sx]))
        return [{"shape": "ramp", "verts": vs, "faces": [[0, 1, 2], [3, 5, 4], [0, 3, 4, 1], [1, 4, 5, 2], [0, 2, 5, 3]]}]
    return [{"shape": "box", "size": [w, d, h], "z": h / 2}]

def prepare(scene):
    if "plan" in scene.get("cam", {}) and not scene["cam"].get("keys"):
        scene = camera_path.apply(scene)[0]
    size = blockout.export_size(scene.get("aspect"))
    frames = max(1, camera_path._jround(float(scene["dur"]) * FPS))
    ts = [i / FPS for i in range(frames)]
    objs = []
    for o in scene["objs"]:
        moving = bool(o.get("keys"))
        track = []
        for t in (ts if moving else ts[:1]):
            s = shots.sample(o, t)
            track.append({"loc": to_b(s["p"]), "rot": _rot_b(s["r"]), "scale": [s["s"][0], s["s"][2], s["s"][1]]})
        objs.append({"id": o["id"], "kind": o["kind"], "color": o.get("color") or "#a7acb3", "parts": _parts(o), "track": track})
    cam = []
    for t in ts:
        c = camera_path.sample_cam(scene["cam"], t)
        cam.append({"loc": to_b(c["p"]), "look": to_b(c["look"]), "mm": c["mm"], "roll": c["roll"]})
    far = 1.0
    for o in objs:
        for tr in o["track"][:1]:
            for c in (cam[0], cam[-1]):
                far = max(far, math.dist(tr["loc"], c["loc"]))
    return {"w": size["w"], "h": size["h"], "fps": FPS, "frames": frames, "objs": objs, "cam": cam,
            "depth": {"near": 0.1, "far": round(far * 1.5, 3)}}

BPY = r'''
import bpy, json, math, os, sys
from mathutils import Quaternion, Vector

D = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
OUT = sys.argv[sys.argv.index("--") + 2]
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = D["w"], D["h"], 100
sc.render.fps, sc.frame_start, sc.frame_end = D["fps"], 1, D["frames"]
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGB"
sc.view_settings.view_transform = "Standard"

def lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def material(hexv):
    m = bpy.data.materials.new("m" + hexv)
    rgb = [lin(int(hexv[i:i + 2], 16) / 255) for i in (1, 3, 5)]
    m.diffuse_color = rgb + [1.0]
    return m

def keyframe(ob, tr, f):
    ob.location = tr["loc"]
    ob.rotation_euler = tr["rot"]
    ob.scale = tr["scale"]
    for p in ("location", "rotation_euler", "scale"):
        ob.keyframe_insert(p, frame=f)

for o in D["objs"]:
    root = bpy.data.objects.new(o["id"], None)
    sc.collection.objects.link(root)
    root.rotation_mode = "YZX"
    mat = material(o["color"])
    for part in o["parts"]:
        if part["shape"] == "ramp":
            me = bpy.data.meshes.new(o["id"] + "_m")
            me.from_pydata(part["verts"], [], part["faces"])
            ob = bpy.data.objects.new(o["id"] + "_p", me)
        else:
            if part["shape"] == "cyl":
                bpy.ops.mesh.primitive_cylinder_add(radius=0.5, depth=1, vertices=32)
            else:
                bpy.ops.mesh.primitive_cube_add(size=1)
            ob = bpy.context.active_object
            for c in list(ob.users_collection):
                c.objects.unlink(ob)
            ob.scale = part["size"]
            ob.location = (0, 0, part["z"])
        sc.collection.objects.link(ob)
        ob.data.materials.append(mat)
        ob.parent = root
    for i, tr in enumerate(o["track"]):
        keyframe(root, tr, i + 1)

cd = bpy.data.cameras.new("shot")
cd.sensor_fit, cd.sensor_height, cd.clip_start, cd.clip_end = "VERTICAL", 24, 0.05, 400
cam = bpy.data.objects.new("shot", cd)
sc.collection.objects.link(cam)
sc.camera = cam
cam.rotation_mode = "QUATERNION"
for i, c in enumerate(D["cam"]):
    f = i + 1
    loc = Vector(c["loc"])
    q = (Vector(c["look"]) - loc).to_track_quat("-Z", "Y")
    if c["roll"]:
        q = q @ Quaternion((0, 0, 1), math.radians(c["roll"]))
    cam.location, cam.rotation_quaternion, cd.lens = loc, q, c["mm"]
    cam.keyframe_insert("location", frame=f)
    cam.keyframe_insert("rotation_quaternion", frame=f)
    cd.keyframe_insert("lens", frame=f)

# 灰模畫面：Workbench（不要光影、只要形狀與分色）
sc.render.engine = "BLENDER_WORKBENCH"
sh = sc.display.shading
sh.light, sh.color_type = "STUDIO", "MATERIAL"
world = bpy.data.worlds.new("w")
sc.world = world
world.color = (0.08, 0.09, 0.1)
sc.render.filepath = os.path.join(OUT, "frames", "f_####")
bpy.ops.render.render(animation=True)

# 深度圖：Eevee＋材質覆寫（顏色＝攝影機距離，近白遠黑），不用合成器
for eng in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
    try:
        sc.render.engine = eng
        break
    except TypeError:
        continue
dm = bpy.data.materials.new("depth")
dm.use_nodes = True
nt = dm.node_tree
for n in list(nt.nodes):
    nt.nodes.remove(n)
cdn = nt.nodes.new("ShaderNodeCameraData")
mr = nt.nodes.new("ShaderNodeMapRange")
mr.inputs["From Min"].default_value = D["depth"]["near"]
mr.inputs["From Max"].default_value = D["depth"]["far"]
mr.inputs["To Min"].default_value = 1.0
mr.inputs["To Max"].default_value = 0.0
em = nt.nodes.new("ShaderNodeEmission")
outn = nt.nodes.new("ShaderNodeOutputMaterial")
nt.links.new(cdn.outputs["View Distance"], mr.inputs["Value"])
nt.links.new(mr.outputs["Result"], em.inputs["Color"])
nt.links.new(em.outputs["Emission"], outn.inputs["Surface"])
bpy.context.view_layer.material_override = dm
world.color = (0, 0, 0)
sc.frame_set(1)
sc.render.filepath = os.path.join(OUT, "depth.png")
bpy.ops.render.render(write_still=True)
with open(os.path.join(OUT, "done.json"), "w") as fh:
    json.dump({"blender": bpy.app.version_string, "engine_depth": sc.render.engine}, fh)
'''

def argv(blender, script_path, data_path, outdir):
    return [blender, "-b", "--factory-startup", "--python-exit-code", "1", "--python", script_path, "--", data_path, outdir]

def h264_encoder(ffmpeg):
    enc = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=60,
                         stdin=subprocess.DEVNULL).stdout
    return "libx264" if " libx264 " in enc else "h264_videotoolbox" if "h264_videotoolbox" in enc else None

def render(scene, outdir, blender=None, ffmpeg="ffmpeg", timeout=900, on_start=None):
    blender = blender or find()
    if not blender:
        raise BlenderError("找不到 Blender")
    data = prepare(scene)
    os.makedirs(outdir, exist_ok=True)
    sp, dp, lp = (os.path.join(outdir, n) for n in ("blockout_bpy.py", "scene.json", "blender.log"))
    with open(sp, "w", encoding="utf-8") as fh:
        fh.write(BPY)
    with open(dp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    with open(lp, "w", encoding="utf-8") as log:
        p = subprocess.Popen(argv(blender, sp, dp, outdir), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        if on_start:
            on_start(p.pid)
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
            raise BlenderError("Blender 超過 %d 秒，已結束 PID %d" % (timeout, p.pid)) from None
    if rc != 0 or not os.path.isfile(os.path.join(outdir, "done.json")):
        with open(lp, encoding="utf-8", errors="replace") as fh:
            tail = fh.read()[-600:]
        raise BlenderError("Blender 失敗（exit %s）：%s" % (rc, tail))
    fr = os.path.join(outdir, "frames")
    first, last = os.path.join(fr, "f_0001.png"), os.path.join(fr, "f_%04d.png" % data["frames"])
    files = {"first_frame": os.path.join(outdir, "first_frame.png"), "last_frame": os.path.join(outdir, "last_frame.png"),
             "depth": os.path.join(outdir, "depth.png"), "ref_video": os.path.join(outdir, "ref_video.mp4")}
    shutil.copyfile(first, files["first_frame"])
    shutil.copyfile(last, files["last_frame"])
    enc = h264_encoder(ffmpeg)
    if not enc:
        raise BlenderError("ffmpeg 沒有 H.264 編碼器")
    r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i",
                        os.path.join(fr, "f_%04d.png"), "-c:v", enc, "-pix_fmt", "yuv420p", files["ref_video"]],
                       capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    if r.returncode:
        raise BlenderError("灰模片編碼失敗：%s" % r.stderr[-300:])
    with open(os.path.join(outdir, "done.json"), encoding="utf-8") as fh:
        done = json.load(fh)
    return {"files": files, "pid": p.pid, "blender": done.get("blender"), "log": lp}
