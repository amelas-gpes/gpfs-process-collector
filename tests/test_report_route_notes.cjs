"use strict";
// What the report and the Markdown export say about routes and about parts without sources.
// Runs the real app.js exporter against the built-in fictional example, with the UI boundary
// stubbed as in test_example_complete.cjs. No network, model or microphone is used.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const source = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");
const context = {console, window:{}, document:{getElementById:()=>({value:""})},
  fetch:()=>{throw new Error("This suite must not contact a provider.");},
  setTimeout:()=>0, clearTimeout:()=>{}, AbortController};
const hook = `
  canReplaceSession=()=>true;
  clearState=(context)=>{state.context=context;state.turns=[];state.draft=null;state.version=0;state.closure={asked:false,confirmed:false};state.parking_lot=[];};
  renderWorkingMap=()=>{}; renderTranscript=()=>{}; renderDraft=()=>{}; scrollConversation=()=>{}; notice=()=>{};
  window.routeNotesTest={loadExample,state,normalizeDraft,markdown,escapeMarkdown,draftRoutes,routedHandoff,handoffNoteMismatch,unrecordedEntryRules,UNCITED_OVERVIEW_NOTE,UNCITED_ITEMS_NOTE};
})();`;
const patched = source.replace(/  init\(\);\s*\}\)\(\);\s*$/,hook);
assert.notEqual(patched,source,"Install a test hook only at the app's initialization boundary");
vm.createContext(context);
vm.runInContext(patched,context,{filename:"app.js"});
const app = context.window.routeNotesTest;
let checks = 0;
const step = (id,title,type="activity",handoff="UNKNOWN / TBD") => ({id,title,type,handoff});
const route = (from,to,label="") => ({from,to,label,evidence_turns:["u1"]});

// ---- Next handoff comes from the map's outgoing routes ----
{
  const draft={steps:[step("S1","Receive invoice"),step("S2","Approve or reject invoice","decision"),step("S3","Pay invoice"),
    step("S4","Return to supplier"),step("S5","Close case","end"),step("S6","Archive file")],
    connections:[route("S1","S2"),route("S2","S3","Approved"),route("S2","S4","Rejected"),route("S3","S5"),route("S9","S1"),route("S1","S9")]};
  const routes=app.draftRoutes(draft),by=id=>draft.steps.find(item=>item.id===id);
  assert.equal(app.routedHandoff(routes,by("S1")),"S2 Approve or reject invoice [Source check unknown]");
  assert.equal(app.routedHandoff(routes,by("S2")),"S3 Pay invoice (Approved) [Source check unknown]; S4 Return to supplier (Rejected) [Source check unknown]");
  assert.equal(app.routedHandoff(routes,by("S3")),"S5 Close case [Source check unknown]");
  assert.match(app.routedHandoff(routes,by("S5")),/ends here/,"An end step with no route is an ending, not a gap");
  assert.match(app.routedHandoff(routes,by("S6")),/No route from this step is recorded/);
  assert.doesNotMatch(app.routedHandoff(routes,by("S1")),/S9/,"A route to a step that does not exist is not a handoff");
  checks++;
}

// ---- A handoff note that names a step the map does not route to ----
{
  const steps=[step("S1","Receive invoice"),step("S2","Approve or reject invoice","decision"),step("S3","Pay invoice"),
    step("S4","Return to supplier"),step("S30","Review"),step("S5","File")];
  const draft={steps,connections:[route("S1","S2"),route("S2","S4","Rejected")]};
  const routes=app.draftRoutes(draft);
  const check=(note,id="S2")=>app.handoffNoteMismatch(routes,{...steps.find(item=>item.id===id),handoff:note});
  // The audit's case: the note promises S3 and S4, the map routes to S4 only.
  assert.equal(check("S3 Pay invoice if approved; S4 Return to supplier if rejected"),
    "The handoff note names S3, but the map has no route from S2 to that step.");
  assert.equal(check("S4 Return to supplier if rejected"),"","A note that names only real targets needs no warning");
  assert.equal(check("Back to S2 after the correction"),"","A step's own ID is not a missing route");
  assert.equal(check("Then S30 takes over"),"The handoff note names S30, but the map has no route from S2 to that step.");
  assert.equal(check("Goes on to S3, or to S1 when rework is needed"),
    "The handoff note names S1, S3, but the map has no route from S2 to those steps.","Steps are listed in map order");
  assert.equal(check("Step S300 in the other process"),"","S3 and S30 are not named by S300");
  assert.equal(check("See MS3-sheet"),"","An ID inside another word is not named");
  // By title: a whole title of two or more words, whatever its letter case.
  assert.equal(check("The clerk will pay invoice the next morning"),
    "The handoff note names S3, but the map has no route from S2 to that step.");
  assert.equal(check("Supplier may repay invoices later"),"","Part of another word is not the title");
  assert.equal(check("Sent for review, then on file"),"","A one-word title is too generic to count as naming a step");
  assert.equal(check("return to supplier when rejected"),"","Naming a real target by its title needs no warning");
  for(const note of ["UNKNOWN / TBD","","Approval goes to AP; rejection goes to correction"])assert.equal(check(note),"");
  assert.equal(app.handoffNoteMismatch(routes,{id:"S1",title:"Receive invoice"}),"","A step without a note has nothing to check");
  checks++;
}

// ---- A step with several incoming routes whose entry rule the map does not record ----
{
  const draft={steps:[step("S4","Supervisor approval"),step("S5","Controller approval"),step("S6","Export and upload payment file"),
    step("S7","Merge point","merge"),step("S8","Wait for both","parallel_join"),step("S9","Check amount","decision"),step("S10","Correct invoice")],
    connections:[route("S4","S6","Supervisor approval complete"),route("S5","S6","Controller approval complete"),
      route("S4","S7"),route("S5","S7"),route("S4","S8"),route("S5","S8"),
      route("S9","S10","Too high"),route("S9","S10","Too low"),route("S6","S9"),route("S10","S9","Corrected")]};
  const notes=app.unrecordedEntryRules(app.draftRoutes(draft));
  assert.equal(notes.length,2,JSON.stringify(notes));
  assert.match(notes[0],/^S6 Export and upload payment file has incoming routes from S4 and S5\b/);
  assert.match(notes[0],/does not record whether all of them are required or any one is enough/);
  assert.match(notes[1],/^S9 Check amount has incoming routes from S6 and S10\b/,"A return route is a second entry too");
  assert.ok(!notes.some(note=>/^S7 |^S8 /.test(note)),"A merge or a parallel join states its own entry rule");
  assert.ok(!notes.some(note=>/^S10 /.test(note)),"Two branches of one decision are one source");
  assert.deepEqual(Array.from(app.unrecordedEntryRules(app.draftRoutes({steps:draft.steps,connections:[route("S4","S6")]}))),[]);
  const three=app.unrecordedEntryRules(app.draftRoutes({steps:draft.steps,connections:[route("S4","S6"),route("S5","S6"),route("S10","S6")]}));
  assert.match(three[0],/from S4, S5 and S10\b/);
  checks++;
}

// ---- The Markdown export ----
app.loadExample();
const {state}=app, md=app.escapeMarkdown;
{
  const draft=state.draft, clean=app.markdown();
  const routes=app.draftRoutes(draft);
  for(const item of draft.steps){
    assert.ok(clean.includes(`- Next handoff: ${md(app.routedHandoff(routes,item))}`),`${item.id}: the handoff shown is the map's`);
    assert.ok(clean.includes(`- Handoff note: ${md(item.handoff)}`),`${item.id}: the participant's wording is kept as a note`);
  }
  assert.doesNotMatch(clean,/- Handoff check:/,"The example's notes name no step that its map does not route to");
  // Parts of the draft that carry no source links say so.
  assert.ok(clean.includes(`## Overview\n\n_${app.UNCITED_OVERVIEW_NOTE}_`));
  for(const heading of ["Trigger","Inputs","Outputs","Exceptions","Controls"])
    assert.match(clean.split("## "+heading+"\n")[1].split("\n## ")[0],/No cited source/);
  for(const heading of ["Procedure","Process connections","Topic notes","Open questions"])
    assert.ok(!clean.includes(`## ${heading}\n\n_${app.UNCITED_ITEMS_NOTE}_`),`${heading} is cited or is not a claim`);
  assert.match(app.UNCITED_ITEMS_NOTE,/no source links/i);assert.match(app.UNCITED_OVERVIEW_NOTE,/without source links/i);
  checks++;

  const first=draft.steps[0],target=routes.out.get(first.id)?.[0]?.to;
  const stranger=draft.steps.find(item=>item.id!==first.id&&!(routes.out.get(first.id)||[]).some(c=>c.to===item.id));
  assert.ok(target&&stranger,"The example has a first step with a route and a step it does not route to");
  const original=first.handoff;
  first.handoff=`${stranger.id} takes it from here`;
  assert.ok(app.markdown().includes(`- Handoff check: ${md(`The handoff note names ${stranger.id}, but the map has no route from ${first.id} to that step.`)}`));
  first.handoff=original;
  checks++;

  // An empty list has nothing to caveat.
  const controls=draft.controls;draft.controls=[];
  assert.ok(!app.markdown().includes(`## Controls\n\n_${app.UNCITED_ITEMS_NOTE}_`));
  draft.controls=controls;

  // Entry rules: listed under the connections when a step has several sources.
  const before=app.unrecordedEntryRules(routes);
  const section=text=>text.split("## Step routes")[1].split("## Item lifecycles")[0];
  for(const note of before)assert.ok(section(clean).includes(`- ${md(note)}`));
  if(!before.length)assert.doesNotMatch(section(clean),/Entry rules not recorded/);
  const ordinary=draft.steps.filter(item=>!["merge","parallel_join"].includes(item.type));
  const [a,b,c]=ordinary;
  const saved=draft.connections;
  draft.connections=[{from:a.id,to:c.id,label:"First approval complete",evidence_turns:["t002"]},{from:b.id,to:c.id,label:"Second approval complete",evidence_turns:["t002"]}];
  const joined=section(app.markdown());
  assert.match(joined,/### Entry rules not recorded/);
  assert.ok(joined.includes(md(`${c.id} ${c.title} has incoming routes from ${a.id} and ${b.id}`)));
  draft.connections=saved;
  checks++;
}
{
  const state=app.state,turn={id:"op1",role:"user",text:"Operations enters the amount each week in the Ledger. Finance is informed by email."};
  const make=(field,text)=>({field,text,evidence_turns:["op1"]});
  const draft=JSON.parse(JSON.stringify(state.draft));
  draft.steps[0].evidence_turns.push("op1");
  draft.steps[0].operating_details=[make("frequency","each week"),make("system","Ledger"),make("responsible","Operations enters the amount"),make("informed","Finance is informed by email")];
  const turns=state.turns.concat(turn);
  state.draft=app.normalizeDraft(draft,turns,[]);
  const exported=app.markdown();
  assert.match(exported,/Frequency: each week \(Sources: op1\)/);
  assert.match(exported,/Reported role assignments \(RACI\)/);
  assert.match(exported,/Operations enters the amount \(op1\) \| — \| — \| Finance is informed by email \(op1\)/);
  draft.steps[0].operating_details=[make("accountable","The controller approves")];
  assert.throws(()=>app.normalizeDraft(draft,turns,[]),/cited source/);
  draft.steps[0].operating_details=[make("system","edge")];
  assert.throws(()=>app.normalizeDraft(draft,turns,[]),/cited source/);
  checks++;
}
console.log(JSON.stringify({checks_passed:checks}));
