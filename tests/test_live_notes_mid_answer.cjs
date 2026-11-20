"use strict";
// Live voice, a participant who talks for minutes. Notes wait for a pause, so in the November 19
// stress test the notes of an 18-second answer arrived 94 seconds later: a 71-second answer had
// begun 2.4 seconds after it. Now, once about 600 characters of the participant's words are
// missing from the notes, the transcript as it stands is captured while they keep talking (at most
// once every 30 seconds, one capture at a time). Its notes are shown as a lagging capture's are;
// nothing reaches the live interviewer until the answer ends; the capture of the whole answer
// still follows and alone marks the answer as captured. Stop talking still catches up the whole
// answer, and the closing sequence is left as it was.
// The page of web/index.html runs web/app.js through its own init() (tests/fixtures/app_page.cjs);
// captions arrive through the real receiveLiveCaption and captures go through the real request.
// The live session and the server are stand-ins. No browser, provider or network.
const assert=require("node:assert/strict");
const {open}=require("./fixtures/app_page.cjs");
const EXPOSE="receiveLiveCaption,receiveLiveStatus,syncLiveCoverage,getCapturedThrough,getLiveQueued,askFinalCheck";
const HOOK="const getCapturedThrough=()=>liveCapturedThrough,getLiveQueued=()=>liveCaptureQueued,askFinalCheck=line=>{pendingFinalCheck={line};};";
const CONFIG={agent_team:{enabled:true,voice_mode:"live_front",interview_memory:true,stop_intent_patterns:["^(?:i need to stop)$"]},
 live:{enabled:true},concurrent_interview:{enabled:true}};
// About 1,900 characters: a little over two minutes at an ordinary pace.
const LONG=["The payment run starts on Tuesday morning when the treasury analyst opens the supplier ledger.",
 "Every line is matched to an approved invoice and to the purchase order behind it.",
 "Lines without a match go to an exceptions sheet that the accounts payable lead reviews before lunch.",
 "Once the sheet is clear the analyst builds the payment file in the bank portal.",
 "The file is checked against the ledger totals and the currency split is confirmed with the cash forecast.",
 "Anything above fifty thousand needs a second approver from the finance director's office.",
 "The approver signs in to the portal, opens each batch and releases it with a hardware token.",
 "If the bank rejects a line the analyst corrects the account details and sends that line again on Wednesday.",
 "After release the remittance advice goes to each supplier by email from the shared mailbox.",
 "The bank statement on Thursday is reconciled to the payment file and any difference is investigated the same day.",
 "Duplicate payments are rare but when one happens the supplier is asked for a refund in writing.",
 "At month end the run totals are reported to the controller with the list of exceptions and their causes.",
 "The whole cycle takes about six hours of the analyst's time each week and most of it is the matching.",
 "Quarter end is heavier because the auditors ask for evidence of every approval above the threshold.",
 "The evidence is a portal export that the analyst saves to the audit folder with the run date in the name.",
 "Suppliers in other currencies are paid from the euro account after the treasurer agrees the rate.",
 "New suppliers cannot be paid until procurement has verified their bank letter and entered them in the ledger.",
 "That verification can take a week so urgent payments are escalated to the finance director by phone.",
 "Nobody can create a supplier and approve its payment, the portal roles keep those two apart.",
 "The run is finished when the last remittance has been sent and the reconciliation shows no open items."].join(" ");
const notes=(summary,{answer="The payment run starts when the treasury analyst opens the supplier ledger.",source="t002",kind="question",leads}={})=>({
 question:"What happens after the release?",summary,focus:"",parking_lot:[],coverage:[],coverage_verified:false,
 capture_token:"token-"+summary.replace(/\W+/g,"-").toLowerCase(),
 memo_findings:[{key:"trigger",status:"partial",answer,evidence_turns:[source]}],
 completion:{ready_for_final_check:false,complete:false},
 ...(leads?{question_candidates:leads}:{}),
 speech_authorization:{approved:true,kind,text:"What happens after the release?",revision:"r1",completion_allowed:false}});
async function interview(){
 const page=await open({config:CONFIG,expose:EXPOSE,hook:HOOK});
 page.state.context={process_name:"Supplier payments",process_owner:"",objective:"Understand the payment run",background:""};
 page.state.started=true;page.state.captureToken="token-before";
 page.state.turns=[{id:"t001",role:"assistant",text:"What starts the payment run?"}];
 const h={page,context:[],said:[],captures:[],pending:[]};
 page.t.conversationUI.live={active:true,connected:true,participantSpeaking:true,assistantSpeaking:false,
  stop(){this.active=false;return Promise.resolve({finalized:true});},setMuted(){},closeInput(){},
  appendContext(text,options){h.context.push({text,kind:options?.kind,at:page.context.Date.now()});return Promise.resolve({status:"acknowledged"});},
  say(text){h.said.push(text);return Promise.resolve({status:"acknowledged"});}};
 page.t.receiveLiveStatus("connecting");
 page.route((url,init,body)=>{
  if(url!=="/api/agent-team/interview")return {};
  h.captures.push({body,at:page.context.Date.now()});
  // Each capture stays on its way until the test lets it return; a cancelled one fails as fetch does.
  return new Promise((resolve,reject)=>{
   h.pending.push(resolve);
   init.signal?.addEventListener("abort",()=>{h.pending.splice(h.pending.indexOf(resolve),1);reject(new DOMException("The operation was aborted.","AbortError"));});
  });
 });
 h.land=async value=>{h.pending.shift()(value);await page.flush();await page.flush();};
 // The participant speaks, two and a half words a second unless stated: a caption delta brings up
 // to three words (one word at a time where a test needs the exact word that sends a capture).
 h.speaker=(id,text,{msPerWord=400}={})=>{
  const words=text.split(" ");let said=0;
  return {
   say(count=words.length){
    for(let left=count;left>0&&said<words.length;){
     const step=Math.min(3,left,words.length-said);said+=step;left-=step;page.advance(msPerWord*step);
     page.t.receiveLiveCaption({id,role:"user",text:words.slice(0,said).join(" "),final:false});
    }
   },
   get text(){return words.slice(0,said).join(" ");},
   get done(){return said===words.length;},
   final(){page.t.conversationUI.live.participantSpeaking=false;page.t.receiveLiveCaption({id,role:"user",text:words.slice(0,said).join(" "),final:true});}
  };
 };
 // The 400 ms timer after a finished caption that sends the capture of the whole answer.
 h.runCaptureTimer=async()=>{
  const timer=page.waiting(entry=>String(entry.fn).includes("runLiveCapture"))[0];
  assert.ok(timer,"A capture of the whole answer is scheduled");
  await page.run(timer);
 };
 return h;
}
const sentTurns=capture=>capture.body.turns;
const lastAnswer=capture=>sentTurns(capture).filter(turn=>turn.role==="user").at(-1);
let passed=0;
async function check(name,fn){await fn();passed++;console.log("PASS "+name);}
(async()=>{
 await check("a long answer is noted while it is spoken; the interviewer hears nothing until it ends",async()=>{
  const h=await interview(),page=h.page,answer=h.speaker("live_u1",LONG);
  // Below the threshold nothing is sent: notes still wait for the pause.
  answer.say(60);
  assert.ok(answer.text.length<600);assert.equal(h.captures.length,0,"No capture for the first sentences");
  // (a) The caption that brings the notes 600 characters behind sends one capture of the answer so far.
  while(!h.captures.length&&!answer.done)answer.say(1);
  assert.equal(h.captures.length,1,"A capture is sent while the participant is still speaking");
  const read=lastAnswer(h.captures[0]).text;
  assert.ok(read.length>=600&&read.split(" ").slice(0,-1).join(" ").length<600,"Sent at the first caption past 600 characters ("+read.length+")");
  assert.ok(LONG.startsWith(read)&&read.length<LONG.length,"It reads the answer as it stands");
  assert.equal(h.captures[0].body.live_notes,true);assert.equal(h.captures[0].body.capture_token,"token-before");
  assert.equal("openAnswers" in h.captures[0].body,false,"Page bookkeeping is not sent to the server");
  assert.equal(page.state.turns.length,2,"One question and the answer being spoken");
  // One capture at a time: more words while it is on its way send nothing more.
  answer.say(25);assert.equal(h.captures.length,1);
  // (b) It returns while the participant is still speaking: its notes are applied.
  // Its lead would be offered when the answer ends if it were kept: nothing said later names its anchor.
  await h.land(notes("Notes from the first half",{leads:[{id:"lead-half",source:"t002",quote:"The payment run starts on Tuesday morning",
   gap:"Who reviews the exceptions sheet?",anchors:["lunch"]}]}));
  assert.equal(page.state.summary,"Notes from the first half","The notes are applied during the answer");
  assert.equal(page.state.memo_findings.find(item=>item.key==="trigger")?.answer,"The payment run starts when the treasury analyst opens the supplier ledger.");
  assert.equal(page.text("summary-text"),"Notes from the first half","The Notes panel shows them");
  assert.equal(page.text("analysis-through"),"Updating notes for answer 1","The notes line says the answer is still being noted");
  assert.equal(page.state.captureToken,"token-before","A token bound to part of the answer is not continued from");
  assert.equal(page.state.coverageVerified,false);assert.equal(page.state.completion,null);
  assert.equal(page.t.getCapturedThrough(),null,"The answer is not marked as captured");
  assert.equal(page.t.getLiveQueued(),true,"The capture of the whole answer is still owed");
  // (c) Nothing reaches the live interviewer mid-answer, not even when a coverage update is tried
  // (the transport tries one when the audio falls quiet).
  page.t.syncLiveCoverage();answer.say(30);page.t.syncLiveCoverage();
  assert.deepEqual(h.context,[],"Nothing is appended to the live context while the participant speaks");
  assert.deepEqual(h.said,[]);assert.equal(page.state.turns.length,2,"The lead's question is not added");
  assert.equal(h.captures.length,1,"Too little new speech and too soon for a second capture");
  // The rest of the answer, about a minute and a half: one more capture, 30 seconds or more later.
  answer.say();
  assert.equal(h.captures.length,2,"A second capture of the answer so far");
  assert.ok(h.captures[1].at-h.captures[0].at>=30000);
  assert.ok(lastAnswer(h.captures[1]).text.length-read.length>=600);
  await h.land(notes("Notes from most of the answer"));
  assert.equal(page.state.summary,"Notes from most of the answer");assert.deepEqual(h.context,[]);
  // (d) The answer ends: the capture of the whole answer runs as before and alone marks it.
  answer.final();
  assert.deepEqual(h.context,[],"Leads from part of an answer are not offered when it ends");
  await h.runCaptureTimer();
  assert.equal(h.captures.length,3,"The end-of-answer capture is sent");
  assert.equal(lastAnswer(h.captures[2]).text,LONG,"It reads the whole answer");
  assert.equal(h.captures[2].body.capture_token,"token-before");
  await h.land(notes("Notes from the whole answer",{leads:[{id:"lead-whole",source:"t002",quote:"The payment run starts on Tuesday morning",
   gap:"Who owns the audit folder?",anchors:["owner"]}]}));
  assert.equal(page.state.summary,"Notes from the whole answer");
  assert.equal(page.t.getCapturedThrough(),"t002:"+LONG,"The capture of the whole answer marks it as captured");
  assert.equal(page.t.getLiveQueued(),false);assert.equal(page.state.captureToken,"token-notes-from-the-whole-answer");
  assert.equal(page.text("analysis-through"),"Notes include all 1 saved answers");
  // After the answer the interviewer gets its one update, from the whole answer.
  assert.equal(h.context.length,1,"One update once the answer has ended");
  assert.match(h.context[0].text,/Who owns the audit folder\?/);assert.doesNotMatch(h.context[0].text,/exceptions sheet/);
 });
 await check("an answer whose capture waited is noted during the long answer that follows it",async()=>{
  // As in the stress test: an answer of about 18 seconds, then a long one 2.4 seconds later. Its
  // caption is finished while the participant is already speaking again.
  const h=await interview(),page=h.page,short=h.speaker("live_u1",LONG.slice(0,LONG.indexOf("Once the sheet")).trim());
  short.say();page.t.receiveLiveCaption({id:"live_u1",role:"user",text:short.text,final:true});
  page.t.receiveLiveCaption({id:"live_a1",role:"assistant",text:"And once the sheet is clear?",final:true});
  page.advance(2400);await h.runCaptureTimer();
  assert.equal(h.captures.length,0,"The participant is already speaking again, so the capture waits");
  const long=h.speaker("live_u2",LONG.slice(LONG.indexOf("Once the sheet")));
  const started=page.context.Date.now();
  while(!h.captures.length&&!long.done)long.say(1);
  assert.equal(h.captures.length,1,"Captured during the long answer");
  const sent=h.captures[0],seconds=(sent.at-started)/1000;
  assert.equal(sentTurns(sent).filter(turn=>turn.role==="user")[0].text,short.text,"The waiting answer is read whole");
  assert.ok(seconds<30,`Sent ${seconds} s into the long answer (the earlier answer counts towards the 600 characters)`);
  await h.land(notes("Notes through the first answer",{answer:"Unmatched lines go to an exceptions sheet.",source:"t002"}));
  assert.equal(page.state.summary,"Notes through the first answer");
  assert.equal(page.state.memo_findings.find(item=>item.key==="trigger")?.evidence_turns.join(),"t002");
  assert.deepEqual(h.context,[]);
  // The rest of the long answer; a later capture of it so far returns before it ends.
  long.say();
  while(h.pending.length)await h.land(notes("Notes so far"));
  const before=h.captures.length;
  long.final();await h.runCaptureTimer();
  assert.equal(h.captures.length,before+1);assert.equal(lastAnswer(h.captures.at(-1)).text,long.text);
  await h.land(notes("Notes through both answers"));
  assert.equal(page.t.getCapturedThrough(),"t004:"+long.text);
 });
 await check("cost stays bounded: one capture at a time, at most one mid-answer capture per 30 seconds",async()=>{
  // A fast speaker (four words a second) talking for over four minutes, the text repeated.
  const h=await interview(),page=h.page,answer=h.speaker("live_u1",[LONG,LONG,LONG].join(" "),{msPerWord:250});
  // A slow capture: nothing else is sent while it is on its way.
  while(!h.captures.length)answer.say(3);
  const first=h.captures[0].at;
  while(page.context.Date.now()-first<60000)answer.say(3);
  assert.equal(h.captures.length,1,"Never two captures at once");
  await h.land(notes("Notes one"));
  // From here each capture returns after ten seconds.
  while(!answer.done){
   answer.say(3);
   if(h.pending.length&&page.context.Date.now()-h.captures.at(-1).at>=10000)await h.land(notes("Notes "+h.captures.length));
  }
  const times=h.captures.map(capture=>capture.at);
  for(let i=1;i<times.length;i++)assert.ok(times[i]-times[i-1]>=30000,`Capture ${i+1} came ${(times[i]-times[i-1])/1000} s after the one before`);
  const minutes=(page.context.Date.now()-times[0])/60000;
  assert.ok(times.length>=4,"The notes keep up with a long answer ("+times.length+" captures)");
  assert.ok(times.length<=Math.floor(minutes*2)+1,`${times.length} captures in ${minutes.toFixed(1)} minutes`);
  assert.deepEqual(h.context,[]);assert.deepEqual(h.said,[]);
  assert.equal(page.t.getCapturedThrough(),null);
 });
 await check("a mid-answer capture that read every word is still only notes; the end-of-answer capture decides",async()=>{
  const h=await interview(),page=h.page,answer=h.speaker("live_u1",LONG);
  while(!h.captures.length)answer.say(1);
  // The participant stops on the very words the capture read.
  answer.final();
  await h.land({...notes("Notes from the capture taken mid-answer",{kind:"final_check"}),question:"Have I missed anything?",coverage_verified:true,
   completion:{ready_for_final_check:true,complete:false},speech_authorization:{approved:true,kind:"final_check",text:"Have I missed anything?",revision:"r1",completion_allowed:false}});
  assert.equal(page.state.summary,"Notes from the capture taken mid-answer","Its notes are applied");
  assert.deepEqual(h.said,[],"No closing line is spoken from it");assert.equal(page.state.closure.asked,false);assert.equal(page.state.coverageVerified,false);
  assert.equal(page.t.getCapturedThrough(),null,"It does not mark the answer as captured");
  await h.runCaptureTimer();
  assert.equal(h.captures.length,2,"The end-of-answer capture runs");
  assert.equal(h.captures[1].body.capture_token,"token-notes-from-the-capture-taken-mid-answer","It continues from the capture of the same words");
  await h.land(notes("Notes from the whole answer"));
  assert.equal(page.t.getCapturedThrough(),"t002:"+answer.text);assert.equal(h.context.length,1,"The interviewer gets its one update now");
 });
 await check("Stop talking during a mid-answer capture still catches up the whole answer",async()=>{
  const h=await interview(),page=h.page,answer=h.speaker("live_u1",LONG);
  while(!h.captures.length)answer.say(1);
  answer.say(20);
  // Stop talking: voice closes, the transport finalizes the caption, voice is off.
  page.t.conversationUI.live.active=false;page.t.receiveLiveStatus("closing");
  answer.final();page.t.receiveLiveStatus("idle");await page.flush();
  assert.equal(h.captures.length,2,"The capture of part of the answer is given up and the catch-up is sent");
  assert.equal(lastAnswer(h.captures[1]).text,answer.text,"The catch-up reads the whole answer");
  assert.equal(page.text("analysis-through"),"Updating notes from your last answer…");
  await h.land(notes("Notes after voice"));
  assert.equal(page.state.summary,"Notes after voice");assert.equal(page.t.getCapturedThrough(),"t002:"+answer.text);
  assert.deepEqual(h.context,[]);assert.deepEqual(h.said,[]);
 });
 await check("the closing sequence and a request to stop are left to the end of the answer",async()=>{
  const cases={
   "the final check was asked":page=>{page.t.askFinalCheck("Have I missed anything?");page.state.closure={asked:true,confirmed:false};page.state.coverageVerified=true;},
   "the completion stands":page=>{page.state.closure={asked:true,confirmed:true};page.state.completion={complete:true,ready_for_final_check:true};page.state.coverageVerified=true;}};
  for(const [name,set] of Object.entries(cases)){
   const h=await interview(),answer=h.speaker("live_u1",LONG);set(h.page);
   answer.say();assert.equal(h.captures.length,0,name+": nothing is captured mid-answer");
   assert.equal(h.page.state.closure.asked,true,name+": the closing state is untouched");
  }
  // Words that, so far, end like a request to stop wait for what follows them.
  const at=LONG.indexOf("Quarter end"),h=await interview(),page=h.page;
  const answer=h.speaker("live_u1",LONG.slice(0,at)+"I need to stop the payments to that supplier until procurement confirms the bank letter. "+LONG.slice(at),{msPerWord:200});
  while(!h.captures.length)answer.say(1);
  const sent=h.captures[0].at,read=lastAnswer(h.captures[0]).text.length;
  await h.land(notes("Notes one"));
  while(!answer.text.endsWith("I need to"))answer.say(1);
  assert.ok(answer.text.length-read>=600&&page.context.Date.now()-sent<30000,"Enough new words, but too soon for the next capture");
  page.advance(30000);
  answer.say(1);assert.ok(answer.text.endsWith("I need to stop"));
  assert.equal(h.captures.length,1,"Not while the words end like a request to stop");
  answer.say(1);assert.equal(h.captures.length,2,"Sent with the next word");
  assert.equal(lastAnswer(h.captures[1]).text.endsWith("I need to stop the"),true);
 });
 console.log(JSON.stringify({checks_passed:passed,provider_calls:0,network_calls:0}));
})().catch(error=>{console.error(error);process.exitCode=1;});
