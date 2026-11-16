"use strict";
// A control that offers the completion review must run the completion check, or not be shown.
// File intake (and any new evidence) withdraws the prepared review; the control that was on screen
// for it then starts the check again (action "close") instead of an ordinary interview turn, and a
// control left over from an earlier failure does not survive a later successful request.
// Real web/app.js and web/document-intake.js behind a synthetic DOM. No browser, provider or network.
const assert=require("node:assert/strict");
const {setup,run,flush,deferred,response,approved,reviewAck}=require("./support/interview_page.cjs");
let passed=0;
const check=async(name,fn)=>{try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}};
const page=()=>setup({modules:["document-intake.js"],expose:"onDocumentEvent,applyInterview",seam:"documentIntake=createDocumentIntake();window.__intake=()=>documentIntake;"});
const FAILED={...approved("Your account is retained. The review could not finish; you can retry it when you are ready.","pause"),preserve_capture:true,review_retry_required:true,review_ticket:"review-ticket-one",capture_token:"capture-failed",coverage_verified:false};
const actions=h=>h.requests("/api/agent-team/interview").map(call=>h.body(call).action);
// A file is added and its intake runs to the end (nothing new to read in this double).
async function addFile(h,batch="batch-a"){
  h.t.onDocumentEvent({type:"upload_started",batchId:batch,names:["Payment SOP.pdf"]});
  assert.equal(h.context.__intake().active,true,"The intake owns the page while the file is handled");
  h.t.onDocumentEvent({type:"upload_settled",batchId:batch});await flush();
  assert.equal(h.context.__intake().active,false);
}
// Wrap up whose completion review fails on the server: the retry control is offered.
async function failedReview(h){
  let reviews=0;
  h.route((url,options)=>{
    if(url==="/api/agent-team/interview")return response(JSON.parse(options.body).action==="close"?reviewAck():approved("What happens next in this work?"));
    if(url==="/api/agent-team/review")return response(++reviews===1?FAILED:{...approved("Have I missed anything else?","final_check"),capture_token:"capture-reviewed",coverage_verified:true});
    return response({});
  });
  h.t.state.turns=[{id:"t001",role:"assistant",text:"How does the work start?"},{id:"t002",role:"user",text:"A supplier email starts a case."}];
  await h.t.finalCheck();
  assert.equal(h.node("retry-question").hidden,false);assert.equal(h.node("retry-question").textContent,"Retry completion review");assert.ok(h.t.pendingReview());
}
// Wrap up whose review is paused by the participant: Resume review is offered.
async function pausedReview(h){
  const review=deferred();
  h.route((url,options)=>{
    if(url==="/api/agent-team/interview")return response(JSON.parse(options.body).action==="close"?reviewAck():approved("What happens next in this work?"));
    if(url==="/api/agent-team/review")return review.promise;
    return response({});
  });
  h.t.state.turns=[{id:"t001",role:"assistant",text:"How does the work start?"},{id:"t002",role:"user",text:"A supplier email starts a case."}];
  const wrapping=h.t.finalCheck();await flush();h.t.pauseCompletionReview();await flush();review.resolve(response(approved()));await wrapping;
  assert.equal(h.node("retry-question").hidden,false);assert.equal(h.node("retry-question").textContent,"Resume review");assert.equal(h.node("retry-question").dataset.resumeReview,"true");
}

run(async()=>{
  await check("after a failed review, adding a file leaves a control that runs the completion check",async()=>{
    const h=page();await failedReview(h);
    await addFile(h);
    const retry=h.node("retry-question");
    assert.equal(h.t.pendingReview(),null,"The intake withdrew the prepared review");
    assert.equal(retry.hidden,false,"The control is still offered after the intake");
    const questions=h.t.state.turns.filter(turn=>turn.role==="assistant").length,reviewsBefore=h.requests("/api/agent-team/review").length;
    await h.t.retryQuestion();
    assert.deepEqual(actions(h),["close","close"],"The control asked for the completion check, not for another interview question");
    assert.equal(h.requests("/api/agent-team/review").length,reviewsBefore+1,"The review ran");
    assert.equal(h.t.state.turns.at(-1).text,"Have I missed anything else?");assert.equal(h.t.state.coverageVerified,true);
    assert.ok(!h.t.state.turns.some(turn=>turn.text==="What happens next in this work?"),"No ordinary question was appended");
    assert.equal(h.t.state.turns.filter(turn=>turn.role==="assistant").length,questions+2,"Only the acknowledgement and the final check were added");
    assert.equal(retry.hidden,true);
  });

  await check("after a paused review, adding a file keeps Resume review a review control",async()=>{
    const h=page();await pausedReview(h);
    await addFile(h);
    const retry=h.node("retry-question");
    assert.equal(retry.hidden,false);assert.equal(retry.textContent,"Resume review");assert.equal(retry.dataset.resumeReview,"true");
    await h.t.retryQuestion();
    assert.deepEqual(actions(h),["close","close"]);
  });

  await check("two overlapping uploads and a later file leave the control in the same state",async()=>{
    const h=page();await failedReview(h);
    h.t.onDocumentEvent({type:"upload_started",batchId:"batch-a",names:["Payment SOP.pdf"]});h.t.onDocumentEvent({type:"upload_started",batchId:"batch-b",names:["Appendix.pdf"]});
    h.t.onDocumentEvent({type:"upload_settled",batchId:"batch-a"});h.t.onDocumentEvent({type:"upload_settled",batchId:"batch-b"});await flush();
    await addFile(h,"batch-c");
    assert.equal(h.node("retry-question").hidden,false);
    assert.equal(h.node("retry-question").textContent,"Resume review","The control no longer promises to retry a review that is gone");assert.equal(h.node("retry-question").dataset.resumeReview,"true");
    await h.t.retryQuestion();assert.deepEqual(actions(h),["close","close"]);
  });

  await check("an ordinary Try again stays an ordinary turn across a file intake",async()=>{
    const h=page();let fail=true;
    h.route(url=>url==="/api/agent-team/interview"?(fail?response({error:"Synthetic outage."},503):response(approved("What happens next in this work?"))):response({}));
    h.node("answer-text").value="A supplier email starts a case.";await h.t.sendAnswer({preventDefault(){}});
    const retry=h.node("retry-question");assert.equal(retry.hidden,false);assert.equal(retry.textContent,"Try again");
    await addFile(h);
    assert.equal(retry.textContent,"Try again","A control that never offered the review is not turned into one");assert.equal(retry.dataset.resumeReview,undefined);
    fail=false;await h.t.retryQuestion();
    assert.deepEqual(actions(h),["answer","answer"]);assert.equal(retry.hidden,true);
  });

  await check("a hidden control is not revived by new evidence",async()=>{
    const h=page();h.route(url=>url==="/api/agent-team/interview"?response(approved("What happens next in this work?")):response({}));
    h.node("retry-question").hidden=true;h.node("retry-question").textContent="Retry completion review";
    await addFile(h);
    assert.equal(h.node("retry-question").hidden,true);assert.equal(h.node("retry-question").dataset.resumeReview,undefined);
  });

  await check("an answer sent instead of retrying turns the offer into a plain retry when it fails",async()=>{
    const h=page();await failedReview(h);
    h.route(url=>url==="/api/agent-team/interview"?response({error:"Synthetic outage."},503):response({}));
    h.node("answer-text").value="One more detail about approvals.";await h.t.sendAnswer({preventDefault(){}});
    const retry=h.node("retry-question");
    assert.equal(retry.hidden,false);assert.equal(retry.textContent,"Try again","The label says what the control now does");assert.equal(retry.dataset.resumeReview,undefined);
    assert.match(h.notices.at(-1).message,/next question didn’t load.*choose Try again/);
    h.route(url=>url==="/api/agent-team/interview"?response(approved("Who approves the payment?")):response({}));
    await h.t.retryQuestion();
    assert.equal(actions(h).at(-1),"answer");assert.equal(h.t.state.turns.at(-1).text,"Who approves the payment?");assert.equal(retry.hidden,true);
  });

  await check("a control left by an earlier failure goes when Wrap up or Skip succeeds",async()=>{
    for(const act of ["finalCheck","skipQuestion"]){
      const h=page();let fail=true;
      h.route(url=>url==="/api/agent-team/interview"?(fail?response({error:"Synthetic outage."},503):response(approved("Is anything else missing?",act==="finalCheck"?"final_check":"question"))):response({}));
      h.node("answer-text").value="A supplier email starts a case.";await h.t.sendAnswer({preventDefault(){}});
      assert.equal(h.node("retry-question").hidden,false);
      fail=false;await h.t[act]();
      assert.equal(h.t.state.turns.at(-1).text,"Is anything else missing?");
      assert.equal(h.node("retry-question").hidden,true,act+": the reply answered the request, so nothing is left to retry");
    }
  });

  console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0}));
});
