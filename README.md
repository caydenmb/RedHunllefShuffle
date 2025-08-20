# Shuffle.com Wager Race

This app shows a live **Shuffle.com wager race** with an Olympic-style podium, a single-row leaderboard for ranks 4–10, and a bottom-right **Kick** mini-player.

## What changed in this patch
- Fixed a case where the **PRIZE** text on top-3 cards could be clipped:
  - Podium cards now use **min-height** (not strict height), a bit more bottom padding, and `overflow: visible`.
  - The top-3 **PRIZE** uses the same green as ranks 4–10.

## Run locally
```bash
# 1) Create & activate a virtual environment
python3 -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows (PowerShell):
# .\.venv\Scripts\Activate.ps1

# 2) Install deps directly
python -m pip install --upgrade pip
python -m pip install Flask Flask-Cors requests gunicorn

# 3) (optional) Environment overrides
export API_KEY="your-affiliate-api-key"
export START_TIME=1755662460
export END_TIME=1756871940
export REFRESH_SECONDS=60
export PORT=8080

# 4) Start
python wager_backend.py
# or (single worker so the scheduler runs once)
gunicorn -w 1 -b 0.0.0.0:${PORT:-8080} wager_backend:app
