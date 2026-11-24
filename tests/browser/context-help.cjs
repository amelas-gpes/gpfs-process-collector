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
    browser = await chromium.launch({executablePath:process.env.COLLECTOR_BROWSER, headless:true,
      args:["--disable-background-networking","--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"]});
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

    async function scrollReportTo(number) {
      const id = `report-section-${number}`;
      await page.locator(`#${id}`).evaluate(section => {
        const scroller = document.getElementById("review-view");
        const margin = parseFloat(getComputedStyle(section).scrollMarginTop);
        scroller.scrollTop += section.getBoundingClientRect().top - scroller.getBoundingClientRect().top - margin + 8;
      });
      await page.locator(`#report-section-links a[href="#${id}"][aria-current="location"]`).waitFor({state:"attached"});
    }

    await page.keyboard.press("Tab");
    await expectTip("jump to the workspace");
    await page.keyboard.press("Escape");
    await page.locator("#welcome-example").click();
    await page.locator('[data-tab="interview"]').click();
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
    const reportLinks = page.locator("#report-section-links a");
    const variations = reportLinks.filter({hasText:"7. Variations and boundaries"});
    await variations.click();
    await page.mouse.move(800, 135);
    assert.equal(await variations.getAttribute("aria-current"), "location");
    assert.equal(await variations.evaluate(link => link.matches(":hover, :focus")), false);
    const railAccent = link => link.evaluate(node => getComputedStyle(node).borderLeftColor);
    assert.notEqual(await railAccent(variations), await railAccent(reportLinks.first()));
    await scrollReportTo(8);
    assert.equal(await variations.getAttribute("aria-current"), null);
    await scrollReportTo(7);
    await page.locator("#review-view").evaluate(scroller => {scroller.scrollTop = scroller.scrollHeight;});
    await page.locator('#report-section-links a[aria-current="location"]').filter({hasText:"Classification and connected work"}).waitFor();
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
    await page.locator("#review-tab-report").click();
    const contents = page.locator("#report-contents");
    await contents.selectOption("report-section-7");
    assert.equal(await contents.inputValue(), "report-section-7");
    await scrollReportTo(8);
    assert.equal(await contents.inputValue(), "report-section-8");
    await page.locator("#session-menu-toggle").click();
    assert.equal(await page.locator("#save-copy-description").count(), 0);
    await page.locator("#open-interview-settings").focus();
    await page.keyboard.press("Tab");
    await expectTip("Save a copy of this interview");
    await page.keyboard.press("Escape");
    await tip.waitFor({state:"detached"});
    assert.deepEqual(errors, []);
    console.log("Context help and report navigation passed on desktop and mobile.");
  } finally {
    try { await browser?.close(); } finally { server.kill(); }
  }
}
run().catch(error => { console.error(error); process.exitCode = 1; });
