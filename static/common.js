/* Shared helpers for both modes. */
const CFG = window.APP_CONFIG || {};

function createMap(elId) {
  const map = L.map(elId, { zoomControl: false }).setView(CFG.mapCenter, CFG.mapZoom);
  L.control.zoom({ position: "topright" }).addTo(map);
  L.tileLayer(CFG.tileUrl, { maxZoom: 19, attribution: CFG.tileAttribution }).addTo(map);
  return map;
}

function escapeHtml(v) {
  return String(v ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function isYes(v) { return v === true || v === 1 || v === "1" || v === "yes"; }

/* ---- schema lookups ---- */
const optValue = o => (typeof o === "object" ? o.value : o);
const optLabel = o => (typeof o === "object" ? o.label : o);

function typeInfo(value) {
  return (CFG.eventTypes || []).find(t => t.value === value)
    || { value, label: value ?? "", color: "#AAAAAA" };
}

function fieldDef(name) { return (CFG.fields || []).find(f => f.name === name); }

const CORE_LABELS = {
  event_id: "ID", event_type: "Art des Vorfalls", verified: "Verifiziert",
  simulated: "Simuliert", reported_at: "Gemeldet", lat: "Breite", lon: "Länge",
};
function fieldLabel(name) {
  const f = fieldDef(name);
  return f ? f.label : (CORE_LABELS[name] || name);
}

function fmtDate(v) {
  const d = new Date(v);
  if (isNaN(d)) return String(v);
  return d.toLocaleString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric",
                                     hour: "2-digit", minute: "2-digit" });
}

/* Display text for one value of one column. */
function fmt(v, name) {
  if (v === true) return "ja";
  if (v === false) return "nein";
  if (v === null || v === undefined) return "";
  if (name === "event_type") return typeInfo(v).label;
  if (name === "reported_at") return fmtDate(v);
  const f = name && fieldDef(name);
  if (f && f.type === "select") {
    const o = (f.options || []).find(o => optValue(o) === v);
    if (o) return optLabel(o);
  }
  return String(v);
}

/* Marker: fill = category colour, white ring = verified, hollow + dashed = simulated. */
function markerStyle(row) {
  const color = typeInfo(row.event_type).color;
  const sim = isYes(row.simulated);
  return { radius: 7, weight: 2, color: isYes(row.verified) ? "#FFFFFF" : color,
           fillColor: color, fillOpacity: sim ? 0.15 : 0.9, dashArray: sim ? "3 3" : null };
}

function popupHtml(row) {
  const rows = Object.entries(row)
    .filter(([k, v]) => !["lat", "lon"].includes(k) && v !== null && v !== "")
    .map(([k, v]) => `<tr><th>${escapeHtml(fieldLabel(k))}</th><td>${escapeHtml(fmt(v, k))}</td></tr>`)
    .join("");
  return `<table class="popup">${rows}</table>`;
}

async function api(url, opts = {}) {
  const res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) { const err = new Error(body.error || res.statusText); err.body = body; throw err; }
  return body;
}

function setStatus(el, msg, kind = "") {
  el.textContent = msg;
  el.className = "status " + kind;
}

/* Sidebar numbers (only rendered for the view role). */
async function loadStats() {
  const box = document.getElementById("stats");
  if (!box) return;
  try {
    const s = await api("/api/stats");
    box.querySelectorAll("[data-stat]").forEach(el => { el.textContent = s[el.dataset.stat] ?? "–"; });
  } catch (_) { /* sidebar stats are optional */ }
}
loadStats();
