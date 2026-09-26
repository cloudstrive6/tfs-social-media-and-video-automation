"""`tfs` command line. Cron / GitHub Actions call `tfs tick` and `tfs publish`."""
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
    sub.add_parser("tick", help="scout if stale, plan upcoming slots, produce the next item")
    sub.add_parser("publish", help="publish every post whose slot has arrived")
    sub.add_parser("scout", help="run the trend scout now and print the ranked topics")
    sub.add_parser("plan", help="plan upcoming slots now")
    sub.add_parser("analyze", help="weekly growth analysis + agent notes + schedule retune")
    sub.add_parser("status", help="show items and posts")
    sub.add_parser("backup", help="copy the SQLite state to the private backup bucket")
    sub.add_parser("verify", help="check every configured credential works (prints names only, never secrets)")
    sub.add_parser("preview-styles", help="generate one sample image per art style for approval")
    for name in ("produce", "approve", "reject", "requeue"):
        sp = sub.add_parser(name)
        sp.add_argument("item_id")
    sub.add_parser("retry").add_argument("post_id", type=int)
    sub.add_parser("auth").add_argument("service", choices=["youtube"])
    a = p.parse_args()

    match a.cmd:
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
        case "preview-styles":
            from .preview import run
            print("
".join(run()))
        case "verify":
            from .verify import run_all
            sys.exit(0 if run_all() else 1)
        case "backup":
            import sqlite3
            from .config import data_dir, env
            if not env("S3_BACKUP_BUCKET"):
                print("backup skipped: S3_BACKUP_BUCKET not configured")
                return
            from .publish import storage
            snapshot = data_dir() / "backup.sqlite3"
            with sqlite3.connect(data_dir() / "tfs.sqlite3") as src, sqlite3.connect(snapshot) as dst:
                src.backup(dst)   # consistent copy even while other jobs write
            print(storage.backup(snapshot))
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
