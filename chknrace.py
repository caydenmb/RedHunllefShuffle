# chknrace.py
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

# Shuffle.com API key
api_key = "f45f746d-b021-494d-b9b6-b47628ee5cc9"

# Base URL for Shuffle.com API with placeholders
url_template = f"https://affiliate.shuffle.com/stats/{api_key}?startTime={{start_time}}&endTime={{end_time}}"

# Define start_time as fixed epoch and end_time dynamic
start_time = 1745371655

# Data cache
data_cache = {}

def log_message(level, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level.upper()}]: {message}")

def fetch_data():
    global data_cache
    try:
        log_message('info', 'Starting data fetch from Shuffle.com API')
        end_time = int(time.time()) - 15
        log_message('debug', f"Current end_time: {end_time}")
        url = url_template.format(start_time=start_time, end_time=end_time)
        log_message('debug', f"Fetching from URL: {url}")
        response = requests.get(url)

        if response.status_code == 400 and "INVALID_DATE" in response.text:
            log_message('warning', 'Invalid date range, fetching lifetime data.')
            url = f"https://affiliate.shuffle.com/stats/{api_key}"
            response = requests.get(url)

        log_message('debug', f"Status code: {response.status_code}")

        if response.status_code == 200:
            api_response = response.json()
            log_message('info', f"Raw API response: {json.dumps(api_response)}")
            if isinstance(api_response, list):
                filtered = [e for e in api_response if e.get('campaignCode') == 'Red']
                if filtered:
                    data_cache = filtered
                    log_message('info', 'Data fetched and cached.')
                    update_placeholder_data()
                else:
                    log_message('warning', 'No data for campaignCode "Red".')
                    data_cache = {"error": "No data found for campaignCode 'Red'."}
            else:
                log_message('warning', 'Invalid data structure.')
                data_cache = {"error": "Invalid data structure."}
        else:
            log_message('error', f"Failed to fetch: {response.status_code}")
            log_message('error', response.text)
    except Exception as e:
        log_message('error', f"Exception during fetch: {e}")
        data_cache = {"error": str(e)}

def update_placeholder_data():
    global data_cache
    try:
        if isinstance(data_cache, list):
            sorted_data = sorted(data_cache, key=lambda x: x['wagerAmount'], reverse=True)
            top = {}
            for i in range(min(12, len(sorted_data))):
                top[f'top{i+1}'] = {
                    'username': sorted_data[i]['username'],
                    'wager': f"${sorted_data[i]['wagerAmount']:,.2f}"
                }
            data_cache = top
            log_message('info', f"Top wagerers: {top}")
        else:
            log_message('warning', 'No valid list to update.')
    except Exception as e:
        log_message('error', f"Error updating data: {e}")

def schedule_data_fetch():
    log_message('info', 'Scheduling data fetch every 90 seconds.')
    fetch_data()
    threading.Timer(90, schedule_data_fetch).start()

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
    log_message('warning', '404 error')
    return render_template('404.html'), 404

# Start data fetching loop
schedule_data_fetch()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    log_message('info', f"Starting Flask on port {port}")
    app.run(host="0.0.0.0", port=port)
