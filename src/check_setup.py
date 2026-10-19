"""Quick test: is the API key found, and does YouTube accept it?

Costs 1 quota unit (out of 10,000 free per day). Never prints the key itself.
"""
import csv
import sys

import requests

from config import API_BASE_URL, API_KEY, CHANNELS_CSV


def main():
    # 1) Is the key there?
    if not API_KEY:
        print("PROBLEM: no API key found.")
        print("Make a copy of .env.example, name it .env, and paste your key after YOUTUBE_API_KEY=")
        sys.exit(1)
    print("OK: API key found in .env")

    # 2) Does the channel list load?
    with open(CHANNELS_CSV, newline="", encoding="utf-8") as f:
        channels = list(csv.DictReader(f))
    print(f"OK: {len(channels)} channels in config/channels.csv")

    # 3) One cheap API call: ask for the first channel's name.
    first = channels[0]
    resp = requests.get(
        f"{API_BASE_URL}/channels",
        params={"part": "snippet", "id": first["channel_id"], "key": API_KEY},
        timeout=30,
    )

    if resp.status_code == 200:
        items = resp.json().get("items", [])
        if items:
            print(f"OK: YouTube answered. First channel = {items[0]['snippet']['title']}")
            print("\nSetup works. You are ready for Step 2.")
        else:
            print(f"PROBLEM: key works, but channel ID {first['channel_id']} was not found.")
        return

    # Explain the most common errors in plain words.
    try:
        reason = resp.json()["error"]["errors"][0]["reason"]
    except (ValueError, KeyError, IndexError):
        reason = "unknown"
    hints = {
        "keyInvalid": "The key is wrong. Copy it again from Google Cloud (no spaces, no quotes).",
        "badRequest": "The key is wrong. Copy it again from Google Cloud (no spaces, no quotes).",
        "accessNotConfigured": "YouTube Data API v3 is not enabled for this Google Cloud project.",
        "quotaExceeded": "Daily quota used up. It resets at midnight Pacific Time (about 14:00-15:00 Jakarta).",
        "forbidden": "The key's restrictions block this API. Allow 'YouTube Data API v3' on the key.",
    }
    print(f"PROBLEM: HTTP {resp.status_code}, reason = {reason}")
    print(hints.get(reason, "See the error above and check docs/api_key_setup.md"))
    sys.exit(1)


if __name__ == "__main__":
    main()
