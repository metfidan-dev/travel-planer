"use strict";

const LEG_COLORS = ["#e74c3c", "#27ae60", "#8e44ad", "#e67e22", "#16a085", "#2980b9", "#c0392b", "#f39c12"];

let wpCounter = 0;

const state = {
    map: null,
    waypoints: [],
    markers: {},
    legs: [],
    legLayers: [],
    weatherGroups: {},   // keyed by "day-N"
    trafficGroups: {},   // keyed by "day-N"
    mapView: "none",
    mode: "driving",
    curvePref: 1,
    sampleInterval: 20,
    searchTimer: null,
    autoRecalcTimer: null,
    dayDates: {},        // {N: {date, time, weatherFetched, trafficFetched}}
};

// ===== INIT =====
document.addEventListener("DOMContentLoaded", () => {
    initMap();
    bindControls();
    addWaypoint();
    addWaypoint();
});

function initMap() {
    state.map = L.map("map", { center: [44, 12], zoom: 5 });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
    }).addTo(state.map);
    state.map.on("click", onMapClick);
}

function bindControls() {
    document.getElementById("add-waypoint-btn").addEventListener("click", () => addWaypoint());
    document.getElementById("calculate-route-btn").addEventListener("click", () => calculateRoute());
    document.getElementById("clear-route-btn").addEventListener("click", clearAll);

    document.getElementById("sample-interval-select").addEventListener("change", (e) => {
        state.sampleInterval = parseInt(e.target.value, 10);
    });

    document.querySelectorAll(".mode-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".mode-btn").forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            state.mode = btn.dataset.mode;
            document.getElementById("curves-control").classList.toggle("hidden", state.mode !== "motorcycle");
            scheduleRecalculate();
        });
    });

    document.addEventListener("click", (e) => {
        if (!e.target.closest(".waypoint-search") && !e.target.closest("#search-suggestions")) {
            hideSuggestions();
        }
    });
}

function onCurvesChange(val) {
    state.curvePref = parseInt(val, 10);
    document.getElementById("curves-badge").textContent = `${val} / 5`;
    state.legs.forEach((l) => { l.curves = state.curvePref; });
    scheduleRecalculate();
}

// ===== AUTO RECALCULATE =====
function scheduleRecalculate() {
    clearTimeout(state.autoRecalcTimer);
    // Save only per-leg curves; day dates/fetched flags live in state.dayDates
    const savedLegCurves = state.legs.map((l) => l.curves ?? state.curvePref);
    state.autoRecalcTimer = setTimeout(() => {
        const valid = state.waypoints.filter((w) => w.lat && w.lon);
        if (valid.length >= 2) calculateRoute(savedLegCurves.length ? savedLegCurves : null);
    }, 900);
}

// ===== DAY HELPERS =====
function computeWaypointDays() {
    let day = 0;
    return state.waypoints.map((wp, i) => {
        if (i > 0 && wp.startNewDay) day++;
        return day;
    });
}

function toggleDaySplit(wpId) {
    const wp = state.waypoints.find((w) => w.id === wpId);
    if (!wp) return;
    wp.startNewDay = !wp.startNewDay;
    renderWaypoints();
    scheduleRecalculate();
}

// Concatena le geometrie di tutti i tratti di un giorno
function getDayGeometry(dayIdx) {
    const dayLegs = state.legs.filter((l) => l.day === dayIdx);
    if (!dayLegs.length) return null;
    let coords = [...dayLegs[0].geometry.coordinates];
    for (let i = 1; i < dayLegs.length; i++) {
        const c = dayLegs[i].geometry.coordinates;
        coords = coords.concat(c.slice(1)); // salta il primo punto (duplicato)
    }
    return { type: "LineString", coordinates: coords };
}

function getDayStats(dayIdx) {
    const dayLegs = state.legs.filter((l) => l.day === dayIdx);
    return {
        duration_sec: dayLegs.reduce((s, l) => s + (l.duration_sec || 0), 0),
        distance_km:  dayLegs.reduce((s, l) => s + (parseFloat(l.distance_km) || 0), 0),
    };
}

// ===== WAYPOINTS =====
function addWaypoint(name = "", lat = null, lon = null, startNewDay = false) {
    const id = ++wpCounter;
    state.waypoints.push({ id, name, lat, lon, startNewDay });
    renderWaypoints();
    if (lat && lon) syncMarker(id);
    return id;
}

function removeWaypoint(id) {
    removeMarker(id);
    state.waypoints = state.waypoints.filter((w) => w.id !== id);
    if (state.waypoints.length > 0) state.waypoints[0].startNewDay = false;
    renderWaypoints();
    clearLegs();
    scheduleRecalculate();
}

function updateWp(id, patch) {
    const wp = state.waypoints.find((w) => w.id === id);
    if (wp) Object.assign(wp, patch);
}

function renderWaypoints() {
    const list  = document.getElementById("waypoints-list");
    list.innerHTML = "";
    const count = state.waypoints.length;
    const days  = computeWaypointDays();

    state.waypoints.forEach((wp, idx) => {
        const isFirst  = idx === 0;
        const isLast   = idx === count - 1;
        const dayIdx   = days[idx];
        const dayColor = LEG_COLORS[dayIdx % LEG_COLORS.length];

        if (isFirst || wp.startNewDay) {
            const hdr = document.createElement("div");
            hdr.className = "day-header";
            hdr.innerHTML = `
              <span class="day-header-line" style="background:${dayColor}"></span>
              <span class="day-header-label" style="background:${dayColor}">&#128197; Giorno ${dayIdx + 1}</span>
              <span class="day-header-line" style="background:${dayColor}"></span>
            `;
            list.appendChild(hdr);
        }

        const label    = isFirst ? "Partenza" : isLast ? "Arrivo" : `Tappa ${idx}`;
        const dotColor = isLast ? "#ea4335" : dayColor;

        const div = document.createElement("div");
        div.className    = "waypoint-item";
        div.dataset.wpid = wp.id;
        div.innerHTML = `
          <div class="waypoint-header">
            <div class="waypoint-badge${isLast && idx > 0 ? " is-last" : ""}">${idx + 1}</div>
            <div class="wp-leg-dot" style="background:${dotColor}"></div>
            <span class="waypoint-label">${escHtml(wp.name || label)}</span>
            ${!isFirst
                ? `<button class="btn-day-split${wp.startNewDay ? " active" : ""}"
                     onclick="toggleDaySplit(${wp.id})"
                     title="${wp.startNewDay ? "Rimuovi separatore" : "Inizia nuovo giorno"}">&#128197;</button>`
                : ""}
            ${count > 2 ? `<button class="btn-delete" onclick="removeWaypoint(${wp.id})">&#10005;</button>` : ""}
          </div>
          <div class="waypoint-search">
            <input class="wp-search-input" type="text" placeholder="Cerca un luogo..."
              value="${escHtml(wp.name)}" data-wpid="${wp.id}"
              oninput="onSearchInput(this)" onfocus="onSearchFocus(${wp.id})" />
            <button class="btn-search" onclick="triggerSearch(${wp.id})">&#128269;</button>
          </div>
        `;
        list.appendChild(div);
    });

    refreshAllMarkers();
}

// ===== MARKERS =====
function makeIcon(idx, total) {
    const isLast = idx === total - 1 && total > 1;
    const bg = isLast ? "#ea4335" : "#1a73e8";
    return L.divIcon({
        html: `<div style="background:${bg};color:white;width:28px;height:28px;border-radius:50% 50% 50% 0;
                transform:rotate(-45deg);display:flex;align-items:center;justify-content:center;
                font-size:11px;font-weight:700;box-shadow:0 2px 6px rgba(0,0,0,.3)">
                <span style="transform:rotate(45deg)">${idx + 1}</span></div>`,
        className: "",
        iconSize: [28, 28], iconAnchor: [14, 28], popupAnchor: [0, -28],
    });
}

function syncMarker(id) {
    const wp = state.waypoints.find((w) => w.id === id);
    if (!wp || !wp.lat) return;
    const idx   = state.waypoints.indexOf(wp);
    const total = state.waypoints.length;
    const popup = `<strong>${escHtml(wp.name || `Tappa ${idx + 1}`)}</strong>`;

    if (state.markers[id]) {
        state.markers[id].setLatLng([wp.lat, wp.lon]);
        state.markers[id].setIcon(makeIcon(idx, total));
        state.markers[id].getPopup()?.setContent(popup);
    } else {
        const m = L.marker([wp.lat, wp.lon], { icon: makeIcon(idx, total), draggable: true })
            .bindPopup(popup).addTo(state.map);
        m.on("dragend", async (e) => {
            const { lat, lng } = e.target.getLatLng();
            const name = await reverseGeocode(lat, lng);
            updateWp(id, { lat, lon: lng, name });
            renderWaypoints();
            clearLegs();
            scheduleRecalculate();
        });
        state.markers[id] = m;
    }
}

function removeMarker(id) {
    if (state.markers[id]) { state.markers[id].remove(); delete state.markers[id]; }
}

function refreshAllMarkers() {
    const ids = new Set(state.waypoints.map((w) => w.id));
    Object.keys(state.markers).forEach((k) => { if (!ids.has(Number(k))) removeMarker(Number(k)); });
    state.waypoints.forEach((wp) => { if (wp.lat) syncMarker(wp.id); });
}

// ===== MAP CLICK =====
async function onMapClick(e) {
    const empty = state.waypoints.find((w) => !w.lat);
    if (!empty) return;
    showLoading(true);
    try {
        const { lat, lng } = e.latlng;
        const name = await reverseGeocode(lat, lng);
        updateWp(empty.id, { lat, lon: lng, name });
        const input = document.querySelector(`.wp-search-input[data-wpid="${empty.id}"]`);
        if (input) input.value = name;
        const lbl = document.querySelector(`.waypoint-item[data-wpid="${empty.id}"] .waypoint-label`);
        if (lbl) lbl.textContent = name;
        syncMarker(empty.id);
        state.map.setView([lat, lng], Math.max(state.map.getZoom(), 10));
        scheduleRecalculate();
    } finally { showLoading(false); }
}

// ===== SEARCH =====
function onSearchFocus(id) { /* reserved */ }

function onSearchInput(input) {
    const id = Number(input.dataset.wpid);
    updateWp(id, { name: input.value, lat: null, lon: null });
    removeMarker(id);
    clearLegs();
    clearTimeout(state.searchTimer);
    if (input.value.length < 3) { hideSuggestions(); return; }
    state.searchTimer = setTimeout(() => doSearch(input.value, id, input), 380);
}

function triggerSearch(id) {
    const input = document.querySelector(`.wp-search-input[data-wpid="${id}"]`);
    if (input && input.value.length >= 2) doSearch(input.value, id, input);
}

async function doSearch(query, id, inputEl) {
    try {
        const res = await fetch("/api/geocode", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query }),
        });
        const results = await res.json();
        showSuggestions(Array.isArray(results) ? results : [], id, inputEl);
    } catch (err) { console.error("Geocoding error:", err); }
}

function showSuggestions(results, id, inputEl) {
    const box = document.getElementById("search-suggestions");
    box.innerHTML = "";
    if (!results.length) { hideSuggestions(); return; }
    const rect = inputEl.getBoundingClientRect();
    box.style.top   = `${rect.bottom + 4}px`;
    box.style.left  = `${rect.left}px`;
    box.style.width = `${rect.width + 46}px`;
    box.classList.remove("hidden");
    results.slice(0, 6).forEach((r) => {
        const item = document.createElement("div");
        item.className   = "suggestion-item";
        item.textContent = r.display_name;
        item.addEventListener("click", () => { selectPlace(id, r); hideSuggestions(); });
        box.appendChild(item);
    });
}

function hideSuggestions() {
    document.getElementById("search-suggestions").classList.add("hidden");
}

function selectPlace(id, result) {
    const lat  = parseFloat(result.lat);
    const lon  = parseFloat(result.lon);
    const name = result.display_name.split(",").slice(0, 2).join(", ").trim();
    updateWp(id, { lat, lon, name });
    const input = document.querySelector(`.wp-search-input[data-wpid="${id}"]`);
    if (input) input.value = name;
    const lbl = document.querySelector(`.waypoint-item[data-wpid="${id}"] .waypoint-label`);
    if (lbl) lbl.textContent = name;
    syncMarker(id);
    state.map.setView([lat, lon], Math.max(state.map.getZoom(), 10));
    clearLegs();
    scheduleRecalculate();
}

// ===== ROUTING =====
async function calculateRoute(savedLegCurves = null) {
    const valid = state.waypoints.filter((w) => w.lat && w.lon);
    if (valid.length < 2) {
        if (!savedLegCurves) alert("Aggiungi almeno 2 tappe con posizione valida prima di calcolare il percorso.");
        return;
    }
    showLoading(true);
    try {
        const curvesPerLeg = Array.from({ length: valid.length - 1 }, (_, i) =>
            savedLegCurves?.[i] ?? state.curvePref
        );

        const res = await fetch("/api/route", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                waypoints:      valid.map((w) => ({ lat: w.lat, lon: w.lon })),
                profile:        state.mode,
                curves:         state.curvePref,
                curves_per_leg: state.mode === "motorcycle" ? curvesPerLeg : [],
            }),
        });
        const data = await res.json();
        if (data.error) { if (!savedLegCurves) alert("Errore percorso: " + data.error); return; }

        const allDays   = computeWaypointDays();
        const validDays = state.waypoints
            .filter((wp) => wp.lat && wp.lon)
            .map((wp) => allDays[state.waypoints.indexOf(wp)]);

        state.legs = data.legs.map((leg, i) => {
            const dayIdx = validDays[i] ?? 0;
            return {
                ...leg,
                color:          LEG_COLORS[dayIdx % LEG_COLORS.length],
                day:            dayIdx,
                fromName:       valid[i]?.name     || `Tappa ${i + 1}`,
                toName:         valid[i + 1]?.name || `Tappa ${i + 2}`,
                curves:         curvesPerLeg[i] ?? state.curvePref,
            };
        });

        // Ensure dayDates has an entry for every day
        const maxDay = Math.max(...state.legs.map((l) => l.day), 0);
        for (let d = 0; d <= maxDay; d++) {
            if (!state.dayDates[d]) state.dayDates[d] = { date: "", time: "09:00", weatherFetched: false, trafficFetched: false };
        }

        drawLegsOnMap();
        buildLegsPanel(data.total_distance_km, data.total_duration_formatted);

        const allLL = state.legs.flatMap((l) => l.geometry.coordinates.map(([ln, lt]) => [lt, ln]));
        if (allLL.length) state.map.fitBounds(L.latLngBounds(allLL), { padding: [30, 30] });

        // Re-fetch meteo/traffico per i giorni che li avevano già caricati
        if (savedLegCurves) {
            for (let d = 0; d <= maxDay; d++) {
                const dd = state.dayDates[d];
                if (!dd?.date) continue;
                if (dd.weatherFetched) fetchWeatherDay(d);
                if (dd.trafficFetched)  fetchTrafficDay(d);
            }
        }
    } catch (err) {
        if (!savedLegCurves) alert("Errore di connessione durante il calcolo del percorso.");
        console.error(err);
    } finally { showLoading(false); }
}

// ===== MAPPA: POLILINEE =====
function drawLegsOnMap() {
    state.legLayers.forEach((l) => l.remove());
    state.legLayers = [];
    clearAllWeatherMarkers();
    clearAllTrafficMarkers();
    state.mapView = "none";
    document.getElementById("map-layer-toggle")?.classList.add("hidden");

    state.legs.forEach((leg) => {
        const layer = L.geoJSON(leg.geometry, {
            style: { color: leg.color, weight: 5, opacity: 0.88 },
        }).addTo(state.map);
        state.legLayers.push(layer);
    });
}

// ===== SIDEBAR: PANNELLO TRATTI =====
function buildLegsPanel(totalDistKm, totalDurFmt) {
    document.getElementById("legs-panel")?.remove();

    const panel = document.createElement("div");
    panel.id        = "legs-panel";
    panel.className = "panel";

    const motoNote = state.mode === "motorcycle"
        ? `<div class="moto-info">&#127949; Moto &mdash; curve selezionabili per tratto</div>`
        : "";

    panel.innerHTML = `
      <div class="panel-title">Percorso calcolato</div>
      ${motoNote}
      <div id="summary-stats">
        <div class="stat-box"><div class="stat-label">Distanza totale</div><div class="stat-value">${totalDistKm} km</div></div>
        <div class="stat-box"><div class="stat-label">Tempo totale</div><div class="stat-value">${totalDurFmt}</div></div>
      </div>
      <button id="export-gmaps-btn" onclick="exportToGoogleMaps()">&#127758; Apri su Google Maps</button>
      <div id="legs-list"></div>
    `;
    document.getElementById("sidebar-body").appendChild(panel);
    const legsList = panel.querySelector("#legs-list");

    const maxDay = state.legs.reduce((m, l) => Math.max(m, l.day), 0);

    for (let d = 0; d <= maxDay; d++) {
        const dayLegs  = state.legs.filter((l) => l.day === d);
        if (!dayLegs.length) continue;

        const dayColor   = LEG_COLORS[d % LEG_COLORS.length];
        const dayTotalKm = dayLegs.reduce((s, l) => s + (parseFloat(l.distance_km) || 0), 0).toFixed(1);
        const dd         = state.dayDates[d] || { date: "", time: "09:00" };

        // ── Day header ──────────────────────────────────────────────────────
        const sep = document.createElement("div");
        sep.className = "legs-day-header";
        sep.style.borderLeftColor = dayColor;
        sep.innerHTML = `
          <div class="legs-day-info">
            <span class="legs-day-dot" style="background:${dayColor}"></span>
            <span class="legs-day-title" style="color:${dayColor}">Giorno ${d + 1}</span>
            <span class="legs-day-km">${dayTotalKm} km</span>
          </div>
          <div class="legs-day-datetime">
            <input class="wp-date-input" type="date"
              value="${dd.date}" min="${todayStr()}" max="${maxDateStr()}"
              onchange="updateDayDate(${d}, 'date', this.value)" />
            <input class="wp-time-input" type="time"
              value="${dd.time || "09:00"}"
              onchange="updateDayDate(${d}, 'time', this.value)" />
          </div>
          <div class="legs-day-btns">
            <button class="btn-weather-seg" onclick="fetchWeatherDay(${d})">&#127780; Meteo</button>
            <button class="btn-traffic-seg" onclick="fetchTrafficDay(${d})">&#128678; Traffico</button>
          </div>
          <div class="seg-weather-container" id="seg-weather-day-${d}"></div>
          <div class="seg-traffic-container" id="seg-traffic-day-${d}"></div>
        `;
        legsList.appendChild(sep);

        // ── Leg cards ───────────────────────────────────────────────────────
        dayLegs.forEach((leg) => {
            const idx  = state.legs.indexOf(leg);
            const from = leg.fromName.split(",")[0];
            const to   = leg.toName.split(",")[0];

            const curvesHtml = state.mode === "motorcycle" ? `
              <div class="leg-curves-control">
                <div class="leg-curves-row">
                  <span class="leg-curves-label">&#127949; Curve</span>
                  <span class="leg-curves-badge" id="leg-curve-badge-${idx}">${leg.curves}/5</span>
                </div>
                <input class="leg-curves-slider" type="range" min="1" max="5"
                  value="${leg.curves}" step="1"
                  oninput="updateLegCurves(${idx}, +this.value)" />
                <div class="leg-curves-hints"><span>1 Diretto</span><span>5 Panoramico</span></div>
              </div>` : "";

            const card = document.createElement("div");
            card.className = "leg-card";
            card.id        = `leg-card-${idx}`;
            card.style.borderLeftColor = leg.color;
            card.innerHTML = `
              <div class="leg-card-header">
                <div class="leg-color-dot" style="background:${leg.color}"></div>
                <span class="leg-card-title">Tratto ${idx + 1}: ${escHtml(from)} &#8594; ${escHtml(to)}</span>
              </div>
              <div class="leg-card-stats">${leg.distance_km} km &middot; ${leg.duration_formatted}</div>
              <div class="leg-curvature" title="Sinuosità: ${leg.curvature_score} °/km">
                <span class="curve-dots" style="color:${curveColor(leg.curvature_stars)}">${curveDots(leg.curvature_stars)}</span>
                <span class="curve-label">${escHtml(leg.curvature_label || "—")}</span>
                <span class="curve-score">${leg.curvature_score || 0} °/km</span>
              </div>
              ${curvesHtml}
            `;
            legsList.appendChild(card);
        });
    }
}

// ===== UPDATE HELPERS =====
function updateDayDate(dayIdx, key, val) {
    if (!state.dayDates[dayIdx]) state.dayDates[dayIdx] = { date: "", time: "09:00", weatherFetched: false, trafficFetched: false };
    state.dayDates[dayIdx][key] = val;
}

function updateLegCurves(legIdx, val) {
    if (!state.legs[legIdx]) return;
    state.legs[legIdx].curves = val;
    const badge = document.getElementById(`leg-curve-badge-${legIdx}`);
    if (badge) badge.textContent = `${val}/5`;
    scheduleRecalculate();
}

// ===== METEO GIORNALIERO =====
async function fetchWeatherDay(dayIdx) {
    const dd = state.dayDates[dayIdx];
    if (!dd?.date) {
        alert(`Seleziona una data per il Giorno ${dayIdx + 1} prima di richiedere le previsioni.`);
        return;
    }

    const geometry = getDayGeometry(dayIdx);
    const stats    = getDayStats(dayIdx);
    if (!geometry) return;

    const container = document.getElementById(`seg-weather-day-${dayIdx}`);
    if (!container) return;
    container.innerHTML = `<div class="seg-loading">&#9203; Recupero previsioni in corso...</div>`;

    showLoading(true);
    try {
        const res = await fetch("/api/weather-segment", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                geometry,
                date:         dd.date,
                time:         dd.time || "09:00",
                duration_sec: stats.duration_sec,
                distance_km:  stats.distance_km,
                interval_km:  state.sampleInterval,
            }),
        });
        const results = await res.json();

        if (!Array.isArray(results)) {
            container.innerHTML = `<div class="seg-error">&#9888; ${escHtml(results.error || "Errore sconosciuto")}</div>`;
            return;
        }

        const key   = `day-${dayIdx}`;
        const color = LEG_COLORS[dayIdx % LEG_COLORS.length];
        renderDayWeather(dayIdx, results, dd.time || "09:00", dd.date, color);
        renderWeatherMarkersOnMap(key, results);
        setMapView("weather");
        showMapToggle();
        state.dayDates[dayIdx].weatherFetched = true;
    } catch (err) {
        if (container) container.innerHTML = `<div class="seg-error">&#9888; Errore di connessione</div>`;
        console.error(err);
    } finally { showLoading(false); }
}

function renderDayWeather(dayIdx, results, departureTime, dateStr, color) {
    const container = document.getElementById(`seg-weather-day-${dayIdx}`);
    if (!container) return;

    const valid    = results.filter((r) => !r.error);
    const errCount = results.length - valid.length;
    if (!valid.length) { container.innerHTML = `<div class="seg-error">Nessun dato disponibile</div>`; return; }

    container.innerHTML = `
      <div class="seg-weather-header" style="border-left-color:${color}">
        Partenza ${fmtDate(dateStr)} ore ${departureTime} &mdash; ${valid.length} punti ogni ~${state.sampleInterval} km
        ${errCount > 0 ? `<span class="seg-warn">(${errCount} non disp.)</span>` : ""}
      </div>
      <div class="seg-weather-row" id="seg-chips-day-${dayIdx}"></div>
    `;

    const row = container.querySelector(`#seg-chips-day-${dayIdx}`);
    valid.forEach((pt) => {
        const chip = document.createElement("div");
        chip.className = "seg-weather-chip";
        chip.style.borderTopColor = tempColor(pt.temperature);
        chip.innerHTML = `
          <div class="chip-dist">${pt.dist_km}&nbsp;km</div>
          <div class="chip-time">&#128336;${pt.estimated_time}</div>
          <div class="chip-icon">${pt.weather_icon}</div>
          <div class="chip-temp">${pt.temperature}°C</div>
          <div class="chip-precip">&#128167;${pt.precipitation_probability}%</div>
          <div class="chip-wind">&#128168;${pt.windspeed}</div>
        `;
        chip.title = [
            `Stima: ${pt.estimated_time} (${fmtDate(pt.estimated_date)})`,
            pt.weather_description,
            `Temp: ${pt.temperature}°C (perc. ${pt.apparent_temperature}°C)`,
            `Vento: ${pt.windspeed} km/h ${compassDir(pt.winddirection)}`,
            `Pioggia: ${pt.precipitation_probability}%`,
        ].join("\n");
        row.appendChild(chip);
    });
}

// ===== TRAFFICO GIORNALIERO =====
async function fetchTrafficDay(dayIdx) {
    const dd = state.dayDates[dayIdx];
    if (!dd?.date) {
        alert(`Seleziona una data per il Giorno ${dayIdx + 1} prima di richiedere il traffico.`);
        return;
    }

    const geometry = getDayGeometry(dayIdx);
    const stats    = getDayStats(dayIdx);
    if (!geometry) return;

    const container = document.getElementById(`seg-traffic-day-${dayIdx}`);
    if (!container) return;
    container.innerHTML = `<div class="seg-loading">&#9203; Stima traffico in corso...</div>`;

    showLoading(true);
    try {
        const res = await fetch("/api/traffic-segment", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                geometry,
                date:         dd.date,
                time:         dd.time || "09:00",
                duration_sec: stats.duration_sec,
                distance_km:  stats.distance_km,
                profile:      state.mode,
                interval_km:  state.sampleInterval,
            }),
        });
        const data = await res.json();

        if (data.error) {
            container.innerHTML = `<div class="seg-error">&#9888; ${escHtml(data.error)}</div>`;
            return;
        }

        const key     = `day-${dayIdx}`;
        const results = data.points || data;
        const meta    = data.points ? data : null;
        const color   = LEG_COLORS[dayIdx % LEG_COLORS.length];
        renderDayTraffic(dayIdx, results, dd.time || "09:00", dd.date, color, meta);
        renderTrafficMarkersOnMap(key, results);
        setMapView("traffic");
        showMapToggle();
        state.dayDates[dayIdx].trafficFetched = true;
    } catch (err) {
        if (container) container.innerHTML = `<div class="seg-error">&#9888; Errore di connessione</div>`;
        console.error(err);
    } finally { showLoading(false); }
}

function renderDayTraffic(dayIdx, results, departureTime, dateStr, color, meta) {
    const container = document.getElementById(`seg-traffic-day-${dayIdx}`);
    if (!container) return;

    const src       = meta?.source || results[0]?.source || "heuristic";
    const isTomTom  = src === "tomtom_historical";
    const sourceBadge = isTomTom
        ? `<span class="traffic-source-badge tomtom">&#128225; TomTom storico</span>`
        : `<span class="traffic-source-badge heuristic">&#128202; Stima statistica</span>`;
    const delayNote = (isTomTom && meta?.leg_delay_min > 0)
        ? `&nbsp;&mdash; ritardo atteso <strong>+${meta.leg_delay_min} min</strong>` : "";

    container.innerHTML = `
      <div class="seg-weather-header" style="border-left-color:${color}">
        &#128678; ${fmtDate(dateStr)} ore ${departureTime} &mdash;
        ${results.length} punti ogni ~${state.sampleInterval} km${delayNote} ${sourceBadge}
      </div>
      <div class="seg-weather-row" id="seg-traffic-chips-day-${dayIdx}"></div>
    `;

    const row = container.querySelector(`#seg-traffic-chips-day-${dayIdx}`);
    results.forEach((pt) => {
        const chip = document.createElement("div");
        chip.className = "seg-traffic-chip";
        chip.style.borderTopColor = pt.traffic_color;
        chip.innerHTML = `
          <div class="chip-dist">${pt.dist_km}&nbsp;km</div>
          <div class="chip-time">&#128336;${pt.estimated_time}</div>
          <div class="chip-traffic-icon">${pt.traffic_icon}</div>
          <div class="chip-traffic-label">${escHtml(pt.traffic_label)}</div>
          ${pt.delay_percent > 0 ? `<div class="chip-delay">+${pt.delay_percent}%</div>` : `<div class="chip-delay">&#10003;</div>`}
        `;
        const tt = [`${pt.weekday_name} ${pt.estimated_time} — km ${pt.dist_km}`, `Traffico: ${pt.traffic_label}`];
        if (pt.source === "tomtom") tt.push(`Velocità: ${pt.current_speed} km/h (libera: ${pt.free_flow_speed} km/h)`);
        if (pt.delay_percent > 0) tt.push(`Ritardo: +${pt.delay_percent}%`);
        chip.title = tt.join("\n");
        row.appendChild(chip);
    });
}

// ===== ICONE MAPPA =====
function makeWeatherIcon(pt) {
    return L.divIcon({
        html: `<div style="background:${tempColor(pt.temperature)};border:2.5px solid white;
            border-radius:50%;width:28px;height:28px;display:flex;align-items:center;
            justify-content:center;font-size:15px;box-shadow:0 2px 6px rgba(0,0,0,.38);
            cursor:pointer;line-height:1;">${pt.weather_icon}</div>`,
        className: "", iconSize: [28, 28], iconAnchor: [14, 14], popupAnchor: [0, -16],
    });
}

function renderWeatherMarkersOnMap(key, results) {
    if (state.weatherGroups[key]) state.weatherGroups[key].clearLayers();
    else state.weatherGroups[key] = L.layerGroup();

    const group = state.weatherGroups[key];
    results.filter((r) => !r.error).forEach((pt) => {
        const marker = L.marker([pt.lat, pt.lon], { icon: makeWeatherIcon(pt) });
        marker.bindPopup(`
          <div style="min-width:160px;font-size:13px">
            <div style="font-size:11px;color:#888;margin-bottom:4px">&#8987; ${pt.estimated_time} &mdash; km ${pt.dist_km}</div>
            <div style="font-weight:700;font-size:16px">${pt.weather_icon} ${pt.temperature}°C</div>
            <div style="color:#555;margin-bottom:5px">${escHtml(pt.weather_description)}</div>
            <div>Percepita: ${pt.apparent_temperature}°C</div>
            <div>&#128167; Pioggia: ${pt.precipitation_probability}%</div>
            <div>&#128168; Vento: ${pt.windspeed} km/h ${compassDir(pt.winddirection)}</div>
            <div>&#9729; Nuvole: ${pt.cloudcover}%</div>
          </div>`);
        group.addLayer(marker);
    });
    if (state.mapView === "weather") group.addTo(state.map);
}

function makeTrafficIcon(pt) {
    return L.divIcon({
        html: `<div style="background:${pt.traffic_color};border:2.5px solid white;border-radius:5px;
            width:28px;height:28px;display:flex;align-items:center;justify-content:center;
            font-size:14px;box-shadow:0 2px 6px rgba(0,0,0,.38);cursor:pointer;line-height:1;">
            ${pt.traffic_icon}</div>`,
        className: "", iconSize: [28, 28], iconAnchor: [14, 14], popupAnchor: [0, -16],
    });
}

function renderTrafficMarkersOnMap(key, results) {
    if (state.trafficGroups[key]) state.trafficGroups[key].clearLayers();
    else state.trafficGroups[key] = L.layerGroup();

    const group = state.trafficGroups[key];
    results.forEach((pt) => {
        const marker = L.marker([pt.lat, pt.lon], { icon: makeTrafficIcon(pt) });
        const speedInfo = pt.source === "tomtom"
            ? `<div style="color:#555;margin-top:3px;font-size:11px">&#128225; ${pt.current_speed} km/h su ${pt.free_flow_speed} km/h</div>` : "";
        marker.bindPopup(`
          <div style="min-width:155px;font-size:13px">
            <div style="font-size:11px;color:#888;margin-bottom:4px">&#8987; ${pt.weekday_name} ${pt.estimated_time} &mdash; km ${pt.dist_km}</div>
            <div style="font-weight:700;font-size:15px">${pt.traffic_icon} ${escHtml(pt.traffic_label)}</div>
            ${speedInfo}
            ${pt.delay_percent > 0 ? `<div style="color:#e67e22;margin-top:4px">&#9888; Ritardo +${pt.delay_percent}%</div>` : ""}
          </div>`);
        group.addLayer(marker);
    });
    if (state.mapView === "traffic") group.addTo(state.map);
}

function clearAllWeatherMarkers() {
    Object.values(state.weatherGroups).forEach((g) => g?.remove());
    state.weatherGroups = {};
}

function clearAllTrafficMarkers() {
    Object.values(state.trafficGroups).forEach((g) => g?.remove());
    state.trafficGroups = {};
}

// ===== TOGGLE LAYER MAPPA =====
function setMapView(view) {
    state.mapView = view;
    Object.values(state.weatherGroups).forEach((g) => { if (!g) return; view === "weather" ? g.addTo(state.map) : g.remove(); });
    Object.values(state.trafficGroups).forEach((g) => { if (!g) return; view === "traffic" ? g.addTo(state.map) : g.remove(); });
    document.getElementById("btn-view-weather")?.classList.toggle("active", view === "weather");
    document.getElementById("btn-view-traffic")?.classList.toggle("active", view === "traffic");
}

function showMapToggle() {
    document.getElementById("map-layer-toggle")?.classList.remove("hidden");
}

// ===== REVERSE GEOCODE =====
async function reverseGeocode(lat, lon) {
    try {
        const res = await fetch("/api/reverse-geocode", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ lat, lon }),
        });
        const data = await res.json();
        if (data.display_name) return data.display_name.split(",").slice(0, 2).join(", ").trim();
    } catch (e) { console.warn("Reverse geocode failed:", e); }
    return `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
}

// ===== CLEAR =====
function clearLegs() {
    state.legLayers.forEach((l) => l.remove());
    state.legLayers = [];
    clearAllWeatherMarkers();
    clearAllTrafficMarkers();
    state.mapView  = "none";
    state.legs     = [];
    state.dayDates = {};
    document.getElementById("legs-panel")?.remove();
    document.getElementById("map-layer-toggle")?.classList.add("hidden");
}

function clearAll() {
    if (!confirm("Vuoi davvero azzerare tutto il percorso?")) return;
    clearTimeout(state.autoRecalcTimer);
    Object.keys(state.markers).forEach((k) => removeMarker(Number(k)));
    clearLegs();
    state.waypoints = [];
    wpCounter = 0;
    addWaypoint();
    addWaypoint();
}

// ===== UTILS =====
function showLoading(on) { document.getElementById("loading").classList.toggle("hidden", !on); }
function todayStr()  { return new Date().toISOString().slice(0, 10); }
function maxDateStr(){ const d = new Date(); d.setDate(d.getDate() + 16); return d.toISOString().slice(0, 10); }
function fmtDate(s)  { if (!s) return ""; const [y, m, d] = s.split("-"); return `${d}/${m}/${y}`; }
function compassDir(deg) {
    const dirs = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"];
    return dirs[Math.round((deg || 0) / 45) % 8];
}
function tempColor(temp) {
    if (temp < 0)  return "#74b9ff";
    if (temp < 10) return "#55efc4";
    if (temp < 20) return "#fdcb6e";
    if (temp < 30) return "#e17055";
    return "#d63031";
}
function curveDots(stars) { const s = stars || 1; return "●".repeat(s) + "○".repeat(5 - s); }
function curveColor(stars) {
    return ["#95a5a6", "#3498db", "#f39c12", "#e67e22", "#e74c3c"][(stars || 1) - 1];
}

// ===== EXPORT TO GOOGLE MAPS =====
function exportToGoogleMaps() {
    const valid = state.waypoints.filter((w) => w.lat && w.lon);
    if (valid.length < 2) { alert("Nessun percorso con coordinate disponibile da esportare."); return; }

    const origin      = `${valid[0].lat},${valid[0].lon}`;
    const destination = `${valid[valid.length - 1].lat},${valid[valid.length - 1].lon}`;
    const mid         = valid.slice(1, -1).map((w) => `${w.lat},${w.lon}`).join("|");
    const modeMap     = { driving: "driving", walking: "walking", cycling: "bicycling", motorcycle: "driving" };

    let url = `https://www.google.com/maps/dir/?api=1&origin=${origin}&destination=${destination}&travelmode=${modeMap[state.mode] || "driving"}`;
    if (mid) url += `&waypoints=${encodeURIComponent(mid)}`;
    window.open(url, "_blank");
}

// ===== IMPORT GOOGLE MAPS =====
function toggleImportSection() {
    const form = document.getElementById("import-gmaps-form");
    const btn  = document.getElementById("import-gmaps-toggle");
    const open = form.classList.toggle("hidden") === false;
    btn.classList.toggle("open", open);
    if (open) document.getElementById("gmaps-url-input").focus();
}

function showImportChoiceModal() {
    return new Promise((resolve) => {
        const overlay = document.createElement("div");
        overlay.className = "import-choice-overlay";
        overlay.innerHTML = `
            <div class="import-choice-box">
                <p>Esiste già un percorso.<br>Cosa vuoi fare con il nuovo link?</p>
                <div class="import-choice-btns">
                    <button class="import-choice-btn primary" id="btn-new-day-import">&#128197; Aggiungi come nuovo giorno</button>
                    <button class="import-choice-btn danger"  id="btn-overwrite-import">&#9998; Sovrascrivi percorso esistente</button>
                    <button class="import-choice-btn cancel"  id="btn-cancel-import">Annulla</button>
                </div>
            </div>`;
        document.body.appendChild(overlay);
        overlay.querySelector("#btn-new-day-import").onclick  = () => { overlay.remove(); resolve("new-day");   };
        overlay.querySelector("#btn-overwrite-import").onclick = () => { overlay.remove(); resolve("overwrite"); };
        overlay.querySelector("#btn-cancel-import").onclick   = () => { overlay.remove(); resolve(null);        };
    });
}

async function importGmapsUrl() {
    const input = document.getElementById("gmaps-url-input");
    const url   = input.value.trim();
    if (!url) { input.focus(); return; }

    const btn = document.getElementById("import-gmaps-btn");
    btn.disabled    = true;
    btn.textContent = "Caricamento…";
    showLoading(true);

    try {
        const res  = await fetch("/api/import-gmaps", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url }),
        });
        const data = await res.json();

        if (data.error) { alert("Errore: " + data.error); return; }
        if (!Array.isArray(data) || data.length < 2) {
            alert("Servono almeno 2 tappe. Condividi un percorso con indicazioni stradali da Google Maps.");
            return;
        }

        const hasExisting = state.waypoints.some((w) => w.lat && w.lon);
        let importMode = "overwrite";
        if (hasExisting) {
            showLoading(false);
            importMode = await showImportChoiceModal();
            showLoading(true);
            if (!importMode) return;
        }

        clearTimeout(state.autoRecalcTimer);
        clearLegs();

        if (importMode === "overwrite") {
            Object.keys(state.markers).forEach((k) => removeMarker(Number(k)));
            state.waypoints = [];
            wpCounter = 0;
            data.forEach((wp) => addWaypoint(wp.name || "", wp.lat, wp.lon));
        } else {
            data.forEach((wp, i) => addWaypoint(wp.name || "", wp.lat, wp.lon, i === 0));
        }

        renderWaypoints();

        const allLL = state.waypoints.filter((w) => w.lat && w.lon).map((w) => [w.lat, w.lon]);
        if (allLL.length) state.map.fitBounds(L.latLngBounds(allLL), { padding: [40, 40] });

        document.getElementById("import-gmaps-form").classList.add("hidden");
        document.getElementById("import-gmaps-toggle").classList.remove("open");
        input.value = "";

        const failed = data.filter((w) => w.error);
        if (failed.length) {
            alert(`Attenzione: ${failed.length} tappa/e non trovata/e (${failed.map((f) => f.name).join(", ")}). Posizionala manualmente.`);
        }
    } catch (err) {
        alert("Errore di connessione.");
        console.error(err);
    } finally {
        btn.disabled    = false;
        btn.textContent = "Importa";
        showLoading(false);
    }
}

// ===== MOBILE VIEW TOGGLE =====
function toggleMobileView() {
    const isMapView = document.body.classList.toggle("mobile-map-view");
    const btn = document.getElementById("mobile-map-toggle");
    if (btn) btn.innerHTML = isMapView ? "&#9776;&nbsp;Pannello" : "&#128506;&nbsp;Mappa";
    if (isMapView && state.map) setTimeout(() => state.map.invalidateSize(), 50);
}

function escHtml(str) {
    return String(str || "")
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
