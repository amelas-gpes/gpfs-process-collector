"use strict";
// While Dictate records, nothing on the page may prompt a screen reader to speak: its speech would
// talk over the participant and be picked up by the open microphone. The recording line is shipped
// markup (web/index.html) driven by the real startRecording of web/app.js, run in the page of
// tests/fixtures/interview_form_page.cjs with a stand-in microphone, recorder and clock. No browser, audio
// device, provider, package or network.
const assert=require("node:assert/strict");
const {openPage,standInMicrophone}=require("./fixtures/interview_form_page.cjs");
let checks=0;
async function check(name,fn){try{await fn();checks++;}catch(error){error.message=name+": "+error.message;throw error;}}

// What makes assistive technology announce a change inside an element.
const announces=node=>["status","alert","log"].includes(node.getAttribute("role"))||["polite","assertive"].includes(node.getAttribute("aria-live"));
const announcingAncestor=node=>{for(let parent=node.parentElement;parent;parent=parent.parentElement)if(announces(parent)&&parent.getAttribute("aria-live")!=="off")return parent;return null;};

async function dictating(){
 const microphone=standInMicrophone(),{recorders,tracks}=microphone,posts=[];
 const page=await openPage({expose:["state","conversationUI"],globals:microphone.globals,
  fetch:async(url,init)=>{
   posts.push(url);
   if(url==="/api/interview")return {ok:true,status:200,json:async()=>({question:"What starts the work?"})};
   if(url==="/api/transcribe"){assert.ok(init.body instanceof Blob);return {ok:true,status:200,json:async()=>({text:"An email from the supplier."})};}
   throw new Error("Unexpected request: "+url);
  }});
 page.$("type-instead").click();await page.settle();
 assert.equal(page.$("record-answer").disabled,false,"Dictate is offered once the interview has a question");
 page.$("record-answer").click();await page.settle();
 assert.ok(page.app.state.recording,"The stand-in microphone is recording");
 assert.equal([...page.intervals.values()].filter(timer=>timer.delay===200).length,1,"One clock runs while recording");
 const tick=[...page.intervals.values()].find(timer=>timer.delay===200);
 assert.equal(tick.delay,200);
 return {page,recorders,tracks,posts,
  // Lets the given time pass, running the clock's interval as a browser would every 200 ms.
  pass(milliseconds){for(let elapsed=0;elapsed<milliseconds&&[...page.intervals.values()].filter(timer=>timer.delay===200).length;elapsed+=200){microphone.clock+=200;tick.fn();}}};
}

(async()=>{
 await check("the recording line is not a live region, and neither its clock nor Discard sits in one",async()=>{
  const {page}=await dictating();
  const line=page.$("recording-status"),time=page.$("recording-time"),discard=page.$("cancel-recording");
  assert.equal(line.shown,true);assert.equal(line.contains(time),true);
  assert.equal(announces(line),false,"The line that holds the running clock must not announce its changes");
  assert.equal(announcingAncestor(time),null,"No region around the clock announces it");
  assert.equal(announcingAncestor(discard),null,"The Discard button is not part of any announcement");
  assert.ok(time.getAttribute("aria-hidden")==="true"||(time.getAttribute("role")==="timer"&&time.getAttribute("aria-live")==="off"),
   "The clock is hidden from assistive technology or is a timer that is never announced");
  assert.equal(announces(page.$("recording-label")),false,"The label changes while the microphone is open");
  assert.equal(discard.tagName,"BUTTON");assert.equal(discard.textContent,"Discard");assert.equal(discard.shown,true);
 });

 await check("the start of a recording is said once; the clock is written once a second and never said",async()=>{
  const {page,pass}=await dictating();
  const status=page.$("live-status"),time=page.$("recording-time");
  assert.equal(status.textContent,"Recording your answer. Select Finish to stop.");
  assert.equal(time.textContent,"0:00");
  const statusWrites=status.writes,timeWrites=time.writes,seen=[];
  for(let step=0;step<22;step++){pass(200);seen.push(time.textContent);}
  assert.deepEqual([...new Set(seen)],["0:00","0:01","0:02","0:03","0:04"]);
  assert.equal(time.writes-timeWrites,4,"4.4 seconds of recording change the clock four times");
  pass(60000);
  assert.equal(time.textContent,"1:04");assert.equal(time.writes-timeWrites,64);
  assert.equal(status.writes,statusWrites,"Nothing is announced while the microphone is open");
  assert.equal(page.$("recording-label").textContent,"Listening · finish when you’re ready");
  assert.ok(page.app.state.recording,"Still recording");
 });

 await check("the 90-second limit still ends the recording and the words reach the reply box",async()=>{
  const {page,pass,recorders,tracks,posts}=await dictating();
  pass(89800);
  assert.equal(recorders[0].state,"recording");assert.equal(page.$("recording-time").textContent,"1:29");
  pass(200);
  assert.equal(page.$("recording-time").textContent,"1:30");
  assert.equal(recorders[0].state,"inactive","The recorder is stopped at 90 seconds");
  assert.match(page.$("notice-text").textContent,/^That’s 90 seconds/);
  assert.equal([...page.intervals.values()].filter(timer=>timer.delay===200).length,0,"The clock stops with the recording");
  await page.settle();
  assert.equal(tracks.every(track=>track.stopped),true,"The microphone is released");
  assert.deepEqual(posts,["/api/interview","/api/transcribe"]);
  assert.equal(page.$("answer-text").value,"An email from the supplier.");
  assert.equal(page.$("recording-status").shown,false);
 });

 await check("Discard ends the recording without sending it anywhere",async()=>{
  const {page,pass,recorders,tracks,posts}=await dictating();
  pass(3000);
  page.$("cancel-recording").click();await page.settle();
  assert.equal(recorders[0].state,"inactive");assert.equal(tracks.every(track=>track.stopped),true);
  assert.equal(page.app.state.recording,null);assert.equal([...page.intervals.values()].filter(timer=>timer.delay===200).length,0);
  assert.deepEqual(posts,["/api/interview"],"A discarded recording is not transcribed");
  assert.equal(page.$("answer-text").value,"");assert.equal(page.$("recording-status").shown,false);
 });

 console.log(JSON.stringify({checks_passed:checks,provider_calls:0,network_calls:0,physical_audio:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
