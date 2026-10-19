"""Step 2: download channel and video data from the YouTube Data API v3.

Flow (only cheap calls, no search.list):
  1. channels.list      -> stats + uploads playlist ID, up to 50 channels per call
  2. playlistItems.list -> newest video IDs in each uploads playlist, 50 per call
  3. videos.list        -> details + stats for those IDs, 50 per call

Every API response is saved as JSON in data/raw/<run_id>/ BEFORE we use it.
If a file already exists, we read it from disk instead of calling the API. So:
  - later steps (database, cleaning, analysis) never need the API again
  - if a run stops (quota, no internet), running it again continues where it stopped

Run: double-click collect.bat  (or: .venv\\Scripts\\python.exe src\\collect.py)
Add --new to force a fresh snapshot.
"""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone

from config import CHANNELS_CSV, MAX_VIDEOS_PER_CHANNEL, RAW_DIR
from youtube_api import ApiError, NotFoundError, QuotaExceededError, YouTubeClient

BATCH_SIZE = 50  # API maximum per call for channels, playlistItems and videos


# ---------- small file helpers ----------

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # write to a temp file, then rename: a crash never leaves half a file


def chunks(items, size):
    """Split a list into pieces: chunks([1,2,3,4,5], 2) -> [1,2], [3,4], [5]."""
    for i in range(0, len(items), size):
        yield items[i:i + size]


# ---------- API calls with a disk cache ----------

class Collector:
    def __init__(self, run_dir, client):
        self.run_dir = run_dir
        self.client = client
        self.from_api = 0
        self.from_disk = 0

    def fetch(self, rel_path, endpoint, params):
        """Return a saved response from disk if we have it, else call YouTube and save it."""
        path = self.run_dir / rel_path
        if path.exists():
            self.from_disk += 1
            return read_json(path)["response"]

        response = self.client.get(endpoint, params)
        self.from_api += 1
        write_json(path, {
            "endpoint": endpoint,
            "params": params,         # no key in here: it travels in a request header
            "fetched_at": utc_now(),  # when these numbers were true (views change every day)
            "response": response,
        })
        return response


def get_channels(col, channel_ids):
    """Channel stats + uploads playlist ID. Returns {channel_id: raw channel item}."""
    found = {}
    for n, batch in enumerate(chunks(channel_ids, BATCH_SIZE), start=1):
        data = col.fetch(f"channels/batch{n}.json", "channels", {
            "part": "snippet,contentDetails,statistics",
            "id": ",".join(batch),
            "maxResults": BATCH_SIZE,
        })
        for item in data.get("items", []):
            found[item["id"]] = item
    return found


def get_video_ids(col, channel_id, uploads_playlist_id, limit):
    """Newest video IDs from a channel's uploads playlist (newest first)."""
    ids, page_token, page = [], None, 1
    while len(ids) < limit:
        params = {"part": "contentDetails", "playlistId": uploads_playlist_id,
                  "maxResults": BATCH_SIZE}
        if page_token:
            params["pageToken"] = page_token  # "give me the next 50"
        data = col.fetch(f"playlists/{channel_id}_page{page}.json", "playlistItems", params)
        ids += [item["contentDetails"]["videoId"] for item in data.get("items", [])]

        page_token = data.get("nextPageToken")
        if not page_token:
            break  # no more pages: channel has fewer videos than the limit
        page += 1
    # dict.fromkeys removes duplicates but keeps the order
    return list(dict.fromkeys(ids))[:limit]


def get_videos(col, channel_id, video_ids):
    """Full video details in batches of 50 IDs per call."""
    videos = []
    for n, batch in enumerate(chunks(video_ids, BATCH_SIZE), start=1):
        data = col.fetch(f"videos/{channel_id}_batch{n}.json", "videos", {
            # liveStreamingDetails is free to add and tells us which videos were live streams
            "part": "snippet,contentDetails,statistics,liveStreamingDetails",
            "id": ",".join(batch),
            "maxResults": BATCH_SIZE,
        })
        videos += data.get("items", [])
    return videos


# ---------- run folders (one folder = one snapshot) ----------

def ask_yes_no(question):
    try:
        return input(question).strip().lower() in ("y", "yes")
    except EOFError:  # no keyboard (e.g. run by another program): treat as "no"
        return False


def pick_run_dir(force_new):
    """Resume an unfinished run, or start a new one. Returns (folder, manifest) or (None, None)."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    runs = sorted(p for p in RAW_DIR.iterdir() if (p / "manifest.json").exists())

    if runs and not force_new:
        last = runs[-1]
        manifest = read_json(last / "manifest.json")
        if manifest["status"] != "complete":
            print(f"Continuing unfinished run {last.name} (saved files are reused, no quota).")
            return last, manifest
        print(f"Latest complete snapshot: {last.name} ({manifest['video_count']} videos).")
        if not ask_yes_no("Download a NEW snapshot? About 121 quota units. [y/N]: "):
            return None, None

    run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = RAW_DIR / run_id
    manifest = {
        "run_id": run_id,
        "started_at": utc_now(),
        "status": "in_progress",
        "max_videos_per_channel": MAX_VIDEOS_PER_CHANNEL,
        "api_units_used": 0,
        "video_count": 0,
        "channels": {},
    }
    write_json(run_dir / "manifest.json", manifest)
    print(f"Starting new snapshot {run_id}")
    return run_dir, manifest


# ---------- summary of missing fields ----------

def print_summary(run_dir):
    """Count the gaps we must handle in cleaning. Missing is NOT the same as zero."""
    videos = []
    for f in sorted((run_dir / "videos").glob("*.json")):
        videos += read_json(f)["response"].get("items", [])
    stats = [v.get("statistics", {}) for v in videos]

    print("\nMissing fields (they stay missing in the raw data; we decide how to treat them in Step 4):")
    print(f"  likes hidden by creator        : {sum('likeCount' not in s for s in stats)}")
    print(f"  comments turned off            : {sum('commentCount' not in s for s in stats)}")
    print(f"  no tags                        : {sum(not v['snippet'].get('tags') for v in videos)}")
    print(f"  were live streams / premieres  : {sum('liveStreamingDetails' in v for v in videos)}")
    print(f"  scheduled, not yet published   : "
          f"{sum(v['snippet'].get('liveBroadcastContent') == 'upcoming' for v in videos)}")


# ---------- main ----------

def main():
    sys.stdout.reconfigure(errors="replace")  # never crash on an emoji in a channel name
    parser = argparse.ArgumentParser(description="Collect YouTube channel and video data.")
    parser.add_argument("--new", action="store_true", help="start a fresh snapshot")
    args = parser.parse_args()

    with open(CHANNELS_CSV, newline="", encoding="utf-8") as f:
        channel_ids = [row["channel_id"].strip() for row in csv.DictReader(f)]

    run_dir, manifest = pick_run_dir(args.new)
    if run_dir is None:
        print("Nothing downloaded. The existing snapshot is kept.")
        return 0

    try:
        client = YouTubeClient()
    except ApiError as exc:
        print(f"STOPPED: {exc}")
        return 1
    col = Collector(run_dir, client)
    exit_code = 0

    try:
        channels = get_channels(col, channel_ids)
        for i, cid in enumerate(channel_ids, start=1):
            ch = channels.get(cid)
            if ch is None:
                print(f"[{i:2}/{len(channel_ids)}] {cid}: NOT FOUND on YouTube, skipped. Check config/channels.csv")
                manifest["channels"][cid] = {"error": "channel not found"}
                continue

            name = ch["snippet"]["title"]
            uploads_id = ch["contentDetails"]["relatedPlaylists"]["uploads"]
            try:
                ids = get_video_ids(col, cid, uploads_id, MAX_VIDEOS_PER_CHANNEL)
                videos = get_videos(col, cid, ids)
            except NotFoundError as exc:
                print(f"[{i:2}/{len(channel_ids)}] {name}: uploads playlist not found ({exc}), skipped")
                manifest["channels"][cid] = {"name": name, "error": str(exc)}
                continue

            # IDs listed but not returned = private or deleted since listing
            gone = len(ids) - len(videos)
            note = f"  ({gone} private/deleted)" if gone else ""
            print(f"[{i:2}/{len(channel_ids)}] {name:<20} {len(videos):>3} videos{note}")
            manifest["channels"][cid] = {"name": name, "ids_listed": len(ids), "videos_saved": len(videos)}

        manifest["status"] = "complete"
        manifest["finished_at"] = utc_now()
        manifest["video_count"] = sum(c.get("videos_saved", 0) for c in manifest["channels"].values())

    except QuotaExceededError:
        print("\nSTOPPED: daily quota used up. Everything downloaded so far is saved.")
        print("Run collect.bat again after the reset (midnight Pacific = about 14:00-15:00 Jakarta).")
        print("It will continue where it stopped.")
        exit_code = 1
    except ApiError as exc:
        print(f"\nSTOPPED: {exc}")
        print("Everything downloaded so far is saved. Fix the problem, then run collect.bat again.")
        exit_code = 1
    finally:
        # Always save progress, even after an error
        manifest["api_units_used"] += client.units_used
        manifest["updated_at"] = utc_now()
        write_json(run_dir / "manifest.json", manifest)

    print(f"\nAPI calls this time: {col.from_api} (about {client.units_used} quota units)."
          f" Read from saved files: {col.from_disk}.")
    if manifest["status"] == "complete":
        print(f"Done: {manifest['video_count']} videos saved in data/raw/{run_dir.name}/")
        print_summary(run_dir)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
