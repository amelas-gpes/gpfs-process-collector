"use strict";
// When the completion review request fails, the control that retries that same review must be shown
// whichever action led to the review: a typed answer, Wrap up, Skip, a retry, or the typed start.
// The retry re-posts the prepared ticket; it does not run the lead again or repeat its acknowledgement.
// Real web/app.js behind a synthetic DOM. No browser, provider or network.
const assert=require("node:assert/strict");
const {setup,run,flush,deferred,response,approved,reviewAck,REVIEW_ACK}=require("./support/interview_page.cjs");
let passed=0;
const check=async(name,fn)=>{try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}};
const FINAL="Have I missed anything else?";
const reviewed=()=>({...approved(FINAL,"final_check"),capture_token:"capture-reviewed",coverage_verified:true});
const REVIEW_FAILED_NOTICE=/^Your answers are still here\. The completion review did not finish; choose Retry completion review to resume it\./;
// The lead prepares the review; the review request fails `failures` times, then succeeds.
function page(failures=1,failure=()=>response({error:"The request could not be completed. Your browser session is retained."},500)){
  const h=setup({expose:"typeInstead"});let reviews=0;
  h.t.state.turns=[{id:"t001",role:"assistant",text:"How does the work start?"},{id:"t002",role:"user",text:"A supplier email starts a case."}];
  h.route(url=>url==="/api/agent-team/interview"?response(reviewAck()):url==="/api/agent-team/review"?(++reviews<=failures?failure():response(reviewed())):response({}));
  h.leads=()=>h.requests("/api/agent-team/interview");h.reviews=()=>h.requests("/api/agent-team/review");
  h.acks=()=>h.t.state.turns.filter(turn=>turn.text===REVIEW_ACK).length;
  return h;
}
function offered(h,label){
  const retry=h.node("retry-question"),said=h.notices.at(-1);
  assert.equal(retry.hidden,false,label+": the retry control is shown");assert.equal(retry.textContent,"Retry completion review",label);assert.equal(retry.dataset.resumeReview,undefined,label);
  assert.equal(said.error,true);assert.match(said.message,REVIEW_FAILED_NOTICE,label+": the notice names the control as it is labelled");assert.doesNotMatch(said.message,/choose Try again/);
  assert.equal(h.t.state.busy,false);assert.ok(h.t.pendingReview(),label+": the prepared review is kept");
}
async function retried(h,label){
  const leads=h.leads().length,reviews=h.reviews().length,ticket=h.body(h.reviews()[0]).review_ticket;
  await h.t.retryQuestion();
  assert.equal(h.leads().length,leads,label+": no second lead call");assert.equal(h.reviews().length,reviews+1);
  assert.equal(h.body(h.reviews().at(-1)).review_ticket,ticket,label+": the same ticket is re-posted");assert.equal(ticket,"review-ticket-one");
  assert.equal(h.acks(),1,label+": the acknowledgement is not repeated");
  assert.equal(h.t.state.turns.at(-1).text,FINAL);assert.equal(h.t.state.coverageVerified,true);assert.equal(h.node("retry-question").hidden,true);
}

run(async()=>{
  await check("Wrap up: a failed review request shows Retry completion review, which re-posts the ticket",async()=>{
    const h=page();await h.t.finalCheck();
    assert.equal(h.leads().length,1);assert.equal(h.body(h.leads()[0]).action,"close");assert.equal(h.reviews().length,1);assert.equal(h.acks(),1);
    offered(h,"Wrap up");
    assert.match(h.notices.at(-1).message,/The request could not be completed\. Your browser session is retained\./,"The server's reason stays visible");
    await retried(h,"Wrap up");
  });

  await check("Skip, a typed answer and the typed start offer the same control",async()=>{
    const skip=page();await skip.t.skipQuestion();
    assert.equal(skip.body(skip.leads()[0]).action,"skip");offered(skip,"Skip");await retried(skip,"Skip");
    const answer=page();answer.node("answer-text").value="That completes the remaining detail.";await answer.t.sendAnswer({preventDefault(){}});
    assert.equal(answer.body(answer.leads()[0]).action,"answer");offered(answer,"Answer");await retried(answer,"Answer");
    const start=page();start.t.state.turns=[];await start.t.typeInstead();
    assert.equal(start.body(start.leads()[0]).action,"start");offered(start,"Type instead");await retried(start,"Type instead");
  });

  await check("a retry that fails again keeps offering the review, for transport failures as well",async()=>{
    const h=page(2,()=>Promise.reject(Object.assign(Error("Failed to fetch"),{name:"TypeError"})));await h.t.finalCheck();
    offered(h,"first failure");assert.match(h.notices.at(-1).message,/The interviewer isn’t available right now/);
    await h.t.retryQuestion();
    assert.equal(h.leads().length,1);assert.equal(h.reviews().length,2);offered(h,"second failure");
    await retried(h,"third attempt");
  });

  await check("Resume review after a pause offers the retry when its fresh review fails",async()=>{
    const h=page(1);
    // First review is paused by the participant; Resume review asks the lead again (a new ticket), and that review fails.
    const held=deferred();let leads=0,reviews=0;
    h.route(url=>url==="/api/agent-team/interview"?response({...reviewAck(),review_ticket:"review-ticket-"+(++leads)}):url==="/api/agent-team/review"?(++reviews===1?held.promise:reviews===2?response({error:"Synthetic outage."},503):response(reviewed())):response({}));
    const wrapping=h.t.finalCheck();await flush();h.t.pauseCompletionReview();await flush();held.resolve(response(reviewed()));await wrapping;
    assert.equal(h.node("retry-question").textContent,"Resume review");
    await h.t.retryQuestion();
    assert.equal(leads,2);assert.equal(h.body(h.leads()[1]).action,"close");offered(h,"Resume review");assert.match(h.notices.at(-1).message,/Synthetic outage\./);
    await h.t.retryQuestion();
    assert.equal(leads,2,"The retry uses the fresh ticket, not another lead call");assert.equal(h.body(h.reviews().at(-1)).review_ticket,"review-ticket-2");assert.equal(h.t.state.turns.at(-1).text,FINAL);
  });

  await check("without a prepared review each action keeps its own failure message and no review control appears",async()=>{
    for(const act of ["finalCheck","skipQuestion","typeInstead"]){
      const h=page();if(act==="typeInstead")h.t.state.turns=[];
      h.route(url=>url==="/api/agent-team/interview"?response({error:"Synthetic lead outage."},503):response({}));
      h.node("retry-question").hidden=true;await h.t[act]();
      assert.equal(h.notices.at(-1).message,"Synthetic lead outage.",act);assert.equal(h.node("retry-question").hidden,true,act+": nothing claims a review can be retried");assert.equal(h.t.pendingReview(),null);
    }
    const h=page();h.route(url=>url==="/api/agent-team/interview"?response({error:"Synthetic lead outage."},503):response({}));
    h.node("answer-text").value="A typed answer.";await h.t.sendAnswer({preventDefault(){}});
    assert.equal(h.node("retry-question").hidden,false);assert.equal(h.node("retry-question").textContent,"Try again");
    assert.match(h.notices.at(-1).message,/^Your answer is still here, but the next question didn’t load\. Add more detail, or choose Try again\. Synthetic lead outage\./);
  });

  await check("a review withdrawn by a change to the conversation is not offered for retry",async()=>{
    // The request fails after the participant's context changed: the ticket no longer matches.
    const h=page(1,()=>{h.t.state.context.process_name="A different process scope";return response({error:"Synthetic outage."},503);});
    h.node("retry-question").hidden=true;await h.t.finalCheck();
    assert.equal(h.node("retry-question").hidden,true);assert.doesNotMatch(h.notices.at(-1)?.message||"",REVIEW_FAILED_NOTICE);
  });

  console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0}));
});
