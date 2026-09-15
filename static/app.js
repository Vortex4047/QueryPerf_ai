/**
 * QueryPerf AI — Core Application Logic
 * High-Performance SQL Optimization & Benchmark Lab
 */

const $ = selector => document.querySelector(selector);
const $$ = selector => document.querySelectorAll(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[char]));

let editor = null;
let models = null;
let activeEditor = 'query';
let activeEngine = 'sqlite';
let currentAnalysisData = null;
let schemaWords = {};
let currentExplainerSteps = [];
let currentExplainerPersona = 'beginner';

// ================= PRESET SCENARIOS =================
const presets = {
  ecommerce: {
    schema: `CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    created_at DATETIME
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    order_date DATE NOT NULL,
    total_amount DECIMAL(10,2),
    status TEXT
);`,
    query: `SELECT * FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id WHERE strftime('%Y', o.order_date) = '2025' AND o.status LIKE '%DELIVERED%' ORDER BY o.total_amount DESC;`
  },
  subquery: {
    schema: `CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name TEXT, email TEXT);
CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER, order_date DATE, total_amount REAL, status TEXT);`,
    query: `SELECT c.customer_id, c.name, (SELECT COUNT(*) FROM orders o WHERE o.customer_id = c.customer_id) AS order_count FROM customers c WHERE c.customer_id IN (SELECT customer_id FROM orders WHERE total_amount > 100);`
  },
  wildcard: {
    schema: `CREATE TABLE products (product_id INTEGER PRIMARY KEY, title TEXT, category TEXT, price REAL);`,
    query: `SELECT * FROM products WHERE title LIKE '%phone%' OR category LIKE '%electronics%' ORDER BY price DESC;`
  }
};

// ================= ERROR & ALERT HELPERS =================
function showError(message) {
  const errBox = $('#error');
  const errMsg = $('#errorMsg');
  if (errMsg && errBox) {
    errMsg.textContent = message;
    errBox.classList.remove('hidden');
  }
}

function hideError() {
  const errBox = $('#error');
  if (errBox) errBox.classList.add('hidden');
}

// ================= EDITOR ACCESSORS =================
function valueFor(name) {
  if (editor && models && models[name]) {
    return models[name].getValue();
  }
  const el = $(`#${name === 'schema' ? 'ddl' : 'query'}`);
  return el ? el.value : '';
}

function setValue(name, value) {
  if (editor && models && models[name]) {
    models[name].setValue(value);
  } else {
    const el = $(`#${name === 'schema' ? 'ddl' : 'query'}`);
    if (el) el.value = value;
  }
}

function switchEditor(name) {
  activeEditor = name;
  $$('.editor-tab').forEach(btn => {
    const selected = btn.dataset.editorTab === name;
    btn.classList.toggle('bg-obsidian-800', selected);
    btn.classList.toggle('border-obsidian-border', selected);
    btn.classList.toggle('text-white', selected);
    btn.classList.toggle('font-semibold', selected);
    btn.classList.toggle('text-slate-400', !selected);
    btn.classList.toggle('font-medium', !selected);
    btn.classList.toggle('border-transparent', !selected);
  });
  if (editor && models) {
    editor.setModel(models[name]);
  } else {
    const qEl = $('#query');
    const ddlEl = $('#ddl');
    if (qEl) qEl.hidden = name !== 'query';
    if (ddlEl) ddlEl.hidden = name !== 'schema';
  }
}

// ================= MONACO EDITOR INITIALIZATION =================
function startMonaco() {
  if (!window.require || !window.require.config) return;
  window.require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.52.0/min/vs' } });
  window.require(['vs/editor/editor.main'], () => {
    try {
      models = {
        query: monaco.editor.createModel($('#query').value, 'sql'),
        schema: monaco.editor.createModel($('#ddl').value, 'sql'),
      };
      $('#query').hidden = true;
      $('#ddl').hidden = true;
      $('#editor').style.display = 'block';
      editor = monaco.editor.create($('#editor'), {
        model: models[activeEditor],
        theme: 'vs-dark',
        minimap: { enabled: false },
        fontSize: 13,
        automaticLayout: true,
        scrollBeyondLastLine: false,
        fontFamily: 'JetBrains Mono, monospace',
        lineNumbers: 'on',
        renderLineHighlight: 'all',
        padding: { top: 12, bottom: 12 }
      });
      monaco.languages.registerCompletionItemProvider('sql', {
        provideCompletionItems: () => ({
          suggestions: Object.entries(schemaWords).flatMap(([table, columns]) => [
            { label: table, kind: monaco.languages.CompletionItemKind.Struct, insertText: table, detail: 'Schema table' },
            ...columns.map(column => ({ label: column, kind: monaco.languages.CompletionItemKind.Field, insertText: column, detail: `${table} column` }))
          ])
        })
      });
    } catch (_) {}
  }, () => {});
}

// ================= UI EVENT BINDINGS =================

// Editor tab switching
$$('.editor-tab').forEach(btn => btn.addEventListener('click', () => switchEditor(btn.dataset.editorTab)));

// Preset loader
const sampleBtn = $('#sampleBtn');
if (sampleBtn) {
  sampleBtn.addEventListener('click', () => {
    const presetKey = $('#samplePreset').value;
    const p = presets[presetKey] || presets.ecommerce;
    setValue('schema', p.schema);
    setValue('query', p.query);
    hideError();
    refreshCompletions();
  });
}

// Engine switcher
$$('.engine-btn').forEach(btn => btn.addEventListener('click', () => {
  activeEngine = btn.dataset.engine;
  $$('.engine-btn').forEach(b => {
    const active = b === btn;
    b.classList.toggle('bg-emerald-600', active);
    b.classList.toggle('text-white', active);
    b.classList.toggle('font-semibold', active);
    b.classList.toggle('shadow-sm', active);
    b.classList.toggle('text-slate-400', !active);
  });
}));

// Output diagnostic tabs
$$('.tab-btn').forEach(btn => btn.addEventListener('click', () => {
  $$('.tab-btn').forEach(t => {
    const sel = t === btn;
    t.classList.toggle('bg-obsidian-800', sel);
    t.classList.toggle('border-obsidian-border', sel);
    t.classList.toggle('text-white', sel);
    t.classList.toggle('font-semibold', sel);
    t.classList.toggle('text-slate-400', !sel);
    t.classList.toggle('font-medium', !sel);
    t.classList.toggle('border-transparent', !sel);
  });
  $$('.tab-panel').forEach(panel => {
    panel.classList.toggle('hidden', panel.dataset.panel !== btn.dataset.tab);
  });
}));

// Button triggers
$('#analyzeBtn')?.addEventListener('click', analyze);
$('#historyBtn')?.addEventListener('click', openDashboard);
$('#dashboardBtn')?.addEventListener('click', openDashboard);
$('#nlSqlBtn')?.addEventListener('click', () => $('#copilotModal')?.classList.remove('hidden'));

// AI Copilot Action
$('#copilotSubmitBtn')?.addEventListener('click', async () => {
  const prompt = $('#copilotInput')?.value.trim();
  const ddl_schema = valueFor('schema').trim();
  if (!prompt) return;

  const copilotBtn = $('#copilotSubmitBtn');
  const copilotText = $('#copilotSubmitBtnText') || copilotBtn;
  copilotBtn.disabled = true;
  copilotText.textContent = 'Generating AST & SQL...';
  try {
    const resp = await fetch('/api/nl-to-sql', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, ddl_schema, engine: activeEngine })
    });
    if (!resp.ok) throw new Error('Copilot translation failed');
    const data = await resp.json();
    setValue('query', data.generated_sql);
    switchEditor('query');
    $('#copilotModal')?.classList.add('hidden');
    analyze();
  } catch (err) {
    alert(err.message || 'Error running copilot');
  } finally {
    copilotBtn.disabled = false;
    copilotText.textContent = 'Generate & Optimize';
  }
});

// Interactive What-If Simulator Quick Presets
$$('.preset-idx-btn').forEach(btn => btn.addEventListener('click', () => {
  const whatIfInput = $('#whatIfInput');
  if (whatIfInput) whatIfInput.value = btn.dataset.cmd;
  $('#whatIfSimBtn')?.click();
}));

// Interactive What-If Simulator Action
$('#whatIfSimBtn')?.addEventListener('click', async () => {
  const index_command = $('#whatIfInput')?.value.trim();
  const ddl_schema = valueFor('schema').trim();
  const query = valueFor('query').trim();
  if (!index_command) return;

  const simBtn = $('#whatIfSimBtn');
  const simText = $('#whatIfBtnText') || simBtn;
  simBtn.disabled = true;
  simText.textContent = 'Simulating in Savepoint...';
  try {
    const resp = await fetch('/api/what-if', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ddl_schema, query, index_command, engine: activeEngine })
    });
    const res = await resp.json();
    if (!resp.ok) throw new Error(res.detail || 'Simulation error');
    renderWhatIfResult(res);
  } catch (err) {
    alert(err.message || 'What-If simulation failed');
  } finally {
    simBtn.disabled = false;
    simText.textContent = 'Simulate Index';
  }
});

function renderWhatIfResult(data) {
  const card = $('#whatIfResultCard');
  if (!card) return;
  card.classList.remove('hidden');
  
  const badge = $('#whatIfVerdictBadge');
  badge.textContent = data.verdict;
  const isUseful = data.verdict === 'Useful';
  badge.className = `rounded px-2.5 py-0.5 text-xs font-bold font-mono ${
    isUseful ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' : 'bg-obsidian-800 text-slate-300 border border-obsidian-border'
  }`;
  
  $('#whatIfSpeedupBadge').textContent = `+${data.speedup_percent}% Measured Gain`;
  $('#whatIfTiming').textContent = `${data.before_ms.toFixed(3)} ms → ${data.after_ms.toFixed(3)} ms`;
  $('#whatIfExplanation').textContent = data.explanation;
  $('#whatIfPlanBefore').textContent = data.plan_before;
  $('#whatIfPlanAfter').textContent = data.plan_after;
}

// 25-Run Distribution Benchmark
$('#runDistributionBtn')?.addEventListener('click', async () => {
  const ddl_schema = valueFor('schema').trim();
  const query = valueFor('query').trim();
  const distBtn = $('#runDistributionBtn');
  distBtn.disabled = true;
  distBtn.textContent = 'Sampling 25 Iterations...';
  try {
    const resp = await fetch('/api/benchmark-distribution', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ddl_schema, query, iterations: 25 })
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'Failed distribution benchmark');
    renderDistribution(data);
  } catch (err) {
    alert(err.message);
  } finally {
    distBtn.disabled = false;
    distBtn.textContent = 'Run 25-Iteration Distribution';
  }
});

function renderDistribution(data) {
  $('#distributionContainer')?.classList.remove('hidden');
  $('#distMedianBadge').textContent = `Median: ${data.median_ms.toFixed(3)} ms · P95: ${data.p95_ms.toFixed(3)} ms`;
  $('#distHistogram').innerHTML = data.distribution_buckets.map(b => `
    <div class="flex items-center gap-3 text-[11px] font-mono">
      <span class="w-36 text-slate-300 truncate">${esc(b.range_label)}</span>
      <div class="flex-1 bg-obsidian-950 h-3 rounded-full overflow-hidden border border-obsidian-border">
        <div class="bg-gradient-to-r from-emerald-500 to-cyan-400 h-full rounded-full transition-all duration-300" style="width: ${Math.max(b.percentage, 4)}%"></div>
      </div>
      <span class="w-16 text-right font-bold text-slate-200">${b.count} (${b.percentage}%)</span>
    </div>
  `).join('');
}

// Export JSON
$('#exportJsonBtn')?.addEventListener('click', () => {
  if (!currentAnalysisData) return alert('Run an analysis first to export results.');
  const blob = new Blob([JSON.stringify(currentAnalysisData, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `queryperf_analysis_${currentAnalysisData.query_fingerprint}.json`;
  a.click();
  URL.revokeObjectURL(url);
});

// Refresh schema completions
async function refreshCompletions() {
  try {
    const resp = await fetch('/api/schema-completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ddl_schema: valueFor('schema'), slow_query: 'SELECT 1;', engine: activeEngine })
    });
    if (resp.ok) schemaWords = (await resp.json()).tables;
  } catch (_) {}
}

// ================= CORE ANALYSIS FUNCTION =================
async function analyze() {
  hideError();
  const ddl_schema = valueFor('schema').trim();
  const slow_query = valueFor('query').trim();
  if (!ddl_schema || !slow_query) return showError('Please supply both schema DDL and a read-only SQL query.');

  const analyzeBtn = $('#analyzeBtn');
  if (analyzeBtn) analyzeBtn.disabled = true;
  $('#analyzeSpinner')?.classList.remove('hidden');
  const btnText = $('#buttonText');
  if (btnText) btnText.textContent = 'Benchmarking Local Sandbox…';
  
  $('#empty')?.classList.add('hidden');
  $('#output')?.classList.add('hidden');
  $('#skeleton')?.classList.remove('hidden');

  try {
    await refreshCompletions();
    const resp = await fetch('/api/optimize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ddl_schema, slow_query, engine: activeEngine })
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || `Analysis failed (${resp.status})`);
    currentAnalysisData = data;
    renderAnalysis(data);
    $('#output')?.classList.remove('hidden');
  } catch (err) {
    showError(err.message || 'Service request error');
    if (!currentAnalysisData) $('#empty')?.classList.remove('hidden');
    else $('#output')?.classList.remove('hidden');
  } finally {
    if (analyzeBtn) analyzeBtn.disabled = false;
    $('#analyzeSpinner')?.classList.add('hidden');
    if (btnText) btnText.textContent = 'Optimize & Benchmark Query';
    $('#skeleton')?.classList.add('hidden');
  }
}

// ================= VISUAL EXECUTION PLAN TREE RENDERER =================
function renderPlanTree(node, containerId, isOriginal) {
  const container = $(`#${containerId}`);
  if (!container || !node) return;
  container.innerHTML = '';

  function createNodeEl(n, depth = 0) {
    const div = document.createElement('div');
    div.className = `p-3 rounded-xl border transition-all cursor-pointer select-none ${depth > 0 ? 'ml-3' : ''}`;

    let borderClass = 'border-obsidian-border bg-obsidian-850 hover:border-slate-500';
    let badgeClass = 'bg-obsidian-800 text-slate-300';
    let costBarWidth = '15%';
    let costBarColor = 'bg-emerald-500';

    if (n.cost_level === 'critical' || n.operation_type === 'scan') {
      borderClass = 'border-rose-500/40 bg-rose-950/20 hover:border-rose-400 text-rose-100 shadow-sm shadow-rose-950/40';
      badgeClass = 'bg-rose-500/20 text-rose-300 border border-rose-500/30';
      costBarWidth = '95%';
      costBarColor = 'bg-rose-500';
    } else if (n.cost_level === 'optimal' || n.operation_type === 'search') {
      borderClass = 'border-emerald-500/40 bg-emerald-950/20 hover:border-emerald-400 text-emerald-100 shadow-sm shadow-emerald-950/40';
      badgeClass = 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
      costBarWidth = '12%';
      costBarColor = 'bg-emerald-400';
    } else if (n.cost_level === 'warning' || n.operation_type === 'temp_btree' || n.operation_type === 'sort') {
      borderClass = 'border-amber-500/40 bg-amber-950/20 hover:border-amber-400 text-amber-100 shadow-sm shadow-amber-950/40';
      badgeClass = 'bg-amber-500/20 text-amber-300 border border-amber-500/30';
      costBarWidth = '65%';
      costBarColor = 'bg-amber-400';
    }

    div.className += ` ${borderClass}`;
    div.innerHTML = `
      <div class="flex items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <span class="rounded px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider font-mono ${badgeClass}">${esc(n.operation_type)}</span>
          <span class="font-mono text-xs font-bold text-white">${esc(n.name)}</span>
        </div>
        <span class="text-[10px] text-slate-400 font-mono font-semibold">~${n.rows_est} rows</span>
      </div>
      <p class="text-[11px] text-slate-300 mt-1.5 line-clamp-1">${esc(n.detail)}</p>
      <div class="mt-2 flex items-center gap-2">
        <div class="flex-1 bg-obsidian-950 h-1.5 rounded-full overflow-hidden">
          <div class="${costBarColor} h-full rounded-full" style="width: ${costBarWidth}"></div>
        </div>
        <span class="text-[9px] font-mono text-slate-400">${n.cost_level.toUpperCase()}</span>
      </div>
    `;

    div.addEventListener('click', (e) => {
      e.stopPropagation();
      inspectPlanNode(n);
    });

    if (n.children && n.children.length > 0) {
      const childWrap = document.createElement('div');
      childWrap.className = 'mt-2 space-y-2 border-l-2 border-obsidian-border pl-2.5';
      n.children.forEach(c => childWrap.appendChild(createNodeEl(c, depth + 1)));
      div.appendChild(childWrap);
    }
    return div;
  }

  container.appendChild(createNodeEl(node));
}

function inspectPlanNode(node) {
  const inspector = $('#nodeInspector');
  if (!inspector) return;
  inspector.classList.remove('hidden');
  $('#nodeTitle').textContent = node.name;
  $('#nodeExplanation').textContent = node.explanation || node.detail;
  $('#nodeTarget').textContent = `Target Relation: ${node.table || 'Subquery Derived Table'}`;
  $('#nodeIndex').textContent = `Index Used: ${node.index_name || 'None (Full Sequential Scan)'}`;

  const badge = $('#nodeBadge');
  badge.textContent = node.operation_type.toUpperCase();
  if (node.cost_level === 'critical') {
    badge.className = 'rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-rose-500/20 text-rose-300 border border-rose-500/30 font-mono';
  } else if (node.cost_level === 'optimal') {
    badge.className = 'rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-mono';
  } else {
    badge.className = 'rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-amber-500/20 text-amber-300 border border-amber-500/30 font-mono';
  }
}

// ================= RENDER COMPLETE ANALYSIS =================
function renderAnalysis(data) {
  $('#output')?.classList.remove('hidden');
  $('#engine').textContent = `${data.analysis_engine} · Engine: ${data.engine.toUpperCase()}`;

  // Top 4 KPI metrics
  $('#originalMs').textContent = `${data.original_ms.toFixed(3)} ms`;
  $('#optimizedMs').textContent = `${data.optimized_ms.toFixed(3)} ms`;
  $('#speedup').textContent = data.speedup_factor;
  $('#fingerprint').textContent = `#${data.query_fingerprint}`;
  $('#originalMetric').textContent = `CPU ${data.original_metrics.cpu_ms.toFixed(2)} ms · ~${data.original_metrics.estimated_io_reads} reads`;
  $('#optimizedMetric').textContent = `CPU ${data.optimized_metrics.cpu_ms.toFixed(2)} ms · ~${data.optimized_metrics.estimated_io_reads} reads`;

  // Confidence Score
  $('#confidenceScore').textContent = data.confidence_breakdown.score;
  $('#confidenceLevel').textContent = `${data.confidence_breakdown.level} CONFIDENCE`;
  $('#confidenceCheckBadge').textContent = `${data.confidence_breakdown.score}/100`;

  // Regression Alert
  if (data.regression_alert && data.regression_alert.is_regression) {
    $('#regressionBanner')?.classList.remove('hidden');
    $('#regressionText').textContent = `${data.regression_alert.previous_ms.toFixed(3)} ms → ${data.regression_alert.current_ms.toFixed(3)} ms (+${data.regression_alert.regression_percent}%). ${data.regression_alert.likely_cause}`;
  } else {
    $('#regressionBanner')?.classList.add('hidden');
  }

  // Cardinality Prediction
  if (data.performance_prediction) {
    const p = data.performance_prediction;
    $('#predRiskBadge').textContent = `${p.risk_level} RISK`;
    $('#predRiskBadge').className = `rounded px-1.5 py-0.5 text-[9px] font-mono font-bold uppercase ${
      p.risk_level === 'HIGH' ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30' :
      (p.risk_level === 'MEDIUM' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30' : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30')
    }`;
    $('#predAccuracyBadge').textContent = `${p.accuracy_percent}% Accuracy`;
    $('#predLatency').textContent = `~${p.predicted_min_ms.toFixed(2)} - ${p.predicted_max_ms.toFixed(2)} ms`;
    $('#actualLatency').textContent = `${data.original_ms.toFixed(3)} ms`;
    $('#predRows').textContent = `~${p.predicted_rows.toLocaleString()} rows`;
    $('#predBottleneck').textContent = p.predicted_bottleneck;
  }

  // Learned Query Optimizer
  if (data.learned_optimization) {
    const lo = data.learned_optimization;
    $('#learnedConfidence').textContent = `${lo.confidence_score}% Confidence`;
    $('#learnedPattern').textContent = lo.matched_historical_pattern;
    $('#learnedStrategy').textContent = lo.recommended_strategy;
    $('#learnedCount').textContent = `${lo.precedent_count} runs`;
    $('#learnedAvgSpeedup').textContent = `${lo.historical_speedup_avg.toFixed(1)}% avg`;
  }

  // Plan Heatmap
  if (data.plan_heatmap && data.plan_heatmap.length) {
    $('#heatmapBar').innerHTML = data.plan_heatmap.map(item => `
      <div class="${item.color_class} h-full transition-all duration-500" style="width: ${Math.max(item.percentage, 4)}%" title="${esc(item.operator)} (${item.percentage}%)"></div>
    `).join('');
    $('#heatmapLegend').innerHTML = data.plan_heatmap.map(item => `
      <span class="flex items-center gap-1.5">
        <span class="h-2 w-2 rounded-full ${item.color_class}"></span>
        <span>${esc(item.table)}: <b class="text-slate-200">${item.percentage}%</b> (${esc(item.operator)})</span>
      </span>
    `).join('');
  }

  // Root-Cause Causal Diagnostic Tree
  if (data.root_cause_tree) {
    renderRootCauseTree(data.root_cause_tree);
  }

  // Controlled Scientific Experiment
  if (data.scientific_experiment) {
    const exp = data.scientific_experiment;
    $('#expPValBadge').textContent = exp.p_value_text;
    $('#expHypothesis').textContent = exp.hypothesis;
    $('#expControlMean').textContent = `${exp.control_mean_ms.toFixed(2)} ms`;
    $('#expControlStd').textContent = `Std Dev: ±${exp.control_std_dev.toFixed(2)} ms`;
    $('#expTreatmentMean').textContent = `${exp.treatment_mean_ms.toFixed(2)} ms`;
    $('#expTreatmentStd').textContent = `Std Dev: ±${exp.treatment_std_dev.toFixed(2)} ms`;
    $('#expConclusion').textContent = exp.conclusion;
  }

  // Performance Cliff
  if (data.performance_cliff) {
    renderPerformanceCliff(data.performance_cliff);
  }

  // Decision Tree
  if (data.decision_tree) {
    renderDecisionTree(data.decision_tree);
  }

  // Dual-Persona Explainer
  currentExplainerSteps = data.dual_persona_explainer || [];

  // Battle Arena Setup
  initBattleArena(data);

  // 1. Visual Execution Plan Trees
  renderPlanTree(data.visual_plan_original, 'visualPlanOriginal', true);
  renderPlanTree(data.visual_plan_optimized, 'visualPlanOptimized', false);
  $('#rawOriginalPlan').textContent = data.original_execution_plan;
  $('#rawOptimizedPlan').textContent = data.optimized_execution_plan;

  // 2. Anti-Pattern Scanner
  $('#antiPatternCount').textContent = data.detected_anti_patterns.length;
  $('#antiPatternsList').innerHTML = data.detected_anti_patterns.length ? data.detected_anti_patterns.map(ap => {
    let sevBadge = 'bg-amber-500/20 text-amber-300 border-amber-500/30';
    if (ap.severity === 'CRITICAL') sevBadge = 'bg-rose-500/20 text-rose-300 border-rose-500/30';
    if (ap.severity === 'LOW') sevBadge = 'bg-obsidian-800 text-slate-300 border-obsidian-border';

    return `
      <div class="rounded-xl border border-obsidian-border bg-obsidian-850 p-4 space-y-2.5 shadow-md">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider font-mono border ${sevBadge}">${esc(ap.severity)}</span>
            <h5 class="text-xs font-bold text-white font-mono">${esc(ap.pattern_name)}</h5>
          </div>
          <span class="text-[10px] uppercase font-bold text-slate-400 font-mono">Impact: ${esc(ap.estimated_impact)}</span>
        </div>
        <p class="text-xs text-slate-300 leading-relaxed"><b class="text-slate-200">Why it's expensive:</b> ${esc(ap.why)}</p>
        <div class="rounded-lg bg-obsidian-950 p-3 text-xs border border-obsidian-border font-mono text-emerald-300 flex items-center justify-between gap-2">
          <div>
            <span class="text-[10px] font-bold uppercase text-slate-400 block mb-0.5 font-sans">Suggested Rewrite:</span>
            <span>${esc(ap.suggested_rewrite)}</span>
          </div>
          <button type="button" class="btn-tactile text-[11px] font-sans text-emerald-400 hover:text-white px-2.5 py-1 rounded bg-obsidian-850 border border-obsidian-border shrink-0" onclick="navigator.clipboard.writeText(${JSON.stringify(ap.suggested_rewrite)})">Copy</button>
        </div>
      </div>
    `;
  }).join('') : '<div class="p-6 text-center text-xs text-slate-400 bg-obsidian-900 rounded-xl border border-obsidian-border">✓ No strict SQL anti-pattern violations detected. Query follows best practices!</div>';

  // 3. Query Rewrite Playground
  $('#rewriteCandidatesGrid').innerHTML = data.rewrite_candidates.map(c => `
    <div class="rounded-xl border ${c.is_best ? 'border-emerald-500/60 bg-emerald-950/20 ring-1 ring-emerald-500/30' : 'border-obsidian-border bg-obsidian-850'} p-4 flex flex-col justify-between shadow-lg">
      <div>
        <div class="flex items-center justify-between mb-2">
          <span class="text-[10px] font-mono text-slate-400 uppercase tracking-wide">${esc(c.strategy)}</span>
          ${c.is_best ? '<span class="rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 px-2 py-0.5 text-[10px] font-bold font-mono">🏆 FASTEST REWRITE</span>' : ''}
        </div>
        <h5 class="text-xs font-bold text-white mb-2">${esc(c.title)}</h5>
        <pre class="rounded-lg bg-obsidian-950 p-3 text-[11px] font-mono text-emerald-200 overflow-x-auto border border-obsidian-border max-h-40 leading-relaxed">${esc(c.query)}</pre>
      </div>
      <div class="mt-3 pt-2.5 border-t border-obsidian-border flex items-center justify-between text-xs font-mono">
        <span class="${c.is_best ? 'text-emerald-300 font-bold' : 'text-slate-300'}">${c.execution_ms.toFixed(3)} ms (+${c.speedup_percent}%)</span>
        <button type="button" class="btn-tactile rounded-lg bg-emerald-600/90 hover:bg-emerald-500 px-2.5 py-1 text-[11px] text-white transition font-sans font-semibold" onclick="loadCandidateQuery(${JSON.stringify(c.query)})">Apply</button>
      </div>
    </div>
  `).join('');

  // 4. Advanced Index Advisor
  $('#indexAdvisorList').innerHTML = data.index_advisor.length ? data.index_advisor.map((idx, i) => `
    <div class="rounded-xl border border-obsidian-border bg-obsidian-850 p-4 space-y-3 shadow-lg">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <span class="rounded-md bg-emerald-500/20 border border-emerald-500/30 px-2 py-0.5 text-xs font-bold text-emerald-300 font-mono">#${i + 1}</span>
          <code class="text-xs font-bold text-white break-all">${esc(idx.index_name)}</code>
          <span class="text-xs text-amber-300 font-bold font-mono">⭐ ${idx.star_rating}/100</span>
        </div>
        <span class="text-xs font-mono font-bold text-emerald-400">+${idx.estimated_benefit_percent}% Benefit</span>
      </div>
      <pre class="rounded-lg bg-obsidian-950 p-2.5 text-xs font-mono text-cyan-200 border border-obsidian-border">${esc(idx.command)}</pre>
      <div class="grid md:grid-cols-2 gap-3 text-xs">
        <div class="rounded-lg bg-emerald-950/20 border border-emerald-500/20 p-3 text-emerald-200 space-y-1">
          <b class="text-[10px] uppercase font-bold text-emerald-400 block font-mono">Trade-Off Advantages (+):</b>
          ${idx.tradeoffs_pros.map(p => `<div>+ ${esc(p)}</div>`).join('')}
        </div>
        <div class="rounded-lg bg-rose-950/20 border border-rose-500/20 p-3 text-rose-200 space-y-1">
          <b class="text-[10px] uppercase font-bold text-rose-400 block font-mono">Trade-Off Costs (−):</b>
          ${idx.tradeoffs_cons.map(c => `<div>− ${esc(c)}</div>`).join('')}
        </div>
      </div>
    </div>
  `).join('') : '<p class="text-xs text-slate-400 p-4">No additional index recommendations required for this query.</p>';

  // 5. Benchmark Comparison Bars
  const origMs = Math.max(data.original_ms, 0.01);
  const optMs = Math.max(data.optimized_ms, 0.01);
  const totalMs = origMs + optMs;
  $('#barOrigMs').textContent = `${origMs.toFixed(3)} ms`;
  $('#barOptMs').textContent = `${optMs.toFixed(3)} ms`;
  $('#barOrigWidth').style.width = `${(origMs / totalMs) * 100}%`;
  $('#barOptWidth').style.width = `${(optMs / totalMs) * 100}%`;

  const origCpu = Math.max(data.original_metrics.cpu_ms, 0.01);
  const optCpu = Math.max(data.optimized_metrics.cpu_ms, 0.01);
  const totalCpu = origCpu + optCpu;
  $('#barOrigCpu').textContent = `${origCpu.toFixed(3)} ms`;
  $('#barOptCpu').textContent = `${optCpu.toFixed(3)} ms`;
  $('#barOrigCpuWidth').style.width = `${(origCpu / totalCpu) * 100}%`;
  $('#barOptCpuWidth').style.width = `${(optCpu / totalCpu) * 100}%`;

  const origIo = Math.max(data.original_metrics.estimated_io_reads, 1);
  const optIo = Math.max(data.optimized_metrics.estimated_io_reads, 1);
  const totalIo = origIo + optIo;
  $('#barOrigIo').textContent = `${origIo}`;
  $('#barOptIo').textContent = `${optIo}`;
  $('#barOrigIoWidth').style.width = `${(origIo / totalIo) * 100}%`;
  $('#barOptIoWidth').style.width = `${(optIo / totalIo) * 100}%`;

  // 6. Query Complexity
  $('#complexityJoins').textContent = data.complexity_analysis.join_count;
  $('#complexitySubqueries').textContent = data.complexity_analysis.subquery_count;
  $('#complexityAggs').textContent = data.complexity_analysis.aggregation_count;
  $('#complexitySorts').textContent = data.complexity_analysis.sort_count;
  $('#complexityFilters').textContent = data.complexity_analysis.filter_count;
  $('#complexityDominant').textContent = data.complexity_analysis.dominant_cost_factor;
  $('#complexityExplanation').textContent = data.complexity_analysis.explanation;

  const riskBadge = $('#complexityRiskBadge');
  riskBadge.textContent = `${data.complexity_analysis.risk_level} RISK`;
  riskBadge.className = `rounded px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider font-mono ${
    data.complexity_analysis.risk_level === 'HIGH' ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30' :
    data.complexity_analysis.risk_level === 'MEDIUM' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30' :
    'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
  }`;

  // Confidence Score Checklist
  $('#confidenceChecklist').innerHTML = data.confidence_breakdown.checklist.map(item => `
    <li class="flex items-start gap-2.5 p-1.5 rounded-lg hover:bg-obsidian-850 transition">
      <span class="text-xs mt-0.5 font-bold ${item.passed ? 'text-emerald-400' : 'text-rose-400'}">${item.passed ? '✓' : '✗'}</span>
      <div class="flex-1">
        <span class="${item.passed ? 'text-slate-200' : 'text-slate-400'}">${esc(item.label)}</span>
        <span class="text-[10px] font-mono font-bold ${item.passed ? 'text-emerald-400' : 'text-slate-500'} ml-1">(${item.impact})</span>
      </div>
    </li>
  `).join('');
  $('#confidencePenalties').innerHTML = data.confidence_breakdown.penalties.map(p => `<div>⚠ ${esc(p)}</div>`).join('');

  // Diagnosis & Takeaway
  $('#diagnosis').textContent = data.bottleneck_analysis;
  $('#takeaway').textContent = data.key_takeaway;

  // Data Preview Table
  const tableHead = $('#previewTable thead');
  const tableBody = $('#previewTable tbody');
  tableHead.innerHTML = `<tr>${data.optimized_preview.columns.map(c => `<th class="px-3.5 py-2 text-[11px] font-bold uppercase tracking-wider font-mono">${esc(c)}</th>`).join('')}</tr>`;
  tableBody.innerHTML = data.optimized_preview.rows.map(row => `
    <tr>${row.map(val => `<td class="px-3.5 py-2 text-slate-300 font-mono">${esc(val)}</td>`).join('')}</tr>
  `).join('');

  // Deployable Migrations
  $('#migrations').innerHTML = data.migrations.map(m => `
    <details class="rounded-xl border border-obsidian-border bg-obsidian-850 p-3.5">
      <summary class="cursor-pointer text-xs font-bold text-slate-300 hover:text-white flex items-center justify-between">
        <span class="font-mono text-emerald-400">${esc(m.name)}</span>
        <span class="text-[10px] font-mono text-slate-400">Expand Up/Down SQL</span>
      </summary>
      <div class="mt-3 space-y-2.5">
        <div class="flex justify-between items-center text-[10px] uppercase font-bold text-emerald-400 font-mono">
          <span>Forward Migration (UP)</span>
          <button type="button" class="underline text-slate-400 hover:text-white font-sans" onclick="navigator.clipboard.writeText(${JSON.stringify(m.up_sql)})">Copy UP</button>
        </div>
        <pre class="rounded-lg bg-obsidian-950 p-2.5 text-xs font-mono text-emerald-200 border border-obsidian-border">${esc(m.up_sql)}</pre>
        <div class="flex justify-between items-center text-[10px] uppercase font-bold text-rose-400 pt-1 font-mono">
          <span>Rollback Migration (DOWN)</span>
          <button type="button" class="underline text-slate-400 hover:text-white font-sans" onclick="navigator.clipboard.writeText(${JSON.stringify(m.down_sql)})">Copy DOWN</button>
        </div>
        <pre class="rounded-lg bg-obsidian-950 p-2.5 text-xs font-mono text-rose-200 border border-obsidian-border">${esc(m.down_sql)}</pre>
      </div>
    </details>
  `).join('');
}

window.loadCandidateQuery = function(sql) {
  setValue('query', sql);
  switchEditor('query');
  analyze();
};

// ================= HISTORICAL METRICS DASHBOARD =================
async function openDashboard() {
  $('#dashboardModal')?.classList.remove('hidden');
  try {
    const resp = await fetch('/api/dashboard');
    if (!resp.ok) return;
    const d = await resp.json();
    $('#dashTotalQueries').textContent = d.total_queries_analyzed;
    $('#dashAvgSpeedup').textContent = `${d.average_speedup_percent}%`;
    $('#dashRegressions').textContent = d.total_regressions_detected;
    $('#dashIndexes').textContent = d.total_indexes_recommended;

    $('#dashAntiPatternList').innerHTML = Object.entries(d.antipattern_distribution).map(([name, count]) => `
      <div class="flex items-center justify-between p-2.5 rounded-xl bg-obsidian-950 border border-obsidian-border">
        <span class="text-slate-300 font-medium">${esc(name)}</span>
        <span class="font-mono font-bold text-amber-300 text-xs">${count} occurrences</span>
      </div>
    `).join('');

    $('#dashSlowQueriesList').innerHTML = d.top_slow_queries.map(q => `
      <div class="p-3 rounded-xl bg-obsidian-950 border border-obsidian-border flex justify-between items-center">
        <div>
          <code class="text-cyan-300 font-mono text-xs font-bold">#${esc(q.fingerprint)}</code>
          <p class="text-[11px] text-slate-400 mt-0.5 font-mono truncate max-w-sm">${esc(q.query)}</p>
        </div>
        <div class="text-right font-mono">
          <b class="text-rose-400 text-xs block">${q.ms.toFixed(3)} ms</b>
          <span class="text-[10px] text-emerald-400 font-bold">${esc(q.speedup)}</span>
        </div>
      </div>
    `).join('');
  } catch (_) {}
}

// ================= RESIZABLE WORKSPACE DIVIDER =================
const divider = $('#divider');
const workspace = $('#workspace');
if (divider && workspace) {
  divider.addEventListener('pointerdown', event => {
    divider.setPointerCapture(event.pointerId);
    const start = event.clientX;
    const left = workspace.children[0].getBoundingClientRect().width;
    divider.onpointermove = move => {
      workspace.style.gridTemplateColumns = `${Math.max(380, left + move.clientX - start)}px 6px minmax(460px, 1.35fr)`;
    };
    divider.onpointerup = () => { divider.onpointermove = null; };
  });
}

// ================= ROOT-CAUSE CAUSAL DIAGNOSTIC TREE =================
function renderRootCauseTree(node) {
  const container = $('#rootCauseTreeContainer');
  if (!container || !node) return;

  function buildLevelHtml(n) {
    let colorClass = 'border-rose-500/40 bg-rose-950/20 text-rose-300';
    let badgeText = 'SYMPTOM';
    if (n.category === 'operator') {
      colorClass = 'border-amber-500/40 bg-amber-950/20 text-amber-300';
      badgeText = 'OPERATOR';
    } else if (n.category === 'planner') {
      colorClass = 'border-cyan-500/40 bg-cyan-950/20 text-cyan-300';
      badgeText = 'PLANNER CHOICE';
    } else if (n.category === 'smell') {
      colorClass = 'border-indigo-500/40 bg-indigo-950/20 text-indigo-300';
      badgeText = 'CODE SMELL';
    } else if (n.category === 'remediation') {
      colorClass = 'border-emerald-500/40 bg-emerald-950/20 text-emerald-300';
      badgeText = 'REMEDIATION FIX';
    }

    let snippetHtml = '';
    if (n.code_snippet) {
      snippetHtml = `
        <div class="mt-2 flex items-center justify-between bg-obsidian-950 p-2 rounded-lg border border-obsidian-border">
          <code class="text-xs font-mono text-slate-200 truncate">${esc(n.code_snippet)}</code>
          <button type="button" class="text-[10px] font-sans text-emerald-400 hover:text-white px-2 py-0.5 rounded bg-obsidian-850 border border-obsidian-border shrink-0 ml-2" onclick="navigator.clipboard.writeText(${JSON.stringify(n.code_snippet)})">Copy</button>
        </div>
      `;
    }

    let childrenHtml = '';
    if (n.children && n.children.length) {
      childrenHtml = `
        <div class="mt-3 pl-4 border-l-2 border-dashed border-obsidian-border space-y-3">
          ${n.children.map(ch => buildLevelHtml(ch)).join('')}
        </div>
      `;
    }

    return `
      <div class="p-3.5 rounded-xl border ${colorClass} shadow-sm space-y-1.5">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="rounded px-2 py-0.5 text-[9px] font-mono font-bold uppercase tracking-wider bg-black/40 border border-white/10">${badgeText}</span>
            <h5 class="text-xs font-bold text-white font-mono">${esc(n.title)}</h5>
          </div>
          <span class="text-[10px] font-mono text-slate-400">${esc(n.metric_impact || '')}</span>
        </div>
        <p class="text-xs text-slate-300 leading-relaxed">${esc(n.description)}</p>
        ${snippetHtml}
        ${childrenHtml}
      </div>
    `;
  }

  container.innerHTML = buildLevelHtml(node);
}

// ================= PERFORMANCE CLIFF SCALING CHART =================
function renderPerformanceCliff(cliff) {
  const container = $('#cliffChartContainer');
  if (!container || !cliff) return;

  $('#cliffTypeBadge').textContent = `${cliff.curve_type.toUpperCase()} SCALING`;
  $('#cliffExplanation').textContent = cliff.explanation;

  const maxMs = Math.max(...cliff.data_points.map(d => Math.max(d.unindexed_ms, d.indexed_ms)), 0.1);

  container.innerHTML = `
    <div class="space-y-3">
      ${cliff.data_points.map(dp => {
        const unindexedPct = Math.min(100, Math.max(8, (dp.unindexed_ms / maxMs) * 100));
        const indexedPct = Math.min(100, Math.max(4, (dp.indexed_ms / maxMs) * 100));
        const isCliff = cliff.cliff_detected && dp.rows === cliff.cliff_threshold_rows;

        return `
          <div class="p-3 rounded-xl bg-obsidian-950 border ${isCliff ? 'border-rose-500/50 shadow-sm shadow-rose-950/50' : 'border-obsidian-border'} space-y-1.5">
            <div class="flex items-center justify-between text-xs font-mono">
              <span class="font-bold text-white flex items-center gap-2">
                ${dp.rows.toLocaleString()} Rows
                ${isCliff ? '<span class="text-[9px] bg-rose-500/20 text-rose-300 border border-rose-500/30 px-1.5 py-0.5 rounded font-sans uppercase">Cliff Point Detected</span>' : ''}
              </span>
              <span class="text-slate-400">Unindexed: <b class="text-rose-400">${dp.unindexed_ms} ms</b> | Indexed: <b class="text-emerald-400">${dp.indexed_ms} ms</b></span>
            </div>
            <div class="space-y-1">
              <div class="h-2 rounded-full bg-rose-500/80 transition-all duration-500" style="width: ${unindexedPct}%"></div>
              <div class="h-2 rounded-full bg-emerald-500/80 transition-all duration-500" style="width: ${indexedPct}%"></div>
            </div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

// ================= DECISION TREE FLOWCHART =================
function renderDecisionTree(nodes) {
  const container = $('#decisionTreeList');
  if (!container || !nodes) return;

  container.innerHTML = nodes.map((n, i) => `
    <div class="p-3.5 rounded-xl border border-obsidian-border bg-obsidian-950 flex gap-3 items-start">
      <div class="grid h-6 w-6 shrink-0 place-items-center rounded-full ${n.condition_met ? 'bg-emerald-600 text-white' : 'bg-obsidian-800 text-slate-400'} text-xs font-bold font-mono">
        ${i + 1}
      </div>
      <div class="flex-1 space-y-1">
        <div class="flex items-center justify-between">
          <h5 class="text-xs font-bold text-white font-mono">${esc(n.question)}</h5>
          <span class="text-[10px] font-mono px-2 py-0.5 rounded ${n.condition_met ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'}">${esc(n.answer)}</span>
        </div>
        <p class="text-xs text-slate-300 font-sans">Prescription: <b class="text-cyan-300">${esc(n.action_taken)}</b></p>
      </div>
    </div>
  `).join('');
}

// ================= BATTLE ARENA TOURNAMENT =================
function initBattleArena(data) {
  $('#battleWinnerBadge').textContent = 'Ready for Battle';
  $('#battleHumanInput').value = '';
  const initialContenders = [
    {
      name: 'Original Query',
      type: 'original',
      execution_ms: data.original_ms,
      speedup_percent: 0.0,
      is_winner: false,
      rank: 2,
      summary: 'Baseline unoptimized query'
    },
    {
      name: 'AI Best Rewrite',
      type: 'ai_rewrite',
      execution_ms: data.optimized_ms,
      speedup_percent: data.original_ms > 0
        ? Number((((data.original_ms - data.optimized_ms) / data.original_ms) * 100).toFixed(1))
        : 0.0,
      is_winner: true,
      rank: 1,
      summary: 'SARGable predicates & index-friendly syntax'
    }
  ];
  renderBattleResults({
    participants: initialContenders,
    winner_name: 'AI Best Rewrite'
  });
}

function renderBattleResults(battleResp) {
  const container = $('#battleLeaderboard');
  if (!container || !battleResp) return;

  $('#battleWinnerBadge').textContent = `Winner: ${battleResp.winner_name}`;

  container.innerHTML = battleResp.participants.map(p => {
    let cardBorder = 'border-obsidian-border bg-obsidian-950';
    let rankBadge = 'bg-obsidian-800 text-slate-300';
    if (p.is_winner) {
      cardBorder = 'border-amber-500/60 bg-amber-950/20 shadow-lg shadow-amber-950/30 ring-1 ring-amber-400/40';
      rankBadge = 'bg-amber-500 text-black font-black';
    }

    return `
      <div class="p-4 rounded-xl border ${cardBorder} flex flex-col justify-between space-y-3">
        <div>
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="h-6 w-6 rounded-full grid place-items-center text-xs font-bold ${rankBadge}">#${p.rank}</span>
              <h5 class="text-xs font-bold text-white">${esc(p.name)}</h5>
            </div>
            ${p.is_winner ? '<span class="text-xs font-bold text-amber-300">🏆 CHAMPION</span>' : ''}
          </div>
          <p class="text-[11px] text-slate-400 mt-1.5">${esc(p.summary)}</p>
        </div>
        <div class="pt-2 border-t border-obsidian-border flex items-center justify-between font-mono">
          <div>
            <span class="text-[10px] text-slate-400 block font-sans">Execution Time</span>
            <b class="text-sm ${p.is_winner ? 'text-amber-300' : 'text-white'} font-bold">${p.execution_ms} ms</b>
          </div>
          <div class="text-right">
            <span class="text-[10px] text-slate-400 block font-sans">Speedup</span>
            <b class="text-sm ${p.speedup_percent > 0 ? 'text-emerald-400' : 'text-slate-400'} font-bold">${p.speedup_percent > 0 ? '+' + p.speedup_percent + '%' : 'Baseline'}</b>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

$('#startBattleBtn')?.addEventListener('click', async () => {
  const ddl_schema = valueFor('schema').trim();
  const original_query = valueFor('query').trim();
  const human_query = $('#battleHumanInput')?.value.trim();

  const battleBtn = $('#startBattleBtn');
  const battleText = $('#startBattleBtnText') || battleBtn;
  battleBtn.disabled = true;
  battleText.textContent = 'Running Tournament...';

  try {
    const resp = await fetch('/api/battle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ddl_schema, original_query, human_query })
    });
    const res = await resp.json();
    if (!resp.ok) throw new Error(res.detail || 'Battle tournament failed');
    renderBattleResults(res);
  } catch (err) {
    alert(err.message || 'Battle arena execution error');
  } finally {
    battleBtn.disabled = false;
    battleText.textContent = 'Start Arena Tournament';
  }
});

// ================= DUAL-PERSONA EXPLAINER =================
function renderExplainerSteps(persona) {
  const container = $('#explainerStepsContainer');
  if (!container || !currentExplainerSteps.length) return;

  const begBtn = $('#personaBeginnerBtn');
  const dbaBtn = $('#personaDbaBtn');
  if (begBtn) {
    begBtn.className = `btn-tactile flex-1 py-1.5 px-3 rounded-lg text-xs font-bold transition shadow-sm ${
      persona === 'beginner' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'
    }`;
  }
  if (dbaBtn) {
    dbaBtn.className = `btn-tactile flex-1 py-1.5 px-3 rounded-lg text-xs font-bold transition shadow-sm ${
      persona === 'dba' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'
    }`;
  }

  container.innerHTML = currentExplainerSteps.map(step => `
    <div class="p-3.5 rounded-xl border border-obsidian-border bg-obsidian-950 space-y-1.5">
      <div class="flex items-center justify-between">
        <span class="rounded px-2 py-0.5 text-[9px] font-mono font-bold uppercase tracking-wider bg-indigo-950/60 text-indigo-300 border border-indigo-500/30">Step ${step.step_number}: ${esc(step.phase)}</span>
      </div>
      <h5 class="text-xs font-bold text-white font-sans">${esc(step.headline)}</h5>
      <p class="text-xs leading-relaxed ${persona === 'beginner' ? 'text-indigo-200' : 'text-slate-300 font-mono text-[11px]'} pt-1">
        ${persona === 'beginner' ? esc(step.beginner_analogy) : esc(step.dba_technical_insight)}
      </p>
    </div>
  `).join('');
}

$('#openExplainerBtn')?.addEventListener('click', () => {
  $('#explainerModal')?.classList.remove('hidden');
  renderExplainerSteps(currentExplainerPersona);
});
$('#personaBeginnerBtn')?.addEventListener('click', () => {
  currentExplainerPersona = 'beginner';
  renderExplainerSteps('beginner');
});
$('#personaDbaBtn')?.addEventListener('click', () => {
  currentExplainerPersona = 'dba';
  renderExplainerSteps('dba');
});

// ================= GLOBAL WORKSPACE HELPERS =================
window.loadSampleScenario = function(key) {
  if (!presets[key]) return;
  const select = $('#samplePreset');
  if (select) select.value = key;
  setValue('schema', presets[key].schema);
  setValue('query', presets[key].query);
  switchEditor('query');
  refreshCompletions();
  
  const btn = $('#analyzeBtn');
  if (btn) {
    btn.focus();
    btn.classList.add('ring-2', 'ring-emerald-400');
    setTimeout(() => btn.classList.remove('ring-2', 'ring-emerald-400'), 1200);
  }
};

window.formatCurrentEditorSql = function() {
  const currentVal = valueFor(activeEditor);
  if (!currentVal) return;
  const formatted = currentVal
    .replace(/\s+/g, ' ')
    .replace(/\s*(SELECT|FROM|WHERE|GROUP BY|ORDER BY|HAVING|LIMIT|LEFT JOIN|RIGHT JOIN|INNER JOIN|JOIN|UNION|WITH)\s+/gi, '\n$1 ')
    .trim();
  setValue(activeEditor, formatted);
};

window.clearCurrentEditor = function() {
  setValue(activeEditor, '');
};

// ================= KEYBOARD SHORTCUTS =================
document.addEventListener('keydown', (e) => {
  // Cmd+Enter or Ctrl+Enter -> Analyze
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
    e.preventDefault();
    analyze();
  }
  // Escape -> Close open modal
  if (e.key === 'Escape') {
    ['#copilotModal', '#dashboardModal', '#explainerModal', '#shortcutsModal', '#nodeInspector'].forEach(sel => {
      const el = $(sel);
      if (el) el.classList.add('hidden');
    });
  }
  // Alt+1 / Alt+2 -> Switch Editor tabs
  if (e.altKey && e.key === '1') {
    e.preventDefault();
    switchEditor('query');
  } else if (e.altKey && e.key === '2') {
    e.preventDefault();
    switchEditor('schema');
  }
});

// Start Monaco Editor
startMonaco();
