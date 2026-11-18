"use strict";
// Exercise the real controls and tooltip lifecycle with the isolated synthetic browser server.
const assert = require("node:assert/strict");
const path = require("node:path");
const {once} = require("node:events");
const {spawn} = require("node:child_process");
const {chromium} = require(process.env.COLLECTOR_PLAYWRIGHT || "playwright");

async function run() {
  const server = spawn(process.env.VOICE_INTERVIEWER_PYTHON || "python",
    ["-I", "-B", path.join(__dirname, "serve.py")], {stdio:["ignore", "pipe", "inherit"]});
  let browser;
  try {
    const [output] = await Promise.race([once(server.stdout, "data"), once(server, "exit").then(() => {
      throw Error("The synthetic server exited before startup.");
    })]);
    const url = output.toString().trim();
    assert.match(url, /^http:\/\/127\.0\.0\.1:\d+\/$/);
    browser = await chromium.launch({executablePath:process.env.COLLECTOR_BROWSER, headless:true});
    const page = await browser.newPage({viewport:{width:1280, height:850}});
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/*", route => new URL(route.request().url()).origin === new URL(url).origin ? route.continue() : route.abort());
    await page.goto(url);
    const tip = page.getByRole("tooltip");

    async function expectTip(fragment) {
      await tip.filter({hasText:fragment}).waitFor({state:"visible", timeout:5000});
      const box = await tip.boundingBox(), view = page.viewportSize();
      assert(box.x >= 0 && box.y >= 0 && box.x + box.width <= view.width && box.y + box.height <= view.height);
    }

    await page.keyboard.press("Tab");
    await expectTip("jump to the workspace");
    await page.keyboard.press("Escape");
    await page.locator("#conversation-tab-workflow").hover();
    await expectTip("handoffs captured");
    await tip.hover();
    await page.waitForTimeout(200);
    assert(await tip.isVisible(), "The hint stays visible while the pointer reads it.");
    await page.keyboard.press("Escape");
    await tip.waitFor({state:"detached"});

    const start = page.locator('[data-tab="interview"]'), review = page.locator('[data-tab="review"]');
    await start.focus();
    await page.keyboard.press("Tab");
    await expectTip("edit the process draft");
    assert.equal(await review.getAttribute("aria-describedby"), "collector-context-help");
    await page.keyboard.press("Escape");
    assert(await review.evaluate(node => node === document.activeElement && !node.hasAttribute("aria-describedby")));

    await page.locator("#open-context").click();
    const goal = page.locator("#objective"), before = await goal.getAttribute("aria-describedby");
    await goal.hover();
    await expectTip("what this interview should establish");
    assert(await tip.evaluate(node => Boolean(node.closest("dialog[open]"))));
    assert.equal(await goal.getAttribute("aria-describedby"), before + " collector-context-help");
    await page.keyboard.press("Escape");
    assert.equal(await goal.getAttribute("aria-describedby"), before);
    assert(await page.locator("#interview-settings").isVisible());
    await page.keyboard.press("Escape");
    await page.locator("#interview-settings").waitFor({state:"hidden"});

    await page.route("**/api/trace/logs?*", route => route.fulfill({json:{
      events:[{type:"fixture.review", timestamp:"2026-01-01T00:00:00Z"}], status:{enabled:false}
    }}));
    await page.locator("#open-context").click();
    await page.locator("#settings-tab-logs").click();
    await page.locator(".log-entry summary").first().hover();
    await expectTip("event to inspect its recorded details");
    await page.locator("#close-interview-settings").click();

    await page.locator("#welcome-example").click();
    await page.locator('[data-tab="interview"]').click();
    await page.locator("#conversation-tab-transcript").click();
    await page.locator("#export-transcript").click();
    for (const [format, fragment] of [["markdown", "as a Markdown document"], ["json", "as structured JSON data"]]) {
      await page.locator(`[data-transcript-format="${format}"]`).hover();
      await expectTip(fragment);
    }
    await page.locator('[data-tab="review"]').click();
    await page.locator("#review-tab-report").click();
    await page.locator("#report-section-links a").first().hover();
    await expectTip("this section of the process report");
    await page.locator("#review-tab-memo").click();
    const finding = page.locator(".memo-finding-summary").first();
    await finding.hover();
    await expectTip("wording, status and cited evidence");
    await finding.click();
    await page.locator(".memo-finding[open] textarea").first().hover();
    await expectTip("finding that appears in the draft");

    await page.locator("#review-tab-procedure").click();
    const field = page.locator(".step-properties select").first();
    await field.hover();
    await expectTip("workflow symbol");
    await page.locator("#review-tab-map").click();
    await tip.waitFor({state:"detached"});
    await page.locator("#map-tools-toggle").click();
    await page.locator("#map-fit").hover();
    await expectTip("Scale and center");
    assert(await tip.evaluate(node => Boolean(node.closest("#map-tools"))));

    await page.locator("#map-tools-toggle").click();
    await page.setViewportSize({width:390, height:844});
    await page.locator("#session-menu-toggle").click();
    await page.locator("#open-component-library").click();
    const tile = page.locator(".cl-tile").first();
    await tile.hover();
    await expectTip(await tile.getAttribute("aria-description"));
    await page.keyboard.press("Escape");
    await tip.waitFor({state:"detached"});
    assert(await page.locator(".cl-dialog").isVisible());
    assert.deepEqual(errors, []);
    console.log("Context help passed across interview, review, map tools, settings and the mobile component library.");
  } finally {
    try { await browser?.close(); } finally { server.kill(); }
  }
}
run().catch(error => { console.error(error); process.exitCode = 1; });
