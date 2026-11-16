"use strict";
// Dictate's "Stop recording when I pause" counts only silence that was heard. It keeps working while
// the page is not drawn (no animation frames: a hidden, minimised or covered tab), and time during
// which nothing sampled the microphone is never treated as a pause.
// Real web/app.js behind a synthetic DOM, a manual clock and a synthetic microphone signal.
// No browser, microphone, provider or network.
const assert=require("node:assert/strict");
const {setup,run,flush,response}=require("./support/interview_page.cjs");
let passed=0;
const check=async(name,fn)=>{try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}};
const LOUD=.08,QUIET=0;
async function dictating(){
  const h=setup({expose:"startRecording,finishRecording"});
  h.node("stop-on-silence").checked=true;
  h.route(url=>url==="/api/transcribe"?response({text:"An analyst reviews the file."}):response({}));
  await h.t.startRecording();await flush();
  assert.ok(h.t.state.recording,"Dictation started");
  h.recording=()=>Boolean(h.t.state.recording)&&h.recorders.at(-1).state==="recording";
  h.stoppedAt=null;h.recorders.at(-1).addEventListener("stop",()=>{h.stoppedAt??=h.now();});
  // pass(ms, drawn): time passes; drawn pages get animation frames, hidden ones only the recorder's slices.
  h.pass=async(ms,drawn=true)=>{if(drawn)await h.visible(ms);else await h.advance(ms);await flush();};
  // The audit's signal: sound 0.4-2.4 s, a 1.8 s gap, sound 4.2-6.7 s, then silence.
  h.script=async(drawnUntil,drawnFrom=Infinity,total=16000)=>{
    const changes=[[400,LOUD],[2400,QUIET],[4200,LOUD],[6700,QUIET]];
    for(let at=0;at<total&&h.recording();at+=50){
      for(const [time,value] of changes)if(time===at)h.setLevel(value);
      await h.pass(50,at<drawnUntil||at>=drawnFrom);
    }
  };
  return h;
}

run(async()=>{
  await check("a visible page stops about 2.2 s after the last sound, and a 1.8 s gap does not end the recording",async()=>{
    const h=await dictating();await h.script(Infinity);
    assert.equal(h.recording(),false);assert.ok(h.stoppedAt>=8850&&h.stoppedAt<=9150,"stopped at "+h.stoppedAt+" ms");
    assert.equal(h.node("recording-label").textContent,"Finishing…");
    assert.equal(h.requests("/api/transcribe").length,1);assert.equal(h.node("answer-text").value,"An analyst reviews the file.");
  });

  await check("with no animation frames (hidden tab) the pause rule still ends the recording after the same pause",async()=>{
    const h=await dictating();await h.script(900);
    assert.equal(h.recording(),false,"The microphone does not stay open until Finish or the 90-second cap");
    assert.ok(h.stoppedAt>=8850&&h.stoppedAt<=9300,"stopped at "+h.stoppedAt+" ms, within one recorder slice of the visible case");
    assert.equal(h.frames.size,0,"The frame that never ran is cancelled with the recording");
    assert.equal(h.requests("/api/transcribe").length,1);
  });

  await check("returning to the page mid-sentence does not end the recording on the first quiet sample",async()=>{
    // Nothing runs from 0.9 s to 3.65 s (frames and slices are both held), then the page is drawn again.
    const h=await dictating();
    for(let at=0;at<900;at+=50){if(at===400)h.setLevel(LOUD);await h.pass(50);}
    h.suspend(2750);
    // The signal went quiet at 2.4 s while nothing was sampling; at 3.65 s the first sample is quiet.
    h.setLevel(QUIET,2400);
    await h.pass(150);
    assert.equal(h.recording(),true,"1.25 s of real silence, none of it observed for 2.2 s, is not a pause");
    // The rest of the sentence is recorded, and the rule ends the recording 2.2 s after it.
    for(let at=3800;at<16000&&h.recording();at+=50){if(at===4200)h.setLevel(LOUD);if(at===6700)h.setLevel(QUIET);await h.pass(50);}
    assert.equal(h.recording(),false);assert.ok(h.stoppedAt>=8850&&h.stoppedAt<=9150,"stopped at "+h.stoppedAt+" ms");
  });

  await check("a long unobserved silence is counted from the return, not from the last sound",async()=>{
    const h=await dictating();
    for(let at=0;at<2400;at+=50){if(at===400)h.setLevel(LOUD);await h.pass(50);}
    h.setLevel(QUIET);h.suspend(6000);
    // Back at 8.4 s: the participant may have been talking the whole time for all the app knows.
    await h.pass(2000);
    assert.equal(h.recording(),true,"Two seconds of observed silence is not yet a pause");
    await h.pass(400);
    assert.equal(h.recording(),false,"2.2 s of observed silence ends it");assert.ok(h.stoppedAt>=10600&&h.stoppedAt<=10800,"stopped at "+h.stoppedAt+" ms");
  });

  await check("becoming visible restarts the count, and the listener lives exactly as long as the recording",async()=>{
    const h=await dictating();
    assert.equal(h.documentListeners.visibilitychange.length,1);
    for(let at=0;at<2400;at+=50){if(at===400)h.setLevel(LOUD);await h.pass(50,false);}
    h.setLevel(QUIET);await h.pass(2000,false);
    assert.equal(h.recording(),true);
    h.document.hidden=false;h.emit("visibilitychange");
    assert.equal(h.t.state.recording.lastSound,h.now(),"The pause is counted from the moment the page is seen again");
    await h.pass(2000);assert.equal(h.recording(),true,"Not ended 2.2 s after the last sound, because the page came back in between");
    await h.pass(400);assert.equal(h.recording(),false);
    assert.equal(h.documentListeners.visibilitychange.length,0,"The listener is removed when the recording ends");
    // Hidden -> still hidden does nothing; a finished recording ignores the event.
    const g=await dictating();g.document.hidden=true;const before=g.t.state.recording.lastSound;await g.pass(300,false);g.emit("visibilitychange");
    assert.equal(g.t.state.recording.lastSound,before);
    g.t.finishRecording(true);await flush();assert.equal(g.documentListeners.visibilitychange.length,0);
  });

  await check("samples too far apart never add up to a pause, and the 90-second cap remains the backstop",async()=>{
    // The recorder's slices arrive once a second (a throttled page) and no frame runs.
    const h=await dictating(),recorder=h.recorders.at(-1);
    h.intervals.get(recorder.sliceTimer).ms=1000;
    for(let at=0;at<20000&&h.recording();at+=50){if(at===400)h.setLevel(LOUD);if(at===2400)h.setLevel(QUIET);await h.pass(50,false);}
    assert.equal(h.recording(),true,"Speech is not cut off by one sample a second");
    await h.pass(71000,false);
    assert.equal(h.recording(),false);assert.ok(h.notices.some(item=>/90 seconds/.test(item.message)));assert.ok(h.stoppedAt>=90000&&h.stoppedAt<=90400,"stopped at "+h.stoppedAt+" ms");
  });

  await check("a short word between two slices is heard on a hidden page",async()=>{
    const h=await dictating();
    for(let at=0;at<12000&&h.recording();at+=10){
      if(at===400)h.setLevel(LOUD);if(at===2000)h.setLevel(QUIET);
      // 100 ms of sound that begins and ends between the slices at 3.25 s and 3.5 s.
      if(at===3300)h.setLevel(LOUD);if(at===3400)h.setLevel(QUIET);
      await h.pass(10,false);
    }
    assert.equal(h.recording(),false);
    assert.ok(h.stoppedAt>=5600&&h.stoppedAt<=5900,"stopped at "+h.stoppedAt+" ms: 2.2 s after the short word, not after the earlier sentence");
  });

  await check("the rule stays off when the box is unticked or nothing was said",async()=>{
    const off=await dictating();off.node("stop-on-silence").checked=false;
    for(const drawn of [true,false]){for(let at=0;at<6000;at+=50){if(at===400&&drawn)off.setLevel(LOUD);if(at===1400&&drawn)off.setLevel(QUIET);await off.pass(50,drawn);}}
    assert.equal(off.recording(),true);
    const silent=await dictating();await silent.pass(6000);await silent.pass(6000,false);
    assert.equal(silent.recording(),true,"No speech was detected, so there is no pause to wait for");
    // Speech inside the first 1.8 s still needs the full pause after it.
    const early=await dictating();
    for(let at=0;at<5000&&early.recording();at+=50){if(at===100)early.setLevel(LOUD);if(at===300)early.setLevel(QUIET);await early.pass(50);}
    assert.equal(early.recording(),false);assert.ok(early.stoppedAt>=2450&&early.stoppedAt<=2650,"stopped at "+early.stoppedAt+" ms");
  });

  console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,physical_audio:false}));
});
