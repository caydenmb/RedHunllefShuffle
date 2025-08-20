from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List

import requests
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

# -----------------------------------------------------------------------------
# Flask app + CORS
# -----------------------------------------------------------------------------
app = Flask(__name__)
CORS(app)  # allow our static JS to call /data and /config

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
API_KEY = os.getenv("API_KEY", "f45f746d-b021-494d-b9b6-b47628ee5cc9")
START_TIME = int(os.getenv("START_TIME", "1755662460"))  # Aug 20, 2025 00:01 ET
END_TIME = int(os.getenv("END_TIME", "1756871940"))      # Sep 02, 2025 23:59 ET
REFRESH_SECONDS = int(os.getenv("REFRESH_SECONDS", "60"))

URL_TEMPLATE = (
    "https://affiliate.shuffle.com/stats/{API_KEY}"
    "?startTime={start}&endTime={end}"
)

# Ensure logs directory exists
os.makedirs("logs", exist_ok=True)

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
import logging
from logging.handlers import RotatingFileHandler

LOGGER = logging.getLogger("wager")
LOGGER.setLevel(logging.DEBUG)

_format = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")

_console = logging.StreamHandler()
_console.setLevel(logging.DEBUG)
_console.setFormatter(_format)
LOGGER.addHandler(_console)

_file = RotatingFileHandler("logs/audit.log", maxBytes=2_000_000, backupCount=5)
_file.setLevel(logging.DEBUG)
_file.setFormatter(_format)
LOGGER.addHandler(_file)

def log(level: str, message: str) -> None:
    """Emit a one-line, greppable record: event=... key=value ..."""
    getattr(LOGGER, level.lower())(message)

log("info", "event=server.boot msg='Starting Shuffle.com wager backend'")

# -----------------------------------------------------------------------------
# Shared state
# -----------------------------------------------------------------------------
_cache_lock = threading.Lock()
_data_cache: Dict[str, Any] = {"podium": [], "others": []}  # mutated under lock

_ip_counts = defaultdict(int)         # visibility only; not an enforcement
_last_minute_bucket = int(time.time() // 60)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def censor_username(username: str) -> str:
    if not username:
        return "******"
    return f"{username[:2]}{'*' * 6}"

def _fetch_from_shuffle() -> List[dict]:
    """
    Fetch raw affiliate stats from Shuffle.com.
    If the date range is invalid, fall back to lifetime stats.
    """
    headers = {"User-Agent": "Shuffle-WagerRace/Final/4.1"}
    url = URL_TEMPLATE.format(API_KEY=API_KEY, start=START_TIME, end=END_TIME)

    t0 = time.perf_counter()
    log("info", f"event=fetch.start url='{url}'")
    resp = requests.get(url, timeout=20, headers=headers)

    # Fallback if API signals invalid date window
    if resp.status_code == 400 and "INVALID_DATE" in resp.text:
        log("warning", "event=fetch.retry reason=INVALID_DATE url='lifetime'")
        resp = requests.get(f"https://affiliate.shuffle.com/stats/{API_KEY}", timeout=20, headers=headers)

    if resp.status_code != 200:
        raise RuntimeError(f"Shuffle API HTTP {resp.status_code}")

    dt_ms = (time.perf_counter() - t0) * 1000
    log("info", f"event=fetch.done status={resp.status_code} duration_ms={dt_ms:.1f}")

    data = resp.json()
    if not isinstance(data, list):
        raise ValueError("Unexpected API format (expected list)")
    return data

def _process_entries(entries: List[dict]) -> Dict[str, Any]:
    """
    Transform raw entries into shape for frontend:
      - podium: dicts for ranks 1..3
      - others: dicts for ranks 4..10 (10th allowed)
    We also log the FULL usernames to the console/audit (admin visibility).
    """
    filtered = [e for e in entries if e.get("campaignCode") == "Red"]
    log("info", f"event=process.in campaign='Red' count={len(filtered)}")

    # Sort by wagerAmount descending, being defensive about missing/str values
    def _wager(e: dict) -> float:
        try:
            return float(e.get("wagerAmount", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    sorted_entries = sorted(filtered, key=_wager, reverse=True)

    podium, others = [], []
    for i, entry in enumerate(sorted_entries[:10], start=1):
        username_full = entry.get("username", "Unknown")

        # --- SAFE conversion to float ---
        try:
            wager_amt = float(entry.get("wagerAmount", 0) or 0)
        except (TypeError, ValueError) as exc:
            log("error", f"event=wager.parse row={i} username_full='{username_full}' raw='{entry.get('wagerAmount')}' error='{exc}'")
            wager_amt = 0.0
        # ----------------------------------------------------------------

        # Currency formatting now safe on a number
        wager_str = f"${wager_amt:,.2f}"

        # Admin visibility: log the FULL username + wager
        log("debug", f"event=rank row={i} username_full='{username_full}' wager='{wager_str}'")

        public = {"username": censor_username(username_full), "wager": wager_str}
        if i <= 3:
            podium.append(public)
        else:
            others.append({"rank": i, **public})

    log("info", f"event=process.out podium={len(podium)} others={len(others)}")
    return {"podium": podium, "others": others}

def _save_snapshot(payload: Dict[str, Any]) -> None:
    """Persist the latest processed cache as JSON for audit/debug."""
    try:
        with open("logs/latest_cache.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        log("info", "event=snapshot.save path='logs/latest_cache.json' result=ok")
    except Exception as exc:
        log("error", f"event=snapshot.save path='logs/latest_cache.json' error='{exc}'")

def _refresh_cache() -> None:
    global _data_cache
    t0 = time.perf_counter()
    try:
        raw = _fetch_from_shuffle()
        processed = _process_entries(raw)
        with _cache_lock:
            _data_cache = processed
        _save_snapshot(processed)
        dt_ms = (time.perf_counter() - t0) * 1000
        log("info", f"event=cache.update podium={len(processed['podium'])} others={len(processed['others'])} duration_ms={dt_ms:.1f} result=success")
    except Exception as exc:
        dt_ms = (time.perf_counter() - t0) * 1000
        log("error", f"event=cache.update duration_ms={dt_ms:.1f} result=failed error='{exc}'")

def _schedule_refresh() -> None:
    """Start a self-rescheduling timer that refreshes every REFRESH_SECONDS."""
    _refresh_cache()
    threading.Timer(REFRESH_SECONDS, _schedule_refresh).start()

# Kick off the background refresh loop exactly once in this process
_schedule_refresh()

# -----------------------------------------------------------------------------
# Request auditing & security headers
# -----------------------------------------------------------------------------
@app.before_request
def _audit_request() -> None:
    """
    Log each request: ip, method, path, referer, user-agent, per-minute count.
    This is visibility-only; we do not hard-block high traffic.
    """
    global _last_minute_bucket
    now_bucket = int(time.time() // 60)
    if now_bucket != _last_minute_bucket:
        _ip_counts.clear()
        _last_minute_bucket = now_bucket

    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0].strip()
    ua = (request.user_agent.string or "").replace("\n", " ")[:160]
    ref = (request.referrer or "-").replace("\n", " ")[:160]
    path = request.path
    method = request.method

    _ip_counts[ip] += 1
    count = _ip_counts[ip]
    lvl = "warning" if count > 120 else "info"
    log(lvl, f"event=request ip={ip} method={method} path='{path}' ref='{ref}' ua='{ua}' count_min={count}")

@app.after_request
def _security_headers(resp):
    """Apply light security headers + log response status for auditing."""
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    log("info", f"event=response path='{request.path}' status={resp.status_code}")
    return resp

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.route("/")
def index():
    log("info", "event=render template='index.html'")
    return render_template("index.html")

@app.route("/data")
def data():
    with _cache_lock:
        payload = dict(_data_cache)  # shallow copy
    log("info", "event=api.hit name='/data'")
    return jsonify(payload)

@app.route("/config")
def config():
    log("info", "event=api.hit name='/config'")
    return jsonify(
        {"start_time": START_TIME, "end_time": END_TIME, "refresh_seconds": REFRESH_SECONDS}
    )

@app.route("/health")
def health():
    return jsonify({"ok": True})

@app.errorhandler(404)
def not_found(e):
    log("warning", f"event=404 path='{request.path}'")
    return render_template("404.html"), 404

# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    log("info", f"event=server.listen addr='0.0.0.0' port={port}")
    app.run(host="0.0.0.0", port=port)
