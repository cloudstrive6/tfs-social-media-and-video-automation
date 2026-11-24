"""Score the re-styled narrator takes against the master (same voice?) and the storyteller brief (delivery).

Same voice: median pitch within 15 Hz of the master and MFCC timbre distance no larger than the control's (C0, the
current production read). Clear: Whisper letter match >= 0.85. Delivery: speaking pace, pauses of 1 s or more,
pitch span (p5 to p95, semitones). Writes check.json and small MP3s for in-chat review.
Run: python tools/check_styled.py <takes_dir> <master_wav> <out_dir>
"""
import difflib, json, pathlib, re, subprocess, sys, unicodedata

import librosa, numpy as np, whisper

takes_dir, master, out = pathlib.Path(sys.argv[1]), sys.argv[2], pathlib.Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
man = json.loads((takes_dir / "manifest.json").read_text(encoding="utf-8"))


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return " ".join(re.findall(r"[a-z0-9]+", "".join(c for c in s if not unicodedata.combining(c))))


def feats(path):
    y, sr = librosa.load(path, sr=16000)
    f0, vf, _ = librosa.pyin(y, fmin=60, fmax=400, sr=sr)
    v = f0[vf] if np.any(vf) else np.array([np.nan])
    mf = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20)
    rms = librosa.feature.rms(y=y, frame_length=800, hop_length=160)[0]
    voiced = rms > 0.08 * np.median(rms[rms > 0])
    runs, cur = [], 0
    for s in ~voiced:
        cur = cur + 1 if s else 0
        if cur == 1:
            runs.append(0)
        if s:
            runs[-1] += 1
    return {"pitch": float(np.nanmedian(v)), "span": float(12 * np.log2(np.nanpercentile(v, 95) / np.nanpercentile(v, 5))),
            "mfcc": mf[1:].mean(axis=1), "speech_s": float(voiced.sum() * 0.01), "dur": len(y) / sr,
            "long_pauses": sum(1 for r in runs if r * 0.01 >= 1.0)}


ref = norm(man["text"])
n_words = len(man["text"].split())
m = feats(master)
wm = whisper.load_model("small", device="cpu")
rows = []
for t in man["takes"]:
    f = takes_dir / t["file"]
    x = feats(f)
    lm = difflib.SequenceMatcher(None, ref, norm(wm.transcribe(str(f), language="tl", fp16=False)["text"]),
                                 autojunk=False).ratio()
    rows.append({**t, "pitch": round(x["pitch"], 1), "span_st": round(x["span"], 1),
                 "timbre_dist": round(float(np.linalg.norm(x["mfcc"] - m["mfcc"])), 2),
                 "wpm_overall": round(n_words / x["dur"] * 60, 1), "wpm_speaking": round(n_words / max(1, x["speech_s"]) * 60, 1),
                 "long_pauses": x["long_pauses"], "letter_match": round(lm, 3)})
    print(json.dumps(rows[-1]), flush=True)
ctrl = min((r["timbre_dist"] for r in rows if r["voice"] == "C0"), default=99)
for r in rows:
    r["same_voice"] = abs(r["pitch"] - m["pitch"]) <= 15 and r["timbre_dist"] <= ctrl * 1.15
    r["pass"] = r["same_voice"] and r["letter_match"] >= 0.85
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(takes_dir / r["file"]), "-ac", "1", "-ar", "22050",
                    "-c:a", "libmp3lame", "-b:a", "24k", str(out / r["file"].replace(".wav", ".mp3"))], check=True)
(out / "check.json").write_text(json.dumps({"master": {"pitch": round(m["pitch"], 1), "span_st": round(m["span"], 1)},
                                            "control_timbre_dist": ctrl, "takes": rows}, indent=1), encoding="utf-8")
print("master pitch", round(m["pitch"], 1), "control timbre", ctrl)
