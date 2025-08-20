console.log("[DEBUG] boot: script.js loaded");

const $ = (sel) => document.querySelector(sel);

const PRIZE_MAP = {
  1: "$1,700.00",
  2: "$900.00",
  3: "$500.00",
  4: "$300.00",
  5: "$200.00",
  6: "$150.00",
  7: "$100.00",
  8: "$75.00",
  9: "$50.00",
  10: "$0.00",
};

const STORE = { X: "stream:x", Y: "stream:y", W: "stream:w", H: "stream:h", MIN: "stream:min" };

function pad2(n) { return String(n).padStart(2, "0"); }

function startCountdown(endEpoch) {
  const elD = $("#dd"), elH = $("#hh"), elM = $("#mm"), elS = $("#ss");
  const target = Number(endEpoch) || 0;
  function tick() {
    const now = Math.floor(Date.now() / 1000);
    let diff = Math.max(0, target - now);
    const days = Math.floor(diff / 86400); diff %= 86400;
    const hours = Math.floor(diff / 3600); diff %= 3600;
    const mins = Math.floor(diff / 60);
    const secs = diff % 60;
    elD.textContent = pad2(days);
    elH.textContent = pad2(hours);
    elM.textContent = pad2(mins);
    elS.textContent = pad2(secs);
  }
  tick();
  setInterval(tick, 1000);
}

let inflight;
async function fetchJSON(url, opts = {}) {
  if (inflight) inflight.abort();
  inflight = new AbortController();
  opts.signal = inflight.signal;
  console.debug("[DEBUG] http.get url=%s", url);
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  return res.json();
}

function successText(rank) {
  if (rank === 1) return "Champion!";
  if (rank === 2) return "Runner-up!";
  if (rank === 3) return "Third place!";
  return "";
}

function makeSeat(rank, name, wager, extraClasses = "") {
  const crown = rank === 1 ? "👑" : rank === 2 ? "🥈" : rank === 3 ? "🥉" : "";
  const success = successText(rank);
  const seat = document.createElement("div");
  seat.className = `podium-seat ${extraClasses} fade-in`;
  seat.innerHTML = `
    <div class="rank-badge">${rank}</div>
    <div class="crown">${crown}</div>
    <div class="user">${name}</div>
    ${success ? `<div class="success-badge">${success}</div>` : ""}
    <div class="label">Wagered</div>
    <div class="wager">${wager}</div>
    <div class="label">Prize</div>
    <div class="prize">${PRIZE_MAP[rank] || "$0.00"}</div>
  `;
  return seat;
}

function renderLeaderboard(data) {
  const podium = $("#podium");
  const others = $("#others-list");

  podium.innerHTML = "";
  others.innerHTML = "";

  if (!data || data.error) {
    podium.innerHTML = `<p class="fade-in">Unable to load the leaderboard right now.</p>`;
    return;
  }

  const p = data.podium || [];
  if (p[1]) podium.appendChild(makeSeat(2, p[1].username, p[1].wager, "col-second"));
  if (p[0]) podium.appendChild(makeSeat(1, p[0].username, p[0].wager, "col-first"));
  if (p[2]) podium.appendChild(makeSeat(3, p[2].username, p[2].wager, "col-third"));

  const list = data.others || [];
  others.style.setProperty("--others-count", String(list.length || 1));

  list.forEach(o => {
    const li = document.createElement("li");
    li.className = "fade-in";
    li.innerHTML = `
      <div class="position">#${o.rank}</div>
      <div class="username">${o.username}</div>
      <div class="label emphasized">Wager</div>
      <div class="wager">${o.wager}</div>
      <div class="prize">${PRIZE_MAP[o.rank] || "$0.00"}</div>
    `;
    others.appendChild(li);
  });

  console.debug("[DEBUG] render done podium=%d others=%d", p.length, list.length);
}

async function bootstrap() {
  try {
    const conf = await fetchJSON("/config");
    console.debug("[DEBUG] config %o", conf);
    startCountdown(conf.end_time);
    const initial = await fetchJSON("/data");
    console.debug("[DEBUG] initial %o", initial);
    renderLeaderboard(initial);
    const cadence = Number(conf.refresh_seconds || 60) * 1000;
    setInterval(async () => {
      try {
        const fresh = await fetchJSON("/data", { cache: "no-store" });
        console.debug("[DEBUG] refresh %o", fresh);
        renderLeaderboard(fresh);
      } catch (err) {
        console.error("[ERROR] refresh failed:", err);
      }
    }, cadence);
  } catch (err) {
    console.error("[ERROR] bootstrap:", err);
  }
}

/* Mini-player logic omitted here for brevity in this snippet — keep your existing version */
function clamp(n, min, max) { return Math.max(min, Math.min(n, max)); }
function initMiniPlayer() {
  const win = $("#stream-floating");
  const handle = $("#stream-drag-handle");
  const resizer = $("#resizeHandle");
  const btnMin = $("#minimizeBtn");
  const btnMax = $("#maximizeBtn");
  const btnClose = $("#closeBtn");

  const sx = Number(localStorage.getItem(STORE.X));
  const sy = Number(localStorage.getItem(STORE.Y));
  const sw = Number(localStorage.getItem(STORE.W));
  const sh = Number(localStorage.getItem(STORE.H));
  const minimized = localStorage.getItem(STORE.MIN) === "1";

  if (sw) win.style.width = `${sw}px`;
  if (sh) win.style.height = `${sh}px`;
  if (!Number.isNaN(sx)) { win.style.left = `${sx}px`; win.style.right = "auto"; }
  if (!Number.isNaN(sy)) { win.style.top = `${sy}px`;  win.style.bottom = "auto"; }
  if (minimized) { win.classList.add("minimized"); win.setAttribute("aria-expanded", "false"); btnMin.setAttribute("aria-pressed", "true"); }

  [btnMin, btnMax, btnClose].forEach(btn => {
    btn.addEventListener("pointerdown", e => e.stopPropagation());
    btn.addEventListener("click", e => e.stopPropagation());
  });

  btnMin.addEventListener("click", () => {
    const isMin = win.classList.toggle("minimized");
    localStorage.setItem(STORE.MIN, isMin ? "1" : "0");
    win.setAttribute("aria-expanded", isMin ? "false" : "true");
    btnMin.setAttribute("aria-pressed", isMin ? "true" : "false");
    console.debug("[DEBUG] mini-player minimized=%s", isMin);
  });

  btnMax.addEventListener("click", () => window.open("https://kick.com/redhunllef", "_blank", "noopener"));
  btnClose.addEventListener("click", () => { win.style.display = "none"; console.debug("[DEBUG] mini-player closed"); });

  let dragging = false, startX=0, startY=0, startL=0, startT=0;
  handle.addEventListener("pointerdown", (e) => {
    dragging = true;
    startX = e.clientX; startY = e.clientY;
    startL = win.offsetLeft; startT = win.offsetTop;
    handle.setPointerCapture(e.pointerId);
    win.style.cursor = "grabbing";
  });
  handle.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const dx = e.clientX - startX, dy = e.clientY - startY;
    const maxX = window.innerWidth - win.offsetWidth;
    const maxY = window.innerHeight - win.offsetHeight;
    win.style.left = `${Math.max(0, Math.min(startL + dx, maxX))}px`;
    win.style.top  = `${Math.max(0, Math.min(startT + dy, maxY))}px`;
    win.style.right = "auto"; win.style.bottom = "auto";
  });
  const endDrag = (e) => {
    if (!dragging) return;
    dragging = false;
    try { handle.releasePointerCapture(e.pointerId); } catch {}
    win.style.cursor = "default";
    localStorage.setItem(STORE.X, String(win.offsetLeft));
    localStorage.setItem(STORE.Y, String(win.offsetTop));
  };
  handle.addEventListener("pointerup", endDrag);
  handle.addEventListener("pointercancel", endDrag);

  let resizing=false, startW=0, startH=0, startRX=0, startRY=0;
  resizer.addEventListener("pointerdown", (e) => {
    e.preventDefault(); e.stopPropagation();
    resizing = true;
    resizer.setPointerCapture(e.pointerId);
    startW = win.offsetWidth; startH = win.offsetHeight;
    startRX = e.clientX; startRY = e.clientY;
  });
  resizer.addEventListener("pointermove", (e) => {
    if (!resizing) return;
    const newW = Math.max(260, Math.min(startW + (e.clientX - startRX), Math.min(820, window.innerWidth)));
    const newH = Math.max(150, Math.min(startH + (e.clientY - startRY), Math.min(600, window.innerHeight)));
    win.style.width = `${newW}px`; win.style.height = `${newH}px`;
  });
  const endResize = (e) => {
    if (!resizing) return;
    resizing = false;
    try { resizer.releasePointerCapture(e.pointerId); } catch {}
    localStorage.setItem(STORE.W, String(win.offsetWidth));
    localStorage.setItem(STORE.H, String(win.offsetHeight));
  };
  resizer.addEventListener("pointerup", endResize);
  resizer.addEventListener("pointercancel", endResize);
}

function setYear() {
  const el = document.getElementById("year");
  if (el) el.textContent = new Date().getFullYear();
}

window.addEventListener("DOMContentLoaded", () => {
  setYear();
  bootstrap();
  initMiniPlayer();
});
