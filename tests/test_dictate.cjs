"use strict";
// The typed Dictate path (startRecording, monitorSilence, finishRecording, completeRecording) and the
// typed read-aloud entry points (speak, speakNatural), driven end to end: what reaches the reply
// box, when a request is made, and that the microphone, the level monitor and playback are released
// on every way out. The pause rule has its own suite (test_dictate_pause_rule.cjs), as has the retry
// of a failed transcription (test_dictate_retry.cjs).
// Real web/app.js behind a synthetic DOM, recorder, audio context and speech socket.
// No browser, microphone, speaker, provider or network.
const assert=require("node:assert/strict");
const {setup,run,flush,deferred,response,approved}=require("./support/interview_page.cjs");
let passed=0;
const check=async(name,fn)=>{try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}};
const HEARD="An analyst reviews the file.";
function page(reply=()=>response({text:HEARD})){
  const h=setup({modules:["document-intake.js"],expose:"startRecording,finishRecording,speak,clearState,onDocumentEvent",seam:"documentIntake=createDocumentIntake();window.__intake=()=>documentIntake;"});
  h.route(url=>url==="/api/transcribe"?reply():url==="/api/voice-session"?response(h.voiceSession):url==="/api/agent-team/interview"?response(approved()):response({}));
  h.transcriptions=()=>h.requests("/api/transcribe");
  h.begin=async()=>{h.setLevel(.1);await h.t.startRecording();await flush();assert.ok(h.t.state.recording,"Dictation started");return h.recorders.at(-1);};
  // Every microphone opened so far is closed, and every level monitor too, exactly once.
  h.released=label=>{
    assert.ok(h.tracks.length>0,label+": a microphone was opened");
    for(const track of h.tracks)assert.ok(track.stopped>=1,label+": the microphone track is stopped");
    for(const context of h.contexts)assert.equal(context.closed,1,label+": the level monitor is closed once");
    assert.equal(h.t.state.recording,null,label+": no recording is left");assert.equal(h.frames.size,0,label+": no animation frame is left");
    assert.equal(h.intervals.size,0,label+": no timer is left");assert.equal((h.documentListeners.visibilitychange||[]).length,0,label+": no page listener is left");
  };
  return h;
}

run(async()=>{
  await check("a dictated answer is appended to an empty reply box for review, not sent",async()=>{
    const h=page(),recorder=await h.begin();
    assert.equal(recorder.slice,250);assert.equal(recorder.mimeType,"audio/webm");assert.equal(h.contexts.length,1);
    assert.equal(h.node("recording-time").textContent,"0:00");assert.match(h.node("recording-label").textContent,/^Listening/);assert.equal(h.t.state.requestingMic,false);
    await h.advance(3200);assert.equal(h.node("recording-time").textContent,"0:03");
    await h.t.startRecording();await flush();
    assert.equal(h.transcriptions().length,1,"Pressing the button again finishes and transcribes");
    const sent=h.transcriptions()[0].options;assert.ok(sent.body instanceof Blob);assert.ok(sent.body.size>0);assert.equal(sent.headers["Content-Type"],"audio/webm");assert.equal(sent.headers["X-CSRF-Token"],"synthetic-csrf");
    assert.equal(h.node("answer-text").value,HEARD);assert.equal(h.t.state.turns.length,0,"Nothing is sent to the interview until Send");
    assert.equal(h.notices.at(-1).message,"Check the text, then choose Send.");assert.equal(h.t.state.transcribing,false);assert.equal(h.t.state.dirty,true);
    assert.equal(h.document.activeElement,h.node("answer-text"));
    h.released("finish");
  });

  await check("it is added after text already in the reply box, and a second dictation after the first",async()=>{
    const h=page();h.node("answer-text").value="  Typed first.  ";
    await h.begin();await h.advance(1000);h.t.finishRecording();await flush();
    assert.equal(h.node("answer-text").value,"Typed first.\n\n"+HEARD);
    await h.begin();await h.advance(1000);h.t.finishRecording();await flush();
    assert.equal(h.node("answer-text").value,"Typed first.\n\n"+HEARD+"\n\n"+HEARD);assert.equal(h.transcriptions().length,2);assert.equal(h.tracks.length,2);
    h.released("two dictations");
  });

  await check("Discard sends nothing and leaves the reply box alone",async()=>{
    const h=page();h.node("answer-text").value="Typed first.";
    await h.begin();await h.advance(4000);h.t.finishRecording(true);await flush();
    assert.equal(h.transcriptions().length,0);assert.equal(h.node("answer-text").value,"Typed first.");assert.equal(h.notices.length,0);assert.equal(h.t.state.transcribing,false);
    h.released("discard");
  });

  await check("a recording under 550 ms is refused without a request",async()=>{
    const h=page();await h.begin();await h.advance(500);h.t.finishRecording();await flush();
    assert.equal(h.transcriptions().length,0);assert.deepEqual(h.notices.map(item=>[item.message,item.error]),[["That recording was too short. Try again, or type your answer.",true]]);
    h.released("too short");
    const g=page();await g.begin();await g.advance(600);g.t.finishRecording();await flush();
    assert.equal(g.transcriptions().length,1,"0.6 s is long enough");
  });

  await check("the recording stops by itself at 90 seconds and is transcribed",async()=>{
    const h=page(),recorder=await h.begin();h.node("stop-on-silence").checked=false;
    await h.advance(89900);assert.equal(recorder.state,"recording");assert.equal(h.node("recording-time").textContent,"1:29");
    await h.advance(200);await flush();
    assert.equal(recorder.state,"inactive");assert.ok(h.notices.some(item=>item.message==="That’s 90 seconds, the most for one answer. Send this part, then keep going."));
    assert.equal(h.transcriptions().length,1);assert.equal(h.node("answer-text").value,HEARD);
    h.released("90-second cap");
  });

  await check("a pause after speech ends the recording when the box is ticked",async()=>{
    const h=page(),recorder=await h.begin();h.node("stop-on-silence").checked=true;
    await h.visible(400);h.setLevel(.08);await h.visible(1600);h.setLevel(0);await h.visible(2000);
    assert.equal(recorder.state,"recording","Two seconds of silence is not yet a pause");
    await h.visible(400);await flush();
    assert.equal(recorder.state,"inactive");assert.equal(h.node("recording-label").textContent,"Finishing…");assert.equal(h.transcriptions().length,1);
    h.released("pause rule");
  });

  await check("an empty transcript and a failed request are reported and nothing is appended",async()=>{
    const empty=page(()=>response({text:""}));empty.node("answer-text").value="Typed first.";
    await empty.begin();await empty.advance(1000);empty.t.finishRecording();await flush();
    assert.equal(empty.node("answer-text").value,"Typed first.");assert.equal(empty.notices.at(-1).message,"Couldn’t transcribe that. We didn’t catch that. Try again, or type your answer.");assert.equal(empty.notices.at(-1).error,true);
    assert.equal(empty.t.state.transcribing,false);empty.released("empty transcript");
    const failed=page(()=>response({error:"The recording is empty or too short. Please record your answer again."},400));
    await failed.begin();await failed.advance(1000);failed.t.finishRecording();await flush();
    assert.equal(failed.node("answer-text").value,"");assert.match(failed.notices.at(-1).message,/^Couldn’t transcribe that\. The recording is empty or too short\./);failed.released("failed request");
    const long=page(()=>response({text:"word ".repeat(1300)}));
    await long.begin();await long.advance(1000);long.t.finishRecording();await flush();
    assert.equal(long.node("answer-text").value.length,6499);assert.equal(long.notices.at(-1).message,"Your reply is 6,499 characters; the limit is 6,000. Nothing was removed. Shorten it or send it in two parts.");
  });

  await check("a new interview during the recording or the transcription receives none of it",async()=>{
    // Replaced while recording: the microphone closes and nothing is sent.
    const h=page();await h.begin();await h.advance(1500);
    h.t.state.generation++;h.t.finishRecording();await flush();
    assert.equal(h.transcriptions().length,0);assert.equal(h.node("answer-text").value,"");assert.equal(h.notices.length,0);h.released("replaced while recording");
    // Replaced while transcribing: the late text is not put into the new interview's reply box.
    const reply=deferred(),g=page(()=>reply.promise);
    await g.begin();await g.advance(1500);g.t.finishRecording();await flush();assert.equal(g.t.state.transcribing,true);
    g.t.clearState();assert.equal(g.t.state.transcribing,false);
    reply.resolve(response({text:"Words spoken in the earlier interview."}));await flush();
    assert.equal(g.node("answer-text").value,"");assert.ok(!g.notices.some(item=>/Check the text/.test(item.message)));
    // The same for a failure that arrives late.
    const failing=deferred(),f=page(()=>failing.promise);
    await f.begin();await f.advance(1500);f.t.finishRecording();await flush();f.t.clearState();const before=f.notices.length;
    failing.resolve(response({error:"Synthetic outage."},503));await flush();
    assert.equal(f.notices.length,before,"A failure of the replaced interview's request is not announced in the new one");
  });

  await check("a file added during the recording or the transcription ends the recording and keeps the words",async()=>{
    const h=page(),recorder=await h.begin();await h.advance(1500);
    h.t.onDocumentEvent({type:"upload_started",batchId:"batch-a",names:["Payment SOP.pdf"]});
    assert.equal(recorder.state,"inactive","The intake ends the recording");assert.equal(h.context.__intake().active,true);
    await flush();
    assert.equal(h.transcriptions().length,1,"What was said is still transcribed");assert.equal(h.node("answer-text").value,HEARD);
    h.released("file during recording");
    await h.t.startRecording();await flush();assert.equal(h.tracks.length,1,"Dictate does not start during a file intake");
    // During the transcription.
    const reply=deferred(),g=page(()=>reply.promise);
    await g.begin();await g.advance(1500);g.t.finishRecording();await flush();
    g.t.onDocumentEvent({type:"upload_started",batchId:"batch-a",names:["Payment SOP.pdf"]});
    reply.resolve(response({text:HEARD}));await flush();
    assert.equal(g.node("answer-text").value,HEARD);assert.equal(g.t.state.transcribing,false);g.released("file during transcription");
  });

  await check("the microphone and the level monitor are released when the recorder fails or the microphone goes away",async()=>{
    const failed=page(),recorder=await failed.begin();await failed.advance(1500);
    recorder.emit("error");await flush();
    assert.equal(recorder.state,"inactive");assert.equal(failed.transcriptions().length,0,"A failed recording is not sent");
    assert.ok(failed.notices.some(item=>item.message==="Recording didn’t work. Try again, or type your answer."&&item.error));failed.released("recorder error");
    // The track ends by itself (the device was unplugged): the browser stops the recorder.
    const gone=page(),lost=await gone.begin();await gone.advance(1500);
    lost.end();await flush();
    assert.equal(gone.transcriptions().length,1,"What was recorded until then is transcribed");assert.equal(gone.node("answer-text").value,HEARD);gone.released("microphone lost");
  });

  await check("a microphone granted too late, or to a recorder that cannot start, is closed at once",async()=>{
    // The interview was replaced while the permission prompt was open.
    const h=page(),grant=deferred();h.microphone(()=>grant.promise);
    const starting=h.t.startRecording();await flush();assert.equal(h.t.state.requestingMic,true);
    h.t.state.generation++;grant.resolve(h.openMicrophone());await starting;
    assert.equal(h.t.state.recording,null);assert.equal(h.recorders.length,0);assert.equal(h.tracks[0].stopped,1);
    // A file intake began while the prompt was open.
    const g=page(),late=deferred();g.microphone(()=>late.promise);
    const waiting=g.t.startRecording();await flush();g.t.onDocumentEvent({type:"upload_started",batchId:"batch-a",names:["Payment SOP.pdf"]});late.resolve(g.openMicrophone());await waiting;
    assert.equal(g.t.state.recording,null);assert.equal(g.recorders.length,0);assert.equal(g.tracks[0].stopped,1);assert.equal(g.t.state.requestingMic,false);
    // The recorder cannot be created for the stream.
    const broken=page();broken.context.MediaRecorder=class{static isTypeSupported(){return false;}constructor(){throw Object.assign(new Error("No supported format"),{name:"NotSupportedError"});}};
    await broken.t.startRecording();await flush();
    assert.equal(broken.t.state.recording,null);assert.equal(broken.tracks[0].stopped,1);assert.equal(broken.notices.at(-1).message,"Recording could not start: No supported format");assert.equal(broken.t.state.requestingMic,false);
  });

  await check("Dictate says why it cannot start",async()=>{
    for(const [name,expected] of [["NotAllowedError",/^Microphone access was not granted\./],["NotFoundError",/^No microphone was found\./],["NotReadableError",/^The microphone could not be opened\./]]){
      const h=page();h.microphone(()=>Promise.reject(Object.assign(new Error("synthetic"),{name})));
      await h.t.startRecording();await flush();
      assert.match(h.notices.at(-1).message,expected);assert.equal(h.notices.at(-1).error,true);assert.equal(h.t.state.recording,null);assert.equal(h.t.state.requestingMic,false);assert.equal(h.recorders.length,0);
    }
    const old=page();old.context.MediaRecorder=undefined;await old.t.startRecording();
    assert.match(old.notices.at(-1).message,/^This browser can’t record audio\./);assert.equal(old.tracks.length,0);
    // Not while something else owns the page.
    for(const busy of [h=>{h.t.state.busy=true;},h=>{h.t.state.transcribing=true;},h=>{h.t.conversationUI.live={active:true};},h=>{h.t.conversationUI.status="closing";}]){
      const h=page();busy(h);await h.t.startRecording();await flush();assert.equal(h.tracks.length,0);assert.equal(h.t.state.recording,null);
    }
  });

  await check("read-aloud does not start over a dictation",async()=>{
    const h=page();await h.begin();
    h.t.speak("What happens next?");
    assert.deepEqual(h.notices.map(item=>item.message),["Finish recording your answer before playing a question."]);
    h.t.speak("What happens next?",true);
    assert.equal(h.notices.length,1,"An automatic read-aloud stays silent about it");
    assert.equal(h.requests("/api/voice-session").length,0);assert.equal(h.sockets.length,0);assert.equal(h.utterances.length,0);assert.equal(h.t.state.speechOperation,null);
    // The same while the microphone permission is pending.
    const g=page(),grant=deferred();g.microphone(()=>grant.promise);const starting=g.t.startRecording();await flush();
    g.t.speak("What happens next?");assert.equal(g.notices.at(-1).message,"Finish recording your answer before playing a question.");assert.equal(g.requests("/api/voice-session").length,0);
    grant.resolve(g.openMicrophone());await starting;
  });

  await check("Dictate stops a question that is being read aloud",async()=>{
    const h=page();h.t.speak("What happens next?");await flush();await h.speech("What happens next?");
    assert.equal(h.audio.length,1);assert.equal(h.audio[0].playCalls,1);assert.equal(h.node("voice-status").textContent,"Speaking · Marin");
    await h.begin();
    assert.equal(h.audio[0].paused,true);assert.equal(h.audio[0].url,null);assert.equal(h.revoked.length,1);assert.equal(h.t.state.speechOperation,null);assert.equal(h.node("stop-speaking").hidden,true);
  });

  await check("the natural voice plays the question and releases everything when it ends",async()=>{
    const h=page();h.t.speak("Who approves the payment?");
    assert.equal(h.node("stop-speaking").hidden,false);assert.equal(h.node("voice-status").hidden,false);assert.equal(h.node("voice-status").textContent,"Preparing AI voice…");
    await flush();assert.equal(h.requests("/api/voice-session").length,1);assert.equal(h.body(h.requests("/api/voice-session")[0]).voice,"marin");assert.equal(h.audio.length,0,"Nothing is heard before the reading is verified");
    await h.speech("Who approves the payment?");
    assert.equal(h.audio.length,1);assert.equal(h.audio[0].playCalls,1);assert.equal(h.sockets[0].closed,true);assert.equal(h.node("voice-status").textContent,"Speaking · Marin");
    h.audio[0].emit("ended");
    assert.equal(h.t.state.speechOperation,null);assert.equal(h.audio[0].url,null);assert.equal(h.revoked.length,1);assert.equal(h.node("stop-speaking").hidden,true);assert.equal(h.node("voice-status").hidden,true);
    assert.ok(![...h.timers.values()].some(item=>item.ms===60000),"The preparation deadline is cleared");
  });

  await check("Stop voice, a newer question and a sent answer each tear the reading down at any stage",async()=>{
    // Stopped before the voice session arrived: nothing is opened afterwards.
    const early=page(),session=deferred();early.route(url=>url==="/api/voice-session"?session.promise:response({}));
    early.t.speak("Who approves the payment?");await flush();const operation=early.t.state.speechOperation;
    early.t.stopSpeaking();assert.equal(operation.controller.signal.aborted,true);assert.equal(early.t.state.speechOperation,null);
    session.resolve(response(early.voiceSession));await flush();
    assert.equal(early.sockets.length,0);assert.equal(early.audio.length,0);assert.equal(early.notices.length,0,"A cancelled reading is not reported as an error");assert.equal(early.node("stop-speaking").hidden,true);
    // Stopped while the audio was being generated: the socket closes, late packets are ignored.
    const mid=page();mid.t.speak("Who approves the payment?");await flush();assert.equal(mid.sockets.length,1);
    mid.t.stopSpeaking();assert.equal(mid.sockets[0].closed,true);
    await mid.speech("Who approves the payment?",mid.sockets[0]).catch(()=>{});
    assert.equal(mid.audio.length,0);assert.equal(mid.notices.length,0);
    // A newer question replaces the one being prepared; only the newer one is heard.
    const newer=page();newer.t.speak("An earlier question?");await flush();const first=newer.sockets[0];
    newer.t.speak("The current question?");await flush();
    assert.equal(first.closed,true);assert.equal(newer.sockets.length,2);
    await newer.speech("The current question?");
    assert.equal(newer.audio.length,1);assert.equal(newer.audio[0].playCalls,1);
    // An answer sent while a question is playing stops the playback.
    const sent=page();sent.t.speak("How does the work start?");await flush();await sent.speech("How does the work start?");assert.equal(sent.audio[0].paused,false);
    sent.node("answer-text").value="A supplier email starts a case.";await sent.t.sendAnswer({preventDefault(){}});
    assert.equal(sent.audio[0].paused,true);assert.equal(sent.audio[0].url,null);assert.equal(sent.revoked.length,1);assert.equal(sent.t.state.speechOperation,null);
    // A reading that never gets ready is given up after a minute, with a way forward.
    const slow=page();slow.route((url,options)=>url==="/api/voice-session"?new Promise((_,reject)=>options.signal.addEventListener("abort",()=>reject(new DOMException("Aborted","AbortError")))):response({}));
    slow.t.speak("Who approves the payment?");await flush();await slow.timer(60000);
    assert.match(slow.notices.at(-1).message,/^The natural AI voice took too long\./);assert.equal(slow.t.state.speechOperation,null);assert.equal(slow.node("stop-speaking").hidden,true);
  });

  await check("an installed voice reads the question and is cancelled the same way",async()=>{
    const h=page();h.t.state.voiceChoice="local:synthetic";h.t.state.voice={name:"Synthetic",lang:"en-US"};
    h.t.speak("Who owns this process?");
    assert.equal(h.utterances.length,1);assert.equal(h.utterances[0].text,"Who owns this process?");assert.equal(h.utterances[0].lang,"en-US");assert.equal(h.requests("/api/voice-session").length,0);
    assert.equal(h.node("stop-speaking").hidden,false);assert.equal(h.t.state.utterance,h.utterances[0]);
    h.utterances[0].onend();assert.equal(h.t.state.utterance,null);assert.equal(h.node("stop-speaking").hidden,true);
    // A newer question: the earlier utterance's late events change nothing.
    h.t.speak("First?");const first=h.utterances.at(-1);h.t.speak("Second?");const second=h.utterances.at(-1);
    first.onend();assert.equal(h.t.state.utterance,second,"The earlier utterance ending does not clear the current one");
    first.onerror({error:"interrupted"});assert.equal(h.notices.length,0);
    second.onerror({error:"synthesis-failed"});
    assert.equal(h.t.state.utterance,null);assert.match(h.notices.at(-1).message,/^The installed voice could not play this question\./);
    // No usable voice: a request to listen says so, an automatic one stays quiet.
    const none=page();none.t.state.voiceChoice="local:missing";none.t.state.voice=null;
    none.t.speak("Who owns this process?",true);assert.equal(none.notices.length,0);
    none.t.speak("Who owns this process?");assert.match(none.notices.at(-1).message,/^Choose an available interviewer voice\./);assert.equal(none.utterances.length,0);
  });

  console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,physical_audio:false}));
});
