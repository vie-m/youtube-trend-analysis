# Data dictionary: `video_features`

Made by `src/features.py`. One row for each published video in the newest snapshot. Saved as the SQLite table `video_features` and as `data/processed/video_features.csv`.

**Use `WHERE in_analysis = 1` for every analysis.** Rows left out are still in the table, and `exclude_reason` says why.

## Identity and time
| Column | Meaning |
|---|---|
| `video_id`, `channel_id`, `channel_name`, `title` | From the API |
| `published_at` | Publish time in UTC, as YouTube gives it |
| `published_at_local` | Same moment in Asia/Jakarta time (UTC+7) |
| `publish_date_local`, `publish_dow`, `publish_hour` | Jakarta date, day name, hour 0-23. `publish_dow_num`: 0 = Monday, used for sorting |
| `video_age_days` | Days from publishing to collection (`collected_at`, not "today") |
| `age_group` | `0-30 days`, `30-90 days`, `90-180 days`, `180-365 days`, `1 year+` |

## Format
| Column | Meaning |
|---|---|
| `duration_iso` | Raw length, e.g. `PT12M30S` |
| `duration_sec`, `duration_min` | Length in seconds and in minutes |
| `length_category` | `short` (3 minutes or less, about the same as a YouTube Short) or `long` |
| `duration_bucket` | `short (<=3 min)`, `3-10 min`, `10-20 min`, `20+ min` |
| `was_live` | 1 = live stream or premiere |
| `category_id` | YouTube category (28 = Science & Technology, 26 = Howto & Style) |
| `has_captions` | 1 = the creator uploaded captions |
| `tag_count` | Number of tags (0 = none) |

## Title
| Column | Meaning |
|---|---|
| `title_length`, `title_word_count` | Characters and words |
| `title_has_number` | 1 = contains a digit ("iPhone 18", "5 Things") |
| `title_has_question` | 1 = contains `?` |
| `title_has_caps_word` | 1 = has an all-caps word of 3+ letters that isn't a tech acronym ("INSANE" counts, "RTX" doesn't) |
| `title_caps_words` | The words that counted, so you can check the rule |

## Performance
| Column | Meaning | Missing when |
|---|---|---|
| `view_count`, `like_count`, `comment_count` | Raw counts at collection time | likes hidden by the creator / comments turned off |
| `subscriber_count` | Channel subscribers, rounded by YouTube (21.4M) | the channel hides its subscriber count |
| `views_per_day` | views / age in days (age counted as at least 1 day) | |
| `views_per_subscriber` | views / channel subscribers | subscribers hidden |
| `like_view_ratio`, `comment_view_ratio` | likes or comments / views | likes or comments hidden |
| `channel_median_views` | Median views of that channel's analyzed videos of the same format | |
| `views_vs_channel_median` | views / `channel_median_views`. 1 = typical for the channel, 3 = triple | row not in analysis |

## Filters
| Column | Meaning |
|---|---|
| `in_analysis` | 1 = use this row |
| `exclude_reason` | `too new (< 30 days)` or `live stream` |
| `snapshot_id`, `collected_at` | Which collection run the numbers come from |
