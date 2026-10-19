"""Interactive Streamlit dashboard for the local YouTube analysis snapshot.

Run from the project root with:
    .venv\\Scripts\\python.exe -m streamlit run dashboard\\app.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# Make project modules importable whether Streamlit starts from the project root
# or from another working directory.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from config import DB_PATH  # noqa: E402
from db import connect  # noqa: E402


st.set_page_config(
    page_title="YouTube Tech Review Trends",
    page_icon="▶",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(ttl=300)
def load_features() -> pd.DataFrame:
    """Load the saved feature table. This never calls the YouTube API."""
    conn = connect()
    try:
        return pd.read_sql("SELECT * FROM video_features", conn)
    finally:
        conn.close()


def median_or_zero(values: pd.Series) -> float:
    """Return a display-safe median for a possibly empty series."""
    value = values.median()
    return 0.0 if pd.isna(value) else float(value)


def format_count(value: float) -> str:
    """Format counts compactly without hiding small values."""
    value = float(value)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return f"{value:,.0f}"


def show_no_data(message: str = "No videos match current filters.") -> None:
    st.info(message)


def make_hour_block(hour: pd.Series) -> pd.Series:
    """Group sparse individual hours into six readable four-hour blocks."""
    return pd.cut(
        hour,
        bins=[-1, 3, 7, 11, 15, 19, 23],
        labels=["00–03", "04–07", "08–11", "12–15", "16–19", "20–23"],
    )


try:
    all_rows = load_features()
except Exception as exc:  # pragma: no cover - shown only when local DB is absent
    st.error("Could not open local database.")
    st.code(str(DB_PATH))
    st.caption("Run setup.bat, collect.bat, load_db.bat and features.bat first.")
    st.stop()

if all_rows.empty:
    st.error("video_features is empty. Run features.bat first.")
    st.stop()

# The dashboard compares only stable analysis rows by default. Excluded rows remain
# in SQLite and are visible in the notebook, but they lack a fair comparison metric.
df = all_rows[
    (all_rows["in_analysis"] == 1)
    & all_rows["performance_index"].notna()
].copy()
df["published_date"] = pd.to_datetime(df["published_at_local"], utc=True).dt.tz_convert("Asia/Jakarta").dt.date
min_date = df["published_date"].min()
max_date = df["published_date"].max()

# ---------- sidebar filters ----------
st.sidebar.header("Filters")
st.sidebar.caption("Filters affect every chart and table below.")

channel_options = sorted(df["channel_name"].dropna().unique())
selected_channels = st.sidebar.multiselect(
    "Channel",
    channel_options,
    default=[],
    help="Leave empty to include all 15 channels.",
)

selected_format = st.sidebar.selectbox(
    "Format",
    ["All", "long", "short"],
    format_func=lambda value: "All formats" if value == "All" else value.title(),
)

duration_options = ["All"] + sorted(df["duration_bucket"].dropna().unique(), key=lambda x: [
    "short (<=3 min)", "3-10 min", "10-20 min", "20+ min"
].index(x) if x in ["short (<=3 min)", "3-10 min", "10-20 min", "20+ min"] else 99)
selected_duration = st.sidebar.selectbox("Duration bucket", duration_options)

age_options = ["All"] + ["30-90 days", "90-180 days", "180-365 days", "1 year+"]
selected_age = st.sidebar.selectbox("Video age", age_options)

selected_dates = st.sidebar.date_input(
    "Publish date",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)
if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
    start_date, end_date = selected_dates
else:
    start_date = end_date = selected_dates

show_sponsored_only = st.sidebar.checkbox("Sponsored disclosure only", value=False)

filtered = df.copy()
if selected_channels:
    filtered = filtered[filtered["channel_name"].isin(selected_channels)]
if selected_format != "All":
    filtered = filtered[filtered["length_category"] == selected_format]
if selected_duration != "All":
    filtered = filtered[filtered["duration_bucket"] == selected_duration]
if selected_age != "All":
    filtered = filtered[filtered["age_group"] == selected_age]
if start_date and end_date:
    filtered = filtered[
        (filtered["published_date"] >= start_date)
        & (filtered["published_date"] <= end_date)
    ]
if show_sponsored_only:
    filtered = filtered[filtered["is_sponsored"] == 1]

# ---------- page header ----------
st.title("YouTube Tech Review Trends")
st.markdown(
    "Explore what relates to video performance across 15 tech-review channels. "
    "**Patterns show correlation, not causation.**"
)
st.caption(
    f"Local snapshot: {df['snapshot_id'].iloc[0]} · "
    "Stable comparison rows only: at least 30 days old, non-live, with 5+ similar videos."
)

if filtered.empty:
    show_no_data()
    st.stop()

# ---------- KPI row ----------
st.subheader("Snapshot")
kpi = st.columns(5)
kpi[0].metric("Videos", f"{len(filtered):,}")
kpi[1].metric("Channels", f"{filtered['channel_name'].nunique():,}")
kpi[2].metric("Median views/day", format_count(median_or_zero(filtered["views_per_day"])))
kpi[3].metric("Median fair index", f"{median_or_zero(filtered['performance_index']):.2f}x")
kpi[4].metric("Breakouts ≥3x", f"{int((filtered['performance_index'] >= 3).sum()):,}")

with st.expander("How fair index works"):
    st.write(
        "Fair index = this video's views per day divided by the median views per day "
        "for videos from the same channel, format and age group. 1.00x is typical; "
        "3.00x is three times typical. Medians reduce the effect of viral outliers."
    )

# ---------- tabs ----------
tab_timing, tab_format, tab_titles, tab_engagement, tab_breakouts = st.tabs(
    ["Upload timing", "Video length", "Title patterns", "Engagement", "Breakouts"]
)

with tab_timing:
    st.subheader("Does upload timing relate to performance?")
    timing_col1, timing_col2 = st.columns(2)
    dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    by_day = (
        filtered.groupby(["publish_dow_num", "publish_dow"], as_index=False, observed=True)
        .agg(videos=("video_id", "count"), fair_index=("performance_index", "median"))
        .sort_values("publish_dow_num")
    )
    filtered["hour_block"] = make_hour_block(filtered["publish_hour"])
    by_hour = (
        filtered.groupby("hour_block", as_index=False, observed=True)
        .agg(videos=("video_id", "count"), fair_index=("performance_index", "median"))
    )
    with timing_col1:
        if by_day.empty:
            show_no_data()
        else:
            fig = px.bar(
                by_day,
                x="publish_dow",
                y="fair_index",
                text=by_day["fair_index"].round(2),
                category_orders={"publish_dow": dow_order},
                labels={"publish_dow": "Jakarta weekday", "fair_index": "Median fair index"},
                title="Upload day",
            )
            fig.add_hline(y=1, line_dash="dash", line_color="black")
            fig.update_traces(marker_color="#3b82f6", textposition="outside")
            fig.update_layout(height=400, showlegend=False)
            st.plotly_chart(fig, width="stretch")
    with timing_col2:
        if by_hour.empty:
            show_no_data()
        else:
            fig = px.bar(
                by_hour,
                x="hour_block",
                y="fair_index",
                text=by_hour["fair_index"].round(2),
                category_orders={"hour_block": ["00–03", "04–07", "08–11", "12–15", "16–19", "20–23"]},
                labels={"hour_block": "Jakarta hour", "fair_index": "Median fair index"},
                title="Upload time block",
            )
            fig.add_hline(y=1, line_dash="dash", line_color="black")
            fig.update_traces(marker_color="#f59e0b", textposition="outside")
            fig.update_layout(height=400, showlegend=False)
            st.plotly_chart(fig, width="stretch")
    st.caption("Small groups can look extreme. Hour blocks use four-hour groups instead of sparse individual hours.")

with tab_format:
    st.subheader("Do shorter or longer videos perform better?")
    by_duration = (
        filtered.groupby("duration_bucket", as_index=False, observed=True)
        .agg(
            videos=("video_id", "count"),
            views_per_day=("views_per_day", "median"),
            fair_index=("performance_index", "median"),
        )
    )
    by_duration["duration_bucket"] = pd.Categorical(
        by_duration["duration_bucket"],
        categories=["short (<=3 min)", "3-10 min", "10-20 min", "20+ min"],
        ordered=True,
    )
    by_duration = by_duration.sort_values("duration_bucket")
    format_col1, format_col2 = st.columns(2)
    with format_col1:
        fig = px.bar(
            by_duration,
            x="duration_bucket",
            y="fair_index",
            text=by_duration["fair_index"].round(2),
            labels={"duration_bucket": "Duration", "fair_index": "Median fair index"},
            title="Fair performance by duration",
        )
        fig.add_hline(y=1, line_dash="dash", line_color="black")
        fig.update_traces(marker_color="#10b981", textposition="outside")
        fig.update_layout(height=420, showlegend=False, xaxis_tickangle=-20)
        st.plotly_chart(fig, width="stretch")
    with format_col2:
        fmt = (
            filtered.groupby("length_category", as_index=False, observed=True)
            .agg(videos=("video_id", "count"), views_per_day=("views_per_day", "median"))
        )
        fig = px.bar(
            fmt,
            x="length_category",
            y="views_per_day",
            text=fmt["views_per_day"].map(format_count),
            labels={"length_category": "Format", "views_per_day": "Median views/day"},
            title="Raw views/day by format",
        )
        fig.update_traces(marker_color="#8b5cf6", textposition="outside")
        fig.update_layout(height=420, showlegend=False)
        st.plotly_chart(fig, width="stretch")
    st.caption("The fair index controls for channel, format and age group. Raw views/day is shown only as context.")

with tab_titles:
    st.subheader("Do title characteristics relate to performance?")
    title_defs = {
        "Number in title": "title_has_number",
        "Question mark": "title_has_question",
        "ALL-CAPS word": "title_has_caps_word",
    }
    title_parts = []
    for label, column in title_defs.items():
        grouped = (
            filtered.groupby(column, as_index=False, observed=True)
            .agg(videos=("video_id", "count"), fair_index=("performance_index", "median"))
        )
        grouped["feature"] = label
        grouped["in_title"] = grouped[column].map({0: "No", 1: "Yes"})
        title_parts.append(grouped[["feature", "in_title", "videos", "fair_index"]])
    title_summary = pd.concat(title_parts, ignore_index=True)
    fig = px.bar(
        title_summary,
        x="fair_index",
        y="feature",
        color="in_title",
        barmode="group",
        text=title_summary["fair_index"].round(2),
        labels={"fair_index": "Median fair index", "feature": "", "in_title": "Feature present"},
        title="Simple title features",
        color_discrete_map={"Yes": "#14b8a6", "No": "#cbd5e1"},
    )
    fig.add_vline(x=1, line_dash="dash", line_color="black")
    fig.update_traces(textposition="outside")
    fig.update_layout(height=420)
    st.plotly_chart(fig, width="stretch")

    topic_patterns = {
        "iPhone": "iphone", "MacBook": "macbook", "iPad": "ipad", "Apple": "apple",
        "Samsung": "samsung", "Pixel": "pixel", "Fold/foldable": "fold",
        "Laptop": "laptop", "Review": "review", "Unboxing": "unbox",
    }
    topic_rows = []
    lowered_titles = filtered["title"].fillna("").str.lower()
    for topic, pattern in topic_patterns.items():
        match = lowered_titles.str.contains(pattern, regex=False)
        if int(match.sum()) >= 10:
            topic_rows.append({
                "topic": topic,
                "videos": int(match.sum()),
                "fair_index": filtered.loc[match, "performance_index"].median(),
            })
    if topic_rows:
        topic_summary = pd.DataFrame(topic_rows).sort_values("fair_index")
        fig = px.bar(
            topic_summary,
            x="fair_index",
            y="topic",
            text=topic_summary["fair_index"].round(2),
            labels={"fair_index": "Median fair index", "topic": "Title contains"},
            title="Common product/topic words",
        )
        fig.add_vline(x=1, line_dash="dash", line_color="black")
        fig.update_traces(marker_color="#f97316", textposition="outside")
        fig.update_layout(height=440)
        st.plotly_chart(fig, width="stretch")
    else:
        show_no_data("Not enough videos for topic comparison under current filters.")
    st.caption("Topic matching is a simple case-insensitive text check, not a causal model.")

with tab_engagement:
    st.subheader("How does engagement differ?")
    engagement = (
        filtered.groupby(["channel_name", "length_category"], as_index=False, observed=True)
        .agg(
            videos=("video_id", "count"),
            likes_per_100=("like_view_ratio", lambda s: 100 * s.median()),
            comments_per_1000=("comment_view_ratio", lambda s: 1000 * s.median()),
            views_per_subscriber=("views_per_subscriber", "median"),
        )
    )
    engagement_col1, engagement_col2 = st.columns(2)
    with engagement_col1:
        fig = px.bar(
            engagement.sort_values("likes_per_100"),
            x="likes_per_100",
            y="channel_name",
            color="length_category",
            barmode="group",
            labels={"likes_per_100": "Likes per 100 views", "channel_name": ""},
            title="Likes per 100 views",
        )
        fig.update_layout(height=580)
        st.plotly_chart(fig, width="stretch")
    with engagement_col2:
        fig = px.bar(
            engagement.sort_values("comments_per_1000"),
            x="comments_per_1000",
            y="channel_name",
            color="length_category",
            barmode="group",
            labels={"comments_per_1000": "Comments per 1,000 views", "channel_name": ""},
            title="Comments per 1,000 views",
        )
        fig.update_layout(height=580)
        st.plotly_chart(fig, width="stretch")
    st.caption("Missing likes/comments stay missing. They are not changed to zero.")
    st.dataframe(
        engagement.sort_values(["length_category", "likes_per_100"], ascending=[True, False])
        .style.format({"likes_per_100": "{:.2f}", "comments_per_1000": "{:.2f}", "views_per_subscriber": "{:.3f}"}),
        width="stretch",
        hide_index=True,
    )

with tab_breakouts:
    st.subheader("Which videos are breakouts?")
    st.caption("Breakout threshold: fair index ≥ 3x. Sponsored flag uses title/description disclosure text and is only a heuristic.")
    breakout_view = filtered.nlargest(20, "performance_index").copy()
    if breakout_view.empty:
        show_no_data()
    else:
        breakout_plot = breakout_view.head(10).sort_values("performance_index")
        breakout_plot["label"] = breakout_plot["channel_name"] + ": " + breakout_plot["title"].str.slice(0, 45)
        fig = px.bar(
            breakout_plot,
            x="performance_index",
            y="label",
            color="is_sponsored",
            orientation="h",
            log_x=True,
            labels={"performance_index": "Times typical views/day (log scale)", "label": "", "is_sponsored": "Sponsor disclosure"},
            title="Top 10 filtered breakouts",
            color_discrete_map={0: "#6366f1", 1: "#ef4444"},
        )
        fig.update_layout(height=520)
        st.plotly_chart(fig, width="stretch")
        display_cols = [
            "channel_name", "title", "length_category", "age_group", "view_count",
            "views_per_day", "typical_views_per_day", "performance_index", "is_sponsored", "video_id",
        ]
        table = breakout_view[display_cols].copy()
        table["youtube_url"] = "https://www.youtube.com/watch?v=" + table["video_id"]
        st.dataframe(
            table.drop(columns=["video_id"]).style.format({
                "view_count": "{:,.0f}", "views_per_day": "{:,.0f}",
                "typical_views_per_day": "{:,.0f}", "performance_index": "{:.1f}x",
            }),
            width="stretch",
            hide_index=True,
            column_config={"youtube_url": st.column_config.LinkColumn("Video")},
        )

st.divider()
st.download_button(
    "Download filtered rows as CSV",
    data=filtered.drop(columns=["published_date", "hour_block"], errors="ignore").to_csv(index=False).encode("utf-8"),
    file_name="youtube_filtered_features.csv",
    mime="text/csv",
)
st.caption("Data source: local SQLite snapshot collected from YouTube Data API v3. No API calls are made by this dashboard.")
