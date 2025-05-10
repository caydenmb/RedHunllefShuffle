# chknrace.py — Guaranteed Top 10 Fetching, Console Logging Restored

import requests
import time
import json
from flask import Flask, jsonify, render_template
from datetime import datetime
import os
import threading
from flask_cors import CORS

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# === API KEY & TIME RANGE (May 10 – May 23, 2025 in EST) ===
api_key = "f45f746d-b021-494d-b9b6-b47628ee5cc9"
start_time = 1746830400  # May 10, 2025 12:00 AM EST
end_time   = 1748014740  # May 23, 2025 11:59 PM EST

url_template = f"https://affiliate.shuffle.com/stats/{api_key}?startTime={{start_time}}&endTime={{end_time}}"

# Cached leaderboard
data_cache = {}

# === Logging Function ===
def log(level, message):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{level.upper()}]: {message}")

# === Fetch from Shuffle API and update cache ===
def fetch_data():
    global data_cache
    try:
        log('info', 'Fetching data from Shuffle API...')

        url = url_template.format(start_time=start_time, end_time=end_time)
        log('debug', f"Requesting URL: {url}")
        response = requests.get(url)

        if response.status_code == 400 and "INVALID_DATE" in response.text:
            log('warning', 'Invalid date range — retrying with lifetime stats')
            response = requests.get(f"https://affiliate.shuffle.com/stats/{api_key}")

        if response.status_code != 200:
            log('error', f"HTTP {response.status_code}: {response.text}")
            data_cache = {"error": f"Status code {response.status_code}"}
            return

        api_data = response.json()
        log('info', f"Received {len(api_data)} total entries from API")

        if not isinstance(api_data, list):
            log('error', 'Expected list from API, got something else.')
            data_cache = {"error": "Invalid API format"}
            return

        # Filter for campaignCode = 'Red'
        filtered = [e for e in api_data if e.get('campaignCode') == 'Red']
        log('info', f"{len(filtered)} entries matched campaignCode='Red'")

        # Sort by wagerAmount
        sorted_entries = sorted(filtered, key=lambda x: x.get('wagerAmount', 0), reverse=True)

        # Limit to top 10 safely
        top_wagerers = {}
        for i, entry in enumerate(sorted_entries[:10]):
            username = entry.get('username', 'Unknown')
            wager_amt = entry.get('wagerAmount', 0.0)
            formatted = f"${wager_amt:,.2f}"
            top_wagerers[f'top{i+1}'] = {
                'username': username,
                'wager': formatted
            }
            log('debug', f"Top {i+1}: {username} wagered {formatted}")

        data_cache = top_wagerers
        log('success', f"Leaderboard updated with {len(top_wagerers)} users.")

    except Exception as e:
        log('error', f"Exception during fetch: {str(e)}")
        data_cache = {"error": str(e)}

# === Repeating fetch every 75 seconds ===
def schedule_fetch_loop():
    fetch_data()  # ← Fetch immediately on start
    threading.Timer(75, schedule_fetch_loop).start()

# === Flask Routes ===
@app.route("/data")
def serve_data():
    log('info', 'Serving cached /data to client')
    return jsonify(data_cache)

@app.route("/")
def serve_index():
    log('info', 'Serving index.html')
    return render_template("index.html")

@app.errorhandler(404)
def handle_404(e):
    log('warning', '404 — Page Not Found')
    return render_template("404.html"), 404

# === Application Entry Point ===
if __name__ == "__main__":
    log('info', 'Starting Flask application on port 8080...')
    schedule_fetch_loop()  # Start repeated fetches + fetch on launch
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
