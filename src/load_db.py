"""Step 3: load the raw JSON snapshots from data/raw/ into SQLite (db/youtube.db).

No API calls and no quota: this only reads the files collect.py saved.

Why duplicates cannot happen:
  1. Each table has a PRIMARY KEY, e.g. videos = (video_id, snapshot_id),
     so the database itself refuses a second copy of the same row.
  2. Rows are written with an "upsert": INSERT ... ON CONFLICT DO UPDATE.
     New key -> insert a row. Existing key -> update that row in place.
So you can run this as often as you like. Row counts only grow when
collect.py has downloaded a NEW snapshot.

Run: double-click load_db.bat (or: .venv\\Scripts\\python.exe src\\load_db.py)
"""
import json
import sys
from datetime import datetime, timezone

from config import DB_PATH, RAW_DIR
from db import connect, create_schema


# ---------- turning API JSON into table rows ----------

def to_int(value):
    """The API sends numbers as text ("12345"). Missing stays None (SQL NULL), never 0."""
    return None if value is None else int(value)


def channel_row(item, snapshot_id, collected_at):
    snippet = item["snippet"]
    stats = item.get("statistics", {})
    hidden = stats.get("hiddenSubscriberCount", False)
    return {
        "channel_id": item["id"],
        "snapshot_id": snapshot_id,
        "collected_at": collected_at,
        "channel_name": snippet["title"],
        "handle": snippet.get("customUrl"),
        "country": snippet.get("country"),
        "channel_created_at": snippet.get("publishedAt"),
        "uploads_playlist_id": item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"),
        "subscriber_count": None if hidden else to_int(stats.get("subscriberCount")),
        "video_count": to_int(stats.get("videoCount")),
        "view_count": to_int(stats.get("viewCount")),
    }


def video_row(item, snapshot_id, collected_at):
    snippet = item["snippet"]
    details = item.get("contentDetails", {})
    stats = item.get("statistics", {})
    caption = details.get("caption")  # the TEXT "true"/"false", not a real boolean
    return {
        "video_id": item["id"],
        "snapshot_id": snapshot_id,
        "collected_at": collected_at,
        "channel_id": snippet["channelId"],
        "title": snippet["title"],
        "description": snippet.get("description"),
        # No "tags" key = the creator added none, so an empty list is the truth here.
        # (Different from likes: a missing likeCount means "unknown", not "zero".)
        "tags": json.dumps(snippet.get("tags", []), ensure_ascii=False),
        "published_at": snippet["publishedAt"],
        "duration_iso": details.get("duration"),
        "category_id": to_int(snippet.get("categoryId")),
        "audio_language": snippet.get("defaultAudioLanguage"),
        "definition": details.get("definition"),
        # Careful: bool("false") is True in Python, so compare the text instead
        "has_captions": None if caption is None else int(caption == "true"),
        "was_live": int("liveStreamingDetails" in item),
        "broadcast_status": snippet.get("liveBroadcastContent"),
        "view_count": to_int(stats.get("viewCount")),
        "like_count": to_int(stats.get("likeCount")),
        "comment_count": to_int(stats.get("commentCount")),
    }


def read_items(folder):
    """Yield (fetched_at, item) for every item in every saved response in a folder."""
    for path in sorted(folder.glob("*.json")):
        saved = json.loads(path.read_text(encoding="utf-8"))
        for item in saved["response"].get("items", []):
            yield saved["fetched_at"], item


# ---------- writing rows ----------

def upsert_sql(table, columns, key_columns):
    """Build an upsert, e.g. for columns a, b, c with key a:

    INSERT INTO t (a, b, c) VALUES (:a, :b, :c)
    ON CONFLICT (a) DO UPDATE SET b = excluded.b, c = excluded.c

    "excluded" = the new row that could not be inserted because the key exists.
    :a, :b are named placeholders: sqlite3 fills them from a dict and escapes
    the values safely (never build SQL by pasting values into the string).
    """
    cols = ", ".join(columns)
    values = ", ".join(f":{c}" for c in columns)
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c not in key_columns)
    return (f"INSERT INTO {table} ({cols}) VALUES ({values}) "
            f"ON CONFLICT ({', '.join(key_columns)}) DO UPDATE SET {updates}")


def count_rows(conn, table, snapshot_id):
    sql = f"SELECT COUNT(*) FROM {table} WHERE snapshot_id = ?"
    return conn.execute(sql, (snapshot_id,)).fetchone()[0]


def load_snapshot(conn, run_dir, manifest):
    sid = manifest["run_id"]
    channel_rows = [channel_row(item, sid, at) for at, item in read_items(run_dir / "channels")]
    video_rows = [video_row(item, sid, at) for at, item in read_items(run_dir / "videos")]
    snapshot_row = {
        "snapshot_id": sid,
        "started_at": manifest["started_at"],
        "finished_at": manifest.get("finished_at"),
        "api_units_used": manifest.get("api_units_used"),
        "channel_count": len(channel_rows),
        "video_count": len(video_rows),
        "loaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    before = {t: count_rows(conn, t, sid) for t in ("channels", "videos")}

    # "with conn" = one transaction: the whole snapshot is saved, or (on any error) nothing is.
    # Order matters: the parent row (snapshot) must exist before rows that point to it.
    with conn:
        conn.execute(upsert_sql("snapshots", list(snapshot_row), ["snapshot_id"]), snapshot_row)
        conn.executemany(upsert_sql("channels", list(channel_rows[0]), ["channel_id", "snapshot_id"]),
                         channel_rows)
        conn.executemany(upsert_sql("videos", list(video_rows[0]), ["video_id", "snapshot_id"]),
                         video_rows)

    for table, rows in (("channels", channel_rows), ("videos", video_rows)):
        new = count_rows(conn, table, sid) - before[table]
        print(f"  {table:<8}: {len(rows):>5} rows read -> {new:>5} new, {len(rows) - new:>5} already there (updated)")


# ---------- checks ----------

def run_checks(conn):
    """Prove the load worked. Each check prints OK or PROBLEM."""
    print("\nChecks:")
    ok = True

    # 1) Rows in the database = videos the collector said it saved
    for sid, expected, actual in conn.execute("""
            SELECT s.snapshot_id, s.video_count, COUNT(v.video_id)
            FROM snapshots AS s
            LEFT JOIN videos AS v ON v.snapshot_id = s.snapshot_id
            GROUP BY s.snapshot_id"""):
        good = expected == actual
        ok &= good
        print(f"  {'OK' if good else 'PROBLEM'}: snapshot {sid} has {actual} videos (expected {expected})")

    # 2) No video twice in the same snapshot (the PRIMARY KEY should make this impossible)
    dupes = conn.execute("""
            SELECT COUNT(*) FROM (
                SELECT video_id, snapshot_id FROM videos
                GROUP BY video_id, snapshot_id HAVING COUNT(*) > 1)""").fetchone()[0]
    ok &= dupes == 0
    print(f"  {'OK' if dupes == 0 else 'PROBLEM'}: duplicate videos = {dupes}")

    # 3) Every video points to a channel row that exists
    orphans = conn.execute("PRAGMA foreign_key_check").fetchall()
    ok &= not orphans
    print(f"  {'OK' if not orphans else 'PROBLEM'}: rows pointing to a missing parent = {len(orphans)}")
    return ok


def print_latest_summary(conn):
    rows = conn.execute("""
        SELECT c.channel_name,
               c.subscriber_count,
               COUNT(*)                       AS videos,
               MIN(DATE(v.published_at))      AS oldest,
               MAX(DATE(v.published_at))      AS newest,
               SUM(v.like_count IS NULL)      AS hidden_likes
        FROM latest_videos AS v
        JOIN latest_channels AS c ON c.channel_id = v.channel_id
        GROUP BY c.channel_id
        ORDER BY c.subscriber_count DESC""").fetchall()
    print("\nLatest snapshot, per channel (oldest = how far back the 200 videos go):")
    print(f"  {'channel':<20} {'subs':>6} {'videos':>6}  {'oldest':<10}  {'newest':<10}  hidden likes")
    for name, subs, videos, oldest, newest, hidden in rows:
        subs_text = f"{subs / 1e6:.1f}M" if subs else "hidden"
        print(f"  {name:<20} {subs_text:>6} {videos:>6}  {oldest}  {newest}  {hidden}")


# ---------- main ----------

def main(db_path=DB_PATH, raw_dir=RAW_DIR):
    runs = sorted(p for p in raw_dir.glob("*") if (p / "manifest.json").exists())
    if not runs:
        print("No snapshots in data/raw/. Run collect.bat first.")
        return 1

    conn = connect(db_path)
    create_schema(conn)

    loaded = 0
    for run_dir in runs:
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        if manifest["status"] != "complete":
            # A half-finished snapshot would make "latest" look like it lost videos
            print(f"Skipping {run_dir.name}: not complete. Run collect.bat to finish it.")
            continue
        print(f"Loading snapshot {run_dir.name}")
        load_snapshot(conn, run_dir, manifest)
        loaded += 1

    if loaded == 0:
        print("Nothing loaded.")
        conn.close()
        return 1

    ok = run_checks(conn)
    print_latest_summary(conn)
    conn.close()
    print(f"\nDatabase: {db_path} ({db_path.stat().st_size / 1e6:.1f} MB)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")  # never crash on an emoji in a channel name
    sys.exit(main())
