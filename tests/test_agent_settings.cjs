"use strict";

const assert = require("node:assert/strict");
const {open} = require("./fixtures/app_page.cjs");
const catalogPath = "/api/admin/agent-prompts";
const prompt = "  Use <file> literally.\nRetain the full instruction.\n";
const catalog = {agents:[
  {id:"lead_interviewer", label:"Lead interviewer", description:"Ask follow-up questions.", prompts:[
    {id:"question", label:"Question", when:"During an interview.", text:"Ask one question."},
    {id:"notes", label:"Capture notes", when:"After an answer.", text:prompt}]},
  {id:"live_interviewer", label:"Live interviewer", description:"Handle live voice.", prompts:[
    {id:"conversation", label:"Conversation", when:"During live voice.", text:"Use the agreed wording."}]}
]};

async function settings(admin) {
  const page = await open({modules:["settings-ui.js", "agent-flow.js", "agent-settings.js"],
    config:{agent_prompts_available:admin}});
  page.context.Event = page.context.CustomEvent = class {
    constructor(type, options) { this.type = type; Object.assign(this, options); }
  };
  page.$("session-menu-toggle").click();
  page.$("open-interview-settings").click();
  return page;
}

async function main() {
  const participant = await settings(false);
  assert.equal(participant.shown("settings-tab-agents"), false);
  participant.window.CollectorSettings.show("agents-details");
  assert.equal(participant.shown("agents-details"), false);
  participant.$("settings-search").input("prompt library");
  assert.equal(participant.$("settings-search-matches").children.length, 0);
  participant.$("settings-search").input("");
  participant.$("settings-tab-usage").dispatchEvent({type:"keydown", key:"ArrowDown"});
  assert.equal(participant.document.activeElement.id, "settings-tab-logs");
  assert.equal(participant.requests.some(r => r.url === catalogPath), false);

  const page = await settings(true);
  const adminTab = page.$("settings-tab-agents");
  assert.ok(adminTab.visible);
  assert.equal(page.requests.some(r => r.url === catalogPath), false);
  page.route((url, options) => {
    assert.equal(url, catalogPath);
    assert.equal(options.method || "GET", "GET");
    assert.equal(options.headers["X-CSRF-Token"], page.state.config.csrf_token);
    assert.equal(options.cache, "no-store");
    return structuredClone(catalog);
  });
  page.$("settings-search").input("prompt library");
  page.$("settings-search-matches").querySelector("button").click();
  await page.flush();
  assert.equal(page.shown("agents-overview"), true);
  assert.equal(page.shown("agents-library"), false);
  page.$("agents-overview").querySelector('[data-agent="lead_interviewer"]').click();
  assert.equal(page.shown("agents-library"), true);
  assert.equal(page.document.activeElement.id, "agent-select");
  assert.equal(page.text("agent-description"), "Ask follow-up questions.");
  page.$("agent-prompt-select").input("notes");
  assert.equal(page.text("agent-prompt-when"), "After an answer.");
  assert.equal(page.$("agent-prompt-text").textContent, prompt);
  assert.equal(page.$("agent-prompt-text").children.length, 0, "Prompt syntax stays literal");
  assert.equal(page.$("agents-details").querySelector("textarea,[contenteditable]"), null);
  let copied;
  page.window.navigator.clipboard = {async writeText(value) { copied = value; }};
  page.$("agent-copy-prompt").click();
  await page.flush();
  assert.equal(copied, prompt, "The entire prompt, including whitespace, is copied");
  assert.equal(page.text("agent-copy-status"), "Prompt copied.");
  page.$("agent-select").input("live_interviewer");
  assert.equal(page.text("agent-copy-status"), "");
  assert.equal(page.$("agent-prompt-select").value, "conversation");
  page.$("agent-prompt-select").input("live-file-withdrawn");
  assert.match(page.$("agent-prompt-text").textContent, /\{file name\}/, "Browser-owned live instructions are included using placeholders");
  const range = {selectNodeContents(node) {this.node = node;}};
  const selection = {removeAllRanges() {this.range = null;}, addRange(value) {this.range = value;}};
  page.window.navigator.clipboard = {async writeText() { throw Error("Permission denied"); }};
  page.window.getSelection = () => selection;
  page.document.createRange = () => range;
  page.document.execCommand = () => false;
  page.$("agent-copy-prompt").click();
  await page.flush();
  assert.equal(selection.range.node, page.$("agent-prompt-text"));
  assert.match(page.text("agent-copy-status"), /selected.*Copy command/);
  page.document.execCommand = () => true;
  page.$("agent-copy-prompt").click();
  await page.flush();
  assert.equal(page.text("agent-copy-status"), "Prompt copied.");
  assert.equal(page.document.activeElement.id, "agent-copy-prompt");
  page.$("agents-overview-button").click();
  assert.equal(page.shown("agents-overview"), true);
  page.$("close-interview-settings").click();
  assert.equal(page.text("agent-prompt-text"), "");
  assert.equal(page.$("agents-overview").children.length, 0);
  page.route(() => ({ok:false, status:503, json:async () => ({error:"Temporary"})}));
  page.$("session-menu-toggle").click();
  page.$("open-interview-settings").click();
  await page.flush();
  assert.ok(page.shown("agents-retry"));
  assert.equal(page.shown("agents-content"), false);
  page.route(() => ({ok:false, status:403, json:async () => ({code:"admin_required"})}));
  page.$("agents-retry").click();
  await page.flush();
  assert.ok(page.shown("agents-access-notice"));
  assert.equal(adminTab.hidden, true);
  assert.equal(page.shown("preferences-details"), true);
  assert.equal(page.text("agent-prompt-text"), "");

  const race = await settings(true);
  let finish;
  race.route(() => new Promise(resolve => {finish = resolve;}));
  race.$("settings-tab-agents").click();
  race.$("settings-tab-data").click();
  finish(catalog);
  await race.flush();
  assert.equal(race.text("agent-prompt-text"), "", "Late responses cannot repopulate a closed view");
  console.log("Agent Settings: admin navigation, workflow, full prompt text, clipboard, retry, access changes and late responses passed.");
}

main().catch(error => { console.error(error); process.exitCode = 1; });
