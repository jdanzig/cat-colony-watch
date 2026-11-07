(() => {
  "use strict";
  const C = window.CCW;
  const { T, app, dialogContent, state, eventLabels, api, escapeHTML, fill, photoURL, timeAgo, viewHeader, chipsForCat, openDialog, registerTab } = C;

  function renderColonies() {
    const rows = state.data.colonies.map((colony) => `
      <button type="button" class="colony-row" data-colony="${escapeHTML(colony.id)}">
        <span><h2>${escapeHTML(colony.name)}</h2><p>${colony.last_fed_at ? fill(T.lastFedBy, { name: escapeHTML(colony.last_fed_by), time: timeAgo(colony.last_fed_at) }) : T.neverFed}</p></span>
        <span class="row-count">${colony.cats}<small>${T.cats}</small></span>
      </button>`).join("");
    app.innerHTML = `<section class="view">${viewHeader(T.coloniesEyebrow, T.coloniesTitle, T.coloniesSubtitle)}
      <section class="map-card"><div id="colony-map" aria-label="${escapeHTML(T.mapLabel)}"></div><div class="map-legend"><span class="legend-urgent">${T.mapUrgent}</span><span class="legend-high">${T.mapHigh}</span><span>${T.mapOkay}</span></div></section>
      <section class="colony-list" aria-label="${escapeHTML(T.colonyList)}">${rows}</section></section>`;
    window.requestAnimationFrame(initMap);
  }

  function initMap() {
    if (!window.L || !document.getElementById("colony-map")) return;
    if (state.map) state.map.remove();
    state.map = L.map("colony-map", { scrollWheelZoom: false }).setView([25.782, -80.22], 11);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "&copy; OpenStreetMap" }).addTo(state.map);
    state.data.colonies.forEach((colony) => {
      const severity = colony.alert_severity || "okay";
      const icon = L.divIcon({ className: "", html: `<div class="colony-pin ${severity}"></div>`, iconSize: [24, 24], iconAnchor: [12, 22] });
      L.marker([colony.lat, colony.lng], { icon }).addTo(state.map)
        .bindTooltip(`${escapeHTML(colony.name)} · ${colony.cats} ${T.cats}`)
        .on("click", () => showColony(colony.id));
    });
    window.setTimeout(() => state.map?.invalidateSize(), 380);
  }

  function catCard(cat) {
    const sightings = cat.unconfirmed_sightings
      ? `<span class="chip blue">${fill(cat.unconfirmed_sightings === 1 ? T.unconfirmedSightings : T.unconfirmedSightingsPlural, { count: cat.unconfirmed_sightings })}</span>` : "";
    return `<button type="button" class="cat-card" data-cat="${cat.id}">
      ${cat.photo_id ? `<img src="${photoURL(cat.photo_id)}" alt="${escapeHTML(T.photoAlt)}">` : `<span class="cat-placeholder" aria-hidden="true">◉</span>`}
      <span class="cat-card-copy"><h3>${escapeHTML(cat.reported_name || cat.display_name)}</h3><span class="chips">${chipsForCat(cat)}${sightings}</span></span>
    </button>`;
  }

  async function showColony(id) {
    try {
      const colony = await api(`/api/colonies/${encodeURIComponent(id)}`);
      const feedings = colony.feeding_log.map((item) => `<div class="log-row"><strong>${escapeHTML(item.volunteer)}</strong><small>${timeAgo(item.at)}</small></div>`).join("");
      const feeders = colony.feeders.map((item) => `<div class="feeder-row"><span><strong>${escapeHTML(item.name)}</strong><br><small>${escapeHTML(item.role)}</small></span><a href="tel:${escapeHTML(item.phone)}">${escapeHTML(item.phone)}</a></div>`).join("");
      dialogContent.innerHTML = `<header class="detail-head"><p class="eyebrow">${T.coloniesTitle}</p><h1>${escapeHTML(colony.name)}</h1><p>${escapeHTML(colony.notes)}</p></header>
        <div class="metric-grid"><div class="metric"><strong>${colony.cats}</strong><span>${T.cats}</span></div><div class="metric"><strong>${colony.fixed}</strong><span>${T.fixed}</span></div><div class="metric"><strong>${colony.needs_tnr}</strong><span>${T.waitingTnr}</span></div><div class="metric"><strong>${colony.needs_vet}</strong><span>${T.needsVet}</span></div></div>
        <div class="last-fed-banner">${colony.last_fed_at ? fill(T.lastFedBy, { name: escapeHTML(colony.last_fed_by), time: timeAgo(colony.last_fed_at) }) : T.neverFed}</div>
        <section class="detail-section"><h2>${T.colonyCats}</h2>${colony.cats_list.length ? `<div class="cat-grid">${colony.cats_list.map(catCard).join("")}</div>` : `<p>${T.noCats}</p>`}</section>
        <section class="detail-section"><h2>${T.feedingLog}</h2><div class="log-list">${feedings || `<p>${T.noFeedings}</p>`}</div></section>
        <section class="detail-section"><h2>${T.regularFeeders}</h2><div class="feeder-list">${feeders}</div></section>`;
      openDialog();
    } catch (error) { C.showToast(error.message || T.loadError); }
  }

  async function showCat(id) {
    try {
      const cat = await api(`/api/cats/${id}`);
      const photos = cat.photos.map((item) => `<div class="photo-tile"><img src="${photoURL(item.id)}" alt="${escapeHTML(T.photoAlt)}">${item.confirmed ? "" : `<span>${T.unconfirmed}</span>`}</div>`).join("");
      const history = cat.history.map((item) => `<div class="history-row"><strong>${escapeHTML(eventLabels[item.kind] || item.kind)}</strong><span>${escapeHTML(item.detail)}</span><small>${escapeHTML(item.volunteer)} · ${timeAgo(item.at)}</small></div>`).join("");
      dialogContent.innerHTML = `<header class="detail-head"><p class="eyebrow">${T.catProfile}</p><h1>${escapeHTML(cat.reported_name || cat.display_name)}</h1><p>${escapeHTML(cat.colony)}</p></header>
        ${cat.photos[0] ? `<div class="profile-hero"><img src="${photoURL(cat.photos[0].id)}" alt="${escapeHTML(T.photoAlt)}"></div>` : ""}
        <div class="chips">${chipsForCat(cat)}</div>
        <section class="detail-section"><div class="log-list"><div class="log-row"><strong>${T.firstSeen}</strong><small>${timeAgo(cat.first_seen)}</small></div><div class="log-row"><strong>${T.lastSeen}</strong><small>${timeAgo(cat.last_seen)}</small></div></div></section>
        <section class="detail-section"><h2>${T.photos}</h2><div class="photo-grid">${photos}</div></section>
        <section class="detail-section"><h2>${T.history}</h2><div class="history-list">${history || `<p>${T.noHistory}</p>`}</div></section>`;
      openDialog();
    } catch (error) { C.showToast(error.message || T.loadError); }
  }

  app.addEventListener("click", (event) => {
    const colony = event.target.closest("[data-colony]");
    if (colony) showColony(colony.dataset.colony);
  });
  dialogContent.addEventListener("click", (event) => {
    const cat = event.target.closest("[data-cat]");
    if (cat) showCat(cat.dataset.cat);
  });
  registerTab("colonies", renderColonies);
})();
