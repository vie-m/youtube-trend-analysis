-- Step 5 analysis queries. Each one starts with "-- name: ..." so Python can load it by name
-- (see load_queries() in src/db.py).
--
-- Rules used in EVERY query:
--   * WHERE in_analysis = 1 AND performance_index IS NOT NULL
--     = published, not live, at least 30 days old, and has a fair group to compare with.
--     Same 2,724 videos everywhere, so the answers can be compared with each other.
--   * MEDIAN(), not AVG(): one viral video would drag an average up a lot.
--     SQLite has no MEDIAN() built in; src/db.py adds it, so run these through connect().
--   * performance_index = views per day / the channel's typical views per day for
--     videos of the same format (Short or long) and age group. 1 = typical, 2 = double.
--     It is the fair metric: channel size, format and video age are already taken out.


-- name: by_weekday
-- Q1a. Does the upload day (Jakarta time) relate to performance?
SELECT publish_dow                         AS weekday,
       COUNT(*)                            AS videos,
       ROUND(MEDIAN(views_per_day))        AS median_views_per_day,
       ROUND(MEDIAN(performance_index), 2) AS median_performance_index
FROM video_features
WHERE in_analysis = 1 AND performance_index IS NOT NULL
GROUP BY publish_dow_num, publish_dow
ORDER BY publish_dow_num;


-- name: by_hour_block
-- Q1b. Does the upload hour (Jakarta time) relate to performance?
-- 4-hour blocks, because single hours have as few as 9 videos.
SELECT CASE WHEN publish_hour < 4  THEN '00-03'
            WHEN publish_hour < 8  THEN '04-07'
            WHEN publish_hour < 12 THEN '08-11'
            WHEN publish_hour < 16 THEN '12-15'
            WHEN publish_hour < 20 THEN '16-19'
            ELSE '20-23' END               AS hour_block,
       COUNT(*)                            AS videos,
       ROUND(MEDIAN(views_per_day))        AS median_views_per_day,
       ROUND(MEDIAN(performance_index), 2) AS median_performance_index
FROM video_features
WHERE in_analysis = 1 AND performance_index IS NOT NULL
GROUP BY hour_block
ORDER BY hour_block;


-- name: top_uploader_per_hour_block
-- Q1c. Who uploads in each time block? If one big channel fills a block,
-- that block's raw views mostly describe that channel, not the hour.
WITH v AS (
    SELECT channel_name,
           CASE WHEN publish_hour < 4  THEN '00-03'
                WHEN publish_hour < 8  THEN '04-07'
                WHEN publish_hour < 12 THEN '08-11'
                WHEN publish_hour < 16 THEN '12-15'
                WHEN publish_hour < 20 THEN '16-19'
                ELSE '20-23' END AS hour_block
    FROM video_features
    WHERE in_analysis = 1 AND performance_index IS NOT NULL
),
counts AS (
    SELECT hour_block, channel_name, COUNT(*) AS videos
    FROM v
    GROUP BY hour_block, channel_name
),
ranked AS (
    -- Window functions: total per block, and rank channels inside each block
    SELECT *,
           SUM(videos) OVER (PARTITION BY hour_block)                       AS block_videos,
           ROW_NUMBER() OVER (PARTITION BY hour_block ORDER BY videos DESC) AS rn
    FROM counts
)
SELECT hour_block,
       block_videos                              AS videos,
       channel_name                              AS top_channel,
       videos                                    AS top_channel_videos,
       ROUND(100.0 * videos / block_videos)      AS top_channel_share_pct
FROM ranked
WHERE rn = 1
ORDER BY hour_block;


-- name: by_duration
-- Q2a. Do shorter or longer videos perform better?
SELECT duration_bucket,
       COUNT(*)                               AS videos,
       COUNT(DISTINCT channel_name)           AS channels,
       ROUND(MEDIAN(views_per_day))           AS median_views_per_day,
       ROUND(MEDIAN(views_per_subscriber), 3) AS median_views_per_subscriber,
       ROUND(MEDIAN(performance_index), 2)    AS median_performance_index
FROM video_features
WHERE in_analysis = 1 AND performance_index IS NOT NULL
GROUP BY duration_bucket
ORDER BY MIN(duration_sec);


-- name: shorts_vs_long_by_channel
-- Q2b. Inside each channel: do its Shorts or its long videos get more views per day?
-- Only videos 90-365 days old, so both formats have the same age range, and
-- only channels with at least 10 of each format.
-- MEDIAN(CASE WHEN ... THEN x END) = median of x for matching rows only (others are NULL, skipped).
WITH per_channel AS (
    SELECT channel_name,
           MAX(subscriber_count)                                                  AS subscribers,
           SUM(length_category = 'short')                                         AS shorts,
           SUM(length_category = 'long')                                          AS long_videos,
           MEDIAN(CASE WHEN length_category = 'short' THEN views_per_day END)     AS short_vpd,
           MEDIAN(CASE WHEN length_category = 'long'  THEN views_per_day END)     AS long_vpd
    FROM video_features
    WHERE in_analysis = 1 AND performance_index IS NOT NULL
      AND video_age_days >= 90 AND video_age_days < 365
    GROUP BY channel_name
)
SELECT channel_name,
       subscribers,
       shorts,
       long_videos,
       ROUND(short_vpd)            AS short_median_views_per_day,
       ROUND(long_vpd)             AS long_median_views_per_day,
       ROUND(short_vpd / long_vpd, 2) AS short_to_long_ratio
FROM per_channel
WHERE shorts >= 10 AND long_videos >= 10
ORDER BY short_to_long_ratio;


-- name: title_features
-- Q3a. Title features: raw views per day next to the fair performance index.
-- UNION ALL stacks the three yes/no features into one long table, so a single
-- GROUP BY can summarise all of them.
WITH v AS (
    SELECT * FROM video_features
    WHERE in_analysis = 1 AND performance_index IS NOT NULL
),
stacked AS (
    SELECT 'has a number' AS feature, title_has_number AS has_it, views_per_day, performance_index FROM v
    UNION ALL
    SELECT 'has a question mark', title_has_question, views_per_day, performance_index FROM v
    UNION ALL
    SELECT 'has an ALL-CAPS word', title_has_caps_word, views_per_day, performance_index FROM v
)
SELECT feature,
       CASE has_it WHEN 1 THEN 'yes' ELSE 'no' END AS in_title,
       COUNT(*)                                    AS videos,
       ROUND(MEDIAN(views_per_day))                AS median_views_per_day,
       ROUND(MEDIAN(performance_index), 2)         AS median_performance_index
FROM stacked
GROUP BY feature, has_it
ORDER BY feature, has_it DESC;


-- name: title_style_by_channel
-- Q3b. Which channels use which title style? (explains why raw views mislead in Q3a)
SELECT channel_name,
       MAX(subscriber_count)                     AS subscribers,
       ROUND(MEDIAN(views_per_day))              AS median_views_per_day,
       ROUND(100.0 * AVG(title_has_number))      AS pct_titles_with_number,
       ROUND(100.0 * AVG(title_has_caps_word))   AS pct_titles_with_caps,
       ROUND(100.0 * AVG(title_has_question))    AS pct_titles_with_question
FROM video_features
WHERE in_analysis = 1 AND performance_index IS NOT NULL
GROUP BY channel_name
ORDER BY median_views_per_day;


-- name: title_length
-- Q3c. Title length in characters vs performance.
SELECT CASE WHEN title_length <= 30 THEN 'up to 30'
            WHEN title_length <= 45 THEN '31-45'
            WHEN title_length <= 60 THEN '46-60'
            ELSE '61+' END                 AS title_length_chars,
       COUNT(*)                            AS videos,
       ROUND(MEDIAN(performance_index), 2) AS median_performance_index
FROM video_features
WHERE in_analysis = 1 AND performance_index IS NOT NULL
GROUP BY title_length_chars
ORDER BY MIN(title_length);


-- name: title_topic_videos
-- Q3d. Topic words in the title: one row per (topic, video) match.
-- A VALUES list works like a small inline table, and JOIN ... ON title LIKE pattern
-- pairs every video with every topic it mentions (a video can match two topics,
-- e.g. "iPhone" and "Apple"). The notebook then summarises per topic.
-- LIKE ignores upper/lower case for English letters in SQLite, and it is a rough
-- match: '%pixel%' also finds "megapixel", '%fold%' also finds "foldable".
WITH topics(topic, pattern) AS (
    VALUES ('iPhone', '%iphone%'), ('iPad', '%ipad%'), ('MacBook', '%macbook%'),
           ('Apple', '%apple%'), ('Samsung', '%samsung%'), ('Pixel', '%pixel%'),
           ('Fold / foldable', '%fold%'), ('Laptop', '%laptop%'), ('Review', '%review%'),
           ('Unboxing', '%unbox%'), ('"vs" comparison', '% vs%')
)
SELECT t.topic,
       v.channel_name,
       v.title,
       v.performance_index
FROM topics AS t
JOIN video_features AS v ON v.title LIKE t.pattern
WHERE v.in_analysis = 1 AND v.performance_index IS NOT NULL
ORDER BY t.topic, v.performance_index DESC;


-- name: engagement_by_format
-- Q4a. Engagement of Shorts vs long videos. Rates are per 100 / per 1,000 views
-- so they are easier to read than 0.0018. Hidden likes are NULL and skipped by MEDIAN.
SELECT length_category                                    AS format,
       COUNT(*)                                           AS videos,
       ROUND(100 * MEDIAN(like_view_ratio), 2)            AS likes_per_100_views,
       ROUND(1000 * MEDIAN(comment_view_ratio), 2)        AS comments_per_1000_views,
       ROUND(MEDIAN(views_per_subscriber), 3)             AS views_per_subscriber
FROM video_features
WHERE in_analysis = 1 AND performance_index IS NOT NULL
GROUP BY length_category;


-- name: engagement_by_channel
-- Q4b. Engagement per channel, Shorts and long videos in separate columns
-- (Shorts get far fewer comments per view, so mixing them would be unfair to
-- channels that post many Shorts).
SELECT channel_name,
       MAX(subscriber_count)                                                                AS subscribers,
       ROUND(100  * MEDIAN(CASE WHEN length_category = 'long'  THEN like_view_ratio END), 2)    AS long_likes_per_100,
       ROUND(100  * MEDIAN(CASE WHEN length_category = 'short' THEN like_view_ratio END), 2)    AS short_likes_per_100,
       ROUND(1000 * MEDIAN(CASE WHEN length_category = 'long'  THEN comment_view_ratio END), 2) AS long_comments_per_1000,
       ROUND(1000 * MEDIAN(CASE WHEN length_category = 'short' THEN comment_view_ratio END), 2) AS short_comments_per_1000,
       ROUND(MEDIAN(CASE WHEN length_category = 'long' THEN views_per_subscriber END), 3)       AS long_views_per_subscriber
FROM video_features
WHERE in_analysis = 1 AND performance_index IS NOT NULL
GROUP BY channel_name
ORDER BY long_likes_per_100 DESC;


-- name: top_breakouts
-- Q5a. Videos that did far better than their own channel's typical video.
SELECT channel_name,
       length_category                    AS format,
       age_group,
       title,
       view_count,
       ROUND(views_per_day)               AS views_per_day,
       ROUND(typical_views_per_day)       AS typical_views_per_day,
       ROUND(performance_index, 1)        AS performance_index,
       is_sponsored
FROM video_features
WHERE in_analysis = 1 AND performance_index IS NOT NULL
ORDER BY performance_index DESC
LIMIT 15;


-- name: best_video_per_channel
-- Q5b. Each channel's single biggest breakout. RANK() numbers the videos inside each
-- channel (PARTITION BY) from best to worst, then we keep rank 1.
WITH ranked AS (
    SELECT channel_name, title, length_category, view_count, performance_index,
           RANK() OVER (PARTITION BY channel_name ORDER BY performance_index DESC) AS rank_in_channel
    FROM video_features
    WHERE in_analysis = 1 AND performance_index IS NOT NULL
)
SELECT channel_name,
       title,
       length_category              AS format,
       view_count,
       ROUND(performance_index, 1)  AS performance_index
FROM ranked
WHERE rank_in_channel = 1
ORDER BY performance_index DESC;


-- name: breakouts_per_channel
-- Q5c. How often does each channel have a breakout (3x typical or more)
-- or an underperformer (a third of typical or less)?
-- In SQLite a comparison like (x >= 3) gives 1 or 0, so SUM counts and AVG gives a share.
SELECT channel_name,
       COUNT(*)                                             AS videos,
       SUM(performance_index >= 3)                          AS breakouts,
       ROUND(100.0 * AVG(performance_index >= 3), 1)        AS pct_breakouts,
       ROUND(100.0 * AVG(performance_index <= 1.0 / 3), 1)  AS pct_underperformers
FROM video_features
WHERE in_analysis = 1 AND performance_index IS NOT NULL
GROUP BY channel_name
ORDER BY pct_breakouts DESC;


-- name: breakouts_by_format_and_sponsor
-- Q5d. Are breakouts more common for Shorts? For sponsored videos?
SELECT length_category                                         AS format,
       CASE is_sponsored WHEN 1 THEN 'sponsored' ELSE 'not sponsored' END AS deal,
       COUNT(*)                                                AS videos,
       ROUND(MEDIAN(performance_index), 2)                     AS median_performance_index,
       ROUND(100.0 * AVG(performance_index >= 3), 1)           AS pct_breakouts
FROM video_features
WHERE in_analysis = 1 AND performance_index IS NOT NULL
GROUP BY length_category, is_sponsored
ORDER BY length_category, is_sponsored;
