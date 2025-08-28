# -*- coding: utf-8 -*-
import os, re, time, json, sqlite3, hashlib, secrets, logging, threading, requests, sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from flask import Flask, request, jsonify, render_template

APP_NAME = "redhunllefshuffle"
app = Flask(__name__, template_folder="templates", static_folder="static")

# -------------------------- Pretty logging --------------------------

def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False

COLOR = _supports_color()

class PrettyLog:
    # ANSI
    C_RESET = "\033[0m"
    C_DIM   = "\033[2m"
    C_BOLD  = "\033[1m"
    C_RED   = "\033[31m"
    C_GRN   = "\033[32m"
    C_YEL   = "\033[33m"
    C_BLU   = "\033[34m"
    C_CYN   = "\033[36m"
    def __init__(self, logger: logging.Logger):
        self.l = logger

    def _fmt(self, icon: str, msg: str, color: str = "", bold=False):
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        if COLOR and color:
            pre = (self.C_BOLD if bold else "") + color
            return f"[{ts}] {icon} {pre}{msg}{self.C_RESET}"
        return f"[{ts}] {icon} {msg}"

    def info(self, msg: str):  self.l.info(self._fmt("ℹ️", msg))
    def ok(self, msg: str):    self.l.info(self._fmt("✅", msg, self.C_GRN))
    def warn(self, msg: str):  self.l.warning(self._fmt("⚠️", msg, self.C_YEL, True))
    def err(self, msg: str):   self.l.error(self._fmt("❌", msg, self.C_RED, True))
    def star(self, msg: str):  self.l.info(self._fmt("⭐", msg, self.C_BLU))
    def live(self, msg: str):  self.l.info(self._fmt("📺", msg, self.C_CYN))
    def dice(self, msg: str):  self.l.info(self._fmt("🎲", msg, self.C_GRN))
    def debug(self, msg: str): self.l.debug(self._fmt("🔍", msg, self.C_DIM))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = PrettyLog(logging.getLogger(APP_NAME))

# -------------------------- Config --------------------------

REFRESH_SECONDS = 60
RACE_END_EPOCH = int(os.environ.get("RACE_END_EPOCH", str(int(time.time()) + 11*24*3600)))

# Kick live status (kept as before; uses your credentials if set)
KICK_CHANNEL       = os.environ.get("KICK_CHANNEL", "redhunllef")
KICK_CLIENT_ID     = os.environ.get("KICK_CLIENT_ID", "")
KICK_CLIENT_SECRET = os.environ.get("KICK_CLIENT_SECRET", "")

# Instance DB for analytics + logs
os.makedirs(app.instance_path, exist_ok=True)
AN_DB = os.path.join(app.instance_path, "analytics.sqlite3")

# -------------------------- Helpers --------------------------

def mask_username(u: str) -> str:
    u = (u or "").strip()
    return (u[:2] + "******") if len(u) >= 2 else (u or "*") + "******"

def money(n) -> str:
    try:
        return f"${float(n):,.2f}"
    except Exception:
        return "$0.00"

def day_str(ts=None):
    return datetime.utcfromtimestamp(ts or time.time()).strftime("%Y-%m-%d")

state = {
    "data":   {"podium": [], "others": [], "updated_at": 0},
    "stream": {"live": False, "viewers": None, "source": "kick-api", "updated_at": 0},
    "kick_token": {"access_token": None, "expires_at": 0},
    "health": {"kick_ok": False, "shuffle_ok": True, "cache_ok": True, "updated_at": 0},
}

BOT_RE    = re.compile(r"(bot|crawler|spider|fetch|monitor|pingdom|curl|wget)", re.I)
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

# -------------------------- Analytics (lightweight) --------------------------

def track_visit():
    try:
        if request.method != "GET": return
        if request.args.get("no_track") == "1": return
        if request.headers.get("DNT") == "1": return
        ua = request.headers.get("User-Agent", "")
        if is_bot(ua): return
        if request.path not in ("/", "/stats", "/stats.html"): return

        ip  = (request.headers.get("X-Forwarded-For") or request.remote_addr or "0.0.0.0").split(",")[0].strip()
        now = int(time.time())
        day = day_str(now)
        ref = request.headers.get("Referer", "")
        try: ref_host = urlparse(ref).hostname or ""
        except Exception: ref_host = ""

        salt       = get_daily_salt(day)
        visitor_id = sha(f"{ip}|{salt}")
        session_id = sha(f"{ip}|{ua}|{day}")
        dev        = device_from_ua(ua)

        con = db_conn()
        con.execute(
            "INSERT INTO visits(day, ts, visitor_id, session_id, path, referrer, device) VALUES(?,?,?,?,?,?,?)",
            (day, now, visitor_id, session_id, request.path, ref_host, dev)
        )
        con.commit()
        con.close()
    except Exception as exc:
        log.warn(f"Analytics store skipped (reason: {exc!r})")

@app.before_request
def _before_request():
    start_background_threads_once()
    track_visit()

# -------------------------- Demo wager data (replace with real API if needed) --------------------------

def _demo_wager_data():
    # Full, uncensored usernames – these are what we write to the console.
    return [
        {"username": "swizzle",    "wager": 228857.91},
        {"username": "liquid",     "wager":  38763.90},
        {"username": "butter",     "wager":  22008.13},
        {"username": "suave",      "wager":  21158.67},
        {"username": "shadow",     "wager":  15035.61},
        {"username": "geckoid",    "wager":  12289.89},
        {"username": "wexford",    "wager":  10424.40},
        {"username": "badger",     "wager":   7298.84},
        {"username": "ekko",       "wager":   3019.25},
        {"username": "tenant",     "wager":   2957.38},
    ]

# -------------------------- Periodic cache refreshers --------------------------

def refresh_wager_cache():
    while True:
        try:
            data_full = _demo_wager_data()  # Full usernames
            data_full.sort(key=lambda r: float(r["wager"]), reverse=True)

            # Console: pretty summary with full names
            top_lines = []
            for i, row in enumerate(data_full[:10], start=1):
                top_lines.append(f"   {i}. {row['username']} — {money(row['wager'])} wagered")
            log.dice("Leaderboard refreshed (top 10):\n" + "\n".join(top_lines))

            # Public: masked usernames
            podium = [{"username": mask_username(d["username"]), "wager": money(d["wager"])}
                      for d in data_full[:3]]
            others = [{"rank": i+4, "username": mask_username(d["username"]), "wager": money(d["wager"])}
                      for i, d in enumerate(data_full[3:10])]

            state["data"] = {"podium": podium, "others": others, "updated_at": int(time.time())}

            # snapshot (full names) for statistics only
            try:
                con = db_conn()
                con.execute("INSERT INTO podium_snapshots(ts, first, second, third) VALUES(?,?,?,?)",
                            (int(time.time()),
                             data_full[0]["username"] if len(data_full)>0 else None,
                             data_full[1]["username"] if len(data_full)>1 else None,
                             data_full[2]["username"] if len(data_full)>2 else None))
                con.commit(); con.close()
            except Exception as exc:
                log.warn(f"Could not store podium snapshot: {exc!r}")

            state["health"]["cache_ok"]   = True
            state["health"]["shuffle_ok"] = True
            state["health"]["updated_at"] = int(time.time())

        except Exception as exc:
            state["health"]["cache_ok"] = False
            log.err(f"Leaderboard refresh failed: {exc!r}")

        time.sleep(REFRESH_SECONDS)

# -------------------------- Kick live status --------------------------

def _kick_get_token():
    if not (KICK_CLIENT_ID and KICK_CLIENT_SECRET):
        log.warn("Kick token not requested (missing client ID/secret)")
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
            headers={"User-Agent": "redhunllefshuffle/1.0"},
            timeout=12,
        )
        if r.status_code == 200:
            tok = r.json()
            state["kick_token"]["access_token"] = tok.get("access_token")
            state["kick_token"]["expires_at"]  = int(time.time()) + int(tok.get("expires_in", 3600))
            log.ok(f"Kick OAuth token acquired (expires in {tok.get('expires_in','?')}s)")
            return state["kick_token"]["access_token"]
        else:
            log.warn(f"Kick token request failed: HTTP {r.status_code}")
    except Exception as exc:
        log.warn(f"Kick token exception: {exc!r}")
    return None

def _kick_fetch_status():
    headers = {"Accept": "application/json", "User-Agent": "redhunllefshuffle/1.0", "Client-Id": KICK_CLIENT_ID or ""}
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
                j  = r.json()
                node = j.get("livestream", j)
                live    = bool(node.get("is_live", node.get("status") == "live"))
                viewers = node.get("viewer_count") or node.get("viewers") or None
                return {"live": live, "viewers": viewers, "source": "kick-api"}
            elif r.status_code == 403:
                log.warn("Kick API blocked (403). Will retry later.")
            else:
                log.warn(f"Kick API error HTTP {r.status_code}")
        except Exception as exc:
            log.warn(f"Kick API request failed: {exc!r}")

    # Return previous state if all calls failed
    prev = state.get("stream", {}).copy()
    return {"live": prev.get("live", False), "viewers": prev.get("viewers"), "source": "kick-api"}

def refresh_stream_cache():
    last_live = None
    last_view = None
    while True:
        try:
            st = _kick_fetch_status()
            state["stream"] = {**st, "updated_at": int(time.time())}

            # Friendly one-liner only when something changes or every refresh
            live_str = "LIVE" if st.get("live") else "OFFLINE"
            viewers  = st.get("viewers")
            if st.get("live"):
                msg = f"Stream status: {live_str} — {viewers if viewers is not None else 'unknown'} watching (Kick API)"
            else:
                msg = f"Stream status: {live_str} (Kick API)"
            # Only log if changed to avoid noise
            if st.get("live") != last_live or viewers != last_view:
                log.live(msg)
            last_live, last_view = st.get("live"), viewers

            # persist timeline
            try:
                con = db_conn()
                con.execute("INSERT INTO stream_log(ts, live, viewers) VALUES(?,?,?)",
                            (int(time.time()), 1 if st.get("live") else 0, st.get("viewers")))
                con.commit(); con.close()
            except Exception as exc:
                log.warn(f"Could not store stream sample: {exc!r}")

            state["health"]["kick_ok"]   = True
            state["health"]["updated_at"] = int(time.time())
        except Exception as exc:
            state["health"]["kick_ok"] = False
            log.err(f"Stream refresh failed: {exc!r}")

        time.sleep(REFRESH_SECONDS)

# -------------------------- Background orchestrator --------------------------

_bg_lock = threading.Lock()
_bg_started = False
def start_background_threads_once():
    global _bg_started
    if _bg_started: return
    with _bg_lock:
        if _bg_started: return
        init_db()
        threading.Thread(target=refresh_wager_cache,  name="wager-cache",  daemon=True).start()
        threading.Thread(target=refresh_stream_cache, name="stream-cache", daemon=True).start()
        _bg_started = True
        log.star(f"Background refreshers started (every {REFRESH_SECONDS}s)")

# -------------------------- Routes --------------------------

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
    return render_template("stats.html")

@app.route("/stats.html")
def stats_page_html():
    return render_template("stats.html")

# -------------------------- Stats API (monthly KPIs + 48h live time) --------------------------

@app.route("/stats-data")
def stats_data():
    """
    kpi.total_visits_month
    kpi.unique_visitors_month
    kpi.online_now
    kpi.avg_session_seconds_mon
    kpi.live_seconds_48h
    series.visits_per_day_month
    series.stream_timeline
    """
    now = int(time.time())
    utc = timezone.utc
    today = datetime.now(utc).date()
    month_start_dt  = today.replace(day=1)
    month_start_ts  = int(datetime(month_start_dt.year, month_start_dt.month, 1, tzinfo=utc).timestamp())
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

        payload["kpi"]["total_visits_month"] = con.execute(
            "SELECT COUNT(*) c FROM visits WHERE day >= ?;", (month_start_str,)
        ).fetchone()["c"]

        payload["kpi"]["unique_visitors_month"] = con.execute(
            "SELECT COUNT(DISTINCT visitor_id) c FROM visits WHERE ts >= ?;", (month_start_ts,)
        ).fetchone()["c"]

        payload["kpi"]["online_now"] = con.execute(
            "SELECT COUNT(DISTINCT session_id) c FROM visits WHERE ts >= ?;", (now - 300,)
        ).fetchone()["c"]

        rows = con.execute(
            "SELECT session_id, MIN(ts) mi, MAX(ts) ma FROM visits WHERE ts >= ? GROUP BY session_id;",
            (month_start_ts,)
        ).fetchall()
        if rows:
            total = 0
            for r in rows:
                mi = int(r["mi"]); ma = int(r["ma"])
                total += max(ma, now) - mi
            payload["kpi"]["avg_session_seconds_mon"] = int(total / len(rows))

        payload["series"]["visits_per_day_month"] = [
            {"day": r["day"], "count": r["c"]} for r in con.execute(
                "SELECT day, COUNT(*) c FROM visits WHERE day >= ? GROUP BY day ORDER BY day ASC;",
                (month_start_str,)
            ).fetchall()
        ]

        timeline = [
            {"ts": r["ts"], "live": bool(r["live"]), "viewers": r["viewers"]} for r in con.execute(
                "SELECT ts, live, viewers FROM stream_log WHERE ts >= ? ORDER BY ts ASC;",
                (start_48h,)
            ).fetchall()
        ]
        payload["series"]["stream_timeline"] = timeline

        last_ts = start_48h
        last_live = 0
        live_secs = 0
        for p in timeline:
            ts = int(p["ts"])
            if last_live:
                live_secs += max(0, ts - last_ts)
            last_live = 1 if p["live"] else 0
            last_ts = ts
        if last_live:
            live_secs += max(0, now - last_ts)
        payload["kpi"]["live_seconds_48h"] = live_secs

        con.close()
    except Exception as exc:
        log.warn(f"Stats query failed: {exc!r}")

    return jsonify(payload)

# -------------------------- Entrypoint --------------------------

if __name__ == "__main__":
    start_background_threads_once()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
