"""Orchestrator. Every step writes its artifact to data/items/<id>/ and is skipped if the artifact
exists, so a crashed or approval-paused item resumes exactly where it stopped."""
from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, TypeVar

from pydantic import BaseModel

from . import db, notify, qa, slots
from .agents import editor, packaging, trend_scout, writers
from .config import channel, data_dir, env, item_dir, media, now, paused_kinds, schedule
from .llm import UsageLimitError
from .media.tts_voxcpm import VoiceDeferred
from .media import compose, render, tts
from .models import (FactCheck, HookReview, ReviewReport, Scene, Script, SeoPack, ShotList, ThumbnailPlan,
                     TitlePlan)

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
SCOUT_EVERY = timedelta(hours=3)
MAX_REWRITES = 2
PUBLISH_EVERY = 60                      # seconds between publish checks while a cloud run is alive
LINGER = timedelta(minutes=35)          # a run stays up for an exact-time post due within this window
HARD_STOP = timedelta(hours=5, minutes=20)  # job timeout is 340 min; leave time to save state
_publishing = threading.Lock()          # the publisher thread and the main thread never publish at once


# ---------------------------------------------------------------- helpers
def cached(path: Path, schema: type[T], make: Callable[[], T]) -> T:
    if path.exists():
        return schema.model_validate_json(path.read_text(encoding="utf-8"))
    obj = make()
    path.write_text(obj.model_dump_json(indent=2), encoding="utf-8")
    return obj


def cached_text(path: Path, make: Callable[[], str]) -> str:
    if not path.exists():
        path.write_text(make(), encoding="utf-8")
    return path.read_text(encoding="utf-8")


def _gate(item: dict, fc: FactCheck) -> bool:
    """Legal/quality gate. Returns True if production may continue."""
    if item["data"].get("approved"):
        return True
    iid = item["id"]
    if fc.verdict == "reject":
        db.set_status(iid, "skipped", "fact-check rejected")
        notify.send(f"⛔ {iid} rejected by fact-check: " + "; ".join(i.problem for i in fc.issues[:5]))
        return False
    rules = channel()["quality"].get("require_human_approval_for", [])
    if not rules and (fc.verdict == "needs_human" or fc.names_living_person_with_allegation):
        reason = ("still names a living person over an unproven allegation" if fc.names_living_person_with_allegation
                  else "fact-check could not clear it")
        db.set_status(iid, "skipped", f"auto-skipped: {reason}")
        notify.send(f"⏭️ {iid} auto-skipped ({reason}). The slot will be filled next cycle.")
        return False
    if fc.verdict == "needs_human" or (fc.names_living_person_with_allegation
                                       and "names_living_person_with_allegation" in rules):
        db.set_status(iid, "awaiting_approval")
        issues = "\n".join(f"- {i.line[:80]} → {i.problem}" for i in fc.issues[:8])
        notify.send(f"🟡 Approval needed: {iid} — {item['data'].get('working_title')}\n"
                    f"Script: {item_dir(iid) / 'factcheck.json'}\n{issues}\n\n"
                    f"Approve: tfs approve {iid}   Reject: tfs reject {iid}")
        return False
    return True


def _script(item: dict, d: Path, dossier: str) -> tuple[Script, HookReview] | None:
    """Writer drafts, Hook Master rewrites; up to MAX_REWRITES rounds to reach the quality bar."""
    q = channel()["quality"]
    issue = db.count_before("long_form", item["id"]) + 1
    feedback = ""
    for rnd in range(MAX_REWRITES + 1):
        draft = cached(d / f"script_r{rnd}.json", Script,
                       lambda: writers.write_script(item, dossier, issue, feedback))
        hook = cached(d / f"hook_r{rnd}.json", HookReview, lambda: writers.hook_pass(item, draft))
        n, limit, floor = writers.spoken_words(hook.script), writers.max_words(item["kind"]), writers.min_words(item["kind"])
        if n > limit * 1.08:
            feedback = (f"TOO LONG: {n} spoken words; the hard limit is {limit}. Cut to {limit} words or fewer: "
                        "one idea, no second example, shortest possible setup.\n" + "\n".join(hook.fixes))
            continue
        if floor and n < floor * 0.95:
            feedback = (f"TOO SHORT: {n} spoken words; long-form must be at least {floor} words "
                        f"({channel()['video']['long_form']['target_minutes'][0]} minutes). Deepen it with another "
                        "chapter, a historical root or a concrete case from the dossier — never padding.\n"
                        + "\n".join(hook.fixes))
            continue
        if hook.hook_score >= q["min_hook_score"] and hook.retention_score >= q["min_script_score"]:
            return hook.script, hook
        feedback = "\n".join(hook.fixes) + f"\n(hook {hook.hook_score}/10, retention {hook.retention_score}/10)"
    db.set_status(item["id"], "skipped", f"below quality bar after {MAX_REWRITES + 1} drafts")
    notify.send(f"⚠️ {item['id']} skipped — script never reached the quality bar.")
    return None


# ---------------------------------------------------------------- video
def _fixes(d: Path) -> dict:
    """Corrections from the review team: {"images": {key: prompt}, "audio": {scene id: tts text}}."""
    f = d / "qa_fixes.json"
    fixes = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    return {"images": {}, "audio": {}, "attempts": {}, "drop": [], **fixes}


def _voiced(script: Script, d: Path) -> list[Scene]:
    """Scenes as the narrator reads them (the Proofreader may respell a line so numbers/names come out right)."""
    respell = _fixes(d)["audio"]
    return [sc.model_copy(update={"text": respell[str(sc.id)]}) if respell.get(str(sc.id)) else sc
            for sc in script.scenes]


def _voiced_script(script: Script, d: Path) -> Script:
    return script.model_copy(update={"scenes": _voiced(script, d)})


def _dossier(d: Path) -> str:
    f = d / "dossier.md"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def _build_video(item: dict, d: Path, script: Script, hook: HookReview) -> tuple[Path, list[float], Path | None, str]:
    """Voice, atlas picture and mix, and (long form) thumbnail; every step cached, so a fix only redoes what it
    touched."""
    return _build_atlas(item, d, script, hook)


HERO_CLIP = "assets/broll/hero_ph_push.mp4"   # approved 3D push into Metro Manila (same in every episode)


ATLAS_CARD = {"map": "map", "doc": "document", "cards": "stat", "bars": "bars", "timeline": "timeline",
              "globe": "map", "checklist": "quote", "linechart": "stat", "barchart": "bars", "waffle": "stat",
              "balance": "bars", "dates": "timeline", "media": "none"}       # values must be Shot.card_type literals


def _atlas_describe(s: dict) -> str:
    k = s["k"]
    if k == "broll":
        what = "3D map push into Metro Manila" if s.get("src") == "assets/hero.mp4" else f"real photo ({s.get('credit', '')})"
        return f"{what} with a red label '{s.get('word', '')}'"
    if k == "map":
        return f"paper map, view {s.get('view', 'ph')}" + (f", label '{s['label']}'" if s.get("label") else "")
    if k == "doc":
        return f"document on paper: {s.get('head', '')} {s.get('sec', '')}, highlighted {s.get('hl', [])}"
    if k in ("cards", "bars", "timeline", "seats"):
        return f"{k}: " + "; ".join(" ".join(str(v) for v in it.values() if v) for it in s.get("items", []))
    if k == "compare":
        return f"compare card: {s.get('ph', {})} vs {s.get('nz', {})}"
    stamp = f", stamp '{s['stamp'].get('text', '')}'" if s.get("stamp") else ""
    if k == "globe":
        return (f"line globe turning to {', '.join(h.get('name', h.get('iso', '')) for h in s.get('highlight', [])) or 'the region'}"
                f"; dots {[p.get('name', '') for p in s.get('places', [])]}; routes {[a.get('names', []) for a in s.get('arcs', [])]}"
                + stamp)
    if k == "checklist":
        return "checklist: " + "; ".join(f"{i.get('text', '')} ({i.get('mark', 'tick')})" for i in s.get("items", [])) + stamp
    if k in ("linechart", "barchart", "waffle", "balance", "dates"):
        vals = "; ".join(" ".join(str(v) for kk, v in it.items() if kk in ("label", "value", "big", "small") and v)
                         for it in s.get("items", []))
        return f"{k}: {s.get('head', '')} {s.get('big', '')} {vals} {s.get('callout', '')}".strip() + stamp
    if k == "media":
        what = f"photo card ({s.get('credit', '')})" if s.get("src") else f"drawn {s.get('icon', 'icon')} card"
        return (f"{what} '{s.get('name', '')}'; side list {[r.get('text', '') for r in s.get('rows', [])]}; "
                f"chips {[c.get('text', '') for c in s.get('chips', [])]}") + stamp
    return f"{k}: {s.get('text') or s.get('left', '')} {s.get('right', '')}".strip() + stamp


def _atlas_shotlist(script: Script, starts: list[float], total: float, shots: list[dict]) -> ShotList:
    """The review team's view of an atlas video: per scene, what its shots are meant to show."""
    from .models import Shot

    bounds = list(starts) + [total]
    out = []
    for i, sc in enumerate(script.scenes):
        mine = [s for s in shots if (0.0 if i == 0 else bounds[i]) - 0.01 <= s["t0"] < bounds[i + 1]]   # the opener starts at 0.0 s
        first = mine[0]["k"] if mine else "map"
        out.append(Shot(scene_id=sc.id, kind="card", style="story", image_prompt="",
                        card_type=ATLAS_CARD.get(first, "none"),
                        card_title=" | then ".join(_atlas_describe(s) for s in mine)[:330] or "paper map",
                        card_lines=[], reuse_of_scene=0, motion="static"))
    return ShotList(shots=out)


def _atlas_video(item: dict, d: Path, script: Script, size: tuple[int, int]) -> tuple[list[float], list[dict]]:
    """Style v2: narrator -> Atlas Designer -> licensed photos -> HyperFrames picture -> SFX and music mix ->
    master -14 LUFS -> mux. Captions are drawn by the runtime. Returns (scene starts, shots)."""
    import subprocess

    import numpy as np

    from .config import ROOT
    from .media import atlas, atlas_plan, broll_pick, sfx_v2
    from .models import AtlasPlan

    kind = item["kind"]
    vertical = size[1] > size[0]
    work = d / "work"
    work.mkdir(parents=True, exist_ok=True)
    vcfg = channel()["tts"].get("voxcpm", {})              # local GPU first, Modal after this deadline
    deadline = datetime.fromisoformat(item["anchor_at"]) - timedelta(hours=float(vcfg.get("local_until_hours_before_slot", 5)))
    if item["id"].startswith("sample-"):                     # dry runs never wait for the local GPU
        deadline = now()
    clips = tts.synthesize(_voiced(script, d), d / "audio", item=item["id"], deadline=deadline)
    voice, starts, total, chapter_cards = atlas_plan.assemble(clips, script.scenes, kind)
    fixes = _fixes(d)                                 # review-team notes on a finished render re-plan the whole video
    done = fixes.setdefault("replanned", {})
    pending = {k: n for k, n in fixes["images"].items()
               if k.isdigit() and fixes["attempts"].get(k, 0) > done.get(k, 0)}
    notes = "".join(f"\n- scene {k}: {n}" + (" (failed twice: use only a map or a bigtext card)"
                                              if k in fixes["drop"] else "") for k, n in sorted(pending.items()))
    if pending:
        (d / "atlas.json").unlink(missing_ok=True)
        done.update({k: fixes["attempts"][k] for k in pending})
        (d / "qa_fixes.json").write_text(json.dumps(fixes, ensure_ascii=False, indent=1), encoding="utf-8")
    plan = cached(d / "atlas.json", AtlasPlan,
                  lambda: packaging.atlas_plan(item, script, _dossier(d), vertical, notes=notes))
    # plan QC (Atlas blocks v3): no scene family on screen longer than MAX_FAMILY_RUN seconds, and every chart's plotted
    # numbers agree with its printed figures (a debt Short once showed a chart that disagreed with its headline). Checked
    # on a dry pass (every photo assumed found) before any photo is fetched; a failing plan is re-planned once.
    dry = atlas_plan.to_shots(plan, script.scenes, clips, starts, total, kind,
                              lambda q, w, a, b: {"kind": "photo", "src": "dry.jpg", "credit": ""}, None)
    problems = atlas_plan.variety_problems(dry) + atlas_plan.chart_problems(dry)
    if problems and not fixes.get("variety_replanned"):
        log.warning("atlas %s: variety QC failed, re-planning once: %s", item["id"], problems)
        fixes["variety_replanned"] = problems
        (d / "qa_fixes.json").write_text(json.dumps(fixes, ensure_ascii=False, indent=1), encoding="utf-8")
        (d / "atlas.json").unlink(missing_ok=True)
        vnotes = notes + "".join(f"\n- whole video, variety: {p}" for p in problems)
        plan = cached(d / "atlas.json", AtlasPlan,
                      lambda: packaging.atlas_plan(item, script, _dossier(d), vertical, notes=vnotes))
    picker = broll_pick.Picker(d, item["id"])
    hero = {"k": "broll", "kind": "video", "src": "assets/hero.mp4", "credit": ""} if kind == "long_form" else None
    shots = sorted(atlas_plan.to_shots(plan, script.scenes, clips, starts, total, kind, picker, hero) + chapter_cards,
                   key=lambda s: s["t0"])
    assets = dict(picker.assets)
    if any(s.get("src") == "assets/hero.mp4" for s in shots):
        assets["assets/hero.mp4"] = ROOT / HERO_CLIP
    (d / "atlas_shots.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "shots.json").write_text(_atlas_shotlist(script, starts, total, shots).model_dump_json(indent=1),
                                  encoding="utf-8")       # what the review team expects each scene to show
    words = atlas_plan.mark_keys(atlas_plan.caption_words(clips, starts), plan, script.scenes, starts, total, shots)
    (d / "atlas_qc.json").write_text(json.dumps({
        "families": atlas_plan.family_runs(shots), "variety_problems": atlas_plan.variety_problems(shots),
        "builds": [[s["k"], s["t0"], atlas_plan.builds(s)] for s in shots],
        "key_words": [w["w"] for w in words if w.get("key")]}, ensure_ascii=False, indent=1), encoding="utf-8")
    sp = atlas.spec(item["id"].replace(".", "-"), size, shots, words, total)
    picture = work / "picture.mp4"
    atlas.render(sp, work, picture, assets)
    if kind == "long_form":                          # thumbnail art: the hero push (else the first photo) without captions
        pick = next((x for x in shots if x.get("src") == "assets/hero.mp4"), None) or             next((x for x in shots if x.get("k") == "broll"), None)
        if pick:
            try:
                t = round(pick["t0"] + 0.8 * (pick["t1"] - pick["t0"]), 2)
                [png] = atlas.snapshot(dict(sp, words=[]), work, [t], work / "thumb_snap", assets)
                shutil.copy(png, d / "thumb_art.png")
            except Exception:
                log.exception("thumbnail snapshot failed; using a frame of the video")
    mixed, report = sfx_v2.mix(voice.astype(np.float32), shots, total)
    raw, mastered = work / "mix_raw.wav", work / "mix.wav"
    sfx_v2.write_wav(raw, mixed)
    lufs, peak = sfx_v2.master(raw, mastered)
    report.update(lufs=lufs, peak=peak, licence_problems=picker.problems())
    (d / "sound_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str),
                                         encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(picture), "-i", str(mastered), "-map", "0:v",
                    "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(d / "video.mp4")],
                   check=True)
    render.srt(clips, starts, d / "captions.srt")
    log.info("atlas %s: %d shots, %d photos, %.1f LUFS, peak %.1f, sfx p10 %.1f dB", item["id"], len(shots),
             len(picker.assets), lufs, peak, report.get("voice_over_sfx_db_p10") or 0)
    return starts, shots


def _build_atlas(item: dict, d: Path, script: Script, hook: HookReview) -> tuple[Path, list[float], Path | None, str]:
    import subprocess

    kind = item["kind"]
    vcfg = channel()["video"]["long_form" if kind == "long_form" else "vertical"]
    size = (vcfg["width"], vcfg["height"])
    video, starts_file, shots_file = d / "video.mp4", d / "starts.json", d / "atlas_shots.json"
    if not video.exists():
        starts, _ = _atlas_video(item, d, script, size)
        starts_file.write_text(json.dumps(starts))
    starts = json.loads(starts_file.read_text())
    thumb_path, thumb_moment = None, "(no custom thumbnail)"
    if kind == "long_form":
        plan = cached(d / "thumbnails.json", ThumbnailPlan, lambda: packaging.thumbnails(item, script))
        best = plan.concepts[0]
        thumb_moment = best.moment
        art = d / "thumb_art.png"
        if not art.exists():                          # the strongest real frame: the hero push, else the first photo
            shots = json.loads(shots_file.read_text(encoding="utf-8"))
            pick = next((s for s in shots if s.get("src") == "assets/hero.mp4"), None) or \
                next((s for s in shots if s.get("k") == "broll"), shots[0])
            t = round(pick["t0"] + 0.8 * (pick["t1"] - pick["t0"]), 2)
            art.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1",
                            str(art)], check=True)
        thumb_path = d / "thumbnail.jpg"
        if not thumb_path.exists():
            compose.thumbnail(art, best.overlay_text, thumb_path)
    return video, starts, thumb_path, thumb_moment


AUDIO_EXTRA_ROUNDS = 2  # extra re-voice rounds when only the narration still has a major problem
MAX_IMAGE_ATTEMPTS = 1   # regenerate a failing shot once; if it fails again it is replaced (never sinks the video)


def _save_fixes(d: Path, report: ReviewReport) -> list[str]:
    """Record the review's corrections. Returns the image keys to regenerate (the rest were dropped)."""
    fixes = _fixes(d)
    regenerate = []
    for key, prompt in report.redo_images.items():
        fixes["attempts"][key] = fixes["attempts"].get(key, 0) + 1
        if fixes["attempts"][key] > MAX_IMAGE_ATTEMPTS and key != "thumbnail":
            if key not in fixes["drop"]:
                fixes["drop"].append(key)
            log.info("shot %s failed review %d times: replaced by a neighbouring illustration", key,
                     fixes["attempts"][key] - 1)
        else:
            fixes["images"][key] = prompt
            regenerate.append(key)
    fixes["audio"].update({k: v for k, v in report.redo_audio.items() if v})
    (d / "qa_fixes.json").write_text(json.dumps(fixes, ensure_ascii=False, indent=1), encoding="utf-8")
    return regenerate


def _apply_video_fixes(d: Path, report: ReviewReport) -> None:
    import shutil

    for key in _save_fixes(d, report):
        if key == "thumbnail":
            for t in (d / "thumb_art.png", d / "thumbnail.jpg"):
                t.unlink(missing_ok=True)
    for key in report.redo_audio:
        for ext in (".mp3", ".json"):
            (d / "audio" / f"{int(key):03d}{ext}").unlink(missing_ok=True)
    if any(k != "thumbnail" for k in report.redo_images) or report.redo_audio:
        for f in (d / "video.mp4", d / "starts.json"):
            f.unlink(missing_ok=True)
        shutil.rmtree(d / "work", ignore_errors=True)


def _reviewed(item: dict, d: Path, build: Callable[[], T], review: Callable[[T], ReviewReport],
              fix: Callable[[ReviewReport], None]) -> tuple[T, ReviewReport | None] | None:
    """Build → review → fix, up to max_fix_rounds. Returns (build result, final report), or None if skipped."""
    rounds = qa.cfg().get("max_fix_rounds", 2) if qa.enabled() else 0
    history: list[ReviewReport] = []

    def repeated_major() -> bool:          # balanced: a one-off narration flag never blocks
        return len(history) >= 2 and bool(set(history[-2].major_scenes) & set(history[-1].major_scenes))

    for rnd in range(rounds + 1):
        built = build()
        if not qa.enabled():
            return built, None
        report = cached(d / f"qa_r{rnd}.json", ReviewReport, lambda: qa.safe(review, built))
        history.append(report)
        log.info("review r%d %s: %s", rnd, item["id"], report.summary)
        if report.passed:
            return _polish(item, d, build, review, fix, built, report)
        if rnd < rounds:
            fix(report)
    extra = rnd
    while repeated_major() and not report.redo_images and extra < rounds + AUDIO_EXTRA_ROUNDS:
        extra += 1                         # visuals are fine; the same line keeps failing: another take
        fix(report)
        built = build()
        report = cached(d / f"qa_r{extra}.json", ReviewReport, lambda: qa.safe(review, built))
        history.append(report)
        log.info("review r%d (voice only) %s: %s", extra, item["id"], report.summary)
        if report.passed:
            return built, report
    if not report.redo_images and not repeated_major():
        log.info("review %s: accepted with notes after %d rounds (no repeated narration problem)", item["id"], rounds)
        return built, report
    problems = "; ".join(report.warnings[:6])
    db.set_status(item["id"], "skipped", f"failed review after {rounds} fix rounds: {problems}"[:2000])
    notify.send(f"⛔ {item['id']} skipped by the review team after {rounds} fix rounds:\n{problems}")
    return None


def _polish(item: dict, d: Path, build: Callable[[], T], review: Callable[[T], ReviewReport],
            fix: Callable[[ReviewReport], None], built: T, report: ReviewReport) -> tuple[T, ReviewReport]:
    """A piece that passed but looks ordinary (appeal below `min_appeal`) gets one improvement pass on the frames
    the reviewers had notes on. The pass is kept only if it still passes review; appeal never blocks a post."""
    cfg = qa.cfg()
    if not report.improve or not report.appeal or report.appeal >= cfg.get("min_appeal", 7) \
            or (d / "qa_polish.json").exists():
        return built, report
    targets = dict(sorted(report.improve.items(), key=lambda kv: -len(kv[1]))[:cfg.get("polish_max_frames", 5)])
    log.info("polish %s: appeal %d/10, improving %s", item["id"], report.appeal, sorted(targets))
    snapshot = _snapshot(d)                           # the reviewed version, restored if the pass goes wrong
    try:
        fix(report.model_copy(update={"redo_images": targets, "redo_audio": {}}))
        polished = build()
        after = cached(d / "qa_polish.json", ReviewReport, lambda: qa.safe(review, polished))
    except UsageLimitError:
        _restore(d, snapshot)
        raise
    except Exception:
        log.exception("polish pass failed; posting the reviewed version")
        _restore(d, snapshot)
        return built, report
    keep = after.passed and after.appeal >= report.appeal
    log.info("polish %s: appeal %d -> %d/10, %s", item["id"], report.appeal, after.appeal,
             "kept" if keep else "reverted to the reviewed version")
    if keep:
        shutil.rmtree(snapshot, ignore_errors=True)
        return polished, after
    _restore(d, snapshot)
    return built, report


POLISH_SKIP = ("work", "work_thumb", "qa_frames", "critic", "audio")   # big or unchanged by a polish pass


def _snapshot(d: Path) -> Path:
    snap = d.parent / f"{d.name}.prepolish"
    shutil.rmtree(snap, ignore_errors=True)
    shutil.copytree(d, snap, ignore=lambda folder, names: [n for n in names if Path(folder) == d and
                                                           (n in POLISH_SKIP or n.startswith("work_"))])
    return snap


def _restore(d: Path, snap: Path) -> None:
    """Put the snapshot's files back (the polish pass's replacements are overwritten)."""
    for src in snap.rglob("*"):
        if src.is_file():
            dst = d / src.relative_to(snap)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    shutil.rmtree(snap, ignore_errors=True)


def _qa_note(report: ReviewReport | None) -> dict:
    if not report:
        return {}
    return {"qa": {"summary": report.summary, "appeal": report.appeal, "hook_frame": report.hook_frame,
                   "warnings": report.warnings[:10]}}


def _produce_video(item: dict, d: Path, dossier: str) -> None:
    kind = item["kind"]
    result = _script(item, d, dossier)
    if not result:
        return
    script, hook = result
    fc = cached(d / "factcheck.json", FactCheck,
                lambda: writers.fact_check(script, dossier, kind, hook.on_screen_hook_text))
    if not _gate(item, fc):
        return
    if fc.on_screen_hook_text.strip():                                     # the checked version goes on screen
        hook = hook.model_copy(update={"on_screen_hook_text": fc.on_screen_hook_text.strip()})
    script = cached(d / "narration.json", Script, lambda: writers.narration_edit(fc.script))  # read-aloud safe

    def review(built) -> ReviewReport:
        video, starts, thumb, _ = built
        shots = ShotList.model_validate_json((d / "shots.json").read_text(encoding="utf-8"))
        dropped = {int(k) for k in _fixes(d)["drop"] if k.isdigit()}
        reused = {s.scene_id for s in shots.shots
                  if s.scene_id in dropped or (s.kind == "reuse" and s.reuse_of_scene in dropped)}
        return qa.review_video(kind, d, _voiced_script(script, d), shots, starts, video, thumb,
                               hook.on_screen_hook_text, reused)

    done = _reviewed(item, d, lambda: _build_video(item, d, script, hook), review,
                     lambda report: _apply_video_fixes(d, report))
    if not done:
        return
    (video, starts, thumb_path, thumb_moment), report = done
    titles = cached(d / "titles.json", TitlePlan, lambda: packaging.titles(item, script, thumb_moment))
    chapters = render.chapters(script.scenes, starts) if kind == "long_form" else []
    cached(d / "seo.json", SeoPack, lambda: packaging.seo(item, script, titles.primary, chapters))

    _schedule(item, title=titles.primary, video=str(video), thumbnail=str(thumb_path or ""), **_qa_note(report))


PLATFORM_LABEL = {"youtube": "YouTube", "youtube_shorts": "YT Shorts", "instagram_reel": "IG Reel",
                  "instagram_carousel": "IG Carousel", "facebook_reel": "FB Reel", "facebook_post": "FB Post", "facebook_video": "FB Video",
                  "tiktok": "TikTok", "tiktok_carousel": "TikTok Photos", "threads_carousel": "Threads"}


def _schedule(item: dict, **artifacts) -> None:
    from . import archive

    if item["data"].get("sample"):                # `tfs sample`: finished, but never queued for posting
        db.set_status(item["id"], "sample", **artifacts)
        return
    try:                                          # the schedule may have changed since this piece was planned
        platforms = {p: db.iso(t) for p, t in slots.unit_by_id(item["id"]).platforms.items()}
        item["data"]["platforms"] = platforms
        artifacts["platforms"] = platforms
    except (StopIteration, ValueError):
        platforms = item["data"]["platforms"]
    for platform, slot in platforms.items():
        if _connected(platform):
            db.queue_post(item["id"], platform, slot)
        else:
            log.info("%s: %s isn't connected yet; not queued", item["id"], platform)
    db.set_status(item["id"], "scheduled", **artifacts)
    log.info("scheduled %s", item["id"])
    _notify_ready(db.get_item(item["id"]))
    archive.archive_item(db.get_item(item["id"]))  # permanent copy in B2 (never blocks posting)
    from . import render_archive                  # final render in the shared studio archive (never blocks posting)
    render_archive.archive_item(db.get_item(item["id"]))


def _connected(platform: str) -> bool:
    """Platforms added before their account is connected are skipped instead of failing every day."""
    if platform == "threads_carousel":
        return bool(env("THREADS_ACCESS_TOKEN") or (data_dir() / "threads_token.json").exists())
    return True


def _notify_ready(item: dict) -> None:
    """Telegram: the finished post itself (thumbnail / video / slides) + where and when it goes out."""
    data = item["data"]
    when = "\n".join(f"• {PLATFORM_LABEL.get(p, p)} — {datetime.fromisoformat(t).strftime('%a %d %b, %H:%M')} PHT"
                     for p, t in sorted(data["platforms"].items(), key=lambda kv: kv[1]))
    caption = f"✅ Ready: {data.get('title') or data.get('working_title')}\n{item['kind'].replace('_', ' ')}\n{when}"
    if data.get("qa"):
        caption += f"\n🔎 Review: {data['qa']['summary']}"
        notes = [w for w in data["qa"].get("warnings", []) if w.startswith("voice")][:3]
        if notes:
            caption += "\n⚠️ Notes:\n• " + "\n• ".join(n[:160] for n in notes)
            caption += f"\nTo pull this post: GitHub → Actions → hold → item {item['id']}"
    if item["kind"] == "carousel":
        notify.send_photos([media(p) for p in data.get("slides", [])], caption)
    elif item["kind"] == "vertical":
        notify.send_video(media(data["video"]), caption)
    else:
        thumb = media(data["thumbnail"]) if data.get("thumbnail") else None
        notify.send_photos([thumb] if thumb else [], caption)


def _post_link(platform: str, remote_id: str) -> str:
    if platform in ("youtube", "youtube_shorts"):
        return f"https://youtu.be/{remote_id}"
    if platform in ("facebook_reel", "facebook_post", "facebook_video"):
        return f"https://www.facebook.com/{remote_id}"
    if platform in ("instagram_reel", "instagram_carousel"):
        return "https://www.instagram.com/thefilipinostandard/"
    if platform == "threads_carousel":
        from .publish import threads
        return threads.permalink(remote_id) or "https://www.threads.com/@thefilipinostandard"
    return ""


def _notify_live(post: dict, remote_id: str) -> None:
    item = db.get_item(post["item_id"])
    title = item["data"].get("title") or item["data"].get("working_title", "")
    notify.send(f"🟢 Live on {PLATFORM_LABEL.get(post['platform'], post['platform'])}: {title}\n"
                f"{_post_link(post['platform'], remote_id)}")


def _alert_once(key: str, text: str, hours: int = 6) -> None:
    """Telegram alert at most once per `hours` for the same kind of problem (marker file travels with the state)."""
    marker = data_dir() / f"alert_{key}.txt"
    if marker.exists() and now() - datetime.fromisoformat(marker.read_text().strip()) < timedelta(hours=hours):
        return
    notify.send(text)
    marker.write_text(now().isoformat(timespec="seconds"))


def produce(item_id: str) -> bool:
    """Returns False when the item is waiting (local narration, paused kind), so the run moves on to the next one."""
    item = db.get_item(item_id)
    if item["kind"] in paused_kinds():
        log.info("%s: %s production is paused; left as it is", item_id, item["kind"])
        return False
    d = item_dir(item_id)
    try:
        dossier = cached_text(d / "dossier.md", lambda: writers.research(item))
        if item["kind"] == "carousel":                # no style v2 carousel design yet (paused_kinds covers this)
            log.info("%s: carousels have no style v2 design yet; left as it is", item_id)
            return False
        _produce_video(item, d, dossier)
    except VoiceDeferred as e:                       # the local GPU worker has the narration; try again next run
        log.info("waiting for local narration: %s", e)
        return False
    except UsageLimitError as e:
        log.warning("usage limit reached; %s will retry on the next run (%s)", item_id, e)
        _alert_once("limit", f"⏸️ Production paused: {str(e)[:300]}\n"
                    "Items are kept and retried every run; nothing broken is posted. "
                    "Top up / upgrade and it resumes by itself.")
    except Exception as e:
        log.exception("production failed for %s", item_id)
        db.set_status(item_id, "failed", str(e)[:2000])
        notify.send(f"❌ Production failed: {item_id}: {e}")
    return True


# ---------------------------------------------------------------- publishing
def _provider(platform: str) -> str:
    cfg = channel()["publishing"]
    return cfg.get("overrides", {}).get(platform, cfg["provider"])


def _due(post: dict) -> bool:
    if _provider(post["platform"]) == "postforme":
        return True                       # submitted right away; Post for Me releases it at scheduled_at
    if post["platform"] in ("youtube", "youtube_shorts"):
        return True                       # uploaded right away, YouTube itself releases it at publishAt
    return datetime.fromisoformat(post["slot_at"]) <= now()


def _publish_one(post: dict) -> tuple[str, str]:
    """Returns (status, remote_id). `submitted` = accepted by Post for Me, confirmed later by reconcile()."""
    item = db.get_item(post["item_id"])
    d, data = item_dir(item["id"]), item["data"]
    from .publish import limits
    from .publish.limits import enforce_seo
    seo = enforce_seo(SeoPack.model_validate_json((d / "seo.json").read_text(encoding="utf-8")))
    slot = datetime.fromisoformat(post["slot_at"])
    video = media(data["video"]) if data.get("video") else None
    slides = [media(p) for p in data.get("slides", [])]
    platform = post["platform"]
    caption = {"youtube": seo.youtube_description, "youtube_shorts": seo.youtube_description,
               "instagram_reel": seo.instagram_caption, "instagram_carousel": seo.instagram_caption,
               "facebook_reel": seo.facebook_caption, "facebook_post": seo.facebook_caption,
               "facebook_video": seo.facebook_caption,
               "tiktok": seo.tiktok_caption, "tiktok_carousel": seo.tiktok_caption,
               "threads_carousel": limits.threads_text(seo.instagram_caption)}[platform]
    title = (data["title"] if platform in ("youtube", "facebook_video") else limits.tiktok_photo_title(data.get("title") or "")
             if platform == "tiktok_carousel" else seo.shorts_title)

    if _provider(platform) == "postforme":
        from .publish import postforme
        files = slides if platform in ("instagram_carousel", "facebook_post", "tiktok_carousel") else [video]
        thumb = media(data["thumbnail"]) if platform == "youtube" and data.get("thumbnail") else None
        pid = postforme.create_post(platform, caption, files, slot, title=title, description=caption,
                                    tags=seo.tags, thumbnail=thumb, external_id=f"{item['id']}:{platform}")
        return "submitted", pid

    from .publish import meta, tiktok, youtube
    match platform:
        case "youtube" | "youtube_shorts":
            thumb = media(data["thumbnail"]) if data.get("thumbnail") else None
            # "submitted" until reconcile() confirms YouTube actually made it public at the slot
            return "submitted", youtube.upload(video, title, caption, seo.tags, slot, thumb)
        case "instagram_reel":
            return "published", meta.ig_reel(video, caption)
        case "facebook_reel":
            return "published", meta.fb_reel(video, caption)
        case "facebook_video":
            return "published", meta.fb_video(video, title, caption)
        case "tiktok":
            return "published", tiktok.post_video(video, caption)
        case "instagram_carousel":
            return "published", meta.ig_carousel(slides, caption)
        case "facebook_post":
            return "published", meta.fb_photos(slides, caption)
        case "threads_carousel":
            from .publish import threads
            return "published", threads.carousel(slides, caption)
    raise ValueError(f"unknown platform {platform}")


def _confirm_youtube(post: dict, late: timedelta) -> None:
    """A direct upload is only 'published' once YouTube reports it public. If it's still private well after
    its publishAt, YouTube has most likely locked it (unaudited API project) — alert instead of assuming."""
    from .publish import youtube

    status = youtube.video_status(post["remote_id"])
    if status.get("privacyStatus") == "public":
        db.finish_post(post["id"], "published", post["remote_id"])
        _notify_live(post, post["remote_id"])
    elif late > timedelta(hours=2):
        db.finish_post(post["id"], "failed", post["remote_id"], f"still {status.get('privacyStatus')} after slot")
        notify.send(f"⚠️ YouTube video {post['remote_id']} ({post['item_id']}) is still "
                    f"{status.get('privacyStatus')} 2h after its slot — check YouTube Studio for a 'Locked' notice. "
                    f"If YouTube is locking API uploads, set publishing.overrides.youtube: postforme.")


def reconcile() -> None:
    """Confirm posts whose slot has passed; record the platform's own id for analytics."""
    from .publish import postforme

    for post in db.posts_with_status("submitted"):
        late = now() - datetime.fromisoformat(post["slot_at"])
        if late < timedelta(minutes=20):
            continue
        if _provider(post["platform"]) == "direct" and post["platform"].startswith("youtube"):
            _confirm_youtube(post, late)
            continue
        res = postforme.results(post["remote_id"], post["platform"])
        if not res:
            if late > timedelta(hours=3):
                db.finish_post(post["id"], "failed", post["remote_id"], "no result from Post for Me after 3h")
                notify.send(f"❌ {post['item_id']} → {post['platform']}: no result from Post for Me")
            continue
        r = res[0]
        if r.get("success"):
            live_id = (r.get("platform_data") or {}).get("id") or post["remote_id"]
            db.finish_post(post["id"], "published", live_id)
            _notify_live(post, live_id)
        else:
            db.finish_post(post["id"], "failed", post["remote_id"], str(r.get("error")))
            notify.send(f"❌ Publish failed: {post['item_id']} → {post['platform']}: {r.get('error')}\n"
                        f"Retry: GitHub → Actions → retry → {post['id']}")


def publish_due() -> int:
    with _publishing:
        return _publish_due()


def _publish_due() -> int:
    done = 0
    for post in db.queued_posts():
        if not _due(post):
            continue
        if now() - datetime.fromisoformat(post["slot_at"]) > timedelta(hours=6):
            db.finish_post(post["id"], "skipped", error="missed slot by >6h")
            continue
        try:
            status, remote_id = _publish_one(post)
            db.finish_post(post["id"], status, remote_id)
            if status == "published":
                _notify_live(post, remote_id)
            done += 1
            log.info("%s %s → %s (%s)", status, post["item_id"], post["platform"], remote_id)
        except Exception as e:
            log.exception("publish failed")
            db.finish_post(post["id"], "failed", error=str(e))
            notify.send(f"❌ Publish failed: {post['item_id']} → {post['platform']}: {e}\n"
                        f"Retry: GitHub → Actions → retry → {post['id']}")
    try:
        reconcile()
    except Exception:
        log.exception("reconcile failed")
    return done


# ---------------------------------------------------------------- scheduler tick
def plan_upcoming() -> list[str]:
    if not slots.is_live():                          # schedule master switch (config/schedule.yaml `live`)
        return []
    horizon = now() + timedelta(hours=schedule()["production_lead_hours"] + 2)
    today = now().date()
    units = [u for day in (today, today + timedelta(days=1)) for u in slots.day_units(day)
             if now() < u.anchor <= horizon and not db.get_item(u.id)]
    return editor.plan(units) if units else []


def expire_stale() -> None:
    for item in db.items_with_status("planned", "awaiting_approval", "failed"):
        if datetime.fromisoformat(item["anchor_at"]) <= now():
            db.set_status(item["id"], "skipped", item.get("error") or "not ready by first slot")
            notify.send(f"⏭️ {item['id']} skipped — not ready by {item['anchor_at']}.")


def tick(max_produce: int = 1) -> None:
    last = db.last_scout_at()
    if not last or now() - datetime.fromisoformat(last) > SCOUT_EVERY:
        try:
            trend_scout.run()
        except Exception as e:  # keep producing from the existing pool / evergreen ideas
            log.exception("trend scout failed")
            notify.send(f"⚠️ Trend scout failed: {e}")
    plan_upcoming()
    expire_stale()
    done = 0
    for item in [i for i in db.items_with_status("planned", "approved") if i["kind"] not in paused_kinds()]:
        if done >= max_produce:
            break
        done += 1 if produce(item["id"]) else 0       # an item waiting for local narration does not block the queue


# ---------------------------------------------------------------- one GitHub Actions run
def _next_timed_post() -> datetime | None:
    """Earliest queued post that has to go out at its exact slot (Meta direct: no platform-side scheduling)."""
    return min((datetime.fromisoformat(p["slot_at"]) for p in db.queued_posts() if not _due(p)), default=None)


def _analysis_due() -> bool:
    """Mondays from 09:00 PHT, once; catches up if a whole Monday was missed."""
    marker = data_dir() / "last_analysis.txt"
    last = datetime.fromisoformat(marker.read_text().strip()) if marker.exists() else None
    t = now()
    if last and t - last > timedelta(days=8):
        return True
    return t.weekday() == 0 and t.hour >= 9 and (not last or last.date() != t.date())


def _weekly_analysis() -> None:
    if not _analysis_due():
        return
    from .agents import analyst
    try:
        analyst.run()
    except UsageLimitError as e:
        log.warning("analysis postponed: %s", e)
        return
    except Exception as e:
        log.exception("weekly analysis failed")
        notify.send(f"⚠️ Weekly analysis failed: {e}")
    (data_dir() / "last_analysis.txt").write_text(now().isoformat(timespec="seconds"))


def _owner_requests() -> bool:
    """Make and publish any post-now requests waiting in R2. Returns True if one was handled."""
    from . import post_now, state
    try:
        requests_ = state.take_requests()
    except Exception:
        log.exception("could not read owner requests")
        return False
    for req in requests_:
        if req.get("type") != "post-now":
            continue
        try:
            result = post_now.make(req.get("kind", "carousel"), req.get("topic", ""), req.get("note", ""))
            log.info("post-now: %s", result)
        except UsageLimitError:
            state.add_request(req)                   # try again once the usage window reopens
            raise
        except Exception as e:
            log.exception("post-now request failed")
            notify.send(f"❌ Post-now request failed: {req.get('topic', '')[:120]}: {e}")
    return bool(requests_)


def _creative_review() -> None:
    """Creative Director, twice a day: recurring review notes become standing notes for the designers."""
    from .agents import creative
    if not creative.due():
        return
    try:
        creative.run()
    except UsageLimitError:
        raise
    except Exception:
        log.exception("creative director failed; trying again next pass")


def _archive_pending() -> None:
    """Retry B2 archiving for finished items this run has on disk (uploads only what's missing)."""
    from . import archive, render_archive

    for item in db.items_with_status("scheduled"):
        if not (item_dir(item["id"]) / "seo.json").exists():
            continue
        if archive.enabled():
            archive.archive_item(item)
        if render_archive.enabled():               # catches up anything published before the key existed
            render_archive.archive_item(item)


def cloud_run(budget: timedelta = timedelta(hours=4)) -> None:
    """Everything one triggered run does, with state restored from and saved back to R2.

    A background thread publishes every minute for the whole run, so a long render never delays a post.
    Runs never overlap (workflow concurrency group); a trigger that arrives mid-run just waits.
    """
    from . import state

    if not state.enabled():   # without saved state every run would re-plan and re-post the same slots
        raise SystemExit("run: no R2 state bucket configured (S3_* secrets) — refusing to run")
    state.pull()
    stop = threading.Event()

    def publisher() -> None:
        while not stop.wait(PUBLISH_EVERY):
            try:
                if publish_due():
                    state.push()
            except Exception:
                log.exception("publisher thread")

    thread = threading.Thread(target=publisher, name="publisher", daemon=True)
    thread.start()
    started, tried, last_tick = now(), set(), None
    try:
        publish_due()
        state.push()
        while now() - started < HARD_STOP:
            if not last_tick or now() - last_tick >= timedelta(minutes=30):
                _weekly_analysis()
                _creative_review()
                tick(max_produce=0)                  # scout if stale, plan upcoming slots, expire stale
                state.push()
                last_tick = now()
            if _owner_requests():                    # post-now requests jump the queue, between pieces
                continue
            todo = [i for i in db.items_with_status("planned", "approved")
                    if i["id"] not in tried and i["kind"] not in paused_kinds()]
            if todo and now() - started < budget:
                tried.add(todo[0]["id"])
                produce(todo[0]["id"])
                state.push()
                continue
            nxt = _next_timed_post()
            if not nxt or nxt - now() > LINGER:
                break
            time.sleep(min(60.0, max(5.0, (nxt - now()).total_seconds())))
        publish_due()
    finally:
        stop.set()
        thread.join(timeout=600)
        _archive_pending()
        state.push()
        state.daily_backup()
        try:
            state.prune()
        except Exception:
            log.exception("prune failed")
