(() => {
  "use strict";
  const T = window.UI_TEXT;
  const counts = JSON.parse(document.getElementById("sponsor-data").textContent);
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

  const container = document.getElementById("sponsor-metrics");
  container.setAttribute("aria-label", T.sponsorMetricsLabel);
  for (const [key, label] of metrics) {
    const card = document.createElement("article");
    card.className = `sponsor-metric sponsor-metric-${key.replaceAll("_", "-")}`;
    const value = document.createElement("strong");
    value.textContent = new Intl.NumberFormat().format(Number(counts[key] || 0));
    const caption = document.createElement("span");
    caption.textContent = label;
    card.append(value, caption);
    container.append(card);
  }
})();
