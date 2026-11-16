"use strict";
// Import each saved boundary through the application, add evidence, then review and confirm again.
const assert=require("node:assert/strict");
const {open}=require("./fixtures/app_page.cjs");
const {approved,reviewAck}=require("./support/interview_page.cjs");
const copy=value=>JSON.parse(JSON.stringify(value));
const finalQuestion="Before we finish, is there anything else someone doing this work needs to know that we haven't captured?";
const expose="loadExample,sessionObject,applySavedSession,finalCheck,sendAnswer,generateDraft,knowledge:()=>knowledgeUI";
const openInterview=()=>open({config:{agent_team:{enabled:true},revisions_available:true},modules:["knowledge-ui.js"],expose});
const receipt=revision=>({process_id:"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",submission_id:"cccccccc-cccc-4ccc-8ccc-cccccccccccc",job_id:"dddddddd-dddd-4ddd-8ddd-dddddddddddd",revision,status:"completed",status_token:"a".repeat(64)});

async function main(){
  const source=await openInterview();source.t.loadExample();
  const original=copy(source.t.sessionObject({includePresentation:true}));
  assert(original.draft?.steps?.length,"The example supplies a real draft with source citations");
  for(const stage of ["notes","failed question","pending review","unanswered final check","confirmed draft"]){
    const page=await openInterview(),saved=copy(original);
    saved.synthetic_example=false;saved.closure={asked:false,confirmed:false};
    saved.knowledge_process_id=receipt(1).process_id;saved.knowledge_status=receipt(1);
    if(stage!=="confirmed draft")saved.draft=null;
    if(stage==="notes")saved.turns.push({id:"t027",role:"assistant",text:"What follows Treasury acceptance?"});
    if(stage==="failed question")saved.capture={in_progress:false,notes_current:false,map_current:false,notes_through_turn:"t024",map_through_turn:"t024"};
    if(stage==="pending review")saved.turns.push({id:"t027",role:"assistant",text:reviewAck().question});
    if(stage==="unanswered final check"){saved.turns.push({id:"t027",role:"assistant",text:finalQuestion});saved.closure.asked=true;}
    if(stage==="confirmed draft")saved.closure={asked:true,confirmed:true};
    const calls=[],addition="Treasury records the acceptance in the release register.";
    page.route((url,options,body)=>{
      if(url==="/api/agent-team/interview"){
        calls.push({url,body});
        if(body.action==="close")return reviewAck();
        if(body.turns.at(-1).text==="No, nothing else.")return {...approved("Thank you. You have confirmed the account.","complete"),workflow_capture:{workflow:saved.workflow},closure:{asked:true,confirmed:true},coverage_verified:true};
        return approved("Who receives the acceptance?");
      }
      if(url==="/api/agent-team/review"){calls.push({url,body});return {...approved(finalQuestion,"final_check"),closure:{asked:true,confirmed:false},coverage_verified:true};}
      if(url==="/api/draft"||url==="/api/agent-team/draft"){calls.push({url:"draft",body});return {draft:{...original.draft,overview:addition}};}
      if(url==="/api/workflow"||url==="/api/agent-team/workflow")return {workflow:saved.workflow};
      if(url==="/api/knowledge/status")return receipt(1);
      if(url==="/api/knowledge/submit"){calls.push({url,body});return receipt(2);}
      return {};
    });
    assert.equal(await page.t.applySavedSession(()=>saved),true,stage);
    assert.equal(page.state.turns.length,saved.turns.length,stage);
    assert.equal(page.state.closure.confirmed,false,"Restoration requires a fresh check");
    if(stage==="confirmed draft"){assert.equal(page.state.savedClosure.kind,"confirmed");assert.deepEqual(copy(page.state.draft.steps),saved.draft.steps);}
    const answer=async line=>{page.$("answer-text").value=line;await page.t.sendAnswer({preventDefault(){}});await page.flush();};
    await answer(addition);await page.t.finalCheck();await page.flush();
    const review=calls.find(call=>call.url==="/api/agent-team/review");
    assert(review,stage+" must execute a fresh review");
    assert.equal(review.body.turns.filter(turn=>turn.text===addition).length,1);
    assert.equal(page.state.turns.at(-1).text,finalQuestion);
    await answer("No, nothing else.");
    assert.equal(page.state.closure.confirmed,true,stage);
    const output=page.t.sessionObject();
    assert.equal(output.turns.filter(turn=>turn.text===addition).length,1);
    assert.equal(output.closure.confirmed,true);
    const runTurns=output.turns.slice(saved.turns.length);
    assert.equal(runTurns.filter(turn=>turn.text===reviewAck().question).length,1);
    assert.equal(calls.filter(call=>call.url==="/api/agent-team/interview").length,3);
    assert.equal(calls.filter(call=>call.url==="/api/agent-team/review").length,1);
    await page.t.generateDraft();await page.flush();
    assert.equal(page.state.draft?.overview,addition,stage+" draft updated");
    assert.equal(calls.filter(call=>call.url==="draft").length,1);
    for(const entry of page.waiting(timer=>timer.ms===1000))await page.run(entry);
    page.t.knowledge().openSubmit();
    const form=page.$("knowledge-submit").querySelector("form");
    assert(form,stage+" submit dialog opened");form.dispatchEvent({type:"submit"});await page.flush();
    const filed=calls.find(call=>call.url==="/api/knowledge/submit");
    assert(filed,stage+" submitted: "+page.text("knowledge-submit"));
    assert.equal(filed.body.process_id,receipt(1).process_id);
    assert.equal(filed.body.draft.overview,addition);
    assert.equal(page.t.knowledge().exportReceipt().revision,2);
    console.log("PASS "+stage);
  }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
