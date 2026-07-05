let currentModeFilter = "all";
let latestStats = null;
let _isRefreshing = false;
let _firstRenderDone = false;
let recentEventsPage = 1;
let tokenSavingsPage = 1;
let _settingsData = null;
let _settingsLoaded = false;
let _activeConfigTab = "hybrid";
let _formDirty = false;

const RECENT_EVENTS_PAGE_SIZE = 100;
const TOKEN_SAVINGS_PAGE_SIZE = 100;

function byId(id) { return document.getElementById(id); }
function setHtml(id, v) { const el = byId(id); if (el) el.innerHTML = v; }
function setText(id, v) { const el = byId(id); if (el) el.textContent = v; }

function paginateRows(rows, page, pageSize) {
  const total = rows.length;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(Math.max(1, page), pages);
  const start = (safePage - 1) * pageSize;
  return {
    page: safePage,
    pages,
    total,
    items: rows.slice(start, start + pageSize),
    start: total ? start + 1 : 0,
    end: Math.min(start + pageSize, total),
  };
}

function renderPager(page, pages, total, onPrev, onNext, label = "rows") {
  if (total <= 0) return "";
  return `
    <div class="table-pager" style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:12px">
      <div class="muted-text">Page ${page} of ${pages} · ${total} ${label}</div>
      <div style="display:flex;gap:8px">
        <button class="save-btn" ${page <= 1 ? "disabled" : ""} onclick="${onPrev}">Prev</button>
        <button class="save-btn" ${page >= pages ? "disabled" : ""} onclick="${onNext}">Next</button>
      </div>
    </div>
  `;
}

// ─── Theme ────────────────────────────────────────────────────────────────────

function initTheme() {
  const saved = localStorage.getItem("cb-theme") || "dark";
  applyTheme(saved);
  byId("themeToggle")?.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    applyTheme(next);
    localStorage.setItem("cb-theme", next);
  });
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const icon = byId("themeIcon");
  const label = byId("themeLabel");
  if (theme === "dark") {
    if (icon) icon.innerHTML = `<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>`;
    if (label) label.textContent = "Light mode";
  } else {
    if (icon) icon.innerHTML = `<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>`;
    if (label) label.textContent = "Dark mode";
  }
}

// ─── Toast ────────────────────────────────────────────────────────────────────

function showToast(message, type = "info", durationMs = 3500) {
  const icons = {
    success: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`,
    error:   `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--error)" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
    info:    `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
  };
  const container = byId("toastContainer");
  if (!container) return;
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.innerHTML = `<span class="toast-icon">${icons[type] || icons.info}</span><span class="toast-msg">${escapeHtml(message)}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.style.animation = "toastOut 0.2s ease forwards";
    setTimeout(() => el.remove(), 220);
  }, durationMs);
}

// ─── Sidebar scroll spy ───────────────────────────────────────────────────────

function initScrollSpy() {
  const sections = document.querySelectorAll(".section[id]");
  const navItems = document.querySelectorAll(".nav-item[data-section]");
  if (!sections.length || !navItems.length) return;

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        navItems.forEach((item) => {
          item.classList.toggle("active", item.dataset.section === entry.target.id);
        });
      }
    });
  }, { rootMargin: "-20% 0px -70% 0px", threshold: 0 });

  sections.forEach((s) => observer.observe(s));

  navItems.forEach((item) => {
    item.addEventListener("click", (e) => {
      e.preventDefault();
      const target = document.getElementById(item.dataset.section);
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
      navItems.forEach((n) => n.classList.remove("active"));
      item.classList.add("active");
      // Special: load settings when scrolling to it
      if (item.dataset.section === "settings") loadSettings();
      if (item.dataset.section === "pipeline-logs") loadPipelineLogs();
      if (item.dataset.section === "qwen-input") { loadQwenInput(); loadPromptConfig(); }
    });
  });
}

// ─── Keyboard shortcuts ───────────────────────────────────────────────────────

function initKeyboard() {
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
    if (e.key === "r" || e.key === "R") { e.preventDefault(); refreshDashboard(); }
    if (e.key === "t" || e.key === "T") { e.preventDefault(); byId("themeToggle")?.click(); }
  });
}

// ─── Fetch with timeout ───────────────────────────────────────────────────────

async function fetchWithTimeout(url, options = {}, timeoutMs = 10000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

// Lazily loads the pre-generated dashboard_stats.js snapshot, only as a
// last-resort fallback when the live dashboard server is unreachable. Not
// loaded via a <script> tag in index.html anymore -- that would parse this
// (ever-growing) snapshot file on every single page load even though a live
// fetch supersedes it in the normal case. Cached after first load/attempt so
// repeated calls (e.g. the 30s auto-refresh) don't re-inject the script tag.
let _dashboardStatsFallbackPromise = null;

function loadDashboardStatsFallback() {
  if (window.CONTEXT_BRIDGE_STATS) return Promise.resolve(window.CONTEXT_BRIDGE_STATS);
  if (_dashboardStatsFallbackPromise) return _dashboardStatsFallbackPromise;
  _dashboardStatsFallbackPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "../usage/dashboard_stats.js?v=20260624";
    script.onload = () => {
      if (window.CONTEXT_BRIDGE_STATS) resolve(window.CONTEXT_BRIDGE_STATS);
      else reject(new Error("dashboard_stats.js loaded but did not set CONTEXT_BRIDGE_STATS"));
    };
    script.onerror = () => reject(new Error("dashboard_stats.js fallback failed to load"));
    document.body.appendChild(script);
  });
  return _dashboardStatsFallbackPromise;
}

async function loadStats() {
  if (window.location.protocol.startsWith("http")) {
    try {
      const res = await fetchWithTimeout("/api/stats", { cache: "no-store" }, 10000);
      if (res.ok) return res.json();
    } catch (_) { /* fall through */ }
  }
  try {
    const res = await fetchWithTimeout("http://127.0.0.1:8795/api/stats", { cache: "no-store" }, 10000);
    if (res.ok) return res.json();
  } catch (_) { /* fall through */ }
  try {
    return await loadDashboardStatsFallback();
  } catch (_) { /* fall through */ }
  throw new Error("Dashboard server not reachable. Run start_Context_Bridge.bat.");
}

// ─── Status dot ───────────────────────────────────────────────────────────────

function setStatus(state, text) {
  const dot = byId("statusDot");
  const textEl = byId("statusText");
  if (dot) dot.className = `status-dot ${state}`;
  if (textEl) textEl.textContent = text;
}

// ─── Refresh ──────────────────────────────────────────────────────────────────

async function refreshDashboard() {
  if (_isRefreshing) return;
  _isRefreshing = true;

  const btn = byId("refreshBtn");
  if (btn) btn.classList.add("spinning");

  const loader = byId("dashboardLoading");
  if (!_firstRenderDone && loader) loader.style.display = "flex";

  const scrollPositions = new Map();
  document.querySelectorAll(".table-wrap").forEach((container) => {
    const table = container.querySelector("table");
    if (table?.id) scrollPositions.set(table.id, { top: container.scrollTop, left: container.scrollLeft });
  });

  try {
    await loadSettings(true);
    latestStats = await loadStats();
    setStatus("live", "Server live");

    setText("generatedAt", `Updated ${formatUtc(latestStats.generated_at)}`);
    byId("generatedAt")?.classList.remove("stale");

    // Update mode badge
    applyModeBadge(_settingsData?.active_runtime || _detectMode(latestStats));

    renderCards(latestStats);
    renderModeOverview(latestStats);
    renderIndexHealth(latestStats);
    renderModePanel("keyword",        "keywordModeCards", "keywordRecent",   latestStats);
    renderModePanel("hybrid_hash",    "hybridModeCards",  "hybridRecent",    latestStats);
    renderModePanel("hybrid_semantic","semanticModeCards","semanticRecent",  latestStats);
    renderEvalComparison(latestStats);
    renderCodeLocationQuality(latestStats);
    renderCodeLocationActivity(latestStats);
    renderGraphifyEnrichment(latestStats);
    renderQualitySuite(latestStats);
    renderConfigHelper();
    renderOutcomeBars(latestStats);
    renderCountTable("failureReasons", "Reason", latestStats.failure_reason_counts);
    renderCountTable("toolCounts", "Tool", latestStats.tool_counts);
    renderEventFilters(latestStats);
    renderRecentEvents(latestStats);
    renderMissedFiles(latestStats);
    renderLowConfidence(latestStats);
    _firstRenderDone = true;
  } catch (error) {
    setStatus("error", "Server offline");
    const genAt = byId("generatedAt");
    if (genAt) { genAt.textContent = error.message; genAt.classList.add("stale"); }
    if (!_firstRenderDone) {
      setHtml("summaryCards", `<div class="load-error">${escapeHtml(error.message)}</div>`);
    }
  } finally {
    if (loader) loader.style.display = "none";
    if (btn) btn.classList.remove("spinning");
    _isRefreshing = false;
    document.querySelectorAll(".table-wrap").forEach((container) => {
      const table = container.querySelector("table");
      if (table?.id && scrollPositions.has(table.id)) {
        const pos = scrollPositions.get(table.id);
        container.scrollTop = pos.top;
        container.scrollLeft = pos.left;
      }
    });
  }
}

// Single source of truth for the top-right mode badge. Called from both
// refreshDashboard() and loadSettings() so whichever resolves last wins with
// the most authoritative value (settings > event-count heuristic).
function applyModeBadge(runtimeOrMode) {
  const runtime = typeof runtimeOrMode === "string"
    ? { server_mode: runtimeOrMode }
    : (runtimeOrMode || {});
  const mode = runtime.server_mode || runtime.active_mode || runtime.mode || "keyword";
  const modeBadge = byId("modeBadge");
  if (!modeBadge) return;
  modeBadge.textContent = { keyword: "Keyword", hybrid: "Hybrid", semantic: "Semantic" }[mode] || mode;
  modeBadge.className = `mode-badge ${mode}`;

  const backendBadge = byId("retrievalBackendBadge");
  if (backendBadge) {
    const backend = String(runtime.embedding_backend || "").trim().toLowerCase();
    backendBadge.textContent = backend === "sentence-transformers"
      ? "Vector: sentence-transformers"
      : backend
        ? `Vector: ${backend}`
        : "Vector: unknown";
  }

  const modelBadge = byId("embeddingModelBadge");
  if (modelBadge) {
    const backend = String(runtime.embedding_backend || "").trim().toLowerCase();
    const model = String(runtime.embedding_model || "").trim();
    if (backend === "sentence-transformers") {
      modelBadge.textContent = `Model: ${model || "unset"}`;
      modelBadge.style.display = "inline-block";
    } else {
      modelBadge.style.display = "none";
    }
  }
  
  const testBadge = byId("testModeBadge");
  if (testBadge && window._settingsData && window._settingsData.test_mode) {
    testBadge.style.display = "inline-block";
  } else if (testBadge) {
    testBadge.style.display = "none";
  }
}

function _detectMode(stats) {
  if (_settingsData?.active_mode) return _settingsData.active_mode;
  const modes = stats.mode_stats || {};
  if ((modes.hybrid_semantic?.event_count || 0) > (modes.hybrid_hash?.event_count || 0)) return "semantic";
  if ((modes.hybrid_hash?.event_count || 0) > (modes.keyword?.event_count || 0)) return "hybrid";
  return "keyword";
}

// ─── Reset ────────────────────────────────────────────────────────────────────

async function resetDashboardData() {
  if (!window.confirm("Clear dashboard usage logs, outcomes, and saved eval snapshots? Indexes and Graphify data are not affected.")) return;

  const button = byId("resetDashboardData");
  if (button) { button.disabled = true; button.textContent = "Resetting…"; }

  try {
    const endpoint = window.location.protocol.startsWith("http")
      ? "/api/reset-dashboard-data"
      : "http://127.0.0.1:8795/api/reset-dashboard-data";
    const res = await fetchWithTimeout(endpoint, { method: "POST", cache: "no-store" }, 10000);
    if (!res?.ok) throw new Error("Server returned an error.");
    latestStats = null;
    currentModeFilter = "all";
    _isRefreshing = false;
    await refreshDashboard();
    if (_settingsData?.active_runtime || _settingsData?.active_mode) applyModeBadge(_settingsData?.active_runtime || _settingsData.active_mode);
    showToast("Dashboard data cleared.", "success");
  } catch (error) {
    showToast(error.message || "Failed to reset.", "error");
  } finally {
    if (button) { button.disabled = false; button.textContent = "Reset Data"; }
  }
}

async function clearRulesCache() {
  const button = byId("clearRulesCache");
  if (button) { button.disabled = true; button.textContent = "Reloading…"; }
  try {
    const endpoint = window.location.protocol.startsWith("http")
      ? "/api/clear-rules-cache"
      : "http://127.0.0.1:8795/api/clear-rules-cache";
    const res = await fetchWithTimeout(endpoint, { method: "POST", cache: "no-store" }, 8000);
    const data = res?.ok ? await res.json() : null;
    if (data?.ok) showToast(data.message, "success");
    else throw new Error(data?.message || "Failed to clear rules cache.");
  } catch (error) {
    showToast(error.message || "Failed to clear rules cache.", "error");
  } finally {
    if (button) { button.disabled = false; button.textContent = "Reload Rules"; }
  }
}

async function clearAnalysisCache() {
  const button = byId("clearAnalysisCache");
  if (button) { button.disabled = true; button.textContent = "Clearing…"; }
  try {
    const endpoint = window.location.protocol.startsWith("http")
      ? "/api/clear-analysis-cache"
      : "http://127.0.0.1:8795/api/clear-analysis-cache";
    const res = await fetchWithTimeout(endpoint, { method: "POST", cache: "no-store" }, 8000);
    const data = res?.ok ? await res.json() : null;
    if (data?.ok) showToast(data.message, "success");
    else throw new Error(data?.message || "Failed to clear cache.");
  } catch (error) {
    showToast(error.message || "Failed to clear cache.", "error");
  } finally {
    if (button) { button.disabled = false; button.textContent = "Clear Local AI Cache"; }
  }
}

// ─── Render helpers ───────────────────────────────────────────────────────────

function metricCard(label, value, hint = "") {
  return `<div class="metric-card">
    <div class="metric-label">${escapeHtml(label)}</div>
    <div class="metric-value">${escapeHtml(String(value))}</div>
    ${hint ? `<div class="metric-hint">${escapeHtml(hint)}</div>` : ""}
  </div>`;
}

function chip(label, value) {
  return `<div class="chip"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`;
}

function getOutcomeMetrics(stats) {
  const outcomes = Array.isArray(stats.recent_outcomes) ? stats.recent_outcomes : [];
  const expectedTotal = Number(stats.total_tasks_with_outcomes || 0);
  const haveFullOutcomeList = outcomes.length === expectedTotal;
  const recorded = haveFullOutcomeList ? outcomes.filter((o) => !o?.inferred) : [];
  const inferred = haveFullOutcomeList ? outcomes.filter((o) => !!o?.inferred) : [];

  const countByOutcome = (rows, name) => rows.filter((o) => o?.outcome === name).length;
  const rate = (value, total) => total > 0 ? Math.round((value / total) * 100) : 0;

  if (recorded.length > 0) {
    const success = countByOutcome(recorded, "success");
    const partial = countByOutcome(recorded, "partial");
    const failed = countByOutcome(recorded, "failed");
    return {
      basis: "recorded",
      count: recorded.length,
      inferredCount: inferred.length,
      successRate: rate(success, recorded.length),
      partialRate: rate(partial, recorded.length),
      failedRate: rate(failed, recorded.length),
      counts: { success, partial, failed },
    };
  }

  if (inferred.length > 0) {
    const success = countByOutcome(inferred, "success");
    const partial = countByOutcome(inferred, "partial");
    const failed = countByOutcome(inferred, "failed");
    return {
      basis: "inferred",
      count: inferred.length,
      inferredCount: inferred.length,
      successRate: rate(success, inferred.length),
      partialRate: rate(partial, inferred.length),
      failedRate: rate(failed, inferred.length),
      counts: { success, partial, failed },
    };
  }

  return {
    basis: "all",
    count: Number(stats.total_tasks_with_outcomes || 0),
    inferredCount: Number(stats.total_inferred_outcomes || 0),
    successRate: Number(stats.success_rate_percent || 0),
    partialRate: Number(stats.partial_rate_percent || 0),
    failedRate: Number(stats.failed_rate_percent || 0),
    counts: {
      success: Number(stats.outcome_counts?.success || 0),
      partial: Number(stats.outcome_counts?.partial || 0),
      failed: Number(stats.outcome_counts?.failed || 0),
    },
  };
}

function renderCards(stats) {
  const outcomeMetrics = getOutcomeMetrics(stats);
  const totalRuns = Number(stats.total_tool_calls || 0);
  const totalOutcomes = Number(outcomeMetrics.count || stats.total_tasks_with_outcomes || 0);
  const outcomeHint = outcomeMetrics.basis === "recorded"
    ? "recorded outcomes"
    : outcomeMetrics.basis === "inferred"
      ? "inferred from events"
      : "recorded + inferred";
  const cards = [
    ["Tool Calls", totalRuns, "all time"],
    ["Outcomes", totalOutcomes, outcomeHint],
    ["Success Rate", `${outcomeMetrics.successRate}%`, `of ${outcomeHint}`],
    ["Partial Rate", `${outcomeMetrics.partialRate}%`, `of ${outcomeHint}`],
    ["Failed Rate", `${outcomeMetrics.failedRate}%`, `of ${outcomeHint}`],
    ["Token savings", `${stats.estimated_token_savings_percent}%`, "measured · chars vs full files"],
    ["Avg Confidence", stats.average_confidence || 0, "retrieval confidence"],
    ["Ranking Profile", stats.latest_ranking_profile || "—", "latest active profile"],
  ];
  setHtml("summaryCards", cards.map(([l, v, h]) =>
    l === "Token savings"
      ? clickableMetricCard(l, v, h, "showTokenSavingsModal()")
      : metricCard(l, v, h)
  ).join(""));
}

function clickableMetricCard(label, value, hint, onclick) {
  return `<div class="metric-card" style="cursor:pointer" title="Click to see how this is calculated" onclick="${onclick}">
    <div class="metric-label">${escapeHtml(label)} &#128269;</div>
    <div class="metric-value">${escapeHtml(String(value))}</div>
    ${hint ? `<div class="metric-hint">${escapeHtml(hint)}</div>` : ""}
  </div>`;
}

function showTokenSavingsModal() {
  const b = latestStats && latestStats.token_savings_breakdown;
  if (!b) return;
  const fmt = (n) => Number(n || 0).toLocaleString();
  const pageData = paginateRows((b.rows || []).slice().reverse(), tokenSavingsPage, TOKEN_SAVINGS_PAGE_SIZE);
  tokenSavingsPage = pageData.page;
  const rows = pageData.items.map((r) => `
    <tr>
      <td style="padding:6px;max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(r.query || "")}</td>
      <td style="padding:6px;text-align:right">${fmt(r.delivered_chars)}</td>
      <td style="padding:6px;text-align:right">${fmt(r.baseline_chars)}</td>
      <td style="padding:6px;text-align:right"><strong>${r.saved_percent}%</strong></td>
    </tr>`).join("");
  const html = `
    <div onclick="closeTokenSavingsModal(event)" style="position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:flex;align-items:center;justify-content:center;padding:24px">
      <div onclick="event.stopPropagation()" style="background:var(--panel,#171c26);color:var(--text,#e8e8e8);max-width:840px;width:100%;max-height:85vh;overflow:auto;border-radius:12px;border:1px solid var(--border,#2a2f3a);padding:22px;box-shadow:0 12px 48px rgba(0,0,0,.55)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <h2 style="margin:0;font-size:17px">Token savings &mdash; how it&#39;s calculated</h2>
          <button onclick="closeTokenSavingsModal()" style="background:none;border:none;color:var(--text-muted,#9aa3b2);font-size:24px;line-height:1;cursor:pointer">&times;</button>
        </div>
        <p style="color:var(--text-muted,#9aa3b2);font-size:12.5px;margin:6px 0 16px;line-height:1.5">
          <strong>Savings = 1 &minus; (chars CB delivered to the model) &divide; (chars of the full files CB pointed to)</strong>, summed across queries.<br>
          Baseline = ${escapeHtml(b.baseline || "")}. Characters are used as a token proxy &mdash; the ratio cancels tokenizer bias, so no token library is required.
        </p>
        <table style="width:100%;border-collapse:collapse;font-size:12.5px">
          <thead><tr style="text-align:left;color:var(--text-muted,#9aa3b2);border-bottom:1px solid var(--border,#2a2f3a)">
            <th style="padding:6px">Query</th>
            <th style="padding:6px;text-align:right">Delivered</th>
            <th style="padding:6px;text-align:right">Full files</th>
            <th style="padding:6px;text-align:right">Saved</th>
          </tr></thead>
          <tbody>${rows}</tbody>
          <tfoot><tr style="border-top:2px solid var(--border,#2a2f3a);font-weight:bold">
            <td style="padding:9px 6px">OVERALL (${(b.rows || []).length} queries)</td>
            <td style="padding:9px 6px;text-align:right">${fmt(b.total_delivered_chars)}</td>
            <td style="padding:9px 6px;text-align:right">${fmt(b.total_baseline_chars)}</td>
            <td style="padding:9px 6px;text-align:right;color:var(--success,#4ade80)">${b.overall_saved_percent}%</td>
          </tr></tfoot>
        </table>
        ${renderPager(pageData.page, pageData.pages, pageData.total, "changeTokenSavingsPage(-1)", "changeTokenSavingsPage(1)", "queries")}
      </div>
    </div>`;
  const root = document.createElement("div");
  root.id = "tsModalRoot";
  root.innerHTML = html;
  document.body.appendChild(root);
}

function closeTokenSavingsModal() {
  const root = byId("tsModalRoot");
  if (root) root.remove();
}

function changeTokenSavingsPage(delta) {
  tokenSavingsPage = Math.max(1, tokenSavingsPage + delta);
  closeTokenSavingsModal();
  showTokenSavingsModal();
}

function renderModeOverview(stats) {
  const modes = stats.mode_stats || {};
  const items = [
    ["Keyword",      modes.keyword,         "Graphify-only retrieval",           "green"],
    ["Hybrid RAG",   modes.hybrid_hash,     "Graphify + hash vector assist",     "blue"],
    ["Semantic RAG", modes.hybrid_semantic, "Graphify + semantic vector assist",  "purple"],
  ];
  setHtml("modeCards", items.map(([label, item, hint, _color]) =>
    metricCard(label, item?.event_count || 0, hint)
  ).join(""));
}

function renderIndexHealth(stats) {
  const health = stats.index_health || {};
  const rows = [
    ["Keyword index",        health.keyword],
    ["Hash vector index",    health.hybrid_hash],
    ["Semantic vector index",health.hybrid_semantic],
  ].map(([label, item]) => {
    const manifest = item?.manifest || {};
    const ok = item?.exists;
    return `<tr>
      <td>${escapeHtml(label)}</td>
      <td><span class="badge ${ok ? "ok" : "bad"}">${ok ? "ready" : "missing"}</span></td>
      <td>${escapeHtml(formatBytes(item?.size_bytes || 0))}</td>
      <td>${escapeHtml(manifest.embedding_backend || item?.kind || "")}</td>
      <td>${escapeHtml(manifest.embedding_model || "")}</td>
      <td>${escapeHtml(String(manifest.chunk_count || ""))}</td>
      <td>${escapeHtml(item?.modified_at || "")}</td>
    </tr>`;
  }).join("");
  setHtml("indexHealth", `
    <thead><tr><th>Index</th><th>Status</th><th>Size</th><th>Backend</th><th>Model</th><th>Chunks</th><th>Modified</th></tr></thead>
    <tbody>${rows || emptyRow(7)}</tbody>
  `);
}

function renderModePanel(mode, cardsId, tableId, stats) {
  const item = (stats.mode_stats || {})[mode] || {};
  setHtml(cardsId, [
    ["Calls",       item.event_count || 0],
    ["Outcomes",    item.outcome_count || 0],
    ["Success",     `${item.success_rate_percent || 0}%`],
    ["Avg conf.",   item.average_confidence || 0],
    ["Avg files",   item.average_files_returned || 0],
    ["Vec suppress",`${item.suppression_rate_percent || 0}%`],
  ].map(([l, v]) => chip(l, v)).join(""));
  // Per-query detail intentionally omitted here — shown once in the global
  // Recent Events table (filterable by mode) to avoid duplication.
}

function renderFileList(files) {
  if (!files?.length) return "";
  return files.slice(0, 3).map((f) => escapeHtml(f)).join("<br>");
}

function renderCompactEvents(id, events) {
  const rows = events.slice(-100).reverse().map((event) => `
    <tr>
      <td class="query-cell">${escapeHtml(event.query || "")}</td>
      <td>${escapeHtml(String(event.confidence ?? ""))}</td>
      <td>${escapeHtml(String(event.files_returned ?? ""))}</td>
      <td>${escapeHtml(String(event.symbol_hits_returned ?? ""))}</td>
      <td>${escapeHtml(String(event.location_hints_returned ?? ""))}</td>
      <td>${escapeHtml(String(event.dependency_chain_returned ?? ""))}</td>
      <td class="files-cell">${renderFileList(event.top_files)}</td>
    </tr>
  `).join("");
  setHtml(id, `
    <thead><tr><th>Query</th><th>Conf</th><th>Files</th><th>Sym</th><th>Loc</th><th>Dep</th><th>Top files</th></tr></thead>
    <tbody>${rows || emptyRow(7)}</tbody>
  `);
}

function renderEvalComparison(stats) {
  const rows = [
    ["Keyword eval",       stats.latest_eval?.summary,                  "file_hit_rate_percent", "top3_owner_hit_rate_percent", "cases_with_broad_top3"],
    ["Hybrid RAG eval",    stats.latest_hybrid_eval?.summary,           "hybrid_file_hit_rate_percent", "hybrid_top3_owner_hit_rate_percent", "file_regressions"],
    ["Semantic RAG eval",  stats.latest_semantic_hybrid_eval?.summary,  "hybrid_file_hit_rate_percent", "hybrid_top3_owner_hit_rate_percent", "file_regressions"],
  ].map(([label, summary, fileKey, ownerKey, riskKey]) => `
    <tr>
      <td>${escapeHtml(label)}</td>
      <td>${escapeHtml(String(summary?.case_count ?? ""))}</td>
      <td>${escapeHtml(formatPercent(summary?.[fileKey]))}</td>
      <td>${escapeHtml(formatPercent(summary?.[ownerKey]))}</td>
      <td>${escapeHtml(String(summary?.[riskKey] ?? ""))}</td>
      <td>${escapeHtml(String(summary?.total_suppressed_vector_candidates ?? ""))}</td>
    </tr>
  `).join("");
  setHtml("evalComparison", `
    <thead><tr><th>Eval</th><th>Cases</th><th>File hit</th><th>Top 3 owners</th><th>Risk count</th><th>Suppressed vectors</th></tr></thead>
    <tbody>${rows || emptyRow(6)}</tbody>
  `);
}

function renderCodeLocationQuality(stats) {
  const usage = stats.code_location_stats || {};
  const summary = stats.latest_code_location_eval?.summary || {};
  setHtml("codeLocationCards", [
    ["Calls",          usage.call_count || 0],
    ["Success",        `${usage.success_rate_percent || 0}%`],
    ["Primary owner",  `${summary.primary_owner_hit_rate_percent ?? usage.primary_owner_rate_percent ?? 0}%`],
    ["Top 3 owners",   `${summary.top3_owner_hit_rate_percent ?? 0}%`],
    ["Top 5 symbols",  `${summary.top5_symbol_hit_rate_percent ?? 0}%`],
    ["Dependency",     `${summary.dependency_hit_rate_percent ?? 0}%`],
    ["Avg code blocks",usage.average_code_blocks || 0],
  ].map(([l, v]) => chip(l, v)).join(""));

  const rows = [
    ["Primary owner hit", summary.primary_owner_hit_rate_percent],
    ["Owner hit",         summary.owner_hit_rate_percent],
    ["Top 3 owner hit",   summary.top3_owner_hit_rate_percent],
    ["Symbol hit",        summary.symbol_hit_rate_percent],
    ["Top 5 symbol hit",  summary.top5_symbol_hit_rate_percent],
    ["Line hint hit",     summary.line_hint_hit_rate_percent],
    ["Dependency hit",    summary.dependency_hit_rate_percent],
  ].map(([l, v]) => `<tr><td>${escapeHtml(l)}</td><td>${escapeHtml(formatPercent(v))}</td></tr>`).join("");
  setHtml("codeLocationEval", `<thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>${rows || emptyRow(2)}</tbody>`);
}

function renderCodeLocationActivity(stats) {
  const events = stats.recent_code_location_events || stats.code_location_stats?.recent_events || [];
  renderCompactEvents("codeLocationRecent", events);
}

function renderGraphifyEnrichment(stats) {
  const report = stats.latest_graphify_enrichment_report || {};
  const summary = report.summary || {};
  const recommendations = summary.top_recommendations || [];
  const moduleFailures = summary.module_failure_counts || {};
  const dynamicChips = Object.entries(moduleFailures).sort((a, b) => b[1] - a[1]).slice(0, 4)
    .map(([name, value]) => [`${formatModuleLabel(name)} misses`, value]);
  const fallback = dynamicChips.length > 0 ? dynamicChips : [["Module misses", 0]];

  setHtml("graphifyEnrichmentCards", [
    ["Failing cases", summary.failing_case_count || 0],
    ["Top action",    recommendations[0]?.count || 0],
    ...fallback,
  ].map(([l, v]) => chip(l, v)).join(""));

  const rows = recommendations.map((item) => `
    <tr><td>${escapeHtml(item.action || "")}</td><td>${escapeHtml(String(item.count ?? ""))}</td></tr>
  `).join("");
  setHtml("graphifyEnrichmentTable", `<thead><tr><th>Recommended Graphify Improvement</th><th>Count</th></tr></thead><tbody>${rows || emptyRow(2)}</tbody>`);
}

function renderQualitySuite(stats) {
  const suite = stats.latest_full_quality_suite || {};
  const snapshot = suite.dashboard_snapshot || {};
  const steps = suite.steps || [];

  setHtml("qualitySuiteCards", [
    ["Suite",          suite.suite_ok ? "pass" : "review"],
    ["Steps",          suite.step_count || 0],
    ["Failed",         suite.failed_step_count || 0],
    ["Tool calls",     snapshot.total_tool_calls || 0],
    ["Token savings",  `${snapshot.estimated_token_savings_percent || 0}%`],
  ].map(([l, v]) => chip(l, v)).join(""));

  const rows = steps.map((step) => `
    <tr>
      <td>${escapeHtml(step.name || "")}</td>
      <td><span class="badge ${step.ok ? "ok" : "bad"}">${step.ok ? "pass" : "failed"}</span></td>
      <td>${escapeHtml(String(step.exit_code ?? ""))}</td>
      <td>${escapeHtml(step.started_at || "")}</td>
    </tr>
  `).join("");
  setHtml("qualitySuiteTable", `<thead><tr><th>Step</th><th>Status</th><th>Exit</th><th>Started</th></tr></thead><tbody>${rows || emptyRow(4)}</tbody>`);
}

const PIPELINE_MODE_HINTS = {
  simple:    "No local AI. CB retrieves files and passes directly to the cloud AI. Fast, zero local resource cost.",
  validated: "Recommended default. CB retrieves → local AI ranks and validates → cloud AI implements. Needs any local model (3B+).",
  iterative: "CB retrieves → local AI analyses → CB re-searches any missing files → cloud AI. Use with a 7B+ model.",
  full:      "Maximum accuracy. CB pre-validates → local AI analyses → gap fill → local AI self-reflects → cloud AI. Needs a capable model (14B+). Slower.",
};

function updatePipelineModeHint(selectEl, hintId) {
  if (!selectEl) return;
  const hint = byId(hintId);
  if (hint) hint.textContent = PIPELINE_MODE_HINTS[selectEl.value] || "";

  // Max Gap Iterations only applies to iterative/full. Hide + disable it for
  // simple/validated so it can't be set (matches backend, which forces it to 0).
  const prefix = selectEl.id.replace("-pipeline-mode", "");
  const gapActive = selectEl.value === "iterative" || selectEl.value === "full";
  const gapField = byId(`${prefix}-max-gap-field`);
  const gapInput = byId(`${prefix}-max-gap-iterations`);
  if (gapField) gapField.style.display = gapActive ? "" : "none";
  if (gapInput) gapInput.disabled = !gapActive;

  // Analysis Enabled + Auto-Analyze are read-only — pipeline mode is the single
  // source of truth. simple = both OFF, all other modes = both ON.
  const aiActive  = selectEl.value !== "simple";
  const enabledEl = byId(`${prefix}-analysis-enabled`);
  const autoEl    = byId(`${prefix}-auto-analyze`);
  if (enabledEl) { enabledEl.checked = aiActive; enabledEl.disabled = true; }
  if (autoEl)    { autoEl.checked    = aiActive; autoEl.disabled    = true; }
}

function renderConfigHelper() {
  const mcpConfig = `[mcp_servers.context_bridge]\nurl = "http://127.0.0.1:<PORT>/sse"`;

  const pipelineModes = [
    {
      mode: "simple",
      color: "#95a5a6",
      desc: "CB retrieves files → Cloud AI implements. No local AI. Use when no local model is available.",
    },
    {
      mode: "validated",
      color: "#3498db",
      desc: "CB retrieves → Local AI ranks and validates → Cloud AI implements. Best default with any local model.",
    },
    {
      mode: "iterative",
      color: "#e67e22",
      desc: "CB retrieves → Local AI analyses → CB gap fill (re-searches missing files) → Cloud AI. Use with a 7B+ model.",
    },
    {
      mode: "full",
      color: "#27ae60",
      desc: "CB pre-validates retrieval → Local AI analyses → CB gap fill → Local AI self-reflects → Cloud AI. Use with a 14B+ model.",
    },
  ];

  const promptRule = `
    <div class="config-card" style="grid-column:1/-1;">
      <h3>How to trigger CB in your prompt</h3>
      <p>Always use the <code>&gt;&gt;SEARCH:</code> tag. CB is skipped if no tag is present.</p>
      <pre>&gt;&gt;SEARCH: &lt;what to find in the codebase&gt;\n&gt;&gt;TASK: &lt;what the AI should do with the result&gt;</pre>
      <p style="margin-top:8px;color:var(--muted);">CB calls <code>search_context_hybrid()</code> automatically — never call it manually. The server decides the search strategy internally based on the active config.</p>
    </div>
  `;

  const pipelineCards = pipelineModes.map((p) => `
    <div class="config-card">
      <h3><span style="display:inline-block;background:${p.color};color:#fff;border-radius:4px;padding:2px 8px;font-size:12px;font-weight:600;">${p.mode.toUpperCase()}</span></h3>
      <p>${escapeHtml(p.desc)}</p>
      <pre>pipeline_mode: "${p.mode}"</pre>
    </div>
  `).join("");

  setHtml("configHelper", `
    <div class="config-card" style="grid-column:1/-1;background:var(--bg-2);border:1px solid var(--border);">
      <h3 style="margin-bottom:4px;">MCP Server Config</h3>
      <p style="color:var(--muted);">One SSE server for all modes. Add this once to your MCP config file — do not use stdio/python args. Replace <code>&lt;PORT&gt;</code> with your port from <code>start_Context_Bridge.bat</code> (default: 8755, run <code>change_port.bat</code> to change it).</p>
      <pre>${escapeHtml(mcpConfig)}</pre>
      <p style="margin-top:8px;color:var(--muted);">Switch between Hybrid and Semantic in <strong>Settings → RAG → Default Mode</strong>. No MCP config change needed.</p>
    </div>
    ${promptRule}
    <div class="config-card" style="grid-column:1/-1;background:var(--bg-2);border:1px solid var(--border);margin-top:8px;">
      <h3 style="margin-bottom:4px;">Pipeline Modes</h3>
      <p style="color:var(--muted);">How CB, local AI, and gap search work together — set in Settings → Pipeline Mode.</p>
    </div>
    ${pipelineCards}
  `);
}

function renderOutcomeBars(stats) {
  const outcomeMetrics = getOutcomeMetrics(stats);
  const outcomes = outcomeMetrics.counts;
  const total = Math.max(1, outcomeMetrics.count || 0);
  const riskCounts = stats.risk_state_counts || {};
  const riskTotalRaw =
    Number(riskCounts.likely_good || 0) +
    Number(riskCounts.needs_review || 0) +
    Number(riskCounts.likely_retrieval_miss || 0) +
    Number(riskCounts.likely_graphify_gap || 0);
  const riskTotal = Math.max(1, riskTotalRaw);
  const items = [
    ["success", "var(--success)", outcomes.success || 0],
    ["partial", "var(--warning)", outcomes.partial  || 0],
    ["failed",  "var(--error)",   outcomes.failed   || 0],
  ];
  const rows = items.map(([name, color, count]) => {
    const pct = Math.round((count / total) * 100);
    return `<div class="bar-row">
      <div class="bar-label">
        <span class="bar-dot" style="background:${color}"></span>
        ${escapeHtml(name)}
      </div>
        <div class="bar-track"><div class="bar-fill ${name}" style="width:${pct}%"></div></div>
        <div style="font-size:12px;color:var(--text-2)">${count} <span style="color:var(--text-muted)">(${pct}%)</span></div>
      </div>`;
  }).join("");
  const riskItems = [
    ["likely good", "var(--success)", riskCounts.likely_good || 0],
    ["needs review", "var(--text-muted)", riskCounts.needs_review || 0],
    ["retrieval miss", "var(--error)", riskCounts.likely_retrieval_miss || 0],
    ["graphify gap", "var(--accent)", riskCounts.likely_graphify_gap || 0],
  ];
  const riskRows = riskItems.map(([name, color, count]) => {
    const pct = Math.round((count / riskTotal) * 100);
    return `<div class="bar-row">
      <div class="bar-label">
        <span class="bar-dot" style="background:${color}"></span>
        ${escapeHtml(name)}
      </div>
        <div class="bar-track"><div class="bar-fill neutral" style="width:${pct}%;background:${color}"></div></div>
        <div style="font-size:12px;color:var(--text-2)">${count} <span style="color:var(--text-muted)">(${pct}%)</span></div>
      </div>`;
  }).join("");
  const recorded = Number(stats.total_recorded_outcomes || 0);
  const inferred = Number(stats.total_inferred_outcomes || 0);
  const note = outcomeMetrics.basis === "recorded"
    ? `<div class="muted-text" style="margin-bottom:12px">Showing recorded outcomes only.${inferred ? ` Ignoring ${inferred} inferred outcome${inferred === 1 ? "" : "s"}.` : ""}</div>`
    : outcomeMetrics.basis === "inferred"
      ? `<div class="muted-text" style="margin-bottom:12px">No recorded outcome logs found in <code>context_bridge/usage/outcomes_*.jsonl</code>. Showing ${inferred} inferred outcome${inferred === 1 ? "" : "s"} from event heuristics.</div>`
      : `<div class="muted-text" style="margin-bottom:12px">Recorded outcomes: ${recorded}${inferred ? ` · inferred: ${inferred}` : ""}</div>`;
  const riskNote = `<div class="muted-text" style="margin:14px 0 12px">Derived retrieval risk is heuristic-only and helps flag searches that may need review.</div>`;
  const aiFlaggedCount = Number(stats.ai_flagged_count || 0);
  const aiFlaggedNote = `<div class="muted-text" style="margin:14px 0 4px">Separate from the risk buckets above — this counts cases where the calling AI itself reported <code>partial</code>/<code>failed</code> with a specific reason. It never changes the risk counts, it's just a second, independent signal for developers to review.</div>`;
  const aiFlaggedBlock = `
    <div style="font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--text-muted);margin-bottom:10px">AI-flagged for review</div>
    ${aiFlaggedNote}
    <div class="bar-row">
      <div class="bar-label"><span class="bar-dot" style="background:var(--warning)"></span>AI flagged</div>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.round((aiFlaggedCount / riskTotal) * 100)}%;background:var(--warning)"></div></div>
      <div style="font-size:12px;color:var(--text-2)">${aiFlaggedCount}</div>
    </div>
  `;
  setHtml("outcomeBars", `
    ${note}
    <div style="font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--text-muted);margin-bottom:10px">Logged outcomes</div>
    ${rows}
    ${riskNote}
    <div style="font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--text-muted);margin-bottom:10px">Derived retrieval risk</div>
    ${riskRows}
    <div style="margin-top:14px">${aiFlaggedBlock}</div>
  `);
}

function renderCountTable(id, title, counts) {
  const rows = Object.entries(counts || {})
    .sort((a, b) => b[1] - a[1])
    .map(([key, value]) => `<tr><td>${escapeHtml(key)}</td><td>${escapeHtml(String(value))}</td></tr>`)
    .join("");
  setHtml(id, `<thead><tr><th>${title}</th><th>Count</th></tr></thead><tbody>${rows || emptyRow(2)}</tbody>`);
}

function renderEventFilters(stats) {
  const filteredCounts = {
    all: stats.recent_events?.length || 0,
    keyword: (stats.recent_events || []).filter((e) => eventMode(e) === "keyword").length,
    hybrid_hash: (stats.recent_events || []).filter((e) => eventMode(e) === "hybrid_hash").length,
    hybrid_semantic: (stats.recent_events || []).filter((e) => eventMode(e) === "hybrid_semantic").length,
    ai_flagged: (stats.recent_events || []).filter((e) => e.ai_flagged).length,
  };
  const filters = [
    ["all",             "All",        filteredCounts.all],
    ["keyword",         "Keyword",    filteredCounts.keyword],
    ["hybrid_hash",     "Hybrid RAG", filteredCounts.hybrid_hash],
    ["hybrid_semantic", "Semantic",   filteredCounts.hybrid_semantic],
    ["ai_flagged",      "AI Flagged", filteredCounts.ai_flagged],
  ];
  setHtml("eventFilters", filters.map(([value, label, count]) =>
    `<button class="filter-btn ${currentModeFilter === value ? "active" : ""}" data-filter="${value}">
      ${escapeHtml(label)}<span class="count">${count}</span>
    </button>`
  ).join(""));
  document.querySelectorAll("#eventFilters .filter-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      currentModeFilter = btn.dataset.filter || "all";
      recentEventsPage = 1;
      renderEventFilters(latestStats);
      renderRecentEvents(latestStats);
    });
  });
}

function renderOutcomeBadge(outcome, failureReason, notes) {
  if (!outcome) return `<span class="badge neutral">—</span>`;
  const cls = outcome === "success" ? "ok" : outcome === "failed" ? "bad" : "neutral";
  const label = outcome === "failed" && failureReason && failureReason !== "none"
    ? `failed (${escapeHtml(failureReason)})`
    : escapeHtml(outcome);
  const title = notes ? ` title="${escapeHtml(notes)}"` : "";
  return `<span class="badge ${cls}"${title} style="cursor:help">${label}</span>`;
}

function renderRiskBadge(state) {
  if (!state) return `<span class="badge neutral">—</span>`;
  const mapping = {
    likely_good: ["ok", "Likely good"],
    needs_review: ["neutral", "Needs review"],
    likely_retrieval_miss: ["bad", "Likely retrieval miss"],
    likely_graphify_gap: ["mode-hybrid_hash", "Likely Graphify gap"],
  };
  const [cls, label] = mapping[state] || ["neutral", state];
  return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
}

function renderReasonChips(reasons) {
  if (!Array.isArray(reasons) || !reasons.length) return "—";
  return reasons.slice(0, 3).map((reason) =>
    `<span class="badge neutral" style="margin:0 4px 4px 0">${escapeHtml(String(reason).replaceAll("_", " "))}</span>`
  ).join("");
}

function renderRecentEvents(stats) {
  const events = (stats.recent_events || []).filter((e) =>
    currentModeFilter === "all"
    || (currentModeFilter === "ai_flagged" ? e.ai_flagged : eventMode(e) === currentModeFilter)
  );
  const pageData = paginateRows(events.slice().reverse(), recentEventsPage, RECENT_EVENTS_PAGE_SIZE);
  recentEventsPage = pageData.page;
  const rows = pageData.items.map((event) => `
      <tr>
        <td style="white-space:nowrap;font-size:11px;color:var(--text-muted)">${escapeHtml(event.timestamp || "")}</td>
        <td><span class="badge mode-${escapeHtml(eventMode(event))}">${escapeHtml(modeLabel(eventMode(event)))}</span></td>
        <td>${escapeHtml(event.tool || "")}</td>
        <td class="query-cell">${escapeHtml(event.query || "")}</td>
        <td>${renderOutcomeBadge(event.outcome, event.failure_reason, event.outcome_notes)}</td>
        <td>${renderRiskBadge(event.risk_state)}${event.ai_flagged ? ` <span class="badge bad" title="AI itself reported partial/failed with a specific reason — independent of CB's own risk classification above." style="cursor:help">⚠ AI flagged</span>` : ""}</td>
        <td>${renderReasonChips(event.risk_reasons)}</td>
        <td>${escapeHtml(event.action_label || "—")}</td>
      <td>${escapeHtml(String(event.analysis_relevance_check ?? ""))}</td>
      <td>${escapeHtml(String(event.confidence ?? ""))}</td>
      <td>${escapeHtml(String(event.files_returned ?? ""))}</td>
      <td>${escapeHtml(String(event.symbol_hits_returned ?? ""))}</td>
      <td>${escapeHtml(String(event.location_hints_returned ?? ""))}</td>
      <td>${escapeHtml(String(event.dependency_chain_returned ?? ""))}</td>
      <td class="files-cell">${renderFileList(event.top_files)}</td>
      <td class="mono-cell">${escapeHtml(event.event_id || "")}</td>
      </tr>
    `).join("");
    setHtml("recentEvents", `
    <thead><tr><th>Time</th><th>Mode</th><th>Tool</th><th>Query</th><th>Outcome</th><th>Risk</th><th>Why</th><th>Action</th><th>AI Rel</th><th>Conf</th><th>Files</th><th>Sym</th><th>Loc</th><th>Dep</th><th>Top files</th><th>Event ID</th></tr></thead>
        <tbody>${rows || emptyRow(16)}</tbody>
      `);
    setHtml("recentEventsPager", renderPager(pageData.page, pageData.pages, pageData.total, "changeRecentEventsPage(-1)", "changeRecentEventsPage(1)", "events"));
  }

function changeRecentEventsPage(delta) {
  recentEventsPage = Math.max(1, recentEventsPage + delta);
  renderRecentEvents(latestStats);
}

function renderMissedFiles(stats) {
  const rows = (stats.missed_files || []).slice(-100).reverse().map((item) => `
    <tr>
      <td>${escapeHtml(item.file || "")}</td>
      <td>${escapeHtml(item.failure_reason || "")}</td>
      <td><span class="badge ${item.status === "resolved" ? "ok" : "neutral"}">${escapeHtml(item.status || "")}</span></td>
      <td class="mono-cell">${escapeHtml(item.event_id || "")}</td>
    </tr>
  `).join("");
  setHtml("missedFiles", `<thead><tr><th>File</th><th>Reason</th><th>Status</th><th>Event</th></tr></thead><tbody>${rows || emptyRow(4)}</tbody>`);
}

function renderLowConfidence(stats) {
  const rows = (stats.low_confidence_searches || []).slice(-100).reverse().map((item) => `
    <tr>
      <td class="query-cell">${escapeHtml(item.query || "")}</td>
      <td>${escapeHtml(item.tool || "")}</td>
      <td>${escapeHtml(String(item.confidence ?? ""))}</td>
      <td class="mono-cell">${escapeHtml(item.event_id || "")}</td>
    </tr>
  `).join("");
  setHtml("lowConfidence", `<thead><tr><th>Query</th><th>Tool</th><th>Conf</th><th>Event</th></tr></thead><tbody>${rows || emptyRow(4)}</tbody>`);
}

// ─── Utilities ────────────────────────────────────────────────────────────────

function eventMode(event) {
  if (event.retrieval_mode) {
    if (event.retrieval_mode === "semantic" || event.retrieval_mode === "semantic_hash") return "hybrid_semantic";
    return event.retrieval_mode;
  }
  if (event.tool === "search_context_hybrid") {
    return event.embedding_backend === "sentence-transformers" ? "hybrid_semantic" : "hybrid_hash";
  }
  if (["search_context","find_related_files","get_graphify_pack","get_module_summary"].includes(event.tool)) return "keyword";
  return "other";
}

function modeLabel(mode) {
  return { keyword: "Keyword", hybrid_hash: "Hybrid", hybrid_semantic: "Semantic", other: "Other" }[mode] || mode;
}

function formatPercent(value) {
  return value == null || value === "" ? "" : `${value}%`;
}

function formatUtc(iso) {
  if (!iso) return "unknown";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const p = (n) => String(n).padStart(2, "0");
  return `${months[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()} `
    + `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} UTC`;
}

function formatBytes(value) {
  const n = Number(value || 0);
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}

function emptyRow(cols) {
  return `<tr class="empty-row"><td colspan="${cols}">No data yet</td></tr>`;
}

function escapeHtml(value) {
  if (value == null) return "";
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatModuleLabel(value) {
  return String(value || "").replace(/[_-]+/g, " ").trim()
    .replace(/\b\w/g, (c) => c.toUpperCase()) || "Unknown";
}

// ─── Settings ─────────────────────────────────────────────────────────────────

async function loadPipelineLogs() {
  try {
    // Pipeline mode status from stats
    const statsEndpoint = window.location.protocol.startsWith("http")
      ? "/api/stats" : "http://127.0.0.1:8795/api/stats";
    const statsRes = await fetchWithTimeout(statsEndpoint, { cache: "no-store" }, 8000);
    const stats = statsRes.ok ? await statsRes.json() : {};
    const ps = stats.pipeline_stats || {};

    const modeColors = { simple: "#95a5a6", validated: "#3498db", iterative: "#e67e22", full: "#27ae60" };
    const mode = ps.pipeline_mode || "unknown";
    const modeColor = modeColors[mode] || "#888";

    const modeSteps = {
      simple:    ["CB Retrieval"],
      validated: ["CB Retrieval", "Local AI"],
      iterative: ["CB Retrieval", "Local AI", "Gap Fill"],
      full:      ["CB Retrieval", "CB Pre-Validate", "Local AI", "Gap Fill", "Self-Reflect"],
    };
    const steps = modeSteps[mode] || [];

    setHtml("pipelineModeStatus", `
      <div class="status-item">
        <div class="status-label">Mode</div>
        <strong style="color:${modeColor};font-size:15px;">${escapeHtml(mode.toUpperCase())}</strong>
      </div>
      <div class="status-item">
        <div class="status-label">Local AI</div>
        <strong>${ps.local_ai_enabled ? "enabled" : "disabled"}</strong>
      </div>
      <div class="status-item">
        <div class="status-label">Provider</div>
        <strong>${escapeHtml(ps.local_ai_provider || "—")}</strong>
      </div>
      <div class="status-item">
        <div class="status-label">Max Gap Iterations</div>
        <strong>${ps.max_gap_iterations ?? "—"}</strong>
      </div>
    `);

    // Steps table
    const stepsRows = steps.map(s => `<tr><td>${escapeHtml(s)}</td><td><span style="color:#27ae60">✓ active</span></td></tr>`).join("");
    setHtml("pipelineStepsTable", `
      <thead><tr><th>Step</th><th>Status</th></tr></thead>
      <tbody>${stepsRows || '<tr><td colspan="2" class="muted-text">No steps configured</td></tr>'}</tbody>
    `);

    // Last run
    const lr = ps.last_run;
    if (lr) {
      setHtml("pipelineLastRun", `
        <div class="status-item"><div class="status-label">Timestamp</div><strong>${escapeHtml(lr.timestamp || "—")}</strong></div>
        <div class="status-item"><div class="status-label">Local AI Latency</div><strong>${lr.latency_ms ? lr.latency_ms + " ms" : "—"}</strong></div>
        <div class="status-item"><div class="status-label">Confidence</div><strong>${escapeHtml(lr.confidence || "—")}</strong></div>
        <div class="status-item"><div class="status-label">Topics Found</div><strong>${lr.topic_count ?? "—"}</strong></div>
        <div class="status-item"><div class="status-label">Gap Searches</div><strong>${lr.gap_searches_fired ?? 0}</strong></div>
        <div class="status-item"><div class="status-label">Gap Files Added</div><strong>${lr.gap_files_added ?? 0}</strong></div>
        <div class="status-item"><div class="status-label">Self-Reflect</div><strong>${lr.reflection ? "yes" : "no"}</strong></div>
        <div class="status-item"><div class="status-label">Fallback</div><strong>${lr.fallback ? "⚠ CB raw" : "—"}</strong></div>
      `);
    } else {
      setHtml("pipelineLastRun", `<span class="muted-text">No run logged yet. Run a search first.</span>`);
    }

    // Gap search log
    const gapEndpoint = window.location.protocol.startsWith("http")
      ? "/api/gap-search" : "http://127.0.0.1:8795/api/gap-search";
    const gapRes = await fetchWithTimeout(gapEndpoint, { cache: "no-store" }, 5000).catch(() => null);
    const gapData = gapRes?.ok ? await gapRes.json() : null;
    if (gapData?.available !== false && gapData?.entries?.length) {
      const gapRows = gapData.entries.map(e => `
        <tr>
          <td style="max-width:220px;word-break:break-word;">${escapeHtml(e.topic || "—")}</td>
          <td><code>${escapeHtml(e.query_used || "—")}</code></td>
          <td>${(e.files_found || []).map(f => `<div style="font-size:11px;">${escapeHtml(f)}</div>`).join("") || "—"}</td>
        </tr>
      `).join("");
      setHtml("pipelineGapTable", `
        <thead><tr><th>Topic (from prompt)</th><th>Search Query Used</th><th>Files Found</th></tr></thead>
        <tbody>${gapRows}</tbody>
      `);
    } else {
      setHtml("pipelineGapTable", `<tbody><tr><td colspan="3" class="muted-text">No gap searches fired on last run.</td></tr></tbody>`);
    }

    // Local AI topics from output log
    const outEndpoint = window.location.protocol.startsWith("http")
      ? "/api/qwen-output" : "http://127.0.0.1:8795/api/qwen-output";
    const outRes = await fetchWithTimeout(outEndpoint, { cache: "no-store" }, 5000).catch(() => null);
    const outData = outRes?.ok ? await outRes.json() : null;
    const topics = outData?.parsed?.topics || [];
    if (topics.length) {
      const topicRows = topics.map(t => `
        <tr>
          <td style="max-width:200px;word-break:break-word;">${escapeHtml(t.issue || "—")}</td>
          <td style="font-size:11px;">${escapeHtml(t.primary_file || "unknown")}</td>
          <td>${t.file_match ? '<span style="color:#27ae60">✓</span>' : '<span style="color:#e74c3c">✗ gap</span>'}</td>
          <td style="font-size:11px;">${escapeHtml(t.finding || "—")}</td>
        </tr>
      `).join("");
      setHtml("pipelineTopicsTable", `
        <thead><tr><th>Issue</th><th>Primary File</th><th>Match</th><th>Finding</th></tr></thead>
        <tbody>${topicRows}</tbody>
      `);
    } else {
      setHtml("pipelineTopicsTable", `<tbody><tr><td colspan="4" class="muted-text">No output logged yet. Run a search first.</td></tr></tbody>`);
    }

  } catch (e) {
    setHtml("pipelineModeStatus", `<span class="muted-text">Error loading pipeline logs: ${escapeHtml(String(e))}</span>`);
  }
}


async function loadQwenInput() {
  try {
    const endpoint = window.location.protocol.startsWith("http")
      ? "/api/qwen-input"
      : "http://127.0.0.1:8795/api/qwen-input";
    const res = await fetchWithTimeout(endpoint, { cache: "no-store" }, 8000);
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const d = await res.json();

    if (!d.available) {
      setHtml("qwenInputMeta", `<div class="panel-body"><span class="muted-text">${escapeHtml(d.message)}</span></div>`);
      setHtml("qwenQuery", "");
      setHtml("qwenUserPrompt", "");
      setHtml("qwenSystemPrompt", "");
      return;
    }

    setHtml("qwenInputMeta", `
      <div class="panel-body">
        <div class="settings-status-row">
          <div class="status-item">
            <div class="status-label">Timestamp</div>
            <strong>${escapeHtml(d.timestamp || "—")}</strong>
          </div>
          <div class="status-item">
            <div class="status-label">Provider</div>
            <strong>${escapeHtml(d.provider || "—")}</strong>
          </div>
          <div class="status-item">
            <div class="status-label">Model</div>
            <strong>${escapeHtml(d.model || "—")}</strong>
          </div>
          <div class="status-item">
            <div class="status-label">Total Prompt Size</div>
            <strong>${Number(d.prompt_chars || 0).toLocaleString()} chars</strong>
          </div>
        </div>
      </div>
    `);

    const qwenQueryEl = document.getElementById("qwenQuery");
    if (qwenQueryEl) qwenQueryEl.textContent = d.query || "";

    const qwenUserEl = document.getElementById("qwenUserPrompt");
    if (qwenUserEl) qwenUserEl.textContent = d.user_prompt || "";

    const qwenSysEl = document.getElementById("qwenSystemPrompt");
    if (qwenSysEl) qwenSysEl.textContent = d.system_prompt || "";

  } catch (err) {
    setHtml("qwenInputMeta", `<div class="panel-body"><span class="save-msg error">Could not load local AI input: ${escapeHtml(err.message)}</span></div>`);
  }

  // Load output alongside input
  try {
    const outEndpoint = window.location.protocol.startsWith("http")
      ? "/api/qwen-output"
      : "http://127.0.0.1:8795/api/qwen-output";
    const outRes = await fetchWithTimeout(outEndpoint, { cache: "no-store" }, 8000);
    if (!outRes.ok) throw new Error(`Server returned ${outRes.status}`);
    const o = await outRes.json();

    if (!o.available) {
      setHtml("qwenOutputMeta", `<div class="panel-body"><span class="muted-text">${escapeHtml(o.message)}</span></div>`);
      return;
    }

    const parsed = o.parsed || {};
    const latency = o.latency_ms ? `${(o.latency_ms / 1000).toFixed(1)}s` : "—";

    setHtml("qwenOutputMeta", `
      <div class="panel-body">
        <div class="settings-status-row">
          <div class="status-item">
            <div class="status-label">Timestamp</div>
            <strong>${escapeHtml(o.timestamp || "—")}</strong>
          </div>
          <div class="status-item">
            <div class="status-label">Local AI Latency</div>
            <strong>${latency}</strong>
          </div>
          <div class="status-item">
            <div class="status-label">Parse Error</div>
            <span class="badge ${parsed.parse_error ? 'bad' : 'ok'}">${parsed.parse_error ? 'YES' : 'NO'}</span>
          </div>
          <div class="status-item">
            <div class="status-label">Parse Incomplete</div>
            <span class="badge ${parsed.parse_incomplete ? 'mode-hybrid_hash' : 'ok'}">${parsed.parse_incomplete ? 'YES' : 'NO'}</span>
          </div>
          <div class="status-item">
            <div class="status-label">Cache Hit</div>
            <span class="badge ${parsed.cache_hit ? 'ok' : 'neutral'}">${parsed.cache_hit ? 'YES' : 'NO'}</span>
          </div>
        </div>
      </div>
    `);

    const rc = parsed.relevance_check || "—";
    const conf = parsed.confidence || "—";
    const rcColor = rc === "PASSED" ? "ok" : rc === "PARTIAL" ? "mode-hybrid_hash" : rc === "FAILED" ? "bad" : "neutral";
    const confColor = conf === "high" ? "ok" : conf === "medium" ? "mode-hybrid_hash" : conf === "low" ? "bad" : "neutral";
    const gapsFired = parsed.gap_searches_fired || 0;
    const gapsAdded = parsed.gap_files_added || 0;
    setHtml("qwenRelevance", `
      <div class="status-item">
        <div class="status-label">Relevance Check</div>
        <span class="badge ${rcColor}">${escapeHtml(rc)}</span>
      </div>
      <div class="status-item">
        <div class="status-label">Confidence</div>
        <span class="badge ${confColor}">${escapeHtml(conf)}</span>
      </div>
      ${gapsFired ? `<div class="status-item">
        <div class="status-label">Gap Re-searches</div>
        <span class="badge mode-hybrid_hash">${gapsFired} fired · ${gapsAdded} files added</span>
      </div>` : ""}
    `);

    setHtml("qwenSummary", escapeHtml(parsed.summary || "No summary returned."));

    const topics = parsed.topics || [];
    const topicsEl = document.getElementById("qwenTopics");
    if (topicsEl) {
      if (topics.length) {
        const trows = topics.map((t, i) => `<tr>
          <td>${i + 1}</td>
          <td>${escapeHtml(t.issue || "")}</td>
          <td>${escapeHtml(t.primary_file || "")}</td>
          <td>${escapeHtml(t.entry_method || "")}</td>
          <td>${escapeHtml(t.finding || "")}</td>
        </tr>`).join("");
        topicsEl.innerHTML = `<thead><tr><th>#</th><th>Issue</th><th>Primary File</th><th>Entry Method</th><th>Finding</th></tr></thead><tbody>${trows}</tbody>`;
      } else {
        topicsEl.innerHTML = `<tbody><tr><td colspan="5" class="muted-text">No topic breakdown returned. Run a multi-issue query to see per-topic analysis.</td></tr></tbody>`;
      }
    }

    const files = parsed.ranked_files || [];
    if (files.length) {
      const rows = files.map(f => `<tr>
        <td>${escapeHtml(f.path || "")}</td>
        <td><span class="badge neutral">${escapeHtml(f.role || "")}</span></td>
        <td>${escapeHtml(f.source || "cb_retrieved")}</td>
        <td>${escapeHtml(f.reason || "")}</td>
      </tr>`).join("");
      setHtml("qwenRankedFiles", `<thead><tr><th>File</th><th>Role</th><th>Source</th><th>Reason</th></tr></thead><tbody>${rows}</tbody>`);
    } else {
      setHtml("qwenRankedFiles", `<tbody><tr><td colspan="4" class="muted-text">No ranked files returned.</td></tr></tbody>`);
    }

    const rawEl = document.getElementById("qwenRawOutput");
    if (rawEl) rawEl.textContent = JSON.stringify(parsed, null, 2);

  } catch (err) {
    setHtml("qwenOutputMeta", `<div class="panel-body"><span class="save-msg error">Could not load local AI output: ${escapeHtml(err.message)}</span></div>`);
  }

  // Load gap re-search log separately
  try {
    const gapEndpoint = window.location.protocol.startsWith("http")
      ? "/api/gap-search"
      : "http://127.0.0.1:8795/api/gap-search";
    const gapRes = await fetchWithTimeout(gapEndpoint, { cache: "no-store" }, 5000);
    const gapData = gapRes.ok ? await gapRes.json() : null;
    const gapEl = document.getElementById("gapSearchTable");
    if (gapEl) {
      if (gapData && gapData.available && gapData.entries && gapData.entries.length) {
        const grow = gapData.entries.map(e => `<tr>
          <td>${escapeHtml(e.topic || "")}</td>
          <td><code>${escapeHtml(e.query_used || "")}</code><br><span class="muted-text" style="font-size:10px">${escapeHtml(e.query_source || "")}</span></td>
          <td>${(e.files_found || []).map(f => escapeHtml(f)).join("<br>") || '<span class="muted-text">none</span>'}</td>
        </tr>`).join("");
        gapEl.innerHTML = `<thead><tr><th>Topic (user's words)</th><th>Query Used</th><th>Files Found</th></tr></thead><tbody>${grow}</tbody>`;
      } else {
        gapEl.innerHTML = `<tbody><tr><td colspan="4" class="muted-text">No gap re-searches fired on last query. Local AI found matching files for all topics.</td></tr></tbody>`;
      }
    }
  } catch (_) {}
}

async function loadPromptConfig() {
  try {
    const endpoint = window.location.protocol.startsWith("http")
      ? "/api/prompt-config"
      : "http://127.0.0.1:8795/api/prompt-config";
    const res = await fetchWithTimeout(endpoint, { cache: "no-store" }, 5000);
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const d = await res.json();
    if (d.error) throw new Error(d.error);
    setHtml("promptConfigCards", `
      <div class="status-item">
        <div class="status-label">Total Context Size</div>
        <strong style="font-size:15px">${Number(d.max_prompt_chars).toLocaleString()} chars</strong>
        <div class="status-note">_MAX_PROMPT_CHARS · line 4</div>
      </div>
      <div class="status-item">
        <div class="status-label">Code Block Size</div>
        <strong style="font-size:15px">${Number(d.max_code_block_chars).toLocaleString()} chars</strong>
        <div class="status-note">_MAX_CODE_BLOCK_CHARS · line 5</div>
      </div>
      <div class="status-item">
        <div class="status-label">Code Blocks Count</div>
        <strong style="font-size:15px">${d.max_code_blocks}</strong>
        <div class="status-note">_MAX_CODE_BLOCKS · line 6</div>
      </div>
    `);
  } catch (err) {
    setHtml("promptConfigCards", `<span class="save-msg error">Could not load prompt config: ${escapeHtml(err.message)}</span>`);
  }
}

async function loadSettings(force = false) {
  if (force) _settingsLoaded = false;
  if (_settingsLoaded && _formDirty) return;
  if (_settingsLoaded && _settingsData) {
    applyModeBadge(_settingsData.active_runtime || _settingsData.active_mode);
    renderServerStatus(_settingsData);
    renderOllamaStatus(_settingsData.ollama);
    renderConfigTabs(_settingsData.active_mode);
    populateForm("hybrid",   _settingsData.configs?.hybrid);
    populateForm("semantic", _settingsData.configs?.semantic);
    populateForm("keyword",  _settingsData.configs?.keyword);
    updateProviderVisibility("hybrid");
    updateProviderVisibility("semantic");
    updateProviderVisibility("keyword");
    updateRestartButtonVisibility("hybrid");
    updateRestartButtonVisibility("semantic");
    updateRestartButtonVisibility("keyword");
    loadProfiles();
    return;
  }
  try {
    const endpoint = window.location.protocol.startsWith("http")
      ? "/api/config"
      : "http://127.0.0.1:8795/api/config";
    const res = await fetchWithTimeout(endpoint, { cache: "no-store" }, 10000);
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    _settingsData = await res.json();
    _settingsLoaded = true;
    _formDirty = false;
    applyModeBadge(_settingsData.active_runtime || _settingsData.active_mode);
    renderServerStatus(_settingsData);
    renderOllamaStatus(_settingsData.ollama);
    renderConfigTabs(_settingsData.active_mode);
    populateForm("hybrid",   _settingsData.configs?.hybrid);
    populateForm("semantic", _settingsData.configs?.semantic);
    populateForm("keyword",  _settingsData.configs?.keyword);
    updateProviderVisibility("hybrid");
    updateProviderVisibility("semantic");
    updateProviderVisibility("keyword");
    updateRestartButtonVisibility("hybrid");
    updateRestartButtonVisibility("semantic");
    updateRestartButtonVisibility("keyword");
    loadProfiles();
  } catch (err) {
    setHtml("serverStatusCards", `<span class="save-msg error">Could not load settings: ${escapeHtml(err.message)}</span>`);
  }
}

// ─── Profile Switcher ─────────────────────────────────────────────────────────

async function loadProfiles() {
  try {
    const base = window.location.protocol.startsWith("http") ? "" : "http://127.0.0.1:8795";
    const res = await fetchWithTimeout(`${base}/api/profiles`, { cache: "no-store" }, 6000);
    if (!res.ok) return;
    const data = await res.json();
    renderProfileSelector(data.profiles || [], data.active || "default");
  } catch (_) {}
}

function renderProfileSelector(profiles, active) {
  const el = byId("profileSelector");
  if (!el) return;

  if (!profiles.length) {
    el.innerHTML = `<p style="color:var(--muted);font-size:13px;">No profiles found in <code>rules/projects/</code>. Run prompt 2 to generate one.</p>`;
    return;
  }

  const isDefault = active === "default" || !active;
  const options = [{ name: "default", label: "default (generic — no domain routing)" }]
    .concat(profiles.map(p => ({ name: p.name, label: p.name })))
    .map(p => `<option value="${escapeHtml(p.name)}" ${active === p.name || (isDefault && p.name === "default") ? "selected" : ""}>${escapeHtml(p.label || p.name)}</option>`)
    .join("");

  el.innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
      <select id="profileDropdown" class="form-input" style="max-width:320px;">${options}</select>
      <button id="profileApplyBtn" class="btn-primary" style="padding:6px 16px;">Apply &amp; Restart CB</button>
      <span id="profileMsg" style="font-size:13px;color:var(--muted);"></span>
    </div>
    <p style="margin-top:8px;font-size:12px;color:var(--muted);">Changing the profile rewrites <code>project_profile</code> in all 3 config files and restarts CB — required because the profile is cached at startup.</p>
  `;

  byId("profileApplyBtn")?.addEventListener("click", async () => {
    const selected = byId("profileDropdown")?.value;
    if (!selected) return;
    const msg = byId("profileMsg");
    if (msg) msg.textContent = "Saving and restarting…";
    try {
      const base = window.location.protocol.startsWith("http") ? "" : "http://127.0.0.1:8795";
      const res = await fetchWithTimeout(`${base}/api/set-profile`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile: selected }),
      }, 10000);
      const data = await res.json();
      if (msg) msg.textContent = data.message || (data.ok ? "Done." : "Error.");
      if (data.ok) showToast(`Profile set to '${selected}'. CB restarting…`, "success", 4000);
      else showToast(data.message || "Failed.", "error");
    } catch (err) {
      if (msg) msg.textContent = `Error: ${err.message}`;
    }
  });
}

// ─── Init ─────────────────────────────────────────────────────────────────────

initTheme();
initScrollSpy();
initKeyboard();

refreshDashboard();
loadQwenInput();
loadPromptConfig();

byId("refreshBtn")?.addEventListener("click", refreshDashboard);
byId("resetDashboardData")?.addEventListener("click", resetDashboardData);
byId("clearAnalysisCache")?.addEventListener("click", clearAnalysisCache);
byId("clearRulesCache")?.addEventListener("click", clearRulesCache);

if (window.location.protocol.startsWith("http")) {
  setInterval(() => {
    if (document.visibilityState !== "hidden") refreshDashboard();
  }, 30000);
}

function renderServerStatus(data) {
  const label = { hybrid: "Hybrid", semantic: "Semantic", keyword: "Keyword" }[data.active_mode] || data.active_mode;
  const badgeCls = { hybrid: "mode-hybrid_hash", semantic: "mode-hybrid_semantic", keyword: "mode-keyword" }[data.active_mode] || "neutral";
  const ollamaRunning = data.ollama?.running;
  setHtml("serverStatusCards", `
    <div class="status-item">
      <div class="status-label">Active Mode</div>
      <span class="badge ${badgeCls}">${escapeHtml(label)}</span>
      <div class="status-note">Requires restart to change</div>
    </div>
    <div class="status-item">
      <div class="status-label">MCP Port</div>
      <strong style="font-size:15px">${escapeHtml(String(data.port || "—"))}</strong>
      <div class="status-note">Change via change_port.bat</div>
    </div>
    <div class="status-item">
      <div class="status-label">Ollama</div>
      <span class="badge ${ollamaRunning ? "ok" : "bad"}">${ollamaRunning ? "running" : "not running"}</span>
      <div class="status-note">${ollamaRunning ? "Ready" : "Run start_ollama.bat"}</div>
    </div>
  `);
}

function renderOllamaStatus(ollama) {
  if (!ollama) return;
  if (!ollama.running) {
    setHtml("ollamaStatus", `<p class="muted-text">Ollama is not running. Start it with <code>start_ollama.bat</code> or <code>ollama serve</code>.</p>`);
    return;
  }
  const loaded = ollama.loaded_models.length
    ? ollama.loaded_models.map((m) => `<span class="model-tag loaded">${escapeHtml(m)}</span>`).join("")
    : `<span class="muted-text">None loaded in memory</span>`;
  const available = ollama.available_models.length
    ? ollama.available_models.map((m) => `<span class="model-tag">${escapeHtml(m)}</span>`).join("")
    : `<span class="muted-text">No models pulled — run <code>ollama pull &lt;model&gt;</code></span>`;
  setHtml("ollamaStatus", `
    <div class="ollama-group">
      <div class="ollama-group-label">Loaded in Memory</div>
      <div class="model-tag-list">${loaded}</div>
    </div>
    <div class="ollama-group">
      <div class="ollama-group-label">Available (Pulled)</div>
      <div class="model-tag-list">${available}</div>
    </div>
  `);
}

function renderConfigTabs(activeMode) {
  setHtml("configTabs", [
    { key: "hybrid",   label: "Hybrid" },
    { key: "semantic", label: "Semantic" },
    { key: "keyword",  label: "Keyword" },
  ].map(({ key, label }) => `
    <button class="config-tab-btn ${key === _activeConfigTab ? "active" : ""}" data-config="${key}">
      ${escapeHtml(label)}
      ${key === activeMode ? `<span class="active-badge">ACTIVE</span>` : ""}
    </button>
  `).join(""));
  document.querySelectorAll(".config-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      _activeConfigTab = btn.dataset.config;
      document.querySelectorAll(".config-tab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      document.querySelectorAll(".config-form").forEach((f) => f.classList.add("hidden"));
      byId(`form-${_activeConfigTab}`)?.classList.remove("hidden");
    });
  });
}

function populateForm(prefix, config) {
  if (!config) return;
  const stage = config.pipeline?.analysis_stage || {};
  const rag   = config.settings?.rag || {};

  setCheck(`${prefix}-analysis-enabled`, stage.enabled);
  setCheck(`${prefix}-auto-analyze`,     stage.auto_analyze);
  setCheck(`${prefix}-show-ai-meta`,     stage.show_ai_meta !== false);
  setVal(`${prefix}-provider`,           stage.provider || "ollama");
  setVal(`${prefix}-model`,              stage.model || "");
  setVal(`${prefix}-endpoint`,           stage.endpoint || "");
  setVal(`${prefix}-temperature`,        stage.temperature ?? "");
  setVal(`${prefix}-timeout`,            stage.timeout_seconds ?? "");
  setVal(`${prefix}-auto-timeout`,       stage.auto_analyze_timeout_seconds ?? "");
  setVal(`${prefix}-apikey`,             "");

  setVal(`${prefix}-pipeline-mode`,        stage.pipeline_mode || "validated");
  setVal(`${prefix}-max-gap-iterations`,   stage.max_gap_iterations ?? 2);
  updatePipelineModeHint(byId(`${prefix}-pipeline-mode`), `${prefix}-pipeline-mode-hint`);

  setCheck(`${prefix}-rag-enabled`,        rag.enabled);
  setVal(`${prefix}-embedding-backend`,    rag.embedding_backend || "hash");
  setVal(`${prefix}-embedding-model`,      rag.embedding_model || "all-MiniLM-L6-v2");
  setVal(`${prefix}-top-k-vector`,         rag.top_k_vector ?? "");
  setVal(`${prefix}-top-k-keyword`,        rag.top_k_keyword ?? "");
  setVal(`${prefix}-protected-keyword`,    rag.protected_keyword_count ?? "");
  setVal(`${prefix}-keyword-weight`,       rag.keyword_weight ?? "");
  setVal(`${prefix}-vector-weight`,        rag.vector_weight ?? "");

  const hintsEl = byId(`${prefix}-model-hints`);
  if (hintsEl) {
    hintsEl.innerHTML = "";
    for (const m of (_settingsData?.ollama?.available_models || [])) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "model-hint-btn";
      btn.textContent = m;
      btn.addEventListener("click", () => { setVal(`${prefix}-model`, m); _formDirty = true; });
      hintsEl.appendChild(btn);
    }
  }

  const providerEl = byId(`${prefix}-provider`);
  if (providerEl) {
    providerEl.onchange = () => { updateProviderVisibility(prefix); _formDirty = true; };
  }

  const backendEl = byId(`${prefix}-embedding-backend`);
  if (backendEl) {
    backendEl.onchange = () => { updateEmbeddingBackendVisibility(prefix); _formDirty = true; };
  }
  updateEmbeddingBackendVisibility(prefix);

  const form = byId(`form-${prefix}`);
  if (form && !form.dataset.dirtyListenerAttached) {
    form.addEventListener("input", () => { _formDirty = true; });
    form.dataset.dirtyListenerAttached = "1";
  }
}

function updateProviderVisibility(prefix) {
  const provider = byId(`${prefix}-provider`)?.value || "ollama";
  const endpointField = byId(`${prefix}-endpoint-field`);
  const apikeyField   = byId(`${prefix}-apikey-field`);
  if (endpointField) endpointField.style.display = provider === "ollama" ? ""     : "none";
  if (apikeyField)   apikeyField.style.display   = provider === "ollama" ? "none" : "";
}

function updateEmbeddingBackendVisibility(prefix) {
  const backend = getVal(`${prefix}-embedding-backend`) || "hash";
  const modelField = byId(`${prefix}-embedding-model-field`);
  if (modelField) modelField.style.display = backend === "sentence-transformers" ? "" : "none";
}

function updateRestartButtonVisibility(configName) {
  const restartBtn = byId(`${configName}-restart-btn`);
  if (!restartBtn) return;
  const isActiveConfig = configName === (_settingsData?.active_mode || "hybrid");
  restartBtn.style.display = isActiveConfig ? "" : "none";
  restartBtn.disabled = !isActiveConfig;
  restartBtn.title = isActiveConfig ? "Restart the live ContextBridge server with this saved retrieval config." : "Only the active config can be applied live.";
}

async function saveConfig(configName) {
  const prefix = configName;
  const timeoutVal  = parseInt(getVal(`${prefix}-timeout`), 10);
  const autoTimeout = parseInt(getVal(`${prefix}-auto-timeout`), 10);
  const temperature = parseFloat(getVal(`${prefix}-temperature`));

  if (getVal(`${prefix}-timeout`) && (isNaN(timeoutVal) || timeoutVal < 10)) {
    showToast("Timeout must be at least 10 seconds.", "error"); return;
  }
  if (getVal(`${prefix}-auto-timeout`) && (isNaN(autoTimeout) || autoTimeout < 10)) {
    showToast("Auto-analyze timeout must be at least 10 seconds.", "error"); return;
  }

  const maxGapIter = parseInt(getVal(`${prefix}-max-gap-iterations`), 10);
  const stage = {
    enabled:                      getVal(`${prefix}-pipeline-mode`) !== "simple",
    auto_analyze:                 getVal(`${prefix}-pipeline-mode`) !== "simple",
    show_ai_meta:                 byId(`${prefix}-show-ai-meta`)?.checked ?? true,
    provider:                     getVal(`${prefix}-provider`),
    model:                        getVal(`${prefix}-model`),
    temperature:                  isNaN(temperature) ? 0.1 : temperature,
    timeout_seconds:              isNaN(timeoutVal)  ? 120 : timeoutVal,
    auto_analyze_timeout_seconds: isNaN(autoTimeout) ? 120 : autoTimeout,
    pipeline_mode:                getVal(`${prefix}-pipeline-mode`) || "validated",
    max_gap_iterations:           isNaN(maxGapIter) ? 2 : Math.min(3, Math.max(1, maxGapIter)),
  };

  const provider = getVal(`${prefix}-provider`);
  if (provider === "ollama") {
    stage.endpoint = getVal(`${prefix}-endpoint`);
    stage.api_key = null;
  } else {
    stage.endpoint = null;
    const key = getVal(`${prefix}-apikey`);
    if (key) stage.api_key = key;
  }

  const topKVector    = parseInt(getVal(`${prefix}-top-k-vector`), 10);
  const topKKeyword   = parseInt(getVal(`${prefix}-top-k-keyword`), 10);
  const protectedKw   = parseInt(getVal(`${prefix}-protected-keyword`), 10);
  const kwWeight      = parseFloat(getVal(`${prefix}-keyword-weight`));
  const vecWeight     = parseFloat(getVal(`${prefix}-vector-weight`));

  const rag = {
    enabled:                  getCheck(`${prefix}-rag-enabled`),
    embedding_backend:        getVal(`${prefix}-embedding-backend`) || "hash",
    embedding_model:          getVal(`${prefix}-embedding-model`) || "all-MiniLM-L6-v2",
    top_k_vector:             isNaN(topKVector)  ? 12  : topKVector,
    top_k_keyword:            isNaN(topKKeyword) ? 20  : topKKeyword,
    protected_keyword_count:  isNaN(protectedKw) ? 8   : protectedKw,
    keyword_weight:           isNaN(kwWeight)    ? 1.0 : kwWeight,
    vector_weight:            isNaN(vecWeight)   ? 0.35: vecWeight,
  };

  showSaveMsg(prefix, "Saving…", null);

  try {
    const endpoint = window.location.protocol.startsWith("http")
      ? "/api/config"
      : "http://127.0.0.1:8795/api/config";
    const res = await fetchWithTimeout(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: configName, updates: { pipeline: { analysis_stage: stage }, settings: { rag } } }),
    }, 10000);
    const data = await res.json();
    const ok = !!data.ok;
    showSaveMsg(prefix, ok ? "Saved." : data.message || "Error.", ok);
    showToast(ok ? `${configName} config saved.` : (data.message || "Save failed."), ok ? "success" : "error");
    if (ok) {
      _formDirty = false; _settingsLoaded = false;
      await loadSettings();
      // Show Apply & Restart button whenever AI pipeline is active (non-simple mode).
      const mode = getVal(`${configName}-pipeline-mode`);
      const applyBtn = byId(`${configName}-apply-btn`);
      if (applyBtn) applyBtn.style.display = mode !== "simple" ? "" : "none";
      updateRestartButtonVisibility(configName);
      if (configName === (_settingsData?.active_mode || "hybrid")) {
        showToast("Saved. Use Apply Retrieval Change to restart CB and activate the new vector backend.", "success", 5000);
      }
    }
  } catch (err) {
    showSaveMsg(prefix, err.message, false);
    showToast(err.message, "error");
  }
}

function showSaveMsg(prefix, text, ok) {
  const el = byId(`${prefix}-save-msg`);
  if (!el) return;
  el.textContent = text;
  el.className = `save-msg${ok === true ? " ok" : ok === false ? " error" : ""}`;
  if (ok !== null) setTimeout(() => { if (el) { el.textContent = ""; el.className = "save-msg"; } }, 3000);
}

async function applyModel(configName) {
  const model = getVal(`${configName}-model`);
  if (!model) { showToast("No model configured — fill in the Model field first.", "error"); return; }

  const btn      = byId(`${configName}-apply-btn`);
  const statusEl = byId(`${configName}-apply-status`);
  if (btn) btn.disabled = true;
  if (statusEl) { statusEl.textContent = "Starting…"; statusEl.className = "save-msg"; }

  try {
    const res  = await fetchWithTimeout("/api/apply-model", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model }),
    }, 6000);
    const data = await res.json();
    if (!data.ok) {
      if (statusEl) { statusEl.textContent = data.message || "Failed."; statusEl.className = "save-msg error"; }
      showToast(data.message || "Failed to start.", "error");
      if (btn) btn.disabled = false;
      return;
    }
  } catch (e) {
    if (statusEl) { statusEl.textContent = e.message; statusEl.className = "save-msg error"; }
    showToast(e.message, "error");
    if (btn) btn.disabled = false;
    return;
  }

  // Poll status every 2 s until done or error.
  const poll = setInterval(async () => {
    try {
      const r = await fetch("/api/apply-model-status");
      const s = await r.json();
      if (statusEl) statusEl.textContent = s.message;
      if (s.status === "done") {
        clearInterval(poll);
        if (statusEl) { statusEl.className = "save-msg ok"; setTimeout(() => { statusEl.textContent = ""; statusEl.className = "save-msg"; }, 5000); }
        if (btn)      { btn.style.display = "none"; btn.disabled = false; }
        showToast(s.message, "success", 5000);
      } else if (s.status === "error") {
        clearInterval(poll);
        if (statusEl) statusEl.className = "save-msg error";
        if (btn) btn.disabled = false;
        showToast(s.message, "error");
      }
    } catch (_) {}
  }, 2000);
}

async function restartContextBridge(configName) {
  const isActiveConfig = configName === (_settingsData?.active_mode || "hybrid");
  if (!isActiveConfig) {
    showToast(`Only the active ${_settingsData?.active_mode || "current"} config can be applied live.`, "error");
    return;
  }

  const btn = byId(`${configName}-restart-btn`);
  const statusEl = byId(`${configName}-restart-status`);
  if (btn) btn.disabled = true;
  if (statusEl) { statusEl.textContent = "Starting…"; statusEl.className = "save-msg"; }

  try {
    const res = await fetchWithTimeout("/api/restart-cb", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "CB restarted with updated retrieval settings ✓" }),
    }, 6000);
    const data = await res.json();
    if (!data.ok) {
      if (statusEl) { statusEl.textContent = data.message || "Failed."; statusEl.className = "save-msg error"; }
      showToast(data.message || "Failed to start restart.", "error");
      if (btn) btn.disabled = false;
      return;
    }
  } catch (e) {
    if (statusEl) { statusEl.textContent = e.message; statusEl.className = "save-msg error"; }
    showToast(e.message, "error");
    if (btn) btn.disabled = false;
    return;
  }

  const poll = setInterval(async () => {
    try {
      const r = await fetch("/api/restart-cb-status");
      const s = await r.json();
      if (statusEl) statusEl.textContent = s.message;
      if (s.status === "done") {
        clearInterval(poll);
        if (statusEl) { statusEl.className = "save-msg ok"; setTimeout(() => { statusEl.textContent = ""; statusEl.className = "save-msg"; }, 5000); }
        if (btn) btn.disabled = false;
        _settingsLoaded = false;
        await loadSettings();
        applyModeBadge(_settingsData?.active_runtime || _settingsData?.active_mode || "keyword");
        showToast(s.message, "success", 5000);
      } else if (s.status === "error") {
        clearInterval(poll);
        if (statusEl) statusEl.className = "save-msg error";
        if (btn) btn.disabled = false;
        showToast(s.message, "error");
      }
    } catch (_) {}
  }, 2000);
}

function setVal(id, value)  { const el = byId(id); if (el) el.value = value ?? ""; }
function getVal(id)         { return byId(id)?.value ?? ""; }
function setCheck(id, v)    { const el = byId(id); if (el) el.checked = !!v; }
function getCheck(id)       { return !!(byId(id)?.checked); }
