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
async function session(){
 const page=await open({config:{agent_team:{enabled:true,voice_mode:"live_front"},live:{enabled:true}},expose:"receiveLiveCaption,renderTranscript,tab,selectConversationView"});
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
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
