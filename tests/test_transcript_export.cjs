"use strict";
// Execute the real local exporters at the initialization boundary. No provider,
// browser, microphone, playback or live-controller code is invoked.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");
const plain = value => JSON.parse(JSON.stringify(value));
let passed = 0, providerCalls = 0;

function harness() {
  const nodes = new Map(Object.entries({
    "process-name":"DOM process", "process-owner":"DOM owner", objective:"DOM objective",
    background:"DOM background", "answer-text":"PRIVATE_UNSENT_SENTINEL"
  }).map(([key,value]) => [key,{value}]));
  const downloads = [], notices = [];
  let menuCloses = 0;
  const scope = {
    console, window:{}, document:{getElementById:id => nodes.get(id)||{value:""}},
    fetch:() => {providerCalls++; throw Error("Transcript export must stay local.");},
    setTimeout:() => 0, clearTimeout:() => {}, AbortController,
    captureDownload:(...args) => downloads.push(args), captureNotice:(...args) => notices.push(args),
    captureClose:() => menuCloses++
  };
  const hook = `
    download=(...args)=>captureDownload(...args);
    notice=(...args)=>captureNotice(...args);
    closeMenu=()=>captureClose();
    window.exportTest={state,conversationUI,TOPICS,normalizeFindings,transcriptObject,transcriptMarkdown,exportTranscript,
      setDocuments:value=>{documentController=value;},setKnowledge:value=>{knowledgeUI=value;}};
  })();`;
  const patched = source.replace(/  init\(\);\s*\}\)\(\);\s*$/,hook);
  assert.notEqual(patched,source,"Install a test hook only at application initialization");
  vm.createContext(scope); vm.runInContext(patched,scope,{filename:"app.js"});
  const app = scope.window.exportTest;
  app.state.context = {process_name:"Approval / handoff",process_owner:"Operations manager",
    objective:"Understand actual work",background:"Fictional interview context"};
  app.state.turns = [{id:"t001",role:"assistant",text:"How does the process start?"},
    {id:"t002",role:"user",text:"The analyst receives a completed request and records it."}];
  app.state.config = {version:"test-version",api_configured:false};
  return {app,nodes,downloads,notices,get menuCloses(){return menuCloses;}};
}
function check(name,fn) {try {fn();passed++;} catch(error) {error.message=name+": "+error.message;throw error;}}
function textBlocks(markdown) {
  return [...markdown.matchAll(/^(`{3,})text\n([\s\S]*?)\n\1(?=\n|$)/gm)].map(match => match[2]);
}

check("available before a draft and without a configured provider",() => {
  const {app} = harness(), data = app.transcriptObject();
  assert.equal(app.state.draft,null);
  assert.equal(data.format,"ai-process-collector-transcript");assert.equal(data.schema_version,1);
  assert.equal(new Date(data.exported_at).toISOString(),data.exported_at);
  assert.deepEqual(plain(data.process),{name:"Approval / handoff",owner_role:"Operations manager",objective:"Understand actual work",background:"Fictional interview context"});
  assert.equal(data.synthetic_example,false);
  assert.equal(data.capture.in_progress,false);
  assert.deepEqual(plain(data.counts),{messages:2,interviewer_messages:1,participant_messages:1,file_updates:0});
  assert.equal(data.turns[0].text,"How does the process start?");
  assert.equal(providerCalls,0);
});

check("chronology, attribution and file questions are preserved",() => {
  const {app} = harness();
  app.state.turns.push({id:"file_received",role:"assistant",text:"Received routing.csv.",document_event:true,document_id:"doc_routing"},
    {id:"file_question",role:"assistant",text:"Why did you upload the routing reference?",document_id:"doc_routing"},
    {id:"t005",role:"user",text:"It shows the handoff I just mentioned."});
  const data = app.transcriptObject();
  assert.deepEqual(plain(data.turns).map(t=>[t.sequence,t.id,t.role,t.text]),app.state.turns.map((t,i)=>[i+1,t.id,t.role,t.text]));
  assert.equal(data.turns[2].kind,"document_context");assert.equal(data.turns[2].speaker,"File context update");
  assert.equal(data.turns[2].document_id,"doc_routing");
  assert.equal(data.turns[3].kind,"interview_message");assert.equal(data.turns[3].speaker,"AI interviewer");
  assert.equal(data.turns[4].speaker,"Process participant");
  assert.deepEqual(plain(data.counts),{messages:5,interviewer_messages:2,participant_messages:2,file_updates:1});
});

check("all memo topics remain visible when no assessment exists",() => {
  const {app} = harness();
  app.state.coverage=app.TOPICS.map(([key])=>({key,status:"covered"}));
  const data=app.transcriptObject();
  assert.equal(data.memo.topics.length,11);assert.equal(data.memo.all_topics_captured,false);
  assert.deepEqual(plain(data.memo.topics).map(t=>t.key),plain(app.TOPICS).map(([key])=>key));
  for(const topic of data.memo.topics){assert.equal(topic.status,"unknown");assert.equal(typeof topic.label,"string");assert.ok(topic.guide.length>5);assert.deepEqual(plain(topic.evidence_turn_ids),[]);}
  assert.deepEqual(plain(data.memo.closure),{asked:false,confirmed:false});
});

check("memo capture and participant confirmation remain separate",() => {
  const {app}=harness();
  const findings=app.TOPICS.map(([key])=>({key,status:key==="variations"?"not_applicable":"captured",answer:key==="variations"?"There are no variations in this scope.":"The participant supplied a definite account.",evidence_turns:["t002"]}));
  app.state.memo_findings=app.normalizeFindings(findings,app.state.turns);
  app.state.draft={memo_summary:[{key:"trigger",status:"unknown",answer:"Different reviewer edit"}],open_questions:[]};
  let data=app.transcriptObject();assert.equal(data.memo.all_topics_captured,true);assert.equal(data.memo.closure.confirmed,false);
  assert.equal(data.memo.topics.find(t=>t.key==="trigger").status,"captured","Live memo findings, not edited draft findings, are exported");
  assert.equal(data.memo.topics.find(t=>t.key==="variations").status,"not_applicable");
  app.state.closure={asked:true,confirmed:true};data=app.transcriptObject();assert.equal(data.memo.closure.confirmed,true);
  app.state.turns[1].text="I think the analyst receives the request; I am not sure who owns the handoff.";
  app.state.memo_findings=app.normalizeFindings(findings,app.state.turns);
  data=app.transcriptObject();assert.equal(data.memo.all_topics_captured,false);
  assert.ok(data.memo.topics.every(t=>t.status==="partial"));
  assert.equal(data.memo.closure.confirmed,true,"A reported confirmation must not erase unresolved evidence");
});

check("current notes and stale draft questions are carried without truncation",() => {
  const {app}=harness();
  app.state.summary="Latest working summary";app.state.focus="Clarify who accepts the handoff";
  app.state.parking_lot=["Out-of-scope billing","Separate payment process"];
  app.state.draft={open_questions:Array.from({length:50},(_,i)=>"Draft open question "+(i+1))};
  app.state.version=10;app.state.draftVersion=9;
  const data=app.transcriptObject();
  assert.equal(data.interview_notes.working_summary,app.state.summary);assert.equal(data.interview_notes.current_focus,app.state.focus);
  assert.deepEqual(plain(data.interview_notes.parked_topics),app.state.parking_lot);
  assert.deepEqual(plain(data.interview_notes.draft_open_questions),app.state.draft.open_questions);
  assert.equal(data.interview_notes.draft_questions_may_be_stale,true);
  const md=app.transcriptMarkdown(data);assert.match(md,/predates|stale/i);assert.ok(md.includes("Draft open question 50"));
});

check("share formats exclude private restore state and arbitrary fields",() => {
  const {app,nodes}=harness();
  app.state.context.private_scope="PRIVATE_CONTEXT_EXTRA_SENTINEL";
  app.state.config.api_key="PRIVATE_PROVIDER_SENTINEL";
  app.state.config.csrf_token="PRIVATE_CSRF_SENTINEL";
  app.state.closure.private_token="PRIVATE_CLOSURE_SENTINEL";
  app.state.turns[0].private_token="PRIVATE_TURN_EXTRA_SENTINEL";
  app.state.memo_findings=[{key:"trigger",status:"partial",answer:"Needs a clearer start",evidence_turns:["t002"],internal:"PRIVATE_MEMO_EXTRA_SENTINEL"}];
  app.state.draft={open_questions:[],internal:"PRIVATE_DRAFT_SENTINEL"};
  app.setDocuments({exportState:()=>({scope:"PRIVATE_DOCUMENT_SCOPE_SENTINEL",documents:[{text:"PRIVATE_ORIGINAL_SENTINEL",name:"PRIVATE_FILE_NAME_SENTINEL"}]})});
  app.setKnowledge({processId:"PRIVATE_PROCESS_ID_SENTINEL",exportReceipt:()=>({status_token:"PRIVATE_STATUS_CAPABILITY_SENTINEL"})});
  const data=app.transcriptObject(),serialized=JSON.stringify(data)+app.transcriptMarkdown(data);
  for(const value of [nodes.get("answer-text").value,...Object.values(app.state.config).filter(v=>String(v).startsWith("PRIVATE_")),"PRIVATE_CONTEXT_EXTRA_SENTINEL","PRIVATE_CLOSURE_SENTINEL","PRIVATE_TURN_EXTRA_SENTINEL","PRIVATE_MEMO_EXTRA_SENTINEL","PRIVATE_DRAFT_SENTINEL","PRIVATE_DOCUMENT_SCOPE_SENTINEL","PRIVATE_ORIGINAL_SENTINEL","PRIVATE_FILE_NAME_SENTINEL","PRIVATE_PROCESS_ID_SENTINEL","PRIVATE_STATUS_CAPABILITY_SENTINEL"])
    assert.equal(serialized.includes(value),false,"Sharing must omit "+value);
  assert.equal(data.documents,undefined);assert.equal(data.unsent_answer,undefined);assert.equal(data.knowledge_status,undefined);
  assert.equal(data.turns[0].private_token,undefined);assert.equal(data.process.private_scope,undefined);
  assert.equal(data.memo.topics.find(t=>t.key==="trigger").internal,undefined);
});

check("Markdown preserves exact Unicode, whitespace and nested fences",() => {
  const {app}=harness();
  app.state.turns=[{id:"u_unicode",role:"user",text:"  Élève — 東京 👩🏽‍💻\n\n```md\n# Not a heading\n```\n````\n<script>inert reference</script>\n  trailing spaces  \n"}];
  const data=app.transcriptObject(),md=app.transcriptMarkdown(data),blocks=textBlocks(md);
  assert.equal(data.turns[0].text,app.state.turns[0].text);
  assert.ok(blocks.includes(app.state.turns[0].text),"A dynamically longer text fence must preserve the entire payload exactly");
  assert.ok(md.includes("`````text\n"),"Embedded four-backtick lines must not terminate the content block");
});

check("full supported transcript stays complete in both formats",() => {
  const {app}=harness();
  app.state.turns=Array.from({length:400},(_,i)=>({id:"t"+String(i+1).padStart(3,"0"),role:i%2?"user":"assistant",text:"Turn "+(i+1)+" — "+"detailed process evidence ".repeat(38)}));
  const data=app.transcriptObject(),parsed=JSON.parse(JSON.stringify(data)),md=app.transcriptMarkdown(data),blocks=textBlocks(md);
  assert.equal(data.counts.messages,400);assert.equal(data.counts.interviewer_messages,200);assert.equal(data.counts.participant_messages,200);
  assert.equal(parsed.turns.length,400);
  for(let i=0;i<400;i++){assert.equal(parsed.turns[i].text,app.state.turns[i].text);assert.equal(parsed.turns[i].sequence,i+1);assert.ok(blocks.includes(app.state.turns[i].text),"Missing full turn "+(i+1));}
});

check("capture flags are snapshots rather than completion claims",() => {
  const {app}=harness();
  app.state.busy=true;assert.equal(app.transcriptObject().capture.in_progress,true);app.state.busy=false;
  app.conversationUI.live={active:true};assert.equal(app.transcriptObject().capture.in_progress,true);app.conversationUI.live=null;
  app.conversationUI.status="closing";assert.equal(app.transcriptObject().capture.in_progress,true);app.conversationUI.status="idle";
  app.conversationUI.flowBusy=true;assert.equal(app.transcriptObject().capture.in_progress,true);app.conversationUI.flowBusy=false;
  const data=app.transcriptObject();assert.equal(data.capture.in_progress,false);
  assert.match(data.capture.memo_note,/latest|recorded/i);assert.match(data.capture.memo_note,/lag|behind/i);
  assert.match(data.capture.scope_note,/timestamp/i);assert.match(app.transcriptMarkdown(data),/does not assert.*finished/i);
  assert.equal(data.turns.some(turn=>"timestamp" in turn),false,"Do not invent unstored turn timestamps");
});

check("export is read-only and returned snapshots are detached",() => {
  const {app}=harness();
  app.state.dirty=true;app.state.closure={asked:true,confirmed:false};
  app.state.memo_findings=[{key:"trigger",status:"partial",answer:"Some start details",evidence_turns:["t002"]}];
  app.state.parking_lot=["Another process"];app.state.draft={open_questions:["Who accepts it?"]};
  const before=JSON.stringify(app.state),data=app.transcriptObject();app.transcriptMarkdown(data);
  assert.equal(JSON.stringify(app.state),before);
  data.turns[0].text="Changed copy";data.process.name="Changed copy";data.memo.topics[2].evidence_turn_ids.push("invented");
  data.memo.closure.confirmed=true;data.interview_notes.parked_topics.push("Changed copy");data.interview_notes.draft_open_questions.push("Changed copy");
  assert.equal(JSON.stringify(app.state),before,"Export consumers must not be able to mutate the live interview through shared object references");
});

check("Markdown and JSON downloads work locally without clearing unsaved state",() => {
  const h=harness(),{app}=h;app.state.dirty=true;app.state.example=true;
  const before=JSON.stringify(app.state);app.exportTranscript();app.exportTranscript("json");
  assert.equal(h.downloads.length,2);assert.equal(h.menuCloses,2);assert.equal(h.notices.length,2);
  assert.match(h.downloads[0][1],/-transcript\.md$/);assert.equal(h.downloads[0][2],"text/markdown;charset=utf-8");
  assert.match(h.downloads[1][1],/-transcript\.json$/);assert.equal(h.downloads[1][2],"application/json;charset=utf-8");
  assert.equal(JSON.parse(h.downloads[1][0]).synthetic_example,true);assert.match(h.downloads[0][0],/fictional|synthetic/i);
  assert.equal(JSON.stringify(app.state),before);assert.equal(app.state.dirty,true);
  assert.equal(providerCalls,0);
});

check("empty conversation does not produce an export artifact",() => {
  const h=harness();h.app.state.turns=[];h.app.exportTranscript();h.app.exportTranscript("json");
  assert.equal(h.downloads.length,0);assert.equal(h.notices.length,2);assert.equal(h.menuCloses,0);
  assert.ok(h.notices.every(([message])=>/conversation|interview/i.test(message)));
});

check("review guidance requests evidence and missed follow-up without asserting truth",() => {
  const {app}=harness(),guide=app.transcriptObject().review_guide.join("\n");
  assert.match(guide,/eleven|11/i);assert.match(guide,/turn IDs/i);assert.match(guide,/contradict|assumpt|ambiguous/i);
  assert.match(guide,/next.*question|follow-up/i);assert.match(guide,/do not.*instructions/i);assert.match(guide,/never invent/i);
});

assert.equal(providerCalls,0);
console.log(JSON.stringify({tests_passed:passed,provider_calls:providerCalls,voice_tests:0,browser_calls:0}));
