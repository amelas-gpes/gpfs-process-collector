"use strict";
// Live voice, a participant who talks for minutes. Notes wait for a pause, so in the November 19
// stress test the notes of an 18-second answer arrived 94 seconds later: a 71-second answer had
// begun 2.4 seconds after it. Now the transcript as it stands is captured while the participant
// keeps talking when the answer being spoken is long (over 1,400 characters, the server's limit
// for its quick excerpt capture, or 100 seconds), or when an answer that already ended is still
// missing from the notes because the participant went straight on. Such a capture is sent with
// live_partial (the server keeps nothing of it), at most three times per answer, spaced 30, 60 and
// 120 seconds from when the previous capture returned. Its notes are shown; nothing reaches the
// live interviewer until the answer ends; the capture of the whole answer follows at once when
// it ends (a capture of part of it still on its way is given up) and alone marks it as captured.
// An ordinary answer is captured once, at its end, as before. A capture sent at a pause is kept
// when the same caption goes on. Words that could be read as a request to stop hold a capture back
// (the cases of tests/fixtures/live_stop_cases.json, held to server.py by
// tests/test_live_stop_parity.py). Stop talking still catches up the whole answer, and the closing
// sequence is left as it was.
// The page of web/index.html runs web/app.js through its own init() (tests/fixtures/app_page.cjs);
// captions arrive through the real receiveLiveCaption and captures go through the real request.
// The live session and the server are stand-ins. No browser, provider or network.
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path");
const {open}=require("./fixtures/app_page.cjs");
const STOP=JSON.parse(fs.readFileSync(path.join(__dirname,"fixtures","live_stop_cases.json"),"utf8"));
const EXPOSE="receiveLiveCaption,receiveLiveStatus,syncLiveCoverage,getCapturedThrough,getLiveQueued,askFinalCheck,liveStopInWords";
const HOOK="const getCapturedThrough=()=>liveCapturedThrough,getLiveQueued=()=>liveCaptureQueued,askFinalCheck=line=>{pendingFinalCheck={line};};";
// The stop patterns the server gives the page (server.STOP_INTENT_PATTERNS).
const CONFIG={agent_team:{enabled:true,voice_mode:"live_front",interview_memory:true,stop_intent_patterns:STOP.patterns},
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
// The longest run of LONG's first words that has at most `chars` characters.
const upTo=(chars,text=LONG)=>{let out="";for(const word of text.split(" ")){const next=out?out+" "+word:word;if(next.length>chars)break;out=next;}return out;};
const LIMIT=1400;
const notes=(summary,{answer="The payment run starts when the treasury analyst opens the supplier ledger.",source="t002",kind="question",leads}={})=>({
 question:"What happens after the release?",summary,focus:"",parking_lot:[],coverage:[],coverage_verified:false,
 capture_token:"token-"+summary.replace(/\W+/g,"-").toLowerCase(),
 memo_findings:[{key:"trigger",status:"partial",answer,evidence_turns:[source]}],
 completion:{ready_for_final_check:false,complete:false},
 ...(leads?{question_candidates:leads}:{}),
 speech_authorization:{approved:true,kind,text:"What happens after the release?",revision:"r1",completion_allowed:false}});
// What the server returns for a capture of part of an answer: notes, and no capability.
const partial=(summary,options)=>{const {capture_token:_,...value}=notes(summary,options);return {...value,live_partial:true};};
const HALF_LEAD={id:"lead-half",source:"t002",quote:"The payment run starts on Tuesday morning",gap:"Who reviews the exceptions sheet?",anchors:["lunch"]};
const WHOLE_LEAD={id:"lead-whole",source:"t002",quote:"The payment run starts on Tuesday morning",gap:"Who owns the audit folder?",anchors:["owner"]};
async function interview(){
 const page=await open({config:CONFIG,expose:EXPOSE,hook:HOOK});
 page.state.context={process_name:"Supplier payments",process_owner:"",objective:"Understand the payment run",background:""};
 page.state.started=true;page.state.captureToken="token-before";
 page.state.turns=[{id:"t001",role:"assistant",text:"What starts the payment run?"}];
 const h={page,context:[],said:[],captures:[],pending:[],cancels:[]};
 page.t.conversationUI.live={active:true,connected:true,participantSpeaking:true,assistantSpeaking:false,
  stop(){this.active=false;return Promise.resolve({finalized:true});},setMuted(){},closeInput(){},
  appendContext(text,options){h.context.push({text,kind:options?.kind,at:page.context.Date.now()});return Promise.resolve({status:"acknowledged"});},
  say(text){h.said.push(text);return Promise.resolve({status:"acknowledged"});}};
 page.t.receiveLiveStatus("connecting");
 page.route((url,init,body)=>{
  if(url==="/api/agent-team/cancel"){h.cancels.push(body.run_id);return {cancelled:true};}
  if(url!=="/api/agent-team/interview")return {};
  // Each capture stays on its way until the test lets it return; a cancelled one fails as fetch does.
  const capture={body,at:page.context.Date.now(),aborted:false};h.captures.push(capture);
  return new Promise((resolve,reject)=>{
   capture.resolve=resolve;h.pending.push(capture);
   init.signal?.addEventListener("abort",()=>{capture.aborted=true;h.pending.splice(h.pending.indexOf(capture),1);reject(new DOMException("The operation was aborted.","AbortError"));});
  });
 });
 h.land=async value=>{const capture=h.pending.shift();capture.returned=page.context.Date.now();capture.resolve(value);await page.flush();await page.flush();};
 // A capture the server could not complete.
 h.fail=async()=>{const capture=h.pending.shift();capture.returned=page.context.Date.now();
  capture.resolve({ok:false,status:502,json:async()=>({error:"The notes service failed."})});await page.flush();await page.flush();};
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
 h.captureTimers=()=>page.waiting(entry=>String(entry.fn).includes("runLiveCapture"));
 h.runCaptureTimer=async()=>{
  const timer=h.captureTimers()[0];
  assert.ok(timer,"A capture of the whole answer is scheduled");
  await page.run(timer);
 };
 return h;
}
const sentTurns=capture=>capture.body.turns;
const lastAnswer=capture=>sentTurns(capture).filter(turn=>turn.role==="user").at(-1);
const level=page=>page.$("analysis-through").dataset.level||"";
const seconds=ms=>Math.round(ms/100)/10;
let passed=0;
async function check(name,fn){await fn();passed++;console.log("PASS "+name);}
(async()=>{
 await check("an ordinary answer is captured once, at its end, as before",async()=>{
  // 729 characters (about 50 seconds) and 1,390 characters (about 95 seconds): one capture each,
  // sent 0.4 s after the answer ends, the quick excerpt capture on the server for both.
  for(const chars of [729,1390]){
   const text=upTo(chars),h=await interview(),page=h.page,answer=h.speaker("live_u1",text);
   const started=page.context.Date.now();answer.say();const ended=page.context.Date.now();
   assert.ok(text.length<=LIMIT&&ended-started<100000,`${text.length} characters in ${seconds(ended-started)} s`);
   assert.equal(h.captures.length,0,`${text.length} characters: nothing is captured while it is spoken`);
   answer.final();await h.runCaptureTimer();
   assert.equal(h.captures.length,1);assert.equal(h.captures[0].at-ended,400,"Sent 0.4 s after the answer ended");
   assert.equal(h.captures[0].body.live_partial,undefined);assert.equal(lastAnswer(h.captures[0]).text,text);
   await h.land(notes("Notes from the answer"));
   assert.equal(page.t.getCapturedThrough(),"t002:"+text);assert.equal(h.captures.length,1,`${text.length} characters: exactly one capture`);
  }
 });
 await check("a long answer is noted while it is spoken; the server is told the capture is partial",async()=>{
  const h=await interview(),page=h.page,answer=h.speaker("live_u1",LONG,{msPerWord:300});
  answer.say(200);
  assert.ok(answer.text.length<=LIMIT);assert.equal(h.captures.length,0,"Nothing while the answer is ordinary in length");
  // (a) The caption that takes the answer past 1,400 characters sends one capture of it so far.
  while(!h.captures.length&&!answer.done)answer.say(1);
  assert.equal(h.captures.length,1,"A capture is sent while the participant is still speaking");
  const read=lastAnswer(h.captures[0]).text,body=h.captures[0].body;
  assert.ok(read.length>LIMIT&&read.split(" ").slice(0,-1).join(" ").length<=LIMIT,"Sent at the first caption past 1,400 characters ("+read.length+")");
  assert.ok(LONG.startsWith(read)&&read.length<LONG.length,"It reads the answer as it stands");
  assert.equal(body.live_partial,true,"The server is told the capture is partial");
  assert.equal(body.live_notes,true);assert.equal(body.capture_token,"token-before");
  assert.equal("openAnswers" in body,false,"Page bookkeeping is not sent to the server");
  answer.say(10);assert.equal(h.captures.length,1,"One capture at a time");
  // (b) It returns while the participant is still speaking: its notes are shown, and the notes line says what they hold.
  await h.land(partial("Notes from the first part",{leads:[HALF_LEAD]}));
  assert.equal(page.state.summary,"Notes from the first part","The notes are applied during the answer");
  assert.equal(page.text("summary-text"),"Notes from the first part","The Notes panel shows them");
  assert.equal(page.text("analysis-through"),"Notes include part of answer 1");assert.equal(level(page),"","Not busy: nothing is on its way");
  assert.equal(page.state.captureToken,"token-before","The capture held before the answer is still the one continued from");
  assert.equal(page.state.coverageVerified,false);assert.equal(page.state.completion,null);
  assert.equal(page.t.getCapturedThrough(),null,"The answer is not marked as captured");
  assert.equal(page.t.getLiveQueued(),true,"The capture of the whole answer is still owed");
  // (c) Nothing reaches the live interviewer mid-answer, not even when a coverage update is tried.
  page.t.syncLiveCoverage();answer.say(5);page.t.syncLiveCoverage();
  assert.deepEqual(h.context,[],"Nothing is appended to the live context while the participant speaks");
  assert.deepEqual(h.said,[]);assert.equal(page.state.turns.length,2,"The lead's question is not added");
  answer.say();
  assert.equal(h.captures.length,1,"The rest of the answer comes too soon for a second capture of it");
  // (d) The answer ends: the capture of the whole answer, an ordinary one, alone marks it.
  const ended=page.context.Date.now();answer.final();
  assert.deepEqual(h.context,[],"Leads from part of an answer are not offered when it ends");
  await h.runCaptureTimer();
  assert.equal(h.captures.length,2,"The end-of-answer capture is sent");assert.equal(h.captures[1].at-ended,400);
  assert.equal(h.captures[1].body.live_partial,undefined,"It is not partial");
  assert.equal(lastAnswer(h.captures[1]).text,LONG,"It reads the whole answer");
  assert.equal(h.captures[1].body.capture_token,"token-before","It continues from the capture held before the answer");
  assert.equal(page.text("analysis-through"),"Updating notes for answer 1");assert.equal(level(page),"busy","Busy while it is on its way");
  await h.land(notes("Notes from the whole answer",{leads:[WHOLE_LEAD]}));
  assert.equal(page.state.summary,"Notes from the whole answer");
  assert.equal(page.t.getCapturedThrough(),"t002:"+LONG,"The capture of the whole answer marks it as captured");
  assert.equal(page.t.getLiveQueued(),false);assert.equal(page.state.captureToken,"token-notes-from-the-whole-answer");
  assert.equal(page.text("analysis-through"),"Notes include all 1 saved answers");
  assert.equal(h.context.length,1,"One update once the answer has ended");
  assert.match(h.context[0].text,/Who owns the audit folder\?/);assert.doesNotMatch(h.context[0].text,/exceptions sheet/);
 });
 await check("an answer that goes on for 100 seconds is noted while it is spoken, however few its words",async()=>{
  const h=await interview(),page=h.page,answer=h.speaker("live_u1",LONG,{msPerWord:1000});
  let started=null;
  while(!h.captures.length&&!answer.done){answer.say(1);started??=page.context.Date.now();}
  assert.equal(h.captures.length,1);
  assert.equal(h.captures[0].at-started,100000,"Sent at the first words 100 seconds after the answer began");
  assert.ok(lastAnswer(h.captures[0]).text.length<LIMIT);assert.equal(h.captures[0].body.live_partial,true);
 });
 await check("cost: a five-minute answer costs at most three captures of part of it and one of the whole",async()=>{
  // An ordinary pace (2.5 words a second); every capture takes 40 s (a full capture late in an interview).
  const text=[LONG,LONG,LONG].join(" ").split(" ").slice(0,750).join(" ");
  const h=await interview(),page=h.page,answer=h.speaker("live_u1",text);
  const t0=page.context.Date.now();
  while(!answer.done){
   answer.say(1);
   assert.ok(h.pending.length<=1,"Never two captures at once");
   if(h.pending.length&&page.context.Date.now()-h.pending[0].at>=40000)await h.land(partial("Notes "+h.captures.length));
  }
  const mid=h.captures.length,minutes=(page.context.Date.now()-t0)/60000;
  assert.ok(minutes>=4.9,`${minutes.toFixed(1)} minutes`);
  assert.ok(mid>=1&&mid<=3,`${mid} captures of part of the answer`);
  assert.ok(h.captures.every(capture=>capture.body.live_partial===true));
  // Spaced from when the capture before returned: 60 s before the second, 120 s before the third.
  for(let i=1;i<mid;i++)assert.ok(h.captures[i].at-h.captures[i-1].returned>=[30000,60000,120000][i],`Capture ${i+1}`);
  const ended=page.context.Date.now();answer.final();await h.runCaptureTimer();
  assert.equal(h.captures.length,mid+1,"Then one capture of the whole answer");
  const end=h.captures.at(-1);
  assert.equal(end.body.live_partial,undefined);assert.equal(lastAnswer(end).text,text);assert.equal(end.at-ended,400);
  await h.land(notes("Notes from the whole answer"));
  assert.equal(page.t.getCapturedThrough(),"t002:"+text);
  console.log(`  five minutes at an ordinary pace, 40 s captures: ${mid} of part of the answer (at ${h.captures.slice(0,mid).map(capture=>seconds(capture.at-t0)+" s").join(", ")}), then 1 of the whole`);
  // A fast speaker (four words a second) for over eight minutes, captures returning in 10 s: the
  // third capture of part of the answer is the last, however long the answer goes on after it.
  const fast=await interview(),speaker=fast.speaker("live_u1",Array(6).fill(LONG).join(" "),{msPerWord:250});
  const start=fast.page.context.Date.now();
  while(!speaker.done){
   speaker.say(3);
   if(fast.pending.length&&fast.page.context.Date.now()-fast.pending[0].at>=10000)await fast.land(partial("Notes "+fast.captures.length));
  }
  assert.equal(fast.captures.length,3,"At most three captures of part of one answer");
  for(let i=1;i<3;i++)assert.ok(fast.captures[i].at-fast.captures[i-1].returned>=[30000,60000,120000][i]);
  assert.ok(fast.page.context.Date.now()-fast.captures[2].returned>180000,"Long after the third, none follows");
  speaker.final();await fast.runCaptureTimer();
  assert.equal(fast.captures.length,4);assert.equal(fast.captures[3].body.live_partial,undefined);
  console.log(`  ${seconds(fast.page.context.Date.now()-start)} s at four words a second, 10 s captures: 3 of part of the answer (at ${fast.captures.slice(0,3).map(capture=>seconds(capture.at-start)+" s").join(", ")}), then 1 of the whole`);
 });
 await check("the capture of the whole answer is not held by a capture of part of it",async()=>{
  // The answer goes on after the capture of part of it was sent, then ends while it is on its way.
  {
   const h=await interview(),page=h.page,answer=h.speaker("live_u1",LONG,{msPerWord:300});
   while(!h.captures.length)answer.say(1);
   const mid=h.captures[0];
   answer.say();const ended=page.context.Date.now();answer.final();
   assert.equal(mid.aborted,true,"The capture of part of the answer is given up when the answer ends");
   assert.equal(h.cancels.length,1,"and the server is asked to stop it");
   assert.equal(h.captureTimers().length,1,"The capture of the whole answer is scheduled at once");
   await h.runCaptureTimer();
   assert.equal(h.captures.length,2);assert.equal(h.captures[1].at-ended,400,"Sent 0.4 s after the answer ended");
   assert.equal(h.captures[1].body.live_partial,undefined);assert.equal(lastAnswer(h.captures[1]).text,LONG);
   await h.land(notes("Notes from the whole answer"));
   assert.equal(page.state.summary,"Notes from the whole answer");assert.equal(page.t.getCapturedThrough(),"t002:"+LONG);
   assert.equal(h.context.length,1,"The interviewer gets its one update");
  }
  // The answer ends on the very words the capture of part of it read: that capture still cannot
  // mark the answer as captured, so it is given up for the capture of the whole answer as well.
  {
   const text=LONG.split(" ").slice(0,upTo(LIMIT).split(" ").length+1).join(" ");
   const h=await interview(),page=h.page,answer=h.speaker("live_u1",text,{msPerWord:300});
   while(!h.captures.length)answer.say(1);
   assert.equal(answer.done,true);assert.equal(lastAnswer(h.captures[0]).text,text);
   const ended=page.context.Date.now();answer.final();
   assert.equal(h.captures[0].aborted,true);
   await h.runCaptureTimer();
   assert.equal(h.captures.length,2);assert.equal(h.captures[1].at-ended,400);assert.equal(h.captures[1].body.live_partial,undefined);
   await h.land(notes("Notes from the whole answer"));
   assert.equal(page.t.getCapturedThrough(),"t002:"+text);assert.deepEqual(h.said,[]);
  }
 });
 await check("an answer whose capture waited is noted as soon as the next one begins",async()=>{
  // As in the stress test: an answer of about 18 seconds, then a long one 2.4 seconds later. Its
  // caption is finished while the participant is already speaking again.
  const h=await interview(),page=h.page,short=h.speaker("live_u1",LONG.slice(0,LONG.indexOf("Once the sheet")).trim());
  short.say();page.t.receiveLiveCaption({id:"live_u1",role:"user",text:short.text,final:true});
  page.t.receiveLiveCaption({id:"live_a1",role:"assistant",text:"And once the sheet is clear?",final:true});
  page.advance(2400);await h.runCaptureTimer();
  assert.equal(h.captures.length,0,"The participant is already speaking again, so the capture waits");
  const long=h.speaker("live_u2",LONG.slice(LONG.indexOf("Once the sheet")));
  const started=page.context.Date.now();
  long.say(1);
  assert.equal(h.captures.length,1,"Captured as the next answer begins");
  const sent=h.captures[0];
  assert.equal(sentTurns(sent).filter(turn=>turn.role==="user")[0].text,short.text,"The waiting answer is read whole");
  assert.equal(sent.body.live_partial,true,"Partial: the next answer has only begun");
  assert.ok(sent.at-started<=400,`Sent ${seconds(sent.at-started)} s into the next answer`);
  long.say(6);
  await h.land(partial("Notes through the first answer",{answer:"Unmatched lines go to an exceptions sheet.",source:"t002"}));
  assert.equal(page.state.summary,"Notes through the first answer");
  assert.equal(page.state.memo_findings.find(item=>item.key==="trigger")?.evidence_turns.join(),"t002");
  assert.equal(page.text("analysis-through"),"Notes include part of answer 2");
  assert.deepEqual(h.context,[]);
  // The rest of the long answer; a capture of it so far returns before it ends.
  long.say();
  while(h.pending.length)await h.land(partial("Notes so far"));
  const before=h.captures.length;
  assert.ok(before<=3);
  long.final();await h.runCaptureTimer();
  assert.equal(h.captures.length,before+1);assert.equal(lastAnswer(h.captures.at(-1)).text,long.text);
  assert.equal(h.captures.at(-1).body.live_partial,undefined);
  await h.land(notes("Notes through both answers"));
  assert.equal(page.t.getCapturedThrough(),"t004:"+long.text);
  // A short reply that waited ("Yes, every week.") is left to the capture at the end of the next
  // answer, which reads both: an ordinary answer after it is still captured once.
  const reply=await interview(),yes=reply.speaker("live_u1","Yes, every week.");
  yes.say();reply.page.t.receiveLiveCaption({id:"live_u1",role:"user",text:yes.text,final:true});
  reply.page.t.receiveLiveCaption({id:"live_a1",role:"assistant",text:"And then?",final:true});
  reply.page.advance(2400);await reply.runCaptureTimer();
  const next=reply.speaker("live_u2",upTo(729));next.say();
  assert.equal(reply.captures.length,0);
  next.final();await reply.runCaptureTimer();
  assert.equal(reply.captures.length,1);assert.deepEqual(sentTurns(reply.captures[0]).filter(turn=>turn.role==="user").map(turn=>turn.text),[yes.text,next.text]);
 });
 await check("the notes line says what the notes hold, busy only while a capture is on its way",async()=>{
  const h=await interview(),page=h.page,answer=h.speaker("live_u1",LONG,{msPerWord:300});
  while(!h.captures.length)answer.say(1);
  answer.say(6);await h.land(partial("Notes from the first part"));
  assert.equal(page.text("analysis-through"),"Notes include part of answer 1");assert.equal(level(page),"");
  answer.say();answer.final();await h.runCaptureTimer();
  assert.equal(page.text("analysis-through"),"Updating notes for answer 1");assert.equal(level(page),"busy");
  // The capture of the whole answer fails: the notes stay as they are, and the line says so.
  await h.fail();
  assert.equal(page.state.summary,"Notes from the first part");
  assert.equal(page.text("analysis-through"),"Notes include part of answer 1","Not 'Updating' once nothing is on its way");
  assert.equal(level(page),"");
 });
 await check("words that could be read as a request to stop hold a capture of part of an answer back",async()=>{
  const h=await interview();
  // The page's check against what the server reads (tests/fixtures/live_stop_cases.json).
  for(const [text,server,held] of STOP.cases){
   assert.equal(h.page.t.liveStopInWords(text),held,JSON.stringify(text));
   if(server)assert.equal(held,true,"Every request to stop the server reads is held back");
  }
  // Deep in an answer: a request to stop with a goodbye after it is still held back, and the
  // words are let go once three sentences have followed it.
  assert.equal(h.page.t.liveStopInWords(LONG+" I need to stop now. Thanks. Bye"),true);
  assert.equal(h.page.t.liveStopInWords(LONG+" I need to stop now. Thanks. Bye. The run"),false);
  // In an answer of 100 seconds: the capture waits on the words that end like a request to stop,
  // and goes with the words that show they were not one.
  const cases=[["The bank file goes out at noon. Okay, I need to stop","the payments to that supplier."],
   ["The bank file goes out at noon; I need to stop","the payments to that supplier."],
   ["The bank file goes out at noon… I need to stop","the payments to that supplier."],
   ["The bank file goes out at noon. Sorry, I need to stop","the payments to that supplier."],
   ["The bank file goes out at noon. I need to stop now, my boss is calling","about the release. The file goes out at noon. The controller signs it. Then the bank confirms."]];
  for(const [phrase,after] of cases){
   // Short sentences before it, so that the request is not among the first clauses of the answer
   // (one there holds the capture back for the whole answer, see liveStopInWords).
   const words=phrase.split(" "),lead=Array(25).fill("The analyst checks each line.").join(" ").split(" ").slice(0,101-words.length);
   // One word a second, one word per caption: the 101st word comes 100 seconds after the first.
   const c=await interview(),answer=c.speaker("live_u1",[...lead,...words,...after.split(" ")].join(" "),{msPerWord:1000});
   for(let word=0;word<100;word++)answer.say(1);
   assert.equal(c.captures.length,0,"Not before 100 seconds");
   answer.say(1);
   assert.ok(answer.text.endsWith(phrase),answer.text.slice(-60));
   assert.equal(c.captures.length,0,`Held back on "${phrase}" (100 seconds in)`);
   while(!c.captures.length&&!answer.done)answer.say(1);
   assert.equal(c.captures.length,1,`Sent once the words go on after "${phrase}"`);
   assert.ok(!c.page.t.liveStopInWords(lastAnswer(c.captures[0]).text));
  }
 });
 await check("a capture sent at a pause is kept when the same caption goes on, and only notes come of it",async()=>{
  const first=LONG.slice(0,LONG.indexOf("Once the sheet")).trim(),rest=LONG.slice(LONG.indexOf("Once the sheet"),LONG.indexOf("Anything above")).trim();
  // The participant pauses (the caption is finished), then goes on in the same caption.
  {
   const h=await interview(),page=h.page,answer=h.speaker("live_u1",first+" "+rest);
   answer.say(first.split(" ").length);answer.final();
   await h.runCaptureTimer();
   assert.equal(h.captures.length,1);assert.equal(lastAnswer(h.captures[0]).text,first);assert.equal(h.captures[0].body.live_partial,undefined);
   page.t.conversationUI.live.participantSpeaking=true;answer.say(6);
   await h.land(notes("Notes up to the pause",{leads:[HALF_LEAD]}));
   assert.equal(page.state.summary,"Notes up to the pause","Its notes are kept although the answer went on");
   assert.equal(page.t.getCapturedThrough(),null,"It does not mark the answer as captured");
   assert.equal(page.state.captureToken,"token-before","Its token is for words that have since grown");
   assert.equal(page.text("analysis-through"),"Notes include part of answer 1");
   assert.equal(page.t.getLiveQueued(),true);assert.deepEqual(h.context,[]);
   answer.say();answer.final();
   assert.deepEqual(h.context,[],"Its leads, from part of the answer, are not offered");
   await h.runCaptureTimer();
   assert.equal(h.captures.length,2);assert.equal(lastAnswer(h.captures[1]).text,answer.text);
   await h.land(notes("Notes from the whole answer",{leads:[WHOLE_LEAD]}));
   assert.equal(page.t.getCapturedThrough(),"t002:"+answer.text);assert.equal(h.context.length,1);
  }
  // It returns after the caption went on and finished again: notes only; the capture of the
  // whole answer follows and alone marks it.
  {
   const h=await interview(),page=h.page,answer=h.speaker("live_u1",first+" "+rest);
   answer.say(first.split(" ").length);answer.final();await h.runCaptureTimer();
   page.t.conversationUI.live.participantSpeaking=true;answer.say();answer.final();
   await h.land(notes("Notes up to the pause"));
   assert.equal(page.state.summary,"Notes up to the pause");assert.equal(page.t.getCapturedThrough(),null);
   await h.runCaptureTimer();
   assert.equal(h.captures.length,2);assert.equal(lastAnswer(h.captures[1]).text,answer.text);
   await h.land(notes("Notes from the whole answer"));assert.equal(page.t.getCapturedThrough(),"t002:"+answer.text);
  }
  // The caption's words were replaced (not added to) after the capture read them: it is not used.
  {
   const h=await interview(),page=h.page,answer=h.speaker("live_u1",first);
   answer.say();answer.final();await h.runCaptureTimer();
   const replaced=first.replace("Tuesday","Monday");
   page.t.receiveLiveCaption({id:"live_u1",role:"user",text:replaced,final:true});
   await h.land(notes("Notes of words no longer there"));
   assert.notEqual(page.state.summary,"Notes of words no longer there","A capture of changed words is not applied");
   assert.equal(page.t.getCapturedThrough(),null);
   await h.runCaptureTimer();
   assert.equal(h.captures.length,2);assert.equal(lastAnswer(h.captures[1]).text,replaced);
  }
 });
 await check("Stop talking during a capture of part of an answer still catches up the whole answer",async()=>{
  const h=await interview(),page=h.page,answer=h.speaker("live_u1",LONG,{msPerWord:300});
  while(!h.captures.length)answer.say(1);
  answer.say(20);
  // Stop talking: voice closes, the transport finalizes the caption, voice is off.
  page.t.conversationUI.live.active=false;page.t.receiveLiveStatus("closing");
  answer.final();page.t.receiveLiveStatus("idle");await page.flush();
  assert.equal(h.captures.length,2,"The capture of part of the answer is given up and the catch-up is sent");
  assert.equal(h.captures[0].aborted,true);
  assert.equal(lastAnswer(h.captures[1]).text,answer.text,"The catch-up reads the whole answer");
  assert.equal(h.captures[1].body.live_partial,undefined);
  assert.equal(page.text("analysis-through"),"Updating notes from your last answer…");
  await h.land(notes("Notes after voice"));
  assert.equal(page.state.summary,"Notes after voice");assert.equal(page.t.getCapturedThrough(),"t002:"+answer.text);
  assert.deepEqual(h.context,[]);assert.deepEqual(h.said,[]);
  // Stop talking on the very words it read: it is kept, and it is the catch-up (none follows).
  {
   const h=await interview(),page=h.page,answer=h.speaker("live_u1",LONG,{msPerWord:300});
   while(!h.captures.length)answer.say(1);
   page.t.conversationUI.live.active=false;page.t.receiveLiveStatus("closing");
   answer.final();page.t.receiveLiveStatus("idle");await page.flush();
   assert.equal(h.captures.length,1);assert.equal(h.captures[0].aborted,false);
   await h.land(partial("Notes of every word"));
   assert.equal(page.state.summary,"Notes of every word");assert.equal(page.t.getCapturedThrough(),"t002:"+answer.text);
   assert.equal(h.captures.length,1,"No catch-up follows");assert.equal(page.state.captureToken,"token-before");
   assert.deepEqual(h.context,[]);assert.deepEqual(h.said,[]);
  }
 });
 await check("the closing sequence is left to the end of the answer",async()=>{
  const cases={
   "the final check was asked":page=>{page.t.askFinalCheck("Have I missed anything?");page.state.closure={asked:true,confirmed:false};page.state.coverageVerified=true;},
   "the completion stands":page=>{page.state.closure={asked:true,confirmed:true};page.state.completion={complete:true,ready_for_final_check:true};page.state.coverageVerified=true;}};
  for(const [name,set] of Object.entries(cases)){
   const h=await interview(),answer=h.speaker("live_u1",LONG);set(h.page);
   answer.say();assert.equal(h.captures.length,0,name+": nothing is captured mid-answer");
   assert.equal(h.page.state.closure.asked,true,name+": the closing state is untouched");
  }
 });
 console.log(JSON.stringify({checks_passed:passed,provider_calls:0,network_calls:0}));
})().catch(error=>{console.error(error);process.exitCode=1;});
