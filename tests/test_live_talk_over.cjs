"use strict";
// When the interviewer talks over a participant who is still answering in Live voice. The real
// caption controller (web/live-voice.js, with the fakes of tests/test_live_voice.cjs) feeds the real
// page (web/app.js on web/index.html, tests/fixtures/app_page.cjs) through receiveLiveCaption, and the
// checks read the turns and the transcript the page shows. The timings follow the November 19 stress
// test, where a long answer and the line spoken over it became dozens of one-word turns
// ("Answer 3: documentation. Step", "Question 4: that", ...). No microphone, browser, network or provider.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const {open}=require("./fixtures/app_page.cjs");
const shared={require,__dirname,console,Buffer,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException,setImmediate,setTimeout,clearTimeout};
const exported=(source,tail)=>{const module={exports:{}};vm.runInNewContext(source+tail,{...shared,module});return module.exports;};
const voice=exported(fs.readFileSync(path.join(__dirname,"test_live_voice.cjs"),"utf8").split("(async()=>{")[0],"\nmodule.exports={setup};");
const QUESTION="What starts the work?";
let events=0;
// A live interview on the page, already asked its first question, with the controller's captions wired to it.
async function session(agent={}){
 const page=await open({config:{agent_team:{enabled:true,voice_mode:"live_front",...agent},live:{enabled:true}},expose:"receiveLiveCaption,renderTranscript,tab,selectConversationView,processEvidence"});
 page.route(()=>({}));
 page.state.context={process_name:"Supplier invoices",process_owner:"",objective:"Understand the work",background:""};page.state.started=true;
 page.state.turns=[{id:"t001",role:"assistant",text:QUESTION}];
 page.t.conversationUI.live={active:true,connected:true,participantSpeaking:false,assistantSpeaking:false,stop(){this.active=false;return Promise.resolve({finalized:true});},
  setMuted(){},appendContext(){return Promise.resolve({status:"acknowledged"});},say(){return Promise.resolve({status:"acknowledged"});}};
 page.t.tab("interview");page.t.selectConversationView("transcript");page.t.renderTranscript();
 const h=voice.setup();await h.api.start({turns:page.state.turns});
 h.api.options.onTranscript=caption=>{h.captions.push(caption);page.t.receiveLiveCaption(caption);};
 // Deltas in the order they arrive: [role, text, start_ms, end_ms] on the session timeline.
 const play=list=>{for(const [role,delta,start_ms,end_ms] of list)h.event({type:role==="user"?"session.input_transcript.delta":"session.output_transcript.delta",event_id:"event_"+(++events),delta,start_ms,end_ms});};
 const turns=()=>page.state.turns.slice(1).map(turn=>`${turn.role}: ${turn.text}`);
 const labels=()=>page.$("transcript").querySelectorAll(".turn-id").map(node=>node.textContent);
 const captions=role=>new Set(h.captions.filter(caption=>caption.role===role).map(caption=>caption.id)).size;
 return {page,h,play,turns,labels,captions,stop:()=>h.api.stop({immediate:true})};
}
// The participant goes through the steps of the work; the interviewer starts on "Step two," and the two
// speak at once for five seconds, the interviewer pausing 1.6 s inside its line as it did in the test.
const TALK_OVER=[
 ["user","Step one,",1000,1400],["user"," open the request",1600,2400],["user"," and check the requester.",2600,3800],["user"," Step two,",4000,4400],
 ["assistant","I can't",4400,4600],
 ["user"," match",4800,5000],["assistant"," confirm",4800,5000],["user"," it to",5000,5400],["assistant"," that",5200,5400],
 ["user"," the purchase",5600,6000],["assistant"," without",5600,5800],["user"," order.",6000,6200],["assistant"," the contract.",5800,6400],
 ["user"," Step three,",6400,6800],["user"," record",7000,7200],["user"," the invoice",7200,7800],
 ["assistant"," So,",8000,8200],["user"," in the",8000,8400],["assistant"," who",8400,8600],["user"," ledger.",8400,8800],
 ["assistant"," approves",8600,8800],["user"," Step four,",9000,9400],["assistant"," the payment?",8800,9400],
 // The line has ended; the answer goes on, with an ordinary pause before its last step.
 ["user"," get approval",9600,10200],["user"," from the manager.",10400,11000],["user"," Step five,",11800,12200],["user"," pay it on Friday.",12400,13000]];
const ANSWER="Step one, open the request and check the requester. Step two, match it to the purchase order. Step three, record the invoice in the ledger. Step four, get approval from the manager. Step five, pay it on Friday.";
const LINE="I can't confirm that without the contract. So, who approves the payment?";
let passed=0;const failed=[];
async function check(name,fn){
 try{await fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.message||error).split("\n").slice(0,14).join("\n     "));}
}
(async()=>{
 await check("a line spoken over a long answer leaves the whole answer, then the whole line",async()=>{
  const s=await session();s.play(TALK_OVER);
  assert.deepEqual(s.turns(),["user: "+ANSWER,"assistant: "+LINE]);
  assert.deepEqual(s.labels(),["Question 1","Answer 1","Question 2"]);
  assert.equal(s.captions("user"),1);assert.equal(s.captions("assistant"),1,"One caption each, not one per word in between");
  assert.ok(s.page.state.turns.slice(1).every(turn=>turn.text.split(/\s+/).length>=10),"No turn of a few words");
  assert.equal(new Set(s.page.state.turns.map(turn=>turn.id)).size,s.page.state.turns.length,"Turn ids stay unique");
  await s.stop();
  assert.deepEqual(s.turns(),["user: "+ANSWER,"assistant: "+LINE],"Ending voice changes nothing");
 });
 await check("what is said once the talk-over is over takes its turns as before",async()=>{
  const s=await session();s.play(TALK_OVER);
  // The interviewer asks again after the answer; the participant replies once the question has been asked.
  s.play([["assistant","Thanks. And if the amounts differ, who do you call?",14200,16800],["user","The supplier's account manager.",17400,19000]]);
  assert.deepEqual(s.turns(),["user: "+ANSWER,"assistant: "+LINE,"assistant: Thanks. And if the amounts differ, who do you call?","user: The supplier's account manager."]);
  assert.deepEqual(s.labels(),["Question 1","Answer 1","Question 2","Question 3","Answer 2"]);
  await s.stop();
 });
 await check("a line that cuts in at a pause, or on the last word, does not split the answer",async()=>{
  // The interviewer takes an 800 ms pause for the end of the answer; the participant goes on
  // 200 ms after its first word, before it could have been heard.
  let s=await session();
  s.play([["user","We scan the invoice",1000,2200],["user"," into the portal.",2200,3000],
   ["assistant","Got it, and",3600,4000],["user"," Then the",3800,4200],["assistant"," who",4000,4200],
   ["user"," system matches it",4200,5000],["assistant"," keys it in?",4200,4800],["user"," to the order.",5000,5800]]);
  assert.deepEqual(s.turns(),["user: We scan the invoice into the portal. Then the system matches it to the order.","assistant: Got it, and who keys it in?"]);
  await s.stop();
  // The interviewer starts on the answer's last word, as at 104.4 s of another run of the test.
  s=await session();
  s.play([["user","Step four, screen the supplier.",1000,3000],["user"," Step",3000,3200],["assistant","I heard",3200,3400],
   ["user"," five.",3400,3600],["assistant"," two approvals.",3400,4200],["assistant"," Who gives the second?",4400,5600]]);
  assert.deepEqual(s.turns(),["user: Step four, screen the supplier. Step five.","assistant: I heard two approvals. Who gives the second?"]);
  await s.stop();
 });
 await check("ordinary exchanges keep their turns, and a filler still joins the question after it",async()=>{
  // Latencies as measured in the test recordings: the interviewer replies 600 to 800 ms after an answer.
  const s=await session();
  s.play([["user","An invoice arrives by email",1000,2600],["assistant","Okay.",3200,3500],["user",".",2600,2620],
   ["assistant"," Who checks it first?",4400,5600],["user","The accounts clerk does.",6200,7400],
   ["assistant","And when the amount is wrong, what happens?",8000,10000],["user","We send it back.",10600,11800],
   // An answer that begins 1.2 s into a line has heard it: it is an answer below the line.
   ["assistant","Who decides that it goes back, and how is the supplier told?",12400,15800],["user","The clerk decides.",13600,14600]]);
  assert.deepEqual(s.turns(),["user: An invoice arrives by email.","assistant: Okay. Who checks it first?","user: The accounts clerk does.",
   "assistant: And when the amount is wrong, what happens?","user: We send it back.",
   "assistant: Who decides that it goes back, and how is the supplier told?","user: The clerk decides."]);
  assert.deepEqual(s.labels(),["Question 1","Answer 1","Question 2","Answer 2","Question 3","Answer 3","Question 4","Answer 4"]);
  await s.stop();
 });
 await check("without a session timeline an interviewer line still ends the answer",async()=>{
  const s=await session();
  s.play([["user","We log the invoice."],["assistant","Who approves it?"],["user","The manager."],["assistant","And then?"],["user","We pay it."]]);
  assert.deepEqual(s.turns(),["user: We log the invoice.","assistant: Who approves it?","user: The manager.","assistant: And then?","user: We pay it."]);
  await s.stop();
 });
 await check("a reply to a short question is a new answer below it, after a listening cue or a talked-over start",async()=>{
  // "Mm-hmm." while the participant pauses, then the rest of the answer, then quick questions and replies.
  let s=await session();
  s.play([["user","We log the invoice",1000,3000],["assistant","Mm-hmm.",3600,3900],["user"," and send it on for approval.",4000,5000],
   ["assistant","Who approves it?",5600,6400],["user","The finance manager.",6900,7800],["assistant","And above ten thousand?",8400,9600],["user","The CFO.",10200,10800]]);
  assert.deepEqual(s.turns(),["user: We log the invoice and send it on for approval.","assistant: Mm-hmm. Who approves it?","user: The finance manager.",
   "assistant: And above ten thousand?","user: The CFO."]);
  await s.stop();
  // The last words of the answer overlap a short question; the reply comes 400 ms after the question ends,
  // and a follow-up is answered the same way. Each reply belongs below its own question.
  s=await session();
  s.play([["user","We check the invoice",1000,2400],["assistant","Who signs",2600,3000],["user"," against the order.",2600,3200],
   ["assistant"," it off?",3000,3400],["user","The manager.",3800,4400],["assistant","And if she's away?",5000,6000],["user","Her deputy.",6600,7200],
   ["assistant","Got it. What happens next?",7800,9400]]);
  assert.deepEqual(s.turns(),["user: We check the invoice against the order.","assistant: Who signs it off?","user: The manager.",
   "assistant: And if she's away?","user: Her deputy.","assistant: Got it. What happens next?"]);
  assert.deepEqual(s.labels(),["Question 1","Answer 1","Question 2","Answer 2","Question 3","Answer 3","Question 4"]);
  await s.stop();
 });
 await check("a correction spoken into a recap is an answer below what it corrects",async()=>{
  const s=await session();
  s.play([["user","Then we post it",1000,2400],["assistant","So you",2600,2800],["user"," to the ledger.",2600,3000],
   ["assistant"," match it to the purchase order",2800,4600],["user","No, we don't match it.",4400,5600],["assistant"," and then you post it?",4800,6000]]);
  assert.deepEqual(s.turns(),["user: Then we post it to the ledger.","assistant: So you match it to the purchase order",
   "user: No, we don't match it.","assistant: and then you post it?"],"The correction follows the recap it contradicts");
  await s.stop();
 });
 await check("a request to stop spoken over the interviewer ends voice, also with a thank-you after it",async()=>{
  const STOP={stop_intent_patterns:["^(?:i need to stop(?: now)?)$"],stop_sign_off_pattern:"^(?:okay|thanks|thank you|bye)$"};
  // "Thanks." once the line has ended: a turn of its own below the line, as before the talk-over.
  let stops=0;const counted=page=>{const live=page.t.conversationUI.live,stop=live.stop.bind(live);live.stop=()=>{stops++;return stop();};};
  let s=await session(STOP);counted(s.page);
  s.play([["user","We pay on Friday.",1000,2400],["assistant","And who",2600,2800],["user"," I need to stop now.",2800,4200],
   ["assistant"," approves it? Of course, we can pause here.",2800,5200],["user"," Thanks.",5600,6000]]);
  assert.deepEqual(s.turns(),["user: We pay on Friday. I need to stop now.","assistant: And who approves it? Of course, we can pause here.","user: Thanks."]);
  assert.equal(stops,1,"Voice ends");assert.equal(s.page.t.conversationUI.muted,true,"The microphone is closed");
  await s.stop();
  // "Thanks." 300 ms after the request, while the line is still being spoken: the same caption as the request.
  stops=0;s=await session(STOP);counted(s.page);
  s.play([["user","We pay on Friday.",1000,2400],["assistant","And who",2600,2800],["user"," I need to stop now.",2800,4200],
   ["assistant"," approves it? Of course,",2800,4600],["user"," Thanks.",4500,4800],["assistant"," we can pause here.",4600,5600]]);
  // The answer is settled once the participant has been quiet for a moment.
  await new Promise(resolve=>setTimeout(resolve,1700));
  assert.deepEqual(s.turns(),["user: We pay on Friday. I need to stop now. Thanks.","assistant: And who approves it? Of course, we can pause here."]);
  assert.equal(stops,1,"Voice ends");assert.equal(s.page.t.conversationUI.muted,true,"The microphone is closed");
  const answers=s.page.t.processEvidence({turns:s.page.state.turns}).turns.filter(turn=>turn.role==="user").map(turn=>turn.text);
  assert.deepEqual(answers,["We pay on Friday."],"Only the answer before the request is process evidence");
  await s.stop();
 });
 await check("an answer that reaches the length limit while the interviewer talks over it leaves the line whole",async()=>{
  const s=await session(),long=("We match the invoice to the purchase order and the delivery note. ".repeat(100)).slice(0,5990).trimEnd();
  s.play([["user",long,1000,2400],["assistant","Who",2400,2600],["user"," and the clerk keeps going",2600,3200],["assistant"," approves it?",2800,3400],
   ["user"," with the next one",3400,3800],["assistant"," Please say.",3600,4000]]);
  const turns=s.page.state.turns.slice(1);
  assert.deepEqual(turns.map(turn=>turn.role),["user","assistant","user"]);
  assert.equal(turns[0].text,long);assert.equal(turns[2].text,"and the clerk keeps going with the next one");
  assert.equal(turns[1].text,"Who approves it? Please say.","The line is one turn, not cut where the answer reached the limit");
  assert.equal(s.captions("assistant"),1);
  await s.stop();
 });
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
