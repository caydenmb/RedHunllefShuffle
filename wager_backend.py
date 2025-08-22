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

# These may be future timestamps; we sanitize on each fetch.
START_TIME = int(os.getenv("START_TIME", "1755662460"))
END_TIME   = int(os.getenv("END_TIME",   "1756871940"))

REFRESH_SECONDS = int(os.getenv("REFRESH_SECONDS", "60"))
PORT = int(os.getenv("PORT", "8080"))

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

# Stream status cache
_stream_lock = threading.Lock()
_stream_cache: Dict[str, Any] = {"live": False, "title": None, "viewers": None, "updated": 0, "source": "unknown"}
_STREAM_TTL = 25  # seconds
_STREAM_ERROR_TTL = 45  # be gentler on failures

# ----------------------- Helpers ------------------------
def censor_username(username: str) -> str:
    """Public rule: first two characters + six asterisks."""
    if not username:
        return "******"
    return username[:2] + "*" * 6

def _sanitize_window() -> Tuple[int, int, str]:
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
# Stronger, browser-like headers
_KICK_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
        "Gecko/20100101 Firefox/124.0"
    ),
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "DNT": "1",
    "Connection": "keep-alive",
    "Referer": "https://kick.com/",
}

_NEXT_JSON_RE = re.compile(
    r'(?s)<script[^>]+type="application/json"[^>]*>\s*(\{.*?\})\s*</script>'
)
_BOOL_RE = re.compile(r'"is_live"\s*:\s*(true|false)', re.IGNORECASE)
_TITLE_RE = re.compile(r'"session_title"\s*:\s*"([^"]+)"')
_VIEWERS_RE = re.compile(r'"viewer_count"\s*:\s*(\d+)', re.IGNORECASE)

def _extract_live_triplet(data: dict) -> Tuple[bool, Optional[str], Optional[int], str]:
    # 0) If payload itself looks like a livestream object
    if isinstance(data, dict) and (
        "is_live" in data and ("session_title" in data or "viewer_count" in data or "slug" in data)
    ):
        return (
            bool(data.get("is_live")),
            data.get("session_title") or data.get("slug") or None,
            data.get("viewer_count") or data.get("viewers") or None,
            "livestream_root",
        )

    # 1) livestream inside channel payloads
    ls = data.get("livestream") if isinstance(data, dict) else None
    if isinstance(ls, dict):
        return (
            bool(ls.get("is_live")),
            ls.get("session_title") or ls.get("slug") or None,
            ls.get("viewer_count") or ls.get("viewers") or None,
            "livestream",
        )

    # 2) recent_livestream fallback
    rls = data.get("recent_livestream") if isinstance(data, dict) else None
    if isinstance(rls, dict):
        return (
            bool(rls.get("is_live")),
            rls.get("session_title") or rls.get("slug") or None,
            rls.get("viewer_count") or rls.get("viewers") or None,
            "recent_livestream",
        )

    # 3) root-level fallback
    if isinstance(data, dict) and "is_live" in data:
        return (
            bool(data.get("is_live")),
            data.get("session_title") or None,
            data.get("viewer_count") or None,
            "root",
        )

    return (False, None, None, "unknown")

def _scrape_kick_html(channel: str) -> Dict[str, Any]:
    url_page = f"https://kick.com/{channel}"
    try:
        r = requests.get(url_page, headers=_KICK_HEADERS, timeout=10)
        if r.status_code != 200:
            log("warning", f"event=kick.html_fetch url='{url_page}' status={r.status_code}")
            return {"live": False, "title": None, "viewers": None, "source": "kick-html"}

        html = r.text or ""
        # Try to find an application/json script first (Next.js embeds)
        m = _NEXT_JSON_RE.search(html)
        if m:
            try:
                payload = json.loads(m.group(1))
                # Best-effort walk to find livestream flags if present
                # Because structures can change, we also fall back to regex below.
                # If you have a stable path, plug it here.
                # Fallback to regex parse if we can't confidently locate fields.
            except Exception as ex:
                log("warning", f"event=kick.html_json_parse_failed err='{ex}'")

        # Regex fallback for robustness across template changes
        is_live = False
        title = None
        viewers = None

        bm = _BOOL_RE.search(html)
        if bm:
            is_live = (bm.group(1).lower() == "true")

        tm = _TITLE_RE.search(html)
        if tm:
            title = tm.group(1).encode('utf-8', 'ignore').decode('utf-8', 'ignore')

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

def _fetch_kick_status(channel: str = "redhunllef") -> Dict[str, Any]:
    endpoints = [
        f"https://kick.com/api/v2/channels/{channel}/livestream",
        f"https://kick.com/api/v1/channels/{channel}/livestream",
        f"https://kick.com/api/v2/channels/{channel}",
        f"https://kick.com/api/v1/channels/{channel}",
    ]

    saw_block = False
    last_exc: Optional[Exception] = None

    for url in endpoints:
        try:
            r = requests.get(url, headers=_KICK_HEADERS, timeout=10)

            # CDN "blocked" codes that shouldn't count as live/offline answer
            if r.status_code in (401, 403, 429):
                saw_block = True
                log("warning", f"event=kick.fetch url='{url}' status={r.status_code} note='blocked'")
                continue

            # livestream endpoints can 204/404 when offline
            if r.status_code in (204, 404):
                log("info", f"event=kick.fetch url='{url}' status={r.status_code} note='offline_or_no_stream'")
                continue

            if r.status_code != 200:
                log("warning", f"event=kick.fetch url='{url}' status={r.status_code}")
                continue

            data = r.json()
            is_live, title, viewers, shape = _extract_live_triplet(data)
            log("info", f"event=kick.parse url='{url}' shape={shape} live={is_live} viewers={viewers}")
            return {"live": is_live, "title": title, "viewers": viewers, "source": "kick"}

        except Exception as exc:
            last_exc = exc
            log("warning", f"event=kick.status_try url='{url}' err='{exc}'")

    # If all JSON endpoints failed and at least one was blocked, try HTML scraping
    if saw_block:
        log("info", "event=kick.fallback_html msg='JSON endpoints blocked; scraping channel page'")
        return _scrape_kick_html(channel)

    if last_exc:
        log("warning", f"event=kick.status_failed err='{last_exc}'")

    return {"live": False, "title": None, "viewers": None, "source": "unknown"}

def get_stream_status() -> Dict[str, Any]:
    now = int(time.time())
    with _stream_lock:
        # Respect TTL (use longer TTL when last fetch was an error-based fallback)
        ttl = _STREAM_TTL
        if _stream_cache.get("source") in ("unknown", "kick-html"):
            ttl = _STREAM_ERROR_TTL
        if now - int(_stream_cache.get("updated", 0)) < ttl:
            return dict(_stream_cache)

    status = _fetch_kick_status("redhunllef")
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
