"""Narrate one queued TFS job on the local RTX 3080 with VoxCPM2: the same model snapshot, master clip and settings as
the Modal app (modal_apps/tfs_voice.py), so the voice is identical wherever a line is made.

Run by tools/voice_worker.py inside the GPU slot, with the VoxCPM venv (not the repo venv):
    D:/AI-Video/VoxCPM/.venv/Scripts/python.exe -I tools/voice_local_gen.py <job.json> <out_dir>
Writes <out_dir>/<file or id:03d.wav> (48 kHz mono 16-bit) per line (several episodes can share one model load) and prints one JSON line per line plus a summary.
"""
import json
import pathlib
import sys
import time

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import numpy as np
import soundfile as sf
import torch
import voxcpm.model.voxcpm2 as _v2
from voxcpm import VoxCPM

ROOT = pathlib.Path(__file__).resolve().parent.parent
MASTER_WAV = ROOT / "assets" / "voice" / "tfs_narrator_master.wav"
MASTER_TXT = ROOT / "assets" / "voice" / "tfs_narrator_master.txt"


def _load_lowmem(path, device="cpu"):
    """Tensor by tensor: the plain loader maps the whole file at once and fails when commit is tight."""
    from safetensors import safe_open
    out = {}
    with safe_open(path, framework="pt", device="cpu") as f:
        for k in f.keys():
            out[k] = f.get_tensor(k)
    return out


_v2.load_file = _load_lowmem


def main(job_path: str, out_dir: str) -> None:
    job = json.loads(pathlib.Path(job_path).read_text(encoding="utf-8"))
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False, optimize=False, device="cuda",
                                   local_files_only=True)
    sr = model.tts_model.sample_rate
    prompt_text = MASTER_TXT.read_text(encoding="utf-8").strip()
    load_s, audio_s = time.time() - t0, 0.0
    for line in job["lines"]:
        torch.manual_seed(int(job.get("seed", 19)))
        t = time.time()
        wav = model.generate(text=line["text"], prompt_wav_path=str(MASTER_WAV), prompt_text=prompt_text,
                             reference_wav_path=str(MASTER_WAV), cfg_value=2.0, inference_timesteps=10)
        wav = np.clip(np.asarray(wav, dtype=np.float32), -1.0, 1.0)
        sf.write(str(out / (line.get("file") or f"{int(line['id']):03d}.wav")), wav, sr, subtype="PCM_16")
        audio_s += len(wav) / sr
        print(json.dumps({"id": line["id"], "secs": round(len(wav) / sr, 2), "gen_s": round(time.time() - t, 1)}),
              flush=True)
    gen_s = time.time() - t0 - load_s
    print(json.dumps({"done": len(job["lines"]), "audio_s": round(audio_s, 1), "load_s": round(load_s, 1),
                      "gen_s": round(gen_s, 1), "rtf": round(gen_s / max(audio_s, 1e-6), 2)}), flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
