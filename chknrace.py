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

API_KEY    = "f45f746d-b021-494d-b9b6-b47628ee5cc9"
START_TIME = 1746833400  # May 10, 2025, 00:01 AM ET
END_TIME   = 1748059140  # May 23, 2025, 11:59 PM ET

URL_TEMPLATE = "https://affiliate.shuffle.com/stats/{API_KEY}?startTime={start_time}&endTime={end_time}"

data_cache = {}  # In-memory cache

# --- Logging ---------------------------------------------------------------

def log_message(level: str, msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level.upper()}]: {msg}")

# --- Data Fetch & Processing ----------------------------------------------

def fetch_data():
    """Fetch, filter, sort, format top9, and cache."""
    global data_cache
    log_message('info', 'Fetching data from Shuffle.com API')
    try:
        # Apply format to replace the placeholders with actual values
        url = URL_TEMPLATE.format(API_KEY=API_KEY, start_time=START_TIME, end_time=END_TIME)
        log_message('debug', f"GET {url}")
        resp = requests.get(url)
        log_message('debug', f"Status {resp.status_code}")

        if resp.status_code == 400 and "INVALID_DATE" in resp.text:
            log_message('warning', 'Invalid date range; fetching lifetime stats')
            resp = requests.get(f"https://affiliate.shuffle.com/stats/{API_KEY}")
            log_message('debug', f"Fallback status {resp.status_code}")

        if resp.status_code != 200:
            log_message('error', f"Fetch failed: {resp.status_code}")
            data_cache = {"error": "Fetch failed"}
            return

        api_data = resp.json()
        if not isinstance(api_data, list):
            log_message('error', 'Unexpected API response format')
            data_cache = {"error": "Invalid API format"}
            return

        log_message('info', f"API returned {len(api_data)} entries")
        filtered = [e for e in api_data if e.get('campaignCode') == 'Red']
        log_message('info', f"Filtered to {len(filtered)} entries for campaign 'Red'")

        sorted_list = sorted(filtered, key=lambda x: x.get('wagerAmount', 0), reverse=True)
        top9 = {}
        for i, entry in enumerate(sorted_list[:9], start=1):
            uname = entry.get('username', 'Unknown')
            amt   = entry.get('wagerAmount', 0.0)
            wstr  = f"${amt:,.2f}"
            top9[f"top{i}"] = {"username": uname, "wager": wstr}
            log_message('debug', f"Rank {i}: {uname} – {wstr}")

        data_cache = top9
        log_message('info', 'data_cache updated with top 9 wagers')

    except Exception as e:
        log_message('error', f"Exception during fetch: {e}")
        data_cache = {"error": str(e)}

def schedule_data_fetch():
    """Fetch immediately, then every 75 seconds."""
    fetch_data()
    log_message('info', 'Next fetch in 75 seconds')
    threading.Timer(75, schedule_data_fetch).start()

# Kick off on import (works under Gunicorn too)
schedule_data_fetch()

# --- Flask Routes ----------------------------------------------------------

@app.route("/data")
def get_data():
    log_message('info', 'Serving /data')
    return jsonify(data_cache)

@app.route("/")
def serve_index():
    log_message('info', 'Serving index.html')
    return render_template('index.html')

@app.errorhandler(404)
def page_not_found(e):
    log_message('warning', '404 – Page Not Found')
    return render_template('404.html'), 404

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    log_message('info', f"Starting Flask app on port {port}")
    app.run(host="0.0.0.0", port=port)
