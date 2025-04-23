// static/script.js
/**
 * Manages:
 *  - Draggable livestream window controls
 *  - Live countdown
 *  - Fetching and rendering top 9 wagerers every 90s
 *  - Masking usernames to first 2 chars + *****
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

// Prize mapping for ranks 4–9
const prizeMap = {
  4: '$150.00',
  5: '$75.00',
  6: '$50.00',
  7: '$25.00',
  8: '$25.00',
  9: '$25.00'
};

// Race end time (May 9 2025 11:59 PM ET)
const targetDate = new Date('2025-05-09T23:59:00-04:00');

document.addEventListener('DOMContentLoaded', () => {
  console.log('[Init] UI ready');
  updateCountdown();
  setInterval(updateCountdown, 1000);
  fetchAndRender();
  setInterval(fetchAndRender, 90000);
  setupWindowControls();
});

/** Update the countdown display every second */
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

/** Fetch /data and render podium (1-3) and others (4-9) */
async function fetchAndRender() {
  try {
    console.log('[Fetch] GET /data');
    const res = await fetch('/data');
    const data = await res.json();
    console.log('[Fetch] Data:', data);

    // Podium seats 1–3
    ['first', 'second', 'third'].forEach((cls, i) => {
      const seat = document.querySelector(`.podium-seat.${cls}`);
      const entry = data[`top${i+1}`];
      if (entry) {
        const masked = maskUsername(entry.username);
        seat.querySelector('.user').textContent  = masked;
        seat.querySelector('.wager').textContent = entry.wager;
      }
    });

    // Others ranks 4–9
    othersList.innerHTML = '';
    Object.keys(data)
      .filter(k => /^top\d+$/.test(k))
      .map(k => parseInt(k.replace('top', ''), 10))
      .sort((a, b) => a - b)
      .forEach(rank => {
        if (rank >= 4 && rank <= 9) {
          const entry = data[`top${rank}`];
          const masked = maskUsername(entry.username);
          const prize = prizeMap[rank];
          const li = document.createElement('li');
          li.innerHTML = `
            <div class="position">${rank}</div>
            <div class="username">${masked}</div>
            <div class="wager">${entry.wager}</div>
            <div class="prize">${prize}</div>
          `;
          othersList.appendChild(li);
        }
      });

  } catch (err) {
    console.error('[Error] fetchAndRender:', err);
  }
}

/** Mask username: first 2 chars + '*****' */
function maskUsername(name) {
  return name.slice(0, 2) + '*****';
}

/** Setup minimize, maximize, close, and drag for livestream window */
function setupWindowControls() {
  minimizeBtn.addEventListener('click', e => {
    e.stopPropagation();
    isMinimized = !isMinimized;
    streamFloating.classList.toggle('minimized');
    if (isMaximized) {
      isMaximized = false;
      streamFloating.classList.remove('maximized');
    }
  });

  maximizeBtn.addEventListener('click', e => {
    e.stopPropagation();
    isMaximized = !isMaximized;
    streamFloating.classList.toggle('maximized');
    if (isMinimized) {
      isMinimized = false;
      streamFloating.classList.remove('minimized');
    }
  });

  closeBtn.addEventListener('click', e => {
    e.stopPropagation();
    streamFloating.style.display = 'none';
  });

  header.addEventListener('mousedown', e => {
    if (e.target.closest('.stream-controls')) return;
    isDragging = true;
    streamFloating.style.bottom = streamFloating.style.right = 'auto';
    const rect = streamFloating.getBoundingClientRect();
    offsetX = e.clientX - rect.left;
    offsetY = e.clientY - rect.top;
  });

  document.addEventListener('mouseup', () => {
    isDragging = false;
  });

  document.addEventListener('mousemove', e => {
    if (!isDragging) return;
    streamFloating.style.top  = `${e.clientY - offsetY}px`;
    streamFloating.style.left = `${e.clientX - offsetX}px`;
  });
}
