# -*- coding: utf-8 -*-
import os
import re
import json
import time
import sqlite3
import hashlib
import secrets
import logging
import threading
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests
from flask import (
    Flask, request, jsonify, render_template
)

APP_NAME = "redhunllefshuffle"
app = Flask(__name__, template_folder="templates", static_folder="static")

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] event=%(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(APP_NAME)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RACE_END_EPOCH = int(os.environ.get("RACE_END_EPOCH", str(int(time.time()) + 11*24*3600)))
KICK_CHANNEL = os.environ.get("KICK_CHANNEL", "redhunllef")
KICK_CLIENT_ID = os.environ.get("KICK_CLIENT_ID", "")
KICK_CLIENT_SECRET = os.environ.get("KICK_CLIENT_SECRET", "")
REFRESH_SECONDS = 60

# --- Writable analytics DB path (instance folder) ---
# If ANALYTICS_DB is defined, use it; else place DB in Flask instance dir.
os.makedirs(app.instance_path, exist_ok=True)
DEFAULT_DB = os.path.join(app.instance_path, "analytics.sqlite3")
AN_DB = os.environ.get("ANALYTICS_DB", DEFAULT_DB)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def mask_username(u: str) -> str:
    u = (u or "").strip()
    return (u[:2] + "******") if len(u) >= 2 else (u or "*") + "******"

def money(n) -> str:
    try:
        return f"${float(n):,.2f}"
    except Exception:
        return "$0.00"

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------
state = {
    "data": {"podium": [], "others": [], "updated_at": 0},
    "stream": {"live": False, "viewers": None, "source": "unknown", "updated_at": 0},
    "kick_token": {"access_token": None, "expires_at": 0},
    "health": {"kick_ok": False, "shuffle_ok": True, "cache_ok": True, "updated_at": 0}
}

# ---------------------------------------------------------------------------
# Analytics (stdlib only)
# ---------------------------------------------------------------------------
BOT_RE = re.compile(r"(bot|crawler|spider|fetch|monitor|pingdom|curl|wget)", re.I)
MOBILE_RE = re.compile(r"(iphone|android|mobile)", re.I)
TABLET_RE = re.compile(r"(ipad|tablet)", re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day TEXT NOT NULL,
  ts INTEGER NOT NULL,
  visitor_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  path TEXT NOT NULL,
  referrer TEXT,
  device TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_visits_day ON visits(day);
CREATE INDEX IF NOT EXISTS idx_visits_vid ON visits(visitor_id);
CREATE INDEX IF NOT EXISTS idx_visits_ts  ON visits(ts);

CREATE TABLE IF NOT EXISTS podium_snapshots (
  ts INTEGER NOT NULL,
  first TEXT, second TEXT, third TEXT
);
CREATE INDEX IF NOT EXISTS idx_podium_ts ON podium_snapshots(ts);

CREATE TABLE IF NOT EXISTS stream_log (
  ts INTEGER NOT NULL,
  live INTEGER NOT NULL,
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
    try:
        con = db_conn()
        con.executescript(SCHEMA)
        con.commit()
    except Exception as exc:
        log.warning(f"analytics.init_db_failed err={exc!r}")
    finally:
        try:
            con.close()
        except Exception:
            pass

def day_str(ts=None):
    return datetime.utcfromtimestamp(ts or time.time()).strftime("%Y-%m-%d")

def get_daily_salt(day: str) -> str:
    con = db_conn()
    try:
        r = con.execute("SELECT salt FROM salts WHERE day=?;", (day,)).fetchone()
        if r:
            return r["salt"]
        salt = secrets.token_hex(16)
        con.execute("INSERT INTO salts(day, salt) VALUES(?,?)", (day, salt))
        con.commit()
        return salt
    finally:
        con.close()

def device_from_ua(ua: str) -> str:
    if not ua: return "desktop"
    if TABLET_RE.search(ua): return "tablet"
    if MOBILE_RE.search(ua): return "mobile"
    return "desktop"

def is_bot(ua: str) -> bool:
    return bool(ua and BOT_RE.search(ua))

def sha(v: str) -> str:
    return hashlib.sha256(v.encode("utf-8")).hexdigest()

def track_visit():
    """Anonymous visit logging for '/' and '/stats'. Safe in readonly envs."""
    try:
        if request.method != "GET": return
        if request.args.get("no_track") == "1": return
        if request.headers.get("DNT") == "1": return

        ua = request.headers.get("User-Agent", "")
        if is_bot(ua): return

        if request.path not in ("/", "/stats"):  # keep stats lean
            return

        ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "0.0.0.0").split(",")[0].strip()
        now = int(time.time())
        day = day_str(now)
        ref = request.headers.get("Referer", "")
        try:
            ref_host = urlparse(ref).hostname or ""
        except Exception:
            ref_host = ""

        salt = get_daily_salt(day)
        visitor_id = sha(f"{ip}|{salt}")
        session_id = sha(f"{ip}|{ua}|{day}")
        dev = device_from_ua(ua)

        con = db_conn()
        try:
            con.execute(
                "INSERT INTO visits(day, ts, visitor_id, session_id, path, referrer, device) VALUES(?,?,?,?,?,?,?)",
                (day, now, visitor_id, session_id, request.path, ref_host, dev)
            )
            con.commit()
        finally:
            con.close()
    except Exception as exc:
        # Never break the request on analytics errors
        log.warning(f"analytics.track_failed err={exc!r}")

@app.before_request
def _before():
    track_visit()

# ---------------------------------------------------------------------------
# Demo leaderboard source (replace with your real data pull)
# ---------------------------------------------------------------------------
def _demo_wager_data():
    return [
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

def refresh_wager_cache():
    while True:
        try:
            data = _demo_wager_data()               # TODO: replace with live source
            data.sort(key=lambda r: float(r["wager"]), reverse=True)

            # Log full, uncensored top3 for ops
            log.info(f"leaderboard.top3 full={[d['username'] for d in data[:3]]}")

            podium = [{"username": mask_username(d["username"]), "wager": money(d["wager"])} for d in data[:3]]
            others = [{"rank": i+4, "username": mask_username(d["username"]), "wager": money(d["wager"])}
                      for i, d in enumerate(data[3:10])]

            state["data"] = {"podium": podium, "others": others, "updated_at": int(time.time())}

            # Save snapshot for churn stats
            try:
                con = db_conn()
                con.execute("INSERT INTO podium_snapshots(ts, first, second, third) VALUES(?,?,?,?)",
                            (int(time.time()),
                             data[0]["username"] if len(data)>0 else None,
                             data[1]["username"] if len(data)>1 else None,
                             data[2]["username"] if len(data)>2 else None))
                con.commit()
                con.close()
            except Exception as exc:
                log.warning(f"podium.snapshot_failed err={exc!r}")

            state["health"]["cache_ok"] = True
            state["health"]["shuffle_ok"] = True
            state["health"]["updated_at"] = int(time.time())
        except Exception as exc:
            state["health"]["cache_ok"] = False
            log.error(f"leaderboard.refresh_failed err={exc!r}")
        time.sleep(REFRESH_SECONDS)

# ---------------------------------------------------------------------------
# Kick live status (token optional; fallback to HTML sniff)
# ---------------------------------------------------------------------------
def _kick_get_token():
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
                "scope": "public",
            },
            timeout=10,
        )
        if r.status_code == 200:
            tok = r.json()
            state["kick_token"]["access_token"] = tok.get("access_token")
            state["kick_token"]["expires_at"] = int(time.time()) + int(tok.get("expires_in", 3600))
            return state["kick_token"]["access_token"]
    except Exception as exc:
        log.warning(f"kick.token_failed err={exc!r}")
    return None

def _kick_fetch_status():
    headers = {"Accept": "application/json"}
    tok = _kick_get_token()
    if tok: headers["Authorization"] = f"Bearer {tok}"

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

    # Fallback HTML
    try:
        url = f"https://kick.com/{KICK_CHANNEL}"
        r = requests.get(url, timeout=10)
        live = ("isLive" in r.text) or ("Live Now" in r.text)
        return {"live": live, "viewers": None, "source": "fallback"}
    except Exception as exc:
        log.warning(f"kick.fallback_failed err={exc!r}")
        return {"live": False, "viewers": None, "source": "unknown"}

def refresh_stream_cache():
    while True:
        try:
            st = _kick_fetch_status()
            state["stream"] = {**st, "updated_at": int(time.time())}
            # timeline for stats
            try:
                con = db_conn()
                con.execute("INSERT INTO stream_log(ts, live, viewers) VALUES(?,?,?)",
                            (int(time.time()), 1 if st.get("live") else 0, st.get("viewers")))
                con.commit()
                con.close()
            except Exception as exc:
                log.warning(f"stream.log_failed err={exc!r}")
            state["health"]["kick_ok"] = True
            state["health"]["updated_at"] = int(time.time())
            log.info(f"stream.status live={st.get('live')} viewers={st.get('viewers')} source={st.get('source')}")
        except Exception as exc:
            state["health"]["kick_ok"] = False
            log.error(f"stream.refresh_failed err={exc!r}")
        time.sleep(REFRESH_SECONDS)

# ---------------------------------------------------------------------------
# One-time background start guard
# ---------------------------------------------------------------------------
_bg_lock = threading.Lock()
_bg_started = False

def start_background_threads_once():
    global _bg_started
    with _bg_lock:
        if _bg_started:
            return
        init_db()  # ensure analytics DB exists
        threading.Thread(target=refresh_wager_cache, name="wager-cache", daemon=True).start()
        threading.Thread(target=refresh_stream_cache, name="stream-cache", daemon=True).start()
        _bg_started = True
        log.info("background.threads_started interval=%ss", REFRESH_SECONDS)

@app.before_first_request
def _warmup():
    start_background_threads_once()

# ---------------------------------------------------------------------------
# Routes / APIs
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/data")
def data():
    return jsonify(state["data"])

@app.route("/config")
def config():
    return jsonify({"end_time": RACE_END_EPOCH})

@app.route("/stream")
def stream():
    return jsonify(state["stream"])

@app.route("/stats")
def stats_page():
    # Not linked from the homepage; accessible if you know the path.
    return render_template("stats.html")

@app.route("/stats-data")
def stats_data():
    """Aggregated, anonymized metrics with safe fallbacks if DB unavailable."""
    now = int(time.time())
    day_today = datetime.utcfromtimestamp(now).date()
    day_30_ago = day_today - timedelta(days=30)
    start_48h = now - 48*3600

    # Default empty payload (in case DB cannot open)
    payload = {
        "kpi": {
            "total_visits": 0, "unique_30d": 0, "online_now": 0,
            "avg_session_seconds": 0, "updates_today": 0,
            "api_health": {
                "kick_ok": bool(state["health"]["kick_ok"]),
                "shuffle_ok": bool(state["health"]["shuffle_ok"]),
                "cache_ok": bool(state["health"]["cache_ok"]),
                "updated_at": state["health"]["updated_at"],
            }
        },
        "series": {
            "visits_per_day": [],
            "top_referrers": [],
            "devices": {},
            "stream_timeline": [],
        },
        "leaderboard": {"podium_churn_24h": 0, "biggest_climb": None}
    }

    try:
        con = db_conn()
        # KPIs
        payload["kpi"]["total_visits"] = con.execute("SELECT COUNT(*) c FROM visits;").fetchone()["c"]
        payload["kpi"]["unique_30d"] = con.execute(
            "SELECT COUNT(DISTINCT visitor_id) c FROM visits WHERE day >= ?;",
            (day_30_ago.strftime("%Y-%m-%d"),)
        ).fetchone()["c"]
        payload["kpi"]["online_now"] = con.execute(
            "SELECT COUNT(DISTINCT session_id) c FROM visits WHERE ts >= ?;",
            (now - 300,)
        ).fetchone()["c"]
        rows = con.execute(
            "SELECT session_id, MIN(ts) mi, MAX(ts) ma FROM visits WHERE day=? GROUP BY session_id;",
            (day_today.strftime("%Y-%m-%d"),)
        ).fetchall()
        payload["kpi"]["avg_session_seconds"] = int(
            sum((r["ma"] - r["mi"]) for r in rows) / len(rows)) if rows else 0

        # Series
        payload["series"]["visits_per_day"] = [
            {"day": r["day"], "count": r["c"]} for r in con.execute(
                "SELECT day, COUNT(*) c FROM visits WHERE day >= ? GROUP BY day ORDER BY day ASC;",
                (day_30_ago.strftime("%Y-%m-%d"),)
            ).fetchall()
        ]
        payload["series"]["top_referrers"] = [
            {"referrer": r["referrer"], "count": r["c"]} for r in con.execute(
                "SELECT referrer, COUNT(*) c FROM visits WHERE day >= ? AND referrer IS NOT NULL "
                "AND referrer <> '' GROUP BY referrer ORDER BY c DESC LIMIT 5;",
                (day_30_ago.strftime("%Y-%m-%d"),)
            ).fetchall()
        ]
        payload["series"]["devices"] = {r["device"]: r["c"] for r in con.execute(
            "SELECT device, COUNT(*) c FROM visits WHERE day >= ? GROUP BY device;",
            (day_30_ago.strftime("%Y-%m-%d"),)
        ).fetchall()}
        payload["series"]["stream_timeline"] = [
            {"ts": r["ts"], "live": bool(r["live"]), "viewers": r["viewers"]} for r in con.execute(
                "SELECT ts, live, viewers FROM stream_log WHERE ts >= ? ORDER BY ts ASC;",
                (start_48h,)
            ).fetchall()
        ]

        # Podium churn (24h)
        churn = 0
        last = None
        for r in con.execute(
            "SELECT ts, first, second, third FROM podium_snapshots WHERE ts >= ? ORDER BY ts ASC;",
            (now - 24*3600,)
        ):
            cur = (r["first"], r["second"], r["third"])
            if last and cur != last:
                churn += sum(1 for a, b in zip(cur, last) if a != b)
            last = cur
        payload["leaderboard"]["podium_churn_24h"] = churn

        con.close()
    except Exception as exc:
        log.warning(f"stats.data_failed err={exc!r}")

    return jsonify(payload)

# ---------------------------------------------------------------------------
# Dev entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Ensure background threads also start when running `python wager_backend.py`
    start_background_threads_once()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
