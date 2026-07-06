"use strict";

// Deeper shades so the white A–E letter stays legible (white on mid-tone fails contrast).
const RATING = {1:["A","#15803d"],2:["B","#3f6212"],3:["C","#854d0e"],4:["D","#c2410c"],5:["E","#b91c1c"]};
const SEV = {critical:"#7f1d1d",high:"#dc2626",medium:"#d97706",low:"#ca8a04"};
const ACCENT="#5b6cff", GOOD="#16a34a", WARN="#d97706", BAD="#dc2626", MUTED="#6b7280";

// Trend charts. accessor pulls the value (or null) from a snapshot.
const CHARTS = [
  {key:"coverage",         label:"Coverage trend",       sub:"overall code %, monthly", color:ACCENT,     unit:"%", yMin:0,      acc:s=>g(s,"sonar","coverage")},
  {key:"sqale_debt_ratio", label:"Tech-debt ratio",      sub:"SonarCloud SQALE",        color:WARN,       unit:"%", yMin:0, goal:"max_debt_ratio_pct", acc:s=>g(s,"sonar","sqale_debt_ratio")},
  {key:"code_smells",      label:"Code smells",          sub:"maintainability findings",color:"#8b5cf6",  unit:"",  acc:s=>g(s,"sonar","code_smells")},
  {key:"bugs",             label:"Bugs & vulnerabilities",sub:"reliability + security",  color:BAD,        unit:"",  acc:s=>g(s,"sonar","bugs")},
  {key:"open_branches",    label:"Open branches",        sub:"unmerged heads on the repo",color:"#0891b2", unit:"",  acc:s=>g(s,"github","open_branches")},
  {key:"tests",            label:"Unit tests",           sub:"total test count over time",color:GOOD,     unit:"",  acc:s=>g(s,"sonar","tests")},
];

let STATE = {config:{}, snapshots:[]};
const charts = {}; // Chart.js instances by canvas id

function g(snap, group, key){ const o = snap && snap[group]; return o ? (o[key] ?? null) : null; }
function monthLabel(ym){ const [y,m]=ym.split("-"); const d=new Date(+y,+m-1,1);
  return d.toLocaleString("en",{month:"short"})+" "+String(y).slice(2); }
function fmt(v, unit="", dec=1){
  if(v===null||v===undefined) return "—";
  if(typeof v==="number"){ const r = (dec===0||v===Math.round(v)) ? Math.round(v) : v;
    return r.toLocaleString("en",{maximumFractionDigits:dec})+unit; }
  return v+unit;
}

async function load(){
  const r = await fetch("/api/data"); STATE = await r.json();
  const months = STATE.snapshots.map(s=>s.month);
  const fromSel=document.getElementById("from"), toSel=document.getElementById("to");
  fromSel.innerHTML = toSel.innerHTML = "";
  months.forEach(m=>{
    fromSel.add(new Option(monthLabel(m), m));
    toSel.add(new Option(monthLabel(m), m));
  });
  if(months.length){ fromSel.value=months[0]; toSel.value=months[months.length-1]; }
  const proj = STATE.config.project_label || "";
  const latest = months[months.length-1] || "";
  document.getElementById("subtitle").textContent = proj + (latest? " · "+monthLabel(latest):"");
  document.getElementById("tracked").textContent = months.length + " month" + (months.length!==1?"s":"") + " tracked";
  render();
}

function filtered(){
  const from=document.getElementById("from").value, to=document.getElementById("to").value;
  return STATE.snapshots.filter(s=> s.month>=from && s.month<=to);
}

function render(){
  const snaps = filtered();
  if(!snaps.length) return;
  const cur = snaps[snaps.length-1], prev = snaps.length>1 ? snaps[snaps.length-2] : null;
  renderKpis(snaps, cur, prev);
  renderRatings(cur);
  renderCharts(snaps);
  renderTests(cur);
  renderDependabot(cur);
  renderGate(cur);
  document.getElementById("footer").textContent =
    "Data from SonarCloud + GitHub · " + snaps.length + " months in view";
}

function kpiCard(label, cur, prev, {unit="",dec=1,higher=true,goal=null}={}){
  let delta="";
  if(cur!=null && prev!=null && typeof cur==="number"){
    const diff = cur-prev;
    if(Math.abs(diff)<1e-9) delta = `<span class="delta flat">▬ no change</span>`;
    else { const improving=(diff>0)===higher, col=improving?GOOD:BAD, arrow=diff>0?"▲":"▼";
      delta = `<span class="delta" style="color:${col}">${arrow} ${fmt(Math.abs(diff),unit,dec)} vs prev</span>`; }
  }
  const goalHtml = goal!=null ? `<span class="cgoal">goal ${fmt(goal,unit,0)}</span>` : "";
  return `<div class="card kpi"><div class="klabel">${label}${goalHtml}</div>
    <div class="kval">${fmt(cur,unit,dec)}</div>${delta}</div>`;
}

function renderKpis(snaps, cur, prev){
  const G = STATE.config.goals || {};
  const dep = s => g(s,"github","dependabot") ? g(s,"github","dependabot").total : null;
  document.getElementById("kpis").innerHTML = [
    kpiCard("Overall coverage", g(cur,"sonar","coverage"), g(prev,"sonar","coverage"), {unit:"%",higher:true,goal:G.coverage_pct}),
    kpiCard("New-code coverage", g(cur,"sonar","new_coverage"), g(prev,"sonar","new_coverage"), {unit:"%",higher:true,goal:G.new_coverage_pct}),
    kpiCard("Tech-debt ratio", g(cur,"sonar","sqale_debt_ratio"), g(prev,"sonar","sqale_debt_ratio"), {unit:"%",higher:false,goal:G.max_debt_ratio_pct}),
    kpiCard("Unit tests", g(cur,"sonar","tests"), g(prev,"sonar","tests"), {dec:0,higher:true}),
    kpiCard("Open branches", g(cur,"github","open_branches"), g(prev,"github","open_branches"), {dec:0,higher:false}),
    kpiCard("Dependabot alerts", dep(cur), dep(prev), {dec:0,higher:false}),
  ].join("");
}

function ratingBadge(v){ const [l,c]=RATING[v]||["?",MUTED]; return `<span class="rating" style="background:${c}">${l}</span>`; }
function renderRatings(cur){
  const s=cur.sonar||{};
  document.getElementById("ratings").innerHTML = [
    `<div class="rblock">${ratingBadge(s.reliability_rating)}<div><b>Reliability</b><span>${fmt(s.bugs,"",0)} bugs</span></div></div>`,
    `<div class="rblock">${ratingBadge(s.security_rating)}<div><b>Security</b><span>${fmt(s.vulnerabilities,"",0)} vulns · ${fmt(s.security_hotspots,"",0)} hotspots</span></div></div>`,
    `<div class="rblock">${ratingBadge(s.sqale_rating)}<div><b>Maintainability</b><span>${fmt(s.code_smells,"",0)} smells · ${fmt(s.duplication,"%")} dup</span></div></div>`,
    `<div class="rblock"><span class="rating" style="background:#4338ca">Σ</span><div><b>Codebase size</b><span>${fmt(s.ncloc,"",0)} lines</span></div></div>`,
  ].join("");
}

function renderCharts(snaps){
  const box=document.getElementById("charts"); box.innerHTML="";
  const G = STATE.config.goals || {};
  const labels = snaps.map(s=>monthLabel(s.month));
  CHARTS.forEach(cfg=>{
    const id="chart-"+cfg.key;
    const card=document.createElement("div"); card.className="card";
    card.innerHTML=`<div class="chdr"><h3>${cfg.label}</h3><span>${cfg.sub}</span></div>
      <div class="chart-box"><canvas id="${id}"></canvas></div>`;
    box.appendChild(card);
    const data = snaps.map(cfg.acc);
    const ds=[{data, borderColor:cfg.color, backgroundColor:cfg.color+"1f", fill:true,
      tension:.3, spanGaps:true, pointRadius:3, pointHoverRadius:5, borderWidth:2.5}];
    const goalVal = cfg.goal ? G[cfg.goal] : null;
    if(goalVal!=null){ ds.push({data:labels.map(()=>goalVal), borderColor:GOOD, borderDash:[5,4],
      borderWidth:1.5, pointRadius:0, fill:false, label:"goal"}); }
    const yScale = {beginAtZero: cfg.yMin===0};
    if(goalVal!=null) yScale.suggestedMax = goalVal * 1.1;
    if(charts[id]) charts[id].destroy();
    charts[id]=new Chart(document.getElementById(id), {
      type:"line",
      data:{labels, datasets:ds},
      options:{responsive:true, maintainAspectRatio:false,
        plugins:{legend:{display:false},
          tooltip:{callbacks:{label:ctx=> (ctx.datasetIndex===1?"goal ":"")+fmt(ctx.parsed.y,cfg.unit,1)}}},
        scales:{y:yScale, x:{grid:{display:false}}}}
    });
  });
}

function doughnut(id, entries){ // entries: [[label,val,color],...]
  if(charts[id]) charts[id].destroy();
  charts[id]=new Chart(document.getElementById(id), {
    type:"doughnut",
    data:{labels:entries.map(e=>e[0]), datasets:[{data:entries.map(e=>e[1]),
      backgroundColor:entries.map(e=>e[2]), borderWidth:0}]},
    options:{responsive:true, maintainAspectRatio:false, cutout:"62%",
      plugins:{legend:{position:"right", labels:{boxWidth:12, font:{size:12}}}}}
  });
}

function renderTests(cur){
  const s=cur.sonar||{};
  document.getElementById("tsd").textContent = fmt(s.test_success_density,"%")+" success density";
  if(s.tests==null){ return; }
  const failing=(s.test_failures||0)+(s.test_errors||0);
  const passing=s.tests-(s.skipped_tests||0)-failing;
  doughnut("c-tests", [["passing",passing,GOOD],["skipped",s.skipped_tests||0,WARN],["failing",failing,BAD]]);
}

function renderDependabot(cur){
  const dep=g(cur,"github","dependabot")||{};
  doughnut("c-dep", [["critical",dep.critical||0,SEV.critical],["high",dep.high||0,SEV.high],
    ["medium",dep.medium||0,SEV.medium],["low",dep.low||0,SEV.low]]);
}

function renderGate(cur){
  const s=cur.sonar||{};
  const conds=(s.gate_conditions||[]).slice(0,8).map(c=>
    `<li><code>${c.metric||""}</code> ${c.actual??""} (limit ${c.threshold??""})</li>`).join("") || "<li>no failing conditions</li>";
  document.getElementById("gate").innerHTML = `<div class="gate">
    <div>SonarCloud new-code gate: <span class="tag">${s.gate_status||"NONE"}</span>
      — informational; fails on new-code rules developers resolve, not overall health.</div>
    <ul>${conds}</ul></div>`;
}

function toast(msg, ok=true){
  const t=document.getElementById("toast");
  t.textContent=msg; t.className="toast show "+(ok?"ok":"err");
  setTimeout(()=>{ t.className="toast"; }, 4500);
}

async function post(path){
  const r=await fetch(path,{method:"POST"});
  return {status:r.status, body:await r.json()};
}

// --- wiring ---------------------------------------------------------------
document.addEventListener("DOMContentLoaded", ()=>{
  document.getElementById("from").addEventListener("change", render);
  document.getElementById("to").addEventListener("change", render);

  document.querySelectorAll(".chip").forEach(chip=> chip.addEventListener("click", ()=>{
    document.querySelectorAll(".chip").forEach(c=>c.classList.remove("active"));
    chip.classList.add("active");
    const n=+chip.dataset.months, months=STATE.snapshots.map(s=>s.month);
    const to=months[months.length-1];
    const from = (n===0||n>=months.length) ? months[0] : months[months.length-n];
    document.getElementById("from").value=from; document.getElementById("to").value=to;
    render();
  }));

  document.getElementById("btn-snapshot").addEventListener("click", async e=>{
    const b=e.target; b.disabled=true; b.textContent="↻ Snapshotting…";
    const {body}=await post("/api/snapshot");
    if(body.ok){ await load(); toast("Snapshot saved for "+monthLabel(body.month)); }
    else toast("Snapshot failed: "+(body.error||"unknown"), false);
    b.disabled=false; b.textContent="↻ Snapshot now";
  });

  document.getElementById("btn-report").addEventListener("click", async e=>{
    const b=e.target; b.disabled=true; b.textContent="⤓ Building…";
    const {body}=await post("/api/report");
    if(body.ok) toast("PO report rebuilt — open it with the button →");
    else toast("Report failed: "+(body.error||"unknown"), false);
    b.disabled=false; b.textContent="⤓ Rebuild report";
  });

  load();
});
