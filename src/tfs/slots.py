"""Turns config/schedule.yaml into production units and platform posting slots."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time

from .config import PHT, schedule

# kind -> [(platform, schedule.yaml key)]; the i-th unit of a kind uses the i-th slot of each list.
FEEDS = {
    "long_form": [("youtube", "youtube_long")],
    "vertical": [("youtube_shorts", "youtube_shorts"), ("instagram_reel", "instagram_reels"),
                 ("facebook_reel", "facebook_reels"), ("tiktok", "tiktok")],
    "carousel": [("instagram_carousel", "instagram_carousels"), ("facebook_post", "facebook_posts")],
}
PREFIX = {"long_form": "long", "vertical": "vert", "carousel": "caro"}


@dataclass
class Unit:
    id: str
    kind: str
    index: int
    platforms: dict[str, datetime] = field(default_factory=dict)

    @property
    def anchor(self) -> datetime:
        return min(self.platforms.values())


def _slot_list(key: str) -> list[str]:
    value = schedule().get(key, [])
    if isinstance(value, dict):  # e.g. tiktok: {enabled, slots}
        return value.get("slots", []) if value.get("enabled", True) else []
    return value


def day_units(d: date) -> list[Unit]:
    units = []
    for kind, count in schedule()["daily_production"].items():
        for i in range(count):
            unit = Unit(id=f"{d.isoformat()}-{PREFIX[kind]}{i}", kind=kind, index=i)
            for platform, key in FEEDS[kind]:
                slots = _slot_list(key)
                if i < len(slots):
                    hh, mm = map(int, slots[i].split(":"))
                    unit.platforms[platform] = datetime.combine(d, time(hh, mm), tzinfo=PHT)
            if unit.platforms:
                units.append(unit)
    return units


def unit_by_id(item_id: str) -> Unit:
    d = date.fromisoformat(item_id[:10])
    return next(u for u in day_units(d) if u.id == item_id)
