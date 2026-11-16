"use strict";
// Before the microphone opens or a first answer is sent, the start screen must say where speech,
// text and files go, with a way to the full notice. The real web/app.js runs against the real
// web/index.html in the page of tests/fixtures/interview_form_page.cjs. No browser, audio device, provider,
// package or network.
const assert=require("node:assert/strict");
const {openPage}=require("./fixtures/interview_form_page.cjs");
const FULL="Synthetic full notice: what is sent, what is stored on this computer, and what is not saved.";
let checks=0;
async function check(name,fn){try{await fn();checks++;}catch(error){error.message=name+": "+error.message;throw error;}}
async function open(){
 const posts=[];
 const page=await openPage({expose:["state","conversationUI","selectConversationView","clearState","setInterviewSettings"],config:{data_notice:FULL},
  fetch:async url=>{posts.push(url);if(url==="/api/interview")return {ok:true,status:200,json:async()=>({question:"What starts the work?"})};throw new Error("Unexpected request: "+url);}});
 return {page,posts,brief:page.$("data-brief"),link:page.$("open-data-notice")};
}

(async()=>{
 await check("the start screen says where speech, text and files go, directly under the start buttons",async()=>{
  const {page,posts,brief,link}=await open();
  assert.equal(page.app.state.started,false);assert.equal(posts.length,0,"Nothing has been sent yet");
  assert.equal(brief.shown,true);
  const dock=page.$("conversation-dock"),order=page.walk(dock);
  assert.equal(dock.contains(brief),true,"It travels with the start buttons");
  for(const id of ["start-live","type-instead"]){
   assert.equal(page.$(id).shown,true);
   assert.ok(order.indexOf(brief)>order.indexOf(page.$(id)),"The line comes after "+id);
  }
  assert.equal(brief.previousElementSibling.contains(page.$("start-live")),true,"Nothing sits between the buttons and the line");
  const said=brief.textContent;
  assert.match(said,/sent to OpenAI/);
  for(const what of [/voice/i,/typed answers/i,/files/i])assert.match(said,what);
  assert.match(said,/not saved automatically/);
  assert.equal(link.tagName,"BUTTON");assert.equal(link.getAttribute("type"),"button");
  assert.equal(link.textContent,"How your data is handled");assert.equal(brief.contains(link),true);
  assert.equal(page.$("interview-settings").open,false,"The full notice is still one click away, not in front");
 });

 await check("the same line is under the reply box when the first answer is typed from the Transcript view",async()=>{
  const {page,brief}=await open();
  page.app.selectConversationView("transcript");
  assert.equal(page.$("transcript-dock-host").contains(brief),true);
  assert.equal(page.$("answer-text").shown,true);assert.equal(brief.shown,true);
 });

 await check("the link opens the full notice and closing it returns to the link",async()=>{
  const {page,brief,link}=await open();
  link.focus();link.click();
  const settings=page.$("interview-settings"),notice=page.$("data-notice");
  assert.equal(settings.open,true);assert.equal(page.$("data-details").open,true,"The Data handling section is opened");
  assert.equal(page.$("data-details").contains(notice),true);
  assert.equal(notice.textContent,FULL);assert.equal(notice.shown,true);
  assert.equal(page.document.activeElement,notice,"Focus lands on the full text");
  page.$("close-interview-settings").click();
  assert.equal(settings.open,false);assert.equal(page.document.activeElement,link);
  assert.equal(brief.shown,true);
  // Settings opened from More options still returns there.
  page.$("session-menu-toggle").click();page.$("open-interview-settings").click();
  assert.equal(settings.open,true);
  page.$("close-interview-settings").click();
  assert.equal(page.document.activeElement,page.$("session-menu-toggle"));
 });

 await check("the line leaves once the interview has started and returns for a new one",async()=>{
  const {page,posts,brief,link}=await open();
  page.$("type-instead").click();await page.settle();
  assert.equal(page.app.state.started,true);assert.equal(posts.length,1);
  assert.equal(brief.hidden,true);assert.equal(link.shown,false);
  page.app.clearState();await page.settle();
  assert.equal(page.app.state.started,false);assert.equal(brief.shown,true);
 });

 console.log(JSON.stringify({checks_passed:checks,provider_calls:0,network_calls:0}));
})().catch(error=>{console.error(error);process.exitCode=1;});
