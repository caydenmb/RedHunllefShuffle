// static/script.js

// Floating Stream Controls
const streamFloating = document.getElementById('stream-floating');
const minimizeBtn = document.getElementById('minimizeBtn');
const maximizeBtn = document.getElementById('maximizeBtn');
const closeBtn = document.getElementById('closeBtn');

let isMinimized = false;
let isMaximized = false;

minimizeBtn.addEventListener('click', () => {
  if (!isMinimized) {
    streamFloating.classList.add('minimized');
    isMinimized = true;
    if (isMaximized) {
      streamFloating.classList.remove('maximized');
      isMaximized = false;
    }
  } else {
    streamFloating.classList.remove('minimized');
    isMinimized = false;
  }
});

maximizeBtn.addEventListener('click', () => {
  if (!isMaximized) {
    streamFloating.classList.add('maximized');
    isMaximized = true;
    if (isMinimized) {
      streamFloating.classList.remove('minimized');
      isMinimized = false;
    }
  } else {
    streamFloating.classList.remove('maximized');
    isMaximized = false;
  }
});

closeBtn.addEventListener('click', () => {
  streamFloating.style.display = 'none';
});

// Countdown + Leaderboard Fetch
document.addEventListener('DOMContentLoaded', () => {
  const countdownEl = document.getElementById('countdown');
  const targetDate = new Date('2025-05-09T23:59:00-04:00'); // May 9 2025, 11:59 PM ET

  function updateCountdown() {
    const now = new Date();
    const diff = targetDate - now;
    if (diff <= 0) {
      countdownEl.textContent = 'Wager Race Ended';
      clearInterval(countdownInterval);
      return;
    }
    const days = Math.floor(diff / 86400000);
    const hours = Math.floor((diff % 86400000) / 3600000);
    const minutes = Math.floor((diff % 3600000) / 60000);
    const seconds = Math.floor((diff % 60000) / 1000);
    countdownEl.textContent = `Time Remaining: ${days}d ${hours}h ${minutes}m ${seconds}s`;
  }
  updateCountdown();
  const countdownInterval = setInterval(updateCountdown, 1000);

  async function fetchAndRender() {
    try {
      const res = await fetch('/data');
      const data = await res.json();

      // Podium (1–3)
      ['first','second','third'].forEach((cls, i) => {
        const seat = document.querySelector(`.podium-seat.${cls}`);
        const entry = data[`top${i+1}`];
        if (entry) {
          seat.querySelector('.user').textContent = entry.username;
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
              <span class="username">${username}</span>
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
  setInterval(fetchAndRender, 90000); // every 1.5 minutes
});
