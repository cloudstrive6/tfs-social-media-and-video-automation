"""Orchestrator. Every step writes its artifact to data/items/<id>/ and is skipped if the artifact
exists, so a crashed or approval-paused item resumes exactly where it stopped."""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, TypeVar

from pydantic import BaseModel

from . import db, notify, qa, slots
from .agents import editor, packaging, trend_scout, writers
from .config import channel, data_dir, item_dir, media, now, schedule
from .llm import UsageLimitError
from .media import cards, compose, images, render, tts
from .models import (Carousel, FactCheck, HookReview, ReviewReport, Scene, Script, SeoPack, ShotList,
                     ThumbnailPlan, TitlePlan)

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
        n, limit = writers.spoken_words(hook.script), writers.max_words(item["kind"])
        if n > limit * 1.08:
            feedback = (f"TOO LONG: {n} spoken words; the hard limit is {limit}. Cut to {limit} words or fewer: "
                        "one idea, no second example, shortest possible setup.\n" + "\n".join(hook.fixes))
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


def _checked_shots(item: dict, script: Script, draft: ShotList, dossier: str) -> ShotList:
    try:
        checked = packaging.preflight_shots(item, script, draft, dossier)
    except UsageLimitError:
        raise
    except Exception:
        log.exception("pre-flight art check failed; using the Visual Director's list as is")
        return draft
    if sorted(s.scene_id for s in checked.shots) != sorted(s.scene_id for s in draft.shots):
        log.warning("pre-flight returned different scene ids; using the draft")
        return draft
    return checked


def _visuals(item: dict, d: Path, script: Script, aspect: str, size: tuple[int, int]) -> list[render.Shot]:
    shots_file = d / "shots.json"
    if shots_file.exists():
        shot_list = ShotList.model_validate_json(shots_file.read_text(encoding="utf-8"))
    else:
        draft = cached(d / "shots_draft.json", ShotList, lambda: packaging.shot_list(item, script))
        dossier_file = d / "dossier.md"
        dossier = dossier_file.read_text(encoding="utf-8") if dossier_file.exists() else ""
        shot_list = cached(shots_file, ShotList,                   # pre-flight: fix before anything is drawn
                           lambda: _checked_shots(item, script, draft, dossier))
    fixed = _fixes(d)["images"]
    by_scene = {s.scene_id: s for s in shot_list.shots}
    img_dir = d / "img"
    img_dir.mkdir(exist_ok=True)

    anchors: dict[str, Path] = {}                  # first illustration of each style anchors the rest

    def make(scene: Scene) -> render.Shot:
        shot = by_scene.get(scene.id)
        out = img_dir / f"{scene.id:03d}.png"
        if shot and shot.kind == "card":
            if not out.exists():
                cards.render_card(shot.card_type, shot.card_title, shot.card_lines, size, out)
            return render.Shot(out, "card", card={"card_type": shot.card_type, "title": shot.card_title,
                                                  "lines": shot.card_lines})
        if shot and shot.kind == "reuse" and (img_dir / f"{shot.reuse_of_scene:03d}.png").exists():
            return render.Shot(img_dir / f"{shot.reuse_of_scene:03d}.png", shot.motion)
        prompt = fixed.get(str(scene.id)) or (shot.image_prompt if shot and shot.image_prompt else scene.visual)
        style = shot.style if shot else "story"
        if not out.exists():
            anchor = anchors.get(style)
            images.generate(prompt, out, aspect, style=style, anchor=anchor if anchor != out else None)
        anchors.setdefault(style, out)
        return render.Shot(out, shot.motion if shot else "push_in")

    # the first illustration of each style is made first (it becomes the style anchor), then the rest in
    # parallel; reuse shots point at earlier illustrations, so they come last
    first = [s for s in script.scenes if by_scene.get(s.id) is None or by_scene[s.id].kind != "reuse"]
    made: dict[int, render.Shot] = {}
    for sc in first:
        shot = by_scene.get(sc.id)
        style = shot.style if shot else "story"
        if (shot is None or shot.kind == "illustration") and style not in anchors:
            made[sc.id] = make(sc)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rest = [sc for sc in first if sc.id not in made]
        made.update(dict(zip([sc.id for sc in rest], pool.map(make, rest))))
    shots = [made.get(sc.id) or make(sc) for sc in script.scenes]

    # shots the review team rejected twice borrow the nearest other illustration (with a different camera move)
    dropped = set(_fixes(d)["drop"])
    if dropped:
        ids = [sc.id for sc in script.scenes]
        bad = {i for i, sc in enumerate(script.scenes)
               if str(sc.id) in dropped or (by_scene.get(sc.id) and by_scene[sc.id].kind == "reuse"
                                            and str(by_scene[sc.id].reuse_of_scene) in dropped)}
        good = [i for i, sh in enumerate(shots) if not sh.card and i not in bad]
        for i in sorted(bad):
            if good:
                j = min(good, key=lambda g: (abs(g - i), g > i))
                shots[i] = render.Shot(shots[j].image, "pull_out" if shots[j].motion != "pull_out" else "pan_left")
        log.info("replaced shots %s with neighbouring illustrations", [ids[i] for i in sorted(bad)])

    # cards get the nearest illustration (before, else after) as their blurred backdrop
    art = [sh.image if not sh.card else None for sh in shots]
    for i, sh in enumerate(shots):
        if sh.card:
            near = next((a for a in art[i::-1] if a), None) or next((a for a in art[i:] if a), None)
            sh.card["backdrop"] = str(near) if near else None
    return shots


def _voiced(script: Script, d: Path) -> list[Scene]:
    """Scenes as the narrator reads them (the Proofreader may respell a line so numbers/names come out right)."""
    respell = _fixes(d)["audio"]
    return [sc.model_copy(update={"text": respell[str(sc.id)]}) if respell.get(str(sc.id)) else sc
            for sc in script.scenes]


def _voiced_script(script: Script, d: Path) -> Script:
    return script.model_copy(update={"scenes": _voiced(script, d)})


def _build_video(item: dict, d: Path, script: Script, hook: HookReview) -> tuple[Path, list[float], Path | None, str]:
    """Images, voice, render and (long form) thumbnail; every step cached, so a fix only redoes what it touched."""
    kind = item["kind"]
    vcfg = channel()["video"]["long_form" if kind == "long_form" else "vertical"]
    size, aspect = (vcfg["width"], vcfg["height"]), "16:9" if kind == "long_form" else "9:16"
    shots = _visuals(item, d, script, aspect, size)
    clips = tts.synthesize(_voiced(script, d), d / "audio")
    video, starts_file = d / "video.mp4", d / "starts.json"
    if not video.exists():
        _, starts = render.render(shots, clips, kind, d / "work", video, hook.on_screen_hook_text,
                                  sound_plan=_sound_plan(item, d, script), scene_ids=[sc.id for sc in script.scenes])
        starts_file.write_text(json.dumps(starts))
    starts = json.loads(starts_file.read_text())
    thumb_path, thumb_moment = None, "(no custom thumbnail)"
    if kind == "long_form":
        plan = cached(d / "thumbnails.json", ThumbnailPlan, lambda: packaging.thumbnails(item, script))
        best = plan.concepts[0]
        thumb_moment = best.moment
        art = d / "thumb_art.png"
        if not art.exists():
            images.generate(_fixes(d)["images"].get("thumbnail") or best.image_prompt, art, "16:9", style="story")
        thumb_path = d / "thumbnail.jpg"
        if not thumb_path.exists():
            compose.thumbnail(art, best.overlay_text, thumb_path)
    return video, starts, thumb_path, thumb_moment


AUDIO_EXTRA_ROUNDS = 2   # extra re-voice rounds when only the narration still has a major problem
MAX_IMAGE_ATTEMPTS = 1   # regenerate a failing shot once; if it fails again it is replaced (never sinks the video)


def _sound_plan(item: dict, d: Path, script: Script):
    """Sound Designer: music moods + accent effects from the library (None -> code-only effects/no music)."""
    from .media import sound
    from .models import SoundPlan

    music, sfx = sound.available()
    if not (music or sfx) or not channel().get("sound", {}).get("enabled", True):
        return None
    try:
        shots = ShotList.model_validate_json((d / "shots.json").read_text(encoding="utf-8"))
        return cached(d / "sound.json", SoundPlan,
                      lambda: packaging.sound_plan(item, script, shots, sound.describe_library()))
    except UsageLimitError:
        raise
    except Exception:
        log.exception("sound designer failed; default music, animation effects only")
        return None


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
        targets = ([d / "thumb_art.png", d / "thumbnail.jpg"] if key == "thumbnail"
                   else [d / "img" / f"{int(key):03d}.png"])
        for t in targets:
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
            return built, report
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
    fc = cached(d / "factcheck.json", FactCheck, lambda: writers.fact_check(script, dossier, kind))
    if not _gate(item, fc):
        return
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


# ---------------------------------------------------------------- carousel
def _produce_carousel(item: dict, d: Path, dossier: str) -> None:
    car = cached(d / "carousel.json", Carousel, lambda: packaging.carousel(item, dossier))
    as_script = Script(scenes=[Scene(id=i, chapter="slide", speaker="TEXT", text=f"{s.headline}\n{s.body}",
                                     visual=s.image_prompt) for i, s in enumerate(car.slides)],
                       sources=[s.source for s in car.slides if s.source])
    fc = cached(d / "factcheck.json", FactCheck, lambda: writers.fact_check(as_script, dossier))
    if not _gate(item, fc):
        return
    edited = {sc.id: sc.text for sc in fc.script.scenes}
    slide_dir = d / "slides"
    slide_dir.mkdir(exist_ok=True)
    handle = channel()["channel"]["handle"].lower()

    def build() -> list[str]:
        fixed = _fixes(d)["images"]
        paths = []
        for i, s in enumerate(car.slides):
            headline, _, body = edited.get(i, f"{s.headline}\n{s.body}").partition("\n")
            art_path, out = slide_dir / f"art{i:02d}.png", slide_dir / f"slide{i:02d}.jpg"
            art = None
            if s.image_prompt and str(i) not in _fixes(d)["drop"]:
                if not art_path.exists():
                    images.generate(fixed.get(str(i)) or s.image_prompt, art_path, "4:5", style=s.style)
                    out.unlink(missing_ok=True)
                art = art_path
            if not out.exists():
                if s.layout == "panel":
                    compose.panel_slide(i, len(car.slides), headline, body, s.source, art, out, handle)
                else:
                    compose.slide(i, len(car.slides), headline, body, s.source, s.theme, art, out, handle)
            paths.append(str(out))
        return paths

    def fix(report: ReviewReport) -> None:
        for key in _save_fixes(d, report):
            (slide_dir / f"art{int(key):02d}.png").unlink(missing_ok=True)
        for key in _fixes(d)["drop"]:                        # art failed twice: text-only slide
            (slide_dir / f"slide{int(key):02d}.jpg").unlink(missing_ok=True)

    prompts = [s.image_prompt for s in car.slides]
    done = _reviewed(item, d, build, lambda paths: qa.review_slides([Path(p) for p in paths], prompts), fix)
    if not done:
        return
    paths, report = done
    text = "\n".join(f"{i + 1}. {s.headline} — {s.body}" for i, s in enumerate(car.slides))
    cached(d / "seo.json", SeoPack,
           lambda: packaging.seo(item, None, car.slides[0].headline, [], f"\n\n# Slides\n{text}"))
    _schedule(item, title=car.slides[0].headline, slides=paths, **_qa_note(report))


PLATFORM_LABEL = {"youtube": "YouTube", "youtube_shorts": "YT Shorts", "instagram_reel": "IG Reel",
                  "instagram_carousel": "IG Carousel", "facebook_reel": "FB Reel", "facebook_post": "FB Post",
                  "tiktok": "TikTok"}


def _schedule(item: dict, **artifacts) -> None:
    from . import archive

    if item["data"].get("sample"):                # `tfs sample`: finished, but never queued for posting
        db.set_status(item["id"], "sample", **artifacts)
        return
    for platform, slot in item["data"]["platforms"].items():
        db.queue_post(item["id"], platform, slot)
    db.set_status(item["id"], "scheduled", **artifacts)
    log.info("scheduled %s", item["id"])
    _notify_ready(db.get_item(item["id"]))
    archive.archive_item(db.get_item(item["id"]))  # permanent copy in B2 (never blocks posting)


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
    if platform in ("facebook_reel", "facebook_post"):
        return f"https://www.facebook.com/{remote_id}"
    if platform in ("instagram_reel", "instagram_carousel"):
        return "https://www.instagram.com/thefilipinostandard/"
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


def produce(item_id: str) -> None:
    item = db.get_item(item_id)
    d = item_dir(item_id)
    try:
        dossier = cached_text(d / "dossier.md", lambda: writers.research(item))
        if item["kind"] == "carousel":
            _produce_carousel(item, d, dossier)
        else:
            _produce_video(item, d, dossier)
    except UsageLimitError as e:
        log.warning("usage limit reached; %s will retry on the next run (%s)", item_id, e)
        _alert_once("limit", f"⏸️ Production paused: {str(e)[:300]}\n"
                    "Items are kept and retried every run; nothing broken is posted. "
                    "Top up / upgrade and it resumes by itself.")
    except Exception as e:
        log.exception("production failed for %s", item_id)
        db.set_status(item_id, "failed", str(e)[:2000])
        notify.send(f"❌ Production failed: {item_id}: {e}")


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
    from .publish.limits import enforce_seo
    seo = enforce_seo(SeoPack.model_validate_json((d / "seo.json").read_text(encoding="utf-8")))
    slot = datetime.fromisoformat(post["slot_at"])
    video = media(data["video"]) if data.get("video") else None
    slides = [media(p) for p in data.get("slides", [])]
    platform = post["platform"]
    caption = {"youtube": seo.youtube_description, "youtube_shorts": seo.youtube_description,
               "instagram_reel": seo.instagram_caption, "instagram_carousel": seo.instagram_caption,
               "facebook_reel": seo.facebook_caption, "facebook_post": seo.facebook_caption,
               "tiktok": seo.tiktok_caption}[platform]
    title = data["title"] if platform == "youtube" else seo.shorts_title

    if _provider(platform) == "postforme":
        from .publish import postforme
        files = slides if platform in ("instagram_carousel", "facebook_post") else [video]
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
        case "tiktok":
            return "published", tiktok.post_video(video, caption)
        case "instagram_carousel":
            return "published", meta.ig_carousel(slides, caption)
        case "facebook_post":
            return "published", meta.fb_photos(slides, caption)
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
    for item in db.items_with_status("planned", "approved")[:max_produce]:
        produce(item["id"])


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


def _archive_pending() -> None:
    """Retry B2 archiving for finished items this run has on disk (uploads only what's missing)."""
    from . import archive

    if not archive.enabled():
        return
    for item in db.items_with_status("scheduled"):
        if (item_dir(item["id"]) / "seo.json").exists():
            archive.archive_item(item)


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
                tick(max_produce=0)                  # scout if stale, plan upcoming slots, expire stale
                state.push()
                last_tick = now()
            todo = [i for i in db.items_with_status("planned", "approved") if i["id"] not in tried]
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
