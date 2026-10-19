# Getting a YouTube Data API v3 key

Free. No credit card needed. Default quota: 10,000 units per day.

1. Open https://console.cloud.google.com and sign in with your Google account.
2. Top bar, project picker > **New Project**. Name: `youtube-trend-analysis`. Click **Create**, then select it.
3. Left menu > **APIs & Services** > **Library**. Search `YouTube Data API v3`, open it, click **Enable**.
4. Left menu > **APIs & Services** > **Credentials** > **+ Create credentials** > **API key**. Copy the key.
5. Click the new key (or **Edit API key**) > **API restrictions** > **Restrict key** > tick **YouTube Data API v3** > **Save**.
   This way, a leaked key can only read public YouTube data.
6. In the project folder, open `.env` (setup.bat creates it from `.env.example`) with Notepad and paste the key:
   `YOUTUBE_API_KEY=AIza...` (no quotes, no spaces). Save.
7. Double-click `check_setup.bat`. It should print `Setup works`.

## Rules for the key
- Never paste it into code, notebooks, chat, or screenshots.
- `.env` is listed in `.gitignore`, so git will not upload it.
- If it leaks: Credentials page > delete key > create a new one.

## Quota cost in this project
| Call | Cost | Used for |
|---|---|---|
| `channels.list` | 1 unit | channel stats + uploads playlist ID |
| `playlistItems.list` | 1 unit per 50 videos | list a channel's uploads |
| `videos.list` | 1 unit per 50 videos | video details and stats |
| `search.list` | **100 units** | not used |

15 channels x 200 videos is about 15 x (1 + 4 + 4) = ~135 units, about 1.4% of the daily quota.
Quota resets at midnight Pacific Time (about 14:00-15:00 Jakarta time).
