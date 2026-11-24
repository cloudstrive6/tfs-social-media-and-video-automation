"""One-off VoxCPM2 voice DESIGN on a Modal L4 (text description only, no reference audio, no cloning of anyone).

Used for the TFS history storyteller narrator (brief from the Epic History delivery study of 2026-11-24): the
designs and the test passage live in modal_apps/voice_design_brief.json. Weights come from the same Modal Volume
as tfs-voice ("tfs-voice-weights"), so nothing is downloaded again.

Run (needs MODAL_TOKEN_ID / MODAL_TOKEN_SECRET):  modal run modal_apps/tfs_voice_design.py --out out/design
Writes out/design/<voice>_take<n>.wav and out/design/manifest.json.
"""
from __future__ import annotations

import io
import json
import pathlib
import time

import modal

MODEL_ID = "openbmb/VoxCPM2"
MODEL_REV = "7936080b41163874f38610f46f438e2c0757f9fd"
HF_CACHE = "/weights/hf"
BRIEF = pathlib.Path(__file__).resolve().parent / "voice_design_brief.json"

app = modal.App("tfs-voice-design")
weights = modal.Volume.from_name("tfs-voice-weights", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "libsndfile1")
    .pip_install("torch==2.10.0", "torchaudio==2.10.0", "torchcodec==0.17.0", "voxcpm==2.0.3",
                 "transformers==5.23.0", "huggingface_hub==2.4.0", "safetensors==0.8.0",
                 "soundfile==0.14.0", "librosa==0.11.0", "numpy==2.4.6")
    .env({"HF_HOME": HF_CACHE, "HF_HUB_DISABLE_TELEMETRY": "1", "TOKENIZERS_PARALLELISM": "false"})
)


@app.function(image=image, gpu="L4", cpu=2.0, memory=12288, volumes={"/weights": weights}, timeout=2400)
def design(text: str, voices: dict, seeds: list[int]) -> list[dict]:
    import numpy as np
    import soundfile as sf
    import torch
    from huggingface_hub import snapshot_download
    from voxcpm import VoxCPM

    try:
        path = snapshot_download(MODEL_ID, revision=MODEL_REV, cache_dir=HF_CACHE, local_files_only=True)
    except Exception:
        path = snapshot_download(MODEL_ID, revision=MODEL_REV, cache_dir=HF_CACHE)
        weights.commit()
    t0 = time.time()
    model = VoxCPM.from_pretrained(path, load_denoiser=False, optimize=False, device="cuda")
    sr = model.tts_model.sample_rate
    print(f"model loaded in {time.time() - t0:.1f} s", flush=True)
    out = []
    for vid, desc in voices.items():
        for n, seed in enumerate(seeds, 1):
            torch.manual_seed(seed)
            t = time.time()
            wav = model.generate(text=f"({desc}){text}", cfg_value=2.0, inference_timesteps=10)
            buf = io.BytesIO()
            sf.write(buf, np.clip(np.asarray(wav, dtype=np.float32), -1, 1), sr, format="WAV", subtype="PCM_16")
            rec = {"voice": vid, "desc": desc, "seed": seed, "file": f"{vid}_take{n}.wav",
                   "secs": round(len(wav) / sr, 2), "gen_s": round(time.time() - t, 1), "wav": buf.getvalue()}
            print(json.dumps({k: v for k, v in rec.items() if k != "wav"}), flush=True)
            out.append(rec)
    return out


@app.local_entrypoint()
def main(out: str = "out/design"):
    brief = json.loads(BRIEF.read_text(encoding="utf-8"))
    o = pathlib.Path(out)
    o.mkdir(parents=True, exist_ok=True)
    t = time.time()
    recs = design.remote(brief["text"], brief["voices"], brief["seeds"])
    takes = []
    for r in recs:
        (o / r["file"]).write_bytes(r.pop("wav"))
        takes.append(r)
    (o / "manifest.json").write_text(json.dumps({"text": brief["text"], "takes": takes, "wall_s": round(time.time() - t, 1)},
                                                ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", len(takes), "takes in", round(time.time() - t, 1), "s")
