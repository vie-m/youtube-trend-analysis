# Local raw data

Raw YouTube Data API responses are intentionally not included in this repository.

To create a fresh local snapshot:

1. Follow [../../docs/api_key_setup.md](../../docs/api_key_setup.md).
2. Put your key in the local `.env` file only.
3. Double-click `../../collect.bat`.
4. Double-click `../../load_db.bat`.
5. Double-click `../../features.bat`.

The collector uses YouTube Data API v3 and saves responses under this folder. The data is subject to YouTube API Services policies; refresh or delete stored statistics according to current policy requirements.
