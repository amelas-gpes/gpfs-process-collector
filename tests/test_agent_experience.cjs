"use strict";
// Actual app transport + controlled voice + reviewed playback integration.
// Only display, browser hardware and network boundaries are faked; no providers.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const app=fs.readFileSync(path.join(__dirname,"../web/app.js"),"utf8");
const controlled=fs.readFileSync(path.join(__dirname,"../web/controlled-voice.js"),"utf8");
const flush=async()=>{for(let i=0;i<45;i++)await Promise.resolve();};
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};
const approved=(question="What happens after the review?",kind="question")=>({question,summary:"",focus:"",parking_lot:[],memo_findings:[],coverage:[],
  completion:{ready_for_final_check:kind==="final_check"||kind==="complete",complete:kind==="complete"},
  speech_authorization:{approved:true,kind,text:question,revision:"reviewed_revision",completion_allowed:kind==="complete"}});
const reviewAck=()=>({...approved("Let me check that I have everything before we finish.","review_pending"),capture_token:"capture-before-review",coverage_verified:false,review_ticket:"review-ticket-one",agent_run_id:"review-run-one"});
const response=value=>({ok:true,status:200,json:async()=>value});
function setup(){
  const nodes=new Map(),timers=new Map(),frames=new Map(),calls=[],sockets=[],audio=[],utterances=[],revoked=[],team=[],teamOptions=[],recorders=[],notices=[];
  let serial=0,now=0,level=0,route=()=>{throw Error("Unexpected network boundary");},legacyStarts=0;
  function node(id){if(!nodes.has(id))nodes.set(id,{id,hidden:false,checked:false,value:"",textContent:"",dataset:{},children:[],style:{},classList:{toggle(){},add(){},remove(){},contains(){return false;}},setAttribute(){},removeAttribute(){},focus(){},querySelector(){return node(id+"-child");},querySelectorAll(){return[];},append(...values){this.children.push(...values);},replaceChildren(...values){this.children=values;},addEventListener(){}});return nodes.get(id);}
  const track={enabled:true,stopped:0,stop(){this.stopped++;}},stream={getTracks:()=>[track],getAudioTracks:()=>[track]};
  class Recorder{
    static isTypeSupported(type){return type==="audio/webm";}
    constructor(_stream,options){this.listeners={};this.mimeType=options?.mimeType||"audio/webm";this.state="inactive";recorders.push(this);}
    addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
    emit(type,event={}){for(const fn of this.listeners[type]||[])fn(event);}
    start(){this.state="recording";}
    stop(){this.state="inactive";Promise.resolve().then(()=>{this.emit("dataavailable",{data:new Blob(["synthetic audio"])});this.emit("stop");});}
  }
  class AudioContext{
    constructor(){this.destination={};}
    createMediaStreamSource(){return{connect(){},disconnect(){}};}
    createMediaElementSource(){return{connect(){}};}
    createAnalyser(){return{fftSize:1024,connect(){},getFloatTimeDomainData(buffer){buffer.fill(level);}};}
    resume(){return Promise.resolve();}close(){return Promise.resolve();}
  }
  class Audio{
    constructor(url){this.url=url;this.listeners={};this.paused=false;this.playCalls=0;audio.push(this);}
    addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
    emit(type){for(const fn of this.listeners[type]||[])fn();}
    play(){this.playCalls++;this.emit("playing");return Promise.resolve();}
    pause(){this.paused=true;this.emit("pause");}
    removeAttribute(name){if(name==="src")this.url=null;}
  }
  class Socket{
    constructor(url){this.url=url;this.listeners={};this.sent=[];this.closed=false;sockets.push(this);}
    addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
    send(text){this.sent.push(JSON.parse(text));}
    close(){this.closed=true;}
    packet(value){for(const fn of this.listeners.message||[])fn({data:JSON.stringify(value)});}
  }
  class Utterance{constructor(text){this.text=text;}}
  const setTimeout=(fn,ms)=>{const id=++serial;timers.set(id,{fn,ms});return id;},clearTimeout=id=>timers.delete(id);
  const requestAnimationFrame=fn=>{const id=++serial;frames.set(id,fn);return id;},cancelAnimationFrame=id=>frames.delete(id);
  const window={WebSocket:Socket,SpeechSynthesisUtterance:Utterance,AudioContext,MediaRecorder:Recorder,
    navigator:{mediaDevices:{getUserMedia:async()=>stream}},performance:{now:()=>now},setTimeout,clearTimeout,requestAnimationFrame,cancelAnimationFrame,
    addEventListener(){},removeEventListener(){},speechSynthesis:{cancel(){},speak(utterance){utterances.push(utterance);utterance.onstart?.();}},
    CollectorLiveVoice:class{constructor(){legacyStarts++;}async start(){throw Error("Legacy voice must not be selected");}},__notices:notices};
  const context={window,console,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException,Audio,WebSocket:Socket,SpeechSynthesisUtterance:Utterance,
    document:{getElementById:node,querySelectorAll:()=>[],createElement:tag=>node("created-"+tag+"-"+(++serial))},
    setTimeout,clearTimeout,requestAnimationFrame,cancelAnimationFrame,crypto:{randomUUID:()=>String(++serial).padStart(32,"0")},
    URL:{createObjectURL:()=>"blob:synthetic-"+(++serial),revokeObjectURL:url=>revoked.push(url)},atob:input=>Buffer.from(input,"base64").toString("binary"),
    fetch:async(url,options)=>{calls.push({url,options});return route(url,options);}};
  const seam=`
    updateControls=()=>{updatePresence();}; renderTranscript=()=>{}; scrollConversation=()=>{};
    selectConversationView=view=>{conversationUI.view=view;}; scheduleWorkflow=()=>{};
    notice=(message,error)=>window.__notices.push({message,error}); setBusy=value=>{state.busy=value;};
    window.__experience={state,conversationUI,request,snapshot,speakReviewed,stopSpeaking,startLiveConversation,sendAnswer,retryQuestion,pauseCompletionReview,
      setTeam:value=>{agentTeamUI=value;},setDocuments:value=>{documentController=value;}};
  `;
  const source=app.replace(/  init\(\);\s*\}\)\(\);\s*$/,seam+"\n})();");
  assert.notEqual(source,app,"The app test seam must replace only startup");
  vm.createContext(context);vm.runInContext(controlled,context,{filename:"controlled-voice.js"});vm.runInContext(source,context,{filename:"app.js"});
  const t=window.__experience;t.state.started=true;t.state.context={process_name:"Synthetic process",objective:"Test interview"};
  t.state.config={csrf_token:"synthetic-csrf",agent_team:{enabled:true},speech:{enabled:true,voices:[{id:"marin",label:"Marin"}]}};t.state.voiceChoice="ai:marin";
  t.setTeam({render:(value,options)=>{team.push(value);teamOptions.push(options);}});
  const tick=async(ms,nextLevel)=>{now+=ms;level=nextLevel;const pending=[...frames.entries()];frames.clear();for(const[,fn]of pending)fn();await flush();};
  const say=async()=>{await tick(100,.08);await tick(600,.08);await tick(2200,0);};
  const timer=async ms=>{const pair=[...timers].find(([,value])=>value.ms===ms);assert.ok(pair,"Expected a "+ms+"ms timer");timers.delete(pair[0]);await pair[1].fn();await flush();};
  const speech=async transcript=>{const socket=sockets.at(-1);assert.ok(socket,"Expected buffered speech socket");socket.packet({type:"session.created"});const item=socket.sent.find(item=>item.type==="conversation.item.create").item;socket.packet({type:"conversation.item.done",item});socket.packet({type:"response.output_audio.delta",delta:Buffer.from([0,0,0,0]).toString("base64")});socket.packet({type:"response.output_audio_transcript.done",transcript});socket.packet({type:"response.done",response:{status:"completed"}});await flush();};
  const voiceSession={provider:"openai",transport:"openai-realtime-websocket",model:"synthetic-model",client_secret:"synthetic-not-a-secret"};
  const standard=(result=approved())=>(url)=>{if(url==="/api/transcribe")return response({text:"An analyst reviews the file."});if(url==="/api/agent-team/interview")return response(result);if(url==="/api/voice-session")return response(voiceSession);if(url==="/api/agent-team/cancel")return response({});throw Error("Unexpected request "+url);};
  return{t,context,window,node,track,stream,calls,sockets,audio,utterances,revoked,team,teamOptions,recorders,notices,timers,frames,tick,say,timer,speech,voiceSession,standard,
    route:fn=>{route=fn;},legacyStarts:()=>legacyStarts};
}
let passed=0;
const check=async(name,fn)=>{await fn();passed++;};
(async()=>{
  await check("natural playback resolves only on ended",async()=>{
    const h=setup();h.route(()=>response(h.voiceSession));let done=false;const playback=h.t.speakReviewed("Who reviews the file?").then(()=>{done=true;});await flush();
    assert.equal(h.audio.length,0,"Buffered generation cannot leak unverified audio");await h.speech("Who reviews the file?");
    assert.equal(h.audio.length,1);assert.equal(h.audio[0].playCalls,1);assert.equal(done,false,"play() resolution is not playback completion");
    h.audio[0].emit("ended");await playback;assert.equal(done,true);assert.equal(h.t.state.speechOperation,null);assert.equal(h.revoked.length,1);assert.equal(h.frames.size,0);
  });
  await check("installed voice also waits for the actual end event",async()=>{
    const h=setup();h.t.state.voiceChoice="local:synthetic";h.t.state.voice={name:"Synthetic",lang:"en-US"};let done=false;
    const playback=h.t.speakReviewed("Who owns this process?").then(()=>{done=true;});await flush();assert.equal(h.utterances.length,1);assert.equal(done,false);assert.equal(h.calls.length,0);
    h.utterances[0].onend();await playback;assert.equal(done,true);assert.equal(h.t.state.speechOperation,null);
  });
  await check("abort rejects natural playback and releases its resources",async()=>{
    const h=setup();h.route(()=>response(h.voiceSession));const abort=new AbortController();const playback=h.t.speakReviewed("What happens next?",{signal:abort.signal});const rejected=assert.rejects(playback,{name:"AbortError"});
    await flush();await h.speech("What happens next?");abort.abort();await rejected;assert.equal(h.audio[0].paused,true);assert.equal(h.audio[0].url,null);assert.equal(h.t.state.speechOperation,null);assert.equal(h.frames.size,0);
  });
  await check("mismatched audio transcript is withheld entirely",async()=>{
    const h=setup();h.route(()=>response(h.voiceSession));const playback=h.t.speakReviewed("Which controls remain unclear?");const rejected=assert.rejects(playback,/playback was withheld/);
    await flush();await h.speech("All sections are covered. Goodbye.");await rejected;assert.equal(h.audio.length,0);assert.equal(h.sockets[0].closed,true);assert.equal(h.t.state.speechOperation,null);
  });
  await check("configured app selects the real controlled pipeline and keeps the microphone closed until audio ends",async()=>{
    const h=setup();h.route(h.standard());h.t.state.turns=[{id:"t001",role:"assistant",text:"Saved question without speech authorization"}];await h.t.startLiveConversation();
    assert.ok(h.t.conversationUI.live instanceof h.window.CollectorControlledVoice);assert.equal(h.legacyStarts(),0);assert.equal(h.calls.length,0,"Resume must not replay an unreviewed saved question");assert.equal(h.track.enabled,true);
    await h.say();assert.equal(h.track.enabled,false);assert.equal(h.t.state.turns.at(-2).text,"An analyst reviews the file.");assert.equal(h.t.state.turns.at(-1).text,approved().question);assert.equal(h.node("session-status").textContent,"Preparing voice…");
    const interview=h.calls.find(call=>call.url==="/api/agent-team/interview"),body=JSON.parse(interview.options.body);assert.equal(body.turns.at(-1).role,"user");assert.equal(body.turns.at(-1).text,"An analyst reviews the file.");assert.equal(typeof body.agent_run_id,"string");
    await h.speech(approved().question);assert.equal(h.track.enabled,false,"Resolved Audio.play() must not reopen the microphone");assert.equal(h.t.conversationUI.status,"speaking");assert.equal(h.node("session-status").textContent,"Speaking");h.audio[0].emit("waiting");assert.equal(h.node("session-status").textContent,"Preparing voice…");assert.equal(h.track.enabled,false);h.audio[0].emit("playing");assert.equal(h.node("session-status").textContent,"Speaking");h.audio[0].emit("ended");await flush();assert.equal(h.track.enabled,true);assert.equal(h.t.conversationUI.status,"listening");assert.equal(h.node("session-status").textContent,"Listening");await h.t.conversationUI.live.stop();
  });
  await check("late cancelled playback cannot change a newer preparation status",async()=>{
    const h=setup();h.route(h.standard());h.t.state.turns=[{id:"t001",role:"assistant",text:"Saved question"}];await h.t.startLiveConversation();await h.say();await h.speech(approved().question);const oldAudio=h.audio[0];await h.t.conversationUI.live.stop({immediate:true});await h.t.startLiveConversation();await h.say();assert.equal(h.node("session-status").textContent,"Preparing voice…");oldAudio.emit("playing");assert.equal(h.node("session-status").textContent,"Preparing voice…");assert.equal(h.track.enabled,false);await h.t.conversationUI.live.stop({immediate:true});
  });
  await check("stop during reviewed playback cannot reopen the microphone on a late ended event",async()=>{
    const h=setup();h.route(h.standard());h.t.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"}];await h.t.startLiveConversation();await h.say();await h.speech(approved().question);
    await h.t.conversationUI.live.stop({immediate:true});assert.equal(h.track.enabled,false);assert.equal(h.track.stopped,1);assert.equal(h.audio[0].paused,true);h.audio[0].emit("ended");await flush();assert.equal(h.track.enabled,false);assert.equal(h.t.conversationUI.live.active,false);assert.equal(h.t.conversationUI.status,"idle");assert.equal(h.t.state.turns.length,3);
  });
  await check("new voice opening passes through team review before playback and listening",async()=>{
    const h=setup();h.route(h.standard());const starting=h.t.startLiveConversation();await flush();
    assert.equal(h.calls[0].url,"/api/agent-team/interview");assert.equal(JSON.parse(h.calls[0].options.body).action,"start");assert.equal(h.t.state.turns.length,1);assert.equal(h.t.state.turns[0].role,"assistant");assert.equal(h.track.enabled,false);
    await h.speech(approved().question);assert.equal(h.track.enabled,false);h.audio[0].emit("ended");await starting;assert.equal(h.track.enabled,true);assert.equal(h.t.conversationUI.status,"listening");await h.t.conversationUI.live.stop();
  });
  await check("unapproved response never reaches app transcript or speech",async()=>{
    const h=setup(),result=approved("We have covered everything.","complete");delete result.speech_authorization;h.route(h.standard(result));h.t.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"}];await h.t.startLiveConversation();await h.say();
    assert.equal(h.t.state.turns.length,2);assert.equal(h.t.state.turns.at(-1).role,"user");assert.equal(h.sockets.length,0);assert.equal(h.audio.length,0);assert.equal(h.track.stopped,1);assert.match(h.notices.at(-1).message,/speech check/);
  });
  await check("authorization cannot override an incomplete server completion assessment",async()=>{
    const h=setup(),result=approved("The interview is complete.","complete");result.completion.complete=false;h.route(h.standard(result));h.t.state.turns=[{id:"t001",role:"assistant",text:"Which sections are still unclear?"}];await h.t.startLiveConversation();await h.say();
    assert.equal(h.t.state.turns.length,2);assert.equal(h.t.state.closure.confirmed,false);assert.equal(h.sockets.length,0);assert.equal(h.track.stopped,1);assert.match(h.notices.at(-1).message,/completion check/);
  });
  await check("current team requests route and publish their real status",async()=>{
    const h=setup(),pending=deferred();let runId;h.route((url,options)=>{const data=JSON.parse(options.body);if(url==="/api/agent-team/workflow"){runId=data.agent_run_id;return pending.promise;}if(url==="/api/agent-team/status"){assert.equal(data.run_id,runId);assert.equal(data.document_scope,"scope-test");assert.equal(options.headers["X-CSRF-Token"],"synthetic-csrf");return response({run_id:runId,status:"running",agents:[{role:"coverage_reviewer",status:"running"}],events:[]});}throw Error(url);});
    const result=h.t.request("/api/workflow",{...h.t.snapshot(),document_scope:"scope-test"});await h.timer(150);assert.equal(h.team.length,1);assert.equal(h.team[0].status,"running");
    pending.resolve(response({agent_team:{run_id:runId,status:"completed",agents:[],events:[]},workflow:{steps:[]}}));await result;assert.equal(h.team.at(-1).status,"completed");assert.equal([...h.timers.values()].filter(timer=>timer.ms===900||timer.ms===150).length,0);
  });
  await check("a streamed provisional question shows while the lead finishes, then clears",async()=>{
    const h=setup(),pending=deferred();let runId;h.route((url,options)=>{const data=JSON.parse(options.body);if(url==="/api/agent-team/interview"){runId=data.agent_run_id;return pending.promise;}if(url==="/api/agent-team/status")return response({run_id:runId,status:"running",agents:[{role:"lead_interviewer",status:"running"}],events:[],provisional_question:"What starts the intake?"});throw Error(url);});
    const lead=h.t.request("/api/interview",h.t.snapshot());await h.timer(150);assert.equal(h.t.state.provisionalQuestion,"What starts the intake?");
    pending.resolve(response({...approved("What starts the intake?"),agent_team:{run_id:runId,status:"completed",agents:[],events:[]}}));await lead;await flush();assert.equal(h.t.state.provisionalQuestion,null,"The accepted response replaces the provisional text");
  });
  await check("a background map never shows a provisional question",async()=>{
    const h=setup(),pending=deferred();let runId;h.route((url,options)=>{const data=JSON.parse(options.body);if(url==="/api/agent-team/workflow"){runId=data.agent_run_id;return pending.promise;}if(url==="/api/agent-team/status")return response({run_id:runId,status:"running",agents:[],events:[],provisional_question:"Leaked?"});throw Error(url);});
    const map=h.t.request("/api/workflow",h.t.snapshot());await h.timer(150);assert.equal(h.t.state.provisionalQuestion,null);
    pending.resolve(response({agent_team:{run_id:runId,status:"completed",agents:[],events:[]},workflow:{steps:[]}}));await map;
  });
  await check("newer run owns the panel when an older completion arrives",async()=>{
    const h=setup(),first=deferred(),second=deferred(),ids=[];h.route((url,options)=>{assert.equal(url,"/api/agent-team/workflow");ids.push(JSON.parse(options.body).agent_run_id);return ids.length===1?first.promise:second.promise;});
    const old=h.t.request("/api/workflow",h.t.snapshot()),fresh=h.t.request("/api/workflow",h.t.snapshot());second.resolve(response({agent_team:{run_id:ids[1],status:"completed"}}));await fresh;first.resolve(response({agent_team:{run_id:ids[0],status:"completed"}}));await old;
    assert.equal(h.team.length,1);assert.equal(h.team[0].run_id,ids[1]);
  });
  await check("background workflow cannot take over an active interviewer status",async()=>{
    const h=setup(),interview=deferred(),workflow=deferred(),ids={};h.route((url,options)=>{const runId=JSON.parse(options.body).agent_run_id;if(url==="/api/agent-team/interview"){ids.interview=runId;return interview.promise;}if(url==="/api/agent-team/workflow"){ids.workflow=runId;return workflow.promise;}return response({run_id:JSON.parse(options.body).run_id,status:"completed"});});
    const lead=h.t.request("/api/interview",h.t.snapshot()),background=h.t.request("/api/workflow",h.t.snapshot());workflow.resolve(response({agent_team:{run_id:ids.workflow,status:"completed"}}));await background;await flush();assert.equal(h.team.length,0);
    interview.resolve(response({agent_team:{run_id:ids.interview,status:"completed"}}));await lead;await flush();assert.ok(h.team.length>0);assert.ok(h.team.every(item=>item.run_id===ids.interview));
  });
  await check("an in-flight status poll is ignored after the session changes",async()=>{
    const h=setup(),work=deferred(),poll=deferred();h.route(url=>url==="/api/agent-team/status"?poll.promise:work.promise);
    const request=h.t.request("/api/workflow",h.t.snapshot());const timer=[...h.timers.entries()].find(([,value])=>value.ms===150);assert.ok(timer);h.timers.delete(timer[0]);const polling=timer[1].fn();await flush();h.t.state.generation++;
    poll.resolve(response({run_id:"old",status:"completed"}));await polling;work.resolve(response({agent_team:{run_id:"old",status:"completed"}}));await request;await flush();assert.equal(h.team.length,0);
  });
  await check("request abort cancels its owned server run and suppresses late completion",async()=>{
    const h=setup(),pending=deferred(),controller=new AbortController();h.route((url,options)=>url==="/api/agent-team/cancel"?response({}):url==="/api/agent-team/status"?response({run_id:JSON.parse(options.body).run_id,status:"blocked",cancelled:true}):pending.promise);
    const promise=h.t.request("/api/workflow",h.t.snapshot(),{signal:controller.signal}),rejected=assert.rejects(promise,{name:"AbortError"});controller.abort();pending.resolve(response({agent_team:{run_id:"late",status:"completed"}}));await rejected;await flush();
    assert.ok(h.team.every(status=>status.status!=="completed"));assert.equal(h.calls.filter(call=>call.url==="/api/agent-team/cancel").length,1);assert.equal(h.timers.size,0);
  });
  await check("typed stale completion cannot change the new session",async()=>{
    const h=setup(),pending=deferred();h.route(()=>pending.promise);h.node("answer-text").value="The original session answer.";const sending=h.t.sendAnswer({preventDefault(){}});await flush();
    h.t.state.generation++;h.t.state.turns=[{id:"new001",role:"user",text:"A new session account."}];h.t.state.closure={asked:false,confirmed:false};h.t.state.completion=null;
    pending.resolve(response({...approved("The interview is finished.","complete"),closure:{asked:true,confirmed:true},agent_team:{run_id:"stale",status:"completed"}}));await sending;
    assert.equal(h.t.state.turns.length,1);assert.equal(h.t.state.turns[0].text,"A new session account.");assert.equal(h.t.state.closure.confirmed,false);assert.equal(h.t.state.completion,null);assert.equal(h.team.length,0);assert.equal(h.sockets.length,0);
  });
  await check("voice stale completion cannot close or speak over a newer correction",async()=>{
    const h=setup(),pending=deferred();h.route(url=>url==="/api/transcribe"?response({text:"The original answer."}):pending.promise);h.t.state.turns=[{id:"t001",role:"assistant",text:"What is the finished condition?"}];await h.t.startLiveConversation();await h.say();
    h.t.state.turns.push({id:"newer",role:"user",text:"Correction: the final approval is still missing."});pending.resolve(response({...approved("Everything is complete.","complete"),closure:{asked:true,confirmed:true}}));await flush();
    assert.equal(h.t.state.turns.length,3);assert.equal(h.t.state.turns.at(-1).id,"newer");assert.equal(h.t.state.closure.confirmed,false);assert.equal(h.sockets.length,0);assert.equal(h.track.stopped,1);assert.match(h.notices.at(-1).message,/conversation changed/);
  });
  await check("missing controlled module does not fall back to the legacy speaker",async()=>{
    const h=setup();delete h.window.CollectorControlledVoice;await h.t.startLiveConversation();assert.equal(h.legacyStarts(),0);assert.equal(h.t.conversationUI.live,null);assert.equal(h.calls.length,0);assert.match(h.notices.at(-1).message,/couldn’t start/);
  });
  await check("typed acknowledgement is applied once before deliberate review; concurrent retry does nothing",async()=>{
    const h=setup(),review=deferred();h.route(url=>url==="/api/agent-team/interview"?response(reviewAck()):url==="/api/agent-team/review"?review.promise:response({}));h.node("answer-text").value="That completes the remaining detail.";
    const sending=h.t.sendAnswer({preventDefault(){}});await flush();assert.equal(h.t.state.turns.at(-1).text,reviewAck().question);assert.equal(h.t.state.coverageVerified,false);assert.equal(h.t.state.busy,true);
    const request=h.calls.find(call=>call.url==="/api/agent-team/review"),payload=JSON.parse(request.options.body);assert.equal(payload.review_ticket,"review-ticket-one");assert.equal(payload.capture_token,"capture-before-review");assert.equal(payload.turns.at(-1).text,reviewAck().question);assert.equal(payload.agent_run_id,undefined,"The ticket owns the original run");
    await h.t.retryQuestion();await h.t.retryQuestion();assert.equal(h.calls.filter(call=>call.url==="/api/agent-team/review").length,1);
    review.resolve(response({...approved("Have I missed anything else?","final_check"),capture_token:"capture-reviewed",coverage_verified:true}));await sending;
    assert.equal(h.t.state.turns.filter(turn=>turn.text===reviewAck().question).length,1);assert.equal(h.t.state.coverageVerified,true);assert.equal(h.t.snapshot().capture_token,"capture-reviewed");assert.equal(h.t.state.busy,false);
  });
  await check("a process title set by the working map during the review does not discard the review",async()=>{
    const h=setup(),review=deferred();h.route(url=>url==="/api/agent-team/interview"?response(reviewAck()):url==="/api/agent-team/review"?review.promise:response({}));h.node("answer-text").value="That completes the remaining detail.";
    const sending=h.t.sendAnswer({preventDefault(){}});await flush();assert.equal(h.t.state.busy,true);
    h.t.state.context.process_name="Named by the working map";
    review.resolve(response({...approved("Have I missed anything else?","final_check"),capture_token:"capture-reviewed",coverage_verified:true}));await sending;
    assert.equal(h.t.state.coverageVerified,true,"The review result is applied despite the title change");assert.equal(h.t.state.turns.at(-1).text,"Have I missed anything else?");assert.ok(!h.notices.some(item=>/conversation changed/.test(item.message)));
  });
  await check("failed review retries its ticket with the visible failure notice and retains confirmation continuity",async()=>{
    const h=setup();let reviews=0,interviews=0;const finalQuestion="Have I missed anything else?",failure={...approved("The review could not finish. Your capture is saved.","pause"),preserve_capture:true,review_retry_required:true,review_ticket:"review-ticket-one",capture_token:"capture-failed",coverage_verified:false};
    h.route((url,options)=>{
      if(url==="/api/agent-team/interview"){
        if(++interviews===1)return response(reviewAck());
        const confirmation=JSON.parse(options.body);assert.equal(confirmation.capture_token,"capture-retried");assert.equal(confirmation.turns.at(-1).text,"No");assert.equal(confirmation.turns.at(-2).text,finalQuestion);assert.ok(confirmation.turns.some(turn=>turn.text===failure.question));
        return response({...approved("The interview is complete.","complete"),coverage_verified:true,no_new_run:true,closure:{asked:true,confirmed:true}});
      }
      return url==="/api/agent-team/review"?response(++reviews===1?failure:{...approved(finalQuestion,"final_check"),capture_token:"capture-retried",coverage_verified:true}):response({});
    });h.node("answer-text").value="There are no more missing facts.";await h.t.sendAnswer({preventDefault(){}});
    assert.equal(h.node("retry-question").hidden,false);assert.equal(h.t.state.coverageVerified,false);await h.t.retryQuestion();
    const requests=h.calls.filter(call=>call.url==="/api/agent-team/review");assert.equal(requests.length,2);const retry=JSON.parse(requests[1].options.body);assert.equal(retry.retry_review,true);assert.equal(retry.review_ticket,"review-ticket-one");assert.equal(retry.capture_token,"capture-failed");assert.equal(retry.turns.at(-1).text,failure.question);assert.equal(retry.turns.at(-2).text,reviewAck().question);
    assert.equal(h.calls.filter(call=>call.url==="/api/agent-team/interview").length,1);assert.equal(h.t.state.turns.filter(turn=>turn.text===reviewAck().question).length,1);assert.equal(h.sockets.length,0);assert.equal(h.t.state.turns.at(-1).text,finalQuestion);
    h.node("answer-text").value="No";await h.t.sendAnswer({preventDefault(){}});assert.equal(reviews,2,"Confirmation must not trigger another completion review");assert.equal(h.t.state.closure.confirmed,true);
  });
  await check("transport retry reuses ticket without authorizing a new paid review",async()=>{
    const h=setup();let reviews=0;h.route(url=>url==="/api/agent-team/interview"?response(reviewAck()):url==="/api/agent-team/review"?(++reviews===1?Promise.reject(Error("Synthetic disconnect")):response(approved("Which handoff remains unclear?"))):response({}));h.node("answer-text").value="That is the last detail.";await h.t.sendAnswer({preventDefault(){}});assert.equal(h.node("retry-question").hidden,false);await h.t.retryQuestion();
    const retry=JSON.parse(h.calls.filter(call=>call.url==="/api/agent-team/review")[1].options.body);assert.equal(retry.retry_review,undefined);assert.equal(retry.review_ticket,"review-ticket-one");assert.equal(h.t.state.turns.filter(turn=>turn.text===reviewAck().question).length,1);
  });
  await check("voice acknowledgement ends before the specialist request begins",async()=>{
    const h=setup(),review=deferred();h.route(url=>url==="/api/agent-team/interview"?response(reviewAck()):url==="/api/agent-team/review"?review.promise:url==="/api/transcribe"?response({text:"That fills the last gap."}):url==="/api/voice-session"?response(h.voiceSession):response({}));h.t.state.turns=[{id:"t001",role:"assistant",text:"What evidence is retained?"}];await h.t.startLiveConversation();await h.say();
    assert.equal(h.calls.filter(call=>call.url==="/api/agent-team/review").length,0);await h.speech(reviewAck().question);assert.equal(h.calls.filter(call=>call.url==="/api/agent-team/review").length,0,"Generation and play() cannot start review");h.audio[0].emit("ended");await flush();assert.equal(h.calls.filter(call=>call.url==="/api/agent-team/review").length,1);assert.equal(h.track.enabled,false);
    review.resolve(response({...approved("Is there anything else I should include?","final_check"),capture_token:"reviewed",coverage_verified:true}));await flush();await h.speech("Is there anything else I should include?");assert.equal(h.track.enabled,false);h.audio[1].emit("ended");await flush();assert.equal(h.track.enabled,true);assert.equal(h.t.state.turns.filter(turn=>turn.text===reviewAck().question).length,1);await h.t.conversationUI.live.stop();
  });
  await check("stopping during acknowledgement prevents the specialist request",async()=>{
    const h=setup();h.route(url=>url==="/api/agent-team/interview"?response(reviewAck()):url==="/api/transcribe"?response({text:"That is all."}):url==="/api/voice-session"?response(h.voiceSession):response({}));h.t.state.turns=[{id:"t001",role:"assistant",text:"Any other controls?"}];await h.t.startLiveConversation();await h.say();await h.speech(reviewAck().question);await h.t.conversationUI.live.stop();h.audio[0].emit("ended");await flush();
    assert.equal(h.calls.filter(call=>call.url==="/api/agent-team/review").length,0);assert.equal(h.track.enabled,false);assert.equal(h.track.stopped,1);
  });
  await check("stopped deliberate review rejects late completion and retains accepted answers",async()=>{
    const h=setup(),review=deferred();h.route(url=>url==="/api/agent-team/interview"?response(reviewAck()):url==="/api/agent-team/review"?review.promise:url==="/api/transcribe"?response({text:"The answer is retained."}):url==="/api/voice-session"?response(h.voiceSession):response({}));h.t.state.turns=[{id:"t001",role:"assistant",text:"What remains?"}];await h.t.startLiveConversation();await h.say();await h.speech(reviewAck().question);h.audio[0].emit("ended");await flush();await h.t.conversationUI.live.stop();
    const request=h.calls.find(call=>call.url==="/api/agent-team/review");assert.equal(request.options.signal.aborted,true);review.resolve(response({...approved("The process is fully covered.","complete"),coverage_verified:true,closure:{asked:true,confirmed:true}}));await flush();assert.equal(h.t.state.turns.length,3);assert.equal(h.t.state.turns[1].text,"The answer is retained.");assert.equal(h.sockets.length,1);assert.equal(h.t.state.closure.confirmed,false);assert.equal(h.track.enabled,false);
  });
  await check("a correction during deliberate review invalidates its late result",async()=>{
    const h=setup(),review=deferred();h.route(url=>url==="/api/agent-team/interview"?response(reviewAck()):url==="/api/agent-team/review"?review.promise:response({}));h.node("answer-text").value="Last original detail.";const sending=h.t.sendAnswer({preventDefault(){}});await flush();h.t.state.turns.push({id:"correction",role:"user",text:"The exception owner is still unknown."});review.resolve(response({...approved("Everything is finished.","complete"),coverage_verified:true,closure:{asked:true,confirmed:true}}));await sending;
    assert.equal(h.t.state.turns.at(-1).id,"correction");assert.equal(h.t.state.coverageVerified,false);assert.equal(h.t.state.closure.confirmed,false);
  });
  await check("owned cached confirmation reuses prior review status and polls its actual run",async()=>{
    const h=setup(),pending=deferred();h.route((url,options)=>url==="/api/agent-team/interview"?pending.promise:response({run_id:JSON.parse(options.body).run_id,status:"completed",agents:[],events:[]}));
    const request=h.t.request("/api/interview",h.t.snapshot());await h.timer(150);const speculative=h.team[0].run_id;assert.notEqual(speculative,"actual-reviewed-run");pending.resolve(response({...approved("Thank you. The interview is complete.","complete"),no_new_run:true,agent_run_id:"actual-reviewed-run",agent_team:{run_id:"actual-reviewed-run",status:"completed",agents:[],events:[]}}));await request;await flush();
    assert.equal(h.team.at(-1).run_id,"actual-reviewed-run");assert.equal(h.teamOptions.at(-1).reuse,true);assert.equal(JSON.parse(h.calls.filter(call=>call.url==="/api/agent-team/status").at(-1).options.body).run_id,"actual-reviewed-run");
  });
  await check("typed acknowledgement cannot claim completed review before its review request",async()=>{
    const h=setup(),ack=reviewAck();ack.coverage_verified=true;h.route(()=>response(ack));h.node("answer-text").value="Still unreviewed.";await h.t.sendAnswer({preventDefault(){}});assert.equal(h.t.state.turns.length,1);assert.equal(h.t.state.turns[0].role,"user");assert.equal(h.t.state.coverageVerified,false);assert.equal(h.calls.filter(call=>call.url==="/api/agent-team/review").length,0);
  });
  for(const purpose of ["partial",undefined])await check("typed partial review accepts only its purpose-bound acknowledgement",async()=>{
    const h=setup(),ack={...reviewAck(),question:"Let me check what we have and keep the unanswered parts open.",...(purpose?{review_purpose:purpose}:{})};ack.speech_authorization.text=ack.question;h.route(url=>url==="/api/agent-team/interview"?response(ack):url==="/api/agent-team/review"?response(approved("We can pause with the unanswered sections open.","pause")):response({}));h.node("answer-text").value="I cannot explain the remaining sections.";await h.t.sendAnswer({preventDefault(){}});assert.equal(h.calls.filter(call=>call.url==="/api/agent-team/review").length,purpose?1:0);assert.equal(h.t.state.closure.confirmed,false);assert.equal(h.t.state.coverageVerified,false);
  });
  await check("pause cancels its review immediately and fresh resume survives late completion",async()=>{
    const h=setup(),oldReview=deferred(),freshLead=deferred();let leads=0;h.route((url,options)=>{
      if(url==="/api/agent-team/interview"){leads++;if(leads===1)return response(reviewAck());assert.equal(JSON.parse(options.body).action,"close");return freshLead.promise;}
      if(url==="/api/agent-team/review")return oldReview.promise;
      return response({});
    });h.node("answer-text").value="The original accepted answer.";const first=h.t.sendAnswer({preventDefault(){}});await flush();h.node("answer-text").value="Keep this unsent clarification.";const transcript=JSON.stringify(h.t.state.turns),findings=JSON.stringify(h.t.state.memo_findings);h.t.pauseCompletionReview();await flush();
    assert.equal(h.t.state.busy,false);assert.equal(h.t.state.coverageVerified,false);assert.equal(h.t.state.closure.confirmed,false);assert.equal(h.node("retry-question").textContent,"Resume review");assert.equal(h.node("answer-text").value,"Keep this unsent clarification.");assert.equal(JSON.stringify(h.t.state.turns),transcript);assert.equal(JSON.stringify(h.t.state.memo_findings),findings);assert.equal(h.calls.filter(call=>call.url==="/api/agent-team/cancel").length,1,"Cancel must reach the server before an uncooperative old transport resolves");
    const resuming=h.t.retryQuestion();await flush();assert.equal(h.t.state.busy,true);oldReview.resolve(response({...approved("Everything is finished.","complete"),coverage_verified:true,closure:{asked:true,confirmed:true}}));await first;assert.equal(h.t.state.busy,true,"The paused request must not clear a newer request's busy state");assert.equal(JSON.stringify(h.t.state.turns),transcript);assert.equal(h.t.state.closure.confirmed,false);
    freshLead.resolve(response(approved("Which exception still needs clarification?")));await resuming;assert.equal(h.t.state.busy,false);assert.equal(h.t.state.turns.at(-1).text,"Which exception still needs clarification?");assert.equal(h.node("answer-text").value,"Keep this unsent clarification.");assert.equal(h.calls.filter(call=>call.url==="/api/agent-team/review").length,1,"Resume obtains fresh authority instead of replaying the cancelled ticket");
  });
  console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,physical_audio:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
