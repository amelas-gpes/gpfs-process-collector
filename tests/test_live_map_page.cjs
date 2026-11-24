"use strict";
// The workflow map in Live voice: shown as soon as it is drawn, checked next, and a failed update
// retried once before anybody is told. Measured on 2026-11-23 with the real provider: the page
// showed nothing until draw and check had both returned (51 to 279 s), the map was eight answers
// behind when the interview stopped, and one refused update raised a red "The diagram and notes
// haven't updated" banner although the notes were current and the retry that followed drew the map.
// Real app.js logic behind a stub DOM; no provider, network, browser or audio is used.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const appSource=fs.readFileSync(path.join(__dirname,"..","web","app.js"),"utf8");
const flush=async()=>{for(let i=0;i<60;i++)await Promise.resolve();};
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};
const step=(id,title)=>({id,title,type:"activity",evidence_turns:["t002"]});
const map=(...titles)=>({title:"Invoice intake",steps:titles.map((title,index)=>step("S"+(index+1),title)),connections:[],open_questions:[]});

function setup({drawFirst=true}={}){
  const nodes=new Map(),notices=[],scheduled=[];let serial=0;
  function node(id){
    if(!nodes.has(id)){
      nodes.set(id,{id,hidden:false,checked:false,disabled:false,value:"",textContent:"",className:"",open:false,dataset:{},children:[],style:{},
        classList:{toggle(){},add(){},remove(){},contains(){return false;}},
        setAttribute(){},removeAttribute(){},getAttribute(){return null;},focus(){},close(){},showModal(){},remove(){},scrollIntoView(){},setSelectionRange(){},
        contains(){return false;},get firstElementChild(){return node(id+"-first");},
        querySelector(){return node(id+"-child");},querySelectorAll(){return[];},
        append(...values){this.children.push(...values);},replaceChildren(...values){this.children=values;},addEventListener(){}});
    }
    return nodes.get(id);
  }
  const window={speechSynthesis:{cancel(){}},SpeechSynthesisUtterance:class{},addEventListener(){},removeEventListener(){},__notices:notices,__scheduled:scheduled};
  const context={window,console,Blob,Date,JSON,TextEncoder,AbortController,DOMException,confirm:()=>true,
    document:{body:node("body"),activeElement:null,getElementById:node,querySelectorAll:()=>[],querySelector:()=>null,
      createElement:tag=>node("created-"+tag+"-"+(++serial)),addEventListener(){}},
    setTimeout:()=>++serial,clearTimeout(){},requestAnimationFrame:()=>++serial,cancelAnimationFrame(){},
    fetch:()=>{throw Error("Map checks must stay local.");}};
  const seam=`
    renderTranscript=()=>{};renderDraft=()=>{};renderWorkingMap=()=>{};renderCoverage=()=>{};scrollConversation=()=>{};
    updateConversationControls=()=>{};updateDocumentIntakeUI=()=>{};stopSpeaking=()=>{};tab=()=>{};syncLiveCoverage=()=>{};
    scheduleWorkflow=()=>{window.__scheduled.push(conversationUI.applied);};
    notice=(message,error,kind)=>window.__notices.push({message,error:Boolean(error),kind:kind||"general"});
    window.__map={state,conversationUI,refreshWorkflow,setRequest:fn=>{request=fn;}};
  })();`;
  const source=appSource.replace(/  init\(\);\s*\}\)\(\);\s*$/,seam);
  assert.notEqual(source,appSource,"Install the test seam only at application initialization");
  vm.createContext(context);vm.runInContext(source,context,{filename:"app.js"});
  const t=window.__map;
  t.state.config={api_configured:true,csrf_token:"synthetic",
    agent_team:{enabled:true,voice_mode:"live_front",interview_memory:true,...(drawFirst?{live_map_draw_first:true}:{})}};
  t.state.started=true;t.state.context={process_name:"Invoice intake",process_owner:"",objective:"Document the work",background:""};
  t.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:"A supplier email starts a case."}];
  t.conversationUI.live={active:true,connected:true,appendContext:()=>Promise.resolve({status:"acknowledged"})};
  t.conversationUI.revision=1;t.conversationUI.applied=-1;
  return {t,node,notices,scheduled};
}
const drawn=(token,...titles)=>({workflow:map(...titles),memo_findings:[],summary:"",focus:"",parking_lot:[],check_token:token});
const checked=(...titles)=>({workflow:map(...titles),route_assurance:[]});
const titles=h=>Array.from(h.t.conversationUI.workflow?.steps||[],row=>row.title);
let passed=0;const failed=[];
async function check(name,fn){
  try{await fn();passed++;console.log("PASS "+name);}
  catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.stack||error).split("\n").slice(0,8).join("\n     "));}
}
(async()=>{
await check("the map is on screen as soon as it is drawn, and its check follows with the token",async()=>{
  const h=setup(),sent=[],audit=deferred();
  h.t.setRequest((pathName,body)=>{sent.push(body);assert.equal(pathName,"/api/workflow");
    return body.draw_first?Promise.resolve(drawn("a".repeat(32),"Receive invoice","Register invoice")):audit.promise;});
  const pending=h.t.refreshWorkflow();await flush();
  assert.equal(sent.length,2);assert.equal(sent[0].draw_first,true);assert.equal(sent[0].live_map,true);
  assert.deepEqual(titles(h),["Receive invoice","Register invoice"],"Shown while the check is still running");
  assert.equal(h.t.conversationUI.workflowCheckPending,true);
  assert.match(h.node("workflow-status").textContent,/Updated through the latest answer · check pending/);
  assert.equal(sent[1].check_token,"a".repeat(32));assert.equal(sent[1].draw_first,undefined);
  assert.equal(JSON.stringify(sent[1].turns),JSON.stringify(sent[0].turns));
  assert.equal(JSON.stringify(sent[1].previous_capture),JSON.stringify(sent[0].previous_capture),"The check is asked for the account the map was drawn from");
  audit.resolve(checked("Receive invoice","Register invoice"));assert.equal(await pending,true);
  assert.equal(h.t.conversationUI.workflowCheckPending,false);
  assert.equal(h.notices.length,0);
});

await check("until a check returns, the next map starts from the last checked one",async()=>{
  const h=setup(),sent=[];
  // First round: drawn and checked.
  h.t.setRequest((_path,body)=>{sent.push(body);return Promise.resolve(body.draw_first?drawn("b".repeat(32),"Receive invoice"):checked("Receive invoice"));});
  await h.t.refreshWorkflow();
  // Second round: drawn, and its check fails twice.
  h.t.state.turns.push({id:"t003",role:"assistant",text:"And then?"},{id:"t004",role:"user",text:"The clerk registers it."});
  h.t.conversationUI.revision=2;sent.length=0;
  h.t.setRequest((_path,body)=>{sent.push(body);return body.draw_first?Promise.resolve(drawn("c".repeat(32),"Receive invoice","An unchecked step")):Promise.reject(Error("The revised step leaves the existing handoff S1 to S2 unverified."));});
  assert.equal(await h.t.refreshWorkflow(),false);
  assert.deepEqual(titles(h),["Receive invoice","An unchecked step"],"The drawn map stays on screen");
  assert.equal(h.notices.length,0,"A failed check interrupts nobody the first time");
  assert.equal(h.scheduled.length>0,true,"It is tried again by itself");
  sent.length=0;await h.t.refreshWorkflow();
  assert.deepEqual(Array.from(sent[0].previous_capture.workflow.steps,row=>row.title),["Receive invoice"],
    "A step nobody checked is never sent as the accepted baseline");
  assert.equal(h.node("retry-workflow").hidden,false,"After the second failure the Workflow line offers the retry");
  assert.match(h.node("workflow-status").textContent,/check incomplete/);
  assert.equal(h.notices.filter(row=>row.error).length,0,"The map is there as drawn: nothing is reported as lost");
});

await check("answers that arrive while a map is drawn are drawn before anything is checked, twice at most",async()=>{
  const h=setup(),sent=[];let round=0;
  h.t.setRequest((_path,body)=>{sent.push(body);
    if(body.draw_first){
      // The participant goes on talking while the map is drawn.
      const next=h.t.state.turns.length+1;h.t.state.turns.push({id:"t"+String(next).padStart(3,"0"),role:"user",text:"A further answer "+next+"."});
      h.t.conversationUI.revision++;return Promise.resolve(drawn(String(++round).repeat(32),"Receive invoice"));}
    return Promise.resolve(checked("Receive invoice"));});
  assert.equal(await h.t.refreshWorkflow(),true);assert.equal(sent.length,1,"No check while a newer answer waits");
  assert.equal(await h.t.refreshWorkflow(),true);assert.equal(sent.length,2);
  await h.t.refreshWorkflow();
  assert.equal(sent.length,4,"The third map in a row is checked whatever is waiting");
  assert.equal(sent[3].check_token,"3".repeat(32));
});

await check("a server that draws and checks in one piece is handled as before",async()=>{
  const h=setup(),sent=[];
  h.t.setRequest((_path,body)=>{sent.push(body);return Promise.resolve(checked("Receive invoice"));});
  assert.equal(await h.t.refreshWorkflow(),true);
  assert.equal(sent.length,1);assert.deepEqual(titles(h),["Receive invoice"]);assert.equal(h.t.conversationUI.workflowCheckPending,false);
  const old=setup({drawFirst:false}),plain=[];
  old.t.setRequest((_path,body)=>{plain.push(body);return Promise.resolve(checked("Receive invoice"));});
  await old.t.refreshWorkflow();
  assert.equal(plain.length,1);assert.equal(plain[0].draw_first,undefined,"Not asked of a server that does not offer it");
});

await check("one failed map update is retried quietly; a second in a row is reported as the map alone",async()=>{
  const h=setup({drawFirst:false});let calls=0;
  h.t.setRequest(()=>{calls++;return Promise.reject(Error("The revised step leaves the existing handoff S11 to S13 unverified."));});
  await h.t.refreshWorkflow();
  assert.equal(h.notices.length,0,"No banner for a failure the next request may make good");
  assert.equal(h.node("workflow-status").textContent,"Updating…");assert.equal(h.scheduled.length,1);
  await h.t.refreshWorkflow();
  assert.equal(calls,2);assert.equal(h.notices.length,1);
  assert.equal(h.notices[0].kind,"map");assert.equal(h.notices[0].error,true);
  assert.match(h.notices[0].message,/^The workflow map hasn’t updated\. Your transcript and notes are still here\. Try again in Workflow\./);
  assert.doesNotMatch(h.notices[0].message,/notes haven’t updated/,"With the interview team the notes have their own status and were current");
  assert.equal(h.node("retry-workflow").hidden,false);
  // The update that then succeeds takes the report off the page again.
  h.node("interview-error").dataset.errorKind="map";h.node("interview-error").hidden=false;
  h.t.setRequest(()=>Promise.resolve(checked("Receive invoice")));
  assert.equal(await h.t.refreshWorkflow(),true);
  assert.equal(h.node("interview-error").hidden,true);
});

console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0,real_browser:false}));
if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
