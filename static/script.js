// static/script.js
/**
 * Draggable livestream window, countdown, and leaderboard rendering.
 * Fetches top 9 every 75 seconds, masks usernames,
 * and emphasizes "Wagered" and "Prize" labels for positions 4–9.
 * Logs to console whenever new data is fetched and after the leaderboard updates.
 */

const streamFloating = document.getElementById('stream-floating');
const minimizeBtn    = document.getElementById('minimizeBtn');
const maximizeBtn    = document.getElementById('maximizeBtn');
const closeBtn       = document.getElementById('closeBtn');
const header         = document.querySelector('.stream-header');
const countdownEl    = document.getElementById('countdown');
const othersList     = document.getElementById('others-list');

let isMinimized = false, isMaximized = false;
let isDragging = false, offsetX = 0, offsetY = 0;

// Prize mapping for positions 4–9
const prizeMap = {
  4: '$350.00',
  5: '$200.00',
  6: '$150.00',
  7: '$100.00',
  8: '$50.00',
  9: '$50.00',
  10: '$50.00'
};

// Timer set for August 05, 2025 at 11:59 PM Eastern (EDT, UTC−4)
const targetDate = new Date('2025-08-19T23:59:00-04:00');

document.addEventListener('DOMContentLoaded', () => {
  // Initialize countdown and data-fetch loops
  updateCountdown();
  setInterval(updateCountdown, 1000);
  fetchAndRender();
  setInterval(fetchAndRender, 75000);  // use 75000, not 75_000
  setupWindowControls();
});

/** Update the countdown display. */
function updateCountdown() {
  const diff = targetDate - new Date();
  if (diff <= 0) {
    countdownEl.textContent = 'Wager Race Ended';
    return;
  }
  const d = Math.floor(diff / 86400000),
        h = Math.floor((diff % 86400000) / 3600000),
        m = Math.floor((diff % 3600000) / 60000),
        s = Math.floor((diff % 60000) / 1000);
  countdownEl.textContent = `Time Remaining: ${d}d ${h}h ${m}m ${s}s`;
}

/** Fetch /data and update the DOM (1–3 podium + 4–9 list). */
async function fetchAndRender() {
  try {
    console.log(`[Fetch] Requesting new data at ${new Date().toLocaleTimeString()}`);
    const res = await fetch('/data');
    const data = await res.json();
    console.log('[Fetch] Data received:', data);

    // Update Podium (1–3)
    ['first', 'second', 'third'].forEach((cls, i) => {
      const seat = document.querySelector(`.podium-seat.${cls}`);
      const entry = data[`top${i+1}`];
      if (entry) {
        seat.querySelector('.user').textContent  = maskUsername(entry.username);
        seat.querySelector('.wager').textContent = entry.wager;
      }
    });

    // Update Others (4–10)
    othersList.innerHTML = '';
    for (let rank = 4; rank <= 10; rank++) {
      const entry = data[`top${rank}`];
      if (entry) {
        const li = document.createElement('li');
        li.innerHTML = `
          <div class="position">${rank}</div>
          <div class="username">${maskUsername(entry.username)}</div>
          <div class="label emphasized">Wagered</div>
          <div class="wager">${entry.wager}</div>
          <div class="label emphasized">Prize</div>
          <div class="prize">${prizeMap[rank]}</div>
        `;
        othersList.appendChild(li);
      }
    }

    console.log('[Update] Leaderboard updated at', new Date().toLocaleTimeString());
  } catch (err) {
    console.error('[Error] fetchAndRender failed:', err);
  }
}

/** Mask a username to first 2 chars + '*****'. */
function maskUsername(name) {
  return name.slice(0, 2) + '*****';
}

/** Wire up minimize/maximize/close and drag behavior. */
function setupWindowControls() {
  minimizeBtn.addEventListener('click', e => {
    e.stopPropagation();
    isMinimized = !isMinimized;
    streamFloating.classList.toggle('minimized');
    console.log('[Window] Minimized:', isMinimized);
    if (isMaximized) {
      isMaximized = false;
      streamFloating.classList.remove('maximized');
    }
  });

  maximizeBtn.addEventListener('click', e => {
    e.stopPropagation();
    isMaximized = !isMaximized;
    streamFloating.classList.toggle('maximized');
    console.log('[Window] Maximized:', isMaximized);
    if (isMinimized) {
      isMinimized = false;
      streamFloating.classList.remove('minimized');
    }
  });

  closeBtn.addEventListener('click', e => {
    e.stopPropagation();
    streamFloating.style.display = 'none';
    console.log('[Window] Closed');
  });

  header.addEventListener('mousedown', e => {
    if (e.target.closest('.stream-controls')) return;
    isDragging = true;
    const rect = streamFloating.getBoundingClientRect();
    offsetX = e.clientX - rect.left;
    offsetY = e.clientY - rect.top;
    streamFloating.style.bottom = streamFloating.style.right = 'auto';
    console.log('[Drag] Start');
  });

  document.addEventListener('mouseup', () => {
    if (isDragging) console.log('[Drag] End');
    isDragging = false;
  });

  document.addEventListener('mousemove', e => {
    if (!isDragging) return;
    streamFloating.style.top  = `${e.clientY - offsetY}px`;
    streamFloating.style.left = `${e.clientX - offsetX}px`;
  });
}
