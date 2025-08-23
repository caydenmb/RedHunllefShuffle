# -*- coding: utf-8 -*-
import os, re, time, json, sqlite3, hashlib, secrets, logging, threading, requests
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from flask import Flask, request, jsonify, render_template

APP_NAME = "redhunllefshuffle"
app = Flask(__name__, template_folder="templates", static_folder="static")

logging.basicConfig(level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] event=%(message)s', datefmt='%Y-%m-%d %H:%M:%S')
log = logging.getLogger(APP_NAME)

REFRESH_SECONDS = 60
RACE_END_EPOCH = int(os.environ.get("RACE_END_EPOCH", str(int(time.time()) + 11*24*3600)))
KICK_CHANNEL = os.environ.get("KICK_CHANNEL", "redhunllef")
KICK_CLIENT_ID = os.environ.get("KICK_CLIENT_ID", "")
KICK_CLIENT_SECRET = os.environ.get("KICK_CLIENT_SECRET", "")

os.makedirs(app.instance_path, exist_ok=True)
AN_DB = os.environ.get("ANALYTICS_DB", os.path.join(app.instance_path, "analytics.sqlite3"))

def mask_username(u: str) -> str:
    u = (u or "").strip()
    return (u[:2] + "******") if len(u) >= 2 else (u or "*") + "******"

def money(n) -> str:
    try: return f"${float(n):,.2f}"
    except Exception: return "$0.00"

def day_str(ts=None):
    return datetime.utcfromtimestamp(ts or time.time()).strftime("%Y-%m-%d")

state = {
    "data": {"podium": [], "others": [], "updated_at": 0},
    "stream": {"live": False, "viewers": None, "source": "kick", "updated_at": 0},
    "kick_token": {"access_token": None, "expires_at": 0},
    "health": {"kick_ok": False, "shuffle_ok": True, "cache_ok": True, "updated_at": 0},
}

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
    finally:
        try: con.close()
        except Exception: pass

def get_daily_salt(day: str) -> str:
    con = db_conn()
    try:
        r = con.execute("SELECT salt FROM salts WHERE day=?;", (day,)).fetchone()
        if r: return r["salt"]
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
    try:
        if request.method != "GET": return
        if request.args.get("no_track") == "1": return
        if request.headers.get("DNT") == "1": return
        ua = request.headers.get("User-Agent", "")
        if is_bot(ua): return
        if request.path not in ("/", "/stats", "/stats.html"): return

        ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "0.0.0.0").split(",")[0].strip()
        now = int(time.time())
        day = day_str(now)
        ref = request.headers.get("Referer", "")
        try: ref_host = urlparse(ref).hostname or ""
        except Exception: ref_host = ""

        salt = get_daily_salt(day)
        visitor_id = sha(f"{ip}|{salt}")
        session_id = sha(f"{ip}|{ua}|{day}")
        dev = device_from_ua(ua)

        con = db_conn()
        con.execute(
            "INSERT INTO visits(day, ts, visitor_id, session_id, path, referrer, device) VALUES(?,?,?,?,?,?,?)",
            (day, now, visitor_id, session_id, request.path, ref_host, dev)
        )
        con.commit()
        con.close()
    except Exception as exc:
        log.warning(f"analytics.track_failed err={exc!r}")

@app.before_request
def _before_request():
    start_background_threads_once()
    track_visit()

def _demo_wager_data():
    return [
        {"username": "swizzle", "wager": 228857.91},
        {"username": "liquid",  "wager":  38763.90},
        {"username": "butter",  "wager":  22008.13},
        {"username": "suave",   "wager":  21158.67},
        {"username": "shadow",  "wager":  15035.61},
        {"username": "geckoid", "wager":  12289.89},
        {"username": "wexford", "wager":  10424.40},
        {"username": "badger",  "wager":   7298.84},
        {"username": "ekko",    "wager":   3019.25},
        {"username": "tenant",  "wager":   2957.38},
    ]

def refresh_wager_cache():
    while True:
        try:
            data = _demo_wager_data()
            data.sort(key=lambda r: float(r["wager"]), reverse=True)
            top3_full = [d["username"] for d in data[:3]]
            log.info(f"leaderboard.refresh ok=true top3_full={top3_full}")

            podium = [{"username": mask_username(d["username"]), "wager": money(d["wager"])} for d in data[:3]]
            others = [{"rank": i+4, "username": mask_username(d["username"]), "wager": money(d["wager"])}
                      for i, d in enumerate(data[3:10])]
            state["data"] = {"podium": podium, "others": others, "updated_at": int(time.time())}

            try:
                con = db_conn()
                con.execute("INSERT INTO podium_snapshots(ts, first, second, third) VALUES(?,?,?,?)",
                            (int(time.time()),
                             data[0]["username"] if len(data)>0 else None,
                             data[1]["username"] if len(data)>1 else None,
                             data[2]["username"] if len(data)>2 else None))
                con.commit(); con.close()
            except Exception as exc:
                log.warning(f"podium.snapshot_failed err={exc!r}")

            state["health"]["cache_ok"] = True
            state["health"]["shuffle_ok"] = True
            state["health"]["updated_at"] = int(time.time())
        except Exception as exc:
            state["health"]["cache_ok"] = False
            log.error(f"leaderboard.refresh_failed err={exc!r}")
        time.sleep(REFRESH_SECONDS)

# ---- Kick API (unchanged from your current live build) ----------------------
def _kick_get_token():
    if not (KICK_CLIENT_ID and KICK_CLIENT_SECRET):
        log.warning("kick.token_skipped reason=missing_credentials")
        return None
    now = int(time.time())
    if state["kick_token"]["access_token"] and now < state["kick_token"]["expires_at"] - 60:
        return state["kick_token"]["access_token"]
    try:
        r = requests.post(
            "https://id.kick.com/oauth2/token",
            data={"grant_type":"client_credentials","client_id":KICK_CLIENT_ID,
                  "client_secret":KICK_CLIENT_SECRET,"scope":"public"},
            headers={"User-Agent":"redhunllefshuffle/1.0"}, timeout=12)
        if r.status_code == 200:
            tok = r.json()
            state["kick_token"]["access_token"] = tok.get("access_token")
            state["kick_token"]["expires_at"]  = int(time.time()) + int(tok.get("expires_in",3600))
            log.info("kick.token_ok expires_in=%s", tok.get("expires_in"))
            return state["kick_token"]["access_token"]
        else:
            log.warning("kick.token_failed status=%s body=%s", r.status_code, r.text[:200])
    except Exception as exc:
        log.warning(f"kick.token_exception err={exc!r}")
    return None

def _kick_fetch_status():
    headers = {"Accept":"application/json","User-Agent":"redhunllefshuffle/1.0","Client-Id":KICK_CLIENT_ID or ""}
    tok = _kick_get_token()
    if tok: headers["Authorization"] = f"Bearer {tok}"
    endpoints = [
        f"https://kick.com/api/v2/channels/{KICK_CHANNEL}/livestream",
        f"https://kick.com/api/v1/channels/{KICK_CHANNEL}/livestream",
    ]
    for url in endpoints:
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code == 200:
                j = r.json()
                node = j.get("livestream", j)
                live = bool(node.get("is_live", node.get("status") == "live"))
                viewers = node.get("viewer_count") or node.get("viewers") or None
                return {"live": live, "viewers": viewers, "source": "kick"}
            elif r.status_code == 403:
                log.warning(f"kick.fetch status=403 url='{url}' note='blocked'")
            else:
                log.warning(f"kick.fetch status={r.status_code} url='{url}' body='{r.text[:160]}'")
        except Exception as exc:
            log.warning(f"kick.fetch_exception url='{url}' err={exc!r}")
    prev = state.get("stream", {}).copy()
    return {"live": prev.get("live", False), "viewers": prev.get("viewers"), "source": "kick"}

def refresh_stream_cache():
    while True:
        try:
            st = _kick_fetch_status()
            state["stream"] = {**st, "updated_at": int(time.time())}
            try:
                con = db_conn()
                con.execute("INSERT INTO stream_log(ts, live, viewers) VALUES(?,?,?)",
                            (int(time.time()), 1 if st.get("live") else 0, st.get("viewers")))
                con.commit(); con.close()
            except Exception as exc:
                log.warning(f"stream.log_failed err={exc!r}")
            state["health"]["kick_ok"] = True
            state["health"]["updated_at"] = int(time.time())
            log.info("stream.refresh ok=true live=%s viewers=%s source=%s",
                     st.get("live"), st.get("viewers"), st.get("source"))
        except Exception as exc:
            state["health"]["kick_ok"] = False
            log.error(f"stream.refresh_failed err={exc!r}")
        time.sleep(REFRESH_SECONDS)

_bg_lock = threading.Lock()
_bg_started = False
def start_background_threads_once():
    global _bg_started
    if _bg_started: return
    with _bg_lock:
        if _bg_started: return
        init_db()
        threading.Thread(target=refresh_wager_cache, name="wager-cache", daemon=True).start()
        threading.Thread(target=refresh_stream_cache, name="stream-cache", daemon=True).start()
        _bg_started = True
        log.info("background.started interval=%s", REFRESH_SECONDS)

# ------------------------------- Routes --------------------------------------
@app.route("/")
def index(): return render_template("index.html")

@app.route("/data")
def data(): return jsonify(state["data"])

@app.route("/config")
def config(): return jsonify({"end_time": RACE_END_EPOCH})

@app.route("/stream")
def stream(): return jsonify(state["stream"])

@app.route("/stats")
def stats_page(): return render_template("stats.html")

@app.route("/stats.html")
def stats_page_html(): return render_template("stats.html")

# ------------- UPDATED: monthly KPIs + live time computation -----------------
@app.route("/stats-data")
def stats_data():
    """
    Returns:
      kpi.total_visits_month       - visits this calendar month (resets on 1st)
      kpi.unique_visitors_month    - distinct anonymized visitors this month
      kpi.online_now               - active sessions in last 5 minutes
      kpi.avg_session_seconds_mon  - average session length this month (includes currently-online time up to now)
      kpi.live_seconds_48h         - total seconds live in last 48 hours
      series.visits_per_day_month  - [{day,count}] for the current month
      series.stream_timeline       - [{ts,live,viewers}] for last 48h (for the band)
      kpi.api_health               - service flags
    """
    now = int(time.time())
    # Month start (UTC)
    utc = timezone.utc
    today = datetime.now(utc).date()
    month_start_dt = today.replace(day=1)
    month_start_ts = int(datetime(month_start_dt.year, month_start_dt.month, 1, tzinfo=utc).timestamp())
    month_start_str = month_start_dt.strftime("%Y-%m-%d")
    start_48h = now - 48*3600

    payload = {
        "kpi": {
            "total_visits_month": 0,
            "unique_visitors_month": 0,
            "online_now": 0,
            "avg_session_seconds_mon": 0,
            "live_seconds_48h": 0,
            "api_health": {
                "kick_ok": bool(state["health"]["kick_ok"]),
                "shuffle_ok": bool(state["health"]["shuffle_ok"]),
                "cache_ok": bool(state["health"]["cache_ok"]),
                "updated_at": state["health"]["updated_at"],
            }
        },
        "series": {
            "visits_per_day_month": [],
            "stream_timeline": []
        }
    }

    try:
        con = db_conn()

        # Total visits (this month)
        payload["kpi"]["total_visits_month"] = con.execute(
            "SELECT COUNT(*) c FROM visits WHERE day >= ?;", (month_start_str,)
        ).fetchone()["c"]

        # Unique visitors (this month)
        payload["kpi"]["unique_visitors_month"] = con.execute(
            "SELECT COUNT(DISTINCT visitor_id) c FROM visits WHERE ts >= ?;", (month_start_ts,)
        ).fetchone()["c"]

        # Online now (5 minutes sliding window)
        payload["kpi"]["online_now"] = con.execute(
            "SELECT COUNT(DISTINCT session_id) c FROM visits WHERE ts >= ?;", (now - 300,)
        ).fetchone()["c"]

        # Avg session (this month), counting ongoing sessions up to NOW
        rows = con.execute(
            "SELECT session_id, MIN(ts) mi, MAX(ts) ma FROM visits WHERE ts >= ? GROUP BY session_id;",
            (month_start_ts,)
        ).fetchall()
        if rows:
            total = 0
            for r in rows:
                mi = int(r["mi"]); ma = int(r["ma"])
                # If a session is still ongoing, count it up to now.
                total += max(ma, now) - mi
            payload["kpi"]["avg_session_seconds_mon"] = int(total / len(rows))
        else:
            payload["kpi"]["avg_session_seconds_mon"] = 0

        # Visits per day (this month)
        payload["series"]["visits_per_day_month"] = [
            {"day": r["day"], "count": r["c"]} for r in con.execute(
                "SELECT day, COUNT(*) c FROM visits WHERE day >= ? GROUP BY day ORDER BY day ASC;",
                (month_start_str,)
            ).fetchall()
        ]

        # Stream timeline + total live seconds (48h)
        timeline = [
            {"ts": r["ts"], "live": bool(r["live"]), "viewers": r["viewers"]} for r in con.execute(
                "SELECT ts, live, viewers FROM stream_log WHERE ts >= ? ORDER BY ts ASC;",
                (start_48h,)
            ).fetchall()
        ]
        payload["series"]["stream_timeline"] = timeline

        # Sum live seconds by reconstructing segments
        last_ts = start_48h
        last_live = 0
        live_secs = 0
        for p in timeline:
            ts = int(p["ts"])
            if last_live:
                live_secs += max(0, ts - last_ts)
            last_live = 1 if p["live"] else 0
            last_ts = ts
        # Tail to now
        if last_live:
            live_secs += max(0, now - last_ts)
        payload["kpi"]["live_seconds_48h"] = live_secs

        con.close()
    except Exception as exc:
        log.warning(f"stats.data_failed err={exc!r}")

    return jsonify(payload)

# ---------------------- Dev entrypoint ---------------------------------------
if __name__ == "__main__":
    start_background_threads_once()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
