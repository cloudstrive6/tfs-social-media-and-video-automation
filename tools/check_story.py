"""Filter and rank the storyteller takes, then build a blind listening page.

Pass: median pitch 110 to 155 Hz (brief 120 to 135, band widened by 15 Hz either side for take-to-take drift) and
Whisper letter match >= 0.85. Rank passes by distance to the Epic History delivery (2026-11-24 study): Tagalog pace
85 to 100 wpm with pauses, at least one pause of 1 s or more, pitch span 11 to 16 semitones (p5 to p95).
Run: D:/AI-Video/Demucs/.venv/Scripts/python.exe -I check_story.py
"""
import difflib, json, pathlib, random, re, subprocess, sys, unicodedata

import librosa, numpy as np, whisper

sys.stdout.reconfigure(encoding="utf-8")
HERE = pathlib.Path(__file__).resolve().parent
C = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "candidates"
man = json.loads((C / "manifest.json").read_text(encoding="utf-8"))


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", s))


ref = norm(man["text"])
words_in_text = len(man["text"].split())
wm = whisper.load_model("small", device="cpu")
rows = []
for t in man["takes"]:
    f = C / t["file"]
    y, sr = librosa.load(f, sr=16000)
    f0, vf, _ = librosa.pyin(y, fmin=60, fmax=400, sr=sr)
    v = f0[vf] if np.any(vf) else np.array([999.0])
    pitch = float(np.median(v))
    span = float(12 * np.log2(np.percentile(v, 95) / np.percentile(v, 5))) if len(v) > 10 else 0.0
    rms = librosa.feature.rms(y=y, frame_length=800, hop_length=160)[0]
    silent = rms < max(1e-4, 0.08 * np.median(rms[rms > 0]))
    runs, cur = [], 0
    for s in silent:
        cur = cur + 1 if s else 0
        if cur == 1:
            runs.append(0)
        if s:
            runs[-1] += 1
    long_pauses = sum(1 for r in runs if r * 0.01 >= 1.0)
    wpm = words_in_text / (len(y) / sr) * 60
    lm = difflib.SequenceMatcher(None, ref, norm(wm.transcribe(str(f), language="tl", fp16=False)["text"]),
                                 autojunk=False).ratio()
    ok = 110 <= pitch <= 155 and lm >= 0.85
    dist = abs(min(max(wpm, 85), 100) - wpm) / 10 + abs(min(max(span, 11), 16) - span) / 3 + (0 if long_pauses else 1) \
        + abs(pitch - 128) / 20
    rows.append({**t, "pitch": round(pitch, 1), "span_st": round(span, 1), "wpm": round(wpm, 1),
                 "long_pauses": long_pauses, "letter_match": round(lm, 3), "pass": ok, "distance": round(dist, 2)})
    print(t["file"], rows[-1]["pitch"], rows[-1]["span_st"], rows[-1]["wpm"], long_pauses, rows[-1]["letter_match"],
          "PASS" if ok else "fail", flush=True)
(C / "check.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")

best = {}
for r in rows:                                     # best take per voice: closest delivery among passes
    if r["pass"] and (r["voice"] not in best or r["distance"] < best[r["voice"]]["distance"]):
        best[r["voice"]] = r
picks = list(best.values())
random.Random(11).shuffle(picks)
B = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "blind"
(B / "mp3").mkdir(parents=True, exist_ok=True)
key, cards = {}, ""
for i, r in enumerate(picks, 1):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(C / r["file"]), "-ac", "1", "-ar", "24000",
                    "-c:a", "libmp3lame", "-b:a", "64k", str(B / "mp3" / f"v{i}.mp3")], check=True)
    key[f"Voice {i}"] = r
    cards += (f'<div class="v"><b>Voice {i}</b><audio controls preload="auto" src="mp3/v{i}.mp3"></audio></div>\n')
(B / "_key_do_not_open.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TFS Storyteller Voices</title><style>
:root{{--bg:#F5F0E6;--card:#fff;--ink:#15203A;--muted:#5A6275;--line:#DED6C6}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#14161c;--card:#1d2028;--ink:#EEF0F4;--muted:#A3A9B6;--line:#2c303a}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:Segoe UI,system-ui,sans-serif;padding:24px 16px}}
main{{max-width:760px;margin:0 auto}} h1{{font-size:22px;margin:0 0 8px}} p{{color:var(--muted);line-height:1.5}}
.v{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:10px 0}}
.v b{{display:block;margin-bottom:6px}} audio{{width:100%}}
</style></head><body><main><h1>TFS history storyteller: {len(picks)} designed voices</h1>
<p>Same Spanish-era passage, read by {len(picks)} male storyteller voices designed from a written brief (no real narrator cloned). Listen blind and pick by ear.</p>
{cards}</main></body></html>"""
(B / "listen.html").write_text(page, encoding="utf-8")
print("picked", len(picks), {k: v["file"] for k, v in key.items()})
