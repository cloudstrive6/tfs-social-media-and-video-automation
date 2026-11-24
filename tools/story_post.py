"""Storyteller design in post on an exact clone of the TFS narrator (Bryce, 2026-11-24).

Picks the clearest clone take (Whisper letter match), then renders variants with Rubber Band (formant-preserving,
so the voice stays itself) and ffmpeg EQ:
  P0 clone, designed pauses only
  P1 slower: tempo 0.90
  P2 slower and a touch deeper: tempo 0.90, pitch -1 semitone, warm EQ
  P3 slowest and deeper: tempo 0.86, pitch -1.5 semitones, warm EQ, faint room
Writes check.json (pitch, timbre distance to the master, pace, clarity) and 24 kb/s MP3s for in-chat review.
Run: python tools/story_post.py <takes_dir> <master_wav> <out_dir>
"""
import difflib, json, pathlib, re, subprocess, sys, unicodedata

import librosa, numpy as np, whisper

takes, master, out = pathlib.Path(sys.argv[1]), sys.argv[2], pathlib.Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
man = json.loads((takes / "manifest.json").read_text(encoding="utf-8"))
WARM = "equalizer=f=140:t=q:w=1.0:g=2.5,equalizer=f=3500:t=q:w=1.2:g=-1.5,equalizer=f=7500:t=q:w=1.5:g=-2"
ROOM = "aecho=0.8:0.5:40|70:0.10|0.06"
VARIANTS = {"P0": (1.0, 0.0, ""), "P1": (0.90, 0.0, ""), "P2": (0.90, -1.0, WARM), "P3": (0.86, -1.5, WARM + "," + ROOM)}


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return " ".join(re.findall(r"[a-z0-9]+", "".join(c for c in s if not unicodedata.combining(c))))


def feats(path):
    y, sr = librosa.load(path, sr=16000)
    f0, vf, _ = librosa.pyin(y, fmin=60, fmax=400, sr=sr)
    v = f0[vf] if np.any(vf) else np.array([np.nan])
    mf = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20)
    return float(np.nanmedian(v)), float(12 * np.log2(np.nanpercentile(v, 95) / np.nanpercentile(v, 5))), mf[1:].mean(1), len(y) / sr


wm = whisper.load_model("small", device="cpu")
ref, nw = norm(man["text"]), len(man["text"].split())
lm = lambda p: difflib.SequenceMatcher(None, ref, norm(wm.transcribe(str(p), language="tl", fp16=False)["text"]), autojunk=False).ratio()
best = max(man["takes"], key=lambda t: lm(takes / t["file"]))
src = takes / best["file"]
mp, _, mm, _ = feats(master)
rows = []
for vid, (tempo, semis, fx) in VARIANTS.items():
    stretched = out / f"{vid}_rb.wav"
    if tempo == 1.0 and semis == 0.0:
        subprocess.run(["cp", str(src), str(stretched)], check=True)
    else:
        subprocess.run(["rubberband", "-q", "-F", "-3", "-t", f"{1 / tempo:.4f}", "-p", str(semis), str(src), str(stretched)], check=True)
    final = out / f"{vid}.wav"
    af = (fx + "," if fx else "") + "loudnorm=I=-18:TP=-2:LRA=7"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(stretched), "-af", af, "-ar", "48000", str(final)], check=True)
    p, span, mf, dur = feats(final)
    rows.append({"variant": vid, "tempo": tempo, "semitones": semis, "pitch": round(p, 1), "span_st": round(span, 1),
                 "timbre_dist": round(float(np.linalg.norm(mf - mm)), 2), "wpm_overall": round(nw / dur * 60, 1),
                 "letter_match": round(lm(final), 3), "from_take": best["file"]})
    print(json.dumps(rows[-1]), flush=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(final), "-ac", "1", "-ar", "22050", "-c:a", "libmp3lame",
                    "-b:a", "24k", str(out / f"{vid}.mp3")], check=True)
(out / "check.json").write_text(json.dumps({"master_pitch": round(mp, 1), "variants": rows}, indent=1), encoding="utf-8")
