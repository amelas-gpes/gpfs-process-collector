"use strict";
// The interview limit (400 turns, 400,000 characters on the server): a warning well before it,
// new answers stopped while the closing sequence still fits, Wrap up available until it no longer
// does, and no instruction that points at a disabled control. The page of web/index.html runs
// web/app.js through its own init() (tests/fixtures/app_page.cjs). No browser, provider or network.
const assert=require("node:assert/strict");
const {open}=require("./fixtures/app_page.cjs");
const EXPOSE="renderTranscript,updateControls,sendAnswer,receiveLiveCaption,getConcurrentInterview,tab,selectConversationView";
const ACK="Let me check that I have everything before we finish.",FINAL="Is there anything I have missed or got wrong?";
const DONE="Thank you. All sixteen sections are captured and you have confirmed the account. It is ready for process-owner review.";
// An interview of `count` turns that began with a question; `size` spreads that many characters over it.
function fill(page,count,size=0){
 const each=size?Math.floor(size/count):0;
 page.state.context={process_name:"Supply order",process_owner:"",objective:"Understand the work",background:""};page.state.started=true;
 page.state.turns=Array.from({length:count},(_,index)=>({id:"t"+String(index+1).padStart(3,"0"),role:index%2?"user":"assistant",
  text:each?"x".repeat(index===0?size-each*(count-1):each):index%2?"We count the cupboard.":"What happens next?"}));
 // The lead has said the account is ready for the final check, so Wrap up is offered (with the managed
 // team and no concurrent notes that is what enables it); only the limit is under test here.
 page.state.completion={ready_for_final_check:true,complete:false};
 page.t.conversationUI.typing=true;page.t.tab("interview");page.t.selectConversationView("transcript");page.t.renderTranscript();
}
const controls=page=>({send:!page.$("send-answer").disabled,dictate:!page.$("record-answer").disabled,skip:!page.$("skip-question").disabled,wrap:!page.$("final-check").disabled});
const typed=page=>{page.$("answer-text").value="One more detail.";page.t.updateControls();};
const line=page=>page.$("interview-limit").hidden?"":page.text("interview-limit");
const reply=(question,kind,extra={})=>({question,summary:"",focus:"",parking_lot:[],memo_findings:[],coverage:[],
 completion:{ready_for_final_check:kind==="final_check"||kind==="complete",complete:kind==="complete"},closure:{asked:kind==="final_check"||kind==="complete",confirmed:kind==="complete"},
 speech_authorization:{approved:true,kind,text:question,revision:"r1",completion_allowed:kind==="complete"},coverage_verified:kind!=="review_pending"&&kind!=="question",...extra});
let passed=0;const failed=[];
async function check(name,fn){
 try{await fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.message||error).split("\n").slice(0,6).join("\n     "));}
}
(async()=>{
 const config={agent_team:{enabled:true}};
 await check("nothing is said or blocked in an interview of ordinary length",async()=>{
  const page=await open({config,expose:EXPOSE});
  for(const count of [3,201,359]){fill(page,count);typed(page);assert.equal(line(page),"",`${count} turns`);assert.deepEqual(controls(page),{send:true,dictate:true,skip:true,wrap:true},`${count} turns`);}
  assert.equal(page.text("composer-hint"),"Ctrl / ⌘ + Enter to send");
 });
 await check("from 360 turns a line that stays says how much room is left and to wrap up",async()=>{
  const page=await open({config,expose:EXPOSE});
  fill(page,360);typed(page);
  assert.equal(page.shown("interview-limit"),true,"The warning is on screen");
  assert.match(line(page),/^About 16 exchanges left in this interview\. Wrap up soon to get the final check\./);
  assert.deepEqual(controls(page),{send:true,dictate:true,skip:true,wrap:true},"Nothing is blocked yet");
  assert.equal(page.waiting(timer=>timer.fn.name==="dismissNotice").length,0,"It is not a toast that times out");
  fill(page,381);assert.match(line(page),/^About 5 exchanges left/);
  fill(page,388);assert.match(line(page),/^About 2 exchanges left/);
  fill(page,391);assert.match(line(page),/^Room for one more answer in this interview\. Wrap up now to get the final check\./);
  // Counted in characters too: long answers reach the size limit in far fewer turns.
  fill(page,120,350000);typed(page);assert.match(line(page),/^This interview is close to its size limit\. Wrap up soon to get the final check\./);
  assert.deepEqual(controls(page),{send:true,dictate:true,skip:true,wrap:true});
  fill(page,120,349000);assert.equal(line(page),"");
 });
 await check("new answers stop eight turns before the limit and Wrap up stays available",async()=>{
  const page=await open({config,expose:EXPOSE});
  for(const count of [392,395,396]){
   fill(page,count);typed(page);
   assert.deepEqual(controls(page),{send:false,dictate:false,skip:false,wrap:true},`${count} turns`);
   assert.match(line(page),/limit for new answers\. Wrap up now to get the final check/,`${count} turns`);
   assert.match(page.text("composer-hint"),/Interview limit reached\. Wrap up/,`${count} turns`);
  }
  // The keyboard shortcut is held to the same rule as the Send button.
  fill(page,392);typed(page);page.route(()=>{throw new Error("No request may be sent for a blocked answer");});
  await page.t.sendAnswer({preventDefault(){}});await page.flush();
  assert.equal(page.state.turns.length,392,"The answer is not added");assert.equal(page.$("answer-text").value,"One more detail.","and stays in the box");
  assert.match(page.text("notice-text"),/limit for new answers/);assert.equal(page.requests.filter(request=>request.url!=="/api/config").length,0);
  // In characters: a full-length answer no longer fits from 394,000, and the closing lines keep their room.
  fill(page,120,394000);typed(page);assert.deepEqual(controls(page),{send:false,dictate:false,skip:false,wrap:true});
  fill(page,120,393000);page.$("answer-text").value="y".repeat(6000);page.t.updateControls();
  await page.t.sendAnswer({preventDefault(){}});await page.flush();
  assert.equal(page.state.turns.length,120,"An answer that would use the room kept for the closing lines is not sent");
  assert.match(page.text("notice-text"),/too long to send/);
 });
 await check("the closing sequence fits after the last answer: acknowledgement, final check, reply, closing line",async()=>{
  const page=await open({config,expose:EXPOSE});fill(page,396);
  let reviews=0;
  page.route((url,options,body)=>{
   if(url==="/api/agent-team/interview")return body.action==="close"?reply(ACK,"review_pending",{capture_token:"token-ack",review_ticket:"ticket-one",agent_run_id:"run-one"})
    :reply(DONE,"complete",{capture_token:"token-done",no_new_run:true});
   if(url==="/api/agent-team/review"){reviews++;return reply(FINAL,"final_check",{capture_token:"token-final"});}
   return {};
  });
  assert.equal(page.$("final-check").click(),true,"Wrap up can be pressed at 396 turns");await page.flush();await page.flush();
  assert.equal(reviews,1);assert.equal(page.state.turns.length,398);assert.equal(page.state.turns.at(-1).text,FINAL);
  assert.equal(page.state.closure.asked,true);
  // The reply to the final check is the one answer that is still accepted.
  page.$("answer-text").value="No, that is everything.";page.t.updateControls();
  assert.equal(controls(page).send,true,"The reply to the final check can be sent");assert.match(line(page),/Reply to the final check to finish/);
  await page.t.sendAnswer({preventDefault(){}});await page.flush();
  assert.equal(page.state.turns.length,400);assert.equal(page.state.turns.at(-1).text,DONE);assert.equal(page.state.closure.confirmed,true);
  assert.equal(line(page),"","A completed interview needs no limit warning");
  assert.equal(page.$("global-notice").classList.contains("error"),false,"Nothing failed on the way");
 });
 await check("Wrap up is disabled only when the closing sequence no longer fits, and nothing points at it then",async()=>{
  const page=await open({config:{...config,concurrent_interview:{enabled:true}},modules:["concurrent-interview.js"],expose:EXPOSE});
  fill(page,396);typed(page);assert.equal(controls(page).wrap,true);
  page.t.getConcurrentInterview().notify({state:"error"});
  assert.equal(page.text("analysis-status"),"Notes need attention. Wrap up to retry.");
  for(const count of [397,399,400]){
   fill(page,count);typed(page);
   assert.deepEqual(controls(page),{send:false,dictate:false,skip:false,wrap:false},`${count} turns`);
   assert.match(line(page),/^This interview is full\. Create a draft or save a copy/,`${count} turns`);
   assert.doesNotMatch(page.text("analysis-status"),/Wrap up/,`${count} turns: the notes status does not point at a disabled control`);
   assert.match(page.text("analysis-status"),/^Notes need attention\. Create a draft or save a copy\./);
   assert.doesNotMatch(page.text("composer-hint"),/Wrap up/);
   assert.equal(page.$("generate-draft").disabled,false,"Create draft stays available");
  }
  fill(page,120,398801);typed(page);assert.equal(controls(page).wrap,false,"No room for the closing lines in characters");
  fill(page,120,398800);typed(page);assert.equal(controls(page).wrap,true);
 });
 await check("Live voice: warned early, stopped when answers stop, and no words are dropped there",async()=>{
  const page=await open({config:{agent_team:{enabled:true,voice_mode:"live_front"},live:{enabled:true}},expose:EXPOSE});
  fill(page,358);let stops=0;
  page.t.conversationUI.live={active:true,connected:true,participantSpeaking:false,assistantSpeaking:false,stop(){stops++;this.active=false;return Promise.resolve({finalized:true});},setMuted(){},appendContext(){return Promise.resolve({status:"acknowledged"});}};
  page.route(()=>({}));
  page.t.receiveLiveCaption({id:"c1",role:"assistant",text:"And after that?",final:true});
  assert.equal(line(page),"");
  page.t.receiveLiveCaption({id:"c2",role:"user",text:"We file the count.",final:true});
  assert.equal(page.state.turns.length,360);assert.match(line(page),/^About 16 exchanges left in this interview/,"The warning appears while voice is on");assert.equal(stops,0);
  fill(page,390);page.t.conversationUI.live.active=true;
  page.t.receiveLiveCaption({id:"c3",role:"assistant",text:"Anything else?",final:true});assert.equal(stops,0);
  page.t.receiveLiveCaption({id:"c4",role:"user",text:"Only the monthly reorder.",final:true});
  assert.equal(page.state.turns.length,392);assert.equal(page.state.turns.at(-1).text,"Only the monthly reorder.","The answer that reaches the limit is kept");
  assert.equal(stops,1,"Voice stops while the closing sequence still fits");
  assert.match(page.text("notice-text"),/limit for new answers, so voice has stopped\. Choose Wrap up/);
  assert.equal(page.$("interview-error").hidden,false,"The reason stays on the line above the conversation");
  // A caption the transport delivers while it closes is still recorded, and voice is not stopped twice.
  page.t.conversationUI.live.active=true; // the transport is still closing
  page.t.receiveLiveCaption({id:"c5",role:"assistant",text:"Thank you.",final:true});assert.equal(page.state.turns.length,393);
  page.t.receiveLiveCaption({id:"c6",role:"user",text:"Bye.",final:true});assert.equal(page.state.turns.length,394);assert.equal(stops,1);
  page.t.conversationUI.live=null;page.state.completion={ready_for_final_check:true,complete:false};page.t.updateControls();typed(page);
  assert.equal(controls(page).wrap,true,"Wrap up is available once voice is off");
 });
 await check("Live voice: the spoken reply to the final check is not cut off, and the hard limit still holds",async()=>{
  const page=await open({config:{agent_team:{enabled:true,voice_mode:"live_front"},live:{enabled:true}},expose:EXPOSE});
  fill(page,394);let stops=0;page.route(()=>({}));
  page.t.conversationUI.live={active:true,connected:true,participantSpeaking:false,assistantSpeaking:false,stop(){stops++;return Promise.resolve({finalized:true});},setMuted(){},appendContext(){return Promise.resolve({status:"acknowledged"});}};
  page.state.closure={asked:true,confirmed:false};
  page.t.receiveLiveCaption({id:"c1",role:"user",text:"No,",final:false});
  assert.equal(page.state.turns.length,395);assert.equal(stops,0,"The reply to the final check is not cut off at its first words");
  page.t.receiveLiveCaption({id:"c1",role:"user",text:"No, that is everything.",final:true});
  assert.equal(page.state.turns.at(-1).text,"No, that is everything.");assert.equal(stops,0,"It is heard to its end");
  fill(page,400);page.t.conversationUI.live.active=true;
  page.t.receiveLiveCaption({id:"c9",role:"user",text:"One more thing.",final:true});
  assert.equal(page.state.turns.length,400,"Nothing is added beyond what the server accepts");assert.equal(stops,1);
  assert.match(page.text("notice-text"),/This interview is full/);
 });
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0,real_browser:false}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
