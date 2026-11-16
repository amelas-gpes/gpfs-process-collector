"use strict";
// Notices a person can actually read: shown inside the modal dialog that is open (the page behind
// it is inert), on screen long enough for their length, paused while pointed at or focused, and,
// for warnings about saved data, kept on a line that does not time out.
// The page of web/index.html runs web/app.js through its own init() (tests/fixtures/app_page.cjs).
// No browser, provider, microphone or network.
const assert=require("node:assert/strict");
const {open}=require("./fixtures/app_page.cjs");
const dismissal=page=>page.waiting(timer=>timer.fn.name==="dismissNotice");
const EXPOSE="renderTranscript,notice,dismissNotice,jumpToTurn,setMemoSheet,setInterviewSettings,showFoundationTopic,closeFoundationTopic,importSession,sessionObject,tab,selectConversationView,sendAnswer";
const STOPPED="Voice stopped early. The last few lines of the transcript may be missing.";
const OPENED="Interview opened. Saved coverage and completion are provisional. Your last answer did not receive a reply. Choose Ask the next question, or Recheck coverage in Workflow.";
const answered=page=>{page.state.context={process_name:"Supply order",process_owner:"",objective:"Understand the work",background:""};page.state.started=true;
 page.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:"A weekly count of the supply cupboard."}];page.t.renderTranscript();};
let passed=0;const failed=[];
// Every check runs, so one failure does not hide the others; any failure fails the suite.
async function check(name,fn){
 try{await fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.message||error).split("\n").slice(0,6).join("\n     "));}
}
(async()=>{
 // ── app-core-1-3: a notice raised while a modal dialog is open ──────────────────────────────
 await check("a failed Wrap up pressed in the Workspace sheet says so inside the sheet",async()=>{
  const page=await open({narrow:true,config:{agent_team:{enabled:false}},expose:EXPOSE});
  answered(page);page.t.tab("interview");page.t.selectConversationView("transcript");
  const sheet=page.$("memo-sheet"),toast=page.$("global-notice"),home=toast.parentNode,after=toast.nextSibling;
  assert.ok(sheet.contains(page.$("final-check")),"On a narrow window Wrap up is inside the Workspace sheet");
  assert.equal(page.$("open-memo").click(),true);assert.equal(sheet.open,true);
  page.route(()=>{throw new TypeError("offline");});
  assert.equal(page.$("final-check").click(),true,"Wrap up can be pressed");await page.flush();
  assert.match(page.text("notice-text"),/isn’t available right now/);
  assert.ok(sheet.contains(toast),"The message is inside the open dialog");assert.equal(page.shown("global-notice"),true);
  assert.equal(page.shown("interview-error"),false,"The inline error line is behind the sheet");
  assert.equal(dismissal(page).length,0,"An error whose only readable copy is this one does not time out while the dialog is open");
  // Closing the sheet puts the notice back where it lives and shows the inline line; only then does it time out.
  assert.equal(page.$("close-memo").click(),true);
  assert.equal(toast.parentNode,home);assert.equal(toast.nextSibling,after);assert.equal(page.shown("global-notice"),true);
  assert.equal(page.shown("interview-error"),true);assert.match(page.text("interview-error"),/isn’t available right now/);
  assert.equal(dismissal(page).length,1);await page.run(dismissal(page)[0]);
  assert.equal(toast.hidden,true);assert.equal(page.shown("interview-error"),true,"The inline error stays");
 });
 await check("an ordinary notice in Settings is shown in Settings and times out as usual",async()=>{
  const page=await open({expose:EXPOSE});
  page.t.setInterviewSettings(true);const settings=page.$("interview-settings"),toast=page.$("global-notice"),home=toast.parentNode;
  page.t.notice("Voice changed.");
  assert.ok(settings.contains(toast));assert.equal(page.shown("global-notice"),true);
  assert.equal(dismissal(page).length,1,"A message the person can see times out");
  await page.run(dismissal(page)[0]);assert.equal(toast.hidden,true);
  page.t.setInterviewSettings(false);assert.equal(toast.parentNode,home,"The hidden notice goes home with the dialog closed");
  page.t.notice("Saved.");assert.equal(toast.parentNode,home);assert.equal(page.shown("global-notice"),true);
 });
 await check("the top-most dialog hosts the notice; it moves down the stack as dialogs close",async()=>{
  const page=await open({narrow:true,expose:EXPOSE});
  const sheet=page.$("memo-sheet"),topic=page.$("foundation-dialog"),toast=page.$("global-notice"),home=toast.parentNode;
  page.$("open-memo").click();
  const button=sheet.querySelector('[data-foundation-topic="purpose"]');assert.ok(button,"The topics are in the sheet");
  assert.equal(button.click(),true);assert.equal(topic.open,true);
  page.t.notice("The notes could not be updated.",true);
  assert.ok(topic.contains(toast),"The dialog on top shows it");assert.equal(page.shown("global-notice"),true);assert.equal(dismissal(page).length,0);
  page.t.closeFoundationTopic();
  assert.ok(sheet.contains(toast),"Still covered by the sheet: the notice moves into it");assert.equal(page.shown("global-notice"),true);assert.equal(dismissal(page).length,0);
  page.t.setMemoSheet(false);
  assert.equal(toast.parentNode,home);assert.equal(page.shown("global-notice"),true);assert.equal(dismissal(page).length,1);
 });
 await check("a source link to the interview setup opens Settings with its explanation on top",async()=>{
  const page=await open({expose:EXPOSE});answered(page);
  page.t.jumpToTurn("context");
  assert.equal(page.$("interview-settings").open,true);
  assert.ok(page.$("interview-settings").contains(page.$("global-notice")));assert.equal(page.shown("global-notice"),true);
  assert.match(page.text("notice-text"),/comes from the interview setup/);
 });
 await check("dismissing a notice inside a dialog works and keeps the keyboard in the dialog",async()=>{
  const page=await open({expose:EXPOSE});
  page.t.setInterviewSettings(true);page.t.notice("Something failed.",true);
  const dismiss=page.$("dismiss-notice");dismiss.focus();assert.equal(page.document.activeElement,dismiss,"The close button can be reached");
  assert.equal(dismiss.click(),true);
  assert.equal(page.$("global-notice").hidden,true);
  assert.ok(page.$("interview-settings").contains(page.document.activeElement),"Focus stays inside the open dialog");
 });
 await check("a dialog that rebuilds its own content does not lose the notice it is showing",async()=>{
  // Admin, Submit and the source excerpt replace all their children when they render again.
  const page=await open({expose:EXPOSE+",clearState"});const admin=page.$("knowledge-admin"),toast=page.$("global-notice"),home=toast.parentNode;
  admin.showModal();page.t.notice("The example could not be added to Admin.",true);
  assert.ok(admin.contains(toast));
  admin.replaceChildren(page.document.createElement("section"));
  assert.equal(page.document.getElementById("global-notice"),null,"The rebuild dropped the notice from the page");
  // Anything that runs before the page has put it back still finds it: another notice, Start over.
  page.t.notice("Saved to Admin.");
  assert.ok(admin.contains(toast),"The next notice is shown in the dialog again");assert.equal(page.text("notice-text"),"Saved to Admin.");assert.equal(page.shown("global-notice"),true);
  admin.replaceChildren(page.document.createElement("section"));
  assert.doesNotThrow(()=>page.t.clearState(),"Start over does not depend on finding the notice by its id");
  page.t.notice("Something failed.",true);admin.replaceChildren(page.document.createElement("section"));await page.flush();
  assert.ok(admin.contains(toast),"A notice that is on screen is put back when the dialog rebuilds");assert.equal(page.shown("global-notice"),true);
  admin.close();assert.equal(toast.parentNode,home,"and goes home when the dialog closes");assert.equal(page.shown("global-notice"),true);
 });
 await check("with no dialog open the notice stays where it lives",async()=>{
  const page=await open({expose:EXPOSE});const toast=page.$("global-notice"),home=toast.parentNode,after=toast.nextSibling;
  page.t.notice("Saved.");assert.equal(toast.parentNode,home);assert.equal(toast.nextSibling,after);
  page.t.notice("Something failed.",true);assert.equal(toast.parentNode,home);assert.equal(dismissal(page).length,1,"On the page an error has its inline line, so the toast times out");
 });

 // ── app-core-1-4: how long a notice stays ───────────────────────────────────────────────────
 await check("a short confirmation keeps the documented three seconds; a long instruction gets reading time",async()=>{
  const page=await open({expose:EXPOSE});
  const time=message=>{page.t.notice(message);const waiting=dismissal(page);assert.equal(waiting.length,1,"One dismissal is pending per notice");return waiting[0][1].ms;};
  for(const message of ["Saved.","Send your answer first, then wrap up.","Stop talking before you open Review."])assert.equal(time(message),3000,message);
  const sentence="Continuing with the current capture. Files remain in Assets for review.",doubled=sentence+" "+sentence;
  assert.ok(time(sentence)>3000,"A sentence of twelve words is given more than three seconds");
  assert.ok(time(OPENED)>=6000,`A 21-word instruction is given at least six seconds (got ${time(OPENED)})`);
  assert.ok(time(doubled)>time(sentence),"More text, more time");
  assert.ok(time(doubled)/doubled.length>=50,"Never less than 50 ms per character");
  assert.ok(time("x".repeat(600))<=20000,"A notice never stays for more than twenty seconds by itself");
 });
 await check("the countdown pauses while the notice is pointed at or holds focus",async()=>{
  const page=await open({expose:EXPOSE});const toast=page.$("global-notice");
  page.t.notice("Saved.");assert.equal(dismissal(page).length,1);
  toast.hover(true);assert.equal(dismissal(page).length,0,"Pointing at the notice stops the countdown");
  toast.hover(false);assert.equal(dismissal(page).length,1,"Moving away starts it again");assert.equal(dismissal(page)[0][1].ms,3000,"with its full time");
  page.$("dismiss-notice").focus();assert.equal(dismissal(page).length,0,"Keyboard focus in the notice stops the countdown");
  toast.hover(true);toast.hover(false);assert.equal(dismissal(page).length,0,"Focus still holds it when the pointer leaves");
  page.$("dismiss-notice").blur();assert.equal(dismissal(page).length,1);
  await page.run(dismissal(page)[0]);assert.equal(toast.hidden,true);
  // A notice that was closed under the pointer does not leave the next one stuck.
  page.t.notice("First.");toast.hover(true);page.t.dismissNotice();page.t.notice("Second.");assert.equal(dismissal(page).length,1);
 });
 await check("Stop talking that could not finalize the transcript leaves its warning on screen",async()=>{
  const page=await open({expose:EXPOSE});answered(page);page.t.tab("interview");
  page.t.conversationUI.live={active:true,connected:true,stop:async()=>({finalized:false}),setMuted(){}};
  page.$("stop-live").dispatchEvent({type:"click",bubbles:true});await page.flush();
  assert.equal(page.text("notice-text"),STOPPED);
  const line=page.$("interview-error");
  assert.equal(line.hidden,false,"The warning is also on the line above the conversation");assert.equal(line.querySelector("span").textContent,STOPPED);
  assert.equal(line.classList.contains("advisory"),true,"It is shown as a warning, not as an error");assert.equal(page.$("global-notice").classList.contains("error"),false);
  await page.run(dismissal(page)[0]);
  assert.equal(page.$("global-notice").hidden,true);assert.equal(line.hidden,false,"The line stays after the notice has timed out");
  assert.equal(line.querySelector("span").textContent,STOPPED);
  line.querySelector("button").click();assert.equal(line.hidden,true,"Until the person dismisses it");
  // A finalized stop says nothing.
  page.t.conversationUI.live={active:true,connected:true,stop:async()=>({finalized:true}),setMuted(){}};
  page.$("stop-live").dispatchEvent({type:"click",bubbles:true});await page.flush();assert.equal(line.hidden,true);
 });
 await check("a warning never replaces an error that is still on the line, and an error replaces a warning",async()=>{
  const page=await open({expose:EXPOSE});const line=page.$("interview-error"),shown=()=>line.querySelector("span").textContent;
  page.t.notice("The notes could not be updated.",true,"notes");page.t.notice(STOPPED,false,"voice",true);
  assert.equal(shown(),"The notes could not be updated. "+STOPPED);assert.equal(line.classList.contains("advisory"),false);assert.equal(line.dataset.errorKind,"notes");
  page.t.notice(STOPPED,false,"voice",true);assert.equal(shown(),"The notes could not be updated. "+STOPPED,"Said once");
  page.t.notice("Another failure.",true);assert.equal(shown(),"Another failure.");assert.equal(line.classList.contains("advisory"),false);
  line.querySelector("button").click();
  page.t.notice(STOPPED,false,"voice",true);assert.equal(shown(),STOPPED);assert.equal(line.classList.contains("advisory"),true);
  page.t.notice("Another failure.",true);assert.equal(shown(),"Another failure.");assert.equal(line.classList.contains("advisory"),false);
  // An ordinary notice leaves the line alone.
  page.t.notice("Saved.");assert.equal(shown(),"Another failure.");assert.equal(line.hidden,false);
 });
 await check("opening a saved interview leaves the provisional-coverage warning on the line",async()=>{
  const page=await open({expose:EXPOSE});answered(page);
  const saved=JSON.stringify(page.t.sessionObject());
  await page.t.importSession({size:saved.length,text:async()=>saved});await page.flush();
  assert.equal(page.text("notice-text"),OPENED);
  const line=page.$("interview-error");assert.equal(line.hidden,false);assert.equal(line.querySelector("span").textContent,OPENED);assert.equal(line.classList.contains("advisory"),true);
  await page.run(dismissal(page)[0]);assert.equal(page.$("global-notice").hidden,true);assert.equal(page.shown("interview-error"),true);
 });
 await check("pausing the completion review leaves its instruction on the line",async()=>{
  const page=await open({config:{agent_team:{enabled:true}},expose:EXPOSE});answered(page);page.t.tab("interview");
  const ack="Let me check that I have everything before we finish.";
  page.route(url=>{
   if(url==="/api/agent-team/interview")return {question:ack,summary:"",focus:"",parking_lot:[],memo_findings:[],coverage:[],completion:{ready_for_final_check:false,complete:false},
    speech_authorization:{approved:true,kind:"review_pending",text:ack,revision:"r1",completion_allowed:false},capture_token:"token-one",coverage_verified:false,review_ticket:"ticket-one",agent_run_id:"run-one"};
   if(url==="/api/agent-team/review")return new Promise(()=>{});
   return {};
  });
  page.$("answer-text").value="That is everything.";void page.t.sendAnswer({preventDefault(){}});await page.flush();
  assert.equal(page.$("pause-completion-review").hidden,false,"The review is running and can be paused");
  page.$("pause-completion-review").dispatchEvent({type:"click",bubbles:true});await page.flush();
  const line=page.$("interview-error");
  assert.match(page.text("notice-text"),/^Review paused\./);assert.equal(line.hidden,false);assert.match(line.querySelector("span").textContent,/^Review paused\. Your answers are still here\./);
  assert.equal(line.classList.contains("advisory"),true);
 });
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0,real_browser:false}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
