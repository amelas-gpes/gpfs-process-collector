"use strict";
// What a person reads when the app opens without a usable provider key. The real
// init() and notice() of web/app.js run against a minimal DOM boundary; the only
// request is a stand-in for /api/config. No browser, provider, package or network.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");
const GENERIC = "The AI service is not configured. Add the API key in local settings, then restart the app. You can still open a saved interview or the fictional example.";
const FAILED = "The app could not read its local configuration. Choose Check configuration to try again.";
const PROBLEM = "The API key configured for this app contains a space, a line break or a character " +
  "that a key cannot contain, so it was not used. Re-enter the key in the local API settings, then restart the app.";
let passed = 0;

function element(id) {
  const classes = new Set(), parts = new Map();
  return {id, hidden:false, textContent:"", value:"", dataset:{},
    classList:{toggle:(name, on) => {if (on) classes.add(name); else classes.delete(name); return on;}, contains:name => classes.has(name)},
    querySelector(selector) {if (!parts.has(selector)) parts.set(selector, element(id + " " + selector)); return parts.get(selector);},
    contains:() => false, setAttribute(name,value){this[name]=String(value);}, addEventListener() {}};
}

// Opens the page as index.html ships it (notice and inline errors hidden, the
// interview view in front) and lets init() read the given /api/config reply.
async function open(reply) {
  const nodes = new Map(), requests = [], timers = [];
  const node = id => {if (!nodes.has(id)) nodes.set(id, element(id)); return nodes.get(id);};
  for (const id of ["global-notice", "interview-error", "review-error", "review-view", "connection-state"]) node(id).hidden = true;
  const scope = {
    console, window:{}, document:{getElementById:node, activeElement:null, addEventListener() {}},
    fetch:async (url, options) => {requests.push([url, options]); return reply;},
    setTimeout:(fn, delay) => timers.push([fn, delay]), clearTimeout:() => {}, AbortController
  };
  // Event wiring, panels and voices are not under test; init() and notice() are the real ones.
  const hook = `
    initEvents=()=>{};renderCoverage=()=>{};updateControls=()=>{};refreshVoices=()=>{};populateVoiceOptions=()=>{};
    createDocumentIntake=()=>null;
    window.startupTest={init,state};
  })();`;
  const patched = source.replace(/  init\(\);\s*\}\)\(\);\s*$/, hook);
  assert.notEqual(patched, source, "Install a test hook only at application initialization");
  vm.createContext(scope); vm.runInContext(patched, scope, {filename:"app.js"});
  await scope.window.startupTest.init();
  assert.deepEqual(requests.map(([url]) => url), ["/api/config"], "Opening the page asks only for its configuration");
  return {
    state:scope.window.startupTest.state,
    shown:{notice:node("notice-text").textContent, inline:node("interview-error").querySelector("span").textContent,
      spoken:node("live-status").textContent},
    noticeHidden:node("global-notice").hidden, noticeIsError:node("global-notice").classList.contains("error"),
    inlineHidden:node("interview-error").hidden, reviewErrorHidden:node("review-error").hidden,
    connection:node("configuration-status").hidden?"Ready":"Unavailable"
  };
}
const config = extra => ({ok:true, json:async () => ({csrf_token:"synthetic-token", data_notice:"Synthetic notice.", ...extra})});
const everywhere = sentence => ({notice:sentence, inline:sentence, spoken:sentence});
async function check(name, fn) {try {await fn(); passed++;} catch (error) {error.message = name + ": " + error.message; throw error;}}

(async () => {
  await check("the server's explanation of an unusable key is what the person reads", async () => {
    const page = await open(config({api_configured:false, api_problem:PROBLEM}));
    assert.deepEqual(page.shown, everywhere(PROBLEM));
    assert.equal(page.noticeHidden, false); assert.equal(page.noticeIsError, true);
    assert.equal(page.inlineHidden, false); assert.equal(page.reviewErrorHidden, true);
    assert.equal(page.connection, "Unavailable"); assert.equal(page.state.config.api_configured, false);
  });

  await check("without an explanation the generic sentence is shown", async () => {
    for (const extra of [{api_configured:false}, {api_configured:false, api_problem:""}, {}]) {
      const page = await open(config(extra));
      assert.deepEqual(page.shown, everywhere(GENERIC), JSON.stringify(extra));
      assert.equal(page.noticeIsError, true); assert.equal(page.inlineHidden, false);
      assert.equal(page.connection, "Unavailable");
    }
  });

  await check("an explanation that is not plain text of a sensible length is never shown", async () => {
    for (const api_problem of [42, true, null, ["text"], {text:"x"}, "x".repeat(601)]) {
      const page = await open(config({api_configured:false, api_problem}));
      assert.deepEqual(page.shown, everywhere(GENERIC), JSON.stringify(api_problem).slice(0, 40));
      assert.equal(page.connection, "Unavailable");
    }
  });

  await check("a configured app opens without any notice", async () => {
    for (const extra of [{api_configured:true}, {api_configured:true, api_problem:PROBLEM}]) {
      const page = await open(config(extra));
      assert.deepEqual(page.shown, everywhere(""));
      assert.equal(page.noticeHidden, true); assert.equal(page.inlineHidden, true);
      assert.equal(page.connection, "Ready"); assert.equal(page.state.config.api_configured, true);
    }
  });

  // knowledge-store-6: a saved store that was damaged at start-up switches off one feature, and the page says which.
  await check("a switched-off saved store is explained when the page opens", async () => {
    const FILES = "Reference files are switched off: the saved file database on this computer (documents.sqlite3) is damaged and was not opened.";
    const KNOWLEDGE = "Company knowledge is switched off: its saved database on this computer (knowledge.sqlite3) is damaged and was not opened, so Submit process and Admin are unavailable.";
    let page = await open(config({api_configured:true, knowledge_unavailable:KNOWLEDGE}));
    assert.deepEqual(page.shown, everywhere(KNOWLEDGE));
    assert.equal(page.noticeHidden, false); assert.equal(page.noticeIsError, true);
    assert.equal(page.connection, "Ready", "The interviewer itself is available");
    page = await open(config({api_configured:true, documents_unavailable:FILES, knowledge_unavailable:KNOWLEDGE}));
    assert.deepEqual(page.shown, everywhere(FILES + " " + KNOWLEDGE));
    // With no usable key as well, the person reads both reasons, the key first.
    page = await open(config({api_configured:false, api_problem:PROBLEM, documents_unavailable:FILES}));
    assert.deepEqual(page.shown, everywhere(PROBLEM + " " + FILES));
    assert.equal(page.connection, "Unavailable");
    // A value that is not a sentence of sensible length is ignored and never hides the app.
    for (const odd of [42, true, null, ["text"], {text:"x"}, "", "x".repeat(2001)]) {
      page = await open(config({api_configured:true, documents_unavailable:odd, knowledge_unavailable:odd}));
      assert.deepEqual(page.shown, everywhere(""), JSON.stringify(odd).slice(0, 40));
      assert.equal(page.noticeHidden, true); assert.equal(page.connection, "Ready");
    }
  });

  await check("a failed or unusable configuration reply keeps the generic sentence", async () => {
    for (const reply of [{ok:false, json:async () => ({error:PROBLEM})}, {ok:true, json:async () => ({api_configured:false, api_problem:PROBLEM})}]) {
      const page = await open(reply);
      assert.deepEqual(page.shown, everywhere(FAILED));
      assert.equal(page.connection, "Unavailable");
    }
  });

  console.log(`startup notice checks passed: ${passed}`);
})().catch(error => {console.error(error); process.exitCode = 1;});
