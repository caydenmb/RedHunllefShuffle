/**
 * script.js
 * - Keeps leaderboard logic identical
 * - Removes iframe/player logic
 * - Adds polished Live Status polling (every 30s) via /stream
 */

console.log("[DEBUG] boot: script.js loaded");

const $ = (s) => document.querySelector(s);

/* Prize schedule (includes 10th with $0.00) */
const PRIZE_MAP = {1:"$1,700.00",2:"$900.00",3:"$500.00",4:"$300.00",5:"$200.00",6:"$150.00",7:"$100.00",8:"$75.00",9:"$50.00",10:"$0.00"};

/* Countdown */
function pad2(n){return String(n).padStart(2,"0")}
function startCountdown(endEpoch){
  const elD=$("#dd"),elH=$("#hh"),elM=$("#mm"),elS=$("#ss");
  const target=Number(endEpoch)||0;
  function tick(){
    const now=Math.floor(Date.now()/1000);
    let diff=Math.max(0,target-now);
    const d=Math.floor(diff/86400);diff%=86400;
    const h=Math.floor(diff/3600);diff%=3600;
    const m=Math.floor(diff/60);const s=diff%60;
    elD.textContent=pad2(d);elH.textContent=pad2(h);elM.textContent=pad2(m);elS.textContent=pad2(s);
  }
  tick(); setInterval(tick,1000);
}

/* Networking */
let inflight;
async function fetchJSON(url,opts={}){
  if(inflight) inflight.abort();
  inflight = new AbortController();
  opts.signal = inflight.signal;
  const res = await fetch(url,opts);
  if(!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  return res.json();
}

/* Live status polling */
async function updateLiveStatus(){
  const badge = $("#liveStatus");
  const text  = badge.querySelector(".text");
  try{
    const data = await fetchJSON("/stream");
    // shape: { live: bool, title?: str, viewers?: int, updated: epoch, source: "kick"|"unknown" }
    if(data.live){
      badge.classList.remove("off","unk"); badge.classList.add("live");
      text.textContent = data.title ? `Live now: ${data.title}` : "Live now";
    }else{
      badge.classList.remove("live","unk"); badge.classList.add("off");
      text.textContent = "Offline";
    }
  }catch(err){
    badge.classList.remove("live","off"); badge.classList.add("unk");
    text.textContent = "Status unavailable";
    console.error("[ERROR] live status:", err);
  }
}

/* Leaderboard rendering (unchanged) */
function successText(r){return r===1?"Champion!":r===2?"Runner-up!":r===3?"Third place!":""}
function makeSeat(rank,name,wager,extra=""){
  const crown = rank===1?"👑":rank===2?"🥈":rank===3?"🥉":"";
  const seat = document.createElement("div");
  seat.className = `podium-seat ${extra} fade-in`;
  seat.innerHTML = `
    <div class="rank-badge">${rank}</div>
    <div class="crown">${crown}</div>
    <div class="user">${name}</div>
    ${rank<=3?`<div class="success-badge">${successText(rank)}</div>`:""}
    <div class="label">Wagered</div>
    <div class="wager">${wager}</div>
    <div class="label">Prize</div>
    <div class="prize">${PRIZE_MAP[rank]||"$0.00"}</div>
  `;
  return seat;
}
function renderLeaderboard(data){
  const podium=$("#podium"), others=$("#others-list");
  podium.innerHTML=""; others.innerHTML="";
  if(!data||data.error){ podium.innerHTML=`<p class="fade-in">Unable to load the leaderboard right now.</p>`; return;}
  const p=data.podium||[];
  if(p[1]) podium.appendChild(makeSeat(2,p[1].username,p[1].wager,"col-second"));
  if(p[0]) podium.appendChild(makeSeat(1,p[0].username,p[0].wager,"col-first"));
  if(p[2]) podium.appendChild(makeSeat(3,p[2].username,p[2].wager,"col-third"));
  const list=data.others||[];
  others.style.setProperty("--others-count", String(list.length||1));
  list.forEach(o=>{
    const li=document.createElement("li");
    li.className="fade-in";
    li.innerHTML=`
      <div class="position">#${o.rank}</div>
      <div class="username">${o.username}</div>
      <div class="label emphasized">Wager</div>
      <div class="wager">${o.wager}</div>
      <div class="prize">${PRIZE_MAP[o.rank]||"$0.00"}</div>
    `;
    others.appendChild(li);
  });
}

/* App boot */
async function bootstrap(){
  try{
    const conf=await fetchJSON("/config");
    startCountdown(conf.end_time);

    const initial=await fetchJSON("/data");
    renderLeaderboard(initial);

    setInterval(async()=>{
      try{ renderLeaderboard(await fetchJSON("/data",{cache:"no-store"})); }
      catch(err){ console.error("[ERROR] refresh leaderboard:", err); }
    }, (Number(conf.refresh_seconds||60))*1000);

    // Live status every 30s
    updateLiveStatus();
    setInterval(updateLiveStatus, 30_000);
  }catch(err){ console.error("[ERROR] bootstrap:",err); }
}

function setYear(){ const el=document.getElementById("year"); if(el) el.textContent=new Date().getFullYear(); }

window.addEventListener("DOMContentLoaded", ()=>{ setYear(); bootstrap(); });
