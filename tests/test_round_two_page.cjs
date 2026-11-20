"use strict";
// Page behaviour added on 2026-11-18: unreported step details on one line, spelling hints for a
// recording, and the head start for a draft at wrap-up. Runs the real app.js with the UI boundary
// stubbed as in test_report_route_notes.cjs. No network, model or microphone is used.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const source = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");
const sent = [];
const context = {console, window:{}, document:{getElementById:()=>({value:""})},
  fetch:(url,options)=>{sent.push({url,options});return Promise.resolve({ok:true,json:()=>Promise.resolve({prepared:true})});},
  setTimeout:()=>0, clearTimeout:()=>{}, AbortController, encodeURIComponent, crypto:{randomUUID:()=>"00000000-0000-4000-8000-000000000000"}};
const hook = `
  window.roundTwoTest={state,conversationUI,reportFieldRows,transcriptionHints,prepareDraftAhead,draftAhead,draftAheadReady,armDraftAhead,
    receiveLiveCaption,isInterviewerLine,turnCaption,quiet(){renderTranscript=()=>{};scheduleWorkflow=()=>{};scheduleLiveCapture=()=>{};participantEvidenceChanged=()=>{};suppressWorkflowReadiness=()=>{};},
    stub(){snapshot=()=>({context:state.context,turns:state.turns});captureForFollowup=()=>({workflow:{steps:[]}});usageHeaders=()=>({"X-Interview-Id":"i"});}};
})();`;
const patched = source.replace(/  init\(\);\s*\}\)\(\);\s*$/,hook);
assert.notEqual(patched,source,"Install a test hook only at the app's initialization boundary");
vm.createContext(context);
vm.runInContext(patched,context,{filename:"app.js"});
const app = context.window.roundTwoTest;
let checks = 0;

// ---- A step's unreported details are named once ----
{
  const rows=app.reportFieldRows([["Owner / role","AP analyst"],["System / tool","UNKNOWN"],["Input",""],["Output","unknown / tbd."],
    ["Completion criteria","Reviewer UNKNOWN; sign-off recorded"],["Handoff note","TBD"],["Entry mode",undefined]]);
  assert.deepEqual(JSON.parse(JSON.stringify(rows.shown)),[["Owner / role","AP analyst"],["Completion criteria","Reviewer UNKNOWN; sign-off recorded"]],
    "A value that says something stays a row, also when part of it is unknown");
  assert.deepEqual(JSON.parse(JSON.stringify(rows.missing)),["System / tool","Input","Output","Handoff note","Entry mode"]);
  assert.match(source,/"Not captured: "\+rows\.missing\.join\(", "\)/,"The report names them on one line");
  assert.match(fs.readFileSync(path.join(__dirname,"..","web","style.css"),"utf8"),/\.report-unstated \{[^}]*color: var\(--muted\)/);
  // The exports keep a line for each field.
  assert.match(source,/- Owner \/ role: \$\{md\(s\.actor\|\|"UNKNOWN \/ TBD"\)\}/);
  checks++;
}

// ---- Spelling hints come from the interview itself ----
{
  app.state.context={process_name:"Facility Compliance"};
  app.state.turns=[
    {id:"t1",role:"assistant",text:"What starts the work?"},
    {id:"t2",role:"user",text:"The AFC opens the Facility Tracker. Then Signatory A signs. We use FAN-SC-12 for it. Signatory A also checks the Facility Tracker."},
    {id:"t3",role:"user",document_event:true,text:"Uploaded Secret File Name.pdf"},
    {id:"t4",role:"user",text:"After that the AFC files it. Then nothing. Entrilia is where it lives, and Entrilia sends the notice."}];
  const hints=JSON.parse(JSON.stringify(app.transcriptionHints()));
  assert.equal(hints[0],"Facility Compliance","The process name comes first");
  for(const term of ["AFC","Signatory A","Facility Tracker","FAN-SC-12","Entrilia"])assert.ok(hints.includes(term),term+" is a hint");
  for(const word of ["The","Then","We","After","Secret File Name.pdf","Uploaded Secret File Name.pdf"])assert.ok(!hints.includes(word),word+" is not a hint");
  assert.ok(hints.length<=20&&hints.every(term=>term.length<=60&&!/[<>,]/.test(term)));
  // A process name too long to be a hint is left out; the terms of the answers still go.
  app.state.context={process_name:"Quarterly Facility Compliance Certificate Review and Borrowing Base Reconciliation"};
  const long=JSON.parse(JSON.stringify(app.transcriptionHints()));
  assert.ok(long.includes("Signatory A")&&long.includes("AFC")&&!long.some(term=>term.startsWith("Quarterly Facility")));
  app.state.turns=[];app.state.context={};
  assert.deepEqual(JSON.parse(JSON.stringify(app.transcriptionHints())),[]);
  assert.match(source,/headers\["X-Transcription-Hints"\]=encodeURIComponent\(hints\.join\(","\)\)/);
  // A live caption checked again leaves out its own turn (options.hintsExcept, see checkLiveCaption).
  assert.match(source,/path==="\/api\/transcribe"\?transcriptionHints\(options\.hintsExcept\):\[\]/,"Only a recording carries them");
  checks++;
}

// ---- What the live voice says only to show it is listening is not a question of its own ----
{
  app.quiet();
  app.state.turns=[];app.conversationUI.captions.clear();
  const say=(role,id,text)=>app.receiveLiveCaption({role,id,text,final:true});
  say("assistant","a1","What usually sets it in motion?");
  say("user","u1","The deal team sends the funding memo.");
  say("assistant","a2","Okay.");
  assert.equal(app.state.turns.length,3);
  assert.equal(app.isInterviewerLine(app.state.turns[2]),true,"A filler on its own is an interviewer line, not Question 2");
  say("assistant","a3","When you do that tie-out, what exactly are you comparing?");
  assert.equal(app.state.turns.length,3,"The question continues the filler's line");
  assert.equal(app.state.turns[2].text,"Okay. When you do that tie-out, what exactly are you comparing?");
  assert.equal(app.isInterviewerLine(app.state.turns[2]),false);
  say("assistant","a3","When you do that tie-out, what exactly are you comparing? Is it by investor?");
  assert.equal(app.state.turns[2].text,"Okay. When you do that tie-out, what exactly are you comparing? Is it by investor?","A caption that grows keeps its lead");
  assert.equal(app.state.turns.length,3);
  say("assistant","a2","Okay.");
  assert.equal(app.state.turns.length,3,"A late checkpoint of the filler's own caption adds no line");
  assert.equal(app.state.turns[2].text,"Okay. When you do that tie-out, what exactly are you comparing? Is it by investor?");
  // A filler after which the participant speaks stays where it is, and a real question is never merged.
  say("user","u2","By investor.");say("assistant","a4","Sure,");say("user","u3","And one more thing.");
  say("assistant","a5","Who signs off the notices?");say("assistant","a6","And where is that recorded?");
  assert.deepEqual(app.state.turns.slice(3).map(turn=>turn.text),["By investor.","Sure,","And one more thing.","Who signs off the notices?","And where is that recorded?"]);
  assert.equal(app.isInterviewerLine(app.state.turns[4]),true);
  assert.equal(app.isInterviewerLine({id:"x",role:"assistant",text:"Okay, who do you call at the bank?"}),false);
  assert.equal(app.isInterviewerLine({id:"y",role:"user",text:"Okay."}),false,"Only the interviewer's filler");
  // Breathing and laughter in the live voice's captions are not words.
  app.state.turns=[];app.conversationUI.captions.clear();
  say("assistant","b1","And when that approval is needed, [inhale] what does the finance manager look at?");
  assert.equal(app.state.turns[0].text,"And when that approval is needed, what does the finance manager look at?");
  say("assistant","b2","[laughs]");
  assert.equal(app.state.turns.length,1,"A caption that is only a sound adds nothing");
  say("user","b3","We file it under [pending] in the tracker.");
  assert.equal(app.state.turns[1].text,"We file it under [pending] in the tracker.","A participant's brackets are theirs");
  app.state.turns=[];app.conversationUI.captions.clear();
  checks++;
}

// ---- The first half of a draft is started when the participant wraps up ----
(async()=>{
  app.stub();
  const turns=[{id:"t1",role:"assistant",text:"What starts it?"},{id:"t2",role:"user",text:"An invoice arrives."},{id:"t3",role:"assistant",text:"Your account so far is saved."}];
  const ready=()=>{app.state.config={draft_prepare:true,csrf_token:"token"};app.state.example=false;app.state.turns=turns;app.state.generation=7;
    app.conversationUI.live=null;app.conversationUI.applied=app.conversationUI.revision=3;
    Object.assign(app.draftAhead,{generation:7,turns:turns.length,body:"",flight:false,ready:""});sent.length=0;};
  // Nothing is sent unless the participant has wrapped up, the map has caught up and the setting allows it.
  ready();app.state.config.draft_prepare=false;app.prepareDraftAhead();assert.equal(sent.length,0,"Off in the settings");
  ready();app.draftAhead.turns=turns.length-1;app.prepareDraftAhead();assert.equal(sent.length,0,"No wrap-up for this conversation");
  ready();app.draftAhead.generation=6;app.prepareDraftAhead();assert.equal(sent.length,0,"Another interview's wrap-up");
  ready();app.conversationUI.applied=2;app.prepareDraftAhead();assert.equal(sent.length,1,"It does not wait for a map that is still catching up");
  ready();app.state.example=true;app.prepareDraftAhead();assert.equal(sent.length,0,"Never for the example");
  ready();app.conversationUI.live={active:true};app.prepareDraftAhead();assert.equal(sent.length,0,"Not while live voice is on");
  ready();app.state.turns=[turns[0]];app.draftAhead.turns=1;app.prepareDraftAhead();assert.equal(sent.length,0,"Nothing has been answered");
  // Wrapped up and settled: one request, like Create draft's own, marked as the first half only.
  ready();app.prepareDraftAhead();
  assert.equal(sent.length,1);
  assert.equal(sent[0].url,"/api/draft");
  const body=JSON.parse(sent[0].options.body);
  assert.equal(body.prepare_only,true);
  assert.ok(body.previous_capture&&Array.isArray(body.turns),"It carries what Create draft sends");
  assert.equal(sent[0].options.headers["X-CSRF-Token"],"token");
  assert.equal(sent[0].options.headers["X-Interview-Id"],"i","Its tokens are counted for this interview");
  assert.equal(app.draftAheadReady(),false,"Not ready until the server says so");
  app.prepareDraftAhead();assert.equal(sent.length,1,"One request at a time");
  await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));
  assert.equal(app.draftAheadReady(),true,"The server kept the first half");
  app.prepareDraftAhead();assert.equal(sent.length,1,"The same account is not asked for twice");
  // Ready is a statement about the account as it stands and a first half the server still holds.
  app.state.context={process_name:"Renamed"};
  assert.equal(app.draftAheadReady(),false,"A renamed process is another account");
  app.state.context={};
  app.draftAhead.readyAt=Date.now()-16*60*1000;
  assert.equal(app.draftAheadReady(),false,"The server no longer keeps a first half that old");
  app.draftAhead.readyAt=Date.now();
  assert.equal(app.draftAheadReady(),true);
  app.state.turns=[...turns,{id:"t4",role:"user",text:"One more thing."}];
  assert.equal(app.draftAheadReady(),false,"A further answer makes it another account");
  ready();app.conversationUI.workflowCheckPending=true;app.prepareDraftAhead();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(app.draftAheadReady(),true);
  app.conversationUI.workflowCheckPending=false;
  assert.equal(app.draftAheadReady(),false,"An identical map can now use the checked draft path");
  app.prepareDraftAhead();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(sent.length,2);
  assert.equal(app.draftAheadReady(),true);
  // While the final check waits for its answer nothing is started; once it is confirmed, it is.
  ready();app.draftAhead.turns=-1;app.state.closure={asked:true,confirmed:false};app.armDraftAhead();
  assert.equal(sent.length,0,"The account is about to grow by the answer to the final check");
  app.state.closure={asked:true,confirmed:true};app.armDraftAhead();
  assert.equal(sent.length,1,"A confirmed account gets its head start");
  app.state.closure={asked:false,confirmed:false};
  await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));
  assert.match(source,/draftAheadReady\(\)\?"Checking your draft against your answers · usually 1 to 2 minutes":"Building your draft · usually 2 to 5 minutes"/);
  assert.match(source,/if\(replied&&generation===state\.generation\)armDraftAhead\(\);/,"Wrap up starts it");
  assert.match(source,/if\(state\.closure\?\.confirmed\)armDraftAhead\(\);/,"So does the answer to the final check");
  assert.match(source,/draftAhead\.ready="";draftAhead\.body="";/,"Create draft uses the first half up");
  assert.match(source,/if\(current\)prepareDraftAhead\(\);/,"So does the map catching up afterwards");
  assert.match(source,/conversationUI\.flowErrorNotified=false;\s*\/\/ The map of a spoken interview becomes current here[^\n]*\n\s*prepareDraftAhead\(\);/,
    "And the map of a spoken interview, which is applied elsewhere");
  checks++;
  console.log(JSON.stringify({suite:"round-two page behaviour",passed:checks}));
})().catch(error=>{console.error(error);process.exit(1);});
