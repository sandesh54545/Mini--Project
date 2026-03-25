/* ── State ─────────────────────────────────────────────────────────────────── */
let currentFile = null;
let analysisData = null;
let activeTab = 'missing';

/* ── DOM refs ───────────────────────────────────────────────────────────────── */
const dropZone    = document.getElementById('dropZone');
const fileInput   = document.getElementById('fileInput');
const fileSelected = document.getElementById('fileSelected');
const analyseBtn  = document.getElementById('analyseBtn');
const loaderWrap  = document.getElementById('loaderWrap');
const results     = document.getElementById('results');
const uploadSection = document.getElementById('uploadSection');
const downloadBtn = document.getElementById('downloadBtn');

/* ── File Handling ──────────────────────────────────────────────────────────── */
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault(); dropZone.classList.remove('drag-over');
  const f = e.dataTransfer.files[0];
  if (f && f.name.endsWith('.csv')) setFile(f);
  else alert('Please drop a CSV file.');
});

fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) setFile(fileInput.files[0]);
});

function setFile(f) {
  currentFile = f;
  fileSelected.textContent = `📄 ${f.name}  (${(f.size / 1024).toFixed(1)} KB)`;
  analyseBtn.disabled = false;
}

/* ── Analyse ─────────────────────────────────────────────────────────────────── */
analyseBtn.addEventListener('click', async () => {
  if (!currentFile) return;
  uploadSection.style.display = 'none';
  loaderWrap.style.display    = 'flex';
  results.style.display       = 'none';

  const fd = new FormData();
  fd.append('file', currentFile);

  try {
    const res  = await fetch('/api/analyse', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) { alert(data.detail || 'Error during analysis.'); reset(); return; }
    analysisData = data;
    renderResults(data);
  } catch (err) {
    alert('Network error: ' + err.message);
    reset();
  }
});

function reset() {
  loaderWrap.style.display    = 'none';
  uploadSection.style.display = 'flex';
}

/* ── Render Results ─────────────────────────────────────────────────────────── */
function renderResults(data) {
  loaderWrap.style.display = 'none';
  results.style.display    = 'block';

  renderScoreBanner(data);
  renderSummaryCards(data);
  renderTabs();
  renderTabContent(activeTab, data);
}

/* Score Banner */
function renderScoreBanner(data) {
  const qs     = data.quality_score;
  const circle = document.getElementById('scoreFill');
  const numEl  = document.getElementById('scoreNum');
  const circumference = 326.7;

  // Color map
  const colMap = { Excellent: '#00c853', Good: '#1e88e5', Fair: '#ff6d00', Poor: '#f44336' };
  const col = colMap[qs.rating] || '#00e5ff';
  circle.style.stroke = col;

  // Animate score
  let cur = 0;
  const target = qs.score;
  const step = () => {
    cur = Math.min(cur + 1.5, target);
    numEl.textContent = Math.round(cur);
    circle.style.strokeDashoffset = circumference - (circumference * cur / 100);
    if (cur < target) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);

  document.getElementById('scoreRating').textContent = qs.rating + ' Quality';
  document.getElementById('scoreRating').style.color = col;
  document.getElementById('scoreFile').textContent = `📄 ${currentFile.name}`;

  // Pills
  const pills = document.getElementById('scorePills');
  pills.innerHTML = '';
  const missing = data.missing_values.total_missing;
  const dups    = data.duplicates.total_duplicate_rows;
  const anom    = data.anomaly_detection.total_anomalies || 0;
  const pillData = [
    { label: `${missing} Missing`, cls: missing > 0 ? 'orange' : 'green' },
    { label: `${dups} Duplicates`, cls: dups > 0 ? 'red' : 'green' },
    { label: `${anom} Anomalies`, cls: anom > 0 ? 'red' : 'green' },
    { label: `${data.overview.total_rows} Rows`, cls: 'blue' },
  ];
  pillData.forEach(p => {
    const el = document.createElement('span');
    el.className = `pill ${p.cls}`;
    el.textContent = p.label;
    pills.appendChild(el);
  });
}

/* Summary Cards */
function renderSummaryCards(data) {
  const ov  = data.overview;
  const qs  = data.quality_score;
  const bd  = qs.breakdown;
  const grid = document.getElementById('summaryGrid');
  const cards = [
    { label: 'Total Rows',     value: ov.total_rows,                       sub: `${ov.total_columns} columns`,  color: '#1e88e5' },
    { label: 'Missing Values', value: data.missing_values.total_missing,   sub: `across ${Object.keys(data.missing_values.columns_with_missing).length} columns`, color: '#ff6d00' },
    { label: 'Duplicate Rows', value: data.duplicates.total_duplicate_rows, sub: `${data.duplicates.duplicate_percentage}% of dataset`, color: '#f44336' },
    { label: 'Anomalies',      value: data.anomaly_detection.total_anomalies || 0, sub: `${data.anomaly_detection.anomaly_percentage || 0}% of rows`, color: '#ab47bc' },
    { label: 'Quality Score',  value: qs.score + '/100',                   sub: qs.rating, color: '#00c853' },
    { label: 'Memory',         value: ov.memory_usage_kb + 'KB',           sub: 'dataset size', color: '#26a69a' },
  ];
  grid.innerHTML = cards.map(c => `
    <div class="summary-card" style="border-left-color:${c.color}">
      <span class="sc-label">${c.label}</span>
      <span class="sc-value" style="color:${c.color}">${c.value}</span>
      <span class="sc-sub">${c.sub}</span>
    </div>`).join('');
}

/* Tabs */
function renderTabs() {
  document.querySelectorAll('.tab').forEach(t => {
    t.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
      t.classList.add('active');
      activeTab = t.dataset.tab;
      renderTabContent(activeTab, analysisData);
    });
  });
}

function renderTabContent(tab, data) {
  const el = document.getElementById('tabContent');
  switch (tab) {
    case 'missing':         el.innerHTML = renderMissing(data);         break;
    case 'duplicates':      el.innerHTML = renderDuplicates(data);      break;
    case 'anomalies':       el.innerHTML = renderAnomalies(data);       break;
    case 'columns':         el.innerHTML = renderColumns(data);         break;
    case 'recommendations': el.innerHTML = renderRecommendations(data); break;
  }
}

/* ── Missing Values Tab ─────────────────────────────────────────────────────── */
function renderMissing(data) {
  const mv = data.missing_values;
  if (mv.total_missing === 0) return `<div class="section-card"><p class="empty">✅ No missing values found. Your dataset is clean on this dimension!</p></div>`;

  const cols = mv.columns_with_missing;
  const items = Object.entries(cols).map(([col, info]) => `
    <div class="mv-item">
      <h4>${col}</h4>
      <span class="mv-badge">${info.count} missing</span>
      <span class="mv-pct">${info.percentage}% of column</span>
      <div class="suggestions">
        ${info.suggestions.map(s => `<div class="suggestion-tip">${s}</div>`).join('')}
      </div>
    </div>`).join('');

  return `
    <div class="section-card">
      <div class="section-title">🔍 Missing Values — ${mv.total_missing} total across ${Object.keys(cols).length} columns</div>
      ${items}
    </div>`;
}

/* ── Duplicates Tab ─────────────────────────────────────────────────────────── */
function renderDuplicates(data) {
  const d = data.duplicates;
  const rows = d.sample_rows;
  let tableHtml = '';
  if (rows && rows.length > 0) {
    const cols = Object.keys(rows[0]);
    tableHtml = `
      <div class="section-title" style="margin-top:1.25rem">Sample Duplicate Rows</div>
      <div style="overflow-x:auto">
      <table class="data-table">
        <thead><tr>${cols.map(c => `<th>${c}</th>`).join('')}</tr></thead>
        <tbody>${rows.map(r => `<tr>${cols.map(c => `<td>${r[c] ?? ''}</td>`).join('')}</tr>`).join('')}</tbody>
      </table>
      </div>`;
  }

  return `
    <div class="section-card">
      <div class="section-title">🔁 Duplicate Records Analysis</div>
      <div class="dup-stat">
        <div>
          <div class="dup-num">${d.total_duplicate_rows}</div>
          <div class="dup-label">Duplicate Rows</div>
        </div>
        <div>
          <div class="dup-num" style="color:var(--orange)">${d.duplicate_percentage}%</div>
          <div class="dup-label">of Dataset</div>
        </div>
      </div>
      <div class="section-title">💡 Suggestions</div>
      <div class="suggestions">
        ${d.suggestions.map(s => `<div class="suggestion-tip">${s}</div>`).join('')}
      </div>
      ${tableHtml}
    </div>`;
}

/* ── Anomaly Detection Tab ──────────────────────────────────────────────────── */
function renderAnomalies(data) {
  const ad = data.anomaly_detection;
  if (!('total_anomalies' in ad)) {
    return `<div class="section-card"><p class="empty">ℹ️ ${ad.note || 'No anomaly data available.'}</p></div>`;
  }

  // Column outlier table
  let colTable = '';
  if (ad.column_outliers) {
    const rows = Object.entries(ad.column_outliers).map(([c, i]) => `
      <tr>
        <td>${c}</td>
        <td>${i.outlier_count}</td>
        <td>${i.lower_bound}</td>
        <td>${i.upper_bound}</td>
        <td>${i.sample_outlier_values.join(', ')}</td>
      </tr>`).join('');
    colTable = `
      <div class="section-title" style="margin-top:1.25rem">📊 Per-Column Outliers (IQR method)</div>
      <div style="overflow-x:auto">
      <table class="data-table">
        <thead><tr><th>Column</th><th>Outliers</th><th>Lower Bound</th><th>Upper Bound</th><th>Sample Values</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      </div>`;
  }

  // Sample anomaly rows
  let sampleHtml = '';
  if (ad.sample_anomalies && ad.sample_anomalies.length > 0) {
    const cols = Object.keys(ad.sample_anomalies[0]);
    sampleHtml = `
      <div class="section-title" style="margin-top:1.25rem">🚨 Sample Anomalous Rows (top 10)</div>
      <div style="overflow-x:auto">
      <table class="data-table">
        <thead><tr>${cols.map(c => `<th>${c}</th>`).join('')}</tr></thead>
        <tbody>${ad.sample_anomalies.map(r => `<tr>${cols.map(c => `<td>${r[c] ?? ''}</td>`).join('')}</tr>`).join('')}</tbody>
      </table>
      </div>`;
  }

  return `
    <div class="section-card">
      <div class="section-title">🤖 Anomaly Detection — Isolation Forest</div>
      <div class="anomaly-header">
        <div>
          <div class="anm-num" style="color:var(--red)">${ad.total_anomalies}</div>
          <div class="dup-label">Anomalous Records</div>
        </div>
        <div>
          <div class="anm-num" style="color:var(--orange)">${ad.anomaly_percentage}%</div>
          <div class="dup-label">of Rows</div>
        </div>
        <div>
          <div class="anm-num" style="color:var(--blue2)">${ad.numeric_columns_analysed.length}</div>
          <div class="dup-label">Numeric Columns Scanned</div>
        </div>
      </div>
      <div class="section-title">💡 Suggestions</div>
      <div class="suggestions">
        ${(ad.suggestions || []).map(s => `<div class="suggestion-tip">${s}</div>`).join('')}
      </div>
      ${colTable}
      ${sampleHtml}
    </div>`;
}

/* ── Column Stats Tab ───────────────────────────────────────────────────────── */
function renderColumns(data) {
  const skip = ['dtype'];
  const cards = Object.entries(data.column_stats).map(([col, info]) => {
    const rows = Object.entries(info)
      .filter(([k]) => !skip.includes(k))
      .map(([k, v]) => {
        const label = k.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        const val   = typeof v === 'object' ? JSON.stringify(v) : v ?? 'N/A';
        return `<div class="col-row"><span>${label}</span><span>${val}</span></div>`;
      }).join('');
    return `
      <div class="col-card">
        <h4>${col} <span style="font-size:.72rem;color:var(--muted)">(${info.dtype})</span></h4>
        ${rows}
      </div>`;
  }).join('');

  return `
    <div class="section-card">
      <div class="section-title">📋 Column-Level Statistics</div>
      <div class="col-grid">${cards}</div>
    </div>`;
}

/* ── Recommendations Tab ────────────────────────────────────────────────────── */
function renderRecommendations(data) {
  const items = data.recommendations.map(r => `
    <div class="rec-item">
      <span class="rec-priority ${r.priority}">${r.priority}</span>
      <div>
        <div class="rec-cat">${r.category}</div>
        <div class="rec-action">${r.action}</div>
      </div>
    </div>`).join('');

  return `
    <div class="section-card">
      <div class="section-title">🎯 Priority Recommendations</div>
      <div class="rec-list">${items}</div>
    </div>`;
}

/* ── Download ───────────────────────────────────────────────────────────────── */
downloadBtn.addEventListener('click', () => {
  if (!analysisData || !analysisData.report_id) {
    alert('Report not available. Please re-run the analysis.');
    return;
  }
  window.location.href = `/api/download/${analysisData.report_id}`;
});
