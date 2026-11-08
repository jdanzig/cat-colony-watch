(() => {
  "use strict";
  const C = window.CCW;
  const { T, I18N, app, state, api, refresh, escapeHTML, fill, viewHeader, actorId, showToast, registerTab } = C;
  state.reportKind = "fed";
  state.location = null;

  function reportHelp() {
    return state.reportKind === "fed" ? T.fedHelp : state.reportKind === "sighting" ? T.sightingHelp : T.urgentHelp;
  }

  function renderReport() {
    const colonyOptions = state.data.colonies.map((colony) => `<option value="${escapeHTML(colony.id)}">${escapeHTML(colony.name)}</option>`).join("");
    const photoFields = `
      <div class="report-photo-fields" id="report-photo-fields"${state.reportKind === "fed" ? " hidden" : ""}>
      <label class="field"><span>${T.photoLabel}</span><span class="photo-input"><input id="report-photo" type="file" accept="image/*" capture="environment" required><span aria-hidden="true">⌁</span><b>${T.takePhoto}</b></span><img id="photo-preview" class="photo-preview" hidden alt="${escapeHTML(T.photoAlt)}"></label>
      <label class="field"><span>${T.noteLabel}</span><textarea id="report-note" placeholder="${escapeHTML(state.reportKind === "urgent" ? T.urgentNotePlaceholder : T.notePlaceholder)}"></textarea></label>
      <div class="field"><span>${T.locationLabel}</span><div class="location-row"><button type="button" class="ghost-button" id="add-location">${T.addLocation}</button><span class="location-status" id="location-status"></span></div></div>
      </div>`;
    app.innerHTML = `<section class="view">${viewHeader(T.reportEyebrow, T.reportTitle, T.reportSubtitle)}
      <div class="report-kinds"><button type="button" class="report-kind ${state.reportKind === "fed" ? "active" : ""}" data-report-kind="fed" aria-pressed="${state.reportKind === "fed"}"><span aria-hidden="true">●</span><b>${T.fed}</b></button><button type="button" class="report-kind ${state.reportKind === "sighting" ? "active" : ""}" data-report-kind="sighting" aria-pressed="${state.reportKind === "sighting"}"><span aria-hidden="true">◉</span><b>${T.sighting}</b></button><button type="button" class="report-kind ${state.reportKind === "urgent" ? "active" : ""}" data-report-kind="urgent" aria-pressed="${state.reportKind === "urgent"}"><span aria-hidden="true">!</span><b>${T.reportUrgent}</b></button></div>
      <p class="report-help">${reportHelp()}</p><form id="report-form" class="report-form"><label class="field"><span>${T.chooseColony}</span><select id="report-colony" required><option value="">${T.chooseColonyPlaceholder}</option>${colonyOptions}</select></label>${photoFields}<button class="primary-button" id="send-report">${T.sendReport}</button></form><div id="report-result"></div></section>`;
    document.getElementById("report-photo").required = state.reportKind !== "fed";
  }

  function selectReportKind(nextKind) {
    if (!["fed", "sighting", "urgent"].includes(nextKind) || nextKind === state.reportKind) return;
    state.reportKind = nextKind;
    app.querySelectorAll("[data-report-kind]").forEach((button) => {
      const active = button.dataset.reportKind === nextKind;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    document.querySelector(".report-help").textContent = reportHelp();
    const photoFields = document.getElementById("report-photo-fields");
    const photo = document.getElementById("report-photo");
    const note = document.getElementById("report-note");
    photoFields.hidden = nextKind === "fed";
    photo.required = nextKind !== "fed";
    note.placeholder = nextKind === "urgent" ? T.urgentNotePlaceholder : T.notePlaceholder;
    document.getElementById("report-result").replaceChildren();
  }

  function locate() {
    const status = document.getElementById("location-status");
    if (!navigator.geolocation) { status.textContent = T.locationUnavailable; return; }
    navigator.geolocation.getCurrentPosition((position) => {
      state.location = { lat: position.coords.latitude, lng: position.coords.longitude };
      status.textContent = T.locationReady;
    }, () => { status.textContent = T.locationUnavailable; }, { enableHighAccuracy: true, timeout: 10000 });
  }

  function imageDataURL(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = reject;
      reader.onload = () => resolve(reader.result);
      reader.readAsDataURL(file);
    });
  }

  async function submitReport(form) {
    const colonyId = document.getElementById("report-colony").value;
    if (!colonyId) return showToast(T.chooseColonyError);
    const button = document.getElementById("send-report");
    button.disabled = true;
    button.textContent = T.sending;
    try {
      let result;
      if (state.reportKind === "fed") {
        result = await api("/api/reports/fed", { method: "POST", body: JSON.stringify({ colony_id: colonyId, volunteer_id: actorId() }) });
        const colony = state.data.colonies.find((item) => item.id === colonyId);
        result.summary = fill(T.fedRecorded, { colony: colony.name });
      } else {
        const file = document.getElementById("report-photo").files[0];
        if (!file) throw new Error(T.choosePhotoError);
        result = await api("/api/reports/photo", { method: "POST", body: JSON.stringify({
          kind: state.reportKind,
          colony_id: colonyId,
          volunteer_id: actorId(),
          note: document.getElementById("report-note").value,
          lat: state.location?.lat || null,
          lng: state.location?.lng || null,
          photo_data_url: await imageDataURL(file),
        }) });
        if (I18N.locale !== "en") {
          const colony = state.data.colonies.find((item) => item.id === colonyId);
          result.summary = `${fill(T.photoReportRecorded, { colony: colony.name })} ${result.needs_review ? T.photoReportNeedsReview : T.photoReportNoReview}`;
        }
      }
      document.getElementById("report-result").innerHTML = `<section class="report-result"><h2>${T.reportRecorded}</h2><p>${escapeHTML(result.summary)}</p></section>`;
      form.reset();
      state.location = null;
      document.getElementById("location-status").textContent = "";
      document.getElementById("photo-preview").hidden = true;
      await refresh();
    } catch (error) {
      showToast(error.message || T.reportError);
    } finally {
      button.disabled = false;
      button.textContent = T.sendReport;
    }
  }

  app.addEventListener("click", (event) => {
    const kind = event.target.closest("[data-report-kind]");
    if (kind) {
      selectReportKind(kind.dataset.reportKind);
      return;
    }
    if (event.target.closest("#add-location")) locate();
  });
  app.addEventListener("change", (event) => {
    if (event.target.id !== "report-photo") return;
    const preview = document.getElementById("photo-preview");
    const file = event.target.files[0];
    if (!file) { preview.hidden = true; return; }
    preview.src = URL.createObjectURL(file);
    preview.hidden = false;
  });
  app.addEventListener("submit", (event) => {
    if (event.target.id !== "report-form") return;
    event.preventDefault();
    submitReport(event.target);
  });
  registerTab("report", renderReport);
})();
