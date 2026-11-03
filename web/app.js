"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const TOPICS = [
    ["name", "Name / scope"], ["purpose", "Purpose"], ["trigger", "Trigger"],
    ["completion", "Completion"], ["accountable", "Accountable owner"], ["lifecycle", "Work lifecycle"],
    ["checks", "Checks / controls"], ["variations", "Variations"], ["pain_points", "Pain points"],
    ["risk", "Risk / impact"], ["materials", "Existing materials"]
  ];
  const MEMO_HEADINGS = {
    name:"Name and other names",purpose:"Purpose",trigger:"Start, cadence and fixed deadlines",
    completion:"Finished condition",accountable:"Accountability",lifecycle:"Things, stages, locations and handoffs",
    checks:"Checks, approvals and proof",variations:"Differences",pain_points:"Manual or painful work",
    risk:"Consequence of failure",materials:"Existing written material"
  };
  const TOPIC_GUIDES = {
    name:"The work's name, other names and boundary.",purpose:"The result this work is meant to deliver.",
    trigger:"What starts the work, how often it happens and any deadlines.",completion:"What must be true for this work to be finished.",
    accountable:"The role accountable for the overall result; it may remain unknown.",lifecycle:"The items, stages, locations and handoffs along the route.",
    checks:"The reported checks, reviewers, approvals and supporting evidence.",variations:"Where the process differs and whether that changes its boundary.",
    pain_points:"Manual work, waiting, rework and other friction.",risk:"What happens if this work is late, wrong or missed.",
    materials:"Existing procedures, templates, examples and other useful records."
  };
  let foundationTopic = null, foundationReturnFocus = null, foundationRestoreFocus = true;
  const REVIEW_SECTIONS = ["review-memo","review-map","review-procedure","review-lifecycles","review-variations","review-questions"];
  const reviewUI = {section:"review-memo",mapScale:1,mapFit:true};
  const state = {
    context: null, turns: [], coverage: [], summary: "", draft: null,
    started: false, busy: false, version: 0, generation: 0,
    draftVersion: null, draftEdited: false, example: false, dirty: false,
    config: null, utterance: null, voice: null, speechVersion: 0,
    localVoices: [], voiceChoice: null, voiceChoiceUser: false, speechOperation: null,
    recording: null, requestingMic: false, transcribing: false,
    memo_findings: [], focus: "", parking_lot: [], closure: {asked:false,confirmed:false},
    elapsedMs: 0, timerStartedAt: null
  };
  const icons = {
    play: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m5 3 7 5-7 5Z"/></svg>'
  };
  const svgNS = "http://www.w3.org/2000/svg";

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function svgEl(tag, attrs = {}, text) {
    const node = document.createElementNS(svgNS, tag);
    Object.entries(attrs).forEach(([k, value]) => node.setAttribute(k, String(value)));
    if (text !== undefined) node.textContent = text;
    return node;
  }
  const text = (value, limit = 18000) => {
    if (typeof value !== "string") return "";
    if (value.length > limit) throw new Error(`A text field exceeds the supported ${limit.toLocaleString()} characters. No content was truncated.`);
    return value;
  };
  const strings = (value, limit = 100) => {
    if (!Array.isArray(value)) return [];
    if (value.length > limit || value.some(x => typeof x !== "string")) throw new Error("A list has too many entries or an invalid value. No content was truncated.");
    return value.map(x => text(x,6000));
  };
  const lines = (value) => value.split("\n").map(v => v.trim()).filter(Boolean);
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const nextTurnId = () => {
    let n = state.turns.length + 1;
    while (state.turns.some(turn => turn.id === `t${String(n).padStart(3, "0")}`)) n++;
    return `t${String(n).padStart(3, "0")}`;
  };
  const safeFilename = (name) => (name || "process").replace(/[^a-zA-Z0-9 _-]/g, "").trim().replace(/\s+/g, "-").slice(0, 75) || "process";

  function notice(message, error = false) {
    $("notice-text").textContent = message;
    $("global-notice").classList.toggle("error", error);
    $("global-notice").hidden = false;
    $("live-status").textContent = message;
  }
  function closeMenu() {
    $("session-menu").hidden = true;
    $("session-menu-toggle").setAttribute("aria-expanded", "false");
  }
  function tab(name, focus = false) {
    $("interview-view").hidden = name !== "interview";
    $("review-view").hidden = name !== "review";
    document.body?.classList.toggle("review-mode", name === "review");
    if (name === "review") selectReviewSection(reviewUI.section);
    document.querySelectorAll(".nav-tab").forEach(button => {
      const active = button.dataset.tab === name;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
    });
    if (focus) {
      const target = name === "review" ? $("review-view") : state.started ? $("answer-text") : $("process-name");
      if (name === "interview" && !state.started) revealAncestors(target);
      target.tabIndex = -1;
      target.focus({preventScroll: true});
    }
  }
  function readContext() {
    return {
      process_name: $("process-name").value.trim(),
      process_owner: $("process-owner").value.trim(),
      objective: $("objective").value.trim(),
      background: $("background").value.trim(),
      meeting_minutes: Number($("meeting-minutes").value) || 60
    };
  }
  function fillContext(context) {
    $("process-name").value = context?.process_name || "";
    $("process-owner").value = context?.process_owner || "";
    $("objective").value = context?.objective || "Understand the current process, responsibilities, handoffs, and exceptions.";
    $("background").value = context?.background || "";
    $("meeting-minutes").value = context?.meeting_minutes || 60;
  }
  function revealAncestors(target) {
    for (let node = target; node; node = node.parentElement) {
      if (node.tagName === "DETAILS") node.open = true;
    }
  }
  function revealContext() {
    if ($("setup-card")) $("setup-card").open = true;
    if ($("context-details")) $("context-details").open = true;
    revealAncestors($("context-form"));
  }
  function updateSaveHint() {
    const hint = $("save-hint");
    if (!hint) return;
    const message = state.dirty ? "Changes to save" : "";
    if (hint.textContent !== message) hint.textContent = message;
    hint.hidden = !state.dirty;
  }
  function updateLaunchPlan() {
    const hint = $("launch-plan-summary");
    if (!hint) return;
    const minutes = Number($("meeting-minutes").value);
    hint.textContent = Number.isInteger(minutes) && minutes >= 1 && minutes <= 1440 ? `${minutes} min · flexible` : "Flexible duration";
  }
  function updateControls() {
    const ready = Boolean(state.config?.api_configured);
    const working = state.busy || state.transcribing || state.requestingMic;
    const recording = Boolean(state.recording);
    const atLimit = state.turns.length >= 399 || state.turns.reduce((n,t) => n+t.text.length,0) >= 394000;
    $("start-interview").disabled = working || recording || (!ready && !state.started);
    const previouslyStarted = document.body?.classList.contains("interview-started");
    document.body?.classList.toggle("interview-started", state.started);
    if ($("setup-card") && previouslyStarted !== undefined && previouslyStarted !== state.started) $("setup-card").open = !state.started;
    if ($("setup-summary")) $("setup-summary").textContent = state.started ? state.context?.process_name || "Interview" : "Set up an interview";
    $("start-interview").firstElementChild.textContent = state.started ? "New interview" : "Start interview";
    ["process-name", "process-owner", "objective", "background"].forEach(id => { $(id).disabled = state.started || working || recording; });
    $("answer-text").disabled = !state.started || working || recording || !ready;
    $("send-answer").disabled = !state.started || working || recording || !ready || atLimit || !$("answer-text").value.trim();
    $("record-answer").disabled = !state.started || working || !ready || atLimit;
    $("skip-question").disabled = !state.started || working || recording || !ready || atLimit;
    $("final-check").disabled = !state.started || working || recording || !ready || atLimit || !state.turns.some(t => t.role === "user");
    $("pause-timer").disabled = !state.started;
    $("meeting-minutes").disabled = working || recording;
    $("composer-hint").textContent = atLimit ? "Interview limit reached. Create a draft or save this session." : "Review the transcript, then send.";
    const canDraft = ready && state.turns.some(t => t.role === "user") && !working && !recording;
    $("generate-draft").disabled = !canDraft;
    $("regenerate-draft").disabled = !canDraft;
    $("export-markdown").disabled = !state.draft;
    $("draft-dot").hidden = !state.draft;
    $("example-banner").hidden = !state.example;
    $("draft-stale").hidden = !state.draft || state.draftVersion === state.version;
    $("thinking").hidden = !working;
    if ($("current-question")) $("current-question").setAttribute("aria-busy", String(state.busy));
    $("thinking-text").textContent = state.requestingMic ? "Waiting for microphone permission…" : state.transcribing ? "Turning your recording into an editable answer…" : state.busyMessage || "Finding the next useful question…";
    $("record-answer").classList.toggle("recording", recording);
    $("record-answer").querySelector("span").textContent = recording ? "Finish" : "Speak";
    $("recording-status").hidden = !recording;
    const voiceReady = canSpeakChoice();
    $("speak-questions").disabled = !voiceReady;
    $("speak-questions").title = voiceReady ? `Selected voice: ${voiceLabel()}` : "Choose an available voice. Questions remain readable on screen.";
    $("voice-select").disabled = recording || state.requestingMic;
    $("preview-voice").disabled = !voiceReady || working || recording;
    $("welcome").hidden = state.turns.length > 0 || working;
    $("review-empty").hidden = Boolean(state.draft);
    $("draft-content").hidden = !state.draft;
    $("draft-content").classList.toggle("draft-content-loading", state.busy);
    $("draft-content").inert = state.busy;
    $("current-focus").hidden = !state.focus;
    $("current-focus").textContent = state.focus || "";
    $("closure-status").hidden = !state.closure.asked && !state.closure.confirmed;
    $("closure-status").textContent = state.closure.confirmed ? "Participant confirmed completeness." : state.closure.asked ? "Waiting for final confirmation." : "";
    updateSaveHint(); updateLaunchPlan();
    updateTimer();
  }
  function setBusy(value, message = "") {
    state.busy = value;
    state.busyMessage = message;
    updateControls();
  }
  function scrollConversation() {
    requestAnimationFrame(() => {
      $("conversation-scroll").scrollTop = $("conversation-scroll").scrollHeight;
    });
  }
  function renderCoverage() {
    const root = $("coverage-list");
    root.replaceChildren();
    let completed = 0;
    let partial = 0;
    TOPICS.forEach(([key, label]) => {
      const item = state.coverage.find(c => c.key === key);
      const finding = state.memo_findings.find(c => c.key === key);
      const status = finding?.status === "not_applicable" || finding?.status === "captured" ? "covered" : finding?.status === "partial" ? "partial" : ["partial", "covered"].includes(item?.status) ? item.status : "missing";
      if (status === "covered") completed++;
      if (status === "partial") partial++;
      const node = el("button", `coverage-item ${status}`);
      node.type = "button";
      node.dataset.foundationTopic = key;
      node.setAttribute("aria-haspopup", "dialog");
      node.setAttribute("aria-controls", "foundation-dialog");
      node.classList.toggle("selected", foundationTopic === key && Boolean($("foundation-dialog")?.open));
      node.title = `${label}: ${finding?.status === "not_applicable" ? "not applicable (participant confirmed)" : status === "missing" ? "not yet explored" : status}`;
      node.setAttribute("aria-label", node.title);
      node.append(el("span", "coverage-dot", status === "covered" ? "✓" : ""), el("span", "", label));
      node.addEventListener("click", () => showFoundationTopic(key,node));
      root.append(node);
    });
    $("coverage-count").textContent = `${completed} / ${TOPICS.length}`;
    $("coverage-progress").style.width = `${(completed + partial * .5) / TOPICS.length * 100}%`;
  }
  function showFoundationTopic(key, trigger) {
    if (!TOPICS.some(([topic]) => topic === key)) return;
    const dialog = $("foundation-dialog");
    if (!dialog || typeof dialog.showModal !== "function") {notice("Topic details are unavailable in this browser. Please use a current browser.",true);return;}
    const finding = state.memo_findings.find(item => item.key === key);
    const labels = {unknown:"Unknown / TBD",partial:"Partial",captured:"Captured",not_applicable:"Not applicable"};
    foundationTopic = key; foundationReturnFocus = trigger; foundationRestoreFocus = true;
    $("foundation-topic-title").textContent = MEMO_HEADINGS[key];
    $("foundation-topic-status").textContent = labels[finding?.status] || labels.unknown;
    $("foundation-topic-answer").textContent = finding?.answer?.trim() ? finding.answer : "Not yet established in this interview.";
    $("foundation-topic-hint").textContent = finding?.answer?.trim() ? "Reported from the interview; not independently verified. Review the cited answers for context." : TOPIC_GUIDES[key];
    $("foundation-topic-sources").replaceChildren(evidenceRow(finding?.evidence_turns || [], () => closeFoundationTopic(false)));
    if (!dialog.open) dialog.showModal();
    document.querySelectorAll("[data-foundation-topic]").forEach(button => button.classList.toggle("selected",button.dataset.foundationTopic === key));
  }
  function closeFoundationTopic(restoreFocus = true) {
    foundationRestoreFocus = restoreFocus;
    $("foundation-dialog")?.close();
  }
  function initFoundationDialog() {
    $("close-foundation-topic").addEventListener("click",() => closeFoundationTopic());
    $("foundation-dialog").addEventListener("close",() => {
      document.querySelectorAll("[data-foundation-topic]").forEach(button => button.classList.remove("selected"));
      const trigger = foundationReturnFocus?.isConnected ? foundationReturnFocus : document.querySelector(`[data-foundation-topic="${foundationTopic}"]`);
      if (foundationRestoreFocus && trigger) {revealAncestors(trigger);trigger.focus({preventScroll:true});}
      foundationReturnFocus = null; foundationTopic = null; foundationRestoreFocus = true;
    });
  }
  function renderTranscript() {
    const root = $("transcript");
    const current = $("current-question");
    const latest = state.turns.findLast(turn => turn.role === "assistant");
    root.replaceChildren();
    state.turns.forEach(turn => {
      const isCurrent = turn === latest;
      const retained = current.firstElementChild;
      if (isCurrent && retained?.id === `turn-${turn.id}` && retained.querySelector(".turn-text")?.textContent === turn.text) {
        const listen = retained.querySelector(".play-turn");
        listen.disabled = !canSpeakChoice();
        listen.title = canSpeakChoice() ? `Play using ${voiceLabel()}` : "Choose an available interviewer voice.";
        return;
      }
      const item = el("article", `turn ${turn.role}`);
      item.id = `turn-${turn.id}`;
      const avatar = el("div", "turn-avatar", turn.role === "assistant" ? "AI" : "YOU");
      avatar.setAttribute("aria-hidden", "true");
      const content = el("div", "turn-content");
      const meta = el("div", "turn-meta");
      const reference = el("span", "turn-id", sourceCaption(turn.id));
      reference.title = turn.id;
      meta.append(el("span", "turn-name", turn.role === "assistant" ? "Interviewer" : "You"), reference);
      content.append(meta, el("p", "turn-text", turn.text));
      if (turn.role === "assistant") {
        const play = el("button", "play-turn");
        play.innerHTML = icons.play;
        play.append(document.createTextNode(" Listen"));
        play.setAttribute("aria-label", `Listen to ${sourceCaption(turn.id)} using the selected voice`);
        play.disabled = !canSpeakChoice();
        play.title = canSpeakChoice() ? `Play using ${voiceLabel()}` : "Choose an available interviewer voice.";
        play.addEventListener("click", () => speak(turn.text));
        content.append(play);
      }
      item.append(avatar, content);
      if (isCurrent) current.replaceChildren(item); else root.append(item);
    });
    if (!latest) current.replaceChildren();
    current.hidden = !latest;
    const historyLength = state.turns.length - (latest ? 1 : 0);
    $("conversation-history").hidden = !historyLength;
    $("history-count").textContent = historyLength ? `${historyLength} ${historyLength === 1 ? "message" : "messages"}` : "";
    $("working-summary").hidden = !state.summary;
    $("summary-text").textContent = state.summary;
    $("parking-panel").hidden = !state.parking_lot.length;
    $("parking-count").textContent = state.parking_lot.length ? `(${state.parking_lot.length})` : "";
    $("parking-list").replaceChildren(...state.parking_lot.map(item => el("li","",item)));
    renderCoverage();
    updateControls();
  }
  async function request(path, data, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.timeout || 150000);
    const external = options.signal;
    const abort = () => controller.abort();
    if (external) {
      external.addEventListener("abort", abort, {once: true});
      if (external.aborted) controller.abort();
    }
    try {
      const headers = {"X-CSRF-Token": state.config?.csrf_token || ""};
      let body;
      if (data instanceof Blob) {
        headers["Content-Type"] = data.type || "audio/webm";
        body = data;
      } else {
        headers["Content-Type"] = "application/json";
        body = JSON.stringify(data);
      }
      const response = await fetch(path, {method: "POST", headers, body, signal: controller.signal, credentials: "same-origin"});
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        const message = text(result.error || result.message, 600);
        if (response.status >= 500 || [401, 402, 403, 429].includes(response.status) || /\b(?:API|OpenAI|Azure|credentials?|quota|billing|credits?|CSRF|endpoint|provider|configuration|configured)\b/i.test(message)) {
          throw new Error("The interviewer is unavailable. Please try again.");
        }
        throw new Error(message || "The interviewer is unavailable. Please try again.");
      }
      return options.audio ? await response.blob() : await response.json();
    } catch (error) {
      if (error.name === "AbortError" && !external?.aborted) throw new Error("The request took too long. Your answer is still available; please try again.");
      if (error.name === "TypeError") throw new Error("The interviewer is unavailable. Please try again.");
      throw error;
    } finally {
      clearTimeout(timeout);
      external?.removeEventListener("abort", abort);
    }
  }
  function stopSpeaking() {
    state.speechVersion++;
    const operation = state.speechOperation;
    state.speechOperation = null;
    if (operation) {
      clearTimeout(operation.timer);
      operation.controller.abort();
      try { operation.socket?.close(); } catch { /* Socket may still be connecting. */ }
      operation.audio?.pause();
      if (operation.audio) operation.audio.removeAttribute("src");
      if (operation.url) URL.revokeObjectURL(operation.url);
    }
    window.speechSynthesis?.cancel();
    state.utterance = null;
    $("stop-speaking").hidden = true;
    $("voice-status").hidden = true;
  }
  function naturalVoices() {
    const voices = state.config?.speech?.voices;
    return Array.isArray(voices) ? voices.filter(v => v && typeof v.id === "string" && /^[a-z]+$/.test(v.id)).map(v => ({id:v.id,label:text(v.label,80)||v.id,description:text(v.description,250)})) : [];
  }
  const localVoiceId = voice => `local:${voice.voiceURI || voice.name}`;
  function selectedNaturalVoice() {
    if (!state.voiceChoice?.startsWith("ai:")) return null;
    return naturalVoices().find(v => `ai:${v.id}` === state.voiceChoice) || null;
  }
  function canSpeakChoice() {
    return selectedNaturalVoice() ? Boolean(state.config?.speech?.enabled && window.WebSocket) : Boolean(state.voice && window.speechSynthesis && window.SpeechSynthesisUtterance);
  }
  function voiceLabel() {return selectedNaturalVoice()?.label || state.voice?.name || "Unavailable voice";}
  function populateVoiceOptions() {
    const select = $("voice-select");
    const ai = naturalVoices();
    if (!state.voiceChoiceUser && state.config?.speech?.enabled && ai.length) {
      const preferred = state.config.speech.default_voice;
      state.voiceChoice = `ai:${ai.find(v => v.id === preferred)?.id || ai[0].id}`;
    } else if (!state.voiceChoice && state.localVoices.length) {
      const preferred = state.localVoices.find(v => /^en[-_]US$/i.test(v.lang)) || state.localVoices.find(v => v.default) || state.localVoices[0];
      state.voiceChoice = localVoiceId(preferred);
    }
    select.replaceChildren();
    if (ai.length) {
      const group = el("optgroup"); group.label = "Natural AI voices";
      ai.forEach(voice => {const option=el("option","",voice.label);option.value=`ai:${voice.id}`;option.disabled=!state.config?.speech?.enabled;group.append(option);});
      select.append(group);
    }
    if (state.localVoices.length) {
      const group = el("optgroup"); group.label = "Installed computer voices";
      state.localVoices.forEach(voice => {const option=el("option","",`${voice.name} · ${voice.lang}`);option.value=localVoiceId(voice);group.append(option);});
      select.append(group);
    }
    if (!Array.from(select.options).some(o => o.value === state.voiceChoice)) {
      const option=el("option","",state.voiceChoice ? "Saved voice unavailable — choose a voice" : "No voice is currently available");
      option.value=state.voiceChoice || "";option.disabled=true;select.prepend(option);
    }
    select.value = state.voiceChoice || "";
    state.voice = state.localVoices.find(v => localVoiceId(v) === state.voiceChoice) || null;
    const natural = selectedNaturalVoice();
    if ($("voice-summary-label")) $("voice-summary-label").textContent = canSpeakChoice() ? `Voice · ${voiceLabel()}` : "Voice settings";
    $("voice-description").textContent = natural ? "AI-generated speech." : state.voice ? "Computer voice · plays on this device." : "Choose a voice to hear questions.";
    $("voice-availability").hidden = canSpeakChoice();
    $("voice-availability").textContent = canSpeakChoice() ? "" : natural ? "The natural AI voice is unavailable. You can choose an installed computer voice or read the questions." : "No selected voice is available. Choose another voice or read the questions.";
    updateControls();
    renderTranscript();
  }
  function refreshVoices() {
    state.localVoices = (window.speechSynthesis?.getVoices() || []).filter(v => v.localService && /^en(?:[-_]|$)/i.test(v.lang));
    populateVoiceOptions();
  }
  function normalizedSpeech(value) {
    return value.normalize("NFKC").toLocaleLowerCase("en").replace(/[^\p{L}\p{N}]/gu, "");
  }
  function pcmWave(chunks, length) {
    if (length < 2 || length % 2) throw new Error("The AI voice returned incomplete audio. Please try again.");
    const bytes = new Uint8Array(44 + length);
    const view = new DataView(bytes.buffer);
    const ascii = (offset, value) => {for (let i=0;i<value.length;i++) bytes[offset+i]=value.charCodeAt(i);};
    ascii(0,"RIFF");view.setUint32(4,36+length,true);ascii(8,"WAVE");ascii(12,"fmt ");view.setUint32(16,16,true);
    view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,24000,true);view.setUint32(28,48000,true);
    view.setUint16(32,2,true);view.setUint16(34,16,true);ascii(36,"data");view.setUint32(40,length,true);
    let offset=44;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
    return new Blob([bytes],{type:"audio/wav"});
  }
  function naturalSpeechAudio(session, message, operation) {
    if (session?.provider !== "openai" || session?.transport !== "openai-realtime-websocket") {
      return Promise.reject(new Error("The selected AI voice connection is not supported by this version. Choose an installed computer voice or read the question on screen."));
    }
    return openAIRealtimeSpeechAudio(session, message, operation);
  }
  function openAIRealtimeSpeechAudio(session, message, operation) {
    return new Promise((resolve,reject) => {
      let settled=false,inputSent=false,responseSent=false,bytes=0,transcript="";
      const chunks=[];
      const itemId=`voice_${state.speechVersion}_${Date.now()}`;
      const fail=message => finish(new Error(message));
      let socket;
      const abort=() => finish(new DOMException("Voice playback canceled.","AbortError"));
      const finish=(error,blob) => {
        if(settled)return;settled=true;
        operation.controller.signal.removeEventListener("abort",abort);
        if(operation.socket===socket)operation.socket=null;
        try{socket?.close();}catch{/* Closing a connecting socket may fail. */}
        chunks.length=0;
        if(error)reject(error);else resolve(blob);
      };
      if(operation.controller.signal.aborted){abort();return;}
      operation.controller.signal.addEventListener("abort",abort,{once:true});
      try {
        socket=new WebSocket(`wss://api.openai.com/v1/realtime?model=${encodeURIComponent(session.model)}`,["realtime",`openai-insecure-api-key.${session.client_secret}`]);
        operation.socket=socket;
      } catch {fail("The natural AI voice could not connect. Please try again or choose an installed computer voice.");return;}
      socket.addEventListener("message",event => {
        if(settled)return;
        if(typeof event.data!=="string"||event.data.length>12*1024*1024){fail("The AI voice returned an unsupported audio response.");return;}
        let packet;try{packet=JSON.parse(event.data);}catch{fail("The AI voice returned an unreadable response.");return;}
        try {
          if(packet.type==="session.created"&&!inputSent){
            inputSent=true;
            socket.send(JSON.stringify({type:"conversation.item.create",item:{id:itemId,type:"message",role:"user",content:[{type:"input_text",text:message}]}}));
          } else if(packet.type==="conversation.item.done"&&packet.item?.id===itemId&&packet.item?.role==="user"&&!responseSent){
            responseSent=true;
            socket.send(JSON.stringify({type:"response.create",response:{output_modalities:["audio"],max_output_tokens:2048}}));
          } else if(packet.type==="response.output_audio.delta"){
            if(typeof packet.delta!=="string"||packet.delta.length*3/4+bytes>8*1024*1024){fail("This spoken question exceeds the audio limit. Read it on screen or try a shorter preview.");return;}
            const raw=atob(packet.delta),chunk=new Uint8Array(raw.length);
            for(let i=0;i<raw.length;i++)chunk[i]=raw.charCodeAt(i);
            bytes+=chunk.length;chunks.push(chunk);
          } else if(packet.type==="response.output_audio_transcript.delta"&&typeof packet.delta==="string"){
            transcript+=packet.delta;
          } else if(packet.type==="response.output_audio_transcript.done"&&typeof packet.transcript==="string"){
            transcript=packet.transcript;
          } else if(packet.type==="response.done"){
            if(packet.response?.status!=="completed"){fail("The AI voice did not finish this question. Please try again.");return;}
            if(normalizedSpeech(transcript)!==normalizedSpeech(message)){fail("The AI voice did not read the question exactly, so playback was withheld. Try Preview or Listen again; the original question remains on screen.");return;}
            finish(null,pcmWave(chunks,bytes));
          } else if(packet.type==="error"){
            fail("The voice is unavailable. Please try again or choose another voice.");
          }
        } catch {fail("The AI voice returned an incomplete response. Please try again.");}
      });
      socket.addEventListener("error",()=>fail("The natural AI voice connection failed. Please try again or choose an installed computer voice."));
      socket.addEventListener("close",()=>{if(!settled)fail("The natural AI voice connection closed before the question was ready. Please try again.");});
    });
  }
  async function speakNatural(message, voice, version) {
    const operation={controller:new AbortController(),socket:null,audio:null,url:null,timer:null};
    state.speechOperation=operation;
    $("stop-speaking").hidden=false;$("voice-status").hidden=false;$("voice-status").textContent="Preparing AI voice…";
    let timedOut=false;
    operation.timer=setTimeout(()=>{timedOut=true;operation.controller.abort();},60000);
    try {
      const session=await request("/api/voice-session",{voice:voice.id},{signal:operation.controller.signal,timeout:60000});
      if(version!==state.speechVersion)return;
      if(typeof session.client_secret!=="string"||typeof session.model!=="string")throw new Error("The AI voice session could not be opened. Please try again.");
      const blob=await naturalSpeechAudio(session,message,operation);
      if(version!==state.speechVersion)return;
      clearTimeout(operation.timer);
      operation.url=URL.createObjectURL(blob);
      operation.audio=new Audio(operation.url);
      const ended=()=>{if(version===state.speechVersion)stopSpeaking();};
      operation.audio.addEventListener("ended",ended,{once:true});
      operation.audio.addEventListener("error",()=>{if(version===state.speechVersion){stopSpeaking();notice("The AI voice audio could not play. Try Listen again or choose another voice.",true);}},{once:true});
      $("voice-status").textContent=`Speaking · ${voice.label}`;
      await operation.audio.play();
    } catch(error) {
      if(version!==state.speechVersion)return;
      stopSpeaking();
      if(timedOut)notice("The natural AI voice took too long. Try Preview or Listen again, or choose an installed computer voice.",true);
      else if(error.name!=="AbortError")notice(error.name==="NotAllowedError"?"Your browser paused voice playback. Select Listen or Preview voice to try again.":error.message,true);
    }
  }
  function speak(message, automatic = false) {
    if (!canSpeakChoice()) {
      if (!automatic) notice("Choose an available interviewer voice. The question remains available as text.", true);
      return;
    }
    if (state.recording || state.requestingMic) { if (!automatic) notice("Finish recording your answer before playing a question."); return; }
    stopSpeaking();
    const version = state.speechVersion;
    const natural=selectedNaturalVoice();
    if(natural){void speakNatural(message,natural,version);return;}
    const utterance = new SpeechSynthesisUtterance(message);
    utterance.voice = state.voice;
    utterance.lang = state.voice.lang;
    utterance.rate = .98;
    state.utterance = utterance;
    $("stop-speaking").hidden = false;
    $("stop-speaking").textContent = "Stop voice";
    utterance.onend = () => {
      if (version === state.speechVersion) {state.utterance = null; $("stop-speaking").hidden = true;}
    };
    utterance.onerror = event => {
      if (version !== state.speechVersion || ["canceled","interrupted"].includes(event.error)) return;
      stopSpeaking();
      notice("The installed voice could not play this question. You can read it above and continue by voice or text.", true);
    };
    try {
      window.speechSynthesis.speak(utterance);
    } catch {
      stopSpeaking();
      notice("Voice playback was unavailable. Use Listen beneath the question to try again, or read the question on screen.", true);
    }
  }
  function elapsedMs() {return state.elapsedMs + (state.timerStartedAt === null ? 0 : Date.now() - state.timerStartedAt);}
  function updateTimer() {
    const seconds = Math.floor(elapsedMs()/1000);
    $("elapsed-time").textContent = `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,"0")}`;
    const planned = state.context?.meeting_minutes || Number($("meeting-minutes").value) || 60;
    $("planned-time").textContent = `/ ${planned} min`;
    $("planned-time").title = "Planned duration is advisory. The interview does not stop when time is reached.";
    $("pause-timer").textContent = state.timerStartedAt === null ? "Resume" : "Pause";
    $("pause-timer").setAttribute("aria-label",`${state.timerStartedAt === null ? "Resume" : "Pause"} elapsed interview timer`);
  }
  function snapshot(action = "answer") {
    return {context:clone(state.context),turns:clone(state.turns),session:{elapsed_minutes:Math.round(elapsedMs()/600)/100,planned_minutes:state.context?.meeting_minutes || 60,closure_requested:action === "close"}};
  }
  function applyInterview(result) {
    if (typeof result.question !== "string" || !result.question.trim()) throw new Error("The interviewer returned an incomplete question. Please try again.");
    const question = text(result.question,6000);
    const coverage = normalizeCoverage(result.coverage);
    const summary = text(result.summary,6000);
    const findings = normalizeFindings(result.memo_findings||[],state.turns);
    const focus = text(result.focus,500);
    const parked = strings(result.parking_lot,50);
    state.turns.push({id:nextTurnId(),role:"assistant",text:question});
    state.version++;
    state.coverage = coverage;
    state.summary = summary;
    state.memo_findings = findings;
    state.focus = focus;
    state.parking_lot = parked;
    state.closure = {asked:result.closure?.asked === true,confirmed:result.closure?.confirmed === true};
    state.dirty = true;
    renderTranscript();
    scrollConversation();
    if (result.ready_for_draft) notice("There is enough detail for an initial draft. You can keep exploring or choose Create draft.");
    if ($("speak-questions").checked) speak(result.question, true);
  }
  async function startInterview(event) {
    event.preventDefault();
    if (state.busy || state.recording || state.transcribing || state.requestingMic) return;
    if (state.started) {
      if (!confirm("Start a new interview? Unsaved conversation and draft edits in this tab will be cleared. Save the session first if you want to keep them.")) return;
      const existing = state.context;
      clearState(existing);
      revealContext();
      $("process-name").focus();
      notice("Update the context, then select Start interview.");
      return;
    }
    if (!$("context-form").reportValidity()) return;
    state.context = readContext();
    state.example = false;
    const generation = state.generation;
    setBusy(true, "Preparing the first question…");
    try {
      const result = await request("/api/interview", {...snapshot(), action: "start"});
      if (generation !== state.generation) return;
      applyInterview(result);
      state.started = true;
      state.timerStartedAt = Date.now();
    } catch (error) { if (generation === state.generation) notice(error.message, true); }
    finally {
      if (generation === state.generation) {
        setBusy(false);
        if (state.started) $("answer-text").focus();
      }
    }
  }
  async function sendAnswer(event) {
    event.preventDefault();
    const answer = $("answer-text").value.trim();
    if (!answer || !state.started || state.busy || state.recording || state.transcribing || state.requestingMic) return;
    if (answer.length > 6000 || state.turns.length >= 399 || state.turns.reduce((n,t) => n+t.text.length,answer.length) > 400000) {notice("This answer or interview exceeds the prototype’s technical size limit. Shorten the answer, or create a draft and save this session. The planned meeting duration never ends the interview.", true); return;}
    stopSpeaking();
    const generation = state.generation;
    const turn = {id: nextTurnId(), role: "user", text: answer};
    state.turns.push(turn);
    state.version++;
    state.dirty = true;
    $("answer-text").value = "";
    renderTranscript();
    setBusy(true);
    scrollConversation();
    try {
      const result = await request("/api/interview", {...snapshot(), action: "answer"});
      if (generation === state.generation) applyInterview(result);
    } catch (error) {
      if (generation !== state.generation) return;
      state.turns = state.turns.filter(t => t !== turn);
      state.version++;
      $("answer-text").value = answer;
      renderTranscript();
      notice(`${error.message} Your answer has been restored below.`, true);
    } finally {
      if (generation === state.generation) { setBusy(false); $("answer-text").focus(); }
    }
  }
  async function skipQuestion() {
    if (!state.started || state.busy || state.recording || state.transcribing || state.requestingMic) return;
    if ($("answer-text").value.trim() && !confirm("Skip this question? Your unsent answer will stay in the answer box.")) return;
    stopSpeaking();
    const generation = state.generation;
    setBusy(true, "Finding another topic to explore…");
    try {
      const result = await request("/api/interview", {...snapshot("skip"), action: "skip"});
      if (generation === state.generation) applyInterview(result);
    } catch (error) { if (generation === state.generation) notice(error.message, true); }
    finally { if (generation === state.generation) setBusy(false); }
  }
  async function finalCheck() {
    if (!state.started || state.busy || state.recording || state.transcribing || state.requestingMic) return;
    if ($("answer-text").value.trim()) {notice("Send the answer currently in the box before requesting the final completeness check."); return;}
    stopSpeaking();
    const generation = state.generation;
    setBusy(true,"Checking for omissions, contradictions, and unresolved questions…");
    try {
      const result = await request("/api/interview",{...snapshot("close"),action:"close"});
      if (generation === state.generation) applyInterview(result);
    } catch(error) {if (generation === state.generation) notice(error.message,true);}
    finally {if (generation === state.generation) setBusy(false);}
  }

  async function startRecording() {
    if (state.recording) { finishRecording(); return; }
    if (state.busy || state.transcribing || state.requestingMic || !state.started) return;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      notice("This browser does not support microphone recording. Use a current Chrome or Edge browser, or type your answer.", true);
      return;
    }
    stopSpeaking();
    const generation = state.generation;
    state.requestingMic = true;
    updateControls();
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}});
      if (generation !== state.generation || state.busy || state.transcribing || !state.started) { stream.getTracks().forEach(t => t.stop()); return; }
      const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find(type => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? {mimeType} : undefined);
      const recording = {recorder, stream, chunks: [], startedAt: performance.now(), lastSound: performance.now(), hasSpeech: false, discard: false, timer: null, frame: null, context: null, generation};
      state.recording = recording;
      state.requestingMic = false;
      recorder.addEventListener("dataavailable", event => { if (event.data.size) recording.chunks.push(event.data); });
      recorder.addEventListener("error", () => { recording.discard = true; notice("The microphone recording failed. Please try again or type your answer.", true); finishRecording(); });
      recorder.addEventListener("stop", () => completeRecording(recording));
      recorder.start(250);
      recording.timer = setInterval(() => {
        const seconds = Math.floor((performance.now() - recording.startedAt) / 1000);
        $("recording-time").textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
        if (seconds >= 90) { notice("The 90-second answer limit was reached. Review this part, then add more in another answer."); finishRecording(); }
      }, 200);
      $("recording-time").textContent = "0:00";
      $("recording-label").textContent = "Listening · finish when you’re ready";
      monitorSilence(recording);
      updateControls();
      $("live-status").textContent = "Recording your answer. Select Finish to stop.";
    } catch (error) {
      stream?.getTracks().forEach(t => t.stop());
      state.recording = null;
      const messages = {
        NotAllowedError: "Microphone access was not granted. Allow it in your browser’s site settings, or type your answer.",
        NotFoundError: "No microphone was found. Connect one or type your answer.",
        NotReadableError: "The microphone could not be opened. Check whether another application is using it, or type your answer."
      };
      notice(messages[error.name] || `Recording could not start: ${error.message}`, true);
      updateControls();
    } finally {
      if (generation === state.generation) {state.requestingMic = false; updateControls();}
    }
  }
  function monitorSilence(recording) {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    try {
      const context = new AudioContext();
      recording.context = context;
      context.resume().catch(() => {});
      const source = context.createMediaStreamSource(recording.stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);
      const data = new Uint8Array(analyser.fftSize);
      const measure = () => {
        if (state.recording !== recording || recording.recorder.state !== "recording") return;
        analyser.getByteTimeDomainData(data);
        let squared = 0;
        for (const value of data) squared += ((value - 128) / 128) ** 2;
        const rms = Math.sqrt(squared / data.length);
        const now = performance.now();
        if (rms > .018) { recording.hasSpeech = true; recording.lastSound = now; }
        const elapsed = now - recording.startedAt;
        if ($("stop-on-silence").checked && recording.hasSpeech && elapsed > 1800 && now - recording.lastSound > 2200) {
          $("recording-label").textContent = "Pause detected · finishing answer";
          finishRecording();
          return;
        }
        recording.frame = requestAnimationFrame(measure);
      };
      recording.frame = requestAnimationFrame(measure);
    } catch { /* Recording still works when a browser cannot provide the level monitor. */ }
  }
  function finishRecording(discard = false) {
    const recording = state.recording;
    if (!recording) return;
    recording.discard ||= discard;
    clearInterval(recording.timer);
    cancelAnimationFrame(recording.frame);
    recording.context?.close().catch(() => {});
    if (recording.recorder.state !== "inactive") recording.recorder.stop();
    recording.stream.getTracks().forEach(track => track.stop());
  }
  async function completeRecording(recording) {
    if (state.recording === recording) state.recording = null;
    clearInterval(recording.timer);
    cancelAnimationFrame(recording.frame);
    recording.stream.getTracks().forEach(track => track.stop());
    const elapsed = performance.now() - recording.startedAt;
    if (recording.discard || recording.generation !== state.generation) { updateControls(); return; }
    if (elapsed < 550 || !recording.chunks.length) { notice("That recording was too short. Try again, or type your answer.", true); updateControls(); return; }
    const blob = new Blob(recording.chunks, {type: recording.recorder.mimeType || "audio/webm"});
    recording.chunks = [];
    state.transcribing = true;
    updateControls();
    try {
      const result = await request("/api/transcribe", blob);
      if (recording.generation !== state.generation) return;
      const answer = text(result.text).trim();
      if (!answer) throw new Error("No speech was recognized. Try again or type your answer.");
      const existing = $("answer-text").value.trim();
      const combined = existing ? `${existing}\n\n${answer}` : answer;
      $("answer-text").value = combined;
      state.dirty = true;
      if (combined.length > 6000) {
        notice("Your recording is transcribed, but the combined answer exceeds 6,000 characters. It is preserved below; shorten it before sending.",true);
        return;
      }
      notice("Review the transcript, then select Send.");
    } catch (error) { if (recording.generation === state.generation) notice(`Transcription failed: ${error.message}`, true); }
    finally {
      if (recording.generation === state.generation) { state.transcribing = false; updateControls(); $("answer-text").focus(); }
    }
  }

  function normalizeCoverage(value) {
    if (!Array.isArray(value)) return [];
    return TOPICS.map(([key, label]) => {
      const item = value.find(v => v && v.key === key);
      return {key, label, status: ["partial", "covered"].includes(item?.status) ? item.status : "missing"};
    });
  }
  function evidenceSources(value, sourceTurns) {
    if(!Array.isArray(value))throw new Error("Source turn references must be a list of participant answer IDs or context.");
    const valid = new Set(sourceTurns.filter(t => t.role === "user").map(t => t.id));
    valid.add("context");
    const ids = strings(value,400).map(id => text(id,40));
    if (ids.some(id => !valid.has(id))) throw new Error("A draft finding cites a source that is not a participant answer or context.");
    return ids;
  }
  function normalizeFindings(value, sourceTurns) {
    if (!Array.isArray(value)) throw new Error("The memo foundation must be a list.");
    if (value.length > 11) throw new Error("The memo foundation contains more than eleven topics.");
    const seen = new Set();
    value.forEach(item => {
      if (!item || !TOPICS.some(([key]) => key === item.key) || seen.has(item.key)) throw new Error("The memo foundation has an unknown or duplicate topic.");
      seen.add(item.key);
    });
    return TOPICS.map(([key]) => {
      const item = value.find(f => f.key === key);
      return {key,status:["partial","captured","not_applicable"].includes(item?.status)?item.status:"unknown",answer:text(item?.answer,12000)||"UNKNOWN / TBD — not established in the interview.",evidence_turns:evidenceSources(item?.evidence_turns||[],sourceTurns)};
    });
  }
  function normalizeDraft(value, sourceTurns = state.turns) {
    if (!value || typeof value !== "object" || !Array.isArray(value.steps)) throw new Error("The draft format was incomplete. Please generate it again.");
    if (value.steps.length > 80) throw new Error("The draft has more than 80 steps.");
    const ids = new Set();
    const steps = value.steps.map((step, i) => {
      const id = text(step?.id, 40);
      if (!/^[a-zA-Z0-9_-]{1,40}$/.test(id) || ids.has(id)) throw new Error(`The draft contains an invalid or duplicate step ID at position ${i+1}.`);
      ids.add(id);
      const evidence = evidenceSources(step?.evidence_turns||[],sourceTurns);
      return {id,title:text(step?.title,500),type:step?.type === "decision"?"decision":"activity",actor:text(step?.actor,500),system:text(step?.system,500),description:text(step?.description,12000),input:text(step?.input,6000)||"UNKNOWN / TBD",output:text(step?.output,6000)||"UNKNOWN / TBD",completion_criteria:text(step?.completion_criteria,6000)||"UNKNOWN / TBD",handoff:text(step?.handoff,6000)||"UNKNOWN / TBD",evidence_turns:evidence};
    });
    const connections = Array.isArray(value.connections) ? value.connections : [];
    if (connections.length > 150 || connections.some(c => !c || !ids.has(c.from) || !ids.has(c.to))) throw new Error("The draft has a connection pointing to a missing step, or more than 150 connections.");
    const rawVariations = Array.isArray(value.variations)?value.variations:[];
    const rawLifecycle = Array.isArray(value.lifecycle_items)?value.lifecycle_items:[];
    if (rawVariations.length>100 || rawLifecycle.length>100) throw new Error("The draft contains too many variation or lifecycle items.");
    const variations = rawVariations.map(item => ({applies_to:text(item?.applies_to,6000)||"UNKNOWN / TBD",difference:text(item?.difference,6000)||"UNKNOWN / TBD",reason:text(item?.reason,6000)||"UNKNOWN / TBD",cost:text(item?.cost,6000)||"UNKNOWN / TBD",charging:text(item?.charging,6000)||"UNKNOWN / TBD",removability:text(item?.removability,6000)||"UNKNOWN / TBD",boundary:item?.boundary === "possibly_separate_work"?"possibly_separate_work":"variation",boundary_reason:text(item?.boundary_reason,6000)||"UNKNOWN / TBD",evidence_turns:evidenceSources(item?.evidence_turns||[],sourceTurns)}));
    const lifecycle_items = rawLifecycle.map(item => ({item:text(item?.item,6000)||"UNKNOWN / TBD",stages:strings(item?.stages),locations:strings(item?.locations),handoffs:strings(item?.handoffs),evidence_turns:evidenceSources(item?.evidence_turns||[],sourceTurns)}));
    return {
      title: text(value.title, 300), overview: text(value.overview, 12000), trigger: text(value.trigger, 6000),
      inputs: strings(value.inputs), outputs: strings(value.outputs), steps,
      connections:connections.map(c => ({from:c.from,to:c.to,label:text(c.label,300),evidence_turns:evidenceSources(c.evidence_turns||[],sourceTurns)})),
      exceptions: strings(value.exceptions), controls: strings(value.controls),
      open_questions: strings(value.open_questions), validation_notes: strings(value.validation_notes),
      memo_summary:normalizeFindings(value.memo_summary||[],sourceTurns),variations,lifecycle_items
    };
  }
  async function generateDraft() {
    if (state.busy || state.recording || state.transcribing || state.requestingMic || !state.turns.some(t => t.role === "user")) return;
    if (state.draft && !confirm("Replace the current draft with a new version from the interview? Any edits to the current draft will be replaced. Save a session or export first if you want to keep them.")) return;
    if ($("answer-text").value.trim() && !confirm("There is an unsent answer. Generate a draft using only the answers already sent? The unsent text will stay in the answer box.")) return;
    stopSpeaking();
    const generation = state.generation;
    const version = state.version;
    setBusy(true, "Building a process map and procedure from the conversation…");
    scrollConversation();
    try {
      const result = await request("/api/draft", snapshot(), {timeout: 180000});
      if (generation !== state.generation || version !== state.version) return;
      state.draft = normalizeDraft(result.draft);
      state.draftVersion = version;
      state.draftEdited = false;
      state.dirty = true;
      renderDraft();
      tab("review", true);
      notice("Draft ready. Review the sources, steps and open questions.");
    } catch (error) { if (generation === state.generation) notice(error.message, true); }
    finally { if (generation === state.generation) setBusy(false); }
  }
  function draftChanged(map = false) {
    state.draftEdited = true;
    state.dirty = true;
    updateSaveHint();
    if (map) renderMap();
  }
  function bindDraftFields() {
    const fields = {"draft-title": "title", "draft-overview": "overview", "draft-trigger": "trigger", "draft-inputs": "inputs", "draft-outputs": "outputs", "draft-open-questions": "open_questions", "draft-validation-notes": "validation_notes", "draft-exceptions": "exceptions", "draft-controls": "controls"};
    Object.entries(fields).forEach(([id, key]) => {
      $(id).addEventListener("input", () => {
        if (!state.draft) return;
        state.draft[key] = Array.isArray(state.draft[key]) ? lines($(id).value) : $(id).value;
        draftChanged();
      });
    });
  }
  function renderDraft() {
    updateControls();
    if (!state.draft) return;
    const draft = state.draft;
    const fields = {"draft-title": "title", "draft-overview": "overview", "draft-trigger": "trigger", "draft-inputs": "inputs", "draft-outputs": "outputs", "draft-open-questions": "open_questions", "draft-validation-notes": "validation_notes", "draft-exceptions": "exceptions", "draft-controls": "controls"};
    Object.entries(fields).forEach(([id, key]) => { $(id).value = Array.isArray(draft[key]) ? draft[key].join("\n") : draft[key]; });
    renderSteps();
    renderConnections();
    renderMap();
    renderMemo();
    renderLifecycle();
    renderVariations();
    selectReviewSection(reviewUI.section);
  }
  function formControl(label, tag, value, change, options = {}) {
    const wrap = el("div");
    const name = el("label", "", label);
    const control = el(tag);
    control.setAttribute("aria-label", options.aria || label);
    if (tag === "select") {
      (options.choices || []).forEach(([val, caption]) => {
        const option = el("option", "", caption); option.value = val; control.append(option);
      });
    } else control.maxLength = options.max || 500;
    if (tag === "textarea") control.rows = options.rows || 2;
    control.value = value;
    control.addEventListener(tag === "select" ? "change" : "input", () => change(control.value));
    name.append(control);
    wrap.append(name);
    return wrap;
  }
  function jumpToTurn(id) {
    tab("interview");
    if (id === "context") {
      revealContext();
      const context = $("context-form");
      context.scrollIntoView({behavior:"smooth",block:"center"});
      context.tabIndex = -1;
      context.focus({preventScroll:true});
      notice("This step cites the interview context. Validate it with the process owner.");
      return;
    }
    const turn = document.getElementById(`turn-${id}`);
    if (!turn) { notice(`Source ${id} is not present in this session. Validate this step with the process owner.`, true); return; }
    revealAncestors(turn);
    turn.scrollIntoView({behavior: "smooth", block: "center"});
    turn.classList.remove("highlight");
    void turn.offsetWidth;
    turn.classList.add("highlight");
    turn.tabIndex = -1;
    turn.focus({preventScroll: true});
  }
  function jumpToReview(id) {
    const target = $(id);
    if (!target || !selectReviewSection(id)) return;
    revealAncestors(target);
    target.scrollIntoView({behavior:"smooth",block:"start"});
    target.tabIndex = -1;
    target.focus({preventScroll:true});
  }
  function selectReviewSection(id, focusTab = false) {
    if (!REVIEW_SECTIONS.includes(id)) return false;
    reviewUI.section = id;
    REVIEW_SECTIONS.forEach(section => {
      const active = section === id;
      const button = $(`review-tab-${section.slice(7)}`);
      $(section).hidden = !active;
      button.setAttribute("aria-selected",String(active));
      button.tabIndex = active ? 0 : -1;
      button.classList.toggle("active",active);
    });
    if (focusTab) {
      const button = $(`review-tab-${id.slice(7)}`);
      button.focus({preventScroll:true});
      button.scrollIntoView({block:"nearest",inline:"nearest"});
    }
    if (id === "review-map" && reviewUI.mapFit) requestAnimationFrame(fitMapToWidth);
    return true;
  }
  function reviewTabKey(event) {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const index = REVIEW_SECTIONS.indexOf(event.currentTarget.dataset.reviewTarget);
    const next = event.key === "ArrowRight" ? (index+1)%REVIEW_SECTIONS.length : event.key === "ArrowLeft" ? (index+REVIEW_SECTIONS.length-1)%REVIEW_SECTIONS.length : event.key === "Home" ? 0 : event.key === "End" ? REVIEW_SECTIONS.length-1 : -1;
    if (index < 0 || next < 0) return;
    event.preventDefault();
    selectReviewSection(REVIEW_SECTIONS[next],true);
  }
  function initReviewTabs() {
    document.querySelectorAll("[data-review-target]").forEach(button => {
      button.addEventListener("click",() => selectReviewSection(button.dataset.reviewTarget,true));
      button.addEventListener("keydown",reviewTabKey);
    });
    selectReviewSection(reviewUI.section);
  }
  function sourceCaption(id) {
    if (id === "context") return "Starting context";
    const turn = state.turns.find(item => item.id === id);
    if (!turn) return "Missing answer";
    const position = state.turns.filter(item => item.role === turn.role).findIndex(item => item.id === id) + 1;
    return `${turn.role === "user" ? "Answer" : "Question"} ${position}`;
  }
  function renderSteps() {
    const root = $("procedure-steps");
    root.replaceChildren();
    state.draft.steps.forEach((step, index) => {
      const article = el("section", "procedure-step");
      article.setAttribute("aria-label", `Step ${step.id}`);
      const header = el("div", "step-header");
      const title = el("input");
      title.value = step.title;
      title.maxLength = 500;
      title.setAttribute("aria-label", `Title for step ${step.id}`);
      title.addEventListener("input", () => { step.title = title.value; draftChanged(true); });
      const remove = el("button", "remove-button", "Remove");
      remove.setAttribute("aria-label", `Remove step ${step.id}`);
      remove.addEventListener("click", () => {
        if (!confirm(`Remove step ${step.id} and its map connections?`)) return;
        state.draft.steps.splice(index, 1);
        state.draft.connections = state.draft.connections.filter(c => c.from !== step.id && c.to !== step.id);
        draftChanged(); renderSteps(); renderConnections(); renderMap();
      });
      header.append(el("span", "step-id", step.id), title, remove);
      const props = el("div", "step-properties");
      props.append(
        formControl("Owner / role", "input", step.actor, v => {step.actor = v; draftChanged(true);}, {aria: `Owner of step ${step.id}`}),
        formControl("System / tool", "input", step.system, v => {step.system = v; draftChanged(true);}, {aria: `System for step ${step.id}`}),
        formControl("Step type", "select", step.type, v => {step.type = v; draftChanged(true);}, {aria: `Type of step ${step.id}`, choices: [["activity", "Activity"], ["decision", "Decision"]]})
      );
      const description = el("textarea", "step-description");
      description.value = step.description;
      description.rows = 3;
      description.maxLength = 12000;
      description.setAttribute("aria-label", `Instructions for step ${step.id}`);
      description.addEventListener("input", () => { step.description = description.value; draftChanged(); });
      const evidence = el("div", "evidence-row");
      evidence.append(el("span", "", "Sources:"));
      if (!step.evidence_turns.length) evidence.append(el("span", "needs-evidence", "Needs validation · no cited answer"));
      step.evidence_turns.forEach(id => {
        const source = el("button", "evidence-link", sourceCaption(id));
        source.title = `Source: ${id}`;
        source.setAttribute("aria-label", `Read ${sourceCaption(id)} for step ${step.id}`);
        source.addEventListener("click", () => jumpToTurn(id));
        evidence.append(source);
      });
      const extra = el("details","step-extra");
      extra.append(el("summary","","Inputs, outputs, completion & handoff"));
      const extras = el("div","detail-two-columns");
      [["input","Input"],["output","Output"],["completion_criteria","Completion criteria"],["handoff","Next handoff"]].forEach(([key,label]) => extras.append(formControl(label,"textarea",step[key],v => {step[key]=v;draftChanged();},{max:6000,aria:`${label} for step ${step.id}`})));
      extra.append(extras);
      article.append(header,props,description,extra,evidence);
      root.append(article);
    });
    if (!state.draft.steps.length) root.append(el("p", "muted", "No process steps yet. Continue the interview or add a step for owner review."));
  }
  function renderConnections() {
    const root = $("connection-rows");
    root.replaceChildren();
    const choices = state.draft.steps.map(s => [s.id, `${s.id} · ${s.title.slice(0, 38)}`]);
    state.draft.connections.forEach((connection, index) => {
      const row = el("div", "connection-row");
      row.append(
        formControl("From", "select", connection.from, v => {connection.from = v; draftChanged(true);}, {choices, aria: `Connection ${index + 1} from step`}),
        formControl("To", "select", connection.to, v => {connection.to = v; draftChanged(true);}, {choices, aria: `Connection ${index + 1} to step`}),
        formControl("Label", "input", connection.label, v => {connection.label = v; draftChanged(true);}, {max:300, aria: `Connection ${index + 1} label`})
      );
      const remove = el("button", "remove-button", "×");
      remove.setAttribute("aria-label", `Remove connection ${index + 1}`);
      remove.addEventListener("click", () => {state.draft.connections.splice(index, 1); draftChanged(); renderConnections(); renderMap();});
      row.append(remove);
      const evidence=evidenceRow(connection.evidence_turns||[]);
      evidence.classList.add("connection-evidence");
      row.append(evidence);
      root.append(row);
    });
    if (!state.draft.connections.length) root.append(el("p", "muted", "No connections have been defined. Add connections between the steps to show the flow."));
  }
  function evidenceRow(ids, beforeJump = null) {
    const evidence = el("div","evidence-row");
    evidence.append(el("span","","Sources:"));
    if (!ids.length) evidence.append(el("span","needs-evidence","UNKNOWN / TBD · needs validation"));
    ids.forEach(id => {
      const source = el("button","evidence-link",sourceCaption(id));
      source.title = `Source: ${id}`;
      source.setAttribute("aria-label",`Read ${sourceCaption(id)}`);
      source.addEventListener("click",() => {beforeJump?.();jumpToTurn(id);});
      evidence.append(source);
    });
    return evidence;
  }
  function renderMemo() {
    const root = $("memo-summary");
    root.replaceChildren();
    state.draft.memo_summary.forEach((finding,index) => {
      const item = el("details","memo-finding");
      const summary = el("summary","memo-finding-summary");
      const topic = `${String(index+1).padStart(2,"0")} · ${MEMO_HEADINGS[finding.key]||finding.key}`;
      const statusLabels = {unknown:"Unknown / TBD",partial:"Partial",captured:"Captured",not_applicable:"Not applicable"};
      const badge = el("span",`memo-status ${finding.status}`,statusLabels[finding.status]||statusLabels.unknown);
      summary.append(el("span","memo-topic",topic),badge);
      const body = el("div","memo-finding-body");
      const header = el("div","memo-finding-header");
      const title = el("label","",topic);
      title.htmlFor = `memo-answer-${finding.key}`;
      const status = el("select");
      status.setAttribute("aria-label",`Review status for ${finding.key.replaceAll("_"," ")}`);
      [["unknown","Unknown / TBD"],["partial","Partial"],["captured","Captured"],["not_applicable","Not applicable"]].forEach(([value,label]) => {const option=el("option","",label);option.value=value;status.append(option);});
      status.value = finding.status;
      status.addEventListener("change",() => {finding.status=status.value;badge.textContent=statusLabels[finding.status]||statusLabels.unknown;badge.className=`memo-status ${finding.status}`;draftChanged();});
      const answer = el("textarea");
      answer.id = `memo-answer-${finding.key}`;
      answer.value = finding.answer;
      answer.rows = 3;
      answer.maxLength = 12000;
      answer.addEventListener("input",()=>{finding.answer=answer.value;draftChanged();});
      header.append(title,status);
      body.append(header,answer,evidenceRow(finding.evidence_turns));
      item.append(summary,body);
      root.append(item);
    });
  }
  function renderLifecycle() {
    const root = $("lifecycle-items");
    root.replaceChildren();
    state.draft.lifecycle_items.forEach((item,index) => {
      const card = el("section","detail-item");
      const head = el("div","detail-item-head");
      const remove = el("button","remove-button","Remove");
      remove.setAttribute("aria-label",`Remove lifecycle item ${index+1}`);
      remove.addEventListener("click",()=>{if(confirm("Remove this lifecycle item?")){state.draft.lifecycle_items.splice(index,1);draftChanged();renderLifecycle();}});
      head.append(el("h3","",`Item ${index+1}`),remove);
      card.append(head,formControl("Work item / document","textarea",item.item,v=>{item.item=v;draftChanged();},{max:6000,aria:`Name of lifecycle item ${index+1}`}));
      const fields = el("div","detail-two-columns");
      [["stages","Stages, in order"],["locations","Locations / systems"],["handoffs","Handoffs"]].forEach(([key,label]) => fields.append(formControl(`${label} · one per line`,"textarea",item[key].join("\n"),v=>{item[key]=lines(v);draftChanged();},{max:18000,rows:3,aria:`${label} for lifecycle item ${index+1}`})));
      card.append(fields,evidenceRow(item.evidence_turns));
      root.append(card);
    });
    if (!state.draft.lifecycle_items.length) root.append(el("p","map-help","UNKNOWN / TBD — no item lifecycle was established. Continue the interview or add an item for review."));
  }
  function renderVariations() {
    const root = $("variation-items");
    root.replaceChildren();
    state.draft.variations.forEach((item,index) => {
      const card = el("section","detail-item");
      const head = el("div","detail-item-head");
      const remove = el("button","remove-button","Remove");
      remove.setAttribute("aria-label",`Remove variation ${index+1}`);
      remove.addEventListener("click",()=>{if(confirm("Remove this variation?")){state.draft.variations.splice(index,1);draftChanged();renderVariations();}});
      head.append(el("h3","",`Variation ${index+1}`),remove);
      card.append(head);
      const fields = el("div","detail-two-columns");
      [["applies_to","Who / what it applies to"],["difference","What differs"],["reason","Why it exists"],["cost","What it costs us · attributed estimate"],["charging","Do we charge for it?"],["removability","Could it go away? · participant’s view"]].forEach(([key,label]) => fields.append(formControl(label,"textarea",item[key],v=>{item[key]=v;draftChanged();},{max:6000,rows:3,aria:`${label} for variation ${index+1}`})));
      fields.append(formControl("Process boundary","select",item.boundary,v=>{item.boundary=v;draftChanged();},{choices:[["variation","Variation of this process"],["possibly_separate_work","Possibly separate work"]],aria:`Boundary for variation ${index+1}`}));
      fields.append(formControl("Reason for boundary assessment","textarea",item.boundary_reason,v=>{item.boundary_reason=v;draftChanged();},{max:6000,rows:3,aria:`Boundary reason for variation ${index+1}`}));
      card.append(fields,evidenceRow(item.evidence_turns));
      root.append(card);
    });
    if (!state.draft.variations.length) root.append(el("p","map-help","UNKNOWN / TBD — no variations were established. An empty list does not confirm that there are none."));
  }
  function wrapWords(value, maxChars = 31, maxLines = 3) {
    const words = String(value || "Untitled step").split(/\s+/);
    const result = [];
    let line = "";
    for (const word of words) {
      if ((line + " " + word).trim().length > maxChars && line) { result.push(line); line = word; }
      else line = (line + " " + word).trim();
    }
    if (line) result.push(line);
    if (result.length > maxLines) return result.slice(0, maxLines - 1).concat(result[maxLines - 1].slice(0, maxChars - 1) + "…");
    return result;
  }
  function renderMap() {
    const root = $("process-map");
    root.replaceChildren();
    if (!state.draft?.steps.length) { root.append(el("p", "muted", "Add process steps to build the map.")); applyMapView(); return; }
    const steps = state.draft.steps;
    const connections = state.draft.connections;
    const positions = new Map();
    const height = steps.length * 157 + 56;
    const width = 760;
    const svg = svgEl("svg", {xmlns:svgNS, viewBox:`0 0 ${width} ${height}`, width, height, role:"img", "aria-labelledby":"map-title map-description"});
    svg.append(svgEl("title", {id:"map-title"}, `Draft process map: ${state.draft.title || "Untitled process"}`));
    svg.append(svgEl("desc", {id:"map-description"}, steps.map(s => `${s.id}: ${s.title}, owner ${s.actor || "not specified"}`).join(". ")));
    svg.append(svgEl("rect", {width, height, fill:"#ffffff", "aria-hidden":"true"}));
    const defs = svgEl("defs");
    const marker = svgEl("marker", {id:"flow-arrow",viewBox:"0 0 10 10",refX:8,refY:5,markerWidth:7,markerHeight:7,orient:"auto-start-reverse"});
    marker.append(svgEl("path", {d:"M 0 0 L 10 5 L 0 10 z", fill:"#8a8a90"}));
    defs.append(marker); svg.append(defs);
    steps.forEach((step,index) => positions.set(step.id, {x:380,y:34 + index * 157,w:320,h:102,index}));
    const edges = svgEl("g", {fill:"none",stroke:"#8a8a90","stroke-width":1.6});
    const edgeLabels = svgEl("g");
    connections.forEach((connection,index) => {
      const from = positions.get(connection.from), to = positions.get(connection.to);
      if (!from || !to) return;
      const isNext = to.index === from.index + 1;
      let path, lx, ly;
      if (isNext) {
        path = `M ${from.x} ${from.y + from.h} L ${to.x} ${to.y - 4}`;
        lx = from.x + 12; ly = from.y + from.h + 25;
      } else {
        const right = to.index > from.index;
        const edgeX = right ? 605 + (index % 3) * 17 : 155 - (index % 3) * 17;
        const sourceX = right ? from.x + from.w / 2 : from.x - from.w / 2;
        const targetX = right ? to.x + to.w / 2 + 4 : to.x - to.w / 2 - 4;
        const sourceY = from.y + from.h / 2;
        const targetY = to.y + to.h / 2 + (from.index === to.index ? 20 : 0);
        path = `M ${sourceX} ${sourceY} H ${edgeX} V ${targetY} H ${targetX}`;
        lx = edgeX + (right ? 7 : -7); ly = (sourceY + targetY) / 2;
      }
      const edge=svgEl("path",{d:path,"marker-end":"url(#flow-arrow)"});
      edge.append(svgEl("title",{},`${connection.from} → ${connection.to}${connection.label?": "+connection.label:""}. Source turns: ${(connection.evidence_turns||[]).join(", ")||"UNKNOWN / TBD — no cited answer"}`));
      edges.append(edge);
      if (connection.label) {
        const label = svgEl("text", {x:lx,y:ly,fill:"#707077","font-family":"Segoe UI, Arial, sans-serif","font-size":10,"text-anchor":isNext || to.index > from.index ? "start" : "end"});
        wrapWords(connection.label, 16, 3).forEach((line, i) => label.append(svgEl("tspan", {x:lx,dy:i ? 13 : 0}, line)));
        edgeLabels.append(label);
      }
    });
    svg.append(edges, edgeLabels);
    steps.forEach(step => {
      const p = positions.get(step.id);
      const group = svgEl("g");
      const isDecision = step.type === "decision";
      if (isDecision) {
        group.append(svgEl("path", {d:`M ${p.x - p.w / 2 + 22} ${p.y} H ${p.x + p.w / 2 - 22} L ${p.x + p.w / 2} ${p.y + p.h / 2} L ${p.x + p.w / 2 - 22} ${p.y + p.h} H ${p.x - p.w / 2 + 22} L ${p.x - p.w / 2} ${p.y + p.h / 2} Z`,fill:"#f0f0f1",stroke:"#9a9a9e","stroke-width":1.2}));
      } else group.append(svgEl("rect", {x:p.x-p.w/2,y:p.y,width:p.w,height:p.h,rx:10,fill:"#ffffff",stroke:"#b8b8bb","stroke-width":1.2}));
      group.append(svgEl("title", {}, `${step.id}: ${step.title}. ${step.description}`));
      group.append(svgEl("text", {x:p.x,y:p.y+19,fill:"#707077","text-anchor":"middle","font-size":9,"font-family":"Segoe UI, Arial, sans-serif","font-weight":600,"letter-spacing":1}, `${step.id} · ${isDecision ? "DECISION" : "ACTIVITY"}`));
      const title = svgEl("text", {x:p.x,y:p.y+41,fill:"#202023","text-anchor":"middle","font-size":13,"font-family":"Segoe UI, Arial, sans-serif","font-weight":600});
      wrapWords(step.title, 35, 2).forEach((line,i) => title.append(svgEl("tspan", {x:p.x,dy:i ? 17 : 0}, line)));
      group.append(title);
      const owner = `${step.actor || "Owner not specified"}${step.system ? " · " + step.system : ""}`;
      group.append(svgEl("text", {x:p.x,y:p.y+83,fill:"#707077","text-anchor":"middle","font-size":10,"font-family":"Segoe UI, Arial, sans-serif"}, owner.length > 48 ? owner.slice(0,47)+"…" : owner));
      svg.append(group);
    });
    const stage = el("div","map-stage");
    stage.dataset.intrinsicWidth = String(width);
    stage.append(svg); root.append(stage);
    applyMapView();
    if (reviewUI.mapFit) requestAnimationFrame(fitMapToWidth);
  }
  function applyMapView() {
    const stage = $("process-map").querySelector(".map-stage");
    if (stage) stage.style.width = `${Number(stage.dataset.intrinsicWidth)*reviewUI.mapScale}px`;
    const out = $("map-zoom-out"), inside = $("map-zoom-in"), fit = $("map-fit"), label = $("map-zoom-label");
    if (out) out.disabled = !stage || reviewUI.mapScale <= .25;
    if (inside) inside.disabled = !stage || reviewUI.mapScale >= 2;
    if (fit) fit.disabled = !stage;
    const zoomText = stage ? `${Math.round(reviewUI.mapScale*100)}%` : "";
    if (label && label.textContent !== zoomText) label.textContent = zoomText;
  }
  function zoomMap(delta) {
    reviewUI.mapFit = false;
    reviewUI.mapScale = Math.max(.25,Math.min(2,Math.round((reviewUI.mapScale+delta)*100)/100));
    applyMapView();
  }
  function fitMapToWidth() {
    const viewport = $("process-map"), stage = viewport.querySelector(".map-stage");
    if (!stage || reviewUI.section !== "review-map" || $("review-view").hidden || viewport.clientWidth <= 0) return;
    const styles = getComputedStyle(viewport);
    const available = viewport.clientWidth - (parseFloat(styles.paddingLeft)||0) - (parseFloat(styles.paddingRight)||0);
    reviewUI.mapFit = true;
    reviewUI.mapScale = Math.max(.25,Math.min(2,available/Number(stage.dataset.intrinsicWidth)));
    applyMapView();
  }

  function download(content, filename, type) {
    const url = URL.createObjectURL(new Blob([content], {type}));
    const link = el("a"); link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
  function sessionObject() {
    return {schema_version:1,saved_at:new Date().toISOString(),context:state.context||readContext(),turns:state.turns,coverage:state.coverage,summary:state.summary,memo_findings:state.memo_findings,focus:state.focus,parking_lot:state.parking_lot,closure:state.closure,elapsed_seconds:Math.floor(elapsedMs()/1000),draft:state.draft,draft_stale:Boolean(state.draft&&state.draftVersion!==state.version),draft_edited:state.draftEdited,synthetic_example:state.example,unsent_answer:$("answer-text").value,voice_choice:state.voiceChoice};
  }
  function exportSession() {
    download(JSON.stringify(sessionObject(),null,2), `${safeFilename(state.context?.process_name || readContext().process_name)}-session.json`, "application/json");
    state.dirty = false;
    updateSaveHint();
    notice("Interview saved. Keep the file somewhere approved for this process information.");
    closeMenu();
  }
  function escapeMarkdown(value) { return String(value ?? "").replace(/([\\`*_{}\[\]<>#|])/g, "\\$1"); }
  function markdown() {
    const d = state.draft;
    const md = escapeMarkdown;
    const list = values => values.length ? values.map(v => `- ${md(v)}`).join("\n") : "- Not established in this interview.";
    const sources = ids => ids.length ? ids.map(md).join(", ") : "No cited answer — UNKNOWN / TBD";
    const parts = [`# ${md(d.title || state.context?.process_name || "Process procedure")}`, "**DRAFT — process owner review required**", state.example ? "**Synthetic example — fictional process data.**" : "", state.draftVersion !== state.version ? "**The interview has changed since this draft was created. Reconcile the new answers before approval.**" : "",`Planned interview: ${state.context?.meeting_minutes||60} minutes (advisory). Elapsed active time: ${Math.floor(elapsedMs()/60000)} minutes. The planned time does not stop the interview.`,`Final completeness check: ${state.closure.confirmed?"participant confirmed":state.closure.asked?"asked; participant confirmation pending":"not yet requested"}.`,"## Overview",md(d.overview),"## Process owner",md(state.context?.process_owner||"UNKNOWN / TBD"),"## Memo foundation"];
    d.memo_summary.forEach(finding => parts.push(`### ${md(MEMO_HEADINGS[finding.key]||finding.key)}`,`Status: ${md(finding.status.replaceAll("_"," "))}`,md(finding.answer),`Source turns: ${sources(finding.evidence_turns)}`));
    parts.push("## Trigger",md(d.trigger),"## Inputs",list(d.inputs),"## Outputs",list(d.outputs),"## Procedure");
    d.steps.forEach((s,i) => parts.push(`### ${i+1}. ${md(s.title)} (${md(s.id)})`,`- Owner / role: ${md(s.actor||"UNKNOWN / TBD")}`,`- System / tool: ${md(s.system||"UNKNOWN / TBD")}`,`- Type: ${md(s.type)}`,`- Input: ${md(s.input||"UNKNOWN / TBD")}`,`- Output: ${md(s.output||"UNKNOWN / TBD")}`,`- Completion criteria: ${md(s.completion_criteria||"UNKNOWN / TBD")}`,`- Next handoff: ${md(s.handoff||"UNKNOWN / TBD")}`,"",md(s.description),"",`Source turns: ${sources(s.evidence_turns)}`));
    parts.push("## Process connections",d.connections.length?d.connections.map(c=>`- ${md(c.from)} → ${md(c.to)}${c.label?`: ${md(c.label)}`:""}. Source turns: ${sources(c.evidence_turns||[])}`).join("\n"):"No connections defined.","## Item lifecycles");
    if (!d.lifecycle_items.length) parts.push("UNKNOWN / TBD — no item lifecycles established.");
    d.lifecycle_items.forEach(item => parts.push(`### ${md(item.item)}`,"Stages:",list(item.stages),"Locations:",list(item.locations),"Handoffs:",list(item.handoffs),`Source turns: ${sources(item.evidence_turns)}`));
    parts.push("## Variations and boundaries");
    if (!d.variations.length) parts.push("UNKNOWN / TBD — an empty list does not confirm there are no variations.");
    d.variations.forEach((item,index)=>parts.push(`### Variation ${index+1}`,`- Applies to: ${md(item.applies_to)}`,`- Difference: ${md(item.difference)}`,`- Reason: ${md(item.reason)}`,`- Cost / effort: ${md(item.cost)}`,`- Charging / billing: ${md(item.charging)}`,`- Removability / standardization: ${md(item.removability)}`,`- Boundary: ${md(item.boundary.replaceAll("_"," "))}`,`- Boundary reason: ${md(item.boundary_reason)}`,`Source turns: ${sources(item.evidence_turns)}`));
    parts.push("## Exceptions",list(d.exceptions),"## Controls",list(d.controls),"## Open questions",list(d.open_questions),"## Validation notes",list(d.validation_notes),"## Parked topics",list(state.parking_lot),"## Interview evidence","The following is the interview record, not independent verification of the process. Coverage does not guarantee exhaustiveness.");
    state.turns.forEach(t => parts.push(`### ${md(t.id)} · ${t.role === "user" ? "Process participant" : "AI interviewer"}`, md(t.text)));
    return parts.filter(p => p !== "").join("\n\n") + "\n";
  }
  function memoMarkdown() {
    const d=state.draft,md=escapeMarkdown;
    const parts=[`# ${md(state.context?.process_name||d.title)} — process capture memo`,"**CURRENT-PRACTICE DRAFT — process owner review required**",state.example?"**Synthetic example — fictional process data.**":"",`Account confirmation: ${state.closure.confirmed?"participant confirmed":state.closure.asked?"requested; pending":"not yet requested"}. Process owner approval: pending.`,"Sources are the participant’s account and supplied context; they are not independent verification. UNKNOWN / TBD and unreviewed material remain visible gaps."];
    d.memo_summary.forEach((finding,index)=>parts.push(`## ${index+1}. ${md(MEMO_HEADINGS[finding.key]||finding.key)}`,`Status: ${md(finding.status.replaceAll("_"," "))}`,md(finding.answer),`Source: ${finding.evidence_turns.length?finding.evidence_turns.map(md).join(", "):"UNKNOWN / TBD"}`));
    if(d.variations.length){parts.push("## Variation differences");d.variations.forEach((v,index)=>parts.push(`### ${index+1}. ${md(v.applies_to)}`,`- What differs: ${md(v.difference)}`,`- Why: ${md(v.reason)}`,`- What it costs us: ${md(v.cost)}`,`- Do we charge: ${md(v.charging)}`,`- Could it go away: ${md(v.removability)}`,`- Boundary: ${md(v.boundary.replaceAll("_"," "))}. ${md(v.boundary_reason)}`));}
    parts.push("## Questions for the process owner — first five",d.open_questions.length?d.open_questions.slice(0,5).map((q,index)=>`${index+1}. ${md(q)}`).join("\n"):"UNKNOWN / TBD — review whether any gaps remain.");
    if(d.open_questions.length>5)parts.push(`${d.open_questions.length-5} additional open questions remain in the detailed procedure appendix and saved session.`);
    parts.push("The detailed process map, procedure, lifecycle records, sources, and full open-question register are in the companion appendix. A populated memo does not demonstrate exhaustive completeness.");
    return parts.filter(Boolean).join("\n\n")+"\n";
  }
  function canReplaceSession() {
    if (state.recording || state.busy || state.transcribing || state.requestingMic) { notice("Finish the current recording or request before replacing the session."); return false; }
    return !state.dirty || confirm("Replace the current session? Unsaved interview text and draft edits will be cleared. Save the session first if you want to keep them.");
  }
  function clearState(context = null) {
    if ($("foundation-dialog")?.open) closeFoundationTopic(false);
    stopSpeaking();
    finishRecording(true);
    state.generation++;
    state.version++;
    Object.assign(state,{context,turns:[],coverage:[],summary:"",draft:null,started:false,busy:false,requestingMic:false,transcribing:false,draftVersion:null,draftEdited:false,example:false,dirty:false,memo_findings:[],focus:"",parking_lot:[],closure:{asked:false,confirmed:false},elapsedMs:0,timerStartedAt:null});
    $("answer-text").value = "";
    $("global-notice").hidden = true;
    $("live-status").textContent = "";
    reviewUI.mapScale = 1; reviewUI.mapFit = true;
    selectReviewSection("review-memo");
    fillContext(context);
    renderTranscript(); renderDraft(); tab("interview"); closeMenu();
  }
  async function importSession(file) {
    if (!file) return;
    if (!canReplaceSession()) return;
    if (file.size > 2 * 1024 * 1024) { notice("That file is too large. Choose a saved interview smaller than 2 MB.", true); return; }
    try {
      const saved = JSON.parse(await file.text());
      if (saved?.schema_version !== 1 || !saved.context || !Array.isArray(saved.turns)) throw new Error("Choose an interview file saved from this app.");
      if (saved.turns.length > 400 || text(saved.context.objective).length > 500 || text(saved.context.background).length > 8000 || (typeof saved.unsent_answer === "string" && saved.unsent_answer.length > 18000)) throw new Error("The session exceeds the prototype’s context, answer, or 400-turn technical limit.");
      const planned = saved.context.meeting_minutes === undefined?60:Number(saved.context.meeting_minutes);
      if (!Number.isFinite(planned)||planned<1||planned>1440) throw new Error("The planned meeting duration must be between 1 and 1,440 minutes. This is advisory and never ends the interview.");
      const context = {
        process_name:text(saved.context.process_name,500),process_owner:text(saved.context.process_owner,500),objective:text(saved.context.objective,500),background:text(saved.context.background,8000),meeting_minutes:planned
      };
      const ids = new Set();
      const turns = saved.turns.map((turn,i) => {
        if (!turn || !["user","assistant"].includes(turn.role) || typeof turn.text !== "string" || typeof turn.id !== "string" || turn.id === "context" || !/^[a-zA-Z0-9_-]{1,40}$/.test(turn.id) || ids.has(turn.id)) throw new Error(`The session has an invalid, reserved, or duplicate turn ID at position ${i+1}.`);
        if (turn.text.length > 6000) throw new Error(`Turn ${turn.id} exceeds the 6,000-character limit.`);
        ids.add(turn.id); return {id:turn.id,role:turn.role,text:turn.text};
      });
      if (turns.reduce((n,t) => n+t.text.length,0) > 400000) throw new Error("The interview text exceeds the prototype’s 400,000-character technical limit.");
      const draft = saved.draft ? normalizeDraft(saved.draft,turns) : null;
      const findings = normalizeFindings(saved.memo_findings||[],turns);
      const summary = text(saved.summary,6000);
      const focus = text(saved.focus,500);
      const parked = strings(saved.parking_lot,50);
      const elapsed = Number(saved.elapsed_seconds||0);
      if (!Number.isFinite(elapsed)||elapsed<0) throw new Error("The session’s elapsed time is invalid.");
      clearState(context);
      Object.assign(state,{turns,coverage:normalizeCoverage(saved.coverage),summary,draft,started:turns.length>0,example:saved.synthetic_example===true,draftEdited:saved.draft_edited===true,memo_findings:findings,focus,parking_lot:parked,closure:{asked:saved.closure?.asked===true,confirmed:saved.closure?.confirmed===true},elapsedMs:elapsed*1000,timerStartedAt:null});
      if (typeof saved.voice_choice === "string" && saved.voice_choice.length <= 400 && /^(ai:[a-z]+|local:.+)$/.test(saved.voice_choice)) {
        state.voiceChoice=saved.voice_choice;state.voiceChoiceUser=true;populateVoiceOptions();
      }
      state.draftVersion = draft ? (saved.draft_stale ? state.version-1 : state.version) : null;
      $("answer-text").value = text(saved.unsent_answer);
      renderTranscript(); renderDraft();
      notice("Interview opened. The timer is paused.");
      if (draft) tab("review");
    } catch (error) { notice(`Could not open session: ${error.message}`, true); }
  }
  function loadExample() {
    if (!canReplaceSession()) return;
    clearState({process_name:"Invoice approval",process_owner:"Accounts payable manager",objective:"Understand invoice intake, approval, and exception handling.",background:"Synthetic example for exploring the prototype. All people, tools, and process details below are fictional.",meeting_minutes:60});
    state.example = true;
    state.started = true;
    state.turns = [
      {id:"t001",role:"assistant",text:"What starts the invoice approval process?"},
      {id:"t002",role:"user",text:"A vendor emails an invoice to our shared accounts payable mailbox. The AP analyst picks it up each morning, logs the invoice in a tracking spreadsheet, and checks for duplicate invoice numbers."},
      {id:"t003",role:"assistant",text:"After the duplicate check, what determines whether the analyst can send the invoice for approval?"},
      {id:"t004",role:"user",text:"The analyst compares the invoice with the purchase order and checks with the department that the goods or services were received. If everything matches, they email the department manager for approval. If it does not match, they put it on hold and ask the vendor or department to resolve it."},
      {id:"t005",role:"assistant",text:"How does the approval come back, and what happens next?"},
      {id:"t006",role:"user",text:"The manager replies by email. The analyst saves the approval in the invoice folder and marks the tracking sheet ready for payment. Treasury prepares the payment separately. We have not defined a backup approver or a standard turnaround time."},
      {id:"t007",role:"assistant",text:"When an invoice is on hold, who follows up, and how do they know the issue is resolved before it moves forward?"}
    ];
    state.memo_findings = normalizeFindings([
      {key:"name",status:"captured",answer:"Invoice approval, from receipt through handoff to Treasury. Payment execution is separate.",evidence_turns:["context","t006"]},
      {key:"purpose",status:"partial",answer:"Prepare matched, manager-approved invoices for payment. The wider business purpose was not explicitly discussed.",evidence_turns:["t004","t006"]},
      {key:"trigger",status:"captured",answer:"A vendor sends an invoice to the shared accounts payable mailbox.",evidence_turns:["t002"]},
      {key:"completion",status:"captured",answer:"Approval is saved and the tracking spreadsheet is marked ready for Treasury to prepare payment.",evidence_turns:["t006"]},
      {key:"accountable",status:"partial",answer:"The AP analyst performs the described steps and the department manager approves. A single accountable process owner was supplied in the context but not confirmed during the interview.",evidence_turns:["context","t002","t006"]},
      {key:"lifecycle",status:"partial",answer:"The invoice moves from shared mailbox to tracking spreadsheet, matching, approval email, invoice folder, and a ready-for-payment status. Hold release is unresolved.",evidence_turns:["t002","t004","t006"]},
      {key:"checks",status:"captured",answer:"Duplicate invoice-number check, invoice-to-purchase-order comparison, receipt confirmation, and saved manager approval.",evidence_turns:["t002","t004","t006"]},
      {key:"pain_points",status:"partial",answer:"No backup approver or standard turnaround time has been defined. Other pain points were not established.",evidence_turns:["t006"]},
      {key:"materials",status:"partial",answer:"The process uses a tracking spreadsheet, purchase orders, approval emails, and an invoice folder. Existing SOPs or templates were not discussed.",evidence_turns:["t002","t004","t006"]}
    ],state.turns);
    state.coverage = state.memo_findings.map(f=>({key:f.key,label:TOPICS.find(([key])=>key===f.key)[1],status:f.status==="captured"?"covered":f.status==="partial"?"partial":"missing"}));
    state.focus = "Ownership and release of invoices on hold";
    state.elapsedMs = 17*60000;
    state.summary = "Invoices arrive by email, are logged and checked for duplicates, matched to a purchase order and receipt, then routed for manager approval. Mismatches are held for resolution. Approval is saved before the invoice is marked ready for Treasury. Backup approval, timing, and hold follow-up remain unclear.";
    state.draft = normalizeDraft({
      title:"Invoice approval — current-state procedure",overview:"A fictional invoice approval workflow covering receipt through handoff to Treasury. Payment execution is outside the described process.",trigger:"A vendor invoice arrives in the shared accounts payable mailbox.",inputs:["Vendor invoice","Purchase order","Confirmation of goods or services received"],outputs:["Approved invoice package marked ready for payment","Invoices on hold pending resolution"],memo_summary:state.memo_findings,lifecycle_items:[{item:"Vendor invoice",stages:["Received","Logged and duplicate-checked","Matched to PO and receipt","Held for resolution if unmatched","Manager approval requested","Approval saved and marked ready for payment"],locations:["Shared mailbox","Tracking spreadsheet","Approval email","Invoice folder"],handoffs:["Vendor to AP analyst","AP analyst to receiving department","AP analyst to department manager","AP analyst to Treasury"],evidence_turns:["t002","t004","t006"]}],variations:[],steps:[
        {id:"S1",title:"Receive and log the invoice",type:"activity",actor:"AP analyst",system:"Shared mailbox and tracking spreadsheet",description:"Review the shared mailbox each morning and log the vendor invoice in the tracking spreadsheet.",evidence_turns:["t002"]},
        {id:"S2",title:"Check for duplicate invoice numbers",type:"activity",actor:"AP analyst",system:"Tracking spreadsheet",description:"Check whether the invoice number already exists. The treatment of a duplicate was not established and needs owner validation.",evidence_turns:["t002"]},
        {id:"S3",title:"Do the invoice, PO, and receipt match?",type:"decision",actor:"AP analyst and receiving department",system:"Purchase order and departmental confirmation",description:"Compare the invoice with the purchase order and obtain confirmation from the department that the goods or services were received.",evidence_turns:["t004"]},
        {id:"S4",title:"Hold and resolve the mismatch",type:"activity",actor:"AP analyst; vendor or department",system:"Communication channel not specified",description:"Put unmatched invoices on hold and ask the vendor or department to resolve the discrepancy. Follow-up ownership and the release criteria remain open.",evidence_turns:["t004"]},
        {id:"S5",title:"Request and receive manager approval",type:"activity",actor:"Department manager; AP analyst",system:"Email",description:"Send the matched invoice to the department manager by email. The manager replies by email with the approval.",evidence_turns:["t004","t006"]},
        {id:"S6",title:"Save approval and hand off for payment",type:"activity",actor:"AP analyst; Treasury",system:"Invoice folder and tracking spreadsheet",description:"Save the approval in the invoice folder, then mark the invoice ready for payment in the tracking spreadsheet. Treasury prepares payment in a separate process.",evidence_turns:["t006"]}
      ],connections:[{from:"S1",to:"S2",label:"",evidence_turns:["t002"]},{from:"S2",to:"S3",label:"Duplicate treatment needs validation",evidence_turns:["t002","t004"]},{from:"S3",to:"S4",label:"Mismatch",evidence_turns:["t004"]},{from:"S3",to:"S5",label:"Match",evidence_turns:["t004"]},{from:"S5",to:"S6",label:"Approved",evidence_turns:["t006"]}],exceptions:["Unmatched invoices are put on hold for vendor or department resolution.","No backup approver or standard turnaround time was defined in the example."],controls:["Check for duplicate invoice numbers.","Match the invoice to the purchase order and confirm receipt.","Save the manager’s approval before handoff for payment."],open_questions:["What happens when the duplicate check finds a match?","Who follows up on invoices on hold, and what authorizes release?","Who approves when the department manager is unavailable?","What happens if the manager rejects the invoice?"],validation_notes:["This is a synthetic example, not a verified business procedure.","Return routing from the hold step was not established; no return connection was invented.","Payment execution and any payment authorization controls were not covered."]});
    state.draftVersion = state.version;
    state.dirty = false;
    renderTranscript(); renderDraft(); scrollConversation();
    notice("Example opened. Explore the map, memo and procedure in Review.");
  }
  function initEvents() {
    initFoundationDialog();
    initReviewTabs();
    document.querySelectorAll(".nav-tab").forEach(button => button.addEventListener("click", () => tab(button.dataset.tab)));
    $("map-zoom-out")?.addEventListener("click",() => zoomMap(-.25));
    $("map-zoom-in")?.addEventListener("click",() => zoomMap(.25));
    $("map-fit")?.addEventListener("click",fitMapToWidth);
    window.addEventListener("resize",() => {if(reviewUI.mapFit)fitMapToWidth();});
    const foundationDetails = $("foundation-details");
    if (foundationDetails && window.matchMedia) {
      const narrow = window.matchMedia("(max-width:650px)");
      const adjustFoundation = () => {foundationDetails.open = !narrow.matches;};
      adjustFoundation(); narrow.addEventListener("change",adjustFoundation);
    }
    $("context-form").addEventListener("submit",startInterview);
    $("context-form").addEventListener("invalid",event => {revealAncestors(event.target);event.target.focus();},true);
    $("answer-form").addEventListener("submit",sendAnswer);
    $("answer-text").addEventListener("input",() => {state.dirty = true; updateControls();});
    $("answer-text").addEventListener("keydown",event => {if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {event.preventDefault(); sendAnswer(event);}});
    $("record-answer").addEventListener("click",startRecording);
    $("cancel-recording").addEventListener("click",() => finishRecording(true));
    $("stop-speaking").addEventListener("click",stopSpeaking);
    $("voice-select").addEventListener("change",()=>{
      stopSpeaking();state.voiceChoice=$("voice-select").value;state.voiceChoiceUser=true;populateVoiceOptions();
      if(state.started)state.dirty=true;
      updateSaveHint();
    });
    $("preview-voice").addEventListener("click",()=>{
      state.voiceChoiceUser=true;
      speak("Hello. I am your process interviewer. Tell me how the work begins, and we can take it one step at a time.");
    });
    $("speak-questions").addEventListener("change",() => {if (!$("speak-questions").checked) stopSpeaking();});
    $("skip-question").addEventListener("click",skipQuestion);
    $("final-check").addEventListener("click",finalCheck);
    $("pause-timer").addEventListener("click",()=>{
      if(!state.started)return;
      if(state.timerStartedAt===null)state.timerStartedAt=Date.now();
      else{state.elapsedMs=elapsedMs();state.timerStartedAt=null;}
      state.dirty=true;updateSaveHint();updateTimer();
    });
    $("meeting-minutes").addEventListener("change",()=>{
      const value=Number($("meeting-minutes").value);
      if(!Number.isInteger(value)||value<1||value>1440){$("meeting-minutes").reportValidity();return;}
      if(state.context)state.context.meeting_minutes=value;
      state.dirty=true;updateSaveHint();updateLaunchPlan();updateTimer();
    });
    $("generate-draft").addEventListener("click",generateDraft);
    $("regenerate-draft").addEventListener("click",generateDraft);
    $("back-to-interview").addEventListener("click",() => tab("interview",true));
    $("empty-start").addEventListener("click",() => tab("interview",true));
    $("dismiss-notice").addEventListener("click",() => {$("global-notice").hidden = true;});
    $("session-menu-toggle").addEventListener("click",() => {const open = $("session-menu").hidden; $("session-menu").hidden = !open; $("session-menu-toggle").setAttribute("aria-expanded",String(open));});
    document.addEventListener("click",event => {if (!$("session-menu").contains(event.target) && !$("session-menu-toggle").contains(event.target)) closeMenu();});
    document.addEventListener("keydown",event => {if (event.key === "Escape") closeMenu();});
    $("export-session").addEventListener("click",exportSession);
    $("import-session").addEventListener("click",() => {closeMenu(); $("session-file").click();});
    $("session-file").addEventListener("change",event => {importSession(event.target.files[0]); event.target.value = "";});
    $("reset-session").addEventListener("click",() => {if (canReplaceSession()) clearState();});
    $("load-example").addEventListener("click",loadExample);
    $("welcome-example").addEventListener("click",loadExample);
    $("leave-example").addEventListener("click",() => {if (canReplaceSession()) {clearState(); revealContext(); $("process-name").focus();}});
    $("export-markdown").addEventListener("click",() => {if (state.draft) download(markdown(),`${safeFilename(state.draft.title)}-DRAFT.md`,"text/markdown;charset=utf-8");});
    $("export-memo").addEventListener("click",()=>{if(state.draft)download(memoMarkdown(),`${safeFilename(state.context?.process_name||state.draft.title)}-memo-DRAFT.md`,"text/markdown;charset=utf-8");});
    $("export-map").addEventListener("click",() => {const svg = $("process-map").querySelector("svg"); if (svg) download(new XMLSerializer().serializeToString(svg),`${safeFilename(state.draft.title)}-DRAFT-map.svg`,"image/svg+xml");});
    $("add-step").addEventListener("click",() => {
      if (!state.draft || state.draft.steps.length >= 80) return;
      let n = state.draft.steps.length + 1;
      while (state.draft.steps.some(s => s.id === `S${n}`)) n++;
      state.draft.steps.push({id:`S${n}`,title:"New step — validate with owner",type:"activity",actor:"UNKNOWN / TBD",system:"UNKNOWN / TBD",description:"",input:"UNKNOWN / TBD",output:"UNKNOWN / TBD",completion_criteria:"UNKNOWN / TBD",handoff:"UNKNOWN / TBD",evidence_turns:[]});
      draftChanged(); renderSteps(); renderConnections(); renderMap();
      $("procedure-steps").lastElementChild.querySelector("input").focus();
    });
    $("add-connection").addEventListener("click",() => {
      if (!state.draft || state.draft.steps.length < 2 || state.draft.connections.length >= 150) {notice("Add at least two steps before defining a connection. This prototype supports up to 150 connections."); return;}
      state.draft.connections.push({from:state.draft.steps[0].id,to:state.draft.steps[1].id,label:"",evidence_turns:[]});
      draftChanged(); renderConnections(); renderMap();
    });
    $("add-lifecycle").addEventListener("click",()=>{
      if(!state.draft||state.draft.lifecycle_items.length>=100)return;
      state.draft.lifecycle_items.push({item:"New work item — validate with owner",stages:["UNKNOWN / TBD"],locations:["UNKNOWN / TBD"],handoffs:["UNKNOWN / TBD"],evidence_turns:[]});
      draftChanged();renderLifecycle();
    });
    $("add-variation").addEventListener("click",()=>{
      if(!state.draft||state.draft.variations.length>=100)return;
      state.draft.variations.push({applies_to:"UNKNOWN / TBD",difference:"UNKNOWN / TBD",reason:"UNKNOWN / TBD",cost:"UNKNOWN / TBD",charging:"UNKNOWN / TBD",removability:"UNKNOWN / TBD",boundary:"variation",boundary_reason:"UNKNOWN / TBD — assess whether this is a variation or separate work.",evidence_turns:[]});
      draftChanged();renderVariations();
    });
    document.querySelectorAll("#context-form input,#context-form textarea").forEach(input => input.addEventListener("input",() => {state.dirty = true;updateSaveHint();updateLaunchPlan();}));
    window.addEventListener("beforeunload",event => {if (state.dirty || state.recording || state.requestingMic || state.transcribing) {event.preventDefault(); event.returnValue = "";}});
    window.addEventListener("pagehide",() => {stopSpeaking(); finishRecording(true);});
    bindDraftFields();
  }
  async function init() {
    initEvents(); renderCoverage(); updateControls();
    refreshVoices();
    window.speechSynthesis?.addEventListener("voiceschanged", refreshVoices);
    setInterval(updateTimer,1000);
    try {
      const response = await fetch("/api/config",{credentials:"same-origin",cache:"no-store"});
      if (!response.ok) throw new Error("The interviewer is unavailable. Please try again.");
      const config = await response.json();
      if (typeof config.csrf_token !== "string") throw new Error("The interviewer is unavailable. Please try again.");
      state.config = config;
      $("data-notice").textContent = text(config.data_notice,4000) || "Data handling information is unavailable. Check the service configuration before submitting interview content.";
      populateVoiceOptions();
      $("connection-state").hidden = true;
      $("connection-state").querySelector("span").textContent = config.api_configured ? "Ready" : "Unavailable";
      if (!config.api_configured) notice("The interviewer is unavailable. Please try again.",true);
    } catch(error) {
      $("connection-state").hidden = true;
      $("connection-state").querySelector("span").textContent = "Unavailable";
      notice("The interviewer is unavailable. Please try again.",true);
    }
    updateControls();
  }
  init();
})();
