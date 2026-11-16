"use strict";
const assert=require("node:assert/strict");
const {open}=require("./fixtures/app_page.cjs");

async function main(){
  const fullNotice="Synthetic notice about this interview's data.";
  const page=await open({config:{data_notice:fullNotice}});
  const {document}=page,settings=page.$("interview-settings");
  const dock=page.$("conversation-dock"),welcome=page.$("welcome").closest("main");
  assert.equal(page.state.started,false);
  for(const id of ["start-live","type-instead"])assert(page.$(id).visible&&dock.contains(page.$(id)));
  for(const id of ["data-brief","open-data-notice","add-context","welcome-guide"])assert.equal(document.getElementById(id),null,id+" was removed");
  assert(!welcome.textContent.includes("How your data is handled"));
  assert(!welcome.textContent.includes("How this works"));
  const menu=page.$("session-menu-toggle");
  menu.click();page.$("open-interview-settings").click();
  assert(settings.open);
  const guide=page.$("help-guide"),summary=guide.querySelector("summary");
  assert.equal(guide.tagName,"DETAILS");
  assert(settings.contains(guide));
  assert.equal(summary.textContent.trim(),"How this works");
  assert.equal(guide.getAttribute("name"),"settings-section");
  summary.focus();assert.equal(document.activeElement,summary);
  const disclosure=page.$("data-details"),notice=page.$("data-notice");
  assert(settings.contains(disclosure)&&disclosure.contains(notice));
  assert.match(disclosure.querySelector("summary").textContent,/Data handling/);
  assert.equal(notice.textContent,fullNotice);
  page.$("close-interview-settings").click();
  assert.equal(document.activeElement,menu);
  assert.equal(page.state.started,false);
  assert.equal(page.requests.filter(request=>request.url.startsWith("/api/interview")||request.url.startsWith("/api/agent-team/")).length,0);
  console.log("Welcome actions, Settings guide and data handling passed.");
}

main().catch(error=>{console.error(error);process.exitCode=1;});
