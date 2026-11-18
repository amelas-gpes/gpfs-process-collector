"use strict";
// Optional browser check of the map lanes: three typed answers in the real page against a synthetic
// provider. The Workflow line goes from "Updating the map" to "check pending" to the checked map, and
// the diagram shows the reported steps between an implied start and end. Not part of tests/run_all.cjs:
// it needs Playwright and a browser. Supply an existing interpreter with VOICE_INTERVIEWER_PYTHON and,
// where Playwright cannot find its own browser, COLLECTOR_BROWSER and COLLECTOR_PLAYWRIGHT.
const assert=require("node:assert/strict"),path=require("node:path");
const {spawn}=require("node:child_process"),{once}=require("node:events");
const {chromium}=require(process.env.COLLECTOR_PLAYWRIGHT||"playwright");

(async()=>{
 const child=spawn(process.env.VOICE_INTERVIEWER_PYTHON||"python",["-I","-B",path.join(__dirname,"typed_map_server.py"),"0.4","3"],{stdio:["ignore","pipe","inherit"],windowsHide:true});
 const url=(await Promise.race([once(child.stdout,"data"),once(child,"exit").then(()=>{throw Error("Test server exited before startup");})]))[0].toString().trim();
 assert.match(url,/^http:\/\/127\.0\.0\.1:\d+\/$/);
 const browser=await chromium.launch({headless:true,...(process.env.COLLECTOR_BROWSER?{executablePath:process.env.COLLECTOR_BROWSER}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1500,height:900}}),errors=[];
  page.on("pageerror",error=>errors.push(String(error)));
  await page.goto(url);await page.waitForLoadState("networkidle");
  await page.getByRole("button",{name:/Type instead/}).click();
  const box=page.locator("#answer-text");await box.waitFor({state:"visible"});
  const line=()=>page.evaluate(()=>document.getElementById("workflow-status")?.textContent||"");
  const watch=async seconds=>{const seen=[],end=Date.now()+seconds*1000;while(Date.now()<end){const text=await line();if(seen.at(-1)!==text)seen.push(text);await page.waitForTimeout(80);}return seen;};
  const say=async text=>{await page.waitForFunction(()=>!document.getElementById("answer-text").disabled);await box.fill(text);await page.locator("#send-answer").click();};
  await say("An analyst logs each invoice in the AP register when it arrives in the shared mailbox.");
  const first=await watch(6);
  await say("Then the manager approves it in the portal.");
  const second=await watch(1.8);
  await say("Treasury releases payment on Thursday.");
  const third=await watch(10);
  const drawn="Updated through the latest answer · check pending",checked="Updated through the latest answer";
  assert.deepEqual(first.slice(-2),[drawn,checked],"The first map is shown as drawn, then as checked: "+JSON.stringify(first));
  assert(second.includes(drawn),"The second map is on screen before its check has finished: "+JSON.stringify(second));
  assert.equal(third.at(-1),checked,JSON.stringify(third));
  await page.getByText("Workflow",{exact:true}).first().click();await page.waitForSelector("[data-step-id]");await page.waitForTimeout(800);
  const diagram=await page.evaluate(()=>({steps:document.querySelectorAll("[data-step-id]").length,
   markers:[...document.querySelectorAll("[data-implied]")].map(node=>node.getAttribute("data-implied")).sort().join(",")}));
  assert.deepEqual(diagram,{steps:3,markers:"end,start"});
  await page.locator('[data-tab="review"]').click();
  const responsePromise=page.waitForResponse(response=>new URL(response.url()).pathname==="/api/draft");
  await page.locator("#review-create-draft").click();
  const response=await responsePromise;
  const result=await response.json();
  assert.equal(response.status(),200,JSON.stringify(result));
  const checkedMap=response.request().postDataJSON().previous_capture.workflow;
  const identity=step=>[step.id,step.title,step.evidence_turns];
  assert.deepEqual(result.draft.steps.map(identity),checkedMap.steps.map(identity));
  assert.deepEqual(result.draft.connections,checkedMap.connections);
  await page.locator("#review-heading").waitFor({state:"visible"});
  await page.locator("#review-tab-map").click();
  await page.locator("#process-map [data-step-id]").nth(2).waitFor();
  await page.waitForFunction(()=>document.getElementById("process-map").getAttribute("aria-busy")==="false");
  assert.equal(await page.locator("#map-gaps").isVisible(),false,"A connected draft has no empty warning after its diagram finishes drawing.");
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({checks_passed:10,first,second,third,diagram,draft_steps:result.draft.steps.length,provider_calls:0,real_browser:true}));
 }finally{await browser.close();child.kill();}
})().catch(error=>{console.error(error);process.exitCode=1;});
