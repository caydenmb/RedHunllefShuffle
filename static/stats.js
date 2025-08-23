(function(){
  function $(s, r=document){ return r.querySelector(s); }
  function fmt(n){ return (n||0).toLocaleString(); }
  function pct(n, total){ return total? Math.round(n/total*100) : 0; }

  function drawArea(svg, data){
    svg.innerHTML='';
    const w=600, h=220, pad=30;
    if(!Array.isArray(data) || data.length===0){
      svg.textContent = 'No data';
      return;
    }
    const max=Math.max(1, ...data.map(d=>d.count||0));
    const step=(w-2*pad)/Math.max(1,(data.length-1));
    let d=`M ${pad} ${h-pad}`;
    data.forEach((pt,i)=>{
      const x=pad + i*step;
      const y=h-pad - ((pt.count||0)/max)*(h-2*pad);
      d+=` L ${x} ${y}`;
    });
    d+=` L ${w-pad} ${h-pad} L ${pad} ${h-pad} Z`;
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('d', d);
    path.setAttribute('fill', '#2a6f2a');
    path.setAttribute('opacity','0.5');
    svg.appendChild(path);
  }

  function drawBars(svg, data){
    svg.innerHTML='';
    const w=600, h=220, pad=30;
    if(!Array.isArray(data) || data.length===0){
      svg.textContent = 'No data';
      return;
    }
    const max=Math.max(1, ...data.map(d=>d.count||0));
    const barH=(h-2*pad)/Math.max(1,data.length);
    data.forEach((row,i)=>{
      const y=pad + i*barH + 6;
      const wid=((row.count||0)/max)*(w-2*pad);
      const rect=document.createElementNS('http://www.w3.org/2000/svg','rect');
      rect.setAttribute('x', pad);
      rect.setAttribute('y', y);
      rect.setAttribute('width', Math.max(2,wid));
      rect.setAttribute('height', barH-12);
      rect.setAttribute('fill', '#2f7ad1');
      svg.appendChild(rect);

      const label=document.createElementNS('http://www.w3.org/2000/svg','text');
      label.setAttribute('x', pad+6);
      label.setAttribute('y', y + (barH/2));
      label.setAttribute('dominant-baseline','middle');
      label.setAttribute('fill','#eaeaea');
      label.setAttribute('font-size','12');
      label.textContent = `${row.referrer||'—'} • ${fmt(row.count||0)}`;
      svg.appendChild(label);
    });
  }

  function drawDonut(svg, legendEl, map){
    svg.innerHTML=''; legendEl.innerHTML='';
    const entries = Object.entries(map||{});
    const total = entries.reduce((a,[,v])=>a+(v||0),0);
    if(entries.length===0 || total===0){
      svg.textContent = 'No data';
      return;
    }
    const cx=300, cy=110, r=70, thick=26;
    const COLORS={mobile:'#3abf5a',desktop:'#8884ff',tablet:'#ff9f43'};
    let start=0;
    entries.forEach(([k,v])=>{
      const frac = (v||0)/total;
      const end = start + frac*2*Math.PI;
      const x1 = cx + Math.cos(start)*r, y1=cy + Math.sin(start)*r;
      const x2 = cx + Math.cos(end)*r,   y2=cy + Math.sin(end)*r;
      const large = frac>0.5 ? 1 : 0;

      const path=document.createElementNS('http://www.w3.org/2000/svg','path');
      const d = [
        `M ${x1} ${y1}`,
        `A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`,
        `L ${cx + Math.cos(end)*(r-thick)} ${cy + Math.sin(end)*(r-thick)}`,
        `A ${r-thick} ${r-thick} 0 ${large} 0 ${cx + Math.cos(start)*(r-thick)} ${cy + Math.sin(start)*(r-thick)}`,
        'Z'
      ].join(' ');
      path.setAttribute('d', d);
      path.setAttribute('fill', COLORS[k] || '#666');
      svg.appendChild(path);

      const leg=document.createElement('div');
      leg.textContent = `${k} — ${fmt(v||0)} (${pct(v,total)}%)`;
      legendEl.appendChild(leg);

      start = end;
    });

    const title=document.createElementNS('http://www.w3.org/2000/svg','text');
    title.setAttribute('x', cx);
    title.setAttribute('y', cy);
    title.setAttribute('text-anchor','middle');
    title.setAttribute('fill','#ddd');
    title.setAttribute('font-weight','900');
    title.textContent = `${fmt(total)} visits`;
    svg.appendChild(title);
  }

  function drawTimeline(svg, timeline){
    svg.innerHTML='';
    const w=600, h=220, pad=20;
    const now = Math.floor(Date.now()/1000);
    const start = now - 48*3600;
    const bandY = h/2 - 12, bandH = 24;
    const liveColor = '#ff5c5c', offColor = '#2a2a2a';

    let lastLive = 0, lastTs = start;
    (timeline||[]).forEach(p=>{
      const ts = Math.max(start, p.ts||start);
      const x1 = pad + ((lastTs - start) / (48*3600)) * (w-2*pad);
      const x2 = pad + ((ts     - start) / (48*3600)) * (w-2*pad);
      const rect=document.createElementNS('http://www.w3.org/2000/svg','rect');
      rect.setAttribute('x', x1);
      rect.setAttribute('y', bandY);
      rect.setAttribute('width', Math.max(1, x2-x1));
      rect.setAttribute('height', bandH);
      rect.setAttribute('fill', lastLive? liveColor : offColor);
      svg.appendChild(rect);
      lastLive = p.live?1:0;
      lastTs = ts;
    });
    const x1 = pad + ((lastTs - start) / (48*3600)) * (w-2*pad);
    const x2 = w-pad;
    const tail=document.createElementNS('http://www.w3.org/2000/svg','rect');
    tail.setAttribute('x', x1); tail.setAttribute('y', bandY);
    tail.setAttribute('width', Math.max(1, x2-x1)); tail.setAttribute('height', bandH);
    tail.setAttribute('fill', lastLive? liveColor : offColor);
    svg.appendChild(tail);
  }

  async function boot(){
    try{
      const r=await fetch('/stats-data',{cache:'no-store'});
      if(!r.ok) throw new Error(`stats-data ${r.status}`);
      const j=await r.json();

      $('#kpi-total').textContent  = (j.kpi.total_visits||0).toLocaleString();
      $('#kpi-unique').textContent = (j.kpi.unique_30d||0).toLocaleString();
      $('#kpi-online').textContent = (j.kpi.online_now||0).toLocaleString();
      $('#kpi-avg').textContent    = (j.kpi.avg_session_seconds||0).toLocaleString();
      $('#kpi-updates').textContent= (j.kpi.updates_today||0).toLocaleString();
      $('#kpi-health').textContent = (j.kpi.api_health.kick_ok && j.kpi.api_health.cache_ok) ? 'OK' : 'Degraded';

      drawArea( $('#visits-svg'), j.series.visits_per_day || [] );
      drawBars(  $('#refs-svg'),   j.series.top_referrers || [] );
      drawDonut( $('#devices-svg'), $('#devices-legend'), j.series.devices || {} );
      drawTimeline( $('#timeline-svg'), j.series.stream_timeline || [] );
    }catch(e){
      console.error('stats load failed', e);
      // show a simple message if the endpoint is unavailable
      const wrap = document.createElement('div');
      wrap.style.cssText = 'width:min(1100px,92%);margin:1rem auto;color:#ccc';
      wrap.textContent = 'Stats are temporarily unavailable.';
      document.body.appendChild(wrap);
    }
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
