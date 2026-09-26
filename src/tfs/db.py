"""SQLite state: trend signals (for velocity), topic pool, production items, platform posts."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

from .config import data_dir, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
  source TEXT, key TEXT, value REAL, meta TEXT, seen_at TEXT
);
CREATE INDEX IF NOT EXISTS signals_key ON signals(source, key, seen_at);

CREATE TABLE IF NOT EXISTS topics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at TEXT, title TEXT, momentum INTEGER, data TEXT, used_by TEXT
);

CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,          -- e.g. 2026-09-27-long0
  kind TEXT,                    -- long_form | vertical | carousel
  anchor_at TEXT,               -- earliest publish time (ISO, PHT)
  status TEXT,                  -- planned, produced, awaiting_approval, scheduled, skipped, failed
  data TEXT,                    -- brief + artifacts index (JSON)
  error TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id TEXT, platform TEXT, slot_at TEXT,
  status TEXT,                  -- queued, submitted (Post for Me), published, failed, skipped
  remote_id TEXT, error TEXT, updated_at TEXT,
  UNIQUE(item_id, platform)
);
"""


@contextmanager
def conn():
    c = sqlite3.connect(data_dir() / "tfs.sqlite3", timeout=60)  # producer + publisher run concurrently
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    try:
        yield c
        c.commit()
    finally:
        c.close()


def iso(dt: datetime) -> str:
    """All timestamps are stored as PHT ISO strings, so plain string comparison orders them."""
    return dt.isoformat(timespec="seconds")


def ago(**delta) -> str:
    return iso(now() - timedelta(**delta))


# ---------- signals ----------
def add_signal(source: str, key: str, value: float, meta: dict | None = None) -> None:
    with conn() as c:
        c.execute("INSERT INTO signals VALUES (?,?,?,?,?)",
                  (source, key.lower().strip(), value, json.dumps(meta or {}), iso(now())))


def previous_signal(source: str, key: str, before: str) -> float | None:
    with conn() as c:
        row = c.execute(
            "SELECT value FROM signals WHERE source=? AND key=? AND seen_at<? ORDER BY seen_at DESC LIMIT 1",
            (source, key.lower().strip(), before)).fetchone()
    return row["value"] if row else None


def first_seen(source: str, key: str) -> str | None:
    with conn() as c:
        row = c.execute("SELECT MIN(seen_at) m FROM signals WHERE source=? AND key=?",
                        (source, key.lower().strip())).fetchone()
    return row["m"]


# ---------- topics ----------
def add_topics(topics: list[dict]) -> None:
    with conn() as c:
        for t in topics:
            c.execute("INSERT INTO topics(run_at,title,momentum,data,used_by) VALUES (?,?,?,?,NULL)",
                      (iso(now()), t["title"], t.get("momentum_score", 0), json.dumps(t, ensure_ascii=False)))


def fresh_topics(hours: int = 12, limit: int = 30) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT id, data FROM topics WHERE used_by IS NULL AND run_at >= ? "
            "ORDER BY momentum DESC LIMIT ?", (ago(hours=hours), limit)).fetchall()
    return [{"topic_id": r["id"], **json.loads(r["data"])} for r in rows]


def last_scout_at() -> str | None:
    with conn() as c:
        return c.execute("SELECT MAX(run_at) m FROM topics").fetchone()["m"]


def mark_topic_used(topic_id: int, item_id: str) -> None:
    with conn() as c:
        c.execute("UPDATE topics SET used_by=? WHERE id=?", (item_id, topic_id))


# ---------- items ----------
def upsert_item(item_id: str, kind: str, anchor_at: str, status: str, data: dict, error: str = "") -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO items VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "status=excluded.status, data=excluded.data, error=excluded.error, updated_at=excluded.updated_at",
            (item_id, kind, anchor_at, status, json.dumps(data, ensure_ascii=False), error, iso(now())))


def get_item(item_id: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    return _item(r) if r else None


def items_with_status(*statuses: str) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            f"SELECT * FROM items WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY anchor_at",
            statuses).fetchall()
    return [_item(r) for r in rows]


def recent_titles(days: int = 30) -> list[str]:
    with conn() as c:
        rows = c.execute("SELECT data FROM items WHERE anchor_at >= ?", (ago(days=days),)).fetchall()
    return [json.loads(r["data"]).get("working_title", "") for r in rows]


def count_before(kind: str, item_id: str) -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) n FROM items WHERE kind=? AND id<? AND status NOT IN ('skipped','failed')",
                         (kind, item_id)).fetchone()["n"]


def set_status(item_id: str, status: str, error: str = "", **data_updates) -> None:
    item = get_item(item_id)
    item["data"].update(data_updates)
    upsert_item(item_id, item["kind"], item["anchor_at"], status, item["data"], error)


def _item(r: sqlite3.Row) -> dict:
    return {**dict(r), "data": json.loads(r["data"])}


# ---------- posts ----------
def queue_post(item_id: str, platform: str, slot_at: str) -> None:
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO posts(item_id,platform,slot_at,status,updated_at) VALUES (?,?,?,?,?)",
                  (item_id, platform, slot_at, "queued", iso(now())))


def queued_posts() -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM posts WHERE status='queued' ORDER BY slot_at").fetchall()
    return [dict(r) for r in rows]


def posts_with_status(status: str) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM posts WHERE status=? ORDER BY slot_at", (status,)).fetchall()
    return [dict(r) for r in rows]


def retry_post(post_id: int) -> None:
    with conn() as c:
        c.execute("UPDATE posts SET status='queued', error='' WHERE id=?", (post_id,))


def posts_for_item(item_id: str) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM posts WHERE item_id=?", (item_id,)).fetchall()]


def finish_post(post_id: int, status: str, remote_id: str = "", error: str = "") -> None:
    with conn() as c:
        c.execute("UPDATE posts SET status=?, remote_id=?, error=?, updated_at=? WHERE id=?",
                  (status, remote_id, error[:2000], iso(now()), post_id))


def posts_for_analysis(days: int = 28) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT p.*, i.kind, i.data FROM posts p JOIN items i ON i.id=p.item_id "
            "WHERE p.status='published' AND p.slot_at >= ?", (ago(days=days),)).fetchall()
    return [dict(r) for r in rows]
