"""Fetch a fresh YouTube snapshot for Streamlit Cloud without writing API data to disk.

The local collector keeps raw JSON for reproducibility. Cloud mode intentionally does
not: it fetches public data into memory, builds features, and lets Streamlit's short
cache expire. One refresh costs about 121 quota units for 15 channels x 200 videos.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from collect import BATCH_SIZE, chunks
from config import CHANNELS_CSV, MAX_VIDEOS_PER_CHANNEL
from load_db import channel_row, video_row
from youtube_api import YouTubeClient


CLOUD_SNAPSHOT_PREFIX = "cloud"


def read_channel_ids(path: Path = CHANNELS_CSV) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [row["channel_id"].strip() for row in csv.DictReader(handle)]


def fetch_cloud_raw(api_key: str) -> pd.DataFrame:
    """Fetch current public rows in memory and return the features.py input shape."""
    client = YouTubeClient(api_key=api_key)
    channel_ids = read_channel_ids()
    snapshot_id = f"{CLOUD_SNAPSHOT_PREFIX}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    channels = {}
    for batch in chunks(channel_ids, BATCH_SIZE):
        response = client.get("channels", {
            "part": "snippet,contentDetails,statistics",
            "id": ",".join(batch),
            "maxResults": BATCH_SIZE,
        })
        channels.update({item["id"]: item for item in response.get("items", [])})

    rows = []
    for channel_id in channel_ids:
        channel = channels.get(channel_id)
        if not channel:
            continue
        channel_info = channel_row(channel, snapshot_id, collected_at)
        uploads_id = channel_info["uploads_playlist_id"]
        video_ids: list[str] = []
        page_token = None
        page = 0
        while len(video_ids) < MAX_VIDEOS_PER_CHANNEL:
            params = {
                "part": "contentDetails",
                "playlistId": uploads_id,
                "maxResults": BATCH_SIZE,
            }
            if page_token:
                params["pageToken"] = page_token
            response = client.get("playlistItems", params)
            video_ids.extend(
                item["contentDetails"]["videoId"]
                for item in response.get("items", [])
                if item.get("contentDetails", {}).get("videoId")
            )
            page_token = response.get("nextPageToken")
            page += 1
            if not page_token:
                break
        video_ids = list(dict.fromkeys(video_ids))[:MAX_VIDEOS_PER_CHANNEL]

        videos = []
        for batch in chunks(video_ids, BATCH_SIZE):
            response = client.get("videos", {
                "part": "snippet,contentDetails,statistics,liveStreamingDetails",
                "id": ",".join(batch),
                "maxResults": BATCH_SIZE,
            })
            videos.extend(response.get("items", []))
        for item in videos:
            row = video_row(item, snapshot_id, collected_at)
            row["channel_name"] = channel_info["channel_name"]
            row["subscriber_count"] = channel_info["subscriber_count"]
            rows.append(row)

    if not rows:
        raise RuntimeError("YouTube returned no videos for configured channels.")
    return pd.DataFrame(rows)
