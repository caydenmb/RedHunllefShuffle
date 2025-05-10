# chknrace.py — Fixed for Top 10 Support, Full Logging, Countdown May 10–23

import requests
import time
import json
from flask import Flask, jsonify, render_template
from datetime import datetime
import os
import threading
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# === Shuffle.com API Key and Epoch Window ===
api_key = "f45f746d-b021-494d-b9b6-b47628ee5cc9"

# May 10, 2025 00:00 AM EST → May 23, 2025 11:59 PM EST
start_time = 1746830400
end_time   = 1748014740

# Endpoint template
url_template = f"https://affiliate.shuffle.com/stats/{api_key}?startTime={{start_time}}&endTime={{end_time}}"

# Cached leaderboard data
data_cache = {}

def log_message(level, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level.upper()}]: {message}")

# === API Fetch Function ===
def fetch_data():
    global data_cache
    try:
        log_message('info', 'Starting data fetch from Shuffle.com API')

        # Construct URL with current time window
        url = url_template.format(start_time=start_time, end_time=end_time)
        log_message('debug', f"Fetching data from: {url}")

        response = requests.get(url)

        if response.status_code == 400 and "INVALID_DATE" in response.text:
            log_message('warning', 'Invalid date range — falling back to lifetime data')
            url = f"https://affiliate.shuffle.com/stats/{api_key}"
            response = requests.get(url)

        if response.status_code != 200:
            log_message('error', f"API fetch failed: HTTP {response.status_code}")
            log_message('error', f"Response content: {response.text}")
            data_cache = {"error": f"API error {response.status_code}"}
            return

        raw_data = response.json()
        log_message('info', f"Received API response with {len(raw_data)} entries")

        if not isinstance(raw_data, list):
            log_message('error', 'Unexpected API response format (not a list)')
            data_cache = {"error": "Invalid API response structure"}
            return

        # Filter for campaignCode = 'Red'
        filtered = [entry for entry in raw_data if entry.get('campaignCode') == 'Red']
        log_message('info', f"Found {len(filtered)} entries with campaignCode='Red'")

        if not filtered:
            log_message('warning', 'No matching campaignCode=Red entries')
            data_cache = {"error": "No campaign data available"}
            return

        # Sort top wagerers
        sorted_data = sorted(filtered, key=lambda x: x.get('wagerAmount', 0), reverse=True)

        # Build leaderboard data
        top_wagerers = {}
        for i in range(min(10, len(sorted_data))):  # Track up to top 10
            entry = sorted_data[i]
            username = entry.get('username', 'Unknown')
            wager_amount = entry.get('wagerAmount', 0.0)
            formatted_amount = f"${wager_amount:,.2f}"

            top_wagerers[f'top{i+1}'] = {
                'username': username,
                'wager': formatted_amount
            }

            # ✨ Log each player
            log_message('debug', f"#{i+1}: {username} wagered {formatted_amount}")

        # Cache the result
        data_cache = top_wagerers
        log_message('info', f"Leaderboard updated with top {len(top_wagerers)} players")

    except Exception as e:
        log_message('error', f"Exception during fetch: {str(e)}")
        data_cache = {"error": str(e)}

# === Recurring Scheduler ===
def schedule_data_fetch():
    fetch_data()
    log_message('info', 'Next fetch scheduled in 75 seconds...')
    threading.Timer(75, schedule_data_fetch).start()

# === Routes ===
@app.route("/data")
def get_data():
    log_message('info', 'Client requested leaderboard (/data)')
    return jsonify(data_cache)

@app.route("/")
def serve_index():
    log_message('info', 'Serving index.html')
    return render_template("index.html")

@app.errorhandler(404)
def not_found(e):
    log_message('warning', '404 - Page not found')
    return render_template("404.html"), 404

# === App Entry ===
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    log_message('info', f"Starting Flask app on port {port}")
    schedule_data_fetch()
    app.run(host="0.0.0.0", port=port)
