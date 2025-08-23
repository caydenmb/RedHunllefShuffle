(() => {
  const $ = (sel, root = document) => root.querySelector(sel);

  const podiumEl   = $('#podium');
  const othersEl   = $('#others-list');
  const statusEl   = $('#data-status');
  const liveEl     = $('#liveStatus');
  const viewerChip = liveEl?.querySelector('.viewer-chip');
  const text       = liveEl?.querySelector('.text');

  const dd = $('#dd'), hh = $('#hh'), mm = $('#mm'), ss = $('#ss');
  const yearOut = $('#year');

  const PRIZES = {1:'$1,700.00',2:'$900.00',3:'$500.00',4:'$300.00',5:'$200.00',6:'$150.00',7:'$100.00',8:'$75.00',9:'$50.00',10:'$0.00'};

  function moneyToNumber(s){ if(typeof s==='number') return s; const n=Number(String(s||'').replace(/[^0-9.]/g,'')); return Number.isFinite(n)?Math.max(0,n):0; }
  function formatUSD(n){ const v=Number.isFinite(n)?n:0; return v.toLocaleString('en-US',{style:'currency',currency:'USD'}); }
  function stableDesc(a,b){ const d=b.wagerNum-a.wagerNum; if(d!==0) return d; const ua=(a.username||'').toLowerCase(), ub=(b.username||'').toLowerCase(); return ua<ub?-1:ua>ub?1:0; }

  let prevTop3Key='', prevOthersKeys=[];

  function buildPodium(raw){
    const list=(raw||[]).map(e=>({username:e?.username??'--',wagerNum:moneyToNumber(e?.wager),wagerStr:formatUSD(moneyToNumber(e?.wager))}));
    list.sort(stableDesc);
    const first=list[0]||{username:'--',wagerStr:formatUSD(0),wagerNum:0};
    const second=list[1]||{username:'--',wagerStr:formatUSD(0),wagerNum:0};
    const third=list[2]||{username:'--',wagerStr:formatUSD(0),wagerNum:0};

    const seats=[
      {place:2,cls:'col-second',medal:'🥈',entry:second,aria:'Second place medal'},
      {place:1,cls:'col-first', meda:'🥇', medal:'🥇',entry:first, aria:'First place medal'},
      {place:3,cls:'col-third', medal:'🥉',entry:third, aria:'Third place medal'},
    ];

    const key=seats.map(s=>`${s.place}:${s.entry.username}|${s.entry.wagerStr}`).join(',');
    podiumEl.innerHTML='';

    seats.forEach(s=>{
      const el=document.createElement('article');
      el.className=`podium-seat ${s.cls} fade-in`;
      el.innerHTML=`
        <span class="rank-badge">${s.place}</span>
        <div class="crown" aria-label="${s.aria}">${s.medal}</div>
        <div class="card-headroom" aria-hidden="true"></div>
        <div class="user">${s.entry.username}</div>
        <div class="label">WAGERED</div>
        <div class="wager">${s.entry.wagerStr}</div>
        <div class="label">PRIZE</div>
        <div class="prize">${PRIZES[s.place]}</div>
      `;
      podiumEl.appendChild(el);
    });

    if(prevTop3Key && prevTop3Key!==key){
      podiumEl.classList.add('place-change');
      setTimeout(()=>podiumEl.classList.remove('place-change'),300);
    }
    prevTop3Key=key;
  }

  function buildOthers(raw){
    let items=(raw||[]).map(e=>({rank:typeof e?.rank==='number'?e.rank:null,username:e?.username??'--',wagerNum:moneyToNumber(e?.wager),wagerStr:formatUSD(moneyToNumber(e?.wager))}));
    if(items.every(o=>typeof o.rank==='number')) items.sort((a,b)=>a.rank-b.rank);
    else { items.sort(stableDesc); items=items.map((o,i)=>({...o,rank:4+i})); }
    const desired=7;
    if(items.length<desired){ const pad=Array.from({length:desired-items.length},(_,i)=>({rank:4+items.length+i,username:'--',wagerNum:0,wagerStr:formatUSD(0)})); items=items.concat(pad); }
    else if(items.length>desired) items=items.slice(0,desired);

    const newKeys=items.map(o=>`${o.rank}|${o.username}|${o.wagerStr}`);
    othersEl.innerHTML=items.map(o=>`
      <li class="fade-in">
        <span class="position">#${o.rank}</span>
        <div class="card-headroom" aria-hidden="true"></div>
        <div class="username">${o.username}</div>
        <div class="label emphasized">WAGERED</div>
        <div class="wager">${o.wagerStr}</div>
        <div class="label emphasized">PRIZE</div>
        <div class="prize">${PRIZES[o.rank]||formatUSD(0)}</div>
      </li>
    `).join('');

    newKeys.forEach((k,i)=>{ if(prevOthersKeys[i] && prevOthersKeys[i]!==k){ const node=othersEl.children[i]; if(node){ node.classList.add('value-changed'); setTimeout(()=>node.classList.remove('value-changed'),900); } }});
    prevOthersKeys=newKeys;
  }

  async function fetchData(){
    try{
      statusEl.hidden=true;
      const r=await fetch('/data',{cache:'no-store'}); if(!r.ok) throw new Error(r.status);
      const j=await r.json();
      const hasAny=(Array.isArray(j.podium)&&j.podium.length)||(Array.isArray(j.others)&&j.others.length);
      if(!hasAny){ statusEl.textContent='Fetching latest placements…'; statusEl.hidden=false; }
      buildPodium(j.podium||[]); buildOthers(j.others||[]);
    }catch(e){ statusEl.textContent='Could not load placements. Retrying…'; statusEl.hidden=false; console.error(e); }
  }

  async function fetchStream(){
    if(!liveEl) return;
    try{
      const r=await fetch('/stream',{cache:'no-store'}); if(!r.ok) throw new Error(r.status);
      const j=await r.json(); const live=!!j.live; const viewers=j.viewers??null;
      liveEl.classList.remove('live','off','unk');
      if(live){ liveEl.classList.add('live'); text.textContent='LIVE NOW!'; if(typeof viewers==='number'){ viewerChip.style.display='inline-flex'; viewerChip.textContent=`${viewers.toLocaleString()} watching`; } else viewerChip.style.display='none'; }
      else { liveEl.classList.add('off'); text.textContent='Offline'; viewerChip.style.display='none'; }
    }catch(e){ liveEl.classList.remove('live','off'); liveEl.classList.add('unk'); text.textContent='Status unavailable'; viewerChip.style.display='none'; console.warn(e); }
  }

  async function initCountdown(){
    try{
      const r=await fetch('/config',{cache:'no-store'}); if(!r.ok) throw new Error(r.status);
      const j=await r.json(); const end=Number(j.end_time)||0;
      function tick(){ const now=Math.floor(Date.now()/1000); let d=Math.max(0,end-now); const D=Math.floor(d/86400); d-=D*86400; const H=Math.floor(d/3600); d-=H*3600; const M=Math.floor(d/60); d-=M*60; const S=d; dd.textContent=String(D).padStart(2,'0'); hh.textContent=String(H).padStart(2,'0'); mm.textContent=String(M).padStart(2,'0'); ss.textContent=String(S).padStart(2,'0'); }
      tick(); setInterval(tick,1000);
    }catch(e){ console.warn('[countdown] failed',e); }
  }

  function boot(){
    if(yearOut) yearOut.textContent=new Date().getFullYear();
    fetchData(); fetchStream(); initCountdown();
    setInterval(fetchData,60_000); setInterval(fetchStream,60_000);
  }
  document.addEventListener('DOMContentLoaded', boot);
})();
