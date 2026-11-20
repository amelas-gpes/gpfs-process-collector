"use strict";
// New metadata crosses the actual app normalizers and exports; no providers.
const strict=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
// Every assertion that returns is counted, so the summary reports what actually ran.
let checks=0;const counted=check=>(...args)=>{const result=check(...args);checks++;return result;};
const assert=new Proxy(counted(strict),{get:(_,name)=>typeof strict[name]==="function"?counted(strict[name]):strict[name]});
const source=fs.readFileSync(path.join(__dirname,"../web/app.js"),"utf8");
const context={console,window:{},document:{getElementById:()=>({value:""})},fetch:()=>{throw Error("No network in metadata tests");},setTimeout:()=>0,clearTimeout:()=>{},AbortController};
const hook=`
  clearState=(context)=>{state.context=context;state.turns=[];state.draft=null;state.version=0;state.closure={asked:false,confirmed:false};state.parking_lot=[];};
  renderWorkingMap=()=>{};renderTranscript=()=>{};renderDraft=()=>{};scrollConversation=()=>{};notice=()=>{};
  window.gpfsTest={normalizeDiscovery,normalizeDraft,sessionObject,loadExample,markdown,memoMarkdown,state};
})();`;
vm.createContext(context);
vm.runInContext(source.replace(/  init\(\);\s*\}\)\(\);\s*$/,hook),context);
const app=context.window.gpfsTest;
app.state.turns=[{id:"u1",role:"user",text:"Internal HR access is part of employee onboarding."},{id:"a1",role:"assistant",text:"A question"}];
const value={taxonomy:[{facet:"entity_type",value:"enterprise",note:"Internal HR",evidence_turns:["u1"]}],connections_out:[{relationship_type:"subprocess_of",counterpart:"Employee onboarding",condition:"Access completion",evidence_turns:["u1"]}]};
const normalized=app.normalizeDiscovery(value,app.state.turns);
assert.equal(normalized.taxonomy[0].value,"enterprise");
assert.equal(normalized.connections_out[0].counterpart,"Employee onboarding");
assert.throws(()=>app.normalizeDiscovery({...value,taxonomy:[{...value.taxonomy[0],evidence_turns:["a1"]}]},app.state.turns),/unavailable answer/);
assert.throws(()=>app.normalizeDiscovery({...value,taxonomy:[{...value.taxonomy[0],evidence_turns:[]}]},app.state.turns),/need evidence/);
app.loadExample();
const saved=app.sessionObject();
assert.equal(saved.memo_findings.length,16);
assert.equal(saved.draft.memo_summary.length,16);
assert(saved.taxonomy.length>0);
assert(saved.connections_out.length>0);
assert(saved.draft.taxonomy.length>0);
const restored=app.normalizeDraft(JSON.parse(JSON.stringify(saved.draft)),saved.turns,saved.document_evidence);
assert.equal(JSON.stringify(restored.taxonomy),JSON.stringify(saved.draft.taxonomy));
assert.equal(JSON.stringify(restored.connections_out),JSON.stringify(saved.draft.connections_out));
const markdown=app.markdown(),memo=app.memoMarkdown();
for(const text of ["## Classification","## Connected processes","Process name","Where it applies","Business rules and lineage","Data and systems","Volume and effort"]){assert(markdown.includes(text),text);assert(memo.includes(text),text);}
console.log(JSON.stringify({checks_passed:checks,provider_calls:0,network_calls:0}));
