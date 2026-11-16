"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {randomUUID} = require("node:crypto");
const {open} = require("./fixtures/app_page.cjs");
const script = fs.readFileSync(path.join(__dirname, "../web/raw-trace.js"), "utf8");
const transientTranscription = "RECORDING-NOT-COMMITTED-CANARY";

async function start(content) {
  const page = await open({config:{raw_trace:{enabled:true,content}},
    expose:"configureTrace,ensureConversation,sendAnswer,applyInterview,selectConversationView,setBusy,showProvisionalQuestion,setInterviewSettings,notice,dismissNotice,transcribeDictation"});
  // The fixture has a separate window object. In a browser window.fetch is the global fetch.
  page.context.crypto = {randomUUID};
  page.context.Headers = Headers;
  vm.runInContext(script, page.context);
  page.context.fetch = page.window.fetch;
  page.t.configureTrace(page.state.config);
  const records = [], batches = [], requests = [];
  let failOnce = false;
  page.route((url, options, body) => {
    if (url === "/api/trace/events") {
      batches.push(body);
      if (failOnce) { failOnce = false; throw new Error("synthetic transport failure"); }
      records.push(...body.events);
      return {received:body.events.length,accepted:body.events.length};
    }
    if (url === "/api/interview") {
      requests.push(options.headers);
      return {question:"Who reads that invoice next?",preserve_capture:true};
    }
    if (url === "/api/transcribe") return {text:transientTranscription};
    throw new Error("Unexpected synthetic route " + url);
  });
  return {page,records,batches,requests,
    flush:() => page.window.CollectorRawTrace.flush(),
    failNext:() => {failOnce=true;}};
}

async function main() {
  const a = await start(true), b = await start(false);
  const answer = "The AP manager approves   invoices.\nThe limit is €500.";
  const canary = "UNSENT-INPUT-CANARY";
  for (const run of [a,b]) {
    const {page} = run;
    page.$("objective").value = "Document the synthetic process.";
    page.t.ensureConversation();
    page.$("answer-text").value = canary;
    page.$("answer-text").dispatchEvent({type:"input", bubbles:true});
    page.$("answer-text").value = answer;
    await page.t.sendAnswer({preventDefault(){}});
    await page.flush();
    page.t.selectConversationView("transcript");
    assert.equal(page.state.turns[0].text,answer);
    assert.equal(page.state.turns[1].text,"Who reads that invoice next?");
    assert.equal(page.$("developer-trace-notice").hidden, run === b);
    await run.flush();
    const {records, requests} = run;
    const dispatched = records.find(row=>row.type==="http.dispatched" && row.payload.path==="/api/interview");
    const received = records.find(row=>row.type==="http.response_headers" && row.operation_id === dispatched.operation_id);
    assert.equal(requests[0].get("X-Trace-Operation"), dispatched.operation_id);
    assert.equal(requests[0].get("X-Trace-Producer"), run.batches[0].producer_id);
    assert.equal(dispatched.turn_id,page.state.turns[0].id);
    assert.equal(received.turn_id,dispatched.turn_id);
    assert.equal(received.interview_id,requests[0].get("X-Trace-Interview"));
    assert(received.seq > dispatched.seq);
    const committed = records.find(row=>row.type==="turn.created" && row.turn_id===dispatched.turn_id);
    const rendered = records.find(row=>row.type==="transcript.rendered" && row.turn_id===dispatched.turn_id);
    assert(committed.seq < rendered.seq);
    assert.equal(committed.interview_id,dispatched.interview_id);
    assert.equal(records.find(row=>row.type==="transcript.rendered" && row.payload.role==="assistant").operation_id,dispatched.operation_id);
    assert(records.some(row=>row.type==="ui.input" && row.payload.value_omitted==="transient_input"));
    assert(!JSON.stringify(run.batches).includes(canary));
    assert(!JSON.stringify(run.batches).includes("synthetic-csrf"));
    assert(!records.some(row=>row.payload.path === "/api/trace/events"));
    if (run === a) {
      assert.equal(committed.payload.content.text,answer);
      assert.equal(rendered.payload.content.text,answer);
    } else {
      assert.equal(committed.payload.content_omitted,"metadata_mode");
      assert(!JSON.stringify(records).includes("The AP manager"));
    }
  }
  assert.notEqual(a.batches[0].producer_id, b.batches[0].producer_id);

  const logger = a.page.window.CollectorRawTrace;
  a.page.t.setBusy(true);
  a.page.t.showProvisionalQuestion("Who receives the signed copy?");
  a.page.t.setBusy(false);
  a.page.t.setInterviewSettings(true);
  a.page.t.notice("Synthetic notice in Settings.", false, "general", true);
  a.page.t.dismissNotice();
  a.page.t.setInterviewSettings(false);
  await a.page.t.transcribeDictation(new Blob(["synthetic"],{type:"audio/webm"}),a.page.state.generation);
  assert.equal(a.page.$("answer-text").value,transientTranscription);
  await a.flush();
  assert(a.records.some(row=>row.type==="interview.progress_rendered" && row.payload.provisional &&
    !row.payload.hidden && row.payload.content.text.includes("Who receives the signed copy?")));
  assert(a.records.some(row=>row.type==="settings.dialog_opened" && row.payload.open));
  assert(a.records.some(row=>row.type==="notice.rendered" && !row.payload.hidden && row.payload.in_dialog));
  assert(a.records.some(row=>row.type==="notice.dismissed" && row.payload.hidden));
  assert(a.records.some(row=>row.type==="voice.editor_updated" && row.payload.value_omitted==="transient_input"));
  assert(!JSON.stringify(a.records).includes(transientTranscription));
  logger.record("test.observed",{}, {text:"x".repeat(60000)});
  a.failNext();
  await a.flush();
  const failed = a.batches.at(-1).events;
  assert(!a.records.some(row=>row.type==="test.observed"));
  await a.flush();
  assert.deepEqual(a.batches.at(-1).events,failed);
  const oversized = a.records.find(row=>row.type==="test.observed");
  assert.equal(oversized.payload.content_omitted,"event_size_limit");
  assert(oversized.payload.original_event_bytes>60000);
  const steps = Array.from({length:60}, (_,index)=>({id:"S"+index, title:"step "+index+" \u20ac".repeat(600)}));
  const graph = {title:"A",steps,connections:[]};
  logger.record("workflow.applied",{step_count:steps.length},()=>({graph}));
  await a.flush();
  const parent = a.records.find(row=>row.type==="workflow.applied");
  const pieces = a.records.filter(row=>row.type==="artifact.part" && row.payload.source_seq===parent.seq);
  assert.equal(pieces.length,parent.payload.content_parts);
  const reconstructed = pieces.filter(row=>row.payload.field==="steps").sort((l,r)=>l.payload.start-r.payload.start)
    .flatMap(row=>row.payload.content.graph.steps);
  assert.deepEqual(reconstructed,steps);
  assert(!a.records.some(row=>row.type==="interview.completed"));
  console.log("Raw browser traces preserve typed/rendered values, request correlation, scope, boundaries and retry sequence.");
}

main().catch(error=>{console.error(error);process.exitCode=1;});
