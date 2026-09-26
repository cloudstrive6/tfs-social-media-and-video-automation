"""`tfs hold`: stop everything that hasn't gone live yet (nothing is deleted).

Queued posts are marked skipped; YouTube videos already uploaded with a scheduled publishAt are set to plain
private; posts already handed to Post for Me for a future time are cancelled there. Run through the `hold`
workflow, which shares the `tfs-state` concurrency group with `run`.
"""
from __future__ import annotations

import logging
from datetime import datetime

from . import db, notify, state
from .config import now

log = logging.getLogger(__name__)


def run(reason: str = "held", item_id: str = "") -> list[str]:
    from .pipeline import _provider

    if not state.enabled():
        raise SystemExit("hold: no R2 state bucket configured")
    state.pull()
    done = []
    for post in db.posts_with_status("queued"):
        if item_id and post["item_id"] != item_id:
            continue
        db.finish_post(post["id"], "skipped", error=reason)
        done.append(f"{post['item_id']} → {post['platform']}: not posted")
    for post in db.posts_with_status("submitted"):
        if item_id and post["item_id"] != item_id:
            continue
        if datetime.fromisoformat(post["slot_at"]) <= now():
            continue                                   # already due/live: leave it to reconcile
        try:
            if post["platform"] in ("youtube", "youtube_shorts") and _provider(post["platform"]) == "direct":
                from .publish import youtube
                youtube.unschedule(post["remote_id"])
                done.append(f"{post['item_id']} → {post['platform']}: upload kept private ({post['remote_id']})")
            else:
                from .publish import postforme
                postforme.cancel(post["remote_id"], post["platform"])
                done.append(f"{post['item_id']} → {post['platform']}: scheduled post cancelled")
            db.finish_post(post["id"], "skipped", post["remote_id"], reason)
        except Exception as e:
            log.exception("hold failed for post %s", post["id"])
            done.append(f"⚠️ {post['item_id']} → {post['platform']}: could not hold ({e}) — check it by hand")
    state.push()
    notify.send(f"⏸️ Hold ({reason}):\n" + ("\n".join(done) if done else "nothing was waiting to go out"))
    return done
