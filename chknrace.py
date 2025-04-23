# chknrace.py
"""
Flask backend for the Shuffle Wager Race website.
Fetches data from Shuffle.com every 90 seconds, filters by campaign "Red",
formats the top 9 wagerers, and serves JSON at /data for the frontend.
Includes detailed console logging and error handling.
"""
import requests
import time
import json
from flask import Flask, jsonify, render_template
from datetime import datetime
import os
import threading
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow cross-origin from our UI

# Shuffle.com API key and URL template
api_key = "f45f746d-b021-494d-b9b6-b47628ee5cc9"
url_template = f"https://affiliate.shuffle.com/stats/{api_key}?startTime={{start_time}}&endTime={{end_time}}"

# Race window start: April 22, 2025 21:27:35 EDT
start_time = 1745371655

# In-memory cache for processed top wagers
data_cache = {}

def log_message(level, msg):
    """Print a timestamped log."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level.upper()}] {msg}")

def fetch_data():
    """Fetch raw stats, filter, and update data_cache."""
    global data_cache
    log_message('info', 'Starting data fetch from Shuffle API')
    try:
        end_time = int(time.time()) - 15
        log_message('debug', f"Computed end_time = {end_time}")
        url = url_template.format(start_time=start_time, end_time=end_time)
        log_message('debug', f"Fetching URL: {url}")
        resp = requests.get(url)
        log_message('debug', f"Received status {resp.status_code}")
        
        # Fallback on invalid date
        if resp.status_code == 400 and "INVALID_DATE" in resp.text:
            log_message('warning', 'Invalid date range, fetching lifetime stats')
            resp = requests.get(f"https://affiliate.shuffle.com/stats/{api_key}")
            log_message('debug', f"Fallback status {resp.status_code}")
        
        if resp.status_code == 200:
            raw = resp.json()
            log_message('info', f"API returned {len(raw) if isinstance(raw, list) else 'N/A'} entries")
            if isinstance(raw, list):
                filtered = [e for e in raw if e.get('campaignCode') == 'Red']
                log_message('info', f"Filtered to {len(filtered)} 'Red' entries")
                data_cache = filtered
                update_placeholder_data()
            else:
                log_message('error', 'Unexpected API response format')
                data_cache = {"error": "Invalid API structure"}
        else:
            log_message('error', f"Fetch failed: {resp.status_code}")
            data_cache = {"error": "Fetch error"}
    except Exception as e:
        log_message('error', f"Exception during fetch: {e}")
        data_cache = {"error": str(e)}

def update_placeholder_data():
    """Sort by wagerAmount, pick top 9, format into data_cache."""
    global data_cache
    if not isinstance(data_cache, list):
        log_message('warning', 'No list data to process')
        return
    try:
        sorted_list = sorted(data_cache, key=lambda x: x['wagerAmount'], reverse=True)
        top = {}
        for i in range(min(9, len(sorted_list))):
            entry = sorted_list[i]
            uname = entry.get('username', 'Unknown')
            amt   = entry.get('wagerAmount', 0.0)
            formatted = f"${amt:,.2f}"
            top[f"top{i+1}"] = {"username": uname, "wager": formatted}
            log_message('debug', f"Rank {i+1}: {uname} – {formatted}")
        data_cache = top
        log_message('info', 'Cache updated with top wagers')
    except Exception as e:
        log_message('error', f"Error processing data: {e}")

def schedule_data_fetch():
    """Fetch now and schedule next fetch in 90 seconds."""
    log_message('info', 'Scheduling next data fetch in 90s')
    fetch_data()
    threading.Timer(90, schedule_data_fetch).start()

@app.route("/data")
def get_data():
    """Endpoint: returns latest formatted wager data as JSON."""
    log_message('info', 'Serving /data')
    return jsonify(data_cache)

@app.route("/")
def serve_index():
    """Endpoint: serves main HTML page."""
    log_message('info', 'Serving index.html')
    return render_template('index.html')

@app.errorhandler(404)
def page_not_found(e):
    """Custom 404 page."""
    log_message('warning', '404 – Page Not Found')
    return render_template('404.html'), 404

if __name__ == "__main__":
    schedule_data_fetch()
    port = int(os.getenv("PORT", 8080))
    log_message('info', f"Starting Flask on port {port}")
    app.run(host="0.0.0.0", port=port)
