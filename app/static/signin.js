document.addEventListener("DOMContentLoaded", () => {
  const t = window.UI_TEXT;
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
  if (new URLSearchParams(location.search).has("error")) {
    const error = document.getElementById("signin-error");
    error.textContent = t.incorrectPasscode;
    error.hidden = false;
  }
});
