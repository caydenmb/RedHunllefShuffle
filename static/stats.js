/* Minimal, dependency-free stats rendering (SVG) — monthly KPIs + live time. */
(function(){
  function $(s, r=document){ return r.querySelector(s); }
  function fmt(n){ return (n||0).toLocaleString(); }

  function drawArea(svg, data){
    svg.innerHTML='';
    const w=600, h=240, pad=30;
    if(!Array.isArray(data) || data.length===0){ svg.textContent='No data'; return; }
    const max=Math.max(1, ...data.map(d=>d.count||0));
    const step=(w-2*pad)/Math.max(1,(data.length-1));
    let d=`M ${pad} ${h-pad}`;
    data.forEach((pt,i)=>{ const x=pad+i*step; const y=h-pad-((pt.count||0)/max)*(h-2*pad); d+=` L ${x} ${y}`;});
    d+=` L ${w-pad} ${h-pad} L ${pad} ${h-pad} Z`;
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('d', d); path.setAttribute('fill', '#2a6f2a'); path.setAttribute('opacity','0.5');
    svg.appendChild(path);
  }

  function drawTimeline(svg, timeline){
    svg.innerHTML='';
    const w=600, h=240, pad=22;
    const now = Math.floor(Date.now()/1000), start = now - 48*3600;
    const bandY = h/2 - 14, bandH = 28; const liveColor='#ff5c5c', offColor='#2a2a2a';
    let lastLive=0, lastTs=start;
    (timeline||[]).forEach(p=>{
      const ts=Math.max(start, p.ts||start);
      const x1=pad + ((lastTs-start)/(48*3600))*(w-2*pad);
      const x2=pad + ((ts-start)/(48*3600))*(w-2*pad);
      const rect=document.createElementNS('http://www.w3.org/2000/svg','rect');
      rect.setAttribute('x',x1); rect.setAttribute('y',bandY);
      rect.setAttribute('width',Math.max(1,x2-x1)); rect.setAttribute('height',bandH);
      rect.setAttribute('fill', lastLive?liveColor:offColor); svg.appendChild(rect);
      lastLive = p.live?1:0; lastTs = ts;
    });
    const x1=pad + ((lastTs-start)/(48*3600))*(w-2*pad), x2=w-pad;
    const tail=document.createElementNS('http://www.w3.org/2000/svg','rect');
    tail.setAttribute('x',x1); tail.setAttribute('y',bandY);
    tail.setAttribute('width',Math.max(1,x2-x1)); tail.setAttribute('height',bandH);
    tail.setAttribute('fill', lastLive?liveColor:offColor); svg.appendChild(tail);
  }

  function humanHrsMin(totalSeconds){
    const h = Math.floor(totalSeconds/3600);
    const m = Math.floor((totalSeconds%3600)/60);
    return `${h}h ${m}m`;
  }

  async function boot(){
    try{
      const r=await fetch('/stats-data',{cache:'no-store'}); if(!r.ok) throw new Error(r.status);
      const j=await r.json();

      $('#kpi-total-month').textContent   = fmt(j.kpi.total_visits_month||0);
      $('#kpi-unique-month').textContent  = fmt(j.kpi.unique_visitors_month||0);
      $('#kpi-online').textContent        = fmt(j.kpi.online_now||0);
      $('#kpi-avg-month').textContent     = fmt(j.kpi.avg_session_seconds_mon||0);

      drawArea( $('#visits-svg'), j.series.visits_per_day_month || [] );
      drawTimeline( $('#timeline-svg'), j.series.stream_timeline || [] );
      $('#live-hrs').textContent = humanHrsMin(j.kpi.live_seconds_48h || 0);
    }catch(e){
      console.error('stats load failed', e);
      const wrap = document.createElement('div');
      wrap.style.cssText = 'width:min(1100px,92%);margin:1rem auto;color:#ccc';
      wrap.textContent = 'Stats are temporarily unavailable.';
      document.body.appendChild(wrap);
    }
  }
  document.addEventListener('DOMContentLoaded', boot);
})();
