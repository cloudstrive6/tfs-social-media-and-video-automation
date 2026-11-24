"""The approved TFS narrator (our own designed voice, master clip assets/voice/tfs_narrator_master.wav) re-styled
as a history storyteller on a Modal L4. Timbre comes from the master as a reference (VoxCPM2 reference_wav_path,
no continuation prompt so the news-read rhythm is not copied); the delivery is steered by a style instruction in
front of each sentence. Sentences are generated one by one and joined with designed pauses (the Epic History
study of 2026-11-24: about 1.2 s between sentences, 2 s before a turn). Control "C0" is the current production
mode (prompt + reference), read straight.

Never clones a real person: the only voice source is the channel's own synthetic master clip.
Run (needs MODAL_TOKEN_ID / MODAL_TOKEN_SECRET):  modal run modal_apps/tfs_voice_styled.py --out out/styled
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
HERE = pathlib.Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets" / "voice"
BRIEF = HERE / "voice_styled_brief.json"

app = modal.App("tfs-voice-styled")
weights = modal.Volume.from_name("tfs-voice-weights", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "libsndfile1")
    .pip_install("torch==2.10.0", "torchaudio==2.10.0", "torchcodec==0.17.0", "voxcpm==2.0.3",
                 "transformers==5.23.0", "huggingface_hub==2.4.0", "safetensors==0.8.0",
                 "soundfile==0.14.0", "librosa==0.11.0", "numpy==2.4.6")
    .env({"HF_HOME": HF_CACHE, "HF_HUB_DISABLE_TELEMETRY": "1", "TOKENIZERS_PARALLELISM": "false"})
    .add_local_file(str(ASSETS / "tfs_narrator_master.wav"), "/assets/master.wav")
    .add_local_file(str(ASSETS / "tfs_narrator_master.txt"), "/assets/master.txt")
)


@app.function(image=image, gpu="L4", cpu=2.0, memory=12288, volumes={"/weights": weights}, timeout=3000)
def styled(sentences: list[dict], styles: dict, seeds: list[int]) -> list[dict]:
    """sentences: [{"text": ..., "pause_after": seconds}]; styles: {id: instruction or "" for the control}."""
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
    master_txt = pathlib.Path("/assets/master.txt").read_text(encoding="utf-8").strip()
    print(f"model loaded in {time.time() - t0:.1f} s", flush=True)
    out = []
    for sid, instruction in styles.items():
        for n, seed in enumerate(seeds, 1):
            t = time.time()
            parts = []
            for k, s in enumerate(sentences):
                torch.manual_seed(seed + 97 * k)
                if instruction:                            # storyteller: timbre from the master, style from the text
                    wav = model.generate(text=f"({instruction}){s['text']}", reference_wav_path="/assets/master.wav",
                                         cfg_value=2.0, inference_timesteps=10)
                else:                                      # control: today's production read
                    wav = model.generate(text=s["text"], prompt_wav_path="/assets/master.wav", prompt_text=master_txt,
                                         reference_wav_path="/assets/master.wav", cfg_value=2.0, inference_timesteps=10)
                parts.append(np.asarray(wav, dtype=np.float32))
                parts.append(np.zeros(int(sr * float(s.get("pause_after", 0.0))), dtype=np.float32))
            full = np.concatenate(parts)
            buf = io.BytesIO()
            sf.write(buf, np.clip(full, -1, 1), sr, format="WAV", subtype="PCM_16")
            rec = {"voice": sid, "instruction": instruction, "seed": seed, "file": f"{sid}_take{n}.wav",
                   "secs": round(len(full) / sr, 2), "gen_s": round(time.time() - t, 1), "wav": buf.getvalue()}
            print(json.dumps({k: v for k, v in rec.items() if k != "wav"}), flush=True)
            out.append(rec)
    return out


@app.local_entrypoint()
def main(out: str = "out/styled"):
    brief = json.loads(BRIEF.read_text(encoding="utf-8"))
    o = pathlib.Path(out)
    o.mkdir(parents=True, exist_ok=True)
    t = time.time()
    takes = []
    for r in styled.remote(brief["sentences"], brief["styles"], brief["seeds"]):
        (o / r["file"]).write_bytes(r.pop("wav"))
        takes.append(r)
    text = " ".join(s["text"] for s in brief["sentences"])
    (o / "manifest.json").write_text(json.dumps({"text": text, "takes": takes, "wall_s": round(time.time() - t, 1)},
                                                ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", len(takes), "takes in", round(time.time() - t, 1), "s")
