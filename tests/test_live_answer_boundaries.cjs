"use strict";
// Where one participant answer ends and the next begins in Live voice captions.
// Replays the real caption controller (web/live-voice.js) with the fakes of
// tests/test_live_voice.cjs; no microphone, browser, network or provider.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const shared={require,__dirname,console,Buffer,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException,setImmediate,setTimeout,clearTimeout};
const exported=(source,tail)=>{const module={exports:{}};vm.runInNewContext(source+tail,{...shared,module});return module.exports;};
const voice=exported(fs.readFileSync(path.join(__dirname,"test_live_voice.cjs"),"utf8").split("(async()=>{")[0],"\nmodule.exports={setup};");
let events=0;
async function live(){
 const h=voice.setup();await h.api.start({turns:[{id:"t001",role:"assistant",text:"What work shall we walk through?"}]});
 h.user=(delta,start_ms,end_ms)=>h.event({type:"session.input_transcript.delta",event_id:"event_"+(++events),delta,start_ms,end_ms});
 h.interviewer=(delta,start_ms,end_ms)=>h.event({type:"session.output_transcript.delta",event_id:"event_"+(++events),delta,start_ms,end_ms});
 // Captions in the order they first appeared, each with its latest text: what the transcript shows.
 h.shown=()=>{const order=[];for(const caption of h.captions)if(!order.includes(caption.id))order.push(caption.id);
  return order.map(id=>{const caption=h.captions.filter(item=>item.id===id).at(-1);return `${caption.role}: ${caption.text}`;});};
 return h;
}
let passed=0;const failed=[];
async function check(name,fn){
 try{await fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.message||error).split("\n").slice(0,12).join("\n     "));}
}
(async()=>{
 await check("what the participant says after an interviewer statement is a new answer below it",async()=>{
  const h=await live();
  h.user("Capital calls.",100,400);
  h.interviewer("Let me check what we have and keep the unanswered parts open.",700,3600);
  h.user("Actually the bank also confirms receipt.",9000,11000);
  assert.deepEqual(h.shown(),["user: Capital calls.","assistant: Let me check what we have and keep the unanswered parts open.","user: Actually the bank also confirms receipt."]);
  await h.api.stop({immediate:true});
 });
 await check("an answer that interrupts a question stays below that question",async()=>{
  const h=await live();
  h.user("We log the invoice.",100,900);
  h.interviewer("And when the invoice arrives, who",1500,2600);
  h.user("The analyst checks it first.",2700,4000);
  h.interviewer("Got it. What does the analyst check?",4300,5600);
  h.user("Supplier and amount.",6000,7000);
  assert.deepEqual(h.shown(),["user: We log the invoice.","assistant: And when the invoice arrives, who","user: The analyst checks it first.",
   "assistant: Got it. What does the analyst check?","user: Supplier and amount."]);
  await h.api.stop({immediate:true});
 });
 await check("a request without a question mark separates the next answer",async()=>{
  const h=await live();
  h.user("We reconcile the account every month.",100,2000);
  h.interviewer("Give me an example.",2400,3400);
  h.user("Last month the fee was posted twice.",4000,6500);
  assert.deepEqual(h.shown(),["user: We reconcile the account every month.","assistant: Give me an example.","user: Last month the fee was posted twice."]);
  await h.api.stop({immediate:true});
 });
 await check("a line the application issues separates the next answer even before it is captioned",async()=>{
  const h=await live();
  h.user("That is everything I can tell you.",100,2000);
  h.step(6000); // the background capture has finished; the application issues its line 6 seconds into the session
  const receipt=h.api.say("Thank you. All sections are captured and you have confirmed the account.");
  h.user(" I think.",2000,2400); // a late fragment of the earlier answer: it started before the line
  assert.deepEqual(h.shown(),["user: That is everything I can tell you. I think."]);
  h.user("Thank you, bye.",6400,7400);
  assert.deepEqual(h.shown(),["user: That is everything I can tell you. I think.","user: Thank you, bye."],"Speech after the line never rewrites the answer before it");
  await h.api.stop({immediate:true});assert.equal((await receipt).status,"cancelled");
 });
 await check("listening cues, acknowledgements and pauses keep one answer, and its parts do not run together",async()=>{
  const h=await live();
  h.user("The invoice arrives by email.",10,1000);
  h.interviewer("I see.",300,600);
  h.user("Then we approve it.",4500,5500); // no leading space from the transcriber
  h.interviewer("Okay, thanks. Go ahead.",5600,6400);
  h.user("And we pay on Friday.",7000,8200);
  h.interviewer("Thank you, good to know.",8300,9000);
  h.user("Unless it is disputed",9400,10400);h.user(".",10400,10420);
  assert.deepEqual(h.shown().filter(line=>line.startsWith("user")),["user: The invoice arrives by email. Then we approve it. And we pay on Friday. Unless it is disputed."]);
  assert.equal(new Set(h.captions.filter(caption=>caption.role==="user").map(caption=>caption.id)).size,1);
  await h.api.stop({immediate:true});
 });
 await check("continuous speech is joined exactly as the transcriber sent it",async()=>{
  const h=await live();
  h.user("It is on the docu",100,900);h.user("mentation",900,1300);h.user(" site",1300,1600);h.user(".",1600,1620);
  h.user(" Version 2",2400,3000);h.user(".5 applies.",3000,3600);
  assert.deepEqual(h.shown(),["user: It is on the documentation site. Version 2.5 applies."]);
  h.interviewer("Mm-hmm.",3700,3900);h.interviewer("Right.",5200,5400); // a later cue without a leading space
  assert.equal(h.shown().at(-1),"assistant: Mm-hmm. Right.");
  await h.api.stop({immediate:true});
 });
 await check("sentences do not run together when the transcriber sends no pause, or no timestamps",async()=>{
  for(const times of [[[100,1000],[1100,2000],[2050,2600]],[[],[],[]]]){ // 100 ms and 50 ms apart; then no timeline at all
   const h=await live();
   h.user("The invoice arrives by email.",...times[0]);h.user("Then we approve it,",...times[1]);h.user("usually on Friday.",...times[2]);
   assert.deepEqual(h.shown(),["user: The invoice arrives by email. Then we approve it, usually on Friday."]);
   // What is not the start of a new word stays exactly as sent: decimals, initials, a web address, parts of a word.
   h.user(" It costs 2.",...times[0]);h.user("5 million in the U.",...times[1]);h.user("S.",...times[2]);
   h.user(" See example.",...times[0]);h.user("com for the docu",...times[1]);h.user("mentation.",...times[2]);
   assert.deepEqual(h.shown(),["user: The invoice arrives by email. Then we approve it, usually on Friday. It costs 2.5 million in the U.S. See example.com for the documentation."]);
   await h.api.stop({immediate:true});
  }
 });
 await check("text in a script written without spaces gains none at a pause",async()=>{
  const h=await live();
  h.user("我们先检查发票",100,900);h.user("然后付款。",1600,2400);h.user("好的",3200,3500);
  assert.deepEqual(h.shown(),["user: 我们先检查发票然后付款。好的"]);
  await h.api.stop({immediate:true});
 });
 await check("late punctuation stays with the answer it ends, whatever the interviewer has said since",async()=>{
  const h=await live();
  h.user("We log the invoice",100,900);
  h.interviewer("Got it, that makes sense.",850,1900); // a statement that began just before the answer's last fragment
  h.user(".",900,920);
  assert.deepEqual(h.shown(),["user: We log the invoice.","assistant: Got it, that makes sense."],"A full stop is never a turn of its own");
  h.user("Then we pay it.",2500,3400);
  assert.deepEqual(h.shown(),["user: We log the invoice.","assistant: Got it, that makes sense.","user: Then we pay it."]);
  // The same after a line the application issued.
  h.step(4000);void h.api.say("We will stop here and keep the unanswered parts open.");
  h.user("!",7600,7620);
  assert.equal(h.shown().at(-1),"user: Then we pay it.!");assert.equal(h.shown().length,3);
  await h.api.stop({immediate:true});
 });
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
