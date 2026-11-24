"""TFS narrator on a Modal L4 GPU: VoxCPM2 in clone mode from the approved master clip (voice picked 2026-11-23).

Every line is generated from assets/voice/tfs_narrator_master.wav plus its text (prompt wav, prompt text and
reference wav all set to the master), never from a text description and never from a real person, so the voice
stays identical across videos. Settings match the local pilot (revamp-2026-11/voice/narrate.py): VoxCPM 2.0.3,
model openbmb/VoxCPM2 at the same snapshot as the local cache, cfg_value 2.0, 10 inference timesteps, no
denoiser, no torch.compile.

Output: one 16-bit PCM mono WAV per take per line at the model's native 48 kHz.

Weights (about 4.7 GB) live in the Modal Volume "tfs-voice-weights" and are downloaded once. Nothing private is in
the image: only open packages, the public model and the master clip (the channel's own synthetic voice).

Deploy (needs MODAL_TOKEN_ID / MODAL_TOKEN_SECRET):
    modal deploy modal_apps/tfs_voice.py
    modal run modal_apps/tfs_voice.py::download_weights          # optional: fill the Volume on a CPU box first
    modal run modal_apps/tfs_voice.py --text "Sa Pilipinas, anim na taon." --out out/voice   # smoke test
The pipeline calls it with modal.Function.from_name("tfs-voice", "narrate") (src/tfs/media/tts_voxcpm.py).
Cost notes are in src/tfs/media/tts_voxcpm.py.
"""
from __future__ import annotations

import io
import pathlib
import time

import modal

MODEL_ID = "openbmb/VoxCPM2"
MODEL_REV = "7936080b41163874f38610f46f438e2c0757f9fd"     # same snapshot as the local pilot cache
WEIGHTS = "/weights"
HF_CACHE = f"{WEIGHTS}/hf"
MASTER_WAV = "/assets/tfs_narrator_master.wav"
MASTER_TXT = "/assets/tfs_narrator_master.txt"
TAKE_SEED_STEP = 12                                         # take k uses seed + 12*k (pilot: takes at 11 and 23)
ASSETS = pathlib.Path(__file__).resolve().parent.parent / "assets" / "voice"

app = modal.App("tfs-voice")
weights = modal.Volume.from_name("tfs-voice-weights", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "libsndfile1")
    .pip_install(                                           # pinned to the local D:/AI-Video/VoxCPM venv
        "torch==2.10.0", "torchaudio==2.10.0", "torchcodec==0.17.0", "voxcpm==2.0.3",
        "transformers==5.23.0", "huggingface_hub==2.4.0", "safetensors==0.8.0",
        "soundfile==0.14.0", "librosa==0.11.0", "numpy==2.4.6",
    )
    .env({"HF_HOME": HF_CACHE, "HF_HUB_DISABLE_TELEMETRY": "1", "TOKENIZERS_PARALLELISM": "false"})
    .add_local_file(str(ASSETS / "tfs_narrator_master.wav"), MASTER_WAV)
    .add_local_file(str(ASSETS / "tfs_narrator_master.txt"), MASTER_TXT)
)

_MODEL = None                                               # kept while a warm container is reused


def _snapshot() -> str:
    from huggingface_hub import snapshot_download
    try:
        return snapshot_download(MODEL_ID, revision=MODEL_REV, cache_dir=HF_CACHE, local_files_only=True)
    except Exception:
        path = snapshot_download(MODEL_ID, revision=MODEL_REV, cache_dir=HF_CACHE)
        weights.commit()
        return path


def _model():
    global _MODEL
    if _MODEL is None:
        from voxcpm import VoxCPM
        t = time.time()
        _MODEL = VoxCPM.from_pretrained(_snapshot(), load_denoiser=False, optimize=False, device="cuda")
        print(f"model loaded in {time.time() - t:.1f} s", flush=True)
    return _MODEL


def _wav_bytes(wav, sr: int) -> bytes:
    import numpy as np
    import soundfile as sf
    buf = io.BytesIO()
    sf.write(buf, np.clip(np.asarray(wav, dtype=np.float32), -1.0, 1.0), sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


@app.function(image=image, gpu="L4", cpu=2.0, memory=12288, volumes={WEIGHTS: weights},
              timeout=3600, scaledown_window=20, max_containers=4)
def narrate(lines: list[str], seed: int = 19, takes: int = 2) -> list[list[bytes]]:
    """WAV bytes (48 kHz, 16-bit, mono) for each take of each line: result[line][take]. One model load per call."""
    import torch
    model = _model()
    sr = model.tts_model.sample_rate
    prompt_text = pathlib.Path(MASTER_TXT).read_text(encoding="utf-8").strip()
    out, t0, audio_s = [], time.time(), 0.0
    for i, text in enumerate(lines):
        if not text.strip():
            raise ValueError(f"line {i} is empty")
        line_takes = []
        for k in range(takes):
            torch.manual_seed(seed + TAKE_SEED_STEP * k)
            wav = model.generate(text=text, prompt_wav_path=MASTER_WAV, prompt_text=prompt_text,
                                 reference_wav_path=MASTER_WAV, cfg_value=2.0, inference_timesteps=10)
            audio_s += len(wav) / sr
            line_takes.append(_wav_bytes(wav, sr))
        out.append(line_takes)
    gen = time.time() - t0
    print(f"{len(lines)} lines x {takes} takes: {audio_s:.1f} s audio in {gen:.1f} s "
          f"(real-time factor {gen / max(audio_s, 1e-6):.2f})", flush=True)
    return out


@app.function(image=image, cpu=1.0, memory=4096, volumes={WEIGHTS: weights}, timeout=1800)
def download_weights() -> str:
    """Fill the weights Volume without paying for a GPU."""
    return _snapshot()


@app.local_entrypoint()
def main(text: str, out: str = "out/voice", seed: int = 19, takes: int = 2):
    o = pathlib.Path(out)
    o.mkdir(parents=True, exist_ok=True)
    t = time.time()
    res = narrate.remote([text], seed=seed, takes=takes)
    for k, data in enumerate(res[0]):
        (o / f"take{k}.wav").write_bytes(data)
    print(f"wrote {len(res[0])} takes to {o} in {time.time() - t:.0f} s wall")
