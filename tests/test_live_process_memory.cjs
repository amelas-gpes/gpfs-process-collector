"use strict";
// Real page and transport functions; only media, the provider and the DOM are simulated.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const shared={require,__dirname,console,Buffer,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException,setImmediate,setTimeout,clearTimeout};
function harness(file,until,tail,replace){
  const module={exports:{}};
  let source=fs.readFileSync(path.join(__dirname,file),"utf8").split(until)[0];
  if(replace)source=source.replace("setTeam:value=>",replace+",setTeam:value=>");
  vm.runInNewContext(source+tail,{...shared,module});
  return module.exports;
}
const app=harness("test_agent_experience.cjs","let passed=0;","\nmodule.exports={setup};",
  "rememberLiveLeads,syncLiveCoverage,recallInterview,previewVoiceTopics,getPreview:()=>voiceTopicPreview,setPreviewRender:()=>{renderCoverage=()=>{};}");
const voice=harness("test_live_voice.cjs","(async()=>{","\nmodule.exports={setup};");
const quote="The division director reviews complex awards before releasing the file.";
const turns=[{id:"a1",role:"assistant",text:"Who reviews it?"},{id:"u1",role:"user",text:quote}];
const lead={id:"x1",source:"u1",quote,gap:"Where do complex awards go after the director reviews them?",anchors:["award","director","complex"]};
function session(){
  const h=app.setup(),t=h.t,sent=[];
  t.state.config.agent_team.interview_memory=true;t.state.config.agent_team.voice_mode="live_front";
  t.state.turns=turns.map(row=>({...row}));
  t.conversationUI.live={active:true,connected:true,participantSpeaking:false,assistantSpeaking:false,
    appendContext(msg,options){sent.push({msg,options});return Promise.resolve({status:"acknowledged"});}};
  return {h,t,sent,live:t.conversationUI.live};
}
(async()=>{
  {
    const {t,live,sent}=session();
    live.participantSpeaking=true;t.rememberLiveLeads("map",[lead],turns);assert.equal(sent.length,0);
    t.state.turns.push({id:"a2",role:"assistant",text:"How is the dispatch recorded?"},{id:"u2",role:"user",text:"A ticket records the notification."});
    live.participantSpeaking=false;live.assistantSpeaking=true;t.syncLiveCoverage();assert.equal(sent.length,0);
    live.assistantSpeaking=false;t.syncLiveCoverage();assert.equal(sent.length,1);assert.ok(sent[0].msg.includes("u1"));
    t.syncLiveCoverage();assert.equal(sent.length,1);
  }
  for(const change of ["The director sends it to legal.","Actually, we no longer follow that route."]){
    const {t,live,sent}=session();
    live.participantSpeaking=true;t.rememberLiveLeads("map",[lead],turns);
    t.state.turns.push({id:"u2",role:"user",text:change});live.participantSpeaking=false;t.syncLiveCoverage();
    assert.equal(sent.length,0);
  }
  {
    const {t,live,sent}=session();live.participantSpeaking=true;t.rememberLiveLeads("map",[lead],turns);
    t.state.turns[1].text="A clerk files routine invoices.";live.participantSpeaking=false;t.syncLiveCoverage();
    assert.equal(sent.length,0);
    assert.equal(t.recallInterview("complex awards").passages.length,0);
    assert.equal(t.recallInterview("routine invoices").passages[0].turn,"u1");
    t.setPreviewRender();
    t.previewVoiceTopics({id:"u2",text:"We run a variance check in Excel."});
    assert.deepEqual([...t.getPreview().keys].sort(),["checks","data_systems"]);
    t.previewVoiceTopics({id:"u2",text:"Let me think about that."});assert.equal(t.getPreview().keys.size,0);
  }
  {
    const h=voice.setup();let queries=0;
    h.api.options.lookupInterview=query=>{assert.equal(query,"release");queries++;return {passages:[{turn:"u1",quote}]};};
    await h.api.start();
    const item={type:"function_call",name:"lookup_interview",call_id:"call_1",arguments:JSON.stringify({query:"release"})};
    const event=nested=>h.event({type:"response.event",delegation_id:"delegation_1",event:nested});
    event({type:"response.output_item.done",response_id:"resp_1",item});
    const complete={type:"response.completed",response:{id:"resp_1",output:[item]}};
    event(complete);event(complete);
    assert.equal(queries,1);
    const sent=h.channels.at(-1).sent;
    assert.equal(sent.filter(p=>p.type==="response.create").length,1);
    const found=sent.find(p=>p.type==="response.item.create");assert.equal(JSON.parse(found.item.output).passages[0].quote,quote);
    await h.api.stop({immediate:true});
  }
  console.log("6 live memory, correction, topic and tool scenarios passed");
})().catch(e=>{console.error(e);process.exitCode=1;});
