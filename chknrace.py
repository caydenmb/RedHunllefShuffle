# chknrace.py — Shuffle Wager Race Backend (Top 10, May 10–23)
import requests
import time
import json
from flask import Flask, jsonify, render_template
from datetime import datetime
import os
import threading
from flask_cors import CORS

# === Initialize Flask app ===
app = Flask(__name__)
CORS(app)

# === Shuffle API Key and Time Range ===
api_key = "f45f746d-b021-494d-b9b6-b47628ee5cc9"  # Replace if needed

# May 10, 2025 @ 12:00 AM EST → May 23, 2025 @ 11:59 PM EST
start_time = 1746830400
end_time   = 1748014740

url_template = f"https://affiliate.shuffle.com/stats/{api_key}?startTime={{start_time}}&endTime={{end_time}}"

# === Cached leaderboard data ===
data_cache = {}

# === Logging function ===
def log_message(level, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level.upper()}]: {message}")

# === Fetch data from Shuffle API ===
def fetch_data():
    global data_cache
    try:
        log_message('info', 'Fetching leaderboard data...')

        url = url_template.format(start_time=start_time, end_time=end_time)
        log_message('debug', f"Requesting: {url}")

        response = requests.get(url)

        if response.status_code == 400 and "INVALID_DATE" in response.text:
            log_message('warning', 'Invalid date range, falling back to lifetime stats')
            url = f"https://affiliate.shuffle.com/stats/{api_key}"
            response = requests.get(url)

        if response.status_code != 200:
            log_message('error', f"Failed to fetch data: HTTP {response.status_code}")
            data_cache = {"error": f"API error {response.status_code}"}
            return

        api_data = response.json()

        if not isinstance(api_data, list):
            log_message('error', 'Unexpected API response format (not a list)')
            data_cache = {"error": "Invalid response format"}
            return

        filtered = [entry for entry in api_data if entry.get('campaignCode') == 'Red']
        log_message('info', f"Filtered {len(filtered)} entries with campaignCode='Red'")

        if not filtered:
            data_cache = {"error": "No entries found for campaignCode 'Red'"}
            return

        sorted_data = sorted(filtered, key=lambda x: x.get('wagerAmount', 0), reverse=True)

        top_wagerers = {}
        count = min(10, len(sorted_data))  # Support top 10 max

        for i in range(count):
            entry = sorted_data[i]
            username = entry.get('username', 'Unknown')
            amount   = entry.get('wagerAmount', 0.0)

            top_wagerers[f'top{i+1}'] = {
                'username': username,
                'wager': f"${amount:,.2f}"
            }

        data_cache = top_wagerers
        log_message('info', f"Updated leaderboard with top {count} players.")

    except Exception as e:
        log_message('error', f"Exception in fetch_data: {str(e)}")
        data_cache = {"error": str(e)}

# === Periodic Fetch Thread ===
def schedule_data_fetch():
    fetch_data()
    log_message('info', 'Next fetch in 75 seconds...')
    threading.Timer(75, schedule_data_fetch).start()

# === Flask Routes ===
@app.route("/data")
def get_data():
    log_message('info', 'Client requested leaderboard via /data')
    return jsonify(data_cache)

@app.route("/")
def serve_index():
    log_message('info', 'Serving index.html')
    return render_template("index.html")

@app.errorhandler(404)
def page_not_found(e):
    log_message('warning', '404 - Page not found')
    return render_template("404.html"), 404

# === Launch Flask App ===
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    log_message('info', f"Launching app on port {port}")
    schedule_data_fetch()
    app.run(host="0.0.0.0", port=port)
