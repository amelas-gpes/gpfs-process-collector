"use strict";
// Real browser startup, with a disposable server and a stub at the microphone permission boundary.
const assert = require("node:assert/strict");
const path = require("node:path");
const {once} = require("node:events");
const {spawn} = require("node:child_process");
const {chromium} = require(process.env.COLLECTOR_PLAYWRIGHT || "playwright");

async function welcome(browser, url, width = 1280) {
  const page = await browser.newPage({viewport:{width, height:840}, reducedMotion:"reduce"});
  await page.route("**/*", route => new URL(route.request().url()).origin === new URL(url).origin
    ? route.continue() : route.abort());
  await page.addInitScript(() => {
    window.micRequests = [];
    navigator.mediaDevices.getUserMedia = async () => {
      window.micRequests.push(document.getElementById("transcript").textContent);
      throw new DOMException("Synthetic microphone denial", "NotAllowedError");
    };
  });
  await page.goto(url);
  await page.waitForFunction(() => document.getElementById("welcome-upload")?.disabled === false);
  return page;
}

async function openChoice(page) {
  await page.locator("#start-live").click();
  const dialog = page.getByRole("dialog", {name:"Save time on your interview"});
  await dialog.waitFor();
  assert.equal(await dialog.evaluate(node => node.matches(":modal")), true);
  const description = await page.locator("#voice-start-description").innerText();
  assert.match(description, /skip|avoid|fewer/i);
  assert.match(description, /question/i);
  assert.deepEqual(await page.evaluate(() => window.micRequests), []);
  return dialog;
}

async function filesFromChoice(page) {
  const dialog = await openChoice(page);
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser"), dialog.getByRole("button", {name:"I have documents"}).click()
  ]);
  assert(chooser.isMultiple());
  return chooser;
}

async function skipFiles(browser, url) {
  const page = await welcome(browser, url, 390);
  const dialog = await openChoice(page);
  for (const name of ["Go to interview", "I have documents"]) {
    const box = await dialog.getByRole("button", {name}).boundingBox();
    assert(box && box.x >= 0 && box.x + box.width <= 390, name + " fits on mobile");
  }
  await page.keyboard.press("Escape");
  await dialog.waitFor({state:"hidden"});
  assert(await page.locator("#start-live").evaluate(node => node === document.activeElement));
  assert.deepEqual(await page.evaluate(() => window.micRequests), []);
  await (await openChoice(page)).getByRole("button", {name:"Go to interview"}).click();
  await page.waitForFunction(() => window.micRequests.length === 1);
  await page.locator("#start-live").click();
  await page.waitForFunction(() => window.micRequests.length === 2);
  assert.equal(await dialog.isVisible(), false, "Retrying an existing interview skips the welcome choice.");
  await page.close();
}

async function rejectFiles(browser, url, files) {
  const page = await welcome(browser, url);
  let uploads = 0;
  page.on("request", request => {if (request.url().endsWith("/api/documents/upload")) uploads++;});
  const chooser = await filesFromChoice(page);
  await chooser.setFiles(files);
  assert(await page.locator("#welcome-upload").isVisible());
  assert.deepEqual(await page.evaluate(() => window.micRequests), []);
  assert.equal(uploads, 0);
  // A canceled or rejected picker must also leave no deferred voice request behind.
  if (await page.locator("#voice-start-dialog").isVisible()) await page.keyboard.press("Escape");
  await page.locator("#type-instead").click();
  await page.locator("#answer-text").waitFor();
  assert.deepEqual(await page.evaluate(() => window.micRequests), []);
  await page.close();
}

async function reviewFile(browser, url, afterUpload) {
  const page = await welcome(browser, url);
  const isFollowup = request => request.url().endsWith("/api/conversation/turn") &&
    request.postDataJSON().action === "document_followup";
  let release;
  const hold = new Promise(resolve => {release = resolve;});
  await page.route("**/api/conversation/turn", async route => {
    if (isFollowup(route.request())) {
      await hold;
      if (afterUpload === "continue") return route.fulfill({status:400, json:{error:"Synthetic review failure"}});
    }
    await route.continue();
  });
  try {
    const chooser = await filesFromChoice(page);
    const [receipt] = await Promise.all([
      page.waitForResponse(response => response.url().endsWith("/api/documents/upload")),
      page.waitForRequest(isFollowup),
      chooser.setFiles({name:"invoice-intake.csv", mimeType:"text/csv",
        buffer:Buffer.from("Role,Activity\nRegistrar,Log the invoice in the purchase order register.")})
    ]);
    assert(receipt.ok());
    const {document} = await receipt.json();
    assert(await page.locator("#document-intake-panel").isVisible());
    assert.deepEqual(await page.evaluate(() => window.micRequests), [], "Review completes before voice starts.");
    if (afterUpload === "leave") await page.locator('[data-tab="review"]').click();
    const ready = page.waitForResponse(response => isFollowup(response.request()));
    const analysis = afterUpload === "wait" ? page.waitForRequest(request =>
      /\/api\/conversation\/(?:status|cancel)$/.test(request.url())) : null;
    release();
    const response = await ready;
    if (afterUpload === "continue") {
      assert.equal(response.status(), 400);
      const proceed = page.getByRole("button", {name:"Continue without waiting"});
      await proceed.waitFor();
      assert.deepEqual(await page.evaluate(() => window.micRequests), [], "A failed review never opens the mic.");
      await proceed.click();
      await page.waitForFunction(() => window.micRequests.length === 1);
      return;
    }
    assert(response.ok());
    const result = await response.json();
    assert(result.document_reading.documents.some(file => file.id === document.id && file.included_chunks > 0));
    await page.waitForFunction(question => document.getElementById("transcript").textContent.includes(question), result.question);
    if (afterUpload === "leave") {
      await page.locator('[data-tab="interview"]').click();
      assert.deepEqual(await page.evaluate(() => window.micRequests), [], "Leaving cancels the deferred start.");
    } else {
      await page.waitForFunction(() => window.micRequests.length > 0);
      const requests = await page.evaluate(() => window.micRequests);
      assert.equal(requests.length, 1);
      assert(requests[0].includes(result.question), "Voice starts with the file-based question already in the interview.");
      const next = await analysis;
      assert.equal(next.postDataJSON().conversation_token, result.conversation_token);
      assert(next.url().endsWith("/status"), "Voice keeps polling the file analysis that supplied its first question.");
    }
  } finally {
    release();
    await page.close();
  }
}

async function main() {
  const child = spawn(process.env.VOICE_INTERVIEWER_PYTHON || "python",
    ["-I", "-B", path.join(__dirname, "serve.py")], {stdio:["ignore", "pipe", "inherit"], windowsHide:true});
  let browser;
  try {
    const [output] = await Promise.race([once(child.stdout, "data"), once(child, "exit").then(() => {
      throw Error("Synthetic server exited before startup.");
    })]);
    const url = output.toString().trim();
    assert.match(url, /^http:\/\/127\.0\.0\.1:\d+\/$/);
    browser = await chromium.launch({executablePath:process.env.COLLECTOR_BROWSER, headless:true});
    await skipFiles(browser, url);
    await rejectFiles(browser, url, []);
    await rejectFiles(browser, url, {name:"unsupported.bin", mimeType:"application/octet-stream", buffer:Buffer.from("invalid")});
    for (const action of ["wait", "leave", "continue"]) await reviewFile(browser, url, action);
    console.log("Voice startup choices, picker cancellation, rejected files, document readiness and navigation passed.");
  } finally {
    try { await browser?.close(); } finally { child.kill(); }
  }
}

main().catch(error => {console.error(error); process.exitCode = 1;});
