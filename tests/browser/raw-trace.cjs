"use strict";
// A real browser, a loopback server, and the existing fully synthetic model adapter.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {spawn} = require("node:child_process");
const {once} = require("node:events");
const {chromium} = require(process.env.COLLECTOR_PLAYWRIGHT || "playwright");

async function main() {
  const base = path.resolve(__dirname, "../../work/raw-trace-validation");
  fs.mkdirSync(base, {recursive:true});
  const dir = fs.mkdtempSync(path.join(base, "synthetic-browser-"));
  const child = spawn(process.env.VOICE_INTERVIEWER_PYTHON, ["-I", "-B", path.join(__dirname, "serve.py"), "--trace-work", dir],
    {windowsHide:true, stdio:["ignore","pipe","inherit"]});
  let browser;
  const ended = once(child, "exit");
  const timeout = setTimeout(() => child.kill(), 90000);
  try {
    const data = await Promise.race([once(child.stdout, "data"), ended.then(() => {throw Error("Synthetic server stopped before announcing its URL");})]);
    const url = new URL(data[0].toString().trim());
    assert.equal(url.hostname, "127.0.0.1");
    browser = await chromium.launch({headless:true, executablePath:process.env.COLLECTOR_BROWSER,
      args:["--disable-background-networking","--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost"]});
    const context = await browser.newContext();
    await context.route("**/*", route => new URL(route.request().url()).origin === url.origin ? route.continue() : route.abort());
    const page = await context.newPage();
    const second = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await Promise.all([page.goto(url.href), second.goto(url.href)]);
    await page.waitForFunction(() => window.CollectorRawTrace !== undefined);
    assert.equal(await page.locator("#developer-trace-notice").count(), 0);
    const token = await page.evaluate(async () => (await (await fetch("/api/config")).json()).csrf_token);
    const answer = "The fictional registrar enters  two spaces before filing the waiver.";
    await page.locator("#type-instead").click();
    await page.locator("#answer-text").fill("unsent-canary-748129");
    await page.locator("#answer-text").fill(answer);
    await page.locator("#send-answer").click();
    await page.getByText("What happens after the invoice is logged?", {exact:true}).first().waitFor({state:"attached"});
    const folder = path.join(dir, "raw-trace");
    const traceFile = path.join(folder, fs.readdirSync(folder).find(name => name.endsWith(".jsonl")));
    // The active writer can have an unfinished final line when sampled.
    const records = () => fs.readFileSync(traceFile, "utf8").split("\n").slice(0,-1).map(line => JSON.parse(line));
    const hasText = (row, value) => JSON.stringify(row.payload).includes(value);
    await page.waitForFunction(() => window.CollectorRawTrace !== undefined);
    for (let i = 0; i < 60; i++) {
      const rows = records();
      if (rows.some(r => r.type === "browser.transcript.rendered" && hasText(r, answer))
            && new Set(rows.filter(r => r.type === "browser.page.script_loaded").map(r => r.producer_id)).size === 2) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    const rows = records();
    for (const type of ["browser.turn.created","browser.transcript.rendered","http.json_parsed"]) {
      assert(rows.some(row => row.type === type && hasText(row, answer)), type);
    }
    const request = rows.find(row => row.type === "http.json_parsed" && hasText(row, answer));
    assert(rows.some(row => row.type === "browser.http.dispatched" && row.operation_id === request.operation_id));
    assert.equal(new Set(rows.filter(row => row.type === "browser.page.script_loaded").map(row => row.producer_id)).size, 2);
    const raw = fs.readFileSync(traceFile, "utf8");
    assert(!raw.includes(token) && !raw.includes("unsent-canary-748129"));
    await page.locator("#session-menu-toggle").click();
    await page.locator("#open-interview-settings").click();
    await page.locator("#logs-details > summary").click();
    await page.waitForFunction(() => document.getElementById("logs-entries").childElementCount > 0 && !document.getElementById("logs-refresh").disabled);
    assert.match(await page.locator("#logs-status").innerText(), /Interview content and activity/);
    await page.locator("#logs-search").fill("browser.turn.created");
    assert(await page.locator(".log-entry").count() > 0);
    await page.locator("#logs-search").fill("The fictional registrar enters");
    await page.locator(".log-entry summary").first().click();
    assert((await page.locator(".log-entry pre").first().innerText()).includes(answer));
    await page.locator("#logs-search").fill("no-such-event-748129");
    assert.equal(await page.locator(".log-entry").count(), 0);
    assert.match(await page.locator("#logs-entries").innerText(), /No loaded entries match/);
    await page.locator("#logs-search").fill("");
    await page.locator("#logs-scope").selectOption("current");
    await page.waitForFunction(() => !document.getElementById("logs-refresh").disabled);
    await page.locator("#logs-refresh").click();
    await page.waitForFunction(() => !document.getElementById("logs-refresh").disabled);
    await page.setViewportSize({width:390, height:844});
    assert(await page.locator("#interview-settings").evaluate(element => element.scrollWidth <= element.clientWidth));
    await page.screenshot({path:path.join(dir, "settings-logs-mobile.png")});
    await page.setViewportSize({width:1280, height:900});
    await page.screenshot({path:path.join(dir, "settings-logs-desktop.png")});
    const reader = "**/api/trace/logs?*";
    await page.route(reader, route => route.fulfill({json:{events:[],status:{mode:"off",enabled:false}}}));
    await page.locator("#logs-refresh").click();
    await page.waitForFunction(() => !document.getElementById("logs-refresh").disabled);
    assert.match(await page.locator("#logs-status").innerText(), /Logging is off/);
    assert.match(await page.locator("#logs-entries").innerText(), /No saved entries/);
    await page.unroute(reader);
    await page.route(reader, route => route.fulfill({status:503,json:{error:"Synthetic read failure"}}));
    await page.locator("#logs-refresh").click();
    await page.waitForFunction(() => !document.getElementById("logs-refresh").disabled);
    assert.match(await page.locator("#logs-status").innerText(), /could not be loaded/);
    await page.unroute(reader);
    await page.route(reader, route => route.fulfill({json:{events:[{type:"test.literal",payload:{text:'<img src=x onerror="window.logInjected=true">'}}],status:{mode:"content",enabled:true}}}));
    await page.locator("#logs-refresh").click();
    await page.waitForFunction(() => !document.getElementById("logs-refresh").disabled);
    await page.locator(".log-entry summary").click();
    assert.equal(await page.locator("#logs-entries img").count(), 0);
    assert((await page.locator(".log-entry pre").innerText()).includes("<img"));
    assert.equal(await page.evaluate(() => Boolean(window.logInjected)), false);
    await page.unroute(reader);
    await page.locator("#logs-refresh").click();
    await page.waitForFunction(() => !document.getElementById("logs-refresh").disabled);
    assert(await page.locator(".log-entry").count() > 0);
    assert.deepEqual(errors, []);
    await browser.close();
    browser = null;
    const stopping = await fetch(new URL("api/shutdown", url), {method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":token},body:"{}"});
    assert(stopping.ok);
    const [exitCode] = await ended;
    assert.equal(exitCode, 0);
    console.log("Verified typed commit, render, matching request, two tabs and secret exclusions. Raw synthetic trace:", traceFile);
  } finally {
    clearTimeout(timeout);
    if (browser) await browser.close();
    if (child.exitCode === null) child.kill();
  }
}
main().catch(error => {console.error(error); process.exitCode = 1;});
