# chknrace.py
"""
Flask backend for the Shuffle Wager Race.
Pulls top 10 wagerers from the Shuffle API every 75 seconds,
filters by campaignCode='Red', and returns structured JSON for frontend.
"""

import requests
import time
import json
from flask import Flask, jsonify, render_template
from datetime import datetime
import os
import threading
from flask_cors import CORS

# === Flask Setup ===
app = Flask(__name__)
CORS(app)

# === API Setup ===
api_key = "f45f746d-b021-494d-b9b6-b47628ee5cc9"  # Replace with your valid key
start_time = 1746849600  # Epoch (example: April 22)
end_time   = 1745531940  # Epoch for May 23, 2025 11:59 PM EST (converted to UTC)
url_template = f"https://affiliate.shuffle.com/stats/{api_key}?startTime={{start_time}}&endTime={{end_time}}"

# === Global Cache ===
data_cache = {}

# === Logging ===
def log_message(level, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level.upper()}]: {message}")

# === Fetch Data from API ===
def fetch_data():
    global data_cache
    try:
        log_message('info', 'Starting data fetch from Shuffle.com API')
        url = url_template.format(start_time=start_time, end_time=end_time)
        log_message('debug', f"GET {url}")
        response = requests.get(url)

        if response.status_code == 400 and "INVALID_DATE" in response.text:
            log_message('warning', 'Invalid date; falling back to lifetime stats')
            url = f"https://affiliate.shuffle.com/stats/{api_key}"
            response = requests.get(url)

        if response.status_code != 200:
            log_message('error', f"Failed to fetch data: {response.status_code}")
            data_cache = {"error": f"API error {response.status_code}"}
            return

        api_data = response.json()

        if not isinstance(api_data, list):
            log_message('error', 'API did not return a list')
            data_cache = {"error": "Unexpected API format"}
            return

        log_message('info', f"API returned {len(api_data)} records")
        filtered = [entry for entry in api_data if entry.get('campaignCode') == 'Red']
        log_message('info', f"{len(filtered)} records matched campaignCode='Red'")

        sorted_data = sorted(filtered, key=lambda x: x.get('wagerAmount', 0), reverse=True)

        top_wagerers = {}
        for i in range(min(10, len(sorted_data))):  # Top 10 only
            entry = sorted_data[i]
            username = entry.get('username', 'Unknown')
            amount = entry.get('wagerAmount', 0.0)
            top_wagerers[f'top{i+1}'] = {
                'username': username,
                'wager': f"${amount:,.2f}"
            }

        data_cache = top_wagerers
        log_message('info', f"Leaderboard updated with top {len(top_wagerers)} users.")

    except Exception as e:
        log_message('error', f"Exception occurred during data fetch: {str(e)}")
        data_cache = {"error": str(e)}

# === Scheduled Fetch ===
def schedule_data_fetch():
    fetch_data()
    log_message('info', 'Next data fetch scheduled in 75 seconds')
    threading.Timer(75, schedule_data_fetch).start()

# === Flask Routes ===
@app.route("/data")
def get_data():
    log_message('info', 'Serving /data to frontend')
    return jsonify(data_cache)

@app.route("/")
def serve_index():
    log_message('info', 'Serving index.html')
    return render_template("index.html")

@app.errorhandler(404)
def page_not_found(e):
    log_message('warning', '404 error: page not found')
    return render_template("404.html"), 404

# === App Entry Point ===
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    log_message('info', f"Starting Flask app on port {port}")
    schedule_data_fetch()
    app.run(host="0.0.0.0", port=port)
