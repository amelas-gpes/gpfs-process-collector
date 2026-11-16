"use strict";
// A dictated answer is not thrown away when its transcription request fails for a reason another
// attempt can cure. The audio is kept (latest recording only, 12 MiB, 10 minutes) and offered with
// Retry recording / Discard recording; it is dropped on success, discard, dismissal, a new
// interview, a file intake and the start of live voice. Failures that the same audio cannot get
// past (nothing heard, a rejected recording) are not offered for retry.
// Real web/app.js behind a synthetic DOM and recorder. No browser, microphone, provider or network.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path");
const {setup,run,flush,deferred,response}=require("./support/interview_page.cjs");
let passed=0;
const check=async(name,fn)=>{try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}};
const KEPT=/Your recording is kept for now: choose Retry recording, or Discard recording\.$/;
function page(){
  const h=setup({modules:["document-intake.js"],realNotice:true,expose:"startRecording,finishRecording,retryDictation,discardFailedDictation,dismissInlineError,clearState,onDocumentEvent,startLiveConversation",
    seam:"documentIntake=createDocumentIntake();window.__kept=()=>failedDictation;"});
  h.kept=()=>h.context.__kept();
  h.transcriptions=()=>h.requests("/api/transcribe");
  h.offered=()=>!h.node("retry-transcription").hidden&&!h.node("discard-recording").hidden;
  h.banner=()=>h.node("interview-error");
  // Dictate for a second and a half, then Finish.
  h.dictate=async()=>{h.setLevel(.1);await h.t.startRecording();await flush();assert.ok(h.t.state.recording,"Dictation started");await h.advance(1500);h.t.finishRecording();await flush();};
  // As the page loads: the interview is the open tab, and the banner and its controls are hidden.
  for(const id of ["retry-transcription","discard-recording","interview-error","review-view"])h.node(id).hidden=true;
  return h;
}
const failing=(status,message="Synthetic failure.")=>()=>response({error:message},status);
const answers=(...replies)=>{let index=0;return url=>url==="/api/transcribe"?replies[Math.min(index++,replies.length-1)]():response({});};
const heard=(text="An analyst reviews the file.")=>()=>response({text});

run(async()=>{
  await check("a transcription that fails once is retried with the same audio and then lands in the reply box",async()=>{
    const h=page();h.route(answers(failing(503,"The AI service could not complete the request (HTTP 503). Your session is retained; try again."),heard()));
    h.node("answer-text").value="Typed before dictating.";
    await h.dictate();
    assert.equal(h.transcriptions().length,1);assert.equal(h.node("answer-text").value,"Typed before dictating.");
    const said=h.notices.at(-1);assert.equal(said.error,true);assert.equal(said.kind,"dictation");
    assert.match(said.message,/^Couldn’t transcribe that\. The AI service could not complete the request \(HTTP 503\)/);assert.match(said.message,KEPT);
    assert.ok(h.kept(),"The recording is kept");assert.equal(h.kept().blob,h.transcriptions()[0].options.body);assert.ok(h.kept().blob.size>0);
    assert.equal(h.offered(),true,"Retry recording and Discard recording are shown");assert.equal(h.banner().hidden,false);assert.equal(h.banner().dataset.errorKind,"dictation");
    assert.equal(h.t.state.transcribing,false);assert.equal(h.document.activeElement,h.node("answer-text"));
    await h.t.retryDictation();
    assert.equal(h.transcriptions().length,2);assert.equal(h.transcriptions()[1].options.body,h.transcriptions()[0].options.body,"The same blob is posted again");
    assert.equal(h.transcriptions()[1].options.headers["Content-Type"],"audio/webm");
    assert.equal(h.node("answer-text").value,"Typed before dictating.\n\nAn analyst reviews the file.");
    assert.equal(h.kept(),null);assert.equal(h.offered(),false);assert.equal(h.node("retry-transcription").hidden,true);assert.equal(h.banner().hidden,true,"The failure banner goes with the retry that cured it");
    assert.equal(h.notices.at(-1).message,"Check the text, then choose Send.");assert.equal(h.recorders.length,1,"Nothing had to be said again");
  });

  await check("a retry that fails again keeps the recording, and the offer survives any number of attempts",async()=>{
    const h=page();h.route(answers(failing(502),failing(502),failing(429,"The AI service's rate limit was reached. Wait briefly, then try again. Your answer is retained."),heard()));
    await h.dictate();const blob=h.kept().blob;
    await h.t.retryDictation();assert.equal(h.kept().blob,blob);assert.equal(h.offered(),true);assert.equal(h.banner().hidden,false);
    await h.t.retryDictation();assert.equal(h.kept().blob,blob);assert.match(h.notices.at(-1).message,/Your answer is retained\..*Your recording is kept/,"The server's 'retained' is now true on this path");
    await h.t.retryDictation();assert.equal(h.kept(),null);assert.equal(h.node("answer-text").value,"An analyst reviews the file.");
    assert.equal(h.transcriptions().length,4);assert.ok(h.transcriptions().every(call=>call.options.body===blob));
  });

  await check("no connection, a timeout, a rate limit and server errors keep the recording",async()=>{
    for(const [label,reply] of [["no connection",()=>Promise.reject(Object.assign(new Error("Failed to fetch"),{name:"TypeError"}))],["rate limit",failing(429)],["request timeout",failing(408)],["server error",failing(500)],["provider error",failing(502)],["unavailable",failing(503)]]){
      const h=page();h.route(answers(reply));await h.dictate();
      assert.ok(h.kept(),label+": kept");assert.equal(h.offered(),true,label);assert.match(h.notices.at(-1).message,KEPT,label);
    }
    // The app's own deadline: the request never answers.
    const h=page();h.route((url,options)=>url==="/api/transcribe"?new Promise((_,reject)=>options.signal.addEventListener("abort",()=>reject(new DOMException("Aborted","AbortError")))):response({}));
    await h.dictate();assert.equal(h.t.state.transcribing,true);await h.timer(150000);
    assert.ok(h.kept(),"timeout: kept");assert.match(h.notices.at(-1).message,/^Couldn’t transcribe that\. That took too long\./);assert.match(h.notices.at(-1).message,KEPT);
  });

  await check("failures that the same audio cannot get past are not offered for retry",async()=>{
    for(const [label,reply,expected] of [
      ["nothing heard",()=>response({text:"   "}),/We didn’t catch that\. Try again, or type your answer\.$/],
      ["rejected recording",failing(400,"The recording is empty or too short. Please record your answer again."),/Please record your answer again\.$/],
      ["unsupported format",failing(400,"Unsupported recording format. Use an up-to-date Chrome or Edge browser."),/Chrome or Edge browser\.$/],
      ["too large",failing(413,"The recording is too large."),/too large\.$/],
      ["not allowed",failing(403,"The request was not accepted."),/not accepted\.$/]]){
      const h=page();h.route(answers(reply));await h.dictate();
      assert.equal(h.kept(),null,label+": not kept");assert.equal(h.offered(),false,label);assert.equal(h.node("retry-transcription").hidden,true,label);
      assert.match(h.notices.at(-1).message,expected,label);assert.doesNotMatch(h.notices.at(-1).message,/recording is kept/,label);assert.equal(h.notices.at(-1).kind,"general",label);
    }
    // A transcript that takes the reply box past its limit is delivered, not retried.
    const long=page();long.route(answers(heard("word ".repeat(1300))));await long.dictate();
    assert.equal(long.kept(),null);assert.equal(long.offered(),false);assert.ok(long.node("answer-text").value.length>6000);assert.match(long.notices.at(-1).message,/the limit is 6,000/);
  });

  await check("Discard recording and dismissing the banner give the recording up",async()=>{
    const h=page();h.route(answers(failing(503)));await h.dictate();
    h.t.discardFailedDictation();
    assert.equal(h.kept(),null);assert.equal(h.offered(),false);assert.equal(h.banner().hidden,true);
    await h.t.retryDictation();assert.equal(h.transcriptions().length,1,"Nothing is left to retry");
    const d=page();d.route(answers(failing(503)));await d.dictate();
    d.t.dismissInlineError("interview-error");
    assert.equal(d.kept(),null,"A dismissed banner would otherwise leave a kept recording with no control");assert.equal(d.offered(),false);assert.equal(d.banner().hidden,true);
    // Dismissing some other error does not touch a recording that is not there.
    d.t.dismissInlineError("review-error");assert.equal(d.kept(),null);
  });

  await check("only the latest recording is kept",async()=>{
    const h=page();h.route(answers(failing(503),failing(503),heard("The second recording.")));
    await h.dictate();const first=h.kept().blob;
    await h.dictate();const second=h.kept().blob;
    assert.notEqual(second,first);assert.equal(h.transcriptions()[1].options.body,second);
    await h.t.retryDictation();
    assert.equal(h.transcriptions()[2].options.body,second);assert.equal(h.node("answer-text").value,"The second recording.");
    // A new dictation that succeeds clears the earlier failure and its banner.
    const g=page();g.route(answers(failing(503),heard("Said again.")));await g.dictate();assert.ok(g.kept());
    await g.dictate();assert.equal(g.kept(),null);assert.equal(g.offered(),false);assert.equal(g.banner().hidden,true);assert.equal(g.node("answer-text").value,"Said again.");
  });

  await check("the kept recording does not outlive its interview, a file intake, live voice or ten minutes",async()=>{
    // A new interview.
    const reset=page();reset.route(answers(failing(503),heard()));await reset.dictate();assert.ok(reset.kept());
    reset.t.clearState();assert.equal(reset.kept(),null);assert.equal(reset.offered(),false);
    await reset.t.retryDictation();assert.equal(reset.transcriptions().length,1);assert.equal(reset.node("answer-text").value,"");
    // A recording whose interview was replaced while its retry was offered is never sent into the new one.
    const stale=page();stale.route(answers(failing(503),heard()));await stale.dictate();stale.t.state.generation++;
    await stale.t.retryDictation();assert.equal(stale.transcriptions().length,1);assert.equal(stale.kept(),null);assert.equal(stale.node("answer-text").value,"");
    // A file intake.
    const intake=page();intake.route(answers(failing(503)));await intake.dictate();assert.ok(intake.kept());
    intake.t.onDocumentEvent({type:"upload_started",batchId:"batch-a",names:["Payment SOP.pdf"]});
    assert.equal(intake.kept(),null);assert.equal(intake.offered(),false);
    // Ten minutes.
    const old=page();old.route(answers(failing(503)));await old.dictate();assert.ok(old.kept());
    await old.timer(10*60*1000);assert.equal(old.kept(),null);assert.equal(old.offered(),false);assert.equal(old.banner().hidden,true);
    // Live voice takes over Retry recording.
    const live=page();live.route(answers(failing(503)));await live.dictate();assert.ok(live.kept());
    live.context.CollectorControlledVoice=undefined;await live.t.startLiveConversation();
    assert.equal(live.kept(),null);assert.equal(live.offered(),false);
  });

  await check("a failure that arrives during a file intake, or for an oversized recording, says the recording was not kept",async()=>{
    const h=page(),reply=deferred();h.route(url=>url==="/api/transcribe"?reply.promise:response({}));
    await h.dictate();h.t.onDocumentEvent({type:"upload_started",batchId:"batch-a",names:["Payment SOP.pdf"]});
    reply.resolve(response({error:"Synthetic outage."},503));await flush();
    assert.equal(h.kept(),null);assert.equal(h.offered(),false);assert.match(h.notices.at(-1).message,/Synthetic outage\. The recording could not be kept; record it again, or type your answer\.$/);
    const big=page();big.route(answers(failing(503)));
    big.setLevel(.1);await big.t.startRecording();await flush();await big.advance(1500);
    big.recorders[0].emit("dataavailable",{data:new Blob([Buffer.alloc(12*1024*1024+1)])});big.t.finishRecording();await flush();
    assert.equal(big.kept(),null);assert.match(big.notices.at(-1).message,/could not be kept/);
  });

  await check("a retry cannot start while the page is busy, and the recording changes hands only once",async()=>{
    const h=page(),second=deferred();let calls=0;h.route(url=>url==="/api/transcribe"?(++calls===1?response({error:"Synthetic outage."},503):second.promise):response({}));
    await h.dictate();
    h.t.state.busy=true;await h.t.retryDictation();assert.equal(calls,1);h.t.state.busy=false;
    const retrying=h.t.retryDictation();await flush();
    assert.equal(calls,2);assert.equal(h.t.state.transcribing,true);assert.equal(h.kept(),null);assert.equal(h.offered(),false);
    await h.t.retryDictation();assert.equal(calls,2,"A second press while the retry runs sends nothing");
    second.resolve(response({text:"An analyst reviews the file."}));await retrying;
    assert.equal(h.node("answer-text").value,"An analyst reviews the file.");assert.equal(h.t.state.transcribing,false);
  });

  await check("the banner's controls are wired to the kept dictation before the voice session's retry",async()=>{
    const app=fs.readFileSync(path.join(__dirname,"..","web","app.js"),"utf8"),html=fs.readFileSync(path.join(__dirname,"..","web","index.html"),"utf8");
    assert.match(html,/<button type="button" id="retry-transcription" hidden>Retry recording<\/button><button type="button" id="discard-recording" hidden>Discard recording<\/button><\/div>/);
    assert.match(app,/\$\('retry-transcription'\)\?\.addEventListener\('click',async\(\)=>\{\s*if\(failedDictation\)\{await retryDictation\(\);return;\}/);
    assert.match(app,/\$\('discard-recording'\)\?\.addEventListener\('click',\(\)=>\{discardFailedDictation\(\);/);
    assert.match(app,/const DICTATION_RETRY_BYTES=12\*1024\*1024,DICTATION_RETRY_MS=10\*60\*1000;/,"The bounds are the voice controller's");
    assert.match(fs.readFileSync(path.join(__dirname,"..","web","controlled-voice.js"),"utf8"),/const MAX_RETRY_AUDIO=12\*1024\*1024, RETRY_AUDIO_MS=10\*60\*1000;/);
  });

  console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,physical_audio:false}));
});
