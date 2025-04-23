// static/script.js
/**
 * Manages the draggable livestream window controls,
 * realtime countdown, and leaderboard fetching & rendering.
 * Includes detailed console logging for debugging.
 */

// UI references
const streamFloating = document.getElementById('stream-floating');
const minimizeBtn    = document.getElementById('minimizeBtn');
const maximizeBtn    = document.getElementById('maximizeBtn');
const closeBtn       = document.getElementById('closeBtn');
const header         = document.querySelector('.stream-header');
const countdownEl    = document.getElementById('countdown');
const othersList     = document.getElementById('others-list');

// State
let isMinimized = false, isMaximized = false;
let isDragging = false, offsetX = 0, offsetY = 0;

// Prize mapping for places 4–9
const prizeMap = {4:'$150.00',5:'$75.00',6:'$50.00',7:'$25.00',8:'$25.00',9:'$25.00'};

// Race end: May 9 2025 11:59PM Eastern
const targetDate = new Date('2025-05-09T23:59:00-04:00');

// Initialize UI
document.addEventListener('DOMContentLoaded', () => {
  console.log('[Init] UI starting');
  updateCountdown();
  setInterval(updateCountdown, 1000);
  fetchAndRender();
  setInterval(fetchAndRender, 90000);
  setupWindowControls();
});

/** Update the countdown text. */
function updateCountdown() {
  const diff = targetDate - new Date();
  if (diff <= 0) {
    countdownEl.textContent = 'Wager Race Ended';
    console.log('[Countdown] Race ended');
    return;
  }
  const d = Math.floor(diff/86400000),
        h = Math.floor((diff%86400000)/3600000),
        m = Math.floor((diff%3600000)/60000),
        s = Math.floor((diff%60000)/1000);
  countdownEl.textContent = `Time Remaining: ${d}d ${h}h ${m}m ${s}s`;
}

/** Fetch /data and render podium & list. */
async function fetchAndRender() {
  try {
    console.log('[Fetch] GET /data');
    const res  = await fetch('/data');
    const data = await res.json();
    console.log('[Fetch] Data:', data);

    // Top 3 podium
    ['first','second','third'].forEach((cls,i) => {
      const seat = document.querySelector(`.podium-seat.${cls}`);
      const e    = data[`top${i+1}`];
      if (e) {
        const m = maskUsername(e.username);
        console.log(`[Render] Podium ${i+1}: ${m}, ${e.wager}`);
        seat.querySelector('.user').textContent  = m;
        seat.querySelector('.wager').textContent = e.wager;
      }
    });

    // Others (4–9)
    othersList.innerHTML = '';
    Object.keys(data)
      .filter(k=>/^top\d+$/.test(k))
      .map(k=>parseInt(k.replace('top','')))
      .sort((a,b)=>a-b)
      .forEach(rank => {
        if (rank>=4 && rank<=9) {
          const e = data[`top${rank}`];
          const m = maskUsername(e.username);
          const p = prizeMap[rank];
          console.log(`[Render] Rank ${rank}: ${m}, ${e.wager}, Prize ${p}`);
          const li = document.createElement('li');
          li.innerHTML = `
            <div class="position">${rank}</div>
            <div class="username">${m}</div>
            <div class="wager">${e.wager}</div>
            <div class="prize">${p}</div>
          `;
          othersList.appendChild(li);
        }
      });
  } catch(err) {
    console.error('[Error] fetchAndRender:', err);
  }
}

/** Mask username to first 2 chars + '*****'. */
function maskUsername(name) {
  return name.slice(0,2) + '*****';
}

/** Setup minimize/maximize/close & drag. */
function setupWindowControls() {
  console.log('[Init] Window controls');
  minimizeBtn.addEventListener('click', e => {
    e.stopPropagation();
    isMinimized = !isMinimized;
    streamFloating.classList.toggle('minimized');
    console.log(`[Window] Minimized: ${isMinimized}`);
    if (isMaximized) {
      isMaximized = false;
      streamFloating.classList.remove('maximized');
    }
  });
  maximizeBtn.addEventListener('click', e => {
    e.stopPropagation();
    isMaximized = !isMaximized;
    streamFloating.classList.toggle('maximized');
    console.log(`[Window] Maximized: ${isMaximized}`);
    if (isMinimized) {
      isMinimized = false;
      streamFloating.classList.remove('minimized');
    }
  });
  closeBtn.addEventListener('click', e => {
    e.stopPropagation();
    console.log('[Window] Closed');
    streamFloating.style.display = 'none';
  });
  header.addEventListener('mousedown', e => {
    if (e.target.closest('.stream-controls')) return;
    console.log('[Drag] Start');
    isDragging = true;
    streamFloating.style.bottom = streamFloating.style.right = 'auto';
    const rect = streamFloating.getBoundingClientRect();
    offsetX = e.clientX - rect.left;
    offsetY = e.clientY - rect.top;
  });
  document.addEventListener('mouseup', () => {
    if (isDragging) console.log('[Drag] Stop');
    isDragging = false;
  });
  document.addEventListener('mousemove', e => {
    if (!isDragging) return;
    streamFloating.style.top  = `${e.clientY - offsetY}px`;
    streamFloating.style.left = `${e.clientX - offsetX}px`;
  });
}
