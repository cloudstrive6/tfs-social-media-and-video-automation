"""TFS v2 hero shot: paper-white 3D archipelago, camera pushes in from high over the Philippines to Metro Manila,
which rises in brick red (it marks where Congress sits; no data is encoded in the heights).
Geometry: Natural Earth provinces (public domain). Cycles on CPU so the GPU stays with Taas Noo.
Run: blender -b -P hero_ph_push.py -- <out_dir> [samples] [fps] [seconds]
Writes <out_dir>/f0001.png ... ; encode with ffmpeg afterwards.
"""
import bpy, bmesh, json, math, sys, time, pathlib

argv = sys.argv[sys.argv.index("--") + 1:]
OUT = pathlib.Path(argv[0]); OUT.mkdir(parents=True, exist_ok=True)
SAMPLES = int(argv[1]) if len(argv) > 1 else 24
FPS = int(argv[2]) if len(argv) > 2 else 24
SECS = float(argv[3]) if len(argv) > 3 else 4.0
import os
GEO = pathlib.Path(os.environ.get("TFS_GEO", "assets/geo/ph_provinces.json"))
provs = json.loads(GEO.read_text(encoding="utf-8"))

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
LON0, LAT0 = 121.8, 12.9
k = math.cos(math.radians(LAT0))
def P(lon, lat): return ((lon - LON0) * k, (lat - LAT0))

def mat(name, rgb, rough=0.7, noise=False):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; b = nt.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough
    if noise:                                   # paper fibre: subtle noise into the colour
        tex = nt.nodes.new("ShaderNodeTexNoise"); tex.inputs["Scale"].default_value = 180; tex.inputs["Detail"].default_value = 6
        mix = nt.nodes.new("ShaderNodeMixRGB"); mix.blend_type = "MULTIPLY"; mix.inputs["Fac"].default_value = 0.08
        mix.inputs["Color1"].default_value = (*rgb, 1)
        nt.links.new(tex.outputs["Color"], mix.inputs["Color2"]); nt.links.new(mix.outputs["Color"], b.inputs["Base Color"])
    return m
paper = mat("paper", (0.80, 0.76, 0.66), 0.95, noise=True)
land = mat("land", (0.95, 0.93, 0.88), 0.85)
brick = mat("brick", (0.55, 0.06, 0.08), 0.5)
ink = mat("ink", (0.08, 0.11, 0.20), 0.6)

bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, 0)); bpy.context.object.data.materials.append(paper)

def is_ncr(p):
    n = (p["name"] + " " + p.get("region", "")).lower()
    return "metropolitan manila" in n or "national capital" in n
ncr_xy = []
for i, p in enumerate(provs):
    rings = []                                  # outer ring of each polygon only: inner rings are lakes and holes
    for r in p["polys"]:
        rings.append(r[0] if r and isinstance(r[0][0], list) else r)
    ncr = is_ncr(p)
    h = 0.32 if ncr else 0.06
    for ring in rings:
        if len(ring) < 4: continue
        me = bpy.data.meshes.new(f"p{i}"); bm = bmesh.new()
        vs = [bm.verts.new((*P(lon, lat), 0.001)) for lon, lat in ring[:-1]]
        try:
            f = bm.faces.new(vs)
        except ValueError:
            bm.free(); continue
        bmesh.ops.recalc_face_normals(bm, faces=[f])
        ext = bmesh.ops.extrude_face_region(bm, geom=[f])
        top = [v for v in ext["geom"] if isinstance(v, bmesh.types.BMVert)]
        bmesh.ops.translate(bm, verts=top, vec=(0, 0, h))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])   # every face outward, so no black backfaces
        bm.to_mesh(me); bm.free()
        ob = bpy.data.objects.new(f"p{i}", me); sc.collection.objects.link(ob)
        ob.data.materials.append(brick if ncr else land)
        if ncr: ncr_xy += [P(lon, lat) for lon, lat in ring]
cx = sum(x for x, y in ncr_xy) / len(ncr_xy); cy = sum(y for x, y in ncr_xy) / len(ncr_xy)

# soft key light and a warm paper-toned world
bpy.ops.object.light_add(type="SUN", location=(0, 0, 10)); sun = bpy.context.object
sun.data.energy = 2.6; sun.rotation_euler = (math.radians(42), math.radians(8), math.radians(140)); sun.data.angle = math.radians(12)
w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.86, 0.82, 0.74, 1); w.node_tree.nodes["Background"].inputs[1].default_value = 0.55
sc.view_settings.view_transform = "Standard"; sc.view_settings.look = "None"

# camera: wide over the archipelago, push to Metro Manila with an ease, slight arc
bpy.ops.object.camera_add(); cam = bpy.context.object; sc.camera = cam; cam.data.lens = 42
tgt = bpy.data.objects.new("tgt", None); sc.collection.objects.link(tgt)
con = cam.constraints.new("TRACK_TO"); con.target = tgt; con.track_axis = "TRACK_NEGATIVE_Z"; con.up_axis = "UP_Y"
N = int(SECS * FPS)
sc.frame_start, sc.frame_end = 1, N; sc.render.fps = FPS
tgt.location = (0.3, 0.6, 0); tgt.keyframe_insert("location", frame=1)
tgt.location = (cx, cy, 0.15); tgt.keyframe_insert("location", frame=N)
cam.location = (1.5, -14.0, 17.0); cam.keyframe_insert("location", frame=1)
cam.location = (cx + 0.9, cy - 2.6, 2.4); cam.keyframe_insert("location", frame=N)
for ob in (cam, tgt):
    for fc in ob.animation_data.action.fcurves:
        for kp in fc.keyframe_points: kp.interpolation = "BEZIER"; kp.easing = "EASE_IN_OUT"

sc.render.engine = "CYCLES"; sc.cycles.samples = SAMPLES; sc.cycles.use_denoising = True
sc.cycles.device = "CPU"
if os.environ.get("TFS_CYCLES_DEVICE") == "GPU":           # Modal L4: OptiX, else CUDA
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = kind; prefs.get_devices()
            if any(d.type == kind for d in prefs.devices):
                for d in prefs.devices: d.use = d.type == kind
                sc.cycles.device = "GPU"; print("DEVICE", kind, flush=True); break
        except TypeError:
            continue
sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
sc.render.image_settings.file_format = "PNG"
t0 = time.time()
rng = os.environ.get("TFS_FRAMES")
F0, F1 = (int(x) for x in rng.split("-")) if rng else (1, N)
for fr in range(F0, F1 + 1):
    if (OUT / f"f{fr:04d}.png").exists(): continue           # resumable
    sc.frame_set(fr); sc.render.filepath = str(OUT / f"f{fr:04d}.png")
    bpy.ops.render.render(write_still=True)
    print(f"FRAME {fr}/{N} {time.time() - t0:.0f}s", flush=True)
print("DONE", round(time.time() - t0))
