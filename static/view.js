/* View mode: list + filters + read-only SQL; results as heatmap, markers, cards and table. */
(function () {
  const map = createMap("map");
  const markers = L.featureGroup().addTo(map);
  const HEAT_GRADIENT = { 0.15: "#185FA5", 0.3: "#378ADD", 0.45: "#5DCAA5",
                          0.65: "#FFD600", 0.82: "#FF8800", 1.0: "#E91E92" };
  const heat = L.heatLayer ? L.heatLayer([], { radius: 34, blur: 26, minOpacity: 0.3,
                                               max: 1.0, maxZoom: 13, gradient: HEAT_GRADIENT }).addTo(map) : null;

  const $ = id => document.getElementById(id);
  const status = $("query-status"), table = $("results-table"), cards = $("cards");
  const drawer = $("drawer"), csvBtn = $("download-csv");
  const searchForm = $("search-form"), sqlForm = $("sql-form");
  const MAX_CARDS = 200;
  let current = { columns: [], rows: [] };
  const markersById = new Map();
  let firstFit = true;

  // ---- static UI: tabs, legend, selects ----
  document.querySelectorAll(".tab").forEach(btn => btn.addEventListener("click", () => {
    document.querySelectorAll(".tab, .tab-pane").forEach(el => el.classList.remove("active"));
    btn.classList.add("active");
    document.querySelector(`.tab-pane[data-pane="${btn.dataset.tab}"]`).classList.add("active");
  }));

  $("legend-types").innerHTML = CFG.eventTypes
    .map(t => `<li><i class="dot" style="background:${t.color}"></i>${escapeHtml(t.label)}</li>`).join("");
  $("f-type").insertAdjacentHTML("beforeend", CFG.eventTypes
    .map(t => `<option value="${escapeHtml(t.value)}">${escapeHtml(t.label)}</option>`).join(""));
  $("column-list").innerHTML = CFG.columns
    .map(c => `<li><code>${escapeHtml(c.name)}</code> <small>${escapeHtml(c.type)}</small></li>`).join("");
  $("sql-examples").addEventListener("change", e => { if (e.target.value) $("f-sql").value = e.target.value; });

  function setToggle(btn, on) { btn.classList.toggle("on", on); btn.setAttribute("aria-pressed", on); }
  $("toggle-heat").addEventListener("click", e => {
    const on = !e.currentTarget.classList.contains("on");
    setToggle(e.currentTarget, on);
    if (heat) (on ? heat.addTo(map) : map.removeLayer(heat));
  });
  function showDrawer(on) { drawer.hidden = !on; setToggle($("toggle-table"), on); map.invalidateSize(); }
  $("toggle-table").addEventListener("click", () => showDrawer(drawer.hidden));

  // ---- rendering ----
  function cardHtml(o) {
    const t = typeInfo(o.event_type);
    const badges = [
      isYes(o.verified) ? '<span class="badge yellow">Verifiziert</span>' : "",
      isYes(o.taken_into_custody) ? '<span class="badge magenta">In Gewahrsam</span>' : "",
      isYes(o.simulated) ? '<span class="badge">Simuliert</span>' : "",
    ].join("");
    const meta = [o.reported_at ? fmtDate(o.reported_at) : "", fmt(o.reporter_role, "reporter_role")]
      .filter(Boolean).map(escapeHtml).join(" · ");
    return `<li><button type="button" class="card" data-id="${escapeHtml(o.event_id)}">` +
      `<span class="card-title"><i class="dot" style="background:${t.color}"></i>${escapeHtml(t.label)}` +
      `<small>#${escapeHtml(o.event_id)}</small></span>` +
      `<span class="card-meta">${meta}</span>` +
      (badges ? `<span class="badges">${badges}</span>` : "") + `</button></li>`;
  }

  function render(columns, rows, { fromSql = false, note = "" } = {}) {
    current = { columns, rows };
    markers.clearLayers();
    markersById.clear();
    const objs = rows.map(r => Object.fromEntries(columns.map((c, i) => [c, r[i]])));
    const hasGeo = columns.includes("lat") && columns.includes("lon");
    const hasId = columns.includes("event_id");

    const heatPts = [];
    if (hasGeo) {
      for (const o of objs) {
        const lat = parseFloat(o.lat), lon = parseFloat(o.lon);
        if (isNaN(lat) || isNaN(lon)) continue;
        const m = L.circleMarker([lat, lon], markerStyle(o)).bindPopup(popupHtml(o));
        markers.addLayer(m);
        heatPts.push([lat, lon, 1]);
        if (hasId) markersById.set(String(o.event_id), m);
      }
      if (heatPts.length && (firstFit || fromSql)) {
        map.fitBounds(markers.getBounds().pad(0.15), { maxZoom: 15 });
        firstFit = false;
      }
    }
    if (heat) heat.setLatLngs(heatPts);

    // cards (only when rows are events)
    if (hasId && columns.includes("event_type")) {
      cards.innerHTML = objs.slice(0, MAX_CARDS).map(cardHtml).join("") ||
        '<li class="empty">Keine Meldungen für diese Auswahl.</li>';
    } else {
      cards.innerHTML = '<li class="empty">Das SQL-Ergebnis enthält keine einzelnen Meldungen – siehe Tabelle.</li>';
    }
    $("list-summary").textContent = `${rows.length} Treffer` +
      (rows.length > MAX_CARDS ? ` · die neuesten ${MAX_CARDS} in der Liste` : "") +
      (fromSql ? " · aus SQL-Abfrage" : "");

    // table
    table.innerHTML =
      "<thead><tr>" + columns.map(c => `<th>${escapeHtml(c)}</th>`).join("") + "</tr></thead><tbody>" +
      rows.map(r => `<tr data-id="${hasId ? escapeHtml(r[columns.indexOf("event_id")]) : ""}">` +
        r.map((v, i) => `<td>${escapeHtml(fmt(v, columns[i]))}</td>`).join("") + "</tr>").join("") + "</tbody>";
    $("result-summary").textContent = `${rows.length} Zeile(n)` +
      (hasGeo ? `, ${heatPts.length} auf der Karte` : " – ohne lat/lon, nicht auf der Karte") + note;
    csvBtn.disabled = rows.length === 0;
  }

  function focusEvent(id) {
    const m = markersById.get(String(id));
    if (m) { map.setView(m.getLatLng(), Math.max(map.getZoom(), 15)); m.openPopup(); }
  }
  cards.addEventListener("click", e => { const b = e.target.closest(".card"); if (b) focusEvent(b.dataset.id); });
  table.addEventListener("click", e => { const tr = e.target.closest("tr[data-id]"); if (tr && tr.dataset.id) focusEvent(tr.dataset.id); });

  // ---- structured search ----
  async function runSearch() {
    const params = new URLSearchParams();
    const q = $("q").value.trim();
    if (q) params.set("q", q);
    for (const [k, v] of new FormData(searchForm).entries()) {
      if (v && k !== "in_view") params.set(k, v);
    }
    if ($("f-inview").checked) params.set("bbox", map.getBounds().toBBoxString());
    setStatus(status, "Suche …");
    try {
      const data = await api("/api/events?" + params);
      const cols = CFG.columns.map(c => c.name);
      render(cols, data.events.map(ev => cols.map(c => ev[c])));
      setStatus(status, "");
    } catch (err) { setStatus(status, err.message, "error"); }
  }
  searchForm.addEventListener("submit", e => { e.preventDefault(); syncRangeChips(); runSearch(); });
  searchForm.addEventListener("reset", () => setTimeout(() => { syncRangeChips(); runSearch(); }, 0));
  $("quick-search").addEventListener("submit", e => { e.preventDefault(); runSearch(); });

  // time-range chips fill the "Von" date
  const isoDay = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  function syncRangeChips(activeBtn = null) {
    document.querySelectorAll("#range-chips .chip-btn").forEach(b => b.classList.toggle("active", b === activeBtn));
    if (!activeBtn && !$("f-from").value && !$("f-to").value) {
      document.querySelector('#range-chips [data-days=""]').classList.add("active");
    }
  }
  $("range-chips").addEventListener("click", e => {
    const btn = e.target.closest(".chip-btn");
    if (!btn) return;
    const days = btn.dataset.days;
    $("f-to").value = "";
    if (days === "") { $("f-from").value = ""; }
    else { const d = new Date(); d.setDate(d.getDate() - Number(days)); $("f-from").value = isoDay(d); }
    syncRangeChips(btn);
    runSearch();
  });

  // ---- SQL console ----
  async function runSql() {
    setStatus(status, "Abfrage läuft …");
    try {
      const data = await api("/api/sql", { method: "POST", body: JSON.stringify({ sql: $("f-sql").value }) });
      render(data.columns, data.rows, { fromSql: true,
        note: data.truncated ? ` – gekürzt auf ${CFG.sqlMaxRows}` : "" });
      showDrawer(true);
      setStatus(status, "");
    } catch (err) { setStatus(status, err.message, "error"); }
  }
  sqlForm.addEventListener("submit", e => { e.preventDefault(); runSql(); });
  $("f-sql").addEventListener("keydown", e => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); runSql(); }
  });

  // ---- CSV export of whatever is currently shown (raw values) ----
  csvBtn.addEventListener("click", () => {
    const raw = v => (v === null || v === undefined ? "" : String(v));
    const esc = v => { const s = raw(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const csv = [current.columns, ...current.rows].map(r => r.map(esc).join(",")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `watchpol-${new Date().toISOString().slice(0, 19).replace(/:/g, "")}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  });

  runSearch();
})();
