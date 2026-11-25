"""Structured-output schemas shared between agents (Claude returns these directly)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Pillar = Literal["now_explained", "how_it_works", "myths_factchecks"]   # style v2 pillars (cartoon-era ones deleted)
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
    on_screen_hook_text: str = ""  # the hook line shown on screen, corrected (numbers/claims must match)


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
    kind: Literal["long_form", "vertical", "carousel"]   # all of a kind's platforms post at these times
    slots: list[str]                                      # HH:MM PHT, one per daily piece


class CreativeNotes(BaseModel):
    summary: str                  # what the review team keeps flagging, in two or three sentences
    agent_notes: list[AgentNote]  # standing notes per design agent (replaces that agent's previous notes)


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
    major_scenes: list[str] = []  # scene ids with a major narration problem this round
    redo_images: dict[str, str]   # "scene id" / "thumbnail" / "slide N" -> corrected prompt
    redo_audio: dict[str, str]    # scene id -> tts text ("" = just re-voice)
    warnings: list[str]
    appeal: int
    hook_frame: int
    summary: str
    improve: dict[str, str] = {}  # not blocking, but worth another pass when appeal is low: key -> what to improve


# ---------- Sound ----------
class MusicCue(BaseModel):
    from_scene: int               # scene id where this mood starts
    mood: str                     # a music key from the library


class SfxCue(BaseModel):
    scene_id: int
    anchor_word: str              # the word in that scene the effect lands on
    sound: str                    # an effect key from the library


class SoundPlan(BaseModel):
    music: list[MusicCue]
    sfx: list[SfxCue]


# ---------- Vector engine (Motion Designer / Visual Critic) ----------
Who = Literal["kuya_standard", "juan", "tito_trapo", "official", "senator", "judge", "police", "citizen", "woman",
              "elder", "child", "farmer", "vendor", "ofw", "student", "nurse", "worker", "silhouette"]
Pose = Literal["stand", "wave", "point", "shrug", "arms_up", "think", "facepalm", "hands_on_hips", "hold", "walk",
               "cheer", "cross_arms"]
Expression = Literal["neutral", "happy", "worried", "angry", "shocked", "smug", "sad", "confused"]
Enter = Literal["none", "pop", "slide_left", "slide_right", "drop", "fade"]
Background = Literal["plain", "spotlight", "office", "senate", "courtroom", "street", "barangay_hall", "province",
                     "city_night", "flood", "newsroom", "kitchen", "airport", "classroom", "history_spanish"]


class Actor(BaseModel):
    who: Who
    label: str                    # silhouettes/roles only, e.g. "SENATOR" ("" otherwise)
    x: float                      # 0..1 across the frame (centre of the figure)
    scale: float                  # figure height as a fraction of frame height (0.25–0.6)
    row: Literal["front", "back"]
    pose: Pose
    expression: Expression
    speaking: bool                # lip-flap on the narration (only the on-screen speaker)
    facing: Literal["left", "right"]
    enter: Enter
    holds: str                    # emoji key held in hand, or ""


class Prop(BaseModel):
    emoji: str                    # key from the emoji library
    x: float
    y: float                      # 0..1 (centre)
    size: float                   # fraction of the short side (0.08–0.35)
    enter: Enter
    motion: Literal["none", "float", "spin", "shake", "pulse", "rain"]
    count: int                    # copies (stack/row; for rain the number of drops)
    at: float                     # 0..1 of the scene when it appears


class Bubble(BaseModel):
    actor: int                    # index into actors
    text: str                     # English, <= 10 words
    at: float


class ScenePlan(BaseModel):
    scene_id: int
    kind: Literal["scene", "card"]
    background: Background
    camera: Literal["push_in", "pull_out", "pan_left", "pan_right", "shake", "static"]
    actors: list[Actor]
    props: list[Prop]
    bubbles: list[Bubble]
    card_type: Literal["stat", "bars", "quote", "timeline", "document", "map", "none"]
    card_title: str
    card_lines: list[str]


class MotionPlan(BaseModel):
    look: Literal["flat", "doodle"]
    scenes: list[ScenePlan]


class SceneCritique(BaseModel):
    scene_id: int
    ok: bool
    problems: list[str]           # what is wrong in the still, concretely


class VisualCritique(BaseModel):
    scenes: list[SceneCritique]
    notes: list[str]


# ---------------------------------------------------------------- atlas engine (style v2, 2026-11-24)
class AtlasItem(BaseModel):
    """One entry of a cards, bars, timeline, seats, checklist, chart, date-card, side-list or chip list (fill only
    the fields that kind uses)."""
    big: str = ""                 # cards: the number or short phrase ("6 YEARS", "0"); dates: the day ("17")
    small: str = ""               # cards: one plain line under it; dates: what happens that day
    color: Literal["red", "ink", "teal", "gold", ""] = ""
    label: str = ""               # bars / seats / barchart / linechart: what the row or point is; dates: month
    value: str = ""               # bars / barchart: the value text ("1/3 OF ALL MEMBERS", "₱1.37T")
    frac: float = 0.0             # bars: 0..1 fill
    num: float = 0.0              # barchart / linechart: the plotted number
    count: int = 0                # seats: filled dots
    of: int = 0                   # seats: total dots
    date: str = ""                # timeline: "7 DEC 2000"
    text: str = ""                # timeline: what happened; checklist row; side-list row; chip
    mark: Literal["tick", "x", "warn", ""] = ""   # checklist: covered / true (tick), not (x), partly (warn)
    at_word: str = ""             # builds on this word of the scene (checklist rows, bars, dates, list rows, chips)


class AtlasSide(BaseModel):
    name: str = ""
    big: str = ""
    small: str = ""


class AtlasShot(BaseModel):
    k: Literal["map", "bigtext", "title", "doc", "cards", "bars", "timeline", "compare", "seats", "split", "broll",
               "globe", "checklist", "linechart", "barchart", "waffle", "balance", "dates", "media"]
    at_word: str = ""             # starts when this word of the scene is spoken; "" = scene start
    text: str = ""                # bigtext / title / split middle
    sub: str = ""
    kicker: str = ""
    items: list[AtlasItem] = []
    head: str = ""                # doc: the document's name ("THE 1987 CONSTITUTION")
    sec: str = ""                 # doc: the section ("ARTICLE XI, SECTION 3")
    body: str = ""                # doc: EXACT quoted text from the dossier, never paraphrased
    hl: list[str] = []            # doc: exact substrings of body to highlight
    src: str = ""                 # source badge ("1987 Constitution, Art. VII, Sec. 4")
    view: Literal["", "ph", "nz", "both", "luzon", "visayas", "mindanao", "ncr"] = ""
    fill: Literal["", "ph", "nz"] = ""
    draw: bool = False
    label: str = ""               # map: yellow label
    left: str = ""                # split: left (red, Philippines) heading
    right: str = ""               # split: right (teal, comparison) heading
    ph: AtlasSide = AtlasSide()   # compare
    nz: AtlasSide = AtlasSide()   # compare
    foot: str = ""                # timeline footer
    broll_query: str = ""         # broll: Wikimedia Commons search (place or object, never a living person)
    word: str = ""                # broll: brick-red word pill
    hero: bool = False            # broll: the 3D Metro Manila push (long-form, at most one)
    # ---- Atlas blocks v3 (2026-11-25): every field below is optional and word-anchored
    stamp: str = ""               # any shot: a slammed English label ("VOLUNTARY", "FALSE", "ALLEGED"), at most 3 words
    stamp_word: str = ""          # the word the stamp lands on ("" = 0.5 s into the shot)
    stamp_color: Literal["red", "teal", "ink", "gold", ""] = ""
    focus: str = ""               # globe: country or city the globe turns and zooms to ("Philippines", "Manila")
    zoom: float = 0.0             # globe: 1 = whole globe, about 2.5 = a region (0 = default 2.6)
    highlight: list[str] = []     # globe: countries that glow red, in order ("Philippines", "Japan")
    places: list[str] = []        # globe: city dots with labels ("Manila", "Tokyo")
    arcs: list[str] = []          # globe: routes "FROM > TO" between places ("Manila > Dubai")
    big: str = ""                 # linechart headline number counted up with the line; balance / waffle number
    small: str = ""               # balance / waffle: the tag under the number ("AN AVERAGE, NOT A BILL")
    frac: float = 0.0             # waffle / balance: the share 0..1 that fills
    callout: str = ""             # linechart: end-dot callout ("+12.6%"); barchart: the arrow tag ("ALMOST 3X")
    callout_word: str = ""        # the word the callout lands on
    big_word: str = ""            # the spoken word of the key number (linechart draw, waffle and balance label)
    name: str = ""                # media: lower third name or role ("SENATE FINANCE COMMITTEE")
    role: str = ""                # media: lower third second line
    icon: Literal["", "person", "building", "house", "coins", "document", "ballot"] = ""  # media: drawn stand-in
    rows: list[AtlasItem] = []    # media: 2 to 4 side-list rows (`text`, `color`, `at_word`)
    chips: list[AtlasItem] = []   # media: honesty chips ("ILLUSTRATIVE", "ALLEGED · NOT PROVEN") on their word


class AtlasScene(BaseModel):
    scene_id: int
    shots: list[AtlasShot]
    key_words: list[str] = []     # caption words boxed in TFS red or gold, one per sentence, copied from the text


class AtlasPlan(BaseModel):
    scenes: list[AtlasScene]
