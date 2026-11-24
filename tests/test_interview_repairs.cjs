"use strict";
// Actual app progress/recovery callbacks with local fake media and no providers.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
let harness=fs.readFileSync(path.join(__dirname,'test_agent_experience.cjs'),'utf8').split('let passed=0;')[0];
harness=harness.replace('setTeam:value=>','renderCoverage,rememberDiscussion,renderAnalysisThrough,setTeam:value=>');
harness+='\nmodule.exports={setup,response,flush};';
const out={exports:{}};
vm.runInNewContext(harness,{require,__dirname,module:out,console,Buffer,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException});
const {setup,response,flush}=out.exports;
let passed=0;async function check(name,fn){try{await fn();passed++;}catch(e){e.message=name+': '+e.message;throw e;}}
// The status is visible on each topic of the Notes list. The page keeps
// one counter, the captured figure, and no longer a separate "N of 16 topics discussed" line.
const discussed=h=>h.node('coverage-list').children.filter(topic=>topic.dataset.topicState==='detail').length;
(async()=>{
await check('a discussed topic is labelled on the topic and does not move the captured figure',async()=>{
 const h=setup();h.t.state.config.concurrent_interview={enabled:true};h.t.state.turns=[{id:'u1',role:'user',text:'I use the spare when equipment is missing.'}];
 h.t.state.memo_findings=[{key:'variations',status:'partial',answer:'Spare route.',evidence_turns:['u1']}];
 h.t.rememberDiscussion({topic_discussion:[{key:'variations',discussed:true,evidence_turns:['u1']}]},h.t.snapshot());h.t.renderCoverage();
 assert.equal(discussed(h),1);assert.equal(h.node('coverage-list').children.length,16);assert.equal(h.node('coverage-count').textContent,'0%');
 assert.equal(h.node('coverage-progress').style.strokeDashoffset,'100','A discussed topic leaves the coverage ring empty');
 assert.equal(h.node('coverage-summary').textContent,'','Nothing to add under the bar');assert.match(h.node('analysis-through').textContent,/all 1 saved answers/);
});
await check('progress states exactly how far the notes have caught up',async()=>{
 const h=setup();h.t.state.config.concurrent_interview={enabled:true};h.t.state.turns=[{id:'u1',role:'user',text:'First detail.'}];
 h.t.rememberDiscussion({},h.t.snapshot());h.t.state.turns.push({id:'u2',role:'user',text:'New detail.'});h.t.renderAnalysisThrough();
 assert.equal(h.node('analysis-through').textContent,'Notes through answer 1 of 2');
 h.t.state.turns.pop();h.t.state.turns[0].text='Corrected detail.';h.t.renderAnalysisThrough();assert.match(h.node('analysis-through').textContent,/revised conversation/);
});
await check('unsupported discussion metadata does not manufacture progress',async()=>{
 const h=setup();h.t.state.turns=[{id:'u1',role:'user',text:'Detail.'}];
 h.t.rememberDiscussion({topic_discussion:[{key:'risks',discussed:true,evidence_turns:['made-up']}]},h.t.snapshot());h.t.renderCoverage();
 assert.equal(discussed(h),0);assert.equal(h.node('coverage-list').children.length,16);
});
console.log(JSON.stringify({tests_passed:passed,provider_calls:0,physical_audio:false}));
})().catch(e=>{console.error(e);process.exitCode=1;});
