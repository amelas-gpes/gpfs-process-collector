"use strict";
// An open page survives a restart of the local server. The server issues a new request token
// each time it starts, so every POST from a page opened before the restart is answered 403.
// The real request() of web/app.js runs against a minimal DOM boundary with a scripted fetch:
// no browser, provider, package or network.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");
const REJECTED = "This page's connection to the local app is out of date, usually because the app was restarted. " +
  "Nothing was processed. Use More options > Save copy to keep your interview before you reload this page.";
const RELOAD = "The local app was restarted with a different version while this page was open, so this page can no longer " +
  "send requests. Use More options > Save copy to keep your interview, then reload this page.";
let passed = 0;

function element(id) {
  const classes = new Set(), parts = new Map();
  return {id, hidden:false, textContent:"", value:"", dataset:{},
    classList:{toggle:(name, on) => {if (on) classes.add(name); else classes.delete(name); return on;}, contains:name => classes.has(name)},
    querySelector(selector) {if (!parts.has(selector)) parts.set(selector, element(id + " " + selector)); return parts.get(selector);},
    contains:() => false, addEventListener() {}};
}
const reply = (status, body) => ({ok:status >= 200 && status < 300, status, json:async () => body, blob:async () => body});
const config = (token, build = "build-1") => reply(200, {csrf_token:token, build_id:build, api_configured:true, data_notice:"Synthetic notice."});

// Opens the page with token "A", then answers each later fetch from `script` in order.
async function open(script) {
  const nodes = new Map(), calls = [];
  const node = id => {if (!nodes.has(id)) nodes.set(id, element(id)); return nodes.get(id);};
  let started = false;
  const scope = {
    console, window:{}, document:{getElementById:node, activeElement:null, addEventListener() {}},
    fetch:async (url, options = {}) => {
      if (!started) {started = true; return config("A");}
      calls.push({url, method:options.method || "GET", token:options.headers?.["X-CSRF-Token"], body:options.body});
      const next = script.shift();
      assert.ok(next, `Unexpected request: ${options.method || "GET"} ${url}`);
      if (next instanceof Error) throw next;
      return typeof next === "function" ? next(url, options) : next;
    },
    setTimeout:() => 0, clearTimeout:() => {}, AbortController, DOMException, Blob, crypto:{randomUUID:() => "00000000-0000-4000-8000-000000000000"}
  };
  const hook = `
    initEvents=()=>{};renderCoverage=()=>{};updateControls=()=>{};refreshVoices=()=>{};populateVoiceOptions=()=>{};
    createDocumentIntake=()=>null;
    window.renewalTest={init,state,request,renewRequestToken};
  })();`;
  const patched = source.replace(/  init\(\);\s*\}\)\(\);\s*$/, hook);
  assert.notEqual(patched, source, "Install a test hook only at application initialization");
  vm.createContext(scope); vm.runInContext(patched, scope, {filename:"app.js"});
  const app = scope.window.renewalTest;
  await app.init();
  assert.equal(app.state.config.csrf_token, "A");
  return {app, calls, left:() => script.length};
}
const failure = async promise => {try {await promise;} catch (error) {return error;} assert.fail("The request should have failed");};
async function check(name, fn) {try {await fn(); passed++;} catch (error) {error.message = name + ": " + error.message; throw error;}}
const sent = calls => calls.map(call => `${call.method} ${call.url}${call.token ? " " + call.token : ""}`);

(async () => {
  await check("a request rejected after a restart is sent again with the server's new token", async () => {
    const page = await open([reply(403, {error:REJECTED}), config("B"), reply(200, {text:"recognized"}), reply(200, {ok:true})]);
    const result = await page.app.request("/api/voice-session", {voice:"marin"});
    assert.deepEqual(JSON.parse(JSON.stringify(result)), {text:"recognized"});
    assert.deepEqual(sent(page.calls), ["POST /api/voice-session A", "GET /api/config", "POST /api/voice-session B"]);
    assert.equal(page.calls[0].body, page.calls[2].body, "The same request is sent again, unchanged");
    assert.equal(page.app.state.config.csrf_token, "B");
    assert.equal(page.app.state.config.build_id, "build-1");
    // The page keeps working with the new token without asking again.
    page.calls.length = 0;
    await page.app.request("/api/voice-session", {voice:"marin"});
    assert.deepEqual(sent(page.calls), ["POST /api/voice-session B"]);
  });

  await check("a recording is sent again as well", async () => {
    const audio = new Blob([new Uint8Array(2048)], {type:"audio/webm"});
    const page = await open([reply(403, {error:REJECTED}), config("B"), reply(200, {text:"spoken answer"})]);
    await page.app.request("/api/transcribe", audio);
    assert.equal(page.calls[2].body, audio);
    assert.equal(page.calls[2].token, "B");
  });

  await check("a different build is never retried: the person is told to save a copy and reload", async () => {
    const page = await open([reply(403, {error:REJECTED}), config("B", "build-2")]);
    const error = await failure(page.app.request("/api/voice-session", {voice:"marin"}));
    assert.equal(error.message, RELOAD);
    assert.equal(error.status, 403);
    assert.deepEqual(sent(page.calls), ["POST /api/voice-session A", "GET /api/config"]);
    assert.equal(page.app.state.config.csrf_token, "A", "A page built for another version does not adopt the new token");
    assert.equal(page.left(), 0);
  });

  await check("another kind of 403 is not retried and keeps the server's own message", async () => {
    // One that names its own cause does not even ask for the configuration (the file list polls).
    const workspace = "The saved file workspace is unavailable on this computer.";
    let page = await open([reply(403, {error:workspace, code:"document_scope_unavailable"})]);
    let error = await failure(page.app.request("/api/voice-session", {voice:"marin"}));
    assert.equal(error.message, workspace);
    assert.equal(error.code, "document_scope_unavailable");
    assert.deepEqual(sent(page.calls), ["POST /api/voice-session A"]);
    // One without a code is checked against the configuration; the token is unchanged, so it is reported.
    const denied = "Administrator access is unavailable.";
    page = await open([reply(403, {error:denied}), config("A")]);
    error = await failure(page.app.request("/api/voice-session", {voice:"marin"}));
    assert.equal(error.message, denied);
    assert.deepEqual(sent(page.calls), ["POST /api/voice-session A", "GET /api/config"]);
    assert.equal(page.app.state.config.csrf_token, "A");
  });

  await check("the server's coded token rejection is renewed the same way", async () => {
    const page = await open([reply(403, {error:REJECTED, code:"request_token_rejected"}), config("B"), reply(200, {ok:true})]);
    await page.app.request("/api/voice-session", {voice:"marin"});
    assert.deepEqual(sent(page.calls), ["POST /api/voice-session A", "GET /api/config", "POST /api/voice-session B"]);
  });

  await check("the retry happens once: a second rejection is reported", async () => {
    const page = await open([reply(403, {error:REJECTED}), config("B"), reply(403, {error:REJECTED})]);
    const error = await failure(page.app.request("/api/voice-session", {voice:"marin"}));
    assert.equal(error.message, REJECTED);
    assert.equal(error.status, 403);
    assert.equal(page.calls.length, 3);
  });

  await check("when the configuration cannot be read the original rejection is reported", async () => {
    for (const answer of [reply(503, {error:"busy"}), new TypeError("Failed to fetch"), reply(200, {build_id:"build-1"}),
                          reply(200, {csrf_token:42, build_id:"build-1"}), reply(200, null)]) {
      const page = await open([reply(403, {error:REJECTED}), answer]);
      const error = await failure(page.app.request("/api/voice-session", {voice:"marin"}));
      assert.equal(error.message, REJECTED);
      assert.equal(page.app.state.config.csrf_token, "A");
      assert.equal(page.calls.length, 2);
    }
  });

  await check("requests rejected together ask for the configuration once and are all sent again", async () => {
    let release;
    const gate = new Promise(resolve => {release = resolve;});
    const answers = {posts:0, configs:0};
    const page = await open(Array.from({length:7}, () => async (url, options) => {
      if (url === "/api/config") {answers.configs++; await gate; return config("B");}
      answers.posts++;
      return options.headers["X-CSRF-Token"] === "B" ? reply(200, {ok:true}) : reply(403, {error:REJECTED});
    }));
    const pending = [page.app.request("/api/voice-session", {voice:"marin"}), page.app.request("/api/voice-session", {voice:"cedar"}),
      page.app.request("/api/voice-session", {voice:"alloy"})];
    await new Promise(resolve => setImmediate(resolve));
    await new Promise(resolve => setImmediate(resolve));
    release();
    const results = await Promise.all(pending);
    assert.equal(results.length, 3);
    assert.equal(answers.configs, 1, "One renewal serves every request that was rejected with the old token");
    assert.equal(answers.posts, 6);
    // A request that was rejected with the old token after the renewal finished needs no second renewal.
    assert.equal(await page.app.renewRequestToken("A"), true);
    assert.equal(page.left(), 0);
  });

  console.log(`token renewal checks passed: ${passed}`);
})().catch(error => {console.error(error); process.exitCode = 1;});
