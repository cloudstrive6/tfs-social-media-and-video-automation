"""`tfs` command line. The GitHub Actions `run` workflow calls `tfs run`."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from . import db, pipeline


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="tfs", description="The Filipino Standard automation")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="one cloud run: restore state from R2, publish + produce, save state back")
    sub.add_parser("tick", help="scout if stale, plan upcoming slots, produce the next item")
    sub.add_parser("publish", help="publish every post whose slot has arrived")
    sub.add_parser("scout", help="run the trend scout now and print the ranked topics")
    sub.add_parser("plan", help="plan upcoming slots now")
    sub.add_parser("analyze", help="weekly growth analysis + agent notes + schedule retune")
    sub.add_parser("status", help="show items and posts")
    sub.add_parser("creative-review", help="Creative Director now: review notes -> standing notes for the designers")
    sub.add_parser("backup", help="dated copy of the SQLite state in the private R2 bucket")
    sub.add_parser("sample", help="produce one piece now for review; never scheduled or posted").add_argument(
        "--kind", choices=["vertical", "carousel"], default="vertical")
    pn = sub.add_parser("post-now", help="make one piece on a topic and publish it right away on all its platforms")
    # workflow inputs arrive as environment variables (never pasted into a shell command line)
    pn.add_argument("--kind", choices=["vertical", "carousel"], default=os.environ.get("TFS_KIND") or "carousel")
    pn.add_argument("--topic", default=os.environ.get("TFS_SAMPLE_TOPIC", ""))
    pn.add_argument("--note", default=os.environ.get("TFS_NOTE", ""), help="extra guidance for the editor and researcher")
    pn.add_argument("--here", action="store_true", help="make it in this process instead of queueing it for a run")
    sub.add_parser("hold", help="stop posts that haven't gone live yet (one item, or all); never deletes").add_argument(
        "item_id", nargs="?", default="")
    sub.add_parser("build-sound-library", help="one-time: generate music beds + sound effects with ElevenLabs into R2")
    sub.add_parser("verify", help="check every configured credential works (prints names only, never secrets)")
    sub.add_parser("preview-styles", help="generate one sample image per art style")
    sub.add_parser("telegram-setup", help="print the chat id(s) that messaged the bot; send a test message")
    sub.add_parser("make-characters", help="generate the recurring cast's model sheets into assets/characters")
    for name in ("produce", "approve", "reject", "requeue"):
        sp = sub.add_parser(name)
        sp.add_argument("item_id")
    sub.add_parser("retry", help="re-queue a failed post (id), or 'failed' = every failed post whose slot is ahead"
                   ).add_argument("post_id")
    sub.add_parser("auth").add_argument("service", choices=["youtube"])
    a = p.parse_args()

    match a.cmd:
        case "run":
            pipeline.cloud_run()
        case "tick":
            pipeline.tick()
        case "publish":
            pipeline.publish_due()
        case "scout":
            from .agents import trend_scout
            for t in trend_scout.run():
                print(f"{t['momentum_score']:>3}  [{t['pillar']}] {t['title']} — {t['predicted_peak']}")
        case "plan":
            print(pipeline.plan_upcoming())
        case "produce":
            pipeline.produce(a.item_id)
        case "approve":
            db.set_status(a.item_id, "approved", approved=True)
        case "reject":
            db.set_status(a.item_id, "skipped", "rejected by human")
        case "requeue":
            db.set_status(a.item_id, "planned")
        case "retry":
            from datetime import datetime

            from . import state
            from .config import now
            if state.enabled():
                state.pull()
            ids = ([p["id"] for p in db.posts_with_status("failed")
                    if datetime.fromisoformat(p["slot_at"]) > now()] if a.post_id == "failed" else [int(a.post_id)])
            for pid in ids:
                db.retry_post(pid)
            print(f"re-queued posts: {ids}")
            if state.enabled():
                state.push()
        case "creative-review":
            from . import state
            from .agents import creative
            if state.enabled():
                state.pull()
            result = creative.run(force=True)
            print(result.summary if result else "no reviewed pieces yet")
            if state.enabled():
                state.push()
        case "analyze":
            from .agents import analyst
            print(analyst.run().summary_markdown)
        case "telegram-setup":
            from .telegram_setup import run as tg
            tg()
        case "make-characters":
            from .characters import run as make
            print("\n".join(make()))
        case "preview-styles":
            from .preview import run
            print("\n".join(run()))
        case "sample":
            from .sample import run as make_sample
            print(make_sample(a.kind))
        case "post-now":
            from . import post_now
            print(post_now.run(a.kind, a.topic, a.note) if a.here else post_now.request(a.kind, a.topic, a.note))
        case "hold":
            from .hold import run as hold
            print("\n".join(hold("held by request", a.item_id)) or "nothing to hold")
        case "build-sound-library":
            from . import state
            from .media import sound
            if state.enabled():
                state.pull()                         # keep what's already built (only missing items are made)
            made = sound.build_library()
            print(f"generated {len(made)} new files; uploaded {state.push_library()} library files to R2")
        case "verify":
            from .verify import run_all
            sys.exit(0 if run_all() else 1)
        case "backup":
            from . import state
            if not state.enabled():
                print("backup skipped: S3_BACKUP_BUCKET not configured")
                return
            state.daily_backup()
        case "auth":
            from .publish import youtube
            print("YOUTUBE_REFRESH_TOKEN=" + youtube.authorize())
        case "status":
            from . import state
            if state.enabled():
                state.pull()
            for status in ("awaiting_approval", "planned", "approved", "scheduled", "failed", "skipped"):
                for it in db.items_with_status(status)[-15:]:
                    posts = {x["platform"]: x["status"] for x in db.posts_for_item(it["id"])}
                    print(f"{it['anchor_at'][:16]}  {status:<17} {it['id']:<22} "
                          f"{it['data'].get('title') or it['data'].get('working_title', '')[:60]}  "
                          f"{json.dumps(posts) if posts else ''}")
            for status in ("failed", "submitted", "published"):
                for post in db.posts_with_status(status)[-20:]:
                    print(f"  post {post['id']:>3} {post['item_id']:<18} {post['platform']:<18} {status:<9} "
                          f"{post['slot_at'][:16]}  {(post.get('error') or '')[:160]}")


if __name__ == "__main__":
    main()
