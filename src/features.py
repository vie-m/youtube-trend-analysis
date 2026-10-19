"""Step 4: clean the raw data and add features for analysis.

Reads the newest snapshot from SQLite (latest_videos + latest_channels), builds one
tidy table with ONE ROW PER VIDEO, and saves it two ways:
  - SQLite table video_features             -> SQL queries in Step 5
  - CSV file data/processed/video_features.csv -> open in Excel if you like

The raw tables are never changed. This table is rebuilt from scratch every run,
so if you change a rule below, run it again. No API calls, no quota.

Run: double-click features.bat  (or: .venv\\Scripts\\python.exe src\\features.py)
"""
import json
import re
import sys

import numpy as np
import pandas as pd

from config import LOCAL_TIMEZONE, PROCESSED_DIR
from db import connect

# ---------- rules: all in one place, so they are easy to explain and change ----------

# YouTube Shorts can be up to 3 minutes (since Oct 2024; before that, 60 s).
# The API has NO "is Short" flag, so duration is our best signal. Our data backs this up:
# 1,290 videos are <= 3 min but only 29 are between 3 and 5 min, a clear gap.
SHORT_MAX_SECONDS = 180

# A video keeps getting most of its views in its first weeks. Younger videos are
# still "in progress", so we keep them in the table but leave them out of analysis.
MIN_AGE_DAYS = 30

# Age groups: views per day shrinks as a video gets older (most views come early),
# so fair comparisons put videos of similar age side by side.
AGE_BINS = [0, MIN_AGE_DAYS, 90, 180, 365, np.inf]
AGE_LABELS = [f"0-{MIN_AGE_DAYS} days", f"{MIN_AGE_DAYS}-90 days", "90-180 days", "180-365 days", "1 year+"]

# Performance index needs a fair "typical" to compare with: the median of at least
# this many videos from the same channel, format and age group. Fewer = too noisy.
MIN_GROUP_SIZE = 5

# Sponsored / brand-deal videos. YouTube's "paid promotion" label is NOT in the API,
# so we look for the words creators use to disclose deals. Heuristic: misses deals
# that are not written down, and very rarely flags a video that only mentions a partner.
SPONSOR_PATTERN = (r"#ad\b|#sponsored|sponsored by|#\w*partner\b|paid partnership"
                   r"|in partnership with|for sponsoring|this video is sponsored")

# Duration groups for "do shorter or longer videos perform better?"
DURATION_BINS = [0, SHORT_MAX_SECONDS, 600, 1200, np.inf]
DURATION_LABELS = ["short (<=3 min)", "3-10 min", "10-20 min", "20+ min"]

# "All-caps word" = shouting for attention ("INSANE", "DON'T"). Product names and
# acronyms are written in caps anyway, so they do NOT count. This list comes from
# looking at every caps word in our titles. It is a heuristic, not perfect.
CAPS_MIN_LETTERS = 3  # "OK" or "TV" is too short to count as shouting
TECH_ACRONYMS = {
    "AIO", "AMD", "AOC", "API", "APU", "ARM", "ASMR", "ASUS", "BMW", "BYD", "CEO", "CES",
    "CPU", "DIY", "DJI", "FPS", "GPT", "GPU", "GTA", "HDMI", "HDR", "HTC", "IBM", "IMAX",
    "LCD", "LED", "LEGO", "LTT", "MKBHD", "MSI", "NASA", "NFC", "NPU", "NVIDIA", "OLED",
    "OPPO", "POV", "QNED", "RAM", "RGB", "ROG", "RTX", "SSD", "TCL", "TSMC", "TUF", "USA",
    "USB", "VPN", "WAN", "WWDC", "XBOX", "XDR", "XGIMI", "XPS", "ZTE", "INZONE", "HONOR",
    "HUAWEI", "NAS", "PRO", "MAX", "ULTRA", "FOLD",  # brand / product names (iPhone 17 PRO MAX)
}

# ---------- small building blocks ----------

# ISO 8601 duration: P[days]D T[hours]H[minutes]M[seconds]S, every part optional.
# Examples: PT12M30S, PT45S, PT1H2M, P1DT2H (very long live streams), P0D (no video yet)
DURATION_RE = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?")


def iso_duration_to_seconds(text):
    """'PT12M30S' -> 750, 'PT1H' -> 3600, 'P0D' -> 0. Anything else -> None."""
    if not isinstance(text, str):
        return None
    match = DURATION_RE.fullmatch(text)
    if match is None:
        return None
    days, hours, minutes, seconds = (int(part) if part else 0 for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


LETTER_WORD_RE = re.compile(r"[A-Za-z][A-Za-z']*")  # words made of letters (and ' as in DON'T)
ANY_WORD_RE = re.compile(r"[\w']+")                 # letters/digits: "iPhone", "18", "don't"


def caps_words(title):
    """Shouting words in a title: 'This is INSANE' -> ['INSANE']. Acronyms are skipped."""
    found = []
    for word in LETTER_WORD_RE.findall(title):
        letters = word.replace("'", "")
        if len(letters) >= CAPS_MIN_LETTERS and letters.isupper() and letters not in TECH_ACRONYMS:
            found.append(word)
    return found


def safe_ratio(top, bottom):
    """top / bottom, but NaN (unknown) when bottom is 0 or missing, instead of inf or an error."""
    return top / bottom.where(bottom > 0)


# ---------- the pipeline ----------

def load_latest(conn):
    """Raw video rows of the newest snapshot, with each video's channel name and subscribers."""
    return pd.read_sql("""
        SELECT v.*, c.channel_name, c.subscriber_count
        FROM latest_videos AS v
        JOIN latest_channels AS c ON c.channel_id = v.channel_id
    """, conn)


def build_features(raw):
    """Return (features table, number of rows dropped). Never changes `raw`."""
    df = raw.copy()

    # 1) Drop scheduled videos: they are announced but not published (0 views, no length).
    upcoming = df["broadcast_status"] == "upcoming"
    df = df[~upcoming].copy()

    # 2) Duration
    df["duration_sec"] = df["duration_iso"].map(iso_duration_to_seconds).astype("Int64")
    df["duration_min"] = (df["duration_sec"] / 60).round(2)
    df["length_category"] = np.where(df["duration_sec"] <= SHORT_MAX_SECONDS, "short", "long")
    df["duration_bucket"] = pd.cut(df["duration_sec"].astype(float), bins=DURATION_BINS,
                                   labels=DURATION_LABELS).astype(str)

    # 3) Time: the API gives UTC ("Z" at the end). Convert to Jakarta (UTC+7, no daylight saving).
    published_utc = pd.to_datetime(df["published_at"], utc=True)
    published_local = published_utc.dt.tz_convert(LOCAL_TIMEZONE)
    df["published_at_local"] = published_local.map(lambda t: t.isoformat())  # 2026-10-19T22:12:21+07:00
    df["publish_date_local"] = published_local.dt.strftime("%Y-%m-%d")
    df["publish_dow"] = published_local.dt.day_name()      # Monday ... Sunday
    df["publish_dow_num"] = published_local.dt.dayofweek   # 0 = Monday, for sorting
    df["publish_hour"] = published_local.dt.hour           # 0-23, Jakarta time

    # 4) Age: from publishing until the moment WE collected the numbers (not "today"),
    #    so the result does not change every time you rerun this script.
    collected_utc = pd.to_datetime(df["collected_at"], utc=True)
    df["video_age_days"] = ((collected_utc - published_utc).dt.total_seconds() / 86400).round(2)
    df["age_group"] = pd.cut(df["video_age_days"], bins=AGE_BINS, labels=AGE_LABELS,
                             right=False).astype(str)  # right=False: exactly 30.0 days -> "30-90"

    # 5) Title features
    title = df["title"]
    df["title_length"] = title.str.len()
    df["title_word_count"] = title.map(lambda t: len(ANY_WORD_RE.findall(t)))
    df["title_has_number"] = title.str.contains(r"\d", regex=True).astype(int)
    df["title_has_question"] = title.str.contains("?", regex=False).astype(int)
    df["title_caps_words"] = title.map(lambda t: " ".join(caps_words(t)))  # kept so you can check it
    df["title_has_caps_word"] = (df["title_caps_words"] != "").astype(int)
    df["tag_count"] = df["tags"].map(lambda t: len(json.loads(t)) if t else 0)
    text = df["title"] + " " + df["description"].fillna("")
    df["is_sponsored"] = text.str.contains(SPONSOR_PATTERN, case=False, regex=True).astype(int)

    # 6) Fair performance metrics. Missing stays missing (NaN), never 0.
    df["views_per_day"] = (df["view_count"] / df["video_age_days"].clip(lower=1)).round(1)
    df["views_per_subscriber"] = safe_ratio(df["view_count"], df["subscriber_count"]).round(5)
    df["like_view_ratio"] = safe_ratio(df["like_count"], df["view_count"]).round(5)
    df["comment_view_ratio"] = safe_ratio(df["comment_count"], df["view_count"]).round(6)

    # 7) Which rows to analyze. Excluded rows stay in the table with a reason, so nothing
    #    disappears silently and you can always look at them.
    reason = pd.Series(pd.NA, index=df.index, dtype="string")
    reason[df["video_age_days"] < MIN_AGE_DAYS] = f"too new (< {MIN_AGE_DAYS} days)"
    reason[df["was_live"] == 1] = "live stream"  # 2-4 hour streams behave differently
    df["exclude_reason"] = reason
    df["in_analysis"] = reason.isna().astype(int)

    # 8) Performance index: views per day compared with SIMILAR videos of the SAME channel.
    #    "Similar" = same format (short/long) and same age group, because views per day
    #    depends on both. 1.0 = typical for that channel, 3.0 = three times its typical.
    #    This takes channel size, format and age out of the comparison, so in Step 5
    #    a small channel's hit counts as much as a big channel's hit.
    #    Median, not mean: one viral video would pull a mean up a lot.
    group = ["channel_id", "length_category", "age_group"]
    ok = df["in_analysis"] == 1
    typical = (df[ok].groupby(group)["views_per_day"]
               .agg(typical_views_per_day="median", group_size="count")
               .reset_index())
    typical.loc[typical["group_size"] < MIN_GROUP_SIZE, "typical_views_per_day"] = np.nan
    df = df.merge(typical[group + ["typical_views_per_day"]], on=group, how="left")
    df["typical_views_per_day"] = df["typical_views_per_day"].where(df["in_analysis"] == 1)
    df["performance_index"] = safe_ratio(df["views_per_day"], df["typical_views_per_day"]).round(3)

    # Whole numbers with gaps: "Int64" keeps them whole (1234, not 1234.0) and allows <NA>
    for col in ["view_count", "like_count", "comment_count", "subscriber_count", "category_id",
                "has_captions"]:
        df[col] = df[col].astype("Int64")

    columns = [
        "video_id", "channel_id", "channel_name", "title",
        "published_at", "published_at_local", "publish_date_local", "publish_dow",
        "publish_dow_num", "publish_hour", "video_age_days", "age_group",
        "duration_iso", "duration_sec", "duration_min", "length_category", "duration_bucket",
        "was_live", "category_id", "has_captions", "tag_count", "is_sponsored",
        "title_length", "title_word_count", "title_has_number", "title_has_question",
        "title_has_caps_word", "title_caps_words",
        "subscriber_count", "view_count", "like_count", "comment_count",
        "views_per_day", "views_per_subscriber", "like_view_ratio", "comment_view_ratio",
        "typical_views_per_day", "performance_index",
        "in_analysis", "exclude_reason", "snapshot_id", "collected_at",
    ]
    return df[columns].sort_values(["channel_name", "published_at"]).reset_index(drop=True), int(upcoming.sum())


# ---------- checks ----------

def run_checks(df):
    print("\nChecks:")
    checks = {
        "duration examples parse correctly": (
            iso_duration_to_seconds("PT12M30S") == 750 and iso_duration_to_seconds("PT45S") == 45
            and iso_duration_to_seconds("PT1H2M3S") == 3723 and iso_duration_to_seconds("P1DT1S") == 86401
            and iso_duration_to_seconds("12:30") is None),
        "every video has a duration": df["duration_sec"].notna().all(),
        "same answer as pandas' own ISO parser": (
            pd.to_timedelta(df["duration_iso"]).dt.total_seconds().astype(int) == df["duration_sec"]).all(),
        "Jakarta time = UTC + 7 hours": (
            (pd.to_datetime(df["published_at_local"].str[:19])
             - pd.to_datetime(df["published_at"].str[:19])) == pd.Timedelta(hours=7)).all(),
        "no negative ages": (df["video_age_days"] >= 0).all(),
        "like ratio between 0 and 1": df["like_view_ratio"].dropna().between(0, 1).all(),
        "one row per video": df["video_id"].is_unique,
    }
    for name, passed in checks.items():
        print(f"  {'OK' if passed else 'PROBLEM'}: {name}")
    return all(checks.values())


def print_summary(df, dropped):
    ok = df["in_analysis"] == 1
    print(f"\nVideos: {len(df)} kept, {dropped} scheduled (not published yet) dropped")
    print(f"In analysis: {ok.sum()}")
    for reason, n in df["exclude_reason"].value_counts().items():
        print(f"  left out, {reason}: {n}")
    print("\nIn analysis by format:")
    print(df[ok].groupby("length_category").agg(
        videos=("video_id", "count"),
        median_views=("view_count", "median"),
        median_views_per_day=("views_per_day", "median"),
        median_like_ratio=("like_view_ratio", "median"),
    ).round(4).to_string())
    print("\nTitles (in analysis): "
          f"{df.loc[ok, 'title_has_number'].mean():.0%} have a number, "
          f"{df.loc[ok, 'title_has_question'].mean():.0%} a question mark, "
          f"{df.loc[ok, 'title_has_caps_word'].mean():.0%} an all-caps word")
    print(f"Like ratio unknown (likes hidden): {df.loc[ok, 'like_view_ratio'].isna().sum()} videos")
    print(f"Performance index unknown (fewer than {MIN_GROUP_SIZE} similar videos to compare with): "
          f"{df.loc[ok, 'performance_index'].isna().sum()} videos")
    print(f"Sponsored (disclosed in title/description): {df.loc[ok, 'is_sponsored'].mean():.0%}")


def main():
    conn = connect()
    raw = load_latest(conn)
    if raw.empty:
        print("No videos in the database. Run collect.bat, then load_db.bat.")
        return 1

    df, dropped = build_features(raw)
    ok = run_checks(df)
    print_summary(df, dropped)

    df.to_sql("video_features", conn, if_exists="replace", index=False)  # rebuilt every run
    conn.close()
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = PROCESSED_DIR / "video_features.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")  # "-sig" lets Excel show emoji/accents
    print(f"\nSaved: SQLite table video_features, and {csv_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
