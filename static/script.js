(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const podiumEl = $('#podium');
  const othersEl = $('#others-list');
  const liveEl = $('#liveStatus');
  const viewerChip = $('.viewer-chip', liveEl);
  const dot = $('.dot', liveEl);
  const text = $('.text', liveEl);

  const dd = $('#dd'), hh = $('#hh'), mm = $('#mm'), ss = $('#ss');
  const yearOut = $('#year');

  const PRIZES = {
    1: '$1,700.00',
    2: '$900.00',
    3: '$500.00',
    4: '$300.00',
    5: '$200.00',
    6: '$150.00',
    7: '$100.00',
    8: '$75.00',
    9: '$50.00',
    10: '$0.00'
  };

  function fmtInt(n) {
    return (n ?? 0).toLocaleString();
  }

  function buildPodium(podium) {
    // Expected: array length 0..3, each { username, wager }
    podiumEl.innerHTML = '';

    const ranks = [
      { cls: 'col-second', label: 2, medal: '🥈' },
      { cls: 'col-first',  label: 1, medal: '🥇' },
      { cls: 'col-third',  label: 3, medal: '🥉' }
    ];

    ranks.forEach((r, idx) => {
      const entry = podium[idx] || null;
      const seat = document.createElement('article');
      seat.className = `podium-seat ${r.cls} fade-in`;

      seat.innerHTML = `
        <span class="rank-badge">${r.label}</span>
        <div class="crown">${r.medal}</div>
        <div class="user">${entry ? entry.username : '--'}</div>
        <div class="label">WAGERED</div>
        <div class="wager">${entry ? entry.wager : '$0.00'}</div>
        <div class="label">PRIZE</div>
        <div class="prize">${PRIZES[r.label]}</div>
      `;

      podiumEl.appendChild(seat);
    });
  }

  function buildOthers(others) {
    // others: [{rank, username, wager}]
    const slice = (others || []).slice(0, 7); // 4..10 -> seven cards
    othersEl.innerHTML = slice.map(o => `
      <li class="fade-in">
        <span class="position">#${o.rank}</span>
        <div class="username">${o.username}</div>
        <div class="label emphasized">WAGER</div>
        <div class="wager">${o.wager}</div>
        <div class="prize">${PRIZES[o.rank] || '$0.00'}</div>
      </li>
    `).join('');
  }

  async function fetchData() {
    try {
      const r = await fetch('/data', { cache: 'no-store' });
      if (!r.ok) throw new Error(`data status ${r.status}`);
      const j = await r.json();
      buildPodium(j.podium || []);
      buildOthers(j.others || []);
      console.info('[leaderboard] updated', j);
    } catch (e) {
      console.error('[leaderboard] failed', e);
    }
  }

  async function fetchStream() {
    try {
      const r = await fetch('/stream', { cache: 'no-store' });
      if (!r.ok) throw new Error(`stream status ${r.status}`);
      const j = await r.json();
      const live = !!j.live;
      const viewers = j.viewers ?? null;

      liveEl.classList.remove('live', 'off', 'unk');
      if (live) {
        liveEl.classList.add('live');
        text.textContent = 'LIVE NOW!';
        if (typeof viewers === 'number') {
          viewerChip.style.display = 'inline-flex';
          viewerChip.textContent = `${fmtInt(viewers)} watching`;
        } else {
          viewerChip.style.display = 'none';
        }
      } else {
        liveEl.classList.add('off');
        text.textContent = 'Offline';
        viewerChip.style.display = 'none';
      }
      console.info('[stream] status', j);
    } catch (e) {
      liveEl.classList.remove('live', 'off');
      liveEl.classList.add('unk');
      text.textContent = 'Status unavailable';
      viewerChip.style.display = 'none';
      console.warn('[stream] failed', e);
    }
  }

  async function initCountdown() {
    try {
      const r = await fetch('/config', { cache: 'no-store' });
      if (!r.ok) throw new Error(`config status ${r.status}`);
      const j = await r.json();
      const end = Number(j.end_time) || 0;

      function tick() {
        const now = Math.floor(Date.now() / 1000);
        let delta = Math.max(0, end - now);

        const d = Math.floor(delta / 86400); delta -= d * 86400;
        const h = Math.floor(delta / 3600);  delta -= h * 3600;
        const m = Math.floor(delta / 60);    delta -= m * 60;
        const s = delta;

        dd.textContent = String(d).padStart(2, '0');
        hh.textContent = String(h).padStart(2, '0');
        mm.textContent = String(m).padStart(2, '0');
        ss.textContent = String(s).padStart(2, '0');
      }

      tick();
      setInterval(tick, 1000);
    } catch (e) {
      console.warn('[countdown] failed', e);
    }
  }

  function boot() {
    if (yearOut) yearOut.textContent = new Date().getFullYear();

    fetchData();
    fetchStream();
    initCountdown();

    // refresh every 60s
    setInterval(fetchData, 60_000);
    setInterval(fetchStream, 60_000);
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
