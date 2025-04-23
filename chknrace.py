# chknrace.py
"""
Flask backend for the Shuffle Wager Race website.
Fetches data from Shuffle.com every 90 seconds, filters for campaign 'Red',
formats the top 9 wagerers, and serves JSON at /data for the frontend.
Includes detailed console logging and error handling.
"""
import requests
import time
from flask import Flask, jsonify, render_template
from datetime import datetime
import os
import threading
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow JS on the frontend to fetch /data

# --- Configuration ---------------------------------------------------------

# Your Shuffle.com API key
API_KEY = "f45f746d-b021-494d-b9b6-b47628ee5cc9"

# Fixed epoch timestamps:
#   start_time: April 22, 2025 21:27:35 EDT
#   end_time:   May 9, 2025 23:59:00 EDT => UTC-4 => UTC 2025-05-10 03:59:00
START_TIME = 1745371655
END_TIME   = 1746849540

# Base URL template
URL_TEMPLATE = (
    f"https://affiliate.shuffle.com/stats/{API_KEY}"
    f"?startTime={{start_time}}&endTime={{end_time}}"
)

# In-memory cache for the top 9 wagerers
data_cache = {}

# --- Logging ---------------------------------------------------------------

def log_message(level: str, msg: str):
    """Print a timestamped log message."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level.upper()}]: {msg}")

# --- Data Fetch and Processing ---------------------------------------------

def fetch_data():
    """
    Fetch raw stats from Shuffle.com,
    filter entries where campaignCode == 'Red',
    sort by wagerAmount descending,
    keep top 9, format as {"top1": {...}, ..., "top9": {...}},
    and store in data_cache.
    """
    global data_cache
    log_message('info', 'Starting data fetch from Shuffle.com API')
    try:
        url = URL_TEMPLATE.format(start_time=START_TIME, end_time=END_TIME)
        log_message('debug', f"Requesting URL: {url}")
        resp = requests.get(url)
        log_message('debug', f"Received status code: {resp.status_code}")

        # Fallback if date range invalid
        if resp.status_code == 400 and "INVALID_DATE" in resp.text:
            log_message('warning', 'Invalid date range; fetching lifetime stats')
            resp = requests.get(f"https://affiliate.shuffle.com/stats/{API_KEY}")
            log_message('debug', f"Fallback status code: {resp.status_code}")

        if resp.status_code != 200:
            log_message('error', f"Fetch failed with status {resp.status_code}")
            data_cache = {"error": "Fetch failed"}
            return

        api_data = resp.json()
        if not isinstance(api_data, list):
            log_message('error', 'Unexpected API response format')
            data_cache = {"error": "Invalid API format"}
            return

        log_message('info', f"API returned {len(api_data)} total entries")
        filtered = [e for e in api_data if e.get('campaignCode') == 'Red']
        log_message('info', f"Filtered to {len(filtered)} entries for campaign 'Red'")

        # Sort descending by wagerAmount
        sorted_list = sorted(filtered, key=lambda x: x.get('wagerAmount', 0), reverse=True)

        # Take top 9
        top9 = {}
        for i, entry in enumerate(sorted_list[:9], start=1):
            uname = entry.get('username', 'Unknown')
            amt   = entry.get('wagerAmount', 0.0)
            wager_formatted = f"${amt:,.2f}"
            top9[f"top{i}"] = {"username": uname, "wager": wager_formatted}
            log_message('debug', f"Rank {i}: {uname} – {wager_formatted}")

        data_cache = top9
        log_message('info', 'data_cache updated with top 9 wagers')

    except Exception as e:
        log_message('error', f"Exception during fetch: {e}")
        data_cache = {"error": str(e)}

def schedule_data_fetch():
    """Fetch immediately, then every 90 seconds."""
    log_message('info', 'Scheduling data fetch in 90 seconds')
    fetch_data()
    threading.Timer(90, schedule_data_fetch).start()

# Kick off the first fetch on import (works under Gunicorn too)
schedule_data_fetch()

# --- Flask Routes ----------------------------------------------------------

@app.route("/data")
def get_data():
    """Serve the latest processed wager data as JSON."""
    log_message('info', 'Serving /data')
    return jsonify(data_cache)

@app.route("/")
def serve_index():
    """Serve the main HTML page."""
    log_message('info', 'Serving index.html')
    return render_template('index.html')

@app.errorhandler(404)
def page_not_found(e):
    """Custom 404 page."""
    log_message('warning', '404 – Page Not Found')
    return render_template('404.html'), 404

# Only call app.run when executed directly
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    log_message('info', f"Starting Flask app on port {port}")
    app.run(host="0.0.0.0", port=port)
