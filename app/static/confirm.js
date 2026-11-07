(() => {
  "use strict";
  const C = window.CCW;
  const { T, app, state, api, refresh, escapeHTML, fill, photoURL, viewHeader, emptyState, actorId, showToast, registerTab } = C;

  function markingText(suggestion) {
    const found = [];
    const visit = (value) => {
      if (Array.isArray(value)) return value.forEach(visit);
      if (!value || typeof value !== "object") return;
      if (Array.isArray(value.matching_specific_markings)) found.push(...value.matching_specific_markings);
      Object.values(value).forEach(visit);
    };
    visit(suggestion.feature_verdicts);
    return found.length ? found.join(" · ") : suggestion.reason;
  }

  function suggestionCard(item) {
    const sameCat = item.kind === "same_cat";
    const duplicate = item.kind === "possible_duplicate";
    const status = item.kind === "status_change";
    const title = sameCat ? T.sameCatQuestion : duplicate ? T.possibleDuplicate : T.statusChange;
    const firstPhoto = sameCat ? item.photo_id : item.target_photo_id;
    const secondPhoto = item.candidate_photo_id;
    const firstLabel = sameCat ? T.newPhoto : duplicate ? T.recordOne : escapeHTML(item.target || item.candidate);
    const secondLabel = sameCat ? escapeHTML(item.candidate) : duplicate ? T.recordTwo : "";
    let actions = "";
    if (sameCat) actions = `<div class="choice-row"><button class="choice-button approve" data-suggestion="${item.id}" data-action="same">${T.same}</button><button class="choice-button" data-suggestion="${item.id}" data-action="different">${T.different}</button><button class="choice-button warn" data-suggestion="${item.id}" data-action="new_cat">${T.newCat}</button></div>`;
    if (duplicate) actions = `<div class="choice-row two"><button class="choice-button approve" data-suggestion="${item.id}" data-action="confirm">${T.mergeRecords}</button><button class="choice-button" data-suggestion="${item.id}" data-action="reject">${T.keepSeparate}</button></div>`;
    if (status) actions = `<div class="choice-row two"><button class="choice-button approve" data-suggestion="${item.id}" data-action="confirm">${fill(T.confirmStatus, { status: T[item.new_status] || escapeHTML(item.new_status) })}</button><button class="choice-button" data-suggestion="${item.id}" data-action="reject">${T.reject}</button></div>`;
    return `<article class="suggestion-card">
      <header class="suggestion-head"><div><p class="eyebrow">${escapeHTML(item.colony || "")}</p><h2>${title}</h2></div>${item.strength ? `<span class="match-strength ${item.strength}">${item.strength === "strong" ? T.strongMatch : T.weakMatch}</span>` : ""}</header>
      ${(firstPhoto || secondPhoto) ? `<div class="compare-photos">${firstPhoto ? `<div class="compare-photo"><img src="${photoURL(firstPhoto)}" alt="${escapeHTML(T.photoAlt)}"><span>${firstLabel}</span></div>` : ""}${secondPhoto ? `<div class="compare-photo"><img src="${photoURL(secondPhoto)}" alt="${escapeHTML(T.photoAlt)}"><span>${secondLabel}</span></div>` : ""}</div>` : ""}
      <div class="suggestion-reason"><h3>${T.decidingMarkings}</h3><p>${escapeHTML(markingText(item))}</p></div>${actions}</article>`;
  }

  function renderConfirm() {
    const suggestions = state.data.suggestions.map(suggestionCard).join("");
    app.innerHTML = `<section class="view">${viewHeader(T.confirmEyebrow, T.confirmTitle, T.confirmSubtitle)}
      ${suggestions ? `<div class="confirm-toolbar"><button class="primary-button" id="confirm-strong">${T.confirmAllStrong}</button></div><div class="suggestion-list">${suggestions}</div>` : emptyState("✓", T.noSuggestionsTitle, T.noSuggestionsBody)}</section>`;
  }

  async function decideSuggestion(id, action, button) {
    button.disabled = true;
    try {
      await api(`/api/suggestions/${id}/decision`, { method: "POST", body: JSON.stringify({ volunteer_id: actorId(), action }) });
      await refresh();
      renderConfirm();
      showToast(T.reviewSaved);
    } catch (error) {
      button.disabled = false;
      showToast(error.message || T.actionError);
    }
  }

  async function confirmAllStrong(button) {
    const strong = state.data.suggestions.filter((item) => item.kind === "same_cat" && item.strength === "strong");
    if (!strong.length) return showToast(T.noStrongMatches);
    button.disabled = true;
    try {
      for (const item of strong) {
        await api(`/api/suggestions/${item.id}/decision`, { method: "POST", body: JSON.stringify({ volunteer_id: actorId(), action: "same" }) });
      }
      await refresh();
      renderConfirm();
      showToast(T.strongMatchesSaved);
    } catch (error) {
      button.disabled = false;
      showToast(error.message || T.actionError);
    }
  }

  app.addEventListener("click", (event) => {
    const decision = event.target.closest("[data-suggestion]");
    if (decision) return decideSuggestion(decision.dataset.suggestion, decision.dataset.action, decision);
    const strong = event.target.closest("#confirm-strong");
    if (strong) confirmAllStrong(strong);
  });
  registerTab("confirm", renderConfirm);
})();
