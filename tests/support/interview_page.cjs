"use strict";
// Shared page double for the typed-interview suites: the real web/app.js (and, on request, its
// sibling browser modules) behind a minimal DOM, manual timers, a manual clock and a scripted
// network boundary. Only display, browser hardware and network boundaries are faked.
// No browser, provider, package or network is used. This file is a helper, not a suite: it sits
// in a subfolder so that tests/run_all.cjs does not run it by itself.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const web=name=>fs.readFileSync(path.join(__dirname,"..","..","web",name),"utf8");
const flush=async(turns=60)=>{for(let i=0;i<turns;i++)await Promise.resolve();};
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};
const response=(value,status=200)=>({ok:status>=200&&status<300,status,json:async()=>value,blob:async()=>value});
// What the server returns for an interview turn, in the shape applyInterview accepts.
const approved=(question="What happens after the review?",kind="question")=>({question,summary:"",focus:"",parking_lot:[],memo_findings:[],coverage:[],
  completion:{ready_for_final_check:kind==="final_check"||kind==="complete",complete:kind==="complete"},
  speech_authorization:{approved:true,kind,text:question,revision:"reviewed_revision",completion_allowed:kind==="complete"}});
const REVIEW_ACK="Let me check that I have everything before we finish.";
const reviewAck=()=>({...approved(REVIEW_ACK,"review_pending"),capture_token:"capture-before-review",coverage_verified:false,review_ticket:"review-ticket-one",agent_run_id:"review-run-one"});

// options.modules: extra web/*.js files evaluated before app.js (for example "document-intake.js").
// options.expose:  names from inside the app closure to hand to the test, as "a,b,c".
// options.seam:    further statements evaluated inside the app closure in place of init().
// options.realNotice: notices are recorded and also drawn by the app's own notice() (banner included).
function setup(options={}){
  const nodes=new Map(),timers=new Map(),intervals=new Map(),frames=new Map(),calls=[],notices=[],views=[],focused=[],scrolls=[],recorders=[],contexts=[],tracks=[],audio=[],sockets=[],utterances=[],revoked=[],documentListeners={};
  let serial=0,now=0,level=0,route=()=>{throw Error("Unexpected network boundary");},microphone=null;
  const document={activeElement:null,hidden:false,visibilityState:"visible",querySelectorAll:()=>[],
    addEventListener(type,fn){(documentListeners[type]??=[]).push(fn);},
    removeEventListener(type,fn){documentListeners[type]=(documentListeners[type]||[]).filter(item=>item!==fn);}};
  function node(id){
    if(!nodes.has(id)){
      const classes=new Set();
      nodes.set(id,{id,hidden:false,checked:false,disabled:false,value:"",textContent:"",dataset:{},children:[],style:{},attributes:{},listeners:{},
        classList:{toggle(name,on){const yes=on===undefined?!classes.has(name):Boolean(on);if(yes)classes.add(name);else classes.delete(name);return yes;},add(name){classes.add(name);},remove(name){classes.delete(name);},contains:name=>classes.has(name)},
        setAttribute(name,value){this.attributes[name]=String(value);},getAttribute(name){return this.attributes[name]??null;},removeAttribute(name){delete this.attributes[name];},
        focus(){document.activeElement=this;focused.push(id);},contains(other){return other===this;},scrollIntoView(){},
        querySelector(){return node(id+"-child");},querySelectorAll(){return[];},
        append(...values){this.children.push(...values);},replaceChildren(...values){this.children=values;},
        addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);},
        showModal(){this.open=true;},close(){this.open=false;this.onclose?.();},
        click(){for(const fn of this.listeners.click||[])fn({target:this,preventDefault(){}});}});
    }
    return nodes.get(id);
  }
  document.getElementById=node;document.createElement=tag=>node("created-"+tag+"-"+(++serial));document.body=node("body");
  // One microphone per getUserMedia call, so a test can see each one released.
  const openMicrophone=()=>{const track={enabled:true,stopped:0,stop(){this.stopped++;}};tracks.push(track);return{getTracks:()=>[track],getAudioTracks:()=>[track]};};
  // A recorder started with a time slice delivers a slice of audio on that period for as long as
  // it records, whether or not the page is drawn (the harness clock decides when), then one last
  // slice and "stop". stop() is asynchronous, as in a browser.
  class Recorder{
    static isTypeSupported(type){return type==="audio/webm";}
    constructor(stream,settings){this.stream=stream;this.listeners={};this.mimeType=settings?.mimeType||"audio/webm";this.state="inactive";this.slices=0;recorders.push(this);}
    addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
    emit(type,event={}){for(const fn of this.listeners[type]||[])fn(event);}
    start(slice){this.state="recording";this.slice=slice;if(slice)this.sliceTimer=setInterval(()=>{if(this.state==="recording"){this.slices++;this.emit("dataavailable",{data:new Blob(["slice "])});}},slice);}
    stop(){if(this.state==="inactive")throw new DOMException("The recorder is not recording.","InvalidStateError");this.end();}
    // Also what a browser does by itself when the microphone track ends.
    end(){this.state="inactive";clearInterval(this.sliceTimer);Promise.resolve().then(()=>{this.emit("dataavailable",{data:new Blob(["last slice"])});this.emit("stop");});}
  }
  // The microphone signal over time, as root-mean-square amplitude: setLevel() changes it from the
  // current instant on. An analyser read-out holds the most recent window of that signal, so a
  // sample taken now still contains a sound that ended a moment ago, as a real analyser does.
  const levels=[{at:-Infinity,value:0}],SAMPLE_RATE=48000;
  const levelAt=time=>{let value=0;for(const change of levels){if(change.at<=time)value=change.value;else break;}return value;};
  class AudioContext{
    constructor(){this.destination={};this.closed=0;this.state="running";this.sampleRate=SAMPLE_RATE;contexts.push(this);}
    createMediaStreamSource(){return{connect(){},disconnect(){}};}
    createMediaElementSource(){return{connect(){}};}
    createAnalyser(){return{fftSize:1024,connect(){},
      getFloatTimeDomainData(buffer){buffer.fill(level);},
      getByteTimeDomainData(buffer){const step=128;for(let start=0;start<buffer.length;start+=step){const age=(buffer.length-start-step/2)/SAMPLE_RATE*1000;buffer.fill(Math.round(128+levelAt(now-age)*128),start,Math.min(buffer.length,start+step));}}};}
    resume(){return Promise.resolve();}
    close(){this.closed++;this.state="closed";return Promise.resolve();}
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
    constructor(url){this.url=url;this.listeners={};this.sent=[];this.closed=false;this.readyState=1;sockets.push(this);}
    addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
    removeEventListener(type,fn){this.listeners[type]=(this.listeners[type]||[]).filter(item=>item!==fn);}
    send(text){this.sent.push(JSON.parse(text));}
    close(){this.closed=true;}
    packet(value){for(const fn of [...(this.listeners.message||[])])fn({data:JSON.stringify(value)});}
  }
  class Utterance{constructor(text){this.text=text;}}
  const setTimeout=(fn,ms)=>{const id=++serial;timers.set(id,{fn,ms});return id;},clearTimeout=id=>timers.delete(id);
  const setInterval=(fn,ms)=>{const id=++serial;intervals.set(id,{fn,ms});return id;},clearInterval=id=>intervals.delete(id);
  const requestAnimationFrame=fn=>{const id=++serial;frames.set(id,fn);return id;},cancelAnimationFrame=id=>frames.delete(id);
  const context={console,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException,Audio,document,
    WebSocket:Socket,SpeechSynthesisUtterance:Utterance,AudioContext,MediaRecorder:Recorder,
    navigator:{mediaDevices:{getUserMedia:async constraints=>{if(microphone)return microphone(constraints);return openMicrophone();}}},
    performance:{now:()=>now},setTimeout,clearTimeout,setInterval,clearInterval,requestAnimationFrame,cancelAnimationFrame,confirm:()=>true,
    addEventListener(){},removeEventListener(){},matchMedia:()=>({matches:false,addEventListener(){}}),
    speechSynthesis:{cancel(){},getVoices:()=>[],speak(utterance){utterances.push(utterance);utterance.onstart?.();}},
    crypto:{randomUUID:()=>String(++serial).padStart(32,"0")},
    URL:{createObjectURL:()=>"blob:synthetic-"+(++serial),revokeObjectURL:url=>revoked.push(url)},atob:input=>Buffer.from(input,"base64").toString("binary"),
    fetch:async(url,request)=>{calls.push({url,options:request});return route(url,request);},
    __notices:notices,__views:views,__scrolls:scrolls};
  context.window=context;
  const names=["state","conversationUI","request","snapshot","sendAnswer","retryQuestion","skipQuestion","finalCheck","pauseCompletionReview","stopSpeaking",...(options.expose||"").split(",").map(name=>name.trim()).filter(Boolean)];
  const seam=`
    const realUpdateControls=updateControls;
    updateControls=()=>{updatePresence();updateSaveHint();}; renderTranscript=()=>{}; scheduleWorkflow=()=>{};
    scrollConversation=()=>{window.__scrolls.push(conversationUI.view);};
    selectConversationView=view=>{conversationUI.view=view;window.__views.push(view);};
    ${options.realNotice?"const shownNotice=notice;":""}
    notice=(message,error=false,kind="general")=>{window.__notices.push({message,error:Boolean(error),kind});${options.realNotice?"shownNotice(message,error,kind);":""}}; setBusy=value=>{state.busy=value;};
    ${options.seam||""}
    window.__page={${[...new Set(names)].map(name=>`${name}:typeof ${name}==="undefined"?undefined:${name}`).join(",")},realUpdateControls,
      pendingReview:()=>pendingCompletionReview,setTeam:value=>{agentTeamUI=value;},setDocuments:value=>{documentController=value;}};
  `;
  const app=web("app.js"),source=app.replace(/  init\(\);\s*\}\)\(\);\s*$/,seam+"\n})();");
  assert.notEqual(source,app,"The app test seam must replace only startup");
  vm.createContext(context);
  for(const name of options.modules||[])vm.runInContext(web(name),context,{filename:name});
  vm.runInContext(source,context,{filename:"app.js"});
  const t=context.__page;
  t.state.started=true;t.state.context={process_name:"Synthetic process",objective:"Test interview"};
  t.state.config={csrf_token:"synthetic-csrf",api_configured:true,agent_team:{enabled:true},speech:{enabled:true,voices:[{id:"marin",label:"Marin"}]}};t.state.voiceChoice="ai:marin";
  t.setTeam({render(){}});
  // Time moves only when a test says so. advance() runs the due interval callbacks in order;
  // frame() delivers one animation frame, as a visible page does; a hidden page delivers none.
  const advance=async ms=>{
    const end=now+ms;
    for(;;){
      let next=null;
      for(const [id,item] of intervals){item.due??=now+item.ms;if(item.due<=end&&(!next||item.due<next.due))next={id,...item};}
      if(!next)break;
      now=next.due;const live=intervals.get(next.id);if(live){live.due=now+live.ms;live.fn();}
      await flush(4);
    }
    now=end;await flush(4);
  };
  const frame=async()=>{const pending=[...frames.entries()];frames.clear();for(const [,fn] of pending)fn();await flush(4);};
  // A page that is being drawn: time passes and an animation frame is delivered every 20 ms.
  const visible=async ms=>{for(let passed=0;passed<ms;passed+=20){await advance(Math.min(20,ms-passed));await frame();}};
  // A suspended page: time passes and nothing runs. Timers that came due fire once, late, afterwards.
  const suspend=ms=>{now+=ms;for(const item of intervals.values())if(item.due!==undefined&&item.due<now)item.due=now;};
  // at: when the change happened, for a change that took place while nothing was running.
  const setLevel=(value,at=now)=>{level=value;levels.push({at,value});levels.sort((a,b)=>a.at-b.at);};
  const timer=async ms=>{const pair=[...timers].find(([,value])=>value.ms===ms);assert.ok(pair,"Expected a "+ms+"ms timer");timers.delete(pair[0]);await pair[1].fn();await flush();};
  const emit=type=>{for(const fn of [...(documentListeners[type]||[])])fn({type});};
  // The natural voice: what /api/voice-session returns, and the provider's side of the speech socket
  // reading `transcript` aloud (a few bytes of audio, then completion).
  const voiceSession={provider:"openai",transport:"openai-realtime-websocket",model:"synthetic-model",client_secret:"synthetic-not-a-secret"};
  const speech=async(transcript,socket=sockets.at(-1))=>{assert.ok(socket,"Expected a speech socket");socket.packet({type:"session.created"});await flush();const item=socket.sent.find(sent=>sent.type==="conversation.item.create").item;socket.packet({type:"conversation.item.done",item});socket.packet({type:"response.output_audio.delta",delta:Buffer.from([0,0,0,0]).toString("base64")});socket.packet({type:"response.output_audio_transcript.done",transcript});socket.packet({type:"response.done",response:{status:"completed"}});await flush();};
  return{t,context,document,node,nodes,calls,notices,views,focused,scrolls,recorders,contexts,tracks,audio,sockets,utterances,revoked,timers,intervals,frames,documentListeners,
    advance,frame,visible,suspend,timer,emit,speech,voiceSession,now:()=>now,setLevel,route:fn=>{route=fn;},microphone:fn=>{microphone=fn;},openMicrophone,
    requests:url=>calls.filter(call=>call.url===url),body:call=>JSON.parse(call.options.body)};
}
// Runs a suite body. A promise that never settles lets Node exit with code 0 and no output, which
// would read as a pass, so a suite that stops before its last check fails here instead.
function run(body){
  let finished=false;
  process.on("exit",()=>{if(!finished&&!process.exitCode){console.error("The suite stopped before its last check: a promise never settled.");process.exitCode=1;}});
  return body().then(()=>{finished=true;},error=>{finished=true;console.error(error);process.exitCode=1;});
}
module.exports={setup,run,flush,deferred,response,approved,reviewAck,REVIEW_ACK};
