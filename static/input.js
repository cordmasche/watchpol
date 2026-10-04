/* Input mode: tap map -> fill form -> POST /api/events */
(function () {
  const map = createMap("map");
  const form = document.getElementById("event-form");
  const status = document.getElementById("form-status");
  const hint = document.getElementById("map-hint");
  let marker = null;

  const chip = (name, value, label, color) =>
    `<label class="chip"${color ? ` style="--chip:${color}"` : ""}>` +
    `<input type="radio" name="${name}" value="${escapeHtml(value)}"><span>${escapeHtml(label)}</span></label>`;

  // ---- category chips ----
  document.getElementById("type-chips").innerHTML =
    CFG.eventTypes.map(t => chip("event_type", t.value, t.label, t.color)).join("");

  // ---- fields from schema.py ----
  function fieldHtml(f) {
    const star = f.required ? " *" : "";
    const err = `<span class="err" data-for="${f.name}"></span>`;
    const group = inner =>
      `<fieldset class="group"><legend>${escapeHtml(f.label)}${star}</legend>${inner}${err}</fieldset>`;

    if (f.type === "boolean") {
      return group(`<div class="chip-row">${chip(f.name, "yes", "Ja")}` +
        `<label class="chip"><input type="radio" name="${f.name}" value="no" checked><span>Nein</span></label></div>`);
    }
    if (f.type === "select" && (f.options || []).length <= 4) {
      return group(`<div class="chip-col">` +
        f.options.map(o => chip(f.name, optValue(o), optLabel(o))).join("") + `</div>`);
    }
    const id = `f-${f.name}`;
    let input;
    switch (f.type) {
      case "textarea": input = `<textarea id="${id}" name="${f.name}" rows="3"></textarea>`; break;
      case "select":
        input = `<select id="${id}" name="${f.name}"><option value=""></option>` +
          f.options.map(o => `<option value="${escapeHtml(optValue(o))}">${escapeHtml(optLabel(o))}</option>`).join("") +
          "</select>";
        break;
      case "number": input = `<input id="${id}" name="${f.name}" type="number" step="any">`; break;
      case "integer": input = `<input id="${id}" name="${f.name}" type="number" step="1">`; break;
      case "date": input = `<input id="${id}" name="${f.name}" type="date">`; break;
      case "datetime": input = `<input id="${id}" name="${f.name}" type="datetime-local">`; break;
      default: input = `<input id="${id}" name="${f.name}" type="text">`;
    }
    return group(input);
  }
  const mainBox = document.getElementById("main-fields");
  const extraBox = document.getElementById("extra-fields");
  for (const f of CFG.fields) {
    (f.group === "extra" ? extraBox : mainBox).insertAdjacentHTML("beforeend", fieldHtml(f));
  }

  // ---- location ----
  const pin = L.divIcon({ className: "pin", iconSize: [34, 34], iconAnchor: [17, 17],
    html: '<svg viewBox="0 0 34 34" width="34" height="34" aria-hidden="true">' +
          '<circle cx="17" cy="17" r="11" fill="none" stroke="#E91E92" stroke-width="2"/>' +
          '<path d="M17 0v34M0 17h34" stroke="#FFFFFF" stroke-width="1.5"/>' +
          '<circle cx="17" cy="17" r="4" fill="#FFD600"/></svg>' });

  function setCoords(lat, lon) {
    form.lat.value = (+lat).toFixed(6);
    form.lon.value = (+lon).toFixed(6);
  }
  function placeMarker(lat, lon, pan = false) {
    if (!marker) {
      marker = L.marker([lat, lon], { draggable: true, icon: pin }).addTo(map);
      marker.on("dragend", () => { const p = marker.getLatLng(); setCoords(p.lat, p.lng); });
    } else {
      marker.setLatLng([lat, lon]);
    }
    hint.hidden = true;
    clearErr("lat");
    if (pan) map.setView([lat, lon], Math.max(map.getZoom(), 15));
  }

  map.on("click", e => { setCoords(e.latlng.lat, e.latlng.lng); placeMarker(e.latlng.lat, e.latlng.lng); });

  // a correction clears that field's error message
  const clearErr = name => { const el = form.querySelector(`.err[data-for="${name}"]`); if (el) el.textContent = ""; };
  form.addEventListener("input", e => {
    if (!e.target.name) return;
    clearErr(e.target.name === "lon" ? "lat" : e.target.name);
    if (status.classList.contains("error")) setStatus(status, "");
  });

  for (const name of ["lat", "lon"]) {
    form[name].addEventListener("change", () => {
      const lat = parseFloat(form.lat.value), lon = parseFloat(form.lon.value);
      if (!isNaN(lat) && !isNaN(lon)) placeMarker(lat, lon, true);
    });
  }

  document.getElementById("locate").addEventListener("click", () => {
    if (!navigator.geolocation) return setStatus(status, "Standort ist auf diesem Gerät nicht verfügbar.", "error");
    navigator.geolocation.getCurrentPosition(
      pos => { setCoords(pos.coords.latitude, pos.coords.longitude);
               placeMarker(pos.coords.latitude, pos.coords.longitude, true); },
      err => setStatus(status, "Standort konnte nicht ermittelt werden: " + err.message, "error"));
  });

  // ---- submit ----
  form.addEventListener("submit", async e => {
    e.preventDefault();
    form.querySelectorAll(".err").forEach(el => (el.textContent = ""));
    const payload = Object.fromEntries(new FormData(form).entries());
    try {
      const ev = await api("/api/events", { method: "POST", body: JSON.stringify(payload) });
      setStatus(status, `Meldung #${ev.event_id} gespeichert.`, "ok");
      form.reset();
      if (marker) { map.removeLayer(marker); marker = null; }
      hint.hidden = false;
      loadStats();
    } catch (err) {
      const fields = (err.body && err.body.fields) || {};
      let firstErr = null;
      for (const [name, msg] of Object.entries(fields)) {
        const el = form.querySelector(`.err[data-for="${name === "lon" ? "lat" : name}"]`);
        if (el) { el.textContent = msg; firstErr = firstErr || el; }
      }
      if (firstErr) {
        const extra = firstErr.closest("details");
        if (extra) extra.open = true;
        firstErr.closest(".group").scrollIntoView({ block: "center", behavior: "smooth" });
      }
      const n = Object.keys(fields).length;
      setStatus(status, n ? "Nicht gespeichert – bitte die markierten Angaben prüfen."
                          : "Nicht gespeichert: " + err.message, "error");
    }
  });
})();
