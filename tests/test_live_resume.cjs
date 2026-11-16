"use strict";
// A long interview can start or resume Live voice. The voice controller forwards the
// current notes and reports a condensed start once; the page warns before the click
// and says afterwards that voice resumed with a condensed history.
// Media, DOM and network boundaries are local fakes; no provider or network is used.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const shared={require,__dirname,console,Buffer,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException,setImmediate,setTimeout,clearTimeout};
const exported=(source,tail)=>{const module={exports:{}};vm.runInNewContext(source+tail,{...shared,module});return module.exports;};
const voice=exported(fs.readFileSync(path.join(__dirname,"test_live_voice.cjs"),"utf8").split("(async()=>{")[0],"\nmodule.exports={setup};");
let source=fs.readFileSync(path.join(__dirname,"test_agent_experience.cjs"),"utf8").split("let passed=0;")[0];
source=source.replace("setTeam:value=>","updateConversationControls,liveHistoryCondensed,liveResumeNotes,setTeam:value=>");
const app=exported(source,"\nmodule.exports={setup,flush};");
const LIMIT={messages:128,bytes:7800};
const HISTORY={condensed:true,included_turns:36,total_turns:50,summary_included:true,latest_turn_clipped:false};
const FILES={condensed:true,included_excerpts:2,retrieved_excerpts:10};
const QUESTION="Thanks. What happens after that step, and who picks it up from you?";
const ANSWER="After I log the invoice in the register I compare the supplier name and the invoice number against last month's entries, and if it looks like a duplicate I link it to the earlier record and close it, otherwise I mark it checked and send the queue link to Treasury so they can accept it before ten.";
const exchanges=count=>Array.from({length:count*2},(_,index)=>({id:`t${index}`,role:index%2?"user":"assistant",text:index%2?ANSWER:QUESTION}));
function fixture(turns){
 const h=app.setup();
 h.t.state.config.agent_team.voice_mode="live_front";
 h.t.state.config.live={enabled:true,history_limit:{...LIMIT}};
 h.t.state.turns=turns;h.t.state.summary="The AP clerk logs invoices and hands accepted ones to Treasury.";
 h.t.state.memo_findings=[{key:"trigger",status:"captured",answer:"An emailed invoice.",evidence_turns:["t1"]},
  {key:"scope",status:"not_applicable",answer:"One entity.",evidence_turns:["t1"]},{key:"risk",status:"partial",answer:"Late payment.",evidence_turns:["t1"]}];
 // The shared harness has display stubs only; place the dock where the page already has it.
 for(const id of ["conversation-dock","live-controls"])h.node(id).contains=()=>false;
 h.node("conversation-dock").parentElement=h.node("voice-panel");
 h.node("live-controls").parentElement=h.node("conversation-dock").querySelector(".dock-row");
 h.started=[];
 h.window.CollectorLiveVoice=class{
  constructor(options){h.voiceOptions=options;this.active=false;this.connected=false;}
  async start(payload){h.started.push(payload);this.active=true;this.connected=true;h.voiceOptions.onStatus("listening");return true;}
  async stop(){this.active=false;this.connected=false;h.voiceOptions.onStatus("idle");return{finalized:true};}
 };
 h.hint=h.node("transcript-live-hint");h.button=h.node("start-live");
 return h;
}
let passed=0;
async function check(name,fn){await fn();passed++;console.log("PASS "+name);}
(async()=>{
 await check("the controller forwards the notes only when the page supplies them",async()=>{
  const h=voice.setup(),notes={summary:"Invoices are logged.",open_topics:["risk"]};
  assert.equal(await h.api.start({context:{process_name:"Invoices"},turns:[{id:"t1",role:"user",text:"Receive invoice"}],notes}),true);
  assert.equal(h.payloads[0][0],"/api/live-session");assert.deepEqual(h.payloads[0][1].notes,notes);
  await h.api.stop({immediate:true});
  const plain=voice.setup();await plain.api.start({context:{process_name:"Invoices"},turns:[]});
  assert.equal("notes" in plain.payloads[0][1],false);await plain.api.stop({immediate:true});
 });
 await check("a condensed start is reported once, after voice is connected",async()=>{
  const reports=[];let connectedAtReport=null;
  const h=voice.setup({request:async()=>({sdp:"v=0\r\no=remote",model:"gpt-live-1",history:{...HISTORY}})});
  h.api.options.onCondensed=info=>{reports.push(info);connectedAtReport=h.api.connected;};
  assert.equal(await h.api.start({context:{process_name:"Invoices"},turns:exchanges(25)}),true);
  assert.equal(reports.length,1);assert.equal(connectedAtReport,true);
  assert.deepEqual(JSON.parse(JSON.stringify(reports[0])),{history:HISTORY,documents:null});
  assert.equal(h.errors.length,0);await h.api.stop({immediate:true});assert.equal(reports.length,1);
 });
 await check("a shorter file selection is reported, and an ordinary start reports nothing",async()=>{
  const reports=[],files={condensed:true,included_excerpts:2,retrieved_excerpts:10};
  const h=voice.setup({request:async()=>({sdp:"v=0\r\no=remote",model:"gpt-live-1",document_context:files})});
  h.api.options.onCondensed=info=>reports.push(info);await h.api.start({context:{},turns:[]});
  assert.deepEqual(JSON.parse(JSON.stringify(reports)),[{history:null,documents:files}]);await h.api.stop({immediate:true});
  const plain=voice.setup({request:async()=>({sdp:"v=0\r\no=remote",model:"gpt-live-1",history:{condensed:false}})});
  plain.api.options.onCondensed=info=>reports.push(info);await plain.api.start({context:{},turns:[]});
  assert.equal(reports.length,1);await plain.api.stop({immediate:true});
 });
 await check("a refused or failed start reports no condensed history",async()=>{
  const reports=[];
  const h=voice.setup({request:async()=>{throw new Error("The server did not start voice.");}});
  h.api.options.onCondensed=info=>reports.push(info);
  assert.equal(await h.api.start({context:{},turns:exchanges(25)}),false);
  assert.equal(reports.length,0);assert.equal(h.errors.length,1);
 });
 await check("the page measures the same limit the server publishes",async()=>{
  const bytes=turns=>turns.reduce((size,turn)=>size+Buffer.byteLength(turn.text,"utf8"),0);
  assert.ok(bytes(exchanges(21))<=LIMIT.bytes&&bytes(exchanges(22))>LIMIT.bytes);
  assert.equal(fixture(exchanges(21)).t.liveHistoryCondensed(),false);
  assert.equal(fixture(exchanges(22)).t.liveHistoryCondensed(),true);
  const exact=[{id:"t1",role:"user",text:"x".repeat(LIMIT.bytes)}];
  assert.equal(fixture(exact).t.liveHistoryCondensed(),false);
  assert.equal(fixture([...exact,{id:"t2",role:"user",text:"y"}]).t.liveHistoryCondensed(),true);
  assert.equal(fixture([...exact,{id:"d1",role:"assistant",text:"File received.",document_event:true}]).t.liveHistoryCondensed(),false,"File acknowledgements are not voice history");
  const short=count=>Array.from({length:count},(_,index)=>({id:`s${index}`,role:"user",text:"Yes."}));
  assert.equal(fixture(short(128)).t.liveHistoryCondensed(),false);assert.equal(fixture(short(129)).t.liveHistoryCondensed(),true);
  assert.equal(fixture([{id:"j1",role:"user",text:"請求書".repeat(900)}]).t.liveHistoryCondensed(),true,"Bytes, not characters, are counted");
  const reviewed=fixture(exchanges(25));reviewed.t.state.config.agent_team.voice_mode="reviewed_turns";assert.equal(reviewed.t.liveHistoryCondensed(),false);
  const unpublished=fixture(exchanges(25));delete unpublished.t.state.config.live.history_limit;assert.equal(unpublished.t.liveHistoryCondensed(),false);
 });
 await check("the limitation is shown beside the button before the click",async()=>{
  const h=fixture(exchanges(25));h.t.updateConversationControls();
  assert.equal(h.hint.hidden,false);assert.match(h.hint.textContent,/voice will continue with a condensed history/);
  assert.match(h.hint.textContent,/notes summary and the most recent turns/);assert.match(h.hint.textContent,/still use the full transcript/);
  assert.equal(h.button.title,h.hint.textContent);assert.equal(h.button.disabled,false,"Voice stays available");
  assert.equal(h.button.querySelector("span").textContent,"Continue talking");
  h.t.conversationUI.view="transcript";h.t.updateConversationControls();
  assert.equal(h.hint.hidden,false,"The warning travels with the button into the transcript view");
  const ordinary=fixture(exchanges(3));ordinary.t.updateConversationControls();
  assert.equal(ordinary.hint.hidden,true);assert.equal(ordinary.button.title,"");
  const unsummarised=fixture(exchanges(25));unsummarised.t.state.summary="";unsummarised.t.updateConversationControls();
  assert.match(unsummarised.hint.textContent,/condensed history \(the most recent turns\)/,"No notes summary is promised when there is none to send");
  assert.equal(unsummarised.button.title,unsummarised.hint.textContent);
 });
 await check("open topics are those with nothing captured; partly covered ones travel separately",async()=>{
  const h=fixture(exchanges(25));
  assert.deepEqual(JSON.parse(JSON.stringify(h.t.liveResumeNotes())),{summary:h.t.state.summary,
   open_topics:["name","purpose","completion","accountable","lifecycle","checks","variations","pain_points","materials","rules","connections","data_systems","volume"],
   partial_topics:["risk"]});
  // Reopening a saved interview turns every captured or not-applicable finding into partial (see the loader in web/app.js).
  const reopened=fixture(exchanges(25));
  reopened.t.state.memo_findings=["name","purpose","trigger","completion","scope"].map(key=>({key,status:"partial",answer:"Reported earlier.",evidence_turns:["t1"]}));
  const notes=reopened.t.liveResumeNotes();
  assert.deepEqual([...notes.partial_topics],["name","purpose","trigger","completion","scope"]);
  assert.deepEqual([...notes.open_topics],["accountable","lifecycle","checks","variations","pain_points","risk","materials","rules","connections","data_systems","volume"],"Topics that already hold an answer are not reported as open");
  reopened.t.state.memo_findings.push({key:"risk",status:"unknown",answer:"",evidence_turns:[]});
  assert.ok(reopened.t.liveResumeNotes().open_topics.includes("risk"));
  const blank=fixture(exchanges(25));blank.t.state.memo_findings=[];
  assert.equal(blank.t.liveResumeNotes().open_topics.length,16);assert.equal(blank.t.liveResumeNotes().partial_topics.length,0);
 });
 await check("voice starts with the current notes and announces the condensed history once",async()=>{
  const h=fixture([...exchanges(25),{id:"d1",role:"assistant",text:"File received.",document_event:true}]);
  await h.t.startLiveConversation();
  assert.equal(h.started.length,1);
  assert.equal(h.started[0].turns.length,50,"File acknowledgements are not sent as history");
  assert.equal(h.started[0].notes.summary,h.t.state.summary);
  assert.deepEqual([...h.started[0].notes.open_topics],["name","purpose","completion","accountable","lifecycle","checks","variations","pain_points","materials","rules","connections","data_systems","volume"]);
  assert.deepEqual([...h.started[0].notes.partial_topics],["risk"]);
  assert.equal(h.notices.length,0,"Nothing is announced until the controller reports a condensed start");
  h.voiceOptions.onCondensed({history:{...HISTORY},documents:null});
  assert.equal(h.notices.length,1,"The notice appears once");
  assert.ok(!h.notices[0].error,"A condensed resume is information, not an error");
  assert.match(h.notices[0].message,/^Voice resumed with a condensed history \(your notes summary and the last 36 of 50 turns\)\. Notes and the report still use the full transcript\.$/);
  h.t.updateConversationControls();
  assert.equal(h.hint.hidden,false);assert.match(h.hint.textContent,/^Voice resumed with a condensed history\./);
  assert.equal(h.button.title,"");
  h.t.conversationUI.view="transcript";h.t.updateConversationControls();
  assert.equal(h.hint.textContent,"Voice is on with a condensed history. Stop talking to type a reply.");
 });
 await check("the notice says what the server reports it seeded, never 'the last 0 turns' or a summary that was not sent",async()=>{
  const said=async history=>{const h=fixture(exchanges(25));await h.t.startLiveConversation();h.voiceOptions.onCondensed({history,documents:null});assert.equal(h.notices.length,1);return h.notices[0].message;};
  const tail=" Notes and the report still use the full transcript.";
  assert.equal(await said({...HISTORY,summary_included:false}),"Voice resumed with a condensed history (the last 36 of 50 turns)."+tail);
  assert.equal(await said({...HISTORY,included_turns:1}),"Voice resumed with a condensed history (your notes summary and the most recent of 50 turns)."+tail);
  assert.equal(await said({...HISTORY,included_turns:1,latest_turn_clipped:true}),"Voice resumed with a condensed history (your notes summary and the end of the most recent turn)."+tail);
  assert.equal(await said({...HISTORY,included_turns:0}),"Voice resumed with a condensed history (your notes summary)."+tail);
  assert.equal(await said({condensed:true,included_turns:0,total_turns:50}),"Voice resumed with a condensed history."+tail);
 });
 await check("an ordinary session keeps its usual hint, and a restart clears the previous state",async()=>{
  const h=fixture(exchanges(3));await h.t.startLiveConversation();
  assert.equal(h.started[0].notes.open_topics.length,13);
  h.t.updateConversationControls();assert.equal(h.hint.hidden,true,"No hint in the voice view of an ordinary session");
  h.t.conversationUI.view="transcript";h.t.updateConversationControls();
  assert.equal(h.hint.hidden,false);assert.equal(h.hint.textContent,"Voice is on. Stop talking to type a reply.");
  h.voiceOptions.onCondensed({history:null,documents:{...FILES}});
  assert.equal(h.notices.length,1);assert.match(h.notices[0].message,/^Voice is using a shorter selection of your files/);
  assert.equal(h.t.conversationUI.liveCondensed,false);assert.equal(h.t.conversationUI.liveDocumentsCondensed,true);
  h.voiceOptions.onCondensed({history:{...HISTORY},documents:{condensed:true}});
  assert.match(h.notices[1].message,/condensed history .*shorter selection of your files/);assert.equal(h.t.conversationUI.liveCondensed,true);
  await h.t.conversationUI.live.stop();await h.t.startLiveConversation();
  assert.equal(h.t.conversationUI.liveCondensed,false,"A new session starts without the previous session's condensed state");
  assert.equal(h.t.conversationUI.liveDocumentsCondensed,false,"A new session starts without the previous session's file-selection state");
  h.voiceOptions.onCondensed({history:null,documents:null});assert.equal(h.notices.length,2);
 });
 await check("a shorter file selection stays on the hint line while that session is on",async()=>{
  // The notice is a toast that leaves after three seconds; the hint line must keep the fact for the session.
  const h=fixture(exchanges(3));await h.t.startLiveConversation();
  h.voiceOptions.onCondensed({history:null,documents:{...FILES}});h.t.updateConversationControls();
  assert.equal(h.hint.hidden,false,"The voice view keeps the file-selection fact on screen");
  assert.equal(h.hint.textContent,"Voice is using a shorter selection of your files than the notes and the report do.");
  h.t.conversationUI.view="transcript";h.t.updateConversationControls();
  assert.equal(h.hint.hidden,false);assert.equal(h.hint.textContent,"Voice is on with a shorter selection of your files. Stop talking to type a reply.");
  await h.t.conversationUI.live.stop();h.t.updateConversationControls();
  assert.equal(h.hint.hidden,true,"Nothing is claimed about a session that has ended");
  const both=fixture(exchanges(25));await both.t.startLiveConversation();
  both.voiceOptions.onCondensed({history:{...HISTORY},documents:{...FILES}});both.t.updateConversationControls();
  assert.equal(both.hint.textContent,"Voice resumed with a condensed history and a shorter selection of your files. Notes and the report still use the full transcript and the larger file selection.");
  both.t.conversationUI.view="transcript";both.t.updateConversationControls();
  assert.equal(both.hint.textContent,"Voice is on with a condensed history and a shorter selection of your files. Stop talking to type a reply.");
  await both.t.conversationUI.live.stop();await both.t.startLiveConversation();both.t.updateConversationControls();
  assert.equal(both.hint.textContent,"Voice is on. Stop talking to type a reply.","The next session starts clean");
 });
 console.log(JSON.stringify({checks_passed:passed,provider_calls:0,network_calls:0}));
})().catch(e=>{console.error(e);process.exitCode=1;});
