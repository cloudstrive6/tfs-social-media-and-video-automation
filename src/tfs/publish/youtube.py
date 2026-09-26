"""YouTube uploads (long form + Shorts) with native scheduling, thumbnails and AI disclosure.

Quota (Sep 2026): uploads use their own "Video Uploads per day" bucket (100/day by default);
thumbnails.set and videos.list use the regular 10,000 units/day. Our cadence (4 uploads/day) is far below both.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from ..config import now, require_env

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def _creds() -> Credentials:
    return Credentials(None, refresh_token=require_env("YOUTUBE_REFRESH_TOKEN"),
                       token_uri="https://oauth2.googleapis.com/token",
                       client_id=require_env("YOUTUBE_CLIENT_ID"),
                       client_secret=require_env("YOUTUBE_CLIENT_SECRET"), scopes=SCOPES)


@lru_cache
def api():
    return build("youtube", "v3", credentials=_creds(), cache_discovery=False)


@lru_cache
def analytics_api():
    return build("youtubeAnalytics", "v2", credentials=_creds(), cache_discovery=False)


def authorize() -> str:
    """One-time interactive consent; prints the refresh token to store as YOUTUBE_REFRESH_TOKEN."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config({"installed": {
        "client_id": require_env("YOUTUBE_CLIENT_ID"), "client_secret": require_env("YOUTUBE_CLIENT_SECRET"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"]}}, SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    return creds.refresh_token


def clean_tags(tags: list[str]) -> list[str]:
    from .limits import youtube_tags
    return youtube_tags(tags)


def upload(video: Path, title: str, description: str, tags: list[str], publish_at: datetime,
           thumbnail: Path | None = None, category_id: str = "27") -> str:
    from .limits import youtube_description, youtube_tags, youtube_title

    status = {"selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}
    if publish_at > now():
        status |= {"privacyStatus": "private",
                   "publishAt": publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    else:
        status["privacyStatus"] = "public"
    body = {
        "snippet": {"title": youtube_title(title), "description": youtube_description(description),
                    "tags": youtube_tags(tags),
                    "categoryId": category_id, "defaultLanguage": "fil", "defaultAudioLanguage": "fil"},
        "status": status,
    }
    request = api().videos().insert(part="snippet,status", body=body, notifySubscribers=True,
                                    media_body=MediaFileUpload(str(video), mimetype="video/mp4",
                                                               chunksize=16 * 1024 * 1024, resumable=True))
    response = None
    while response is None:
        _, response = request.next_chunk()
    video_id = response["id"]
    if thumbnail:
        api().thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumbnail))).execute()
    return video_id


def video_status(video_id: str) -> dict:
    items = api().videos().list(part="status", id=video_id).execute().get("items", [])
    return items[0]["status"] if items else {}


def update_title(video_id: str, title: str) -> None:
    item = api().videos().list(part="snippet", id=video_id).execute()["items"][0]
    from .limits import youtube_title
    snippet = item["snippet"] | {"title": youtube_title(title)}
    api().videos().update(part="snippet", body={"id": video_id, "snippet": snippet}).execute()


def unschedule(video_id: str) -> None:
    """Keep an uploaded video private and cancel its scheduled publish (nothing is deleted)."""
    status = {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}
    api().videos().update(part="status", body={"id": video_id, "status": status}).execute()
