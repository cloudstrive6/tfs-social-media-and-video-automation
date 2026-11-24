"""Turns config/schedule.yaml into production units and platform posting slots.

Two config shapes are read:

* weekly (since 2026-11-24): `week` maps each PHT weekday to a day type, and `day_types` lists that day's units
  per kind. A unit is produced once and cross-posted; each platform can have its own time or skip the unit.
* old: no `week`; every day makes `daily_production[kind]` units, the i-th at `slots[kind][i]` on every platform
  of the kind at the same moment.

The analyst's override (data/schedule_override.yaml, merged into `slots` by config.schedule) applies to both:
in the weekly shape it moves the i-th unit of a kind on every day by (override time - config time).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .config import PHT, load_yaml, paused_kinds, schedule

PREFIX = {"long_form": "long", "vertical": "vert", "carousel": "caro"}
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass
class Unit:
    id: str
    kind: str
    index: int
    platforms: dict[str, datetime] = field(default_factory=dict)
    format: str = ""                      # editor hint from the weekly schedule (carousel: multi | single)

    @property
    def anchor(self) -> datetime:
        return min(self.platforms.values())


def is_live(sched: dict | None = None) -> bool:
    """The master switch (`live` in schedule.yaml). Missing means live, so an old-format config keeps running."""
    sched = schedule() if sched is None else sched
    return bool(sched.get("live", True))


def _at(d: date, hhmm: str, shift: timedelta = timedelta(0)) -> datetime:
    hh, mm = map(int, str(hhmm).split(":"))
    return datetime.combine(d, time(hh, mm), tzinfo=PHT) + shift      # may roll past midnight (PHT)


def _minutes(hhmm: str) -> int:
    hh, mm = map(int, str(hhmm).split(":"))
    return hh * 60 + mm


def _shifts(sched: dict, base: dict) -> dict[str, list[timedelta]]:
    """Per kind and unit index: how far the analyst's override moved that slot from the config's time."""
    out = {}
    for kind, merged in (sched.get("slots") or {}).items():
        defaults = (base.get("slots") or {}).get(kind) or []
        out[kind] = [timedelta(minutes=_minutes(m) - _minutes(b)) for m, b in zip(merged, defaults)]
    return out


def day_type(d: date, sched: dict | None = None) -> str | None:
    """The day type for a PHT date in the weekly shape, or None for an old-format config."""
    sched = schedule() if sched is None else sched
    week = sched.get("week")
    return week.get(WEEKDAYS[d.weekday()]) if week else None


def _unit_platforms(spec: dict, all_platforms: list[str], d: date, shift: timedelta) -> dict[str, datetime]:
    only, skip = spec.get("only"), set(spec.get("skip") or [])
    targets = [p for p in all_platforms if (only is None or p in only) and p not in skip]
    targets += [p for p in (only or []) if p not in targets]          # a platform named only here still posts
    times = spec.get("times") or {}
    return {p: _at(d, times.get(p, spec["at"]), shift) for p in targets}


def _weekly_units(d: date, sched: dict, base: dict) -> list[Unit]:
    kind_specs = (sched.get("day_types") or {}).get(day_type(d, sched)) or {}
    shifts = _shifts(sched, base)
    units = []
    for kind, specs in kind_specs.items():
        for i, spec in enumerate(specs or []):
            moved = shifts.get(kind, [])
            shift = moved[i] if i < len(moved) else timedelta(0)
            platforms = _unit_platforms(spec, sched["platforms"].get(kind, []), d, shift)
            if platforms:
                units.append(Unit(id=f"{d.isoformat()}-{PREFIX[kind]}{i}", kind=kind, index=i,
                                  platforms=platforms, format=str(spec.get("format") or "")))
    return units


def _legacy_units(d: date, sched: dict) -> list[Unit]:
    """Old shape: the i-th unit of a kind posts at that kind's i-th slot on every one of its platforms at once."""
    units = []
    for kind, count in (sched.get("daily_production") or {}).items():
        times = sched["slots"].get(kind, [])
        for i in range(min(count, len(times))):
            at = _at(d, times[i])
            unit = Unit(id=f"{d.isoformat()}-{PREFIX[kind]}{i}", kind=kind, index=i,
                        platforms={platform: at for platform in sched["platforms"].get(kind, [])})
            if unit.platforms:
                units.append(unit)
    return units


def day_units(d: date, sched: dict | None = None) -> list[Unit]:
    """The production units for a PHT date, each with its per-platform publish times. Paused kinds are left out.
    `sched` is for tests; by default the config plus the analyst's override is read."""
    if sched is None:
        sched, base = schedule(), load_yaml("schedule")
    else:
        base = sched
    paused = paused_kinds()
    units = _weekly_units(d, sched, base) if sched.get("week") else _legacy_units(d, sched)
    return [u for u in units if u.kind not in paused]


def day_posts(d: date, sched: dict | None = None) -> dict[str, list[datetime]]:
    """Per platform, the sorted publish times of the day's units (a platform that posts nothing is absent)."""
    out: dict[str, list[datetime]] = {}
    for unit in day_units(d, sched):
        for platform, at in unit.platforms.items():
            out.setdefault(platform, []).append(at)
    return {p: sorted(ts) for p, ts in out.items()}


def unit_by_id(item_id: str) -> Unit:
    d = date.fromisoformat(item_id[:10])
    return next(u for u in day_units(d) if u.id == item_id)
