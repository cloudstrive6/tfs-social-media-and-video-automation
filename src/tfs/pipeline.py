"""Orchestrator. Every step writes its artifact to data/items/<id>/ and is skipped if the artifact
exists, so a crashed or approval-paused item resumes exactly where it stopped."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, TypeVar

from pydantic import BaseModel

from . import db, notify, slots
from .agents import editor, packaging, trend_scout, writers
from .config import channel, item_dir, now, schedule
from .llm import UsageLimitError
from .media import cards, compose, images, render, tts
from .models import (Carousel, FactCheck, HookReview, Scene, Script, SeoPack, ShotList,
                     ThumbnailPlan, TitlePlan)

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
SCOUT_EVERY = timedelta(hours=3)
MAX_REWRITES = 2


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
    rules = channel()["quality"]["require_human_approval_for"]
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
        if hook.hook_score >= q["min_hook_score"] and hook.retention_score >= q["min_script_score"]:
            return hook.script, hook
        feedback = "\n".join(hook.fixes) + f"\n(hook {hook.hook_score}/10, retention {hook.retention_score}/10)"
    db.set_status(item["id"], "skipped", f"below quality bar after {MAX_REWRITES + 1} drafts")
    notify.send(f"⚠️ {item['id']} skipped — script never reached the quality bar.")
    return None


# ---------------------------------------------------------------- video
def _visuals(item: dict, d: Path, script: Script, aspect: str, size: tuple[int, int]) -> list[render.Shot]:
    shot_list = cached(d / "shots.json", ShotList, lambda: packaging.shot_list(item, script))
    by_scene = {s.scene_id: s for s in shot_list.shots}
    img_dir = d / "img"
    img_dir.mkdir(exist_ok=True)

    def make(scene: Scene) -> render.Shot:
        shot = by_scene.get(scene.id)
        out = img_dir / f"{scene.id:03d}.png"
        if shot and shot.kind == "card":
            if not out.exists():
                cards.render_card(shot.card_type, shot.card_title, shot.card_lines, size, out)
            return render.Shot(out, "card")
        if shot and shot.kind == "reuse" and (img_dir / f"{shot.reuse_of_scene:03d}.png").exists():
            return render.Shot(img_dir / f"{shot.reuse_of_scene:03d}.png", shot.motion)
        prompt = shot.image_prompt if shot and shot.image_prompt else scene.visual
        images.generate(prompt, out, aspect, style=shot.style if shot else "story")
        return render.Shot(out, shot.motion if shot else "push_in")

    # illustrations first (reuse shots point at them), in parallel
    first = [s for s in script.scenes if by_scene.get(s.id) is None or by_scene[s.id].kind != "reuse"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        made = dict(zip([s.id for s in first], pool.map(make, first)))
    return [made.get(s.id) or make(s) for s in script.scenes]


def _produce_video(item: dict, d: Path, dossier: str) -> None:
    iid, kind = item["id"], item["kind"]
    result = _script(item, d, dossier)
    if not result:
        return
    script, hook = result
    fc = cached(d / "factcheck.json", FactCheck, lambda: writers.fact_check(script, dossier))
    if not _gate(item, fc):
        return
    script = fc.script
    vcfg = channel()["video"]["long_form" if kind == "long_form" else "vertical"]
    size, aspect = (vcfg["width"], vcfg["height"]), "16:9" if kind == "long_form" else "9:16"

    shots = _visuals(item, d, script, aspect, size)
    clips = tts.synthesize(script.scenes, d / "audio")
    video, starts_file = d / "video.mp4", d / "starts.json"
    if not video.exists():
        _, starts = render.render(shots, clips, kind, d / "work", video, hook.on_screen_hook_text)
        starts_file.write_text(json.dumps(starts))
    starts = json.loads(starts_file.read_text())

    thumb_path = None
    thumb_moment = "(no custom thumbnail)"
    if kind == "long_form":
        plan = cached(d / "thumbnails.json", ThumbnailPlan, lambda: packaging.thumbnails(item, script))
        best = plan.concepts[0]
        thumb_moment = best.moment
        art = images.generate(best.image_prompt, d / "thumb_art.png", "16:9", style="story")
        thumb_path = compose.thumbnail(art, best.overlay_text, d / "thumbnail.jpg")
    titles = cached(d / "titles.json", TitlePlan, lambda: packaging.titles(item, script, thumb_moment))
    chapters = render.chapters(script.scenes, starts) if kind == "long_form" else []
    cached(d / "seo.json", SeoPack, lambda: packaging.seo(item, script, titles.primary, chapters))

    _schedule(item, title=titles.primary, video=str(video), thumbnail=str(thumb_path or ""))


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
    paths = []
    for i, s in enumerate(car.slides):
        headline, _, body = edited.get(i, f"{s.headline}\n{s.body}").partition("\n")
        art = (images.generate(s.image_prompt, slide_dir / f"art{i:02d}.png", "4:5", style=s.style)
               if s.image_prompt else None)
        out = slide_dir / f"slide{i:02d}.jpg"
        handle = channel()["channel"]["handle"].lower()
        if s.layout == "panel":
            compose.panel_slide(i, len(car.slides), headline, body, s.source, art, out, handle)
        else:
            compose.slide(i, len(car.slides), headline, body, s.source, s.theme, art, out, handle)
        paths.append(str(out))
    text = "\n".join(f"{i + 1}. {s.headline} — {s.body}" for i, s in enumerate(car.slides))
    cached(d / "seo.json", SeoPack,
           lambda: packaging.seo(item, None, car.slides[0].headline, [], f"\n\n# Slides\n{text}"))
    _schedule(item, title=car.slides[0].headline, slides=paths)


def _schedule(item: dict, **artifacts) -> None:
    for platform, slot in item["data"]["platforms"].items():
        db.queue_post(item["id"], platform, slot)
    db.set_status(item["id"], "scheduled", **artifacts)
    log.info("scheduled %s", item["id"])


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
        log.warning("Claude usage limit reached; %s will retry on the next tick (%s)", item_id, e)
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
    seo = SeoPack.model_validate_json((d / "seo.json").read_text(encoding="utf-8"))
    slot = datetime.fromisoformat(post["slot_at"])
    video = Path(data["video"]) if data.get("video") else None
    slides = [Path(p) for p in data.get("slides", [])]
    platform = post["platform"]
    caption = {"youtube": seo.youtube_description, "youtube_shorts": seo.youtube_description,
               "instagram_reel": seo.instagram_caption, "instagram_carousel": seo.instagram_caption,
               "facebook_reel": seo.facebook_caption, "facebook_post": seo.facebook_caption,
               "tiktok": seo.tiktok_caption}[platform]
    title = data["title"] if platform == "youtube" else seo.shorts_title

    if _provider(platform) == "postforme":
        from .publish import postforme
        media = slides if platform in ("instagram_carousel", "facebook_post") else [video]
        thumb = Path(data["thumbnail"]) if platform == "youtube" and data.get("thumbnail") else None
        pid = postforme.create_post(platform, caption, media, slot, title=title, description=caption,
                                    tags=seo.tags, thumbnail=thumb, external_id=f"{item['id']}:{platform}")
        return "submitted", pid

    from .publish import meta, tiktok, youtube
    match platform:
        case "youtube" | "youtube_shorts":
            thumb = Path(data["thumbnail"]) if data.get("thumbnail") else None
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
            db.finish_post(post["id"], "published", (r.get("platform_data") or {}).get("id") or post["remote_id"])
        else:
            db.finish_post(post["id"], "failed", post["remote_id"], str(r.get("error")))
            notify.send(f"❌ Publish failed: {post['item_id']} → {post['platform']}: {r.get('error')}\n"
                        f"Retry: tfs retry {post['id']}")


def publish_due() -> int:
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
            done += 1
            log.info("%s %s → %s (%s)", status, post["item_id"], post["platform"], remote_id)
        except Exception as e:
            log.exception("publish failed")
            db.finish_post(post["id"], "failed", error=str(e))
            notify.send(f"❌ Publish failed: {post['item_id']} → {post['platform']}: {e}\n"
                        f"Retry: tfs retry {post['id']}")
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
