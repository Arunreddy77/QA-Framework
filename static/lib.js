// Shared helpers for all six screens. No framework, no build step, no charting
// library -- charts are hand-built SVG/CSS per the design brief.

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return res.status === 204 ? null : res.json();
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function qs(name) {
  return new URLSearchParams(location.search).get(name);
}

function fmtDate(input) {
  if (!input) return "—";
  const d = typeof input === "number" ? new Date(input * 1000) : new Date(input);
  if (isNaN(d)) return "—";
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return sameDay ? `Today, ${time}` : `${d.toLocaleDateString([], { month: "short", day: "numeric" })}, ${time}`;
}

function fmtElapsed(seconds) {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60), s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

// status -> {label, chipClass} used consistently across Library/Report/Dashboard.
const STATUS_META = {
  complete:        { label: "Complete",      chip: "chip-good" },
  running:         { label: "Running",       chip: "chip-warn" },
  starting:        { label: "Starting",      chip: "chip-warn" },
  paused_at_h1:    { label: "Needs review",  chip: "chip-warn" },
  rejected_at_h1:  { label: "Rejected",      chip: "chip-bad" },
  escalated:       { label: "Escalated",     chip: "chip-bad" },
  failed:          { label: "Failed",        chip: "chip-bad" },
  unknown_or_idle: { label: "Idle",          chip: "chip-neutral" },
  not_found:       { label: "Not found",     chip: "chip-neutral" },
};
function statusMeta(status) {
  return STATUS_META[status] || { label: status || "Unknown", chip: "chip-neutral" };
}
function statusChipHtml(status) {
  const m = statusMeta(status);
  return `<span class="chip ${m.chip}">${escapeHtml(m.label)}</span>`;
}

// ---- Ring (donut) chart: SVG circle, stroke-dasharray for the arc. ----
function renderRing(pct, opts = {}) {
  const size = opts.size || 140;
  const stroke = opts.stroke || 14;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const value = pct == null ? 0 : pct;
  const offset = c * (1 - value / 100);
  const color = opts.color || (value >= 90 ? "var(--good)" : value >= 60 ? "var(--warn)" : "var(--bad)");
  const label = pct == null ? "—" : `${value}%`;
  return `
    <div class="ring-wrap" style="width:${size}px;height:${size}px;">
      <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
        <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="var(--gridline)" stroke-width="${stroke}" />
        <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="${color}" stroke-width="${stroke}"
          stroke-dasharray="${c}" stroke-dashoffset="${offset}" stroke-linecap="round"
          transform="rotate(-90 ${size/2} ${size/2})" />
      </svg>
      <div class="ring-label">
        <div class="ring-pct">${label}</div>
        ${opts.sub ? `<div class="ring-sub">${escapeHtml(opts.sub)}</div>` : ""}
      </div>
    </div>`;
}

// ---- Trend line: plain SVG polyline with markers, last point highlighted. ----
function renderTrendLine(points, opts = {}) {
  const w = opts.width || 560, h = opts.height || 160, pad = 28;
  const usable = points.filter(p => p.pass_rate != null);
  if (usable.length === 0) return `<div class="empty-state">Not enough data yet.</div>`;
  const xs = (i) => pad + (i / Math.max(usable.length - 1, 1)) * (w - pad * 2);
  const ys = (v) => h - pad - (v / 100) * (h - pad * 2);
  const coords = usable.map((p, i) => [xs(i), ys(p.pass_rate)]);
  const poly = coords.map(([x, y]) => `${x},${y}`).join(" ");

  const gridLines = [0, 50, 100].map(v => `
    <line x1="${pad}" y1="${ys(v)}" x2="${w - pad}" y2="${ys(v)}" stroke="var(--gridline)" stroke-width="1" />
    <text x="2" y="${ys(v) + 4}" font-size="10" fill="var(--text-muted)">${v}</text>`).join("");

  const dots = coords.map(([x, y], i) => {
    const last = i === coords.length - 1;
    return `<circle cx="${x}" cy="${y}" r="${last ? 4.5 : 3}" fill="${last ? "var(--accent)" : "#fff"}" stroke="var(--accent)" stroke-width="2" />`;
  }).join("");

  const xLabels = usable.map((p, i) => {
    if (usable.length > 8 && i % Math.ceil(usable.length / 8) !== 0 && i !== usable.length - 1) return "";
    return `<text x="${xs(i)}" y="${h - 6}" font-size="10" fill="var(--text-muted)" text-anchor="middle">${escapeHtml(p.label || "")}</text>`;
  }).join("");

  return `<svg width="100%" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet">
    ${gridLines}
    <polyline points="${poly}" fill="none" stroke="var(--accent)" stroke-width="2" />
    ${dots}
    ${xLabels}
  </svg>`;
}

// ---- Horizontal bar chart: styled <div> bars, no library. ----
function renderBarChart(rows, opts = {}) {
  const max = Math.max(1, ...rows.map(r => r.value));
  const colors = opts.colors || ["var(--accent)", "var(--series-2)", "var(--series-3)"];
  return rows.map((r, i) => `
    <div class="bar-row">
      <div>${escapeHtml(r.label)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(r.value / max) * 100}%;background:${colors[i % colors.length]}"></div></div>
      <div class="mono">${r.value}</div>
    </div>`).join("");
}

function sidebarNav(active) {
  const items = [
    ["/static/dashboard.html", "Dashboard"],
    ["/static/library.html", "Requirements"],
    ["/", "New run"],
    ["/static/library.html", "Reports"],
    ["/static/knowledge-store.html", "Knowledge store"],
  ];
  return `
    <div class="sidebar">
      <div class="brand"><span class="mark">✓</span> QA Framework</div>
      <nav>
        ${items.map(([href, label]) => `<a href="${href}" class="${label === active ? "active" : ""}">${label}</a>`).join("")}
      </nav>
      <div class="user-chip-row">
        <div class="user-chip">RK</div>
        <div><div style="font-weight:600;font-size:0.82rem;">Rajesh</div><div class="muted" style="font-size:0.72rem;">Cognitivzen</div></div>
      </div>
    </div>`;
}

function topbarNav(active) {
  const items = [["/", "New run"], ["/static/library.html", "Run history"], ["/static/knowledge-store.html", "Knowledge store"]];
  return `
    <div class="topbar">
      <div class="brand"><span class="mark">✓</span> QA Framework</div>
      <nav>${items.map(([href, label]) => `<a href="${href}" class="${label === active ? "active" : ""}">${label}</a>`).join("")}</nav>
      <div class="user-chip">RK</div>
    </div>`;
}
