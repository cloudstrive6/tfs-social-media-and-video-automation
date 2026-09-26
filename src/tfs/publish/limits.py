"""Platform metadata rules, enforced where metadata is written (SEO writer) and again right before upload.

YouTube (developers.google.com/youtube/v3/docs/videos):
- title: max 100 characters, any UTF-8 except < and >
- description: max 5000 BYTES (₱ is 3 bytes, emoji 4), any UTF-8 except < and >
- tags: the whole list max 500 characters; the commas between tags count, and a tag containing a space counts
  as if wrapped in quotes (+2). A list over the limit rejects the entire upload ("invalidTags").
Instagram: caption max 2200 characters, max 30 hashtags (more fails the post), max 20 @mentions.
TikTok: caption max 2200 characters.
"""
from __future__ import annotations

import re

YT_TITLE, YT_DESC_BYTES, YT_TAGS = 100, 5000, 500
IG_CAPTION, IG_HASHTAGS, IG_MENTIONS = 2200, 30, 20
TIKTOK_CAPTION = 2200
HASHTAG = re.compile(r"(?<!\w)#\w+")
MENTION = re.compile(r"(?<!\w)@\w+")


def _no_angle(text: str) -> str:
    return (text or "").replace("<", "‹").replace(">", "›")


def _cut_chars(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit * 0.7 else cut).rstrip(" ,;:-—") + "…"[:max(0, limit - len(cut))]


def youtube_title(title: str) -> str:
    t = re.sub(r"\s+", " ", _no_angle(title)).strip()
    return _cut_chars(t, YT_TITLE)[:YT_TITLE]


def youtube_description(text: str) -> str:
    d = _no_angle(text)
    data = d.encode("utf-8")
    if len(data) <= YT_DESC_BYTES:
        return d
    cut = data[:YT_DESC_BYTES].decode("utf-8", errors="ignore")      # never split a multi-byte character
    line = cut.rfind("\n")
    return cut[:line] if line > len(cut) * 0.8 else cut


def youtube_tags(tags: list[str], budget: int = YT_TAGS) -> list[str]:
    """Keep the best tags (in order) that fit YouTube's counting rules exactly."""
    out, seen, used = [], set(), 0
    for tag in tags:
        t = re.sub(r"[<>#,\"]", "", tag or "")
        t = re.sub(r"\s+", " ", t).strip()
        if not t or t.lower() in seen:
            continue
        cost = len(t) + (2 if " " in t else 0) + (1 if out else 0)
        if used + cost > budget:
            continue
        out.append(t)
        seen.add(t.lower())
        used += cost
    return out


def tags_length(tags: list[str]) -> int:
    return sum(len(t) + (2 if " " in t else 0) for t in tags) + max(0, len(tags) - 1)


def _keep_first(pattern: re.Pattern, text: str, limit: int) -> str:
    count = 0

    def sub(m: re.Match) -> str:
        nonlocal count
        count += 1
        return m.group() if count <= limit else ""
    return re.sub(r"[ \t]{2,}", " ", pattern.sub(sub, text))


def instagram_caption(text: str) -> str:
    t = _keep_first(HASHTAG, text or "", IG_HASHTAGS)
    t = _keep_first(MENTION, t, IG_MENTIONS)
    return _cut_chars(t, IG_CAPTION)[:IG_CAPTION]


def tiktok_caption(text: str) -> str:
    return _cut_chars(text or "", TIKTOK_CAPTION)[:TIKTOK_CAPTION]


def enforce_seo(pack):
    """Return a copy of a SeoPack that every platform will accept."""
    return pack.model_copy(update={
        "youtube_description": youtube_description(pack.youtube_description),
        "tags": youtube_tags(pack.tags),
        "shorts_title": youtube_title(pack.shorts_title),
        "instagram_caption": instagram_caption(pack.instagram_caption),
        "tiktok_caption": tiktok_caption(pack.tiktok_caption),
    })
