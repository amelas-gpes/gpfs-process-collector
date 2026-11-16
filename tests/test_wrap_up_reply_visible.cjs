"use strict";
// The interviewer's reply to Wrap up (or to the retry control) must be on screen. Both can be used
// from the Workflow view, which shows the map and not the transcript: the reply is then shown in the
// transcript with the cursor in the reply box, and while someone types in the Workflow view the
// question being answered is repeated above the reply box.
// Real web/app.js behind a synthetic DOM. No browser, provider or network.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path");
const {setup,run,flush,deferred,response,approved,reviewAck}=require("./support/interview_page.cjs");
let passed=0;
const check=async(name,fn)=>{try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}};
const FINAL="Before we finish, is there anything else someone doing this work needs to know that we haven’t captured?";
const reviewed=()=>({...approved(FINAL,"final_check"),capture_token:"capture-reviewed",coverage_verified:true,closure:{asked:true,confirmed:false}});
function page(view="workflow"){
  const h=setup({expose:"syncDockQuestion,updateConversationControls,typeInstead"});
  h.t.state.turns=[{id:"t001",role:"assistant",text:"How does the work start?"},{id:"t002",role:"user",text:"A supplier email starts a case."}];
  h.t.conversationUI.view=view;h.t.conversationUI.typing=true;
  // Wrap up: the lead acknowledges, the review runs, the final omissions question comes back.
  h.route(url=>url==="/api/agent-team/interview"?response(reviewAck()):url==="/api/agent-team/review"?response(reviewed()):response({}));
  // The reply box cannot take focus while the page is busy: record whether it was.
  h.focusedWhileBusy=[];const box=h.node("answer-text"),focus=box.focus;box.focus=function(...args){h.focusedWhileBusy.push(h.t.state.busy);return focus.apply(this,args);};
  return h;
}

run(async()=>{
  await check("Wrap up from the Workflow view shows the final question in the transcript and focuses the reply box",async()=>{
    const h=page("workflow");h.document.activeElement=h.node("final-check");
    await h.t.finalCheck();
    assert.equal(h.t.state.turns.at(-1).text,FINAL);assert.equal(h.t.state.closure.asked,true);
    assert.equal(h.t.conversationUI.view,"transcript","The transcript, where the question was appended, is on screen");assert.deepEqual(h.views,["transcript"]);
    assert.equal(h.scrolls.at(-1),"transcript","The end of the transcript is scrolled into view after the switch");
    assert.equal(h.document.activeElement,h.node("answer-text"));assert.deepEqual(h.focusedWhileBusy,[false],"Focus moves once the reply box is enabled again");
  });

  await check("the same applies to the retry control and to Resume review",async()=>{
    // Retry of a prepared review whose first attempt failed in transport.
    const h=page("workflow");let reviews=0;
    h.route(url=>url==="/api/agent-team/interview"?response(reviewAck()):url==="/api/agent-team/review"?(++reviews===1?Promise.reject(Error("Synthetic disconnect")):response(reviewed())):response({}));
    await h.t.finalCheck();
    assert.equal(h.t.conversationUI.view,"workflow","A failed review asks nothing, so the view is left alone");assert.deepEqual(h.views,[]);assert.deepEqual(h.focusedWhileBusy,[]);
    h.document.activeElement=h.node("retry-question");await h.t.retryQuestion();
    assert.equal(h.t.state.turns.at(-1).text,FINAL);assert.equal(h.t.conversationUI.view,"transcript");assert.equal(h.document.activeElement,h.node("answer-text"));assert.deepEqual(h.focusedWhileBusy,[false]);
    // Resume review after a pause, started from the Workflow view (its Recheck coverage button routes here).
    const p=page("workflow"),held=deferred();let leads=0;
    p.route(url=>url==="/api/agent-team/interview"?response(++leads===1?reviewAck():approved("Which exception still needs clarification?")):url==="/api/agent-team/review"?held.promise:response({}));
    const wrapping=p.t.finalCheck();await flush();p.t.pauseCompletionReview();await flush();held.resolve(response(reviewed()));await wrapping;
    p.views.length=0;p.focusedWhileBusy.length=0;p.t.conversationUI.view="workflow";p.document.activeElement=p.node("retry-workflow");
    await p.t.retryQuestion();
    assert.equal(p.t.state.turns.at(-1).text,"Which exception still needs clarification?");assert.deepEqual(p.views,["transcript"]);assert.equal(p.document.activeElement,p.node("answer-text"),"Focus leaves the button that started the request");assert.deepEqual(p.focusedWhileBusy,[false]);
  });

  await check("a view that already shows the question is not replaced, and focus elsewhere is respected",async()=>{
    for(const view of ["transcript","voice"]){
      const h=page(view);await h.t.finalCheck();
      assert.equal(h.t.conversationUI.view,view);assert.deepEqual(h.views,[],view+": no view change");
      assert.equal(h.scrolls.at(-1),view);assert.equal(h.document.activeElement,h.node("answer-text"),view+": focus was on the page body, so it goes to the reply box");
    }
    const h=page("workflow"),elsewhere=h.node("coverage-list"),held=deferred();
    h.route(url=>url==="/api/agent-team/interview"?response(reviewAck()):url==="/api/agent-team/review"?held.promise:response({}));
    h.document.activeElement=h.node("final-check");const wrapping=h.t.finalCheck();await flush();
    h.document.activeElement=elsewhere;held.resolve(response(reviewed()));await wrapping;
    assert.equal(h.t.conversationUI.view,"transcript");assert.equal(h.document.activeElement,elsewhere,"A reader who moved to the notes keeps their place");
    // The reply area is hidden (voice only, never typed): nothing hidden is focused.
    const hidden=page("voice");hidden.node("composer-area").hidden=true;await hidden.t.finalCheck();
    assert.equal(hidden.document.activeElement,null);
  });

  await check("a paused review is not followed by a second view change, and a replaced interview by none",async()=>{
    const h=page("workflow"),held=deferred();
    h.route(url=>url==="/api/agent-team/interview"?response(reviewAck()):url==="/api/agent-team/review"?held.promise:response({}));
    const wrapping=h.t.finalCheck();await flush();h.t.pauseCompletionReview();await flush();
    assert.deepEqual(h.views,["transcript"],"Pause review shows the transcript itself");
    held.resolve(response(reviewed()));await wrapping;
    assert.deepEqual(h.views,["transcript"]);assert.notEqual(h.t.state.turns.at(-1).text,FINAL);
    const g=page("workflow"),late=deferred();
    g.route(url=>url==="/api/agent-team/interview"?late.promise:response({}));
    const stale=g.t.finalCheck();await flush();g.t.state.generation++;late.resolve(response(approved("A question for the interview that was replaced.")));await stale;
    assert.deepEqual(g.views,[]);assert.deepEqual(g.focusedWhileBusy,[]);
  });

  await check("the question being answered is repeated above the reply box in the Workflow view only",async()=>{
    const h=page("workflow"),box=h.node("dock-question"),label=h.node("dock-question-text");
    h.t.syncDockQuestion();
    assert.equal(box.hidden,false);assert.equal(label.textContent,"How does the work start?");
    // An answer sent from the Workflow view: the next question arrives there too.
    h.route(url=>url==="/api/agent-team/interview"?response(approved("Who approves the payment?")):response({}));
    h.node("answer-text").value="The AP analyst registers the invoice.";await h.t.sendAnswer({preventDefault(){}});
    assert.equal(h.t.conversationUI.view,"workflow","Sending an answer does not change the view");assert.deepEqual(h.views,[]);
    h.t.updateConversationControls();
    assert.equal(box.hidden,false);assert.equal(label.textContent,"Who approves the payment?");
    // File notices are not questions.
    h.t.state.turns.push({id:"doc_intake",role:"assistant",text:"Thanks for sharing.",document_event:true});h.t.syncDockQuestion();
    assert.equal(label.textContent,"Who approves the payment?");
    for(const view of ["transcript","voice"]){h.t.conversationUI.view=view;h.t.syncDockQuestion();assert.equal(box.hidden,true,view+" shows the question itself");}
    h.t.conversationUI.view="workflow";h.t.state.turns=[];h.t.syncDockQuestion();assert.equal(box.hidden,true,"Nothing to show before the first question");
    // It belongs to the reply area, so it is on screen exactly when the reply box is.
    const html=fs.readFileSync(path.join(__dirname,"..","web","index.html"),"utf8"),area=html.slice(html.indexOf('id="composer-area"'),html.indexOf('id="answer-form"'));
    assert.match(area,/<p class="dock-question" id="dock-question" hidden><span class="dock-question-label">Current question<\/span><span id="dock-question-text"><\/span><\/p>/);
    const css=fs.readFileSync(path.join(__dirname,"..","web","style.css"),"utf8");assert.match(css,/\.dock-question \{[^}]*overflow: auto;/,"A long question scrolls inside its own box");
  });

  console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0}));
});
