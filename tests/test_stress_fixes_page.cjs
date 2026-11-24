"use strict";
// Page fixes from the 19 November stress test: an answer the server reads as empty can no longer lock
// an interview, a refused answer goes back to the box, a saved interview with such an answer opens,
// a lone surrogate is repaired, the transcript limit is counted once per turn,
// a long list of unread files is shown as a count, and the draft head start can
// be cancelled. The page of web/index.html runs web/app.js (tests/fixtures/app_page.cjs); no network.
const assert=require("node:assert/strict");
const {open}=require("./fixtures/app_page.cjs");
const EXPOSE="sendAnswer,receiveLiveCaption,importSession,transcriptLimit,turnText,fileNames,prepareDraftAhead,"+
 "cancelDraftAhead,draftAhead,interviewRequests,renderTranscript,updateControls,tab,selectConversationView,readContext";
const HOOK="window.__notices=[];const __notice=notice;notice=(message,...rest)=>{window.__notices.push(String(message));return __notice(message,...rest);};";
const SEPARATORS="\u001c\u001d\u001e\u001f\u0085";
let passed=0;const failed=[];
async function check(name,fn){
 try{await fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.stack||error).split("\n").slice(0,6).join("\n     "));}
}
async function interview(){
 const page=await open({config:{agent_team:{enabled:true}},expose:EXPOSE,hook:HOOK});
 page.state.context={process_name:"Capital call",process_owner:"",objective:"Understand the work",background:""};page.state.started=true;
 page.state.turns=[{id:"t001",role:"assistant",text:"What starts a capital call?"}];
 page.t.conversationUI.typing=true;page.t.tab("interview");page.t.selectConversationView("transcript");page.t.renderTranscript();
 return page;
}
const question={question:"Who approves the notice?",summary:"",focus:"",parking_lot:[],memo_findings:[],coverage:[],
 completion:{ready_for_final_check:false,complete:false},closure:{asked:false,confirmed:false},
 speech_authorization:{approved:true,kind:"question",text:"Who approves the notice?",revision:"r1",completion_allowed:false}};
const interviewCalls=page=>page.requests.filter(item=>/\/api\/(agent-team\/)?interview$|\/api\/conversation\/turn$/.test(item.url));

(async()=>{
 await check("the page trims an answer with the server's whitespace and repairs a lone surrogate",async()=>{
  const page=await interview();
  for(const ch of SEPARATORS)assert.equal(page.t.turnText(" "+ch+"\n"),"",`U+${ch.charCodeAt(0).toString(16).padStart(4,"0")} alone is empty`);
  assert.equal(page.t.turnText("\u001fWire released\u0085"),"Wire released","Real text is kept, the separators around it go");
  assert.equal(page.t.turnText("Fee \ud800 waived"),"Fee � waived","A lone surrogate half becomes U+FFFD");
  assert.equal(page.t.turnText("Fee 😀 waived"),"Fee 😀 waived","A whole pair is untouched");
 });
 await check("an answer of only control separators is not added and nothing is sent",async()=>{
  const page=await interview();page.route(()=>question);
  for(const ch of SEPARATORS){
   page.$("answer-text").value=ch;await page.t.sendAnswer({preventDefault(){}});await page.flush();
   assert.equal(page.state.turns.length,1,"No blank answer joins the transcript");
  }
  assert.equal(interviewCalls(page).length,0,"Nothing was sent to the interviewer");
  page.$("answer-text").value="\u001f";page.t.updateControls();
  assert.equal(page.$("send-answer").disabled,true,"Send is not offered for a box that holds nothing to send");
  await page.t.sendAnswer({preventDefault(){}});assert.equal(page.$("answer-text").value,"","and Ctrl+Enter clears it");
  page.$("answer-text").value="The GP sends the notice.";await page.t.sendAnswer({preventDefault(){}});await page.flush();
  assert.equal(page.state.turns.filter(turn=>turn.role==="user").length,1,"A real answer still goes through");
 });
 await check("an answer the server refuses goes back to the box instead of blocking every later request",async()=>{
  const page=await interview();
  page.route(()=>({ok:false,status:400,json:async()=>({error:"Turn text contains an incomplete Unicode character. Edit that text and try again."}),headers:{get:()=>null}}));
  page.$("answer-text").value="We wire the funds.";await page.t.sendAnswer({preventDefault(){}});await page.flush();
  assert.deepEqual(page.state.turns.map(turn=>turn.id),["t001"],"The refused answer left the transcript");
  assert.equal(page.$("answer-text").value,"We wire the funds.","It is back in the box to edit");
  assert.ok(page.window.__notices.some(message=>/incomplete Unicode character.*Your answer is back in the box\./.test(message)),"The reason is shown");
  page.route(()=>question);await page.t.sendAnswer({preventDefault(){}});await page.flush();
  assert.equal(page.state.turns.filter(turn=>turn.role==="user").length,1,"Sending again works");
  // The interview returns to where it was: a final check that was asked is still asked.
  const again=await interview();again.state.closure={asked:true,confirmed:false};const version=again.state.evidenceVersion;
  again.route(()=>({ok:false,status:400,json:async()=>({error:"Turn text is required."}),headers:{get:()=>null}}));
  again.$("answer-text").value="Nothing else.";await again.t.sendAnswer({preventDefault(){}});await again.flush();
  assert.equal(again.state.closure.asked,true,"The final check is still the open question");
  assert.equal(again.state.evidenceVersion,version,"No answer was added, so the account did not change");
  const last=interviewCalls(page).at(-1).body;
  assert.equal(last.turns.filter(turn=>turn.role==="user").length,1,"Only the resent answer is in the request");
 });
 await check("a saved interview with a blank-to-the-server answer opens without it",async()=>{
  const page=await interview();
  const saved={schema_version:1,context:{process_name:"Capital call",process_owner:"",objective:"",background:""},
   turns:[{id:"t001",role:"assistant",text:"What starts a capital call?"},{id:"t002",role:"user",text:"\u001f"},
          {id:"t003",role:"user",text:"The GP sends the notice \ud800."},{id:"t004",role:"assistant",text:"Who checks it?"}]};
  await page.t.importSession({size:1000,text:async()=>JSON.stringify(saved)});await page.flush();
  assert.deepEqual(page.state.turns.map(turn=>turn.id),["t001","t003","t004"],"The blank answer is left out, the rest opens");
  assert.equal(page.state.turns[1].text,"The GP sends the notice �.","Its broken character is repaired");
 });
 await check("a live caption the server would read as empty makes no turn",async()=>{
  const page=await interview();const before=page.state.turns.length;
  page.t.receiveLiveCaption({id:"c1",role:"user",text:"\u001f\u001e",final:true});
  assert.equal(page.state.turns.length,before);
 });
 await check("the transcript limit is counted per turn and follows an edited turn",async()=>{
  const page=await interview();
  page.state.turns=Array.from({length:300},(_,index)=>({id:"t"+String(index+1).padStart(3,"0"),role:index%2?"user":"assistant",text:"x".repeat(1000)}));
  assert.equal(page.t.transcriptLimit().size,300000);
  page.state.turns[5].text="x".repeat(10);assert.equal(page.t.transcriptLimit().size,299010,"A changed text is recounted");
  page.state.turns.push({id:"t999",role:"user",text:"😀😀"});assert.equal(page.t.transcriptLimit().size,299012,"Characters, not UTF-16 units");
 });
 await check("more than three unread files are named by count",async()=>{
  const page=await interview();const files=n=>Array.from({length:n},(_,i)=>({name:`ledger-${i}.csv`}));
  assert.equal(page.t.fileNames(files(3)),"ledger-0.csv, ledger-1.csv, ledger-2.csv");
  assert.equal(page.t.fileNames(files(11)),"11 files");
 });
 await check("the draft head start can be cancelled and stays cancelled until it is armed again",async()=>{
  const page=await interview();let signal=null,sent=0;
  page.state.config.draft_prepare=true;page.state.turns.push({id:"t002",role:"user",text:"The GP sends the notice."});
  page.route((url,init)=>{if(url==="/api/draft"){sent++;signal=init.signal;return new Promise((resolve,reject)=>init.signal.addEventListener("abort",()=>reject(new DOMException("Aborted","AbortError"))));}return question;});
  Object.assign(page.t.draftAhead,{generation:page.state.generation,turns:page.state.turns.length,body:"",flight:false,ready:""});
  page.t.prepareDraftAhead();await page.flush();
  assert.equal(sent,1,"The head start was sent");assert.ok(signal,"with a signal");assert.equal(page.t.interviewRequests.size>0,true,"and tracked with the interview's requests");
  page.t.cancelDraftAhead();await page.flush();
  assert.equal(signal.aborted,true,"Cancelling aborts it");assert.equal(page.t.draftAhead.flight,false);assert.equal(page.t.draftAhead.body,"");
  page.t.prepareDraftAhead();await page.flush();assert.equal(sent,1,"It does not restart by itself");
  Object.assign(page.t.draftAhead,{turns:page.state.turns.length});page.t.prepareDraftAhead();await page.flush();
  assert.equal(sent,2,"Armed again, it is sent again");
  // Pausing it (voice starting) aborts it but keeps it armed for the same account.
  page.t.cancelDraftAhead(false);await page.flush();assert.equal(signal.aborted,true);
  page.t.prepareDraftAhead();await page.flush();assert.equal(sent,3,"The same account can start it again");
 });
 await check("the context fields repair a broken character before they are sent",async()=>{
  const page=await interview();
  page.$("background").value="Fee \ud800 waived";page.$("process-name").value="Capital \udc00call";
  const context=page.t.readContext();
  assert.equal(context.background,"Fee \ufffd waived");assert.equal(context.process_name,"Capital \ufffdcall");
 });
 console.log(`${passed} passed, ${failed.length} failed`);
 if(failed.length)process.exit(1);
})();
