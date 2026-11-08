(() => {
  "use strict";
  const T = window.UI_TEXT;
  const I18N = window.UI_I18N;
  const counts = JSON.parse(document.getElementById("sponsor-data").textContent);
  const container = document.getElementById("sponsor-metrics");
  const localeSelect = document.getElementById("locale-select");

  function localize() {
    const metrics = [
      ["colonies", T.sponsorColonies],
      ["cats", T.sponsorCats],
      ["fixed", T.sponsorFixed],
      ["needs_tnr", T.sponsorWaitingTnr],
      ["needs_vet", T.sponsorNeedsVet],
      ["open_needs", T.sponsorOpenNeeds],
      ["urgent_needs", T.sponsorUrgentNeeds],
    ];
    document.title = T.sponsorPageTitle;
    document.getElementById("sponsor-kicker").textContent = T.sponsorKicker;
    document.getElementById("sponsor-title").textContent = T.sponsorTitle;
    document.getElementById("sponsor-subtitle").textContent = T.sponsorSubtitle;
    document.getElementById("sponsor-privacy").textContent = T.sponsorPrivacy;
    container.setAttribute("aria-label", T.sponsorMetricsLabel);
    container.replaceChildren();
    for (const [key, label] of metrics) {
      const card = document.createElement("article");
      card.className = `sponsor-metric sponsor-metric-${key.replaceAll("_", "-")}`;
      const value = document.createElement("strong");
      const numberLocale = I18N.locale === "es" ? "es-US" : I18N.locale === "ht" ? "ht-HT" : "en-US";
      value.textContent = new Intl.NumberFormat(numberLocale).format(Number(counts[key] || 0));
      const caption = document.createElement("span");
      caption.textContent = label;
      card.append(value, caption);
      container.append(card);
    }
    I18N.localizeControl(localeSelect);
  }

  I18N.bindControl(localeSelect);
  window.addEventListener("ccw:localechange", localize);
  localize();
})();
