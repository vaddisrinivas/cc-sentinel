"""Dashboard HTML template — served from localhost, Chart.js from CDN."""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>cc-retrospect Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
:root {
  --bg: #0d1117; --surface: #161b22; --surface2: #1c2129; --border: #30363d;
  --text: #e6edf3; --muted: #8b949e; --dim: #484f58;
  --green: #3fb950; --green-bg: #1a3a2a; --yellow: #d29922; --yellow-bg: #3a2f1a;
  --red: #f85149; --red-bg: #3a1a1a; --blue: #58a6ff; --blue-bg: #1a2a3a;
  --purple: #bc8cff; --orange: #d18616;
}
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); padding: 24px 32px; max-width: 1280px; margin: 0 auto; line-height: 1.5; }

.header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
.header h1 { font-size: 22px; font-weight: 600; }
.header .meta { color: var(--muted); font-size: 13px; }

/* Budget */
.budget { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 24px 28px; margin-bottom: 24px; }
.budget h2 { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
.budget-row { display: flex; align-items: baseline; gap: 16px; margin-bottom: 16px; }
.budget-amount { font-size: 44px; font-weight: 700; letter-spacing: -1px; }
.budget-of { font-size: 14px; color: var(--muted); }
.budget-track { height: 10px; background: var(--border); border-radius: 5px; margin-bottom: 10px; position: relative; }
.budget-fill { height: 100%; border-radius: 5px; }
.budget-markers { position: relative; height: 20px; margin-bottom: 16px; }
.budget-marker { position: absolute; transform: translateX(-50%); font-size: 11px; color: var(--muted); }
.budget-marker.hit { font-weight: 700; }
.projects { border-top: 1px solid var(--border); padding-top: 12px; }
.proj-row { display: flex; align-items: center; padding: 6px 0; }
.proj-name { width: 200px; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.proj-bar { flex: 1; height: 8px; background: var(--border); border-radius: 4px; margin: 0 12px; }
.proj-fill { height: 100%; border-radius: 4px; background: var(--blue); }
.proj-cost { width: 90px; text-align: right; font-size: 13px; color: var(--muted); font-weight: 600; }

/* Stats */
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 24px; }
.stat { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; }
.stat-val { font-size: 26px; font-weight: 700; }
.stat-lbl { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; }

/* Grid */
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }
@media (max-width: 960px) { .grid { grid-template-columns: 1fr; } }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px 24px; }
.card h3 { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 16px; }
.card.full { grid-column: 1 / -1; }

/* Interventions */
.alert { border-radius: 8px; padding: 12px 16px; margin-bottom: 10px; display: flex; align-items: center; gap: 12px; }
.alert.warn { background: var(--yellow-bg); border-left: 3px solid var(--yellow); }
.alert.error { background: var(--red-bg); border-left: 3px solid var(--red); }
.alert.info { background: var(--blue-bg); border-left: 3px solid var(--blue); }
.alert.good { background: var(--green-bg); border-left: 3px solid var(--green); }
.alert-badge { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 4px; }
.alert-badge.warn { background: var(--yellow); color: #000; }
.alert-badge.error { background: var(--red); color: #fff; }
.alert-badge.info { background: var(--blue); color: #000; }
.alert-badge.good { background: var(--green); color: #000; }
.alert-msg { font-size: 13px; }

/* Sessions */
.session-list { max-height: 520px; overflow-y: auto; }
.sess { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; margin-bottom: 8px; cursor: pointer; }
.sess:hover { border-color: var(--blue); }
.sess-row { display: grid; grid-template-columns: 32px 1fr 80px 60px 70px 80px; gap: 10px; align-items: center; font-size: 13px; }
.grade { width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 12px; flex-shrink: 0; }
.grade-A { background: var(--green-bg); color: var(--green); }
.grade-B { background: #2a3520; color: #7ee787; }
.grade-C { background: var(--yellow-bg); color: var(--yellow); }
.grade-D { background: var(--red-bg); color: var(--red); }
.sess .proj { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sess .cost { font-weight: 600; text-align: right; }
.sess .dur { color: var(--muted); text-align: right; }
.sess .mdl { color: var(--purple); font-size: 11px; text-align: right; }
.sess .fr { color: var(--red); font-size: 12px; text-align: right; }
.sess-detail { display: none; margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border); font-size: 12px; color: var(--muted); }
.sess-detail.open { display: block; }
.tool-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.tool-tag { background: var(--surface2); border-radius: 4px; padding: 2px 8px; font-size: 11px; }

/* Compactions */
.compact-row { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
.compact-row:last-child { border-bottom: none; }
.compact-ts { color: var(--muted); width: 150px; font-size: 12px; flex-shrink: 0; }
.compact-reason { flex: 1; }
.compact-tokens { color: var(--green); font-weight: 600; }

/* Trends */
.t-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.t-table th { text-align: left; padding: 8px 10px; color: var(--muted); font-size: 11px; text-transform: uppercase; border-bottom: 1px solid var(--border); }
.t-table td { padding: 8px 10px; border-bottom: 1px solid var(--border); }

/* Frustration */
.frust-tag { display: inline-block; background: var(--red-bg); border: 1px solid rgba(248,81,73,0.3); border-radius: 6px; padding: 4px 10px; margin: 3px; font-size: 12px; }
.frust-cnt { font-weight: 700; margin-left: 4px; color: var(--red); }

.empty { color: var(--dim); font-style: italic; font-size: 13px; padding: 20px; text-align: center; }
.footer { text-align: center; color: var(--dim); font-size: 11px; padding: 24px 0; border-top: 1px solid var(--border); margin-top: 24px; }
</style>
</head>
<body>

<div class="header">
  <h1>cc-retrospect</h1>
  <div class="meta" id="meta"></div>
</div>
<div class="budget" id="budget"></div>
<div class="stats" id="stats"></div>
<div class="grid">
  <div class="card"><h3>Interventions</h3><div id="interventions"></div></div>
  <div class="card"><h3>Model Cost Split</h3><div style="height:220px;position:relative"><canvas id="model-chart"></canvas></div></div>
  <div class="card full"><h3>Daily Cost</h3><div style="height:260px;position:relative"><canvas id="cost-chart"></canvas></div></div>
  <div class="card full"><h3>Recent Sessions</h3><div class="session-list" id="sessions"></div></div>
  <div class="card"><h3>Compaction Events</h3><div id="compactions"></div></div>
  <div class="card"><h3>Weekly Trends</h3><div id="trends"></div></div>
  <div class="card full"><h3>Frustration Triggers</h3><div id="frustrations"></div></div>
</div>
<div class="footer">cc-retrospect &middot; refresh with <code>/cc-retrospect:dashboard</code> &middot; Ctrl+C to stop server</div>

<script>
const D = __DATA_JSON__;
const fmt = n => '$' + n.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
const fmtK = n => n >= 1000 ? '$' + (n/1000).toFixed(1) + 'k' : '$' + n.toFixed(0);
const fmtTok = n => n >= 1e9 ? (n/1e9).toFixed(1)+'B' : n >= 1e6 ? (n/1e6).toFixed(1)+'M' : n >= 1e3 ? (n/1e3).toFixed(0)+'k' : String(n);
const proj = p => (p||'').replace(/^-Users-[^-]+-Projects-/,'').replace(/^-Users-[^-]+-/,'~').replace(/^-/,'') || '?';

Chart.defaults.color = '#e6edf3';
Chart.defaults.borderColor = '#21262d';
Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, sans-serif';
Chart.defaults.font.size = 11;

// Meta
document.getElementById('meta').textContent = `${D.generated_at} \u00b7 ${D.sessions.length} sessions \u00b7 ${D.days}d window`;

// Budget
(function(){
  const el = document.getElementById('budget');
  const cost = D.state.today_cost || 0;
  const tiers = D.budget_tiers;
  const max = tiers[tiers.length-1].threshold * 1.3;
  const pct = Math.min(100, cost/max*100);
  let color = '#3fb950';
  for (const t of tiers) if (cost >= t.threshold) color = t.color;
  const projs = Object.entries(D.state.projects||{}).map(([k,v])=>[proj(k),v.today_cost||0]).sort((a,b)=>b[1]-a[1]);

  el.innerHTML = `
    <h2>Today's Spend</h2>
    <div class="budget-row"><div class="budget-amount" style="color:${color}">${fmt(cost)}</div><div class="budget-of">of ${fmtK(tiers[tiers.length-1].threshold)} severe</div></div>
    <div class="budget-track"><div class="budget-fill" style="width:${pct}%;background:${color}"></div></div>
    <div class="budget-markers">${tiers.map(t=>{const p=t.threshold/max*100;return`<div class="budget-marker${cost>=t.threshold?' hit':''}" style="left:${p}%;color:${cost>=t.threshold?t.color:'var(--muted)'}">${t.label} ${fmtK(t.threshold)}</div>`;}).join('')}</div>
    <div class="projects">${projs.map(([n,c])=>`<div class="proj-row"><span class="proj-name">${n}</span><div class="proj-bar"><div class="proj-fill" style="width:${cost>0?c/cost*100:0}%"></div></div><span class="proj-cost">${fmt(c)}</span></div>`).join('')}</div>
  `;
})();

// Stats
(function(){
  const ss = D.sessions;
  const total = ss.reduce((s,x)=>s+(x.total_cost||0),0);
  const avgDur = ss.length ? ss.reduce((s,x)=>s+(x.duration_minutes||0),0)/ss.length : 0;
  const frust = ss.reduce((s,x)=>s+(x.frustration_count||0),0);
  const subs = ss.reduce((s,x)=>s+(x.subagent_count||0),0);
  const cr = ss.reduce((s,x)=>s+(x.total_cache_read_tokens||0),0);
  const inp = ss.reduce((s,x)=>s+(x.total_input_tokens||0),0);
  const rate = (inp+cr)>0 ? (cr/(inp+cr)*100).toFixed(1) : '0';

  document.getElementById('stats').innerHTML = [
    {v:fmt(total),l:`Total (${D.days}d)`}, {v:ss.length,l:'Sessions'},
    {v:Math.round(avgDur)+'m',l:'Avg Duration'}, {v:frust,l:'Frustrations'},
    {v:subs,l:'Subagents'}, {v:rate+'%',l:'Cache Hit'},
    {v:(D.compactions||[]).length,l:'Compactions'},
  ].map(s=>`<div class="stat"><div class="stat-val">${s.v}</div><div class="stat-lbl">${s.l}</div></div>`).join('');
})();

// Interventions
(function(){
  const items = [];
  (D.state.last_waste_flags||[]).forEach(f => items.push({b:'WASTE',m:f,c:'warn'}));
  (D.state.budget_alerts_today||[]).forEach(a => items.push({b:a.toUpperCase(),m:`Budget ${a} tier crossed (${fmt(D.state.today_cost||0)})`,c:a==='severe'||a==='critical'?'error':'warn'}));
  if ((D.state.last_session_duration_minutes||0)>120) items.push({b:'LONG',m:`Last session: ${Math.round(D.state.last_session_duration_minutes)}m`,c:'warn'});
  if ((D.state.last_subagent_count||0)>10) items.push({b:'AGENTS',m:`${D.state.last_subagent_count} subagents last session`,c:'warn'});
  if ((D.state.last_frustration_count||0)>3) items.push({b:'FRUST',m:`${D.state.last_frustration_count} frustration signals`,c:'error'});
  if (!items.length) items.push({b:'OK',m:'No interventions today',c:'good'});
  document.getElementById('interventions').innerHTML = items.map(i=>`<div class="alert ${i.c}"><span class="alert-badge ${i.c}">${i.b}</span><span class="alert-msg">${i.m}</span></div>`).join('');
})();

// Model donut
(function(){
  const totals = {};
  D.sessions.forEach(s => { for (const [m,c] of Object.entries(s.model_breakdown||{})) { const k=m.includes('opus')?'Opus':m.includes('sonnet')?'Sonnet':m.includes('haiku')?'Haiku':'Other'; totals[k]=(totals[k]||0)+c; }});
  const labels = Object.keys(totals);
  if (!labels.length) { document.getElementById('model-chart').parentElement.innerHTML='<div class="empty">No model data</div>'; return; }
  const colors = {Opus:'rgba(188,140,255,0.85)',Sonnet:'rgba(88,166,255,0.85)',Haiku:'rgba(63,185,80,0.85)',Other:'rgba(209,134,22,0.85)'};
  new Chart(document.getElementById('model-chart'), {
    type: 'doughnut',
    data: { labels, datasets: [{ data: labels.map(l=>totals[l]), backgroundColor: labels.map(l=>colors[l]||'#888'), borderWidth: 0 }] },
    options: { responsive: true, maintainAspectRatio: false, cutout: '60%',
      plugins: { legend: { position: 'right', labels: { padding: 12, usePointStyle: true, pointStyle: 'rectRounded',
        generateLabels: ch => ch.data.labels.map((l,i) => ({text:`${l}  ${fmt(ch.data.datasets[0].data[i])}`, fillStyle:ch.data.datasets[0].backgroundColor[i], strokeStyle:'transparent', color:'#e6edf3', index:i}))
      }}}
    }
  });
})();

// Daily cost stacked bar
(function(){
  const daily = {}, dm = {};
  D.sessions.forEach(s => {
    const d = (s.start_ts||'').slice(0,10); if (!d) return;
    daily[d] = (daily[d]||0) + (s.total_cost||0);
    if (!dm[d]) dm[d] = {};
    for (const [m,c] of Object.entries(s.model_breakdown||{})) {
      const k = m.includes('opus')?'Opus':m.includes('sonnet')?'Sonnet':'Haiku';
      dm[d][k] = (dm[d][k]||0) + c;
    }
  });
  const days = Object.keys(daily).sort();
  if (!days.length) { document.getElementById('cost-chart').parentElement.innerHTML='<div class="empty">No data</div>'; return; }
  new Chart(document.getElementById('cost-chart'), {
    type: 'bar',
    data: {
      labels: days.map(d=>d.slice(5)),
      datasets: [
        { label:'Opus', data:days.map(d=>(dm[d]||{}).Opus||0), backgroundColor:'rgba(188,140,255,0.7)', stack:'s' },
        { label:'Sonnet', data:days.map(d=>(dm[d]||{}).Sonnet||0), backgroundColor:'rgba(88,166,255,0.7)', stack:'s' },
        { label:'Haiku', data:days.map(d=>(dm[d]||{}).Haiku||0), backgroundColor:'rgba(63,185,80,0.7)', stack:'s' },
      ]
    },
    options: { responsive:true, maintainAspectRatio:false,
      plugins: { legend: { labels: { usePointStyle:true, pointStyle:'rectRounded', padding:16 } },
        tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${fmt(ctx.raw)}` } }
      },
      scales: { x: { grid: { display:false } }, y: { stacked:true, ticks: { callback: v=>'$'+v }, grid: { color:'#21262d' } } }
    }
  });
})();

// Sessions
(function(){
  function gr(s) {
    if (s.duration_minutes>180||s.subagent_count>15||s.total_cost>100||s.frustration_count>10) return 'D';
    if (s.duration_minutes>120||s.subagent_count>12||s.total_cost>60||s.frustration_count>5) return 'C';
    if (s.duration_minutes>90||s.subagent_count>8||s.total_cost>30) return 'B';
    return 'A';
  }
  const recent = [...D.sessions].sort((a,b)=>(b.start_ts||'').localeCompare(a.start_ts||'')).slice(0,30);
  document.getElementById('sessions').innerHTML = recent.map(s => {
    const g = gr(s);
    const tm = Object.entries(s.model_breakdown||{}).sort((a,b)=>b[1]-a[1])[0];
    const mn = tm?(tm[0].includes('opus')?'Opus':tm[0].includes('sonnet')?'Sonnet':'Haiku'):'';
    const tools = Object.entries(s.tool_counts||{}).sort((a,b)=>b[1]-a[1]).slice(0,10);
    const waste = [];
    const gh = (s.webfetch_domains||{})['github.com']; if (gh) waste.push(`GitHub WebFetch: ${gh}`);
    if (s.mega_prompt_count) waste.push(`Mega prompts: ${s.mega_prompt_count}`);
    return `<div class="sess" onclick="this.querySelector('.sess-detail').classList.toggle('open')">
      <div class="sess-row">
        <div class="grade grade-${g}">${g}</div>
        <div class="proj">${proj(s.project)} <span style="color:var(--dim);font-size:11px">${(s.start_ts||'').slice(0,16).replace('T',' ')}</span></div>
        <div class="cost">${fmt(s.total_cost||0)}</div>
        <div class="dur">${Math.round(s.duration_minutes||0)}m</div>
        <div class="mdl">${mn}</div>
        <div class="fr">${s.frustration_count?s.frustration_count+' frust':''}</div>
      </div>
      <div class="sess-detail">
        <div><b>Messages:</b> ${s.message_count||0} &middot; <b>Subagents:</b> ${s.subagent_count||0} &middot; <b>Tokens:</b> ${fmtTok(s.total_input_tokens||0)} in / ${fmtTok(s.total_output_tokens||0)} out / ${fmtTok(s.total_cache_read_tokens||0)} cached</div>
        ${tools.length?`<div class="tool-tags">${tools.map(([t,c])=>`<span class="tool-tag">${t}: ${c}</span>`).join('')}</div>`:''}
        ${waste.length?`<div style="margin-top:8px;color:var(--yellow)">Waste: ${waste.join(' &middot; ')}</div>`:''}
      </div>
    </div>`;
  }).join('');
})();

// Compactions
(function(){
  const ev = D.compactions || [];
  if (!ev.length) { document.getElementById('compactions').innerHTML='<div class="empty">No compaction events yet</div>'; return; }
  document.getElementById('compactions').innerHTML = ev.slice(-15).reverse().map(e => {
    const ts = (e.timestamp||e.ts||'').replace('T',' ').slice(0,19);
    const reason = e.compact_reason||e.reason||'auto';
    const freed = e.tokens_freed||e.tokens||0;
    const msgs = e.message_count_at_compact||e.message_count||0;
    const label = freed ? fmtTok(freed)+' freed' : msgs ? `at msg ${msgs}` : '';
    const reasonTxt = reason==='unknown'||!reason ? 'compacted' : reason;
    return `<div class="compact-row"><span class="compact-ts">${ts}</span><span class="compact-reason">${reasonTxt}</span><span class="compact-tokens">${label}</span></div>`;
  }).join('');
})();

// Trends
(function(){
  const t = D.trends || [];
  if (!t.length) { document.getElementById('trends').innerHTML='<div class="empty">Run <code>/cc-retrospect trends --backfill</code></div>'; return; }
  document.getElementById('trends').innerHTML = `<table class="t-table">
    <tr><th>Week</th><th>Cost</th><th>Sess</th><th>Dur</th><th>Eff</th><th>Frust</th><th>Agents</th></tr>
    ${t.slice(-8).reverse().map(r=>`<tr><td>${r.week}</td><td>${fmtK(r.cost)}</td><td>${r.sessions}</td><td>${r.avg_duration}m</td><td>${r.model_efficiency}%</td><td>${r.frustrations}</td><td>${r.subagents}</td></tr>`).join('')}
  </table>`;
})();

// Frustrations
(function(){
  const w = {};
  D.sessions.forEach(s => { for (const [k,c] of Object.entries(s.frustration_words||{})) w[k]=(w[k]||0)+c; });
  const top = Object.entries(w).sort((a,b)=>b[1]-a[1]).slice(0,20);
  if (!top.length) { document.getElementById('frustrations').innerHTML='<div class="empty">No frustration signals</div>'; return; }
  document.getElementById('frustrations').innerHTML = top.map(([k,c])=>`<span class="frust-tag">${k}<span class="frust-cnt">${c}</span></span>`).join('');
})();
</script>
</body>
</html>"""
