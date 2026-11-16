"use strict";
const assert=require("node:assert/strict");
const {openPage}=require("./fixtures/interview_form_page.cjs");
const crypto=require("node:crypto");
(async()=>{
 let passed=0;
 const usage={day_tokens:4200,daily_token_cap:5000,interview_tokens:200,interview_token_cap:1000,quota_blocked:false};
 const page=await openPage({globals:{crypto},expose:["state","normalizedFacts","usageHeaders","showUsage","checkUsage","sessionObject","normalizeDraft","draftFieldSources","generationRecords"],
   config:{usage},fetch:async url=>{
     assert.equal(url,"/api/usage/check");
     return {ok:true,status:200,json:async()=>({usage:{...usage,day_tokens:4500,quota_blocked:true}})};
   }});
 const label=page.$("usage-summary"),id=page.app.usageHeaders()["X-Interview-Id"];
 assert.match(id,/^[0-9a-f]{32}$/);assert.equal(page.requests[0].init.headers["X-Interview-Id"],id);
 assert.match(label.textContent,/4,200 tokens used/);assert.match(label.textContent,/200 tokens used/);
 await page.app.checkUsage();assert.match(label.textContent,/4,500/);assert.match(label.textContent,/quota was reached/);
 assert.equal(page.requests.at(-1).init.headers["X-Interview-Id"],id);assert.equal(page.app.sessionObject().usage_id,id);
 passed++;
 const turns=[{id:"u1",role:"user",text:"I used the ledger."},{id:"a1",role:"assistant",text:"100 staff"}];
 const input={topic:"scope",text:"Used the ledger",evidence_turns:["u1","a1"],support:[{source_id:"u1",quote:"the ledger"},{source_id:"a1",quote:"100 staff"},{source_id:"u1",quote:"new fact"}],unverified:["Number of staff"]};
 const facts=page.app.normalizedFacts([input],turns,[]);
 assert.equal(facts.length,1);assert.deepEqual(Array.from(facts[0].evidence_turns),["u1"]);
 assert.equal(facts[0].support.length,1);assert.equal(facts[0].support[0].quote,"the ledger");assert.equal(facts[0].unverified[0],"Number of staff");
 passed++;
 const item={field:"trigger",index:0,text:"I used the ledger.",evidence_turns:["u1"]},model={stage:"draft_audit",model:"fixture-model",prompt_id:"abcdef0123456789",reasoning_effort:"low"};
 const draft=page.app.normalizeDraft({steps:[],trigger:item.text,inputs:[],outputs:[],exceptions:[],controls:[],field_evidence:[item,{...item,index:1}],generated_by:[model]},turns,[]);
 assert.equal(draft.field_evidence.length,1);assert.equal(draft.generated_by[0].model,"fixture-model");
 assert.deepEqual(Array.from(page.app.draftFieldSources(draft,"trigger",0,item.text)),["u1"]);
 assert.equal(page.app.draftFieldSources(draft,"trigger",0,"Edited text").length,0);passed++;
 console.log(JSON.stringify({tests_passed:passed,provider_calls:0}));
})().catch(error=>{console.error(error);process.exitCode=1;});
