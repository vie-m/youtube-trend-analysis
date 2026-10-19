-- YouTube Trend Analysis: database schema (SQLite)
--
-- Key idea: one "snapshot" = one run of collect.py.
-- Views, likes and subscribers change every day, so every channel and video row
-- is tagged with the snapshot it came from. One video = one row PER snapshot.
--   - Loading the same snapshot twice   -> same rows, no duplicates (PRIMARY KEY)
--   - Loading a newer snapshot later    -> new rows, old ones kept (history)
--
-- Running this file again is safe: IF NOT EXISTS skips anything already created.
-- Dates are TEXT in ISO 8601 UTC ("2026-10-19T15:12:21Z"): SQLite has no DATE type,
-- and ISO text sorts correctly and works with SQLite's DATE()/STRFTIME().

-- One row per collection run (the "collection date" lives here and on every row below)
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id     TEXT PRIMARY KEY,  -- folder name in data/raw, e.g. 2026-10-19_230140 (sorts by time)
    started_at      TEXT NOT NULL,     -- UTC
    finished_at     TEXT,              -- UTC
    api_units_used  INTEGER,
    channel_count   INTEGER,
    video_count     INTEGER,
    loaded_at       TEXT NOT NULL      -- UTC, last time load_db.py loaded this snapshot
);

-- One row per channel per snapshot
CREATE TABLE IF NOT EXISTS channels (
    channel_id          TEXT NOT NULL,     -- UC... (never changes, unlike names)
    snapshot_id         TEXT NOT NULL REFERENCES snapshots (snapshot_id),
    collected_at        TEXT NOT NULL,     -- UTC moment YouTube returned these numbers
    channel_name        TEXT NOT NULL,
    handle              TEXT,              -- @name
    country             TEXT,              -- NULL if the channel did not set one
    channel_created_at  TEXT,              -- UTC
    uploads_playlist_id TEXT,
    subscriber_count    INTEGER,           -- rounded by YouTube to 3 digits (21.4M); NULL if hidden
    video_count         INTEGER,           -- ALL videos on the channel, not just the 200 we collected
    view_count          INTEGER,           -- ALL-time channel views
    PRIMARY KEY (channel_id, snapshot_id)
);

-- One row per video per snapshot. Raw values only: cleaning happens in Step 4.
CREATE TABLE IF NOT EXISTS videos (
    video_id         TEXT NOT NULL,
    snapshot_id      TEXT NOT NULL,
    collected_at     TEXT NOT NULL,        -- UTC; needed later for "video age" and "views per day"
    channel_id       TEXT NOT NULL,
    title            TEXT NOT NULL,
    description      TEXT,
    tags             TEXT NOT NULL DEFAULT '[]',  -- JSON list. '[]' = creator set no tags
    published_at     TEXT NOT NULL,        -- UTC (converted to Asia/Jakarta in Step 4)
    duration_iso     TEXT,                 -- e.g. PT12M30S (converted to seconds in Step 4)
    category_id      INTEGER,              -- 28 = Science & Technology, 26 = Howto & Style, ...
    audio_language   TEXT,
    definition       TEXT,                 -- hd / sd
    has_captions     INTEGER CHECK (has_captions IN (0, 1)),          -- creator-uploaded captions
    was_live         INTEGER NOT NULL CHECK (was_live IN (0, 1)),     -- live stream or premiere
    broadcast_status TEXT,                 -- none / live / upcoming (upcoming = not published yet)
    view_count       INTEGER,
    like_count       INTEGER,              -- NULL = hidden by the creator. NOT the same as 0
    comment_count    INTEGER,              -- NULL = comments turned off. NOT the same as 0
    PRIMARY KEY (video_id, snapshot_id),
    FOREIGN KEY (channel_id, snapshot_id) REFERENCES channels (channel_id, snapshot_id)
);

-- Speeds up "all videos of one channel in one snapshot" (the most common filter)
CREATE INDEX IF NOT EXISTS idx_videos_snapshot_channel ON videos (snapshot_id, channel_id);

-- Shortcuts: only the newest snapshot. Analysis queries use these.
CREATE VIEW IF NOT EXISTS latest_channels AS
SELECT * FROM channels
WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM snapshots);

CREATE VIEW IF NOT EXISTS latest_videos AS
SELECT * FROM videos
WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM snapshots);
