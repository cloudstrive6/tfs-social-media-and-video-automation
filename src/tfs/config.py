"""Loads config/*.yaml, prompts and environment. Everything else imports from here."""
from __future__ import annotations

import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import truststore
import yaml
from dotenv import load_dotenv

# Use the OS certificate store (works behind antivirus/corporate HTTPS inspection on Windows).
truststore.inject_into_ssl()

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

PHT = ZoneInfo("Asia/Manila")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def require_env(name: str) -> str:
    value = env(name)
    if not value:
        raise RuntimeError(f"Missing environment variable {name} (see .env.example)")
    return value


@lru_cache
def load_yaml(name: str) -> dict:
    return yaml.safe_load((ROOT / "config" / f"{name}.yaml").read_text(encoding="utf-8"))


def channel() -> dict:
    return load_yaml("channel")


def schedule() -> dict:
    """config/schedule.yaml, with slot changes the analyst wrote to the data dir layered on top."""
    merged = dict(load_yaml("schedule"))
    override = data_dir() / "schedule_override.yaml"
    if override.exists():
        for key, slots in (yaml.safe_load(override.read_text()) or {}).items():
            if isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], "slots": slots}
            elif key in merged:
                merged[key] = slots
    return merged


def sources() -> dict:
    return load_yaml("sources")


def data_dir() -> Path:
    path = Path(env("TFS_DATA_DIR") or ROOT / "data")
    path.mkdir(parents=True, exist_ok=True)
    return path


def media(path: str) -> Path:
    """A stored artifact path, re-rooted onto this machine's data dir if the run's workspace moved."""
    p = Path(path)
    if p.exists() or "items" not in p.parts:
        return p
    return data_dir().joinpath(*p.parts[len(p.parts) - p.parts[::-1].index("items") - 1:])


def item_dir(item_id: str) -> Path:
    path = data_dir() / "items" / item_id
    path.mkdir(parents=True, exist_ok=True)
    return path


@lru_cache
def style_bible() -> str:
    return (ROOT / "docs" / "STYLE_BIBLE.md").read_text(encoding="utf-8")


def load_prompt(agent: str) -> str:
    """Agent prompt plus any standing notes the analyst has written for it."""
    prompt = (ROOT / "prompts" / f"{agent}.md").read_text(encoding="utf-8")
    notes = data_dir() / "analyst_notes" / f"{agent}.md"
    if notes.exists():
        prompt += "\n\n## Standing notes from the Growth Analyst\n" + notes.read_text(encoding="utf-8")
    return prompt


def now() -> datetime:
    return datetime.now(PHT)
