"""`tfs` command line. The GitHub Actions `run` workflow calls `tfs run`."""
from __future__ import annotations

import argparse
import json
import logging
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
    sub.add_parser("backup", help="dated copy of the SQLite state in the private R2 bucket")
    sub.add_parser("sample", help="produce one piece now for review; never scheduled or posted").add_argument(
        "--kind", choices=["vertical", "carousel"], default="vertical")
    sub.add_parser("verify", help="check every configured credential works (prints names only, never secrets)")
    sub.add_parser("preview-styles", help="generate one sample image per art style")
    sub.add_parser("telegram-setup", help="print the chat id(s) that messaged the bot; send a test message")
    sub.add_parser("make-characters", help="generate the recurring cast's model sheets into assets/characters")
    for name in ("produce", "approve", "reject", "requeue"):
        sp = sub.add_parser(name)
        sp.add_argument("item_id")
    sub.add_parser("retry").add_argument("post_id", type=int)
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
            db.retry_post(a.post_id)
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
            for status in ("awaiting_approval", "planned", "approved", "scheduled", "failed", "skipped"):
                for it in db.items_with_status(status)[-15:]:
                    posts = {x["platform"]: x["status"] for x in db.posts_for_item(it["id"])}
                    print(f"{it['anchor_at'][:16]}  {status:<17} {it['id']:<22} "
                          f"{it['data'].get('title') or it['data'].get('working_title', '')[:60]}  "
                          f"{json.dumps(posts) if posts else ''}")


if __name__ == "__main__":
    main()
