"""Turns config/schedule.yaml into production units and platform posting slots."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time

from .config import PHT, paused_kinds, schedule

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


def day_units(d: date) -> list[Unit]:
    """The day's production units: the i-th unit of a kind posts at that kind's i-th slot on every one of its
    platforms at once."""
    sched = schedule()
    units = []
    paused = paused_kinds()
    for kind, count in sched["daily_production"].items():
        if kind in paused:
            continue
        times = sched["slots"].get(kind, [])
        for i in range(min(count, len(times))):
            hh, mm = map(int, times[i].split(":"))
            at = datetime.combine(d, time(hh, mm), tzinfo=PHT)
            unit = Unit(id=f"{d.isoformat()}-{PREFIX[kind]}{i}", kind=kind, index=i,
                        platforms={platform: at for platform in sched["platforms"].get(kind, [])})
            if unit.platforms:
                units.append(unit)
    return units


def unit_by_id(item_id: str) -> Unit:
    d = date.fromisoformat(item_id[:10])
    return next(u for u in day_units(d) if u.id == item_id)
