from __future__ import annotations

import json
import os
import re
import threading
import time
import logging
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Tuple, Optional

import requests
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

# ----------------------- App & CORS -----------------------
app = Flask(__name__)
CORS(app)

# ----------------------- Config --------------------------
API_KEY = os.getenv("API_KEY", "f45f746d-b021-494d-b9b6-b47628ee5cc9")

# Shuffle time window (sanitized each fetch)
START_TIME = int(os.getenv("START_TIME", "1755662460"))
END_TIME   = int(os.getenv("END_TIME",   "1756871940"))

REFRESH_SECONDS = int(os.getenv("REFRESH_SECONDS", "60"))
PORT = int(os.getenv("PORT", "8080"))

# Kick OAuth credentials (use ENV in production)
KICK_CLIENT_ID = os.getenv("KICK_CLIENT_ID", "01K39PNSMPVX2PS4EEJ2K69EVF")
KICK_CLIENT_SECRET = os.getenv(
    "KICK_CLIENT_SECRET",
    "47970da4c8790427e09eaebd1b7c8d522ef233c54bbd896514c7f562c66ca74e",
)
KICK_CHANNEL_SLUG = os.getenv("KICK_CHANNEL_SLUG", "redhunllef")

# Official API base
_KICK_API_BASE = "https://api.kick.com/public/v1"
# OAuth server
_KICK_OAUTH_TOKEN = "https://id.kick.com/oauth/token"

URL_RANGE = "https://affiliate.shuffle.com/stats/{API_KEY}?startTime={start}&endTime={end}"
URL_LIFE  = "https://affiliate.shuffle.com/stats/{API_KEY}"

# ----------------------- Logging -------------------------
os.makedirs("logs", exist_ok=True)

LOGGER = logging.getLogger("wager")
LOGGER.setLevel(logging.DEBUG)  # keep DEBUG to see rank logs
fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")

sh = logging.StreamHandler()
sh.setLevel(logging.DEBUG)
sh.setFormatter(fmt)
LOGGER.addHandler(sh)

fh = RotatingFileHandler("logs/audit.log", maxBytes=2_000_000, backupCount=5)
fh.setLevel(logging.DEBUG)
fh.setFormatter(fmt)
LOGGER.addHandler(fh)

def log(level: str, msg: str) -> None:
    getattr(LOGGER, level.lower())(msg)

log("info", "event=server.boot msg='starting backend'")

# ----------------------- Caches --------------------------
_cache_lock = threading.Lock()
_data_cache: Dict[str, Any] = {"podium": [], "others": []}

# Stream status cache (ttl 60s when API OK, 120s on fallback/error)
_stream_lock = threading.Lock()
_stream_cache: Dict[str, Any] = {"live": False, "title": None, "viewers": None, "updated": 0, "source": "unknown"}
_STREAM_TTL_OK = 60
_STREAM_TTL_ERROR = 120

# Kick app token cache
_token_lock = threading.Lock()
_kick_token: Dict[str, Any] = {"access_token": None, "expires_at": 0}

# ----------------------- Helpers ------------------------
def censor_username(username: str) -> str:
    """Public rule: first two characters + six asterisks."""
    if not username:
        return "******"
    return username[:2] + "*" * 6

def _sanitize_window() -> Tuple[int, int, str]:
    """Clamp window to now; fallback to last 14d if invalid."""
    now = int(time.time())
    start = START_TIME
    end = END_TIME
    reason = "configured"

    if end > now:
        end = now
        reason = "end_clamped_to_now"

    if start >= end:
        end = now
        start = now - 14 * 24 * 3600
        reason = "fallback_last_14d"

    return start, end, reason

# ---------------- Shuffle fetch ----------------
def _fetch_from_shuffle() -> List[dict]:
    headers = {"User-Agent": "Shuffle-WagerRace/Final"}
    start, end, why = _sanitize_window()
    url_range = URL_RANGE.format(API_KEY=API_KEY, start=start, end=end)
    url_life = URL_LIFE.format(API_KEY=API_KEY)

    try:
        t0 = time.perf_counter()
        log("info", f"event=fetch.range start={start} end={end} reason={why} url='{url_range}'")
        r = requests.get(url_range, timeout=20, headers=headers)

        if r.status_code == 400:
            log("warning", f"event=fetch.range_http_400 retry=lifetime url='{url_life}'")
            r2 = requests.get(url_life, timeout=20, headers=headers)
            r2.raise_for_status()
            dt = (time.perf_counter() - t0) * 1000
            log("info", f"event=fetch.done source=lifetime status={r2.status_code} duration_ms={dt:.1f}")
            data = r2.json()
            if not isinstance(data, list):
                raise ValueError("unexpected API format (lifetime)")
            return data

        r.raise_for_status()
        dt = (time.perf_counter() - t0) * 1000
        log("info", f"event=fetch.done source=window status={r.status_code} duration_ms={dt:.1f}")
        data = r.json()
        if not isinstance(data, list):
            raise ValueError("unexpected API format (window)")
        return data

    except requests.RequestException as exc:
        log("warning", f"event=fetch.window_failed err='{exc}' retry=lifetime url='{url_life}'")
        r3 = requests.get(url_life, timeout=20, headers=headers)
        r3.raise_for_status()
        data = r3.json()
        if not isinstance(data, list):
            raise ValueError("unexpected API format (lifetime_after_fail)")
        return data

def _process_entries(entries: List[dict]) -> Dict[str, Any]:
    filtered = [e for e in entries if e.get("campaignCode") == "Red"]

    def _w(e: dict) -> float:
        try:
            return float(e.get("wagerAmount", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    sorted_entries = sorted(filtered, key=_w, reverse=True)

    podium, others = [], []
    top10_debug = []

    for i, entry in enumerate(sorted_entries[:10], start=1):
        full = entry.get("username", "Unknown")
        try:
            amt = float(entry.get("wagerAmount", 0) or 0)
        except (TypeError, ValueError) as exc:
            log("error", f"event=wager.parse row={i} user_full='{full}' raw='{entry.get('wagerAmount')}' err='{exc}'")
            amt = 0.0

        wager_str = f"${amt:,.2f}"

        # UNCENSORED admin log per rank
        log("debug", f"event=rank row={i} username_full='{full}' wager='{wager_str}'")
        top10_debug.append(f"{i}:{full}({wager_str})")

        public = {"username": censor_username(full), "wager": wager_str}
        if i <= 3:
            podium.append(public)
        else:
            others.append({"rank": i, **public})

    if top10_debug:
        log("info", "event=top10.summary " + " ".join(top10_debug))

    return {"podium": podium, "others": others}

def _refresh_cache() -> None:
    t0 = time.perf_counter()
    try:
        processed = _process_entries(_fetch_from_shuffle())
        with _cache_lock:
            _data_cache.update(processed)

        # snapshot (best-effort)
        try:
            with open("logs/latest_cache.json", "w", encoding="utf-8") as f:
                json.dump(processed, f, indent=2)
        except Exception as ex:
            log("warning", f"event=snapshot.save_failed err='{ex}'")

        log("info", f"event=cache.update podium={len(processed['podium'])} others={len(processed['others'])} ms={(time.perf_counter()-t0)*1000:.1f}")
    except Exception as exc:
        log("error", f"event=cache.update_failed err='{exc}'")

def _schedule_refresh() -> None:
    _refresh_cache()
    threading.Timer(REFRESH_SECONDS, _schedule_refresh).start()

# Kick off the background refresher once
_schedule_refresh()

# ------------------- Kick live status -------------------
# Browser-like headers for HTML fallback
_KICK_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "DNT": "1",
    "Connection": "keep-alive",
    "Referer": "https://kick.com/",
}

# HTML scrape helpers (fallback)
_NEXT_JSON_RE = re.compile(r'(?s)<script[^>]+type="application/json"[^>]*>\s*(\{.*?\})\s*</script>')
_BOOL_RE = re.compile(r'"is_live"\s*:\s*(true|false)', re.IGNORECASE)
_TITLE_RE = re.compile(r'"(session_title|stream_title)"\s*:\s*"([^"]+)"')
_VIEWERS_RE = re.compile(r'"viewer_count"\s*:\s*(\d+)', re.IGNORECASE)

def _extract_live_from_api_channel_payload(data: dict) -> Tuple[bool, Optional[str], Optional[int], str]:
    if not isinstance(data, dict):
        return (False, None, None, "kick-api")
    stream = data.get("stream") or {}
    is_live = bool(stream.get("is_live"))
    title = data.get("stream_title") or stream.get("title") or None
    viewers = stream.get("viewer_count") or None
    try:
        viewers = int(viewers) if viewers is not None else None
    except Exception:
        viewers = None
    return (is_live, title, viewers, "kick-api")

def get_kick_app_token(force_refresh: bool = False) -> Optional[str]:
    # Basic guard
    if not KICK_CLIENT_ID or not KICK_CLIENT_SECRET:
        log("warning", "event=kick.token.missing msg='client id/secret not configured'")
        return None

    now = time.time()
    with _token_lock:
        token = _kick_token.get("access_token")
        exp = float(_kick_token.get("expires_at") or 0)
        # Refresh if forced or within 30s of expiry
        if token and not force_refresh and (exp - now) > 30:
            return token

        try:
            payload = {
                "grant_type": "client_credentials",
                "client_id": KICK_CLIENT_ID,
                "client_secret": KICK_CLIENT_SECRET,
            }
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            r = requests.post(_KICK_OAUTH_TOKEN, data=payload, headers=headers, timeout=10)
            if r.status_code != 200:
                log("warning", f"event=kick.token.status status={r.status_code} body='{r.text[:200]}'")
                return None
            j = r.json()
            access = j.get("access_token")
            expires_in = int(j.get("expires_in") or 3600)
            if not access:
                log("warning", "event=kick.token.no_access_token")
                return None
            _kick_token["access_token"] = access
            # Add a small safety buffer (10s)
            _kick_token["expires_at"] = now + max(expires_in - 10, 30)
            log("info", "event=kick.token.ok msg='received app token'")
            return access
        except Exception as exc:
            log("warning", f"event=kick.token.failed err='{exc}'")
            return None

def _scrape_kick_html(channel: str) -> Dict[str, Any]:
    url_page = f"https://kick.com/{channel}"
    try:
        r = requests.get(url_page, headers=_KICK_HEADERS, timeout=10)
        if r.status_code != 200:
            log("warning", f"event=kick.html_fetch url='{url_page}' status={r.status_code}")
            return {"live": False, "title": None, "viewers": None, "source": "kick-html"}

        html = r.text or ""
        # Try structured JSON first (Next.js style); if unknown, we rely on regex fallbacks.
        try:
            m = _NEXT_JSON_RE.search(html)
            if m:
                _ = json.loads(m.group(1))  # reserved for future stable path parsing
        except Exception as ex:
            log("warning", f"event=kick.html_json_parse_failed err='{ex}'")

        is_live = False
        title = None
        viewers = None

        bm = _BOOL_RE.search(html)
        if bm:
            is_live = (bm.group(1).lower() == "true")

        tm = _TITLE_RE.search(html)
        if tm:
            title = tm.group(2).encode('utf-8', 'ignore').decode('utf-8', 'ignore')

        vm = _VIEWERS_RE.search(html)
        if vm:
            try:
                viewers = int(vm.group(1))
            except Exception:
                viewers = None

        log("info", f"event=kick.html_parse live={is_live} viewers={viewers} title_detected={'yes' if title else 'no'}")
        return {"live": is_live, "title": title, "viewers": viewers, "source": "kick-html"}
    except Exception as exc:
        log("warning", f"event=kick.html_fetch_failed url='{url_page}' err='{exc}'")
        return {"live": False, "title": None, "viewers": None, "source": "unknown"}

def _fetch_kick_status(channel: str = KICK_CHANNEL_SLUG) -> Dict[str, Any]:
    token = get_kick_app_token(force_refresh=False)
    if token:
        try:
            url = f"{_KICK_API_BASE}/channels"
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            params = [("slug", channel)]
            log("info", f"event=kick.api.fetch url='{url}' params={params}")
            r = requests.get(url, headers=headers, params=params, timeout=10)
            if r.status_code == 401:
                # Token may be expired/invalid; refresh once and retry
                log("warning", "event=kick.api.unauthorized msg='refreshing token and retrying'")
                token2 = get_kick_app_token(force_refresh=True)
                if token2:
                    headers["Authorization"] = f"Bearer {token2}"
                    r = requests.get(url, headers=headers, params=params, timeout=10)

            if r.status_code == 200:
                j = r.json()
                data = (j.get("data") or [])
                if data:
                    is_live, title, viewers, src = _extract_live_from_api_channel_payload(data[0])
                    log("info", f"event=kick.api.parse live={is_live} viewers={viewers}")
                    return {"live": is_live, "title": title, "viewers": viewers, "source": src}
                log("info", "event=kick.api.empty msg='no channel data for slug'")
                return {"live": False, "title": None, "viewers": None, "source": "kick-api"}

            log("warning", f"event=kick.api.status status={r.status_code} body='{r.text[:200]}'")
            # fall through to HTML
        except Exception as exc:
            log("warning", f"event=kick.api.failed err='{exc}'")
            # fall through to HTML

    # HTML fallback
    return _scrape_kick_html(channel)

def get_stream_status() -> Dict[str, Any]:
    now = int(time.time())
    with _stream_lock:
        ttl = _STREAM_TTL_OK if _stream_cache.get("source") == "kick-api" else _STREAM_TTL_ERROR
        if now - int(_stream_cache.get("updated", 0)) < ttl:
            return dict(_stream_cache)

    status = _fetch_kick_status(KICK_CHANNEL_SLUG)
    status["updated"] = now
    with _stream_lock:
        _stream_cache.update(status)
    log("info", f"event=stream.status live={status['live']} viewers={status.get('viewers')} source={status['source']}")
    return status

# ----------------------- HTTP --------------------------
@app.before_request
def _audit():
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0].strip()
    ua = (request.user_agent.string or "").replace("\n", " ")[:160]
    log("info", f"event=request ip={ip} path='{request.path}' ua='{ua}'")

@app.after_request
def _sec(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return resp

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/data")
def data():
    with _cache_lock:
        payload = dict(_data_cache)
    return jsonify(payload)

@app.route("/config")
def config():
    return jsonify({"start_time": START_TIME, "end_time": END_TIME, "refresh_seconds": REFRESH_SECONDS})

@app.route("/stream")
def stream():
    return jsonify(get_stream_status())

@app.errorhandler(404)
def nf(e):
    return render_template("404.html"), 404

if __name__ == "__main__":
    log("info", f"event=server.listen port={PORT}")
    app.run(host="0.0.0.0", port=PORT)
