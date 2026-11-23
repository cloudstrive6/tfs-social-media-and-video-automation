"""TFS Blender hero shots on a Modal L4 GPU (Bryce approved Modal for this on 2026-11-24).

Renders any TFS Blender scene script headless with Cycles on the GPU (OptiX), split into frame chunks
across a few containers, and returns the PNG frames. The same scene scripts run locally on the CPU;
they read these environment variables when set:
    TFS_CYCLES_DEVICE=GPU    use the GPU (OptiX, falls back to CUDA)
    TFS_GEO=<path>           the Natural Earth geo JSON the scene needs
    TFS_FRAMES=<a>-<b>       render only this frame range
Blender 4.5.10 LTS, the same version as the local install. Nothing private is in the image.

Cost guide (Modal pricing page, read 2026-11-24): L4 about US$0.000222 a second (about US$0.80 an
hour) plus a little CPU and memory, billed only while running, inside the US$30 monthly free credit.

    modal run modal_apps/tfs_blender.py --script <scene.py> --geo <geo.json> --frames 96 --out <dir> [--chunks 3] [--samples 24]
"""
from __future__ import annotations

import io
import pathlib
import time
import zipfile

import modal

BLENDER_URL = "https://download.blender.org/release/Blender4.5/blender-4.5.10-linux-x64.tar.xz"
app = modal.App("tfs-blender-render")
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("wget", "xz-utils", "libxrender1", "libxi6", "libxkbcommon0", "libsm6", "libgl1", "libegl1",
                 "libxxf86vm1", "libxfixes3", "libxext6", "libx11-6")
    .run_commands(f"wget -q {BLENDER_URL} -O /tmp/b.tar.xz && mkdir -p /opt/blender && "
                  "tar -xJf /tmp/b.tar.xz -C /opt/blender --strip-components=1 && rm /tmp/b.tar.xz")
)


@app.function(image=image, gpu="L4", timeout=3600)
def render_chunk(script: bytes, geo: bytes, first: int, last: int, samples: int, fps: int, secs: float) -> dict:
    import os, subprocess
    work = pathlib.Path("/tmp/work"); out = work / "frames"; out.mkdir(parents=True, exist_ok=True)
    (work / "scene.py").write_bytes(script); (work / "geo.json").write_bytes(geo)
    env = dict(os.environ, TFS_CYCLES_DEVICE="GPU", TFS_GEO=str(work / "geo.json"), TFS_FRAMES=f"{first}-{last}")
    t = time.time()
    res = subprocess.run(["/opt/blender/blender", "-b", "-P", str(work / "scene.py"), "--", str(out), str(samples), str(fps), str(secs)],
                         env=env, capture_output=True, text=True)
    if res.returncode:
        raise RuntimeError(res.stdout[-3000:] + res.stderr[-3000:])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for f in sorted(out.glob("*.png")):
            z.write(f, f.name)
    device = [ln for ln in res.stdout.splitlines() if "DEVICE" in ln]
    return {"zip": buf.getvalue(), "seconds": round(time.time() - t, 1), "first": first, "last": last, "device": device[:1]}


@app.local_entrypoint()
def main(script: str, geo: str, frames: int, out: str, chunks: int = 3, samples: int = 24, fps: int = 24, secs: float = 4.0):
    s = pathlib.Path(script).read_bytes(); g = pathlib.Path(geo).read_bytes()
    o = pathlib.Path(out); o.mkdir(parents=True, exist_ok=True)
    step = -(-frames // chunks)
    args = [(s, g, a, min(frames, a + step - 1), samples, fps, secs) for a in range(1, frames + 1, step)]
    t = time.time(); gpu_s = 0.0
    for r in render_chunk.starmap(args):
        with zipfile.ZipFile(io.BytesIO(r["zip"])) as z:
            z.extractall(o)
        gpu_s += r["seconds"]
        print(f"chunk {r['first']}-{r['last']}: {r['seconds']} s on GPU {r['device']}", flush=True)
    print(f"DONE {frames} frames, wall {time.time() - t:.0f} s, GPU-seconds {gpu_s:.0f}, "
          f"approx L4 cost US${gpu_s * 0.000222:.3f} (plus CPU/memory and image build on first run)")
