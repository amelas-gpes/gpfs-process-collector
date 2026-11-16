"use strict";
// A question that is read aloud while typing must show that it is playing, and offer a way to stop
// it, where the participant is: on the question itself and above the reply box, not only inside the
// Settings dialog. Escape stops it too. The real web/app.js runs against the real web/index.html in
// the page of tests/fixtures/interview_form_page.cjs with a stand-in installed voice (and, for the AI voice, a
// voice session that never arrives). No browser, audio device, provider, package or network.
const assert=require("node:assert/strict");
const {openPage}=require("./fixtures/interview_form_page.cjs");
const VOICE={name:"Test voice",lang:"en-US",voiceURI:"synthetic-voice",localService:true};
let checks=0;
async function check(name,fn){try{await fn();checks++;}catch(error){error.message=name+": "+error.message;throw error;}}

async function open(options={}){
 const posts=[];let cancels=0,questions=0;
 const page=await openPage({expose:["state","conversationUI","selectConversationView"],voices:[VOICE],...options,
  fetch:async url=>{
   posts.push(url);
   if(url==="/api/interview")return {ok:true,status:200,json:async()=>({question:["What starts the work?","Who reads that email first?","What do they check?"][questions++]})};
   if(url==="/api/voice-session")return new Promise(()=>{}); // a reader that never answers
   throw new Error("Unexpected request: "+url);
  }});
 const synthesis=page.window.speechSynthesis,cancel=synthesis.cancel;
 synthesis.cancel=()=>{cancels++;cancel();};
 const button=id=>page.$("turn-"+id).querySelector(".play-turn");
 return {page,posts,button,cancels:()=>cancels,
  line:page.$("speech-status"),lineText:()=>page.$("speech-status-text").textContent,
  async typeInstead(){page.$("type-instead").click();await page.settle();},
  async answer(text){page.$("answer-text").value=text;page.fire(page.$("answer-text"),"input");page.fire(page.$("answer-form"),"submit");await page.settle();}};
}
// An interview with two questions on screen and nothing playing.
async function twoQuestions(options){
 const t=await open(options);
 await t.typeInstead();await t.answer("An email from the supplier arrives.");
 assert.equal(t.page.app.state.turns.map(turn=>turn.id).join(),"t001,t002,t003");
 return t;
}

(async()=>{
 await check("the playback line and its Stop button ship above the reply box, outside Settings",async()=>{
  const {page,line}=await open();
  const dock=page.$("conversation-dock"),stop=page.$("stop-reading");
  assert.equal(dock.contains(line),true);assert.equal(page.$("interview-settings").contains(line),false);
  assert.equal(line.contains(stop),true);assert.equal(stop.tagName,"BUTTON");assert.equal(stop.getAttribute("type"),"button");
  assert.equal(stop.textContent,"Stop reading");
  assert.equal(line.hidden,true,"Nothing is playing when the page opens");
  // Preview voice keeps its own controls in Settings.
  assert.equal(page.$("interview-settings").contains(page.$("stop-speaking")),true);
  assert.equal(page.$("interview-settings").contains(page.$("voice-status")),true);
 });

 await check("read aloud while typing: the new question shows Stop and the state, on the interview screen",async()=>{
  const t=await open(),{page}=t;
  page.$("speak-questions").checked=true;
  await t.typeInstead();
  assert.equal(page.spoken.length,1);assert.equal(page.spoken[0].text,"What starts the work?");
  assert.equal(page.$("interview-settings").open,false,"Settings is closed");
  assert.equal(t.line.shown,true,"The playback line is on screen");
  assert.equal(t.lineText(),"Preparing voice…");
  assert.equal(page.$("stop-reading").shown,true);
  const play=t.button("t001");
  assert.equal(play.textContent,"Stop");assert.equal(play.getAttribute("aria-label"),"Stop reading Question 1 aloud");
  page.spoken[0].onstart();
  assert.equal(t.lineText(),"Speaking");assert.equal(play.textContent,"Stop");
  // The same button stops the voice and becomes Listen again.
  const before=t.cancels();
  play.click();
  assert.ok(t.cancels()>before,"The voice is silenced");
  assert.equal(page.app.state.utterance,null);
  assert.equal(play.textContent,"Listen");assert.equal(play.getAttribute("aria-label"),"Listen to Question 1 using the selected voice");
  assert.equal(t.line.shown,false);
  assert.equal(page.spoken.length,1,"Stopping does not start it again");
  // The next question is read in turn, and typing an answer silences the one before.
  play.click();assert.equal(page.spoken.length,2);
  await t.answer("An email from the supplier arrives.");
  assert.equal(page.spoken.length,3);assert.equal(page.spoken[2].text,"Who reads that email first?");
  assert.equal(t.button("t001").textContent,"Listen");assert.equal(t.button("t003").textContent,"Stop");
  assert.equal(t.line.shown,true);
 });

 await check("Listen: one question plays at a time, and the end of playback restores the button",async()=>{
  const t=await twoQuestions(),{page}=t;
  assert.equal(page.spoken.length,0,"Read aloud is off by default");assert.equal(t.line.shown,false);
  t.button("t001").click();
  assert.equal(page.spoken.at(-1).text,"What starts the work?");
  assert.equal(t.button("t001").textContent,"Stop");assert.equal(t.button("t003").textContent,"Listen");
  t.button("t003").click();
  assert.equal(page.spoken.at(-1).text,"Who reads that email first?");
  assert.equal(t.button("t001").textContent,"Listen");assert.equal(t.button("t003").textContent,"Stop");
  assert.equal(t.button("t003").getAttribute("aria-label"),"Stop reading Question 2 aloud");
  page.spoken.at(-1).onstart();assert.equal(t.lineText(),"Speaking");
  page.spoken.at(-1).onend();
  assert.equal(t.button("t003").textContent,"Listen");assert.equal(t.line.shown,false);assert.equal(t.lineText(),"");
  // A superseded utterance that ends late must not touch the one that is playing now.
  t.button("t001").click();const first=page.spoken.at(-1);
  t.button("t003").click();
  first.onend();
  assert.equal(t.button("t003").textContent,"Stop");assert.equal(t.line.shown,true);
 });

 await check("Stop reading above the reply box stops it and hands focus to the reply box",async()=>{
  const t=await twoQuestions(),{page}=t;
  t.button("t003").click();page.spoken.at(-1).onstart();
  const stop=page.$("stop-reading"),before=t.cancels();
  stop.focus();assert.equal(page.document.activeElement,stop);
  stop.click();
  assert.ok(t.cancels()>before);assert.equal(t.line.shown,false);assert.equal(t.button("t003").textContent,"Listen");
  assert.equal(page.document.activeElement,page.$("answer-text"),"Focus does not fall off the page with the button");
  // In the Voice view the transcript rows are out of sight; the line travels with the reply box.
  page.app.selectConversationView("voice");
  t.button("t003").click();
  assert.equal(page.$("voice-panel").contains(t.line),true);assert.equal(t.line.shown,true);
  page.$("stop-reading").click();assert.equal(t.line.shown,false);
 });

 await check("Escape stops a question that is being read, and nothing else",async()=>{
  const t=await twoQuestions(),{page}=t;
  const version=page.app.state.speechVersion;
  page.fire(page.$("answer-text"),"keydown",{key:"Escape"});
  assert.equal(page.app.state.speechVersion,version,"With nothing playing Escape does not touch the voice");
  t.button("t003").click();page.spoken.at(-1).onstart();
  page.fire(page.$("answer-text"),"keydown",{key:"Enter"});
  assert.equal(t.button("t003").textContent,"Stop","Another key leaves it playing");
  const before=t.cancels();
  page.fire(page.$("answer-text"),"keydown",{key:"Escape"});
  assert.ok(t.cancels()>before);assert.equal(page.app.state.utterance,null);
  assert.equal(t.button("t003").textContent,"Listen");assert.equal(t.line.shown,false);
  // The interviewer's own voice in a reviewed conversation is not a question read by Listen:
  // Escape leaves it to Stop talking.
  const operation={controller:new AbortController(),timer:null,socket:null,audio:null,url:null};
  page.app.state.speechOperation=operation;
  page.fire(page.document.body,"keydown",{key:"Escape"});
  assert.equal(operation.controller.signal.aborted,false);assert.equal(page.app.state.speechOperation,operation);
  page.app.state.speechOperation=null;
 });

 await check("AI voice: the wait for the voice is visible and can be stopped",async()=>{
  const t=await twoQuestions({globals:{WebSocket:class{}},
   config:{speech:{enabled:true,default_voice:"marin",voices:[{id:"marin",label:"Marin",description:"Synthetic"}]}}}),{page}=t;
  assert.equal(page.app.state.voiceChoice,"ai:marin");
  t.button("t003").click();await page.settle();
  assert.deepEqual(t.posts.filter(url=>url==="/api/voice-session").length,1);
  assert.equal(t.line.shown,true);assert.equal(t.lineText(),"Preparing voice…");
  assert.equal(t.button("t003").textContent,"Stop");
  assert.equal(page.$("live-status").textContent,"Preparing voice…","The wait is said once");
  const operation=page.app.state.speechOperation;assert.ok(operation);
  page.fire(page.document.body,"keydown",{key:"Escape"});
  assert.equal(operation.controller.signal.aborted,true,"The request for the voice is abandoned");
  assert.equal(page.app.state.speechOperation,null);
  assert.equal(t.line.shown,false);assert.equal(t.button("t003").textContent,"Listen");
 });

 console.log(JSON.stringify({checks_passed:checks,provider_calls:0,network_calls:0,physical_audio:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
