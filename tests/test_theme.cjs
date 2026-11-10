"use strict";

const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

const web = path.resolve(__dirname, "../web");
const html = readFileSync(path.join(web, "index.html"), "utf8");
const script = readFileSync(path.join(web, "theme.js"), "utf8");
const key = "process-collector.theme";

function openTab({ dark = false, saved, blocked = false } = {}) {
  function target(properties = {}) {
    const listeners = new Map();
    return Object.assign(properties, {
      addEventListener(type, handler) { listeners.set(type, handler); },
      fire(type, event = {}) { listeners.get(type)?.(event); },
    });
  }
  const media = target({ matches: dark });
  const select = target({ value: "" });
  const metas = { "color-scheme": {}, "theme-color": {} };
  const values = new Map(saved === undefined ? [] : [[key, saved]]);
  const dataset = {};
  const document = target({
    documentElement: { dataset },
    querySelector(selector) { return metas[selector.match(/name="([^"]+)"/)[1]]; },
    getElementById(id) { assert.equal(id, "theme-select"); return select; },
  });
  const window = target({
    matchMedia(query) { assert.equal(query, "(prefers-color-scheme: dark)"); return media; },
    get localStorage() {
      if (blocked) throw new Error("Browser storage disabled");
      return {
        getItem(name) { return values.get(name) ?? null; },
        setItem(name, value) { values.set(name, value); },
        removeItem(name) { values.delete(name); },
      };
    },
  });
  vm.runInNewContext(script, { document, window });
  return {
    dataset, metas, select, values,
    ready() { document.fire("DOMContentLoaded"); },
    system(dark) { media.matches = dark; media.fire("change"); },
    choose(value) { select.value = value; select.fire("change"); },
    storage(eventKey) { window.fire("storage", { key: eventKey }); },
  };
}

test("the preference script runs before the first stylesheet and before the settings control exists", () => {
  const bootstrap = html.match(/<script\b[^>]*\bsrc="\/theme\.js"[^>]*>/i);
  const style = html.match(/<link\b[^>]*\brel="stylesheet"/i);
  assert.ok(bootstrap && style && bootstrap.index < style.index);
  assert.doesNotMatch(bootstrap[0], /\b(?:defer|async)\b/);
  const tab = openTab({ dark: true, saved: "light" });
  assert.equal(tab.dataset.theme, "light");
  assert.equal(tab.metas["color-scheme"].content, "light");
  tab.ready();
  assert.equal(tab.select.value, "light");
});

test("invalid or missing preferences follow live system changes until an explicit choice", () => {
  for (const saved of [undefined, "unknown"]) {
    const tab = openTab({ dark: true, saved });
    tab.ready();
    assert.equal(tab.select.value, "system");
    assert.equal(tab.dataset.theme, "dark");
    tab.system(false);
    assert.equal(tab.dataset.theme, "light");
    tab.choose("dark");
    assert.equal(tab.values.get(key), "dark");
    tab.system(true);
    tab.system(false);
    assert.equal(tab.dataset.theme, "dark");
    tab.choose("system");
    assert.equal(tab.values.has(key), false);
    assert.equal(tab.dataset.theme, "light");
  }
});

test("storage changes in another tab update open controls, including after clearing storage", () => {
  const tab = openTab();
  tab.ready();
  tab.values.set(key, "dark");
  tab.storage(key);
  assert.equal(tab.select.value, "dark");
  assert.equal(tab.dataset.theme, "dark");
  tab.values.clear();
  tab.storage(null);
  assert.equal(tab.select.value, "system");
  assert.equal(tab.dataset.theme, "light");
});

test("settings still work in the current tab when browser storage is blocked", () => {
  const tab = openTab({ dark: false, blocked: true });
  tab.ready();
  tab.choose("dark");
  assert.equal(tab.dataset.theme, "dark");
  tab.choose("system");
  assert.equal(tab.dataset.theme, "light");
  tab.system(true);
  assert.equal(tab.dataset.theme, "dark");
});
