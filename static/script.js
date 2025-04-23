// static/script.js

// Floating Stream Controls & Dragging
const streamFloating = document.getElementById('stream-floating');
const minimizeBtn    = document.getElementById('minimizeBtn');
const maximizeBtn    = document.getElementById('maximizeBtn');
const closeBtn       = document.getElementById('closeBtn');
const dragHandle     = document.querySelector('.stream-title');

let isMinimized = false, isMaximized = false;
let isDragging  = false, offsetX = 0, offsetY = 0;

// Minimize / Maximize / Close
minimizeBtn.addEventListener('click', () => {
  streamFloating.classList.toggle('minimized');
  if (isMaximized) {
    streamFloating.classList.remove('maximized');
    isMaximized = false;
  }
  isMinimized = !isMinimized;
});
maximizeBtn.addEventListener('click', () => {
  streamFloating.classList.toggle('maximized');
  if (isMinimized) {
    streamFloating.classList.remove('minimized');
    isMinimized = false;
  }
  isMaximized = !isMaximized;
});
closeBtn.addEventListener('click', () => {
  streamFloating.style.display = 'none';
});

// Drag logic on title only
dragHandle.addEventListener('mousedown', (e) => {
  isDragging = true;
  streamFloating.style.bottom = 'auto';
  streamFloating.style.right  = 'auto';
  const rect = streamFloating.getBoundingClientRect();
  offsetX = e.clientX - rect.left;
  offsetY = e.clientY - rect.top;
});
document.addEventListener('mouseup', () => {
  isDragging = false;
});
document.addEventListener('mousemove', (e) => {
  if (!isDragging) return;
  streamFloating.style.top  = `${e.clientY - offsetY}px`;
  streamFloating.style.left = `${e.clientX - offsetX}px`;
});

// Countdown + Leaderboard Fetch/Render with Masking
document.addEventListener('DOMContentLoaded', () => {
  const countdownEl = document.getElementById('countdown');
  const targetDate  = new Date('2025-05-09T23:59:00-04:00');

  function updateCountdown() {
    const diff = targetDate - new Date();
    if (diff <= 0) {
      countdownEl.textContent = 'Wager Race Ended';
      clearInterval(cntInt);
      return;
    }
    const d = Math.floor(diff / 86400000),
          h = Math.floor((diff % 86400000) / 3600000),
          m = Math.floor((diff % 3600000) / 60000),
          s = Math.floor((diff % 60000) / 1000);
    countdownEl.textContent = `Time Remaining: ${d}d ${h}h ${m}m ${s}s`;
  }
  updateCountdown();
  const cntInt = setInterval(updateCountdown, 1000);

  // Mask username: first 2 chars + 5 asterisks
  function maskUsername(name) {
    return name.slice(0,2) + '*****';
  }

  async function fetchAndRender() {
    try {
      const res  = await fetch('/data');
      const data = await res.json();

      // Podium (1–3)
      ['first','second','third'].forEach((cls, i) => {
        const seat = document.querySelector(`.podium-seat.${cls}`);
        const entry = data[`top${i+1}`];
        if (entry) {
          seat.querySelector('.user').textContent  = maskUsername(entry.username);
          seat.querySelector('.wager').textContent = entry.wager;
        }
      });

      // Others (4–12)
      const others = document.getElementById('others-list');
      others.innerHTML = '';
      Object.keys(data)
        .filter(k => k.startsWith('top'))
        .map(k => parseInt(k.replace('top','')))
        .sort((a,b) => a - b)
        .forEach(rank => {
          if (rank > 3) {
            const { username, wager } = data[`top${rank}`];
            const li = document.createElement('li');
            li.innerHTML = `
              <span class="position">${rank}</span>
              <span class="username">${maskUsername(username)}</span>
              <span class="wager">${wager}</span>
            `;
            others.appendChild(li);
          }
        });
    } catch (err) {
      console.error('Failed to fetch wager data:', err);
    }
  }

  fetchAndRender();
  setInterval(fetchAndRender, 90000);
});
