"use strict";
// More formats on Review is a menu beside Download report: its choices form one floating group, and a
// choice, Escape or a click elsewhere closes it. Only the browser's own summary toggle is a stand-in.
const assert=require("node:assert/strict");
const {open}=require("./fixtures/app_page.cjs");

async function main(){
  const page=await open();
  const menu=page.$("report-more-exports"),summary=menu.querySelector("summary"),group=menu.querySelector(".report-export-menu");
  assert.equal(group.getAttribute("role"),"group");
  assert.equal(group.getAttribute("aria-label"),"More formats");
  for(const id of ["download-bpmn","download-step-csv","download-png","print-report"])assert(group.contains(page.$(id)),id+" is one of the menu's choices");
  // Review is not on screen in a new interview, so each event is delivered as the browser would deliver it.
  menu.open=true;page.$("download-step-csv").dispatchEvent({type:"click",bubbles:true});
  assert.equal(menu.open,false,"A choice closes the menu");
  menu.open=true;summary.dispatchEvent({type:"click",bubbles:true});
  assert.equal(menu.open,true,"Opening and closing from the button is left to the browser");
  page.$("answer-text").dispatchEvent({type:"click",bubbles:true});
  assert.equal(menu.open,false,"A click elsewhere closes the menu");
  menu.open=true;
  const escape={type:"keydown",key:"Escape",bubbles:true,stopPropagation(){this.stopped=true;}};
  group.dispatchEvent(escape);
  assert.equal(menu.open,false,"Escape closes the menu");
  assert.equal(escape.stopped,true,"Escape is handled by the menu, not by the page behind it");
  menu.open=false;group.dispatchEvent({type:"keydown",key:"Escape",bubbles:true,stopPropagation(){this.stopped=true;}});
  assert.equal(page.requests.filter(request=>request.url!=="/api/config").length,0,"Opening and closing the menu sends nothing");
  console.log("More formats: grouped choices, close on a choice, on a click elsewhere and on Escape passed.");
}
main().catch(error=>{console.error(error);process.exitCode=1;});
