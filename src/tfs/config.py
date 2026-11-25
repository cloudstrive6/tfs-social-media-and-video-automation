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
    if override.exists():                          # {"slots": {kind: [HH:MM, ...]}}; older per-platform keys are ignored
        changed = (yaml.safe_load(override.read_text()) or {}).get("slots") or {}
        merged["slots"] = {**merged["slots"], **{k: v for k, v in changed.items() if k in merged["slots"]}}
    return merged


def paused_kinds() -> set[str]:
    """Production kinds on pause (schedule.yaml `paused`): not planned, produced or posted. With the atlas engine,
    carousels also pause until a style v2 carousel brief exists (their slide art and copy are cartoon-era)."""
    paused = set(schedule().get("paused") or [])
    if _v2() and not (ROOT / "prompts" / "v2" / "carousel_designer.md").exists():
        paused.add("carousel")
    return paused


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


def _v2() -> bool:
    """Style v2 (atlas engine, approved 2026-11-24): the cartoon-era bible and briefs are not used (Bryce: "don't use
    that old one")."""
    return channel().get("video", {}).get("engine") == "atlas"


def notes_dir(kind: str) -> Path:
    """Standing notes folder ("analyst_notes" or "creative_notes"). Style v2 keeps its own, so notes written while
    reviewing cartoon-era videos never steer atlas videos."""
    return data_dir() / (f"{kind}_v2" if _v2() else kind)


def style_bible() -> str:
    """Style Bible v2 is the only bible; the cartoon-era one was deleted on 2026-11-25."""
    return (ROOT / "docs" / "STYLE_BIBLE_V2.md").read_text(encoding="utf-8")


V2_NATIVE = {"atlas_designer"}      # written for the atlas engine from the start; lives in prompts/


class RetiredBriefError(RuntimeError):
    """An agent with no style v2 brief was asked for: the cartoon-era briefs are deleted, never a fallback."""


def load_prompt(agent: str) -> str:
    """Agent prompt plus any standing notes for it. Only style v2 briefs exist (prompts/v2/, plus the atlas designer,
    written for atlas from the start); the cartoon-era briefs were deleted (Bryce, 2026-11-25: "any of the old-style
    elements ... Remove and Do Not Use since that is flawed", then "remove/delete the old-style")."""
    path = ROOT / "prompts" / "v2" / f"{agent}.md"
    if not path.exists():
        if agent not in V2_NATIVE:
            raise RetiredBriefError(f"no style v2 brief for '{agent}'; the cartoon-era briefs are deleted")
        path = ROOT / "prompts" / f"{agent}.md"
    prompt = path.read_text(encoding="utf-8")
    notes = notes_dir("analyst_notes") / f"{agent}.md"
    if notes.exists():
        prompt += "\n\n## Standing notes from the Growth Analyst\n" + notes.read_text(encoding="utf-8")
    creative = notes_dir("creative_notes") / f"{agent}.md"
    if creative.exists() and creative.read_text(encoding="utf-8").strip():
        prompt += ("\n\n## Standing notes from the Creative Director (from recent reviews; follow them)\n"
                   + creative.read_text(encoding="utf-8"))
    return prompt


def now() -> datetime:
    return datetime.now(PHT)
