"use strict";
// gap-uncommitted-diff-7: a reply whose question no longer fits in the interview. The notes, the
// working map and the capture token of that reply are kept; only the question is left out. The
// participant is told that the interview is full, and is not offered "Try again", which would
// repeat a paid request that ends the same way. Real web/app.js behind a stub DOM with the
// network boundary scripted; no provider, browser or audio is used.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const appSource=fs.readFileSync(path.join(__dirname,"..","web","app.js"),"utf8");
const flush=async()=>{for(let i=0;i<60;i++)await Promise.resolve();};
const ok=value=>({ok:true,status:200,json:async()=>value});
const down=()=>({ok:false,status:503,json:async()=>({error:"The provider is unavailable."})});
const plain=value=>JSON.parse(JSON.stringify(value));
const FULL="This interview is full. Save a copy or create a draft from the answers already recorded.";
const ACK="Let me check that I have everything before we finish.";
const LIMIT=400000;

function setup(){
  const nodes=new Map(),timers=new Map(),calls=[],notices=[];let serial=0,route=url=>{throw Error("Unexpected request "+url);};
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
  const setTimeout=(fn,ms)=>{const id=++serial;timers.set(id,{fn,ms});return id;},clearTimeout=id=>timers.delete(id);
  const window={speechSynthesis:{cancel(){}},SpeechSynthesisUtterance:class{},addEventListener(){},removeEventListener(){},setTimeout,clearTimeout,__notices:notices};
  const context={window,console,Blob,Date,JSON,TextEncoder,AbortController,DOMException,confirm:()=>true,setTimeout,clearTimeout,
    requestAnimationFrame:()=>++serial,cancelAnimationFrame(){},crypto:{randomUUID:()=>String(++serial).padStart(32,"0")},
    document:{body:node("body"),activeElement:null,getElementById:node,querySelectorAll:()=>[],querySelector:()=>null,createElement:tag=>node("created-"+tag+"-"+(++serial)),addEventListener(){}},
    fetch:async(url,options)=>{calls.push({url,body:typeof options?.body==="string"?JSON.parse(options.body):null});return route(url,options);}};
  const seam=`
    renderTranscript=()=>{};renderDraft=()=>{};renderWorkingMap=()=>{};renderCoverage=()=>{};scrollConversation=()=>{};
    updateConversationControls=()=>{};updateDocumentIntakeUI=()=>{};stopSpeaking=()=>{};tab=()=>{};speak=text=>window.__spoken.push(text);
    selectConversationView=view=>{conversationUI.view=view;};
    notice=(message,error)=>window.__notices.push({message,error:Boolean(error)});
    window.__full={state,conversationUI,sendAnswer,retryQuestion,finalCheck,applyInterview,applyLiveCapture,liveSnapshot,
      review:()=>pendingCompletionReview};
  })();`;
  const source=appSource.replace(/  init\(\);\s*\}\)\(\);\s*$/,seam);
  assert.notEqual(source,appSource,"Install the test seam only at application initialization");
  window.__spoken=[];
  vm.createContext(context);vm.runInContext(source,context,{filename:"app.js"});
  const t=window.__full;
  t.state.config={api_configured:true,csrf_token:"synthetic"};
  t.state.started=true;t.state.context={process_name:"Long interview",process_owner:"",objective:"Reach the limit",background:""};
  // The participant may use the reserved space to answer the final omissions check.
  t.state.closure={asked:true,confirmed:false};
  // 393,100 characters already recorded.
  t.state.turns=[...Array.from({length:65},(_,index)=>({id:"long"+index,role:"user",text:"x".repeat(6000)})),{id:"partial",role:"user",text:"x".repeat(3100)}];
  const answer=text=>{node("answer-text").value=text;return t.sendAnswer({preventDefault(){}});};
  const size=()=>t.state.turns.reduce((chars,turn)=>chars+turn.text.length,0);
  return {t,node,calls,notices,spoken:window.__spoken,timers,answer,size,route:fn=>{route=fn;},
    errors:()=>notices.filter(item=>item.error).map(item=>item.message),
    interviewCalls:()=>calls.filter(call=>/\/api\/(agent-team\/)?interview$/.test(call.url)).length};
}
// A reply with notes, a working map and a capture token, as the interviewer returns after an answer.
const reply=(question,turn,extra={})=>({question,summary:"Captured through the last answer.",focus:"closing",parking_lot:[],coverage:[],
  memo_findings:[{key:"trigger",status:"partial",answer:"A supplier email starts the work.",evidence_turns:[turn]}],
  capture_token:"token-of-this-reply",
  workflow_capture:{workflow:{title:"Long interview",steps:[{id:"S1",title:"Register the invoice",evidence_turns:[turn]}],connections:[],open_questions:[]}},...extra});
const trigger=h=>plain(h.t.state.memo_findings.find(item=>item.key==="trigger")||null);

// INTERVIEW_FULL_ALL=1 runs every check and lists each failure; the default stops at the first.
let passed=0;const failures=[];
async function check(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;if(!process.env.INTERVIEW_FULL_ALL)throw error;failures.push(error.message.split("\n")[0]);}}

(async()=>{
await check("a question that does not fit is left out, and the notes, map and token of the same reply are kept",async()=>{
  const h=setup();
  h.route(url=>url==="/api/interview"?ok(reply("z".repeat(901),"t067")):down());
  await h.answer("y".repeat(6000));await flush();
  assert.equal(h.size(),LIMIT-900,"The answer is recorded");
  assert.equal(h.t.state.turns.at(-1).id,"t067");assert.equal(h.t.state.turns.at(-1).role,"user","The question that does not fit is not added");
  assert.deepEqual(trigger(h),{key:"trigger",status:"partial",answer:"A supplier email starts the work.",evidence_turns:["t067"]},"The notes of the same reply are applied");
  assert.equal(h.t.state.summary,"Captured through the last answer.");assert.equal(h.t.state.focus,"closing");
  assert.equal(h.t.state.captureToken,"token-of-this-reply");
  assert.deepEqual(plain(h.t.conversationUI.workflow.steps.map(step=>step.id)),["S1"],"The working map of the same reply is applied");
  assert.deepEqual(h.errors(),[FULL],"Only the full-interview notice is shown");
  assert.equal(h.node("retry-question").hidden,true,"Try again would repeat the same request with the same outcome");
  assert.equal(h.t.state.busy,false);assert.deepEqual(h.spoken,[]);
  assert.equal(h.interviewCalls(),1);
});

await check("a question that just fits is asked as usual",async()=>{
  const h=setup();
  h.route(url=>url==="/api/interview"?ok(reply("z".repeat(900),"t067")):down());
  await h.answer("y".repeat(6000));await flush();
  assert.equal(h.size(),LIMIT);assert.equal(h.t.state.turns.at(-1).role,"assistant");
  assert.deepEqual(h.errors().filter(message=>/full/.test(message)),[]);
  assert.equal(trigger(h).answer,"A supplier email starts the work.");assert.equal(h.node("retry-question").hidden,true);
});

await check("an ordinary failure still offers Try again, and a retry that fills the interview withdraws it",async()=>{
  const h=setup();
  h.route(()=>down());
  await h.answer("y".repeat(6000));await flush();
  assert.equal(h.node("retry-question").hidden,false);
  assert.match(h.errors().at(-1),/next question didn’t load\. Add more detail, or choose Try again\. The provider is unavailable\./);
  assert.equal(trigger(h),null,"Nothing was captured by the failed request");
  // A retry that fails the same ordinary way keeps its own wording and the control.
  await h.t.retryQuestion();await flush();
  assert.equal(h.errors().at(-1),"The provider is unavailable. Your answers remain in the conversation.");
  assert.equal(h.node("retry-question").hidden,false);
  // The retry that succeeds returns a question with no room left.
  h.route(url=>url==="/api/interview"?ok(reply("z".repeat(901),"t067")):down());
  await h.t.retryQuestion();await flush();
  assert.equal(h.errors().at(-1),FULL,"The full-interview notice stands by itself");
  assert.equal(h.node("retry-question").hidden,true);
  assert.equal(trigger(h).answer,"A supplier email starts the work.","The retried reply's notes are applied");
  assert.equal(h.t.state.captureToken,"token-of-this-reply");
  assert.equal(h.t.state.turns.at(-1).role,"user");assert.equal(h.t.state.busy,false);
});

await check("a reply without notes whose line does not fit adds nothing and says the interview is full",async()=>{
  const h=setup();h.t.state.turns.push({id:"t067",role:"user",text:"y".repeat(6000)});
  h.t.state.memo_findings=[{key:"trigger",status:"partial",answer:"Earlier note.",evidence_turns:["t067"]}];
  h.route(url=>url==="/api/interview"?ok({question:"z".repeat(901),preserve_capture:true,capture_token:"pause-token"}):down());
  await h.t.finalCheck();await flush();
  assert.equal(h.t.state.turns.length,67);assert.deepEqual(h.errors(),[FULL]);
  assert.equal(h.t.state.memo_findings[0].answer,"Earlier note.","A reply without notes leaves the notes as they were");
  assert.equal(h.t.state.captureToken,"pause-token");
  assert.throws(()=>h.t.applyInterview({question:"?".repeat(901),preserve_capture:true}),error=>error.code==="interview_full"&&error.message===FULL);
});

await check("a completion review whose acknowledgement does not fit is not started",async()=>{
  const h=setup();h.t.state.config.agent_team={enabled:true};
  h.t.state.turns.push({id:"filler",role:"user",text:"x".repeat(LIMIT-393100-6000-ACK.length+1)});
  const pendingReview=reply(ACK,"t068",{review_ticket:"ticket-1",coverage_verified:false,speech_authorization:{approved:true,kind:"review_pending",text:ACK},completion:{ready_for_final_check:false,complete:false}});
  h.route(url=>url==="/api/agent-team/interview"?ok(pendingReview):["/api/agent-team/status","/api/agent-team/cancel"].includes(url)?ok({}):down());
  await h.answer("y".repeat(6000));await flush();
  assert.equal(h.size(),LIMIT-ACK.length+1,"One character too few is left for the acknowledgement");
  assert.equal(h.t.state.turns.at(-1).role,"user");
  assert.equal(trigger(h).answer,"A supplier email starts the work.");
  assert.equal(h.t.review(),null,"No review waits on an acknowledgement that was never shown");
  assert.equal(h.calls.some(call=>call.url==="/api/agent-team/review"),false);
  assert.deepEqual(h.errors(),[FULL]);assert.equal(h.node("retry-question").hidden,true);
});

// Live voice: the application's own lines (final check, pause, completion, review acknowledgement) are
// added to the transcript when they are handed to the interviewer, so the same limit applies to them.
function live(h){
  const said=[];let stopped=0;
  h.t.state.config.agent_team={enabled:true,voice_mode:"live_front"};
  h.t.conversationUI.live={active:true,say:async text=>{said.push(text);return {status:"acknowledged"};},appendContext:async()=>({status:"acknowledged"}),
    stop(){stopped++;this.active=false;}};
  h.t.state.turns.push({id:"t067",role:"user",text:"y".repeat(6000)});
  return {said,stops:()=>stopped};
}
const closing=(question,kind="final_check")=>reply(question,"t067",{coverage_verified:true,completion:{ready_for_final_check:true,complete:false},closure:{asked:true,confirmed:false},
  speech_authorization:{approved:true,kind,text:question}});

await check("in Live voice a closing line that does not fit is not spoken, and the notes of that capture are kept",async()=>{
  const h=setup(),voice=live(h);
  const applied=await h.t.applyLiveCapture(closing("z".repeat(901)),h.t.liveSnapshot());await flush();
  assert.equal(applied,true,"The capture counts as applied, so the same answer is not captured again");
  assert.equal(trigger(h).answer,"A supplier email starts the work.");assert.equal(h.t.state.captureToken,"token-of-this-reply");
  assert.equal(h.t.state.turns.at(-1).id,"t067","The line is not added to the transcript");
  assert.deepEqual(voice.said,[],"and it is not handed to the interviewer");
  assert.deepEqual(h.errors(),[FULL]);
  assert.equal(voice.stops(),1,"Voice ends, as it does when a caption no longer fits");
});

await check("in Live voice a closing line that fits is spoken, and an ordinary capture is never held to the limit",async()=>{
  const h=setup(),voice=live(h);
  assert.equal(await h.t.applyLiveCapture(closing("z".repeat(900)),h.t.liveSnapshot()),true);await flush();
  assert.equal(h.t.state.turns.at(-1).text,"z".repeat(900));assert.deepEqual(voice.said,["z".repeat(900)]);assert.deepEqual(h.errors(),[]);assert.equal(voice.stops(),0);
  // The lead's own next question is not shown or spoken in Live voice, whatever its length.
  const other=setup(),second=live(other);
  assert.equal(await other.t.applyLiveCapture(closing("z".repeat(5000),"question"),other.t.liveSnapshot()),true);await flush();
  assert.equal(other.t.state.turns.at(-1).id,"t067");assert.deepEqual(other.errors(),[]);assert.equal(second.stops(),0);
  assert.equal(trigger(other).answer,"A supplier email starts the work.");
});

await check("a review that finishes after voice ended keeps its decision when its line does not fit, and offers no retry",async()=>{
  const h=setup(),voice=live(h);let release;
  const waiting=new Promise(resolve=>{release=resolve;});
  h.route(url=>url==="/api/agent-team/review"?waiting:["/api/agent-team/status","/api/agent-team/cancel"].includes(url)?ok({}):down());
  // The acknowledgement fits and is spoken; the review then runs.
  const acknowledged={...closing(ACK,"review_pending"),review_ticket:"ticket-live",coverage_verified:false,completion:{ready_for_final_check:false,complete:false},closure:{asked:false,confirmed:false},
    memo_findings:[{key:"trigger",status:"partial",answer:"Before the review.",evidence_turns:["t067"]}]};
  const applying=h.t.applyLiveCapture(acknowledged,h.t.liveSnapshot());await flush();
  assert.deepEqual(voice.said,[ACK]);assert.equal(h.t.state.turns.at(-1).text,ACK);
  assert.ok(h.calls.some(call=>call.url==="/api/agent-team/review"),"The review is running");
  // Voice ends while it runs. Its decision arrives with a final-check question one character too long.
  h.t.conversationUI.live.active=false;
  const room=LIMIT-h.size();
  release(ok(closing("z".repeat(room+1))));await applying;await flush();
  assert.equal(trigger(h).answer,"A supplier email starts the work.","The reviewed notes are applied");
  assert.equal(h.t.state.coverageVerified,true);
  assert.equal(h.t.state.turns.at(-1).text,ACK,"The question that does not fit is not added");
  assert.deepEqual(h.errors(),[FULL],"The review is not reported as unfinished, and no retry is offered for it");
  assert.equal(h.node("retry-question").hidden,true);
  assert.equal(h.t.state.closure.asked,false,"A final check that was not shown has not been asked");
});

if(failures.length){console.error(failures.join("\n"));process.exitCode=1;}
console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
