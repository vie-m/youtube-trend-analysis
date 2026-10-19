"""Small wrapper around the YouTube Data API v3.

Why a wrapper? Every call needs the same things: the API key, a timeout,
retries when YouTube has a hiccup, and a clean stop when the daily quota
is gone. Writing that once here keeps collect.py short and readable.
"""
import time

import requests

from config import API_BASE_URL, API_KEY


class QuotaExceededError(Exception):
    """Daily quota is used up. Only fix: wait for the daily reset."""


class NotFoundError(Exception):
    """Channel or playlist does not exist (deleted, or wrong ID)."""


class ApiError(Exception):
    """Any other error that retrying will not fix (bad key, API not enabled...)."""


# Temporary problems: worth waiting a few seconds and trying again.
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "backendError"}
# Daily quota gone: retrying only wastes time.
QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded"}


def _error_reason(resp):
    """YouTube explains errors in JSON: {"error": {"errors": [{"reason": ...}]}}."""
    try:
        return resp.json()["error"]["errors"][0]["reason"]
    except (ValueError, KeyError, IndexError, TypeError):
        return "unknown"


class YouTubeClient:
    def __init__(self, api_key=API_KEY, max_attempts=4):
        if not api_key:
            raise ApiError("No API key. Put YOUTUBE_API_KEY in .env (see docs/api_key_setup.md).")
        self.session = requests.Session()  # reuses one connection: faster than new ones
        # Send the key in a header, not in the URL. Error messages and logs often
        # print the full URL; they never print headers, so the key can't leak there.
        self.session.headers["X-Goog-Api-Key"] = api_key
        self.max_attempts = max_attempts
        self.units_used = 0  # list calls cost 1 unit each (search.list would cost 100)

    def get(self, endpoint, params):
        """GET one API endpoint, e.g. get("videos", {...}). Returns the parsed JSON."""
        url = f"{API_BASE_URL}/{endpoint}"
        problem = ""
        for attempt in range(1, self.max_attempts + 1):
            try:
                resp = self.session.get(url, params=params, timeout=30)
            except (requests.ConnectionError, requests.Timeout) as exc:
                problem = f"network error ({type(exc).__name__})"
            else:
                self.units_used += 1  # YouTube charges quota once it receives a request
                if resp.status_code == 200:
                    return resp.json()

                reason = _error_reason(resp)
                if reason in QUOTA_REASONS:
                    raise QuotaExceededError(reason)
                if resp.status_code == 404 or reason.endswith("NotFound"):
                    raise NotFoundError(f"{endpoint}: {reason}")
                if resp.status_code not in RETRY_STATUS and reason not in RETRY_REASONS:
                    raise ApiError(f"{endpoint}: HTTP {resp.status_code}, reason = {reason}")
                problem = f"HTTP {resp.status_code} ({reason})"

            if attempt < self.max_attempts:
                wait = 2 ** attempt  # 2, 4, 8 seconds: "exponential backoff"
                print(f"    {problem}. Retrying in {wait}s (attempt {attempt}/{self.max_attempts})")
                time.sleep(wait)

        raise ApiError(f"{endpoint}: still failing after {self.max_attempts} attempts: {problem}")
