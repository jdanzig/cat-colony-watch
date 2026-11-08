document.addEventListener("DOMContentLoaded", () => {
  const t = window.UI_TEXT;
  const i18n = window.UI_I18N;
  const localeSelect = document.getElementById("locale-select");

  function localize() {
    document.title = t.pageTitle;
    const values = {
      "signin-kicker": t.signInKicker,
      "signin-title": t.signInTitle,
      "signin-body": t.signInBody,
      "passcode-label": t.passcode,
      "signin-button": t.signIn,
      "privacy-note": t.privacyNote,
    };
    Object.entries(values).forEach(([id, value]) => { document.getElementById(id).textContent = value; });
    if (new URLSearchParams(location.search).has("error") || document.body.dataset.rateLimited) {
      const error = document.getElementById("signin-error");
      error.textContent = document.body.dataset.rateLimited ? t.tooManyAttempts : t.incorrectPasscode;
      error.hidden = false;
    }
    i18n.localizeControl(localeSelect);
  }

  i18n.bindControl(localeSelect);
  window.addEventListener("ccw:localechange", localize);
  localize();
});
