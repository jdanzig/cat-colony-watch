"use strict";

const assert = require("node:assert/strict");

const stored = new Map();
const listeners = new Map();
global.CustomEvent = class CustomEvent {
  constructor(type, options = {}) { this.type = type; this.detail = options.detail; }
};
global.document = { documentElement: { lang: "" } };
global.window = {
  localStorage: {
    getItem: (key) => stored.get(key) || null,
    setItem: (key, value) => stored.set(key, value),
  },
  addEventListener(type, callback) {
    const callbacks = listeners.get(type) || [];
    callbacks.push(callback);
    listeners.set(type, callbacks);
  },
  dispatchEvent(event) {
    for (const callback of listeners.get(event.type) || []) callback(event);
  },
};

require("../app/static/ui_text.js");

const { UI_I18N: i18n, UI_TEXT: text, UI_TEXTS: texts } = window;
assert.deepEqual(Object.keys(texts.es).sort(), Object.keys(texts.en).sort());
assert.deepEqual(Object.keys(texts.ht).sort(), Object.keys(texts.en).sort());
assert.equal(i18n.locale, "en");
assert.equal(text.todayTitle, "Today");
assert.equal(document.documentElement.lang, "en");

const liveTextObject = text;
i18n.setLocale("es");
assert.strictEqual(window.UI_TEXT, liveTextObject);
assert.equal(text.todayTitle, "Hoy");
assert.equal(text.sameCatQuestion, "¿Es el mismo gato?");
assert.equal(text.shareSponsorReport, "Compartir informe para patrocinadores");
assert.equal(i18n.translateContent("New cat from photo"), "Gato nuevo registrado a partir de la foto");
assert.equal(
  i18n.translateContent("Dark stripe extending outward from the eye across the cheek."),
  "Franja oscura que se extiende desde el ojo por la mejilla.",
);
assert.equal(i18n.translateContent("Sombra was fixed at the clinic today."), "Sombra fue esterilizado hoy en la clínica.");
assert.equal(document.documentElement.lang, "es");
assert.equal(stored.get("ccw-locale"), "es");

const attributes = {};
const control = {
  dataset: {},
  innerHTML: "",
  value: "",
  setAttribute: (name, value) => { attributes[name] = value; },
  addEventListener: (type, callback) => { control[type] = callback; },
};
i18n.bindControl(control);
assert.equal(control.value, "es");
assert.match(control.innerHTML, /value="ht">KR/);
assert.equal(attributes["aria-label"], "Idioma");
control.value = "ht";
control.change();
assert.equal(i18n.locale, "ht");
assert.equal(text.todayTitle, "Jodi a");
assert.equal(text.sameCatQuestion, "Menm chat la?");
assert.equal(text.shareSponsorReport, "Pataje rapò pou esponsò");
assert.equal(i18n.translateContent("New cat from photo"), "Nouvo chat anrejistre apati foto a");
assert.equal(
  i18n.translateContent("Dark stripe extending outward from the eye across the cheek."),
  "Bann nwa ki soti nan je a epi pase sou bò figi a.",
);
assert.equal(i18n.translateContent("Sombra was fixed at the clinic today."), "Yo te esterilize Sombra nan klinik la jodi a.");
assert.equal(document.documentElement.lang, "ht");
assert.equal(control.value, "ht");
assert.equal(attributes["aria-label"], "Lang");

i18n.setLocale("not-a-locale");
assert.equal(i18n.locale, "en");

console.log("English/Spanish/Haitian Creole UI text checks passed");
