"""Project settings in one place, so other scripts never hardcode paths or numbers."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = the folder above src/. Using this (not "the current folder")
# means scripts work no matter where you start them from.
ROOT = Path(__file__).resolve().parent.parent

# Load YOUTUBE_API_KEY from the .env file into environment variables.
load_dotenv(ROOT / ".env")
API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()

# Folders
CHANNELS_CSV = ROOT / "config" / "channels.csv"
RAW_DIR = ROOT / "data" / "raw"              # untouched API responses (JSON)
PROCESSED_DIR = ROOT / "data" / "processed"  # cleaned tables (CSV)
DB_PATH = ROOT / "db" / "youtube.db"         # SQLite database file
FIGURES_DIR = ROOT / "reports" / "figures"   # saved charts for the README

# Analysis settings
MAX_VIDEOS_PER_CHANNEL = 200
LOCAL_TIMEZONE = "Asia/Jakarta"

# YouTube Data API
API_BASE_URL = "https://www.googleapis.com/youtube/v3"
