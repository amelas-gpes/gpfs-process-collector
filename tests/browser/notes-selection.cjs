"use strict";
// Real hit testing in the Notes rail and mobile sheet. Use the same local synthetic
// server and COLLECTOR_BROWSER, COLLECTOR_PLAYWRIGHT, VOICE_INTERVIEWER_PYTHON
// settings as walk.cjs. No provider calls or remote browser resources are needed.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {spawn} = require("node:child_process");
const {once} = require("node:events");
const {chromium} = require(process.env.COLLECTOR_PLAYWRIGHT || "playwright");

const purposeAnswer = "Give Treasury the approved payment instructions.";
const nameAnswer = "The handoff has no recorded name yet.";
const topic = (page, key) => page.locator(`[data-foundation-topic="${key}"]`);

async function checkDialog(page, expectedTitle, expectedAnswer) {
  await page.locator("#foundation-dialog[open]").waitFor();
  assert.equal(await page.locator("#foundation-topic-title").innerText(), expectedTitle);
  assert.equal(await page.locator("#foundation-topic-answer").innerText(), expectedAnswer);
  await page.keyboard.press("Escape");
  await page.locator("#foundation-dialog").waitFor({state:"hidden"});
}

// Aim first. Locator.click() after the update would re-aim and conceal a moving target.
async function clickAcrossUpdate(page, update) {
  const label = topic(page, "purpose").locator(".coverage-label");
  const box = await label.boundingBox();
  assert(box, "Purpose is visible");
  const x = box.x + Math.min(12, box.width / 2), y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  assert.equal(await page.evaluate(([x, y]) =>
    document.elementFromPoint(x, y)?.closest("[data-foundation-topic]")?.dataset.foundationTopic,
  [x, y]), "purpose", "The pointer starts on Purpose");
  await update();
  await page.mouse.click(x, y);
  await checkDialog(page, "Purpose", purposeAnswer);
}

async function exercise(browser, url, width) {
  const page = await browser.newPage({viewport:{width, height:900}, reducedMotion:"reduce"});
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  // Like fixtures/app_page.cjs, expose a test seam inside the application closure.
  // Supply capture inputs, leaving the page, rendering, layout and event handlers intact.
  await page.route("**/*", async route => {
    const address = new URL(route.request().url());
    if (address.origin !== new URL(url).origin) return route.abort();
    if (address.pathname !== "/app.js") return route.continue();
    const response = await route.fetch(), source = await response.text();
    const seam = source.replace(/  init\(\);\s*\}\)\(\);\s*$/, () =>
      "  window.notesFixture = {state, renderCoverage, rememberDiscussion};\n  init();\n})();");
    assert.notEqual(seam, source, "Expose the capture fixture at the application's entry point");
    return route.fulfill({response, body:seam});
  });
  try {
    await page.goto(url);
    await page.locator("#welcome-example").click();
    await page.locator('[data-tab="interview"]').click();
    await page.locator("#conversation-tab-transcript").click();
    if (await page.locator("#open-memo").isVisible()) await page.locator("#open-memo").click();
    await page.evaluate(() => {
      const {state, renderCoverage} = window.notesFixture;
      state.example = false;
      state.coverageVerified = false;
      state.config.concurrent_interview = {enabled:true};
      state.turns = [{id:"t001",role:"assistant",text:"What outcome does the work deliver?"}];
      state.memo_findings = [];
      state.coverage = [];
      state.advisory = {};
      state.consolidation = [];
      renderCoverage();
    });
    await clickAcrossUpdate(page, async () => {
      await page.evaluate(({nameAnswer, purposeAnswer}) => {
        const {state, rememberDiscussion, renderCoverage} = window.notesFixture;
        state.turns.push({id:"t002",role:"user",text:purposeAnswer});
        state.memo_findings = [
          {key:"name",status:"unknown",answer:nameAnswer,evidence_turns:[]},
          {key:"purpose",status:"captured",answer:purposeAnswer,evidence_turns:["t002"]}
        ];
        state.advisory.purpose = {answer:purposeAnswer,complete:false,gaps:["Clarify the result."],next_question:""};
        rememberDiscussion({}, {turns:state.turns}, []);
        renderCoverage();
      }, {nameAnswer, purposeAnswer});
      assert.match(await page.locator("#analysis-through").textContent(), /Notes include all 1 saved answer/);
      assert.equal(await page.locator("#coverage-count").innerText(), "1 / 16");
    });
    await clickAcrossUpdate(page, async () => {
      await page.evaluate(() => {
        const {state, renderCoverage} = window.notesFixture;
        state.turns = state.turns.filter(turn => turn.role === "user");
        state.focus = "How the supplier invoice moves from review to the payment handoff";
        state.coverageNeedsReview = true;
        state.consolidation = ["trigger","checks","data_systems"];
        renderCoverage();
      });
      assert.equal(await page.locator("#coverage-consolidation").isVisible(), true);
      assert.equal(await page.locator("#memo-focus-block").isVisible(), true);
    });
    // The native close event is queued. Dismissing the previous topic must leave focus on a
    // control the participant has already selected while that event is still pending.
    await topic(page, "name").click();
    await page.locator("#foundation-dialog[open]").waitFor();
    const focusAfterClose = await page.evaluate(async () => {
      const dialog = document.querySelector("#foundation-dialog");
      const closed = new Promise(resolve => dialog.addEventListener("close", resolve, {once:true}));
      document.querySelector("#close-foundation-topic").click();
      document.querySelector('[data-foundation-topic="purpose"]').focus();
      await closed;
      return document.activeElement.dataset.foundationTopic;
    });
    assert.equal(focusAfterClose, "purpose", "A late close event must preserve the next topic's focus");
    await topic(page, "name").click();
    const nextTopic = await page.evaluate(async () => {
      const dialog = document.querySelector("#foundation-dialog");
      const closed = new Promise(resolve => dialog.addEventListener("close", resolve, {once:true}));
      document.querySelector("#close-foundation-topic").click();
      document.querySelector('[data-foundation-topic="purpose"]').click();
      await closed;
      return document.querySelector("[data-foundation-topic].selected")?.dataset.foundationTopic;
    });
    assert.equal(nextTopic, "purpose", "The previous close event must leave the reopened topic selected");
    // Escape follows the same path as the Close button. Move focus again before the queued
    // close event even when the browser had returned it to this control between two topics.
    const focusAfterReopen = await page.evaluate(async () => {
      const dialog = document.querySelector("#foundation-dialog");
      const closed = new Promise(resolve => dialog.addEventListener("close", resolve, {once:true}));
      dialog.requestClose();
      document.querySelector('[data-foundation-topic="name"]').focus();
      await closed;
      return document.activeElement.dataset.foundationTopic;
    });
    assert.equal(focusAfterReopen, "name", "A later keyboard move can select the original opener again");
    await topic(page, "name").focus();
    await page.keyboard.press("Enter");
    await checkDialog(page, "Name and other names", nameAnswer);
    await page.keyboard.press("Tab");
    assert.equal(await topic(page, "purpose").evaluate(button => button === document.activeElement), true);
    await page.keyboard.press("Space");
    await checkDialog(page, "Purpose", purposeAnswer);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
}

async function main() {
  const executablePath = process.env.COLLECTOR_BROWSER;
  assert(executablePath && fs.existsSync(executablePath), "Set COLLECTOR_BROWSER to an installed Edge or Chrome executable.");
  const child = spawn(process.env.VOICE_INTERVIEWER_PYTHON || "python",
    ["-I","-B",path.join(__dirname,"serve.py")], {stdio:["ignore","pipe","inherit"], windowsHide:true});
  let browser, url;
  try {
    const [buffer] = await Promise.race([once(child.stdout, "data"),
      once(child, "exit").then(() => {throw Error("Synthetic server exited before startup");})]);
    url = buffer.toString().trim();
    assert.match(url, /^http:\/\/127\.0\.0\.1:\d+\/$/);
    browser = await chromium.launch({headless:true, executablePath,
      args:["--disable-background-networking","--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"]});
    for (const width of [1280,390]) await exercise(browser, url, width);
    console.log("PASS Notes pointer and keyboard selection in the desktop rail and mobile sheet");
  } finally {
    if (browser) await browser.close();
    if (url) {
      try {
        const config = await (await fetch(url+"api/config")).json();
        const shutdown = await fetch(url+"api/shutdown", {method:"POST",
          headers:{"X-CSRF-Token":config.csrf_token, Origin:new URL(url).origin}, body:"{}"});
        if (!shutdown.ok) child.kill();
      } catch { child.kill(); }
    } else child.kill();
  }
}
main().catch(error => {console.error(error);process.exitCode = 1;});
