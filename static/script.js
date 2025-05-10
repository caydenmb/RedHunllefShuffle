// static/script.js
/**
 * Draggable livestream window, countdown, and leaderboard rendering.
 * Fetches top 10 every 75 seconds, masks usernames,
 * and emphasizes "Wagered" in green and "Prize" in grey for all positions.
 * Logs to console whenever new data is fetched and after updates.
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

// 🏆 Prize mapping for positions 4–10
const prizeMap = {
  1: '$1,500.00',
  2: '$850.00',
  3: '$600.00',
  4: '$450.00',
  5: '$200.00',
  6: '$150.00',
  7: '$100.00',
  8: '$50.00',
  9: '$50.00',
 10: '$50.00'
};

// Race end time: May 23, 2025 11:59 PM EST
const targetDate = new Date('2025-05-23T23:59:00-05:00');

document.addEventListener('DOMContentLoaded', () => {
  updateCountdown();
  setInterval(updateCountdown, 1000);
  fetchAndRender();
  setInterval(fetchAndRender, 75000);  // 75 seconds
  setupWindowControls();
});

/** ⏳ Countdown timer */
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

/** 📊 Fetch and render leaderboard */
async function fetchAndRender() {
  try {
    console.log(`[Fetch] Requesting new data at ${new Date().toLocaleTimeString()}`);
    const res = await fetch('/data');
    const data = await res.json();
    console.log('[Fetch] Data received:', data);

    // 🎖 Podium (1–3)
    ['first', 'second', 'third'].forEach((cls, i) => {
      const seat = document.querySelector(`.podium-seat.${cls}`);
      const entry = data[`top${i + 1}`];
      if (entry) {
        seat.querySelector('.user').textContent  = maskUsername(entry.username);
        seat.querySelector('.wager').textContent = entry.wager;
        seat.querySelector('.prize').textContent = prizeMap[i + 1];
      }
    });

    // 🥈 Others (4–10)
    othersList.innerHTML = '';
    for (let rank = 4; rank <= 10; rank++) {
      const entry = data[`top${rank}`];
      if (entry) {
        const li = document.createElement('li');
        li.innerHTML = `
          <div class="position">${rank}</div>
          <div class="username">${maskUsername(entry.username)}</div>
          <div class="label wagered-label">Wagered</div>
          <div class="wager">${entry.wager}</div>
          <div class="label prize-label">Prize</div>
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

/** 🔐 Obfuscate username */
function maskUsername(name) {
  return name.slice(0, 2) + '*****';
}

/** 🎥 Livestream window controls */
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
