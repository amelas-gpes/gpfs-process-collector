"use strict";
// Optional cross-browser regression. Supply existing interpreter, Playwright and browser paths.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {spawn} = require("node:child_process");
const {once} = require("node:events");
const {text} = require("node:stream/consumers");
const {chromium} = require(process.env.COLLECTOR_PLAYWRIGHT || "playwright");

async function localServer() {
  const child = spawn(process.env.VOICE_INTERVIEWER_PYTHON || "python", ["-I", "-B", path.join(__dirname, "serve.py")],
    {stdio:["ignore", "pipe", "inherit"], windowsHide:true});
  const timeout = setTimeout(() => child.kill(), 30000);
  try {
    const first = await Promise.race([once(child.stdout, "data"), once(child, "exit").then(() => {throw Error("Test server exited before startup");})]);
    const url = first[0].toString().trim();
    assert.match(url, /^http:\/\/127\.0\.0\.1:\d+\/$/);
    return {child, url};
  } finally {
    clearTimeout(timeout);
  }
}

async function main() {
  const executablePath = process.env.COLLECTOR_BROWSER;
  assert(executablePath && fs.existsSync(executablePath), "Set COLLECTOR_BROWSER to an installed Edge or Chrome executable.");
  const seed = Number(process.argv[2] || 17);
  let state = seed >>> 0;
  function random(max) { state = (Math.imul(state, 1664525) + 1013904223) >>> 0; return state % max; }
  const {child, url} = await localServer();
  let browser;
  try {
    browser = await chromium.launch({headless:true, executablePath, args:["--disable-background-networking",
      "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1", "--no-first-run"]});
    const context = await browser.newContext({viewport:{width:1280, height:840}});
    const page = await context.newPage();
    const errors = [];
    const adminRequests = [];
    context.on("request", request => {
      if (new URL(request.url()).pathname.startsWith("/api/knowledge/admin/")) adminRequests.push(request.url());
    });
    page.on("pageerror", error => errors.push(error.message));
    await context.route("**/*", route => {
      const target = new URL(route.request().url());
      return target.protocol === "http:" && target.origin !== new URL(url).origin || target.protocol === "https:"
        ? route.abort() : route.continue();
    });
    await page.goto(url, {waitUntil:"domcontentloaded"});
    const navbarContext=page.getByRole("navigation",{name:"Workspace"}).getByRole("button",{name:"Context",exact:true});
    await navbarContext.focus();
    await page.keyboard.press("Enter");
    await page.waitForFunction(()=>document.activeElement===document.getElementById("process-owner"));
    await page.keyboard.press("Escape");
    await page.waitForFunction(()=>document.activeElement===document.querySelector("#open-context")&&!document.querySelector("#interview-settings").open);
    await page.getByRole("button",{name:"More options",exact:true}).click();
    await page.locator("#open-interview-settings").click();
    assert.equal(await page.locator("#knowledge-admin, #open-knowledge-admin").count(), 0);
    const guide=page.locator("#help-guide");
    await page.locator("#settings-tab-help").focus();
    await page.keyboard.press("Enter");
    assert(await guide.isVisible(),"The Settings guide is selected with Enter");
    await page.keyboard.press("ArrowUp");
    assert(await page.locator("#logs-details").isVisible(),"Arrow keys switch Settings sections");
    await page.keyboard.press("Escape");
    await page.waitForFunction(()=>document.activeElement===document.getElementById("session-menu-toggle"));
    await page.locator("#welcome-example").click();
    const refs = ["report", "memo", "map", "procedure", "lifecycles", "variations", "questions"];
    const views = ["voice", "transcript", "workflow"];
    for (let index = 0; index < 36; index++) {
      const width = [390, 768, 1280][random(3)];
      await page.setViewportSize({width, height:840});
      let tab;
      if (random(3) === 0) {
        await page.locator('[data-tab="interview"]').click();
        tab = page.locator("#conversation-tab-" + views[random(views.length)]);
      } else {
        await page.locator('[data-tab="review"]').click();
        tab = page.locator("#review-tab-" + refs[random(refs.length)]);
      }
      await tab.click();
      assert.equal(await tab.getAttribute("aria-selected"), "true", "seed " + seed + ", action " + index);
      assert.equal(await page.locator("#" + await tab.getAttribute("aria-controls")).isVisible(), true);
      if (index % 6 === 0) {
        await page.locator("#session-menu-toggle").click();
        assert.equal(await page.locator("#session-menu").isVisible(), true);
        await page.keyboard.press("Escape");
        assert.equal(await page.locator("#session-menu").isVisible(), false);
      }
    }
    await page.goto(url, {waitUntil:"domcontentloaded"});
    await page.setViewportSize({width:1280, height:840});
    await page.locator("#type-instead").click();
    const reply = page.locator("#answer-text");
    await page.waitForFunction(() => document.activeElement === document.querySelector("#answer-text") &&
      !document.querySelector("#answer-text").disabled);
    const answer = "A fictional registrar logs the form when it arrives.";
    await reply.fill(answer);
    await page.locator("#send-answer").click();
    await page.waitForFunction(() => !document.querySelector("#answer-text").disabled &&
      document.querySelector("#transcript").textContent.includes("fictional registrar"));
    await page.locator("#session-menu-toggle").click();
    await page.locator("#submit-process-menu").click();
    const submission = page.locator("#knowledge-submit");
    const [filed] = await Promise.all([
      page.waitForResponse(response => response.url().endsWith("/api/knowledge/submit")),
      submission.getByRole("button", {name:/^Submit (process|anyway)$/}).click()
    ]);
    assert.equal(filed.status(), 202);
    const [status] = await Promise.all([
      page.waitForResponse(response => response.url().endsWith("/api/knowledge/status")),
      submission.getByRole("button", {name:"Refresh status"}).click()
    ]);
    assert.equal(status.status(), 200);
    assert.equal((await status.json()).revision, 1);
    await submission.getByRole("button", {name:"Close"}).click();
    await page.locator("#session-menu-toggle").click();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#export-session").click()
    ]);
    const saved = JSON.parse(await text(await download.createReadStream()));
    assert(saved.turns.some(turn => turn.role === "user" && turn.text === answer));
    await page.locator("#session-menu-toggle").click();
    page.once("dialog", dialog => dialog.accept());
    const [cleanup] = await Promise.all([
      page.waitForResponse(response => response.url().endsWith("/api/conversation/discard")),
      page.locator("#reset-session").click()
    ]);
    assert.equal(cleanup.status(),200);
    await page.waitForFunction(() => !document.querySelector("#transcript").textContent.includes("fictional registrar"));
    const config=await (await page.request.get(url+"api/config")).json();
    const headers={"X-CSRF-Token":config.csrf_token,Origin:new URL(url).origin};
    const workspace=await (await page.request.post(url+"api/documents/session",{headers,data:{}})).json();
    assert(workspace.scope);
    const sharedCopy={name:"synthetic.json",mimeType:"application/json",
      buffer:Buffer.from(JSON.stringify({...saved,documents:{scope:workspace.scope,documents:[]}}))};
    const peer=await page.context().newPage();
    peer.on("pageerror",error=>errors.push(error.message));
    await peer.goto(url,{waitUntil:"domcontentloaded"});
    for(const tab of [page,peer]){
      const restored=tab.waitForResponse(response=>response.url().endsWith("/api/documents/status"));
      await tab.locator("#session-file").setInputFiles(sharedCopy);
      assert.equal((await restored).status(),200);
    }
    await page.locator('input[type=file][accept*=".csv"]').setInputFiles({
      name:"fictional-register.csv",mimeType:"text/csv",buffer:Buffer.from("role,action\nregistrar,files form")});
    await peer.waitForFunction(()=>document.querySelector("#saved-file-followup-text").textContent.includes("fictional-register.csv"));
    assert.equal(await peer.locator("#document-intake-panel").isVisible(),false);
    assert.equal(await peer.locator("#resume-file-followup").isVisible(),true);
    await peer.close();
    assert.deepEqual(adminRequests, []);
    assert.deepEqual(errors, []);
    process.stdout.write(JSON.stringify({browser:browser.version(), seed, navigationActions:36, typedSaveAndDiscard:true,sharedFileNotice:true, pageErrors:errors.length}) + "\n");
  } finally {
    if (browser) await browser.close();
    // Normal authenticated app shutdown lets the test server drain and delete its temporary directory.
    try {
      const config = await (await fetch(url + "api/config")).json();
      await fetch(url + "api/shutdown", {method:"POST", headers:{"X-CSRF-Token":config.csrf_token},body:"{}"});
    } catch { child.kill(); }
  }
}
main().catch(error => {console.error(error);process.exitCode=1;});
