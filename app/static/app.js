(() => {
  "use strict";

  const T = window.UI_TEXT;
  const app = document.getElementById("app");
  const nav = document.getElementById("bottom-nav");
  const dialog = document.getElementById("detail-dialog");
  const dialogContent = document.getElementById("dialog-content");
  const actorSelect = document.getElementById("actor-select");
  const renderers = {};
  const state = { tab: location.hash.slice(1) || "today", data: null, map: null };

  const escapeHTML = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
  const fill = (template, values = {}) => Object.entries(values).reduce(
    (text, [key, value]) => text.replaceAll(`{${key}}`, value), template,
  );
  const photoURL = (id) => id ? `/api/photos/${id}` : "";
  const actorId = () => actorSelect.value;
  const actor = () => state.data.volunteers.find((item) => item.id === actorId());
  const eventLabels = {
    fed: T.eventFed, sighting: T.eventSighting, tnr_done: T.eventTnrDone,
    health: T.eventHealth, kittens: T.eventKittens, need: T.eventNeed, status: T.eventStatus,
  };

  function timeAgo(value) {
    if (!value) return T.neverFed;
    const date = new Date(value);
    const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
    if (seconds < 60) return T.justNow;
    const minutes = Math.round(seconds / 60);
    if (minutes === 1) return T.minuteAgo;
    if (minutes < 60) return fill(T.minutesAgo, { count: minutes });
    const hours = Math.round(minutes / 60);
    if (hours === 1) return T.hourAgo;
    if (hours < 36) return fill(T.hoursAgo, { count: hours });
    const days = Math.round(hours / 24);
    if (days === 1) return T.dayAgo;
    if (days < 14) return fill(T.daysAgo, { count: days });
    return fill(T.onDate, { date: date.toLocaleDateString(undefined, { month: "short", day: "numeric" }) });
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    if (response.status === 401) {
      location.href = "/signin";
      throw new Error(T.actionError);
    }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || T.actionError);
    return payload;
  }

  async function refresh() {
    state.data = await api("/api/bootstrap");
    hydrateActor();
    updateCounts();
  }

  function hydrateActor() {
    const saved = localStorage.getItem("ccw-volunteer");
    const fallback = state.data.volunteers.find((item) => item.role === "admin") || state.data.volunteers[0];
    actorSelect.innerHTML = state.data.volunteers.map((volunteer) =>
      `<option value="${escapeHTML(volunteer.id)}">${escapeHTML(volunteer.name)}</option>`
    ).join("");
    actorSelect.value = state.data.volunteers.some((item) => item.id === saved) ? saved : fallback.id;
  }

  function updateCounts() {
    [["alert-count", state.data.alerts.length], ["confirm-count", state.data.suggestions.length]].forEach(([id, count]) => {
      const node = document.getElementById(id);
      node.textContent = count > 99 ? "99+" : String(count);
      node.classList.toggle("visible", count > 0);
    });
  }

  function viewHeader(eyebrow, title, subtitle) {
    return `<header class="view-header"><p class="eyebrow">${eyebrow}</p><h1>${title}</h1><p>${subtitle}</p></header>`;
  }

  function emptyState(icon, title, body) {
    return `<section class="empty-state"><div class="empty-icon" aria-hidden="true">${icon}</div><h2>${title}</h2><p>${body}</p></section>`;
  }

  function chipsForCat(cat) {
    const chips = [`<span class="chip green">${T[cat.status] || escapeHTML(cat.status)}</span>`];
    chips.push(`<span class="chip ${cat.tnr_status === "needs_tnr" ? "orange" : "blue"}">${cat.tnr_status === "fixed" ? T.fixedChip : cat.tnr_status === "needs_tnr" ? T.needsTnrChip : T.unknownTnrChip}</span>`);
    chips.push(`<span class="chip ${cat.health === "needs_vet" ? "orange" : "green"}">${cat.health === "needs_vet" ? T.vetChip : T.healthyChip}</span>`);
    if (cat.pregnant) chips.push(`<span class="chip orange">${T.pregnantChip}</span>`);
    return chips.join("");
  }

  function openDialog() {
    if (!dialog.open) dialog.showModal();
    dialog.scrollTop = 0;
  }

  let toastTimer;
  function showToast(message) {
    const toast = document.getElementById("toast");
    toast.textContent = message;
    toast.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("visible"), 2800);
  }

  function registerTab(name, renderer) {
    renderers[name] = renderer;
    const button = nav.querySelector(`[data-tab="${name}"]`);
    if (button) button.disabled = false;
  }

  function render() {
    if (!state.data) return;
    if (!renderers[state.tab]) state.tab = "today";
    nav.querySelectorAll("button[data-tab]").forEach((button) => {
      button.classList.toggle("active", button.dataset.tab === state.tab);
      button.disabled = !renderers[button.dataset.tab];
    });
    renderers[state.tab]();
    app.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function renderToday() {
    const cards = state.data.alerts.map((alert) => `
      <article class="alert-card ${escapeHTML(alert.severity)}">
        ${alert.photo_id ? `<img class="alert-photo" src="${photoURL(alert.photo_id)}" alt="${escapeHTML(T.photoAlt)}">` : `<div class="alert-photo placeholder" aria-hidden="true">✦</div>`}
        <div class="alert-body"><div class="alert-meta"><span class="severity ${escapeHTML(alert.severity)}">${T[alert.severity] || alert.severity}</span><span>${escapeHTML(alert.colony)}</span></div>
          <h2>${escapeHTML(alert.text)}</h2><button type="button" class="small-button" data-alert-done="${alert.id}">${T.done}</button></div>
      </article>`).join("");
    app.innerHTML = `<section class="view">${viewHeader(T.todayEyebrow, T.todayTitle, T.todaySubtitle)}${cards ? `<div class="alert-grid">${cards}</div>` : emptyState("✓", T.allClearTitle, T.allClearBody)}</section>`;
  }

  async function resolveAlert(id, button) {
    button.disabled = true;
    try {
      await api(`/api/alerts/${id}/done`, { method: "POST", body: JSON.stringify({ volunteer_id: actorId() }) });
      await refresh();
      renderToday();
      showToast(T.reviewSaved);
    } catch (error) { button.disabled = false; showToast(error.message || T.actionError); }
  }

  function localizeShell() {
    document.title = T.pageTitle;
    document.getElementById("brand-name").textContent = T.appName;
    document.getElementById("brand-tagline").textContent = T.appTagline;
    document.querySelector(".brand").setAttribute("aria-label", T.appName);
    document.getElementById("actor-label").textContent = T.actingAs;
    document.getElementById("loading-copy").textContent = T.loading;
    nav.setAttribute("aria-label", T.appName);
    [T.tabToday, T.tabColonies, T.tabConfirm, T.tabReport].forEach((label, index) => { nav.querySelectorAll("button b")[index].textContent = label; });
    document.getElementById("dialog-close").setAttribute("aria-label", T.close);
  }

  window.CCW = {
    T, app, nav, dialog, dialogContent, state, eventLabels,
    api, refresh, render, registerTab, showToast, openDialog,
    actorId, escapeHTML, fill, photoURL, timeAgo, viewHeader, emptyState, chipsForCat,
  };
  registerTab("today", renderToday);

  nav.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-tab]");
    if (!button || button.disabled) return;
    state.tab = button.dataset.tab;
    history.replaceState(null, "", `#${state.tab}`);
    render();
  });
  actorSelect.addEventListener("change", () => {
    localStorage.setItem("ccw-volunteer", actorId());
    showToast(fill(T.reportsAs, { name: actor().name }));
  });
  document.getElementById("dialog-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  app.addEventListener("click", (event) => {
    const alert = event.target.closest("[data-alert-done]");
    if (alert) resolveAlert(alert.dataset.alertDone, alert);
  });

  localizeShell();
  refresh().then(render).catch((error) => {
    app.innerHTML = `<section class="view">${emptyState("!", T.loadError, error.message || T.loadError)}<button class="primary-button" onclick="location.reload()">${T.retry}</button></section>`;
  });
})();
