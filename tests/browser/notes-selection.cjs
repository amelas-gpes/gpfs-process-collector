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
      "  window.notesFixture = {state, renderCoverage, renderTranscript, rememberDiscussion, rememberCoverageCheckpoint, clearState, sessionObject};\n  init();\n})();");
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
    const meter=page.getByRole("progressbar",{name:"Topic coverage",exact:true});
    const arc=page.locator("#coverage-progress");
    assert.equal(await meter.getAttribute("aria-valuenow"), "0");
    assert.equal(await arc.evaluate(node=>parseFloat(getComputedStyle(node).strokeDashoffset)), 100);
    const animateRing=width===1280;
    if (animateRing) await page.emulateMedia({reducedMotion:"no-preference"});
    await clickAcrossUpdate(page, async () => {
      const swept=await page.evaluate(async ({nameAnswer, purposeAnswer}) => {
        const {state, rememberDiscussion, renderCoverage} = window.notesFixture;
        state.turns.push({id:"t002",role:"user",text:purposeAnswer});
        state.memo_findings = [
          {key:"name",status:"unknown",answer:nameAnswer,evidence_turns:[]},
          {key:"purpose",status:"captured",answer:purposeAnswer,evidence_turns:["t002"]}
        ];
        state.advisory.purpose = {answer:purposeAnswer,complete:false,gaps:["Clarify the result."],next_question:""};
        rememberDiscussion({}, {turns:state.turns}, []);
        renderCoverage();
        const transition=document.getElementById("coverage-progress").getAnimations().find(item=>item.transitionProperty==="stroke-dashoffset");
        if (transition) await transition.finished;
        return Boolean(transition);
      }, {nameAnswer, purposeAnswer});
      assert.equal(swept,animateRing,"The ring sweeps only when motion is enabled");
      assert.match(await page.locator("#analysis-through").textContent(), /Notes include all 1 saved answer/);
      assert.equal(await page.locator("#coverage-count").innerText(), "6%");
      assert.equal(await meter.getAttribute("aria-valuetext"), "1 of 16 topics captured (6%)");
      assert.equal(await arc.evaluate(node=>parseFloat(getComputedStyle(node).strokeDashoffset)), 93.75);
      if (animateRing) await page.emulateMedia({reducedMotion:"reduce"});
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
    await checkDialog(page, "Name and scope", nameAnswer);
    await page.keyboard.press("Tab");
    assert.equal(await topic(page, "purpose").evaluate(button => button === document.activeElement), true);
    await page.keyboard.press("Space");
    await checkDialog(page, "Purpose", purposeAnswer);
    await page.evaluate(()=>{
      const {state,renderTranscript,rememberCoverageCheckpoint,clearState}=window.notesFixture;
      clearState({process_name:"Method B release",process_owner:"",objective:"Document current practice",background:""});
      state.started=true;
      state.turns=[{id:"t002",role:"user",text:"Method B stays on hold until the model owner confirms the release test."}];
      state.coverageVerified=true;
      state.memo_findings.push({key:"completion",status:"partial",answer:"The held route stops before release.",evidence_turns:["t002"]});
      rememberCoverageCheckpoint(undefined,undefined,undefined,{topics:[{key:"completion",complete:false,ready_for_owner_review:true,gaps:[],next_question:"",
        owner_followups:[{dimension:"observable_finish",kind:"operational_hold",gap:"The release test for Method B needs approval.",scope:"Method B only",interim_action:"Keep the transaction on hold.",resolver:"The current model owner",evidence_turns:["t002"]}]}]});
      renderTranscript();
    });
    if(await page.locator("#open-memo").isVisible())await page.locator("#open-memo").click();
    const finish=topic(page,"completion");
    assert.equal(await finish.locator(".coverage-state").innerText(),"Owner follow-up");
    await finish.focus();await page.keyboard.press("Enter");
    const gaps=page.locator("#foundation-topic-gaps");
    await gaps.getByRole("heading",{name:"For the process owner"}).waitFor({state:"visible",timeout:3000});
    assert.match(await gaps.innerText(),/Method B only/);
    assert.match(await gaps.innerText(),/Keep the transaction on hold/);
    assert.match(await gaps.innerText(),/The current model owner/);
    assert.ok(await gaps.evaluate(el=>el.scrollWidth<=el.clientWidth),"Gap detail fits within the panel");
    await page.keyboard.press("Escape");
    assert.equal(await finish.evaluate(button=>button===document.activeElement),true);
    const saved=await page.evaluate(()=>window.notesFixture.sessionObject());
    assert.equal(saved.owner_followups.length,1);
    const restored=await browser.newPage({viewport:{width,height:900},reducedMotion:"reduce"});
    try{
      restored.on("pageerror",error=>errors.push(error.message));
      const aiRequests=[];
      restored.on("request",request=>{
        const route=new URL(request.url()).pathname;
        if(request.method()==="POST"&&/^\/api\/(agent-team|concurrent|interview|workflow|draft|voice-session)(\/|$)/.test(route))aiRequests.push(route);
      });
      await restored.goto(url);
      await restored.locator("#session-file").setInputFiles({name:"hold.json",mimeType:"application/json",buffer:Buffer.from(JSON.stringify(saved))});
      await restored.waitForFunction(()=>document.querySelector("#process-name").value==="Method B release");
      if(await restored.locator("#open-memo").isVisible())await restored.locator("#open-memo").click();
      const restoredTopic=topic(restored,"completion");
      await restoredTopic.focus();await restored.keyboard.press("Enter");
      const restoredGaps=restored.locator("#foundation-topic-gaps");
      assert.equal(await restoredGaps.getByRole("heading",{name:"Saved owner follow-up · recheck pending"}).isVisible(),true);
      assert.match(await restoredGaps.innerText(),/Keep the transaction on hold/);
      assert.notEqual(await restored.locator("#foundation-topic-status").innerText(),"Owner follow-up");
      await restored.keyboard.press("Escape");
      await topic(restored,"risk").click();
      assert.equal(await restoredGaps.getByRole("heading",{name:"What this topic covers"}).isVisible(),true);
      assert.doesNotMatch(await restoredGaps.innerText(),/current model owner/);
      await restored.keyboard.press("Escape");
      if(await restored.locator("#memo-sheet").isVisible())await restored.locator("#close-memo").click();
      await restored.locator("#open-context").click();
      await restored.locator("#process-owner").fill("Newly assigned owner");
      await restored.locator("#close-interview-settings").click();
      if(await restored.locator("#open-memo").isVisible())await restored.locator("#open-memo").click();
      await restoredTopic.click();
      assert.doesNotMatch(await restoredGaps.innerText(),/current model owner|Saved owner follow-up/);
      assert.deepEqual(aiRequests,[],"Opening the saved session and inspecting topics use existing evidence locally");
    }finally{await restored.close();}
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
