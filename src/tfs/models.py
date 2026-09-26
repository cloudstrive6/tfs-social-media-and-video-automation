"""Structured-output schemas shared between agents (Claude returns these directly)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Pillar = Literal["now_explained", "history_retold", "why_were_like_this", "myths_factchecks"]
Kind = Literal["long_form", "vertical", "carousel"]


# ---------- Trend Scout ----------
class TrendTopic(BaseModel):
    title: str
    angle: str                    # the Filipino Standard framing
    pillar: Pillar
    why_now: str                  # the acceleration evidence
    predicted_peak: str           # e.g. "in 1–3 days", "Sept 21 (anniversary)"
    momentum_score: int           # 0–100, acceleration not size
    evergreen_score: int          # 0–100, will it still get searched in 6 months?
    legal_risk: Literal["low", "medium", "high"]
    search_keywords: list[str]
    evidence: list[str]           # which signals supported this


class TrendReport(BaseModel):
    topics: list[TrendTopic]


# ---------- Editor-in-Chief ----------
class SlateItem(BaseModel):
    slot_id: str                  # echoed back from the request
    topic_id: int                 # from the topic pool, or 0 for an evergreen idea
    working_title: str
    pillar: Pillar
    primary_keyword: str
    brief: str
    legal_risk: Literal["low", "medium", "high"]


class Slate(BaseModel):
    items: list[SlateItem]


# ---------- Script ----------
class Scene(BaseModel):
    id: int
    chapter: str                  # chapter name ("Cold open", "Hook", "Chapter 1: …")
    speaker: str                  # NARRATOR, JUAN, TITO_TRAPO, …
    text: str                     # spoken words with delivery cues
    visual: str                   # what's on screen


class Script(BaseModel):
    scenes: list[Scene]
    sources: list[str]            # "[S1] Title — Outlet — Date — URL"


class HookReview(BaseModel):
    script: Script
    hook_score: int
    retention_score: int
    on_screen_hook_text: str      # ≤8 words, used on vertical first frame / carousel cover
    fixes: list[str]


class FactIssue(BaseModel):
    line: str
    problem: str
    fix: str


class FactCheck(BaseModel):
    verdict: Literal["pass", "pass_with_edits", "needs_human", "reject"]
    script: Script
    issues: list[FactIssue]
    names_living_person_with_allegation: bool


# ---------- Packaging ----------
class ThumbConcept(BaseModel):
    moment: str
    composition: str
    colors: str
    image_prompt: str
    overlay_text: str             # "" for no text
    ctr_rationale: str


class ThumbnailPlan(BaseModel):
    concepts: list[ThumbConcept]  # ranked best first


class TitleOption(BaseModel):
    title: str
    curiosity: int
    clarity: int
    keyword_fit: int
    honesty: int


class TitlePlan(BaseModel):
    options: list[TitleOption]
    primary: str
    alternates: list[str]


class SeoPack(BaseModel):
    youtube_description: str
    tags: list[str]
    shorts_title: str
    instagram_caption: str
    facebook_caption: str
    tiktok_caption: str


# ---------- Visuals ----------
Style = Literal["story", "satire", "comic", "archival"]


class Shot(BaseModel):
    scene_id: int
    kind: Literal["illustration", "card", "reuse"]
    style: Style                  # illustration only; ignored for cards
    image_prompt: str             # illustration only
    card_type: Literal["stat", "bars", "quote", "timeline", "document", "map", "none"]
    card_title: str
    card_lines: list[str]
    reuse_of_scene: int           # reuse only, else 0
    motion: Literal["push_in", "pull_out", "pan_left", "pan_right", "shake", "static"]


class ShotList(BaseModel):
    shots: list[Shot]


# ---------- Carousel ----------
class Slide(BaseModel):
    layout: Literal["cover", "panel", "text"]   # panel = full-bleed comic art + caption box + speech bubble
    headline: str                 # cover/text: headline · panel: caption box text
    body: str                     # cover/text: body · panel: speech-bubble line ("" = none)
    source: str
    theme: Literal["dark", "flag_blue", "flag_red", "paper"]
    image_prompt: str             # "" = no illustration, typographic slide
    style: Style


class Carousel(BaseModel):
    format: Literal["comic", "explainer", "single"]
    slides: list[Slide]


# ---------- Analyst ----------
class AgentNote(BaseModel):
    agent: str
    notes: list[str]


class SlotChange(BaseModel):
    platform: str
    slots: list[str]


class AnalystReport(BaseModel):
    summary_markdown: str
    agent_notes: list[AgentNote]
    schedule_changes: list[SlotChange]
    title_swaps: list[str]        # "videoId | new title"


# ---------- Review team (after render, before scheduling) ----------
class AudioVerdict(BaseModel):
    scene_id: int
    ok: bool
    severity: Literal["none", "minor", "major"]   # major = wrong number/name/fact, skipped phrase, garbled line
    problem: str                  # "" if ok
    tts_text: str                 # "" or the scene text respelled so the narrator says it right (numbers, names)


class AudioQA(BaseModel):
    scenes: list[AudioVerdict]
    summary: str


class ShotVerdict(BaseModel):
    frame: str                    # the frame label as given (e.g. "scene 12", "thumbnail", "slide 3", "hook")
    ok: bool
    blocking: bool                # must be fixed before posting
    problems: list[str]
    fix_prompt: str               # full corrected image prompt for an AI illustration, else ""


class VisualQA(BaseModel):
    frames: list[ShotVerdict]
    appeal_score: int             # 1-10: would a Filipino scrolling at 11pm stop for this?
    hook_frame_score: int         # 1-10: the first frame alone
    notes: list[str]


class ReviewReport(BaseModel):
    passed: bool
    major_audio: bool = False     # a wrong number/name/skipped phrase remains (minor slips never reject)
    redo_images: dict[str, str]   # "scene id" / "thumbnail" / "slide N" -> corrected prompt
    redo_audio: dict[str, str]    # scene id -> tts text ("" = just re-voice)
    warnings: list[str]
    appeal: int
    hook_frame: int
    summary: str
