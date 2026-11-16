"use strict";
// What assistive technology is told during a typed or dictated interview: that the interviewer is
// working, and the next question when it arrives. The real web/app.js runs against the real
// web/index.html in the page of tests/fixtures/interview_form_page.cjs; the interviewer's replies are a local
// stand-in for /api/interview. No browser, audio device, provider, package or network.
const assert=require("node:assert/strict");
const {openPage}=require("./fixtures/interview_form_page.cjs");
const EXPOSE=["state","conversationUI","applyInterview","updateControls","setBusy","showProvisionalQuestion","onDocumentEvent","selectConversationView"];
const THINKING="Thinking of the next question…";
const VOICE={name:"Test voice",lang:"en-US",voiceURI:"synthetic-voice",localService:true};
let checks=0;

// Opens the page with an interviewer whose replies the test releases one at a time.
async function open(options={}){
 const pending=[];
 const page=await openPage({expose:EXPOSE,...options,fetch:async url=>{
  assert.equal(url,"/api/interview","Only the interviewer is asked");
  return new Promise(resolve=>pending.push(reply=>resolve({ok:true,status:200,json:async()=>reply})));
 }});
 const status=page.$("live-status");
 return {page,status,said:()=>status.textContent,
  async reply(result){assert.equal(pending.length,1,"One interviewer request is waiting");pending.shift()(result);await page.settle();},
  async typeInstead(){page.$("type-instead").focus();page.$("type-instead").click();await page.settle();},
  async send(answer){page.$("answer-text").value=answer;page.fire(page.$("answer-text"),"input");page.fire(page.$("answer-form"),"submit");await page.settle();}};
}
async function check(name,fn){try{await fn();checks++;}catch(error){error.message=name+": "+error.message;throw error;}}

(async()=>{
 await check("the shipped regions: one polite status line, and the transcript itself stays quiet",async()=>{
  const {page,status}=await open();
  assert.equal(status.getAttribute("role"),"status");assert.equal(status.getAttribute("aria-live"),"polite");
  assert.equal(status.classList.contains("sr-only"),true,"The status line is for assistive technology only");
  // Live voice reads every question itself; a live transcript or caption would say each one twice.
  assert.equal(page.$("transcript").getAttribute("aria-live"),"off");
  assert.equal(page.$("current-question").getAttribute("aria-live"),"off");
  assert.equal(page.$("thinking").contains(status),false);
 });

 await check("Type instead: the wait is said, then the opening question, and focus returns to the reply box",async()=>{
  const t=await open();
  await t.typeInstead();
  assert.equal(t.page.app.conversationUI.view,"transcript");
  assert.equal(t.page.$("thinking").shown,true,"The wait is on screen");
  assert.equal(t.page.$("answer-text").disabled,true);
  assert.equal(t.said(),THINKING,"The wait is said too");
  await t.reply({question:"What starts the work?"});
  assert.equal(t.said(),"Question: What starts the work?");
  assert.equal(t.page.$("turn-t001").querySelector(".turn-text").textContent,"What starts the work?");
  assert.equal(t.page.$("answer-text").disabled,false);
  assert.equal(t.page.document.activeElement,t.page.$("answer-text"),"The reply box has focus again once the question is there");
 });

 await check("Type instead does not pull focus back from a control the participant moved to",async()=>{
  const t=await open();
  await t.typeInstead();
  t.page.$("conversation-tab-workflow").focus();
  await t.reply({question:"What starts the work?"});
  assert.equal(t.page.document.activeElement,t.page.$("conversation-tab-workflow"));
  assert.equal(t.said(),"Question: What starts the work?");
 });

 await check("each typed answer: the wait is said once, then the next question",async()=>{
  const t=await open();
  await t.typeInstead();await t.reply({question:"What starts the work?"});
  const before=t.status.writes;
  await t.send("An email from the supplier arrives.");
  assert.equal(t.said(),THINKING);
  assert.equal(t.status.writes,before+1,"One announcement for the wait");
  // The controls are refreshed many times while a reply is prepared; none of that may repeat it.
  for(let i=0;i<5;i++)t.page.app.updateControls();
  assert.equal(t.status.writes,before+1);
  await t.reply({question:"Who reads that email first?"});
  assert.equal(t.said(),"Question: Who reads that email first?");
  assert.equal(t.status.writes,before+2,"One announcement for the question");
  await t.send("The accounts assistant.");
  assert.equal(t.said(),THINKING,"The next wait is said again");
  await t.reply({question:"What do they check?",preserve_capture:true});
  assert.equal(t.said(),"Question: What do they check?","A reply that keeps the notes as they are is a question all the same");
 });

 await check("a change in what the interviewer is doing is said; the provisional question is not said twice",async()=>{
  const t=await open();
  await t.typeInstead();await t.reply({question:"What starts the work?"});
  t.page.app.setBusy(true,"Finding another topic to explore…");
  assert.equal(t.said(),"Finding another topic to explore…");
  t.page.app.setBusy(false);t.page.app.setBusy(true);
  assert.equal(t.said(),THINKING);
  const writes=t.status.writes;
  t.page.app.showProvisionalQuestion("Who approves the invoice?");
  assert.match(t.page.$("thinking-text").textContent,/^Up next: Who approves the invoice\?/,"The provisional question is shown");
  assert.equal(t.status.writes,writes,"but it is said when it arrives as the question");
  assert.equal(t.said(),THINKING);
  t.page.app.setBusy(false);
  t.page.app.applyInterview({question:"Who approves the invoice?"});
  assert.equal(t.said(),"Question: Who approves the invoice?");
 });

 await check("read aloud: a question the voice plays is not also written to the status line",async()=>{
  const t=await open({voices:[VOICE]});
  t.page.$("speak-questions").checked=true;
  await t.typeInstead();await t.reply({question:"What starts the work?"});
  assert.deepEqual(t.page.spoken.map(utterance=>utterance.text),["What starts the work?"]);
  assert.doesNotMatch(t.said(),/What starts the work/);
  // Read aloud left on with no voice that can play: the question is said through the status line.
  t.page.app.state.voice=null;
  await t.send("An email arrives.");await t.reply({question:"Who reads it?"});
  assert.equal(t.page.spoken.length,1);
  assert.equal(t.said(),"Question: Who reads it?");
 });

 await check("live voice: nothing is added to what the interviewer says aloud",async()=>{
  const t=await open();
  await t.typeInstead();await t.reply({question:"What starts the work?"});
  t.page.app.conversationUI.live={active:true};
  const writes=t.status.writes;
  t.page.app.setBusy(true);
  t.page.app.applyInterview({question:"Who reads that email first?"});
  assert.equal(t.status.writes,writes);
  assert.equal(t.said(),"Question: What starts the work?");
  assert.equal(t.page.app.state.turns.at(-1).text,"Who reads that email first?");
 });

 await check("Voice view: the presence label is the status region for the wait; the question is still said",async()=>{
  const t=await open();
  await t.typeInstead();await t.reply({question:"What starts the work?"});
  t.page.app.selectConversationView("voice");
  const presence=t.page.$("presence-status"),writes=t.status.writes;
  assert.equal(presence.getAttribute("role"),"status");
  t.page.app.setBusy(true);
  assert.equal(presence.shown,true);assert.equal(presence.textContent,"Thinking…");
  assert.equal(t.status.writes,writes,"The same wait is not said by two regions");
  // Having heard it there, the participant is not told again on moving to the transcript,
  t.page.app.selectConversationView("transcript");t.page.app.updateControls();
  assert.equal(t.status.writes,writes);
  // but a different wait that starts there is said.
  t.page.app.setBusy(true,"Finding another topic to explore…");
  assert.equal(t.said(),"Finding another topic to explore…");
  t.page.app.selectConversationView("voice");t.page.app.setBusy(false);
  t.page.app.applyInterview({question:"Who reads that email first?"});
  assert.equal(t.said(),"Question: Who reads that email first?","The current-question caption is not a live region");
 });

 await check("a question chosen from a file is said as the question it becomes",async()=>{
  const t=await open();
  t.page.app.onDocumentEvent({type:"question",document:{id:"doc_1",name:"Payment policy.pdf",analysis:{}},question:{text:"Who signs off payments over the limit?"}});
  assert.equal(t.page.app.state.turns.at(-1).text,"From Payment policy.pdf: Who signs off payments over the limit?");
  assert.equal(t.said(),"Question: From Payment policy.pdf: Who signs off payments over the limit?");
  assert.equal(t.page.document.activeElement,t.page.$("answer-text"));
 });

 console.log(JSON.stringify({checks_passed:checks,provider_calls:0,network_calls:0}));
})().catch(error=>{console.error(error);process.exitCode=1;});
