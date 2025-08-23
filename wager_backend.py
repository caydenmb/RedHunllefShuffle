# -*- coding: utf-8 -*-
import os
import re
import json
import time
import math
import queue
import sqlite3
import hashlib
import secrets
import logging
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from flask import (
    Flask, request, jsonify, render_template,
    send_from_directory, abort
)

# -----------------------------------------------------------------------------
# Basic app config
# -----------------------------------------------------------------------------
APP_NAME = "redhunllefshuffle"
app = Flask(__name__, template_folder="templates", static_folder="static")

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] event=%(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(APP_NAME)

# -----------------------------------------------------------------------------
# Environment / simple settings
# -----------------------------------------------------------------------------
# Countdown end (race end). You can override via env var RACE_END_EPOCH.
RACE_END_EPOCH = int(os.environ.get("RACE_END_EPOCH", str(int(time.time()) + 11*24*3600)))

# Kick API credentials (optional; if missing or blocked we fall back gracefully)
KICK_CLIENT_ID = os.environ.get("KICK_CLIENT_ID", "")
KICK_CLIENT_SECRET = os.environ.get("KICK_CLIENT_SECRET", "")

KICK_CHANNEL = os.environ.get("KICK_CHANNEL", "redhunllef")

# Cache timing
REFRESH_SECONDS = 60

# Analytics DB path (stdlib sqlite3)
AN_DB = os.environ.get("ANALYTICS_DB", "analytics.sqlite3")

# -----------------------------------------------------------------------------
# Helper: mask usernames for UI, keep full in logs
# -----------------------------------------------------------------------------
def mask_username(u: str) -> str:
    u = (u or "").strip()
    if len(u) < 2:
        return (u or "*") + "******"
    return u[:2] + "******"

# -----------------------------------------------------------------------------
# In-memory caches
# -----------------------------------------------------------------------------
state = {
    "data": {  # leaderboard cache
        "podium": [],  # list of dicts: {username,wager}
        "others": [],  # list of dicts: {rank,username,wager}
        "updated_at": 0,
    },
    "stream": {  # live/offline cache
        "live": False,
        "viewers": None,
        "source": "unknown",
        "updated_at": 0,
    },
    "kick_token": {
        "access_token": None,
        "expires_at": 0,
    },
    "health": {  # last probe status booleans
        "kick_ok": False,
        "shuffle_ok": True,
        "cache_ok": True,
        "updated_at": 0,
    }
}

# -----------------------------------------------------------------------------
# Analytics (stdlib only)
# -----------------------------------------------------------------------------
BOT_RE = re.compile(r"(bot|crawler|spider|fetch|monitor|pingdom|curl|wget)", re.I)
MOBILE_RE = re.compile(r"(iphone|android|ipad|mobile)", re.I)
TABLET_RE = re.compile(r"(ipad|tablet)", re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day TEXT NOT NULL,           -- 'YYYY-MM-DD'
  ts INTEGER NOT NULL,         -- epoch seconds
  visitor_id TEXT NOT NULL,    -- sha256(ip + daily_salt)
  session_id TEXT NOT NULL,    -- coarse session (hash ip+ua for day)
  path TEXT NOT NULL,
  referrer TEXT,
  device TEXT NOT NULL         -- 'mobile'|'desktop'|'tablet'
);

CREATE INDEX IF NOT EXISTS idx_visits_day ON visits(day);
CREATE INDEX IF NOT EXISTS idx_visits_vid ON visits(visitor_id);
CREATE INDEX IF NOT EXISTS idx_visits_ts  ON visits(ts);

CREATE TABLE IF NOT EXISTS podium_snapshots (
  ts INTEGER NOT NULL,         -- epoch seconds
  first TEXT, second TEXT, third TEXT
);

CREATE INDEX IF NOT EXISTS idx_podium_ts ON podium_snapshots(ts);

CREATE TABLE IF NOT EXISTS stream_log (
  ts INTEGER NOT NULL,
  live INTEGER NOT NULL,       -- 0/1
  viewers INTEGER
);

CREATE INDEX IF NOT EXISTS idx_stream_ts ON stream_log(ts);

CREATE TABLE IF NOT EXISTS salts (
  day TEXT PRIMARY KEY,
  salt TEXT NOT NULL
);
"""

def db_conn():
    con = sqlite3.connect(AN_DB, timeout=3)
    con.execute("PRAGMA journal_mode=WAL;")
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db_conn()
    try:
        con.executescript(SCHEMA)
        con.commit()
    finally:
        con.close()

init_db()

def get_daily_salt(day: str) -> str:
    """Returns a stable daily salt; generates and stores if missing."""
    con = db_conn()
    try:
        cur = con.execute("SELECT salt FROM salts WHERE day=?;", (day,))
        row = cur.fetchone()
        if row:
            return row["salt"]
        new = secrets.token_hex(16)
        con.execute("INSERT OR REPLACE INTO salts(day, salt) VALUES(?,?);", (day, new))
        con.commit()
        return new
    finally:
        con.close()

def device_from_ua(ua: str) -> str:
    if not ua:
        return "desktop"
    if TABLET_RE.search(ua):
        return "tablet"
    if MOBILE_RE.search(ua):
        return "mobile"
    return "desktop"

def is_bot(ua: str) -> bool:
    if not ua:
        return False
    return bool(BOT_RE.search(ua))

def coarse_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def track_visit():
    """Light, privacy-safe analytics for '/','/stats' (GET)."""
    try:
        if request.method != "GET":
            return
        if request.args.get("no_track") == "1":
            return
        if request.headers.get("DNT") == "1":
            return

        ua = request.headers.get("User-Agent", "")
        if is_bot(ua):
            return

        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "0.0.0.0").split(",")[0].strip()
        path = request.path
        if path not in ("/", "/stats"):
            # keep analytics focused; skip JSON APIs by default
            return

        now = int(time.time())
        day = datetime.utcnow().strftime("%Y-%m-%d")
        salt = get_daily_salt(day)
        visitor_id = coarse_hash(f"{ip}|{salt}")
        # crude session: hash of ip + UA + day
        session_id = coarse_hash(f"{ip}|{ua}|{day}")
        ref = request.headers.get("Referer", "")
        ref_host = ""
        if ref:
            try:
                ref_host = urlparse(ref).hostname or ""
            except Exception:
                ref_host = ""

        dev = device_from_ua(ua)

        con = db_conn()
        try:
            con.execute(
                "INSERT INTO visits(day, ts, visitor_id, session_id, path, referrer, device) "
                "VALUES(?,?,?,?,?,?,?);",
                (day, now, visitor_id, session_id, path, ref_host, dev)
            )
            con.commit()
        finally:
            con.close()
    except Exception as exc:
        log.warning(f"analytics.track_failed error={exc!r}")

@app.before_request
def _before_request():
    track_visit()

# -----------------------------------------------------------------------------
# Leaderboard data: Replace the two fetchers below with your real sources.
# To keep this file self-contained, we simulate a structure that the frontend expects.
# -----------------------------------------------------------------------------
def _demo_wager_data():
    """Simulated data structure with full names (logged) and masked names (served)."""
    # In your live app, pull real data here and map into the same shape.
    sample = [
        {"username": "swizzle", "wager": 228857.91},
        {"username": "liquid",  "wager": 38763.90},
        {"username": "butter",  "wager": 22008.13},
        {"username": "suave",   "wager": 21158.67},
        {"username": "shadow",  "wager": 15035.61},
        {"username": "geckoid", "wager": 12289.89},
        {"username": "wexford", "wager": 10424.40},
        {"username": "badger",  "wager":  7298.84},
        {"username": "ekko",    "wager":  3019.25},
        {"username": "tenant",  "wager":  2957.38},
    ]
    return sample

def refresh_wager_cache():
    """Refreshes leaderboard cache every REFRESH_SECONDS. Logs full names to console."""
    while True:
        try:
            data = _demo_wager_data()  # TODO: replace w/ real pull

            # Sort descending by numeric wager
            data.sort(key=lambda r: float(r["wager"]), reverse=True)

            # Log full names to console (uncensored)
            top3 = [d["username"] for d in data[:3]]
            log.info(f"leaderboard.top3 full={top3}")

            # Prepare podium (top 3 shown)
            podium = [{"username": mask_username(d["username"]),
                       "wager": f"${float(d['wager']):,.2f}"} for d in data[:3]]

            # Prepare others (ranks 4..10)
            others = []
            for idx, d in enumerate(data[3:10], start=4):
                others.append({
                    "rank": idx,
                    "username": mask_username(d["username"]),
                    "wager": f"${float(d['wager']):,.2f}"
                })

            # Update cache
            state["data"] = {
                "podium": podium,
                "others": others,
                "updated_at": int(time.time())
            }

            # Save podium snapshot for churn stats
            try:
                con = db_conn()
                con.execute(
                    "INSERT INTO podium_snapshots(ts, first, second, third) VALUES(?,?,?,?);",
                    (int(time.time()),
                     (data[0]["username"] if len(data) > 0 else None),
                     (data[1]["username"] if len(data) > 1 else None),
                     (data[2]["username"] if len(data) > 2 else None))
                )
                con.commit()
                con.close()
            except Exception as exc:
                log.warning(f"podium.snapshot_failed error={exc!r}")

            # Health
            state["health"]["shuffle_ok"] = True
            state["health"]["cache_ok"] = True
            state["health"]["updated_at"] = int(time.time())

        except Exception as exc:
            log.error(f"leaderboard.refresh_failed err={exc!r}")
            state["health"]["cache_ok"] = False

        time.sleep(REFRESH_SECONDS)

# -----------------------------------------------------------------------------
# Kick stream status
# -----------------------------------------------------------------------------
def _kick_get_token() -> str | None:
    if not (KICK_CLIENT_ID and KICK_CLIENT_SECRET):
        return None
    now = int(time.time())
    if state["kick_token"]["access_token"] and now < state["kick_token"]["expires_at"] - 60:
        return state["kick_token"]["access_token"]
    try:
        r = requests.post(
            "https://id.kick.com/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": KICK_CLIENT_ID,
                "client_secret": KICK_CLIENT_SECRET,
                "scope": "public"
            },
            timeout=10
        )
        if r.status_code == 200:
            tok = r.json()
            state["kick_token"]["access_token"] = tok.get("access_token")
            state["kick_token"]["expires_at"] = int(time.time()) + int(tok.get("expires_in", 3600))
            return state["kick_token"]["access_token"]
    except Exception as exc:
        log.warning(f"kick.token_failed err={exc!r}")
    return None

def _kick_fetch_status() -> dict:
    """Try official API with bearer; if blocked, fall back to page scrape."""
    headers = {"Accept": "application/json"}
    token = _kick_get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Official-ish endpoints may vary; try two patterns:
    for url in [
        f"https://kick.com/api/v2/channels/{KICK_CHANNEL}/livestream",
        f"https://kick.com/api/v1/channels/{KICK_CHANNEL}/livestream",
    ]:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                j = r.json()
                live = bool(j.get("livestream", j).get("is_live", j.get("is_live", False)))
                viewers = j.get("livestream", j).get("viewer_count", j.get("viewer_count"))
                return {"live": live, "viewers": viewers, "source": "kick"}
            elif r.status_code == 403:
                log.warning(f"kick.fetch url='{url}' status=403 note='blocked'")
            else:
                log.warning(f"kick.fetch url='{url}' status={r.status_code}")
        except Exception as exc:
            log.warning(f"kick.fetch_failed url='{url}' err={exc!r}")

    # Fallback: basic HTML scrape (very conservative)
    try:
        url = f"https://kick.com/{KICK_CHANNEL}"
        r = requests.get(url, timeout=10)
        live = ("isLive" in r.text) or ("Live Now" in r.text)
        # viewer count not reliably parsable in static HTML -> None
        return {"live": live, "viewers": None, "source": "fallback"}
    except Exception as exc:
        log.warning(f"kick.fallback_failed err={exc!r}")
        return {"live": False, "viewers": None, "source": "unknown"}

def refresh_stream_cache():
    while True:
        try:
            st = _kick_fetch_status()
            state["stream"] = {
                **st,
                "updated_at": int(time.time())
            }
            # Log stream status history for stats timeline
            try:
                con = db_conn()
                con.execute(
                    "INSERT INTO stream_log(ts, live, viewers) VALUES(?,?,?);",
                    (int(time.time()), 1 if st.get("live") else 0, st.get("viewers"))
                )
                con.commit()
                con.close()
            except Exception as exc:
                log.warning(f"stream.log_failed error={exc!r}")

            state["health"]["kick_ok"] = True
            state["health"]["updated_at"] = int(time.time())
            log.info(f"stream.status live={st.get('live')} viewers={st.get('viewers')} source={st.get('source')}")
        except Exception as exc:
            state["health"]["kick_ok"] = False
            log.error(f"stream.refresh_failed err={exc!r}")
        time.sleep(REFRESH_SECONDS)

# -----------------------------------------------------------------------------
# JSON APIs consumed by the frontend
# -----------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/data")
def api_data():
    return jsonify(state["data"])

@app.route("/config")
def api_config():
    return jsonify({"end_time": RACE_END_EPOCH})

@app.route("/stream")
def api_stream():
    return jsonify(state["stream"])

@app.route("/stats")
def stats_page():
    # No link from home; you can share /stats directly.
    return render_template("stats.html")

@app.route("/stats-data")
def stats_data():
    """Aggregated, anonymized metrics for stats page."""
    now = int(time.time())
    day_today = datetime.utcnow().date()
    day_30_ago = day_today - timedelta(days=30)
    day_48h_ago_ts = now - 48*3600

    con = db_conn()
    try:
        # KPIs
        total_visits = con.execute("SELECT COUNT(*) c FROM visits;").fetchone()["c"]
        unique_30d = con.execute(
            "SELECT COUNT(DISTINCT visitor_id) c FROM visits WHERE day >= ?;",
            (day_30_ago.strftime("%Y-%m-%d"),)
        ).fetchone()["c"]

        online_5m = con.execute(
            "SELECT COUNT(DISTINCT session_id) c FROM visits WHERE ts >= ?;",
            (now - 300,)
        ).fetchone()["c"]

        # Avg session length (very approximate): per session_id today's first/last
        rows = con.execute(
            "SELECT session_id, MIN(ts) mi, MAX(ts) ma FROM visits WHERE day=? GROUP BY session_id;",
            (day_today.strftime("%Y-%m-%d"),)
        ).fetchall()
        if rows:
            avg_session = sum((r["ma"] - r["mi"]) for r in rows) / len(rows)
        else:
            avg_session = 0

        # Visits per day (last 30)
        visits_series = con.execute(
            "SELECT day, COUNT(*) c FROM visits WHERE day >= ? GROUP BY day ORDER BY day ASC;",
            (day_30_ago.strftime("%Y-%m-%d"),)
        ).fetchall()
        visits_series = [{"day": r["day"], "count": r["c"]} for r in visits_series]

        # Top referrers (last 30)
        ref_rows = con.execute(
            "SELECT referrer, COUNT(*) c FROM visits WHERE day >= ? AND referrer IS NOT NULL "
            "AND referrer <> '' GROUP BY referrer ORDER BY c DESC LIMIT 5;",
            (day_30_ago.strftime("%Y-%m-%d"),)
        ).fetchall()
        top_referrers = [{"referrer": r["referrer"], "count": r["c"]} for r in ref_rows]

        # Device breakdown (last 30)
        dev_rows = con.execute(
            "SELECT device, COUNT(*) c FROM visits WHERE day >= ? GROUP BY device;",
            (day_30_ago.strftime("%Y-%m-%d"),)
        ).fetchall()
        devices = {r["device"]: r["c"] for r in dev_rows}

        # Stream timeline (48h)
        stream_rows = con.execute(
            "SELECT ts, live, viewers FROM stream_log WHERE ts >= ? ORDER BY ts ASC;",
            (day_48h_ago_ts,)
        ).fetchall()
        stream_timeline = [{"ts": r["ts"], "live": bool(r["live"]), "viewers": r["viewers"]} for r in stream_rows]

        # Podium churn (24h) + biggest climb
        podium_rows = con.execute(
            "SELECT ts, first, second, third FROM podium_snapshots WHERE ts >= ? ORDER BY ts ASC;",
            (now - 24*3600,)
        ).fetchall()
        churn = 0
        last = None
        for r in podium_rows:
            cur = (r["first"], r["second"], r["third"])
            if last and cur != last:
                churn += sum(1 for a, b in zip(cur, last) if a != b)
            last = cur

        # For biggest climb we’d need position history; we’ll report churn only (safe & simple).
        biggest_climb = None

        # Health
        health = state["health"]

        payload = {
            "kpi": {
                "total_visits": total_visits,
                "unique_30d": unique_30d,
                "online_now": online_5m,
                "avg_session_seconds": int(avg_session),
                "updates_today": sum(1 for r in stream_rows if True),  # placeholder proxy for activity
                "api_health": {
                    "kick_ok": bool(health["kick_ok"]),
                    "shuffle_ok": bool(health["shuffle_ok"]),
                    "cache_ok": bool(health["cache_ok"]),
                    "updated_at": health["updated_at"],
                }
            },
            "series": {
                "visits_per_day": visits_series,
                "top_referrers": top_referrers,
                "devices": devices,
                "stream_timeline": stream_timeline,
            },
            "leaderboard": {
                "podium_churn_24h": churn,
                "biggest_climb": biggest_climb
            }
        }
        return jsonify(payload)
    finally:
        con.close()

# -----------------------------------------------------------------------------
# 404
# -----------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

# -----------------------------------------------------------------------------
# Background threads
# -----------------------------------------------------------------------------
def _boot_threads():
    t1 = threading.Thread(target=refresh_wager_cache, name="wager-cache", daemon=True)
    t2 = threading.Thread(target=refresh_stream_cache, name="stream-cache", daemon=True)
    t1.start()
    t2.start()

_boot_threads()

# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # Dev server
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
