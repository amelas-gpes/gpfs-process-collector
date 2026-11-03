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
  const readingUI = {transcript:{query:"",matches:[],index:-1},report:{query:"",matches:[],index:-1}};
  let sourceOrigin=null;
  let memoRestoreFocus=true, settingsRestoreFocus=true, noticeTimer=null, noticeKind="general";
  const REVIEW_SECTIONS = ["review-report","review-memo","review-map","review-procedure","review-lifecycles","review-variations","review-questions"];
  const reviewUI = {section:"review-report",mapScale:1,mapFit:true};
  const state = {
    context: null, turns: [], coverage: [], summary: "", draft: null, processNameManual:false,
    started: false, busy: false, version: 0, generation: 0,
    draftVersion: null, draftEdited: false, example: false, dirty: false,
    config: null, utterance: null, voice: null, speechVersion: 0,
    localVoices: [], voiceChoice: null, voiceChoiceUser: false, speechOperation: null,
    recording: null, requestingMic: false, transcribing: false,
    memo_findings: [], focus: "", parking_lot: [], closure: {asked:false,confirmed:false},
  };
  const conversationUI = {view:"voice", typing:false, live:null, status:"idle", muted:false, captions:new Map(), workflow:null, revision:0, applied:-1, flowBusy:false, flowTimer:null, flowAbort:null};
  const icons = {
    play: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m5 3 7 5-7 5Z"/></svg>'
  };
  const svgNS = "http://www.w3.org/2000/svg";
  const workflowCanvases=new Map();
  let workflowDetailReturn=null, workflowDetailSource=null;
  let documentController=null, pendingDocumentReason=null, restoringDocuments=false;
  let knowledgeUI=null;
  let gpfsPresence=null, auxiliaryVoiceState="idle", voiceEnded=false;
  const documentQuestionsHandled=new Set(),documentVoiceUpdates=new Set();

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

  function notice(message, error = false, kind="general") {
    clearTimeout(noticeTimer);noticeKind=kind;
    $("notice-text").textContent = message;
    $("global-notice").classList.toggle("error", error);
    $("global-notice").hidden = false;
    $("live-status").textContent = message;
    if(error){const region=$($("review-view").hidden?"interview-error":"review-error");if(region){region.hidden=false;region.dataset.errorKind=kind;region.querySelector("span").textContent=message;}}
    noticeTimer=setTimeout(()=>{$("global-notice").hidden=true;noticeTimer=null;},3000);
  }
  function closeMenu() {
    $("session-menu").hidden = true;
    $("session-menu-toggle").setAttribute("aria-expanded", "false");
  }
  function tab(name, focus = false) {
    if(name==="review"&&(conversationUI.live?.active||conversationUI.status==="closing")){notice("End live voice before opening Review. Your microphone controls stay here.");return;}
    $("interview-view").hidden = name !== "interview";
    $("review-view").hidden = name !== "review";
    document.body?.classList.toggle("review-mode", name === "review");
    if (name === "review") {setMemoSheet(false,false);selectReviewSection(reviewUI.section);}
    document.querySelectorAll(".nav-tab").forEach(button => {
      const active = button.dataset.tab === name;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
    });
    updatePresence();
    if (focus) {
      const target = name === "review" ? $("review-view") : state.started ? $("conversation-tab-"+conversationUI.view) : $("start-live");
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
      background: $("background").value.trim()
    };
  }
  function fillContext(context) {
    $("process-name").value = context?.process_name || "";
    $("process-owner").value = context?.process_owner || "";
    $("objective").value = context?.objective || "Understand the current process, responsibilities, handoffs, and exceptions.";
    $("background").value = context?.background || "";
  }
  function applyProcessTitle(value) {
    if(state.processNameManual||!state.turns.some(turn=>turn.role==="user"))return;
    const title=typeof value==="string"&&value.length<=180?value.trim():"";
    if(!title||/^(unknown|untitled|process|workflow|interview|not established)(\s*[-—:].*)?$/i.test(title))return;
    state.context=state.context||readContext();
    if(state.context.process_name===title)return;
    state.context.process_name=title;$("process-name").value=title;
    state.version++;state.dirty=true;$("live-status").textContent=`Process named: ${title}. You can edit the title above.`;updateSaveHint();
  }
  function revealAncestors(target) {
    for (let node = target; node; node = node.parentElement) {
      if (node.tagName === "DETAILS") node.open = true;
    }
  }
  function revealContext() {
    if($("context-details"))$("context-details").hidden=false;
    setInterviewSettings(true);
    if ($("setup-card")) $("setup-card").open = true;
    if ($("context-details")) $("context-details").open = true;
    revealAncestors($("context-form"));
  }
  function updateSaveHint() {
    const hint = $("save-hint");
    if (!hint) return;
    const message = state.dirty ? "Unsaved changes" : "";
    if (hint.textContent !== message) hint.textContent = message;
    hint.hidden = !state.dirty;
    $("export-session")?.classList.toggle("has-unsaved",state.dirty);
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
    if ($("setup-summary")) $("setup-summary").textContent = state.started ? state.context?.process_name || "Interview" : "Space to think.";
    $("start-interview").firstElementChild.textContent = state.started ? "New interview" : "Start interview";
    ["process-owner", "objective", "background"].forEach(id => { $(id).disabled = state.started || working || recording; });
    $("process-name").disabled=false;
    $("answer-text").disabled = !state.started || working || recording || !ready;
    $("send-answer").disabled = !state.started || working || recording || !ready || atLimit || !$("answer-text").value.trim();
    $("record-answer").disabled = !state.started || working || !ready || atLimit;
    $("skip-question").disabled = !state.started || working || recording || !ready || atLimit;
    $("final-check").disabled = !state.started || working || recording || !ready || atLimit || !state.turns.some(t => t.role === "user");
    $("composer-hint").textContent = atLimit ? "Interview limit reached. Create a draft or save this session." : "Review the transcript, then send.";
    if($("retry-question"))$("retry-question").disabled=working||recording||Boolean(conversationUI.live?.active);
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
    $("record-answer").setAttribute("aria-label",recording?"Finish recording":"Record an answer");
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
    $("closure-status").hidden = !state.closure.asked && !state.closure.confirmed;
    $("closure-status").textContent = state.closure.confirmed ? "Participant confirmed completeness." : state.closure.asked ? "Waiting for final confirmation." : "";
    updateConversationControls();
    updateSaveHint();
    if($("export-markdown"))$("export-markdown").title=state.draft?"Download the complete business process report as Markdown":"Create a review draft to download the report";
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
    const root = $("coverage-list"), focusedTopic=document.activeElement?.dataset?.foundationTopic;
    root.replaceChildren();
    let completed = 0;
    let partial = 0;
    TOPICS.forEach(([key, label]) => {
      const item = state.coverage.find(c => c.key === key);
      const finding = state.memo_findings.find(c => c.key === key);
      const status = finding ? (["not_applicable","captured"].includes(finding.status) ? "covered" : finding.status==="partial" ? "partial" : "missing") : ["partial","covered"].includes(item?.status) ? item.status : "missing";
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
      node.append(el("span", "coverage-dot", status === "covered" ? "✓" : ""), el("span", "coverage-label", label), el("span", "coverage-state", finding?.status === "not_applicable" ? "Not applicable" : status === "covered" ? "Captured" : status === "partial" ? "Exploring" : "To explore"));
      node.addEventListener("click", () => showFoundationTopic(key,node));
      root.append(node);
    });
    $("coverage-count").textContent = `${completed} / ${TOPICS.length}`;
    $("coverage-progress").style.width = `${(completed + partial * .5) / TOPICS.length * 100}%`;
    if($("coverage-mobile-count")) $("coverage-mobile-count").textContent=`${completed}/${TOPICS.length}`;
    if($("coverage-summary")) $("coverage-summary").textContent=completed ? `${completed} topics captured` : "Building the picture";
    renderMemoContext();
    if(focusedTopic&&!$("foundation-dialog")?.open)document.querySelector(`[data-foundation-topic="${focusedTopic}"]`)?.focus({preventScroll:true});
    if(foundationTopic && $("foundation-dialog")?.open) showFoundationTopic(foundationTopic,document.querySelector(`[data-foundation-topic="${foundationTopic}"]`));
  }
  function renderMemoContext() {
    if($("memo-focus")) $("memo-focus").textContent=state.focus || (state.started ? "Understanding how the work begins" : "The work you want to capture");
    const remaining=TOPICS.filter(([key])=>{
      const finding=state.memo_findings.find(f=>f.key===key),coverage=state.coverage.find(c=>c.key===key);
      return finding ? !["captured","not_applicable"].includes(finding.status) : coverage?.status!=="covered";
    }).map(([,label])=>label);
    if($("memo-next")) $("memo-next").textContent=remaining.length ? remaining.slice(0,3).join(" · ")+(remaining.length>3?` + ${remaining.length-3} more`:"") : "All topics captured. Confirm any gaps before wrapping up.";
    const next=$("memo-next-action");if(next){next.hidden=!remaining.length;next.textContent=remaining.length?`Explore ${remaining[0]} →`:"";next.onclick=()=>{const topic=TOPICS.find(([,label])=>label===remaining[0]);if(topic){setMemoSheet(false,false);showFoundationTopic(topic[0],document.querySelector(`[data-foundation-topic="${topic[0]}"]`));}};}
    $("working-summary").hidden=!state.summary; $("summary-text").textContent=state.summary;
    $("parking-panel").hidden=!state.parking_lot.length;
    $("parking-count").textContent=state.parking_lot.length ? `(${state.parking_lot.length})` : "";
    $("parking-list").replaceChildren(...state.parking_lot.map(item=>el("li","",item)));
  }
  function setMemoSheet(open, restoreFocus=true) {
    memoRestoreFocus=restoreFocus;
    const sheet=$("memo-sheet"); if(!sheet)return;
    if(open&&!sheet.open)sheet.showModal();
    if(!open&&sheet.open)sheet.close();
  }
  function setInterviewSettings(open, restoreFocus=true) {
    settingsRestoreFocus=restoreFocus;
    const dialog=$("interview-settings"); if(!dialog)return;
    if(open&&!dialog.open)dialog.showModal();
    if(!open&&dialog.open)dialog.close();
  }
  function showFoundationTopic(key, trigger) {
    if (!TOPICS.some(([topic]) => topic === key)) return;
    const dialog = $("foundation-dialog");
    if (!dialog || typeof dialog.showModal !== "function") {notice("Topic details are unavailable in this browser. Please use a current browser.",true);return;}
    const finding = state.memo_findings.find(item => item.key === key);
    const labels = {unknown:"Unknown / TBD",partial:"Partial",captured:"Captured",not_applicable:"Not applicable"};
    foundationTopic = key; foundationReturnFocus = trigger?.closest?.("dialog")&&!trigger.closest("dialog").open ? $("open-memo") : trigger; foundationRestoreFocus = true;
    $("foundation-topic-title").textContent = MEMO_HEADINGS[key];
    $("foundation-topic-status").textContent = labels[finding?.status] || labels.unknown;
    $("foundation-topic-answer").textContent = finding?.answer?.trim() ? finding.answer : "Not yet established in this interview.";
    $("foundation-topic-hint").textContent = finding?.status==="partial" ? `Still to clarify: ${TOPIC_GUIDES[key]} Resolve the open detail or uncertainty before this topic can be complete. Review the cited answers for context.` : finding?.answer?.trim() ? "Reported from the interview; not independently verified. Review the cited answers for context." : TOPIC_GUIDES[key];
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
    const root = $("transcript"), current = $("current-question"), scroll=$("conversation-scroll"), scrollTop=scroll.scrollTop;
    const latest = state.turns.findLast(turn => turn.role === "assistant"&&!turn.document_event);
    root.replaceChildren();
    state.turns.forEach(turn => {
      const item = el("article", `turn ${turn.role}`); item.id = `turn-${turn.id}`;
      const content = el("div", "turn-content"), meta = el("div", "turn-meta");
      meta.append(el("span", "turn-name", turn.role === "assistant" ? "Interviewer" : "You"), el("span", "turn-id", sourceCaption(turn.id)));
      content.append(meta, el("p", "turn-text", turn.text));
      if (turn.role === "assistant") {
        const play = el("button", "play-turn", "Listen"); play.type="button";
        play.disabled = !canSpeakChoice() || Boolean(conversationUI.live?.active);
        play.setAttribute("aria-label", `Listen to ${sourceCaption(turn.id)} using the selected voice`);
        play.addEventListener("click", () => speak(turn.text)); content.append(play);
      }
      item.append(content); root.append(item);
    });
    current.replaceChildren();
    if (latest) current.append(el("p", "turn-text", latest.text));
    current.hidden = !latest;
    $("conversation-history").hidden = false;
    $("history-count").textContent = state.turns.length ? `${state.turns.length} messages` : "";
    if ($("transcript-count")) $("transcript-count").textContent=state.turns.length||"";
    if ($("transcript-empty")) $("transcript-empty").hidden=state.turns.length>0;
    $("working-summary").hidden = !state.summary; $("summary-text").textContent = state.summary;
    $("parking-panel").hidden = !state.parking_lot.length;
    $("parking-count").textContent = state.parking_lot.length ? `(${state.parking_lot.length})` : "";
    $("parking-list").replaceChildren(...state.parking_lot.map(item => el("li","",item)));
    scroll.scrollTop=scrollTop;
    refreshReadingSearch("transcript",false);
    renderCoverage(); updateControls();
  }
  function refreshReadingSearch(kind,move=true) {
    const ui=readingUI[kind],root=$(kind==="transcript"?"transcript":"report-content");if(!root)return;
    const input=$(kind+"-search"),query=(input?input.value:ui.query||"").trim().slice(0,180);ui.query=query;
    const previous=ui.index;ui.matches=[];
    const selector=kind==="transcript"?".turn-text":"p,dd,li,h1,h2,h3,h4";
    root.querySelectorAll(selector).forEach(part=>{
      if(part.querySelector("button"))return;
      const original=part.textContent;part.textContent="";
      const lower=original.toLocaleLowerCase(),needle=query.toLocaleLowerCase();let start=0,index=needle?lower.indexOf(needle):-1;
      while(index!==-1&&ui.matches.length<500){part.append(el("span","",original.slice(start,index)));const mark=el("mark","search-match",original.slice(index,index+query.length));part.append(mark);ui.matches.push(mark);start=index+query.length;index=lower.indexOf(needle,start);}
      part.append(el("span","",original.slice(start)));
    });
    ui.index=ui.matches.length?Math.max(0,Math.min(previous,ui.matches.length-1)):-1;
    updateSearchPosition(kind,move);
  }
  function updateSearchPosition(kind,move=true) {
    const ui=readingUI[kind];ui.matches.forEach((mark,i)=>mark.classList.toggle("current-match",i===ui.index));
    const count=$(kind+"-search-count");if(count)count.textContent=ui.query?(ui.matches.length?`${ui.index+1} / ${ui.matches.length}${ui.matches.length===500?"+":""}`:"No matches"):"";
    for(const direction of ["previous","next"])if($(kind+"-search-"+direction))$(kind+"-search-"+direction).disabled=!ui.matches.length;
    if(move)ui.matches[ui.index]?.scrollIntoView({block:"center",behavior:"smooth"});
  }
  function moveReadingSearch(kind,direction){const ui=readingUI[kind];if(!ui.matches.length)return;ui.index=(ui.index+direction+ui.matches.length)%ui.matches.length;updateSearchPosition(kind);}
  function rememberSourceOrigin(){sourceOrigin={generation:state.generation,review:!$("review-view").hidden,section:reviewUI.section,view:conversationUI.view,scroll:$("conversation-scroll").scrollTop,reviewScroll:$("review-view").scrollTop,topic:foundationTopic,memoOpen:Boolean($("memo-sheet")?.open),focus:document.activeElement,turn:document.activeElement?.dataset?.sourceTurn,step:workflowDetailSource?{...workflowDetailSource}:null};}
  function returnToSource(){
    const origin=sourceOrigin;sourceOrigin=null;if($("source-return"))$("source-return").hidden=true;if($("settings-source-return"))$("settings-source-return").hidden=true;if(!origin||origin.generation!==state.generation)return;
    setInterviewSettings(false,false);
    if(origin.review){tab("review");selectReviewSection(origin.section);$("review-view").scrollTop=origin.reviewScroll;}else{tab("interview");selectConversationView(origin.view);$("conversation-scroll").scrollTop=origin.scroll;}
    if(origin.topic){if(origin.memoOpen)setMemoSheet(true);showFoundationTopic(origin.topic,document.querySelector(`[data-foundation-topic="${origin.topic}"]`));}
    else if(origin.step){const graph=origin.step.containerId==="live-workflow"?conversationUI.workflow:state.draft,step=graph?.steps.find(s=>s.id===origin.step.stepId);if(step){workflowCanvases.get(origin.step.containerId)?.focusStep?.(step.id);showWorkflowStep(step,origin.step.containerId);}}
    else {const surface=origin.review?$(origin.section):$(origin.view+"-panel"),replacement=origin.turn?[...surface.querySelectorAll(".evidence-link")].find(link=>link.dataset.sourceTurn===origin.turn):null;const focus=replacement||(origin.focus?.isConnected&&surface.contains(origin.focus)?origin.focus:null)||$(origin.review?`review-tab-${origin.section.slice(7)}`:`conversation-tab-${origin.view}`);focus?.focus({preventScroll:true});}
  }
  function selectConversationView(view, focus=false) {
    if (!["voice","transcript","workflow"].includes(view)) return;
    conversationUI.view=view;
    if(view!=="workflow"){$("interview-view").classList.remove("workflow-expanded");if($("workflow-expand")){$("workflow-expand").setAttribute("aria-pressed","false");$("workflow-expand").textContent="Focus";}}
    document.querySelectorAll("[data-conversation-view]").forEach(button=>{
      const active=button.dataset.conversationView===view;
      button.setAttribute("aria-selected",String(active)); button.tabIndex=active?0:-1;
      if(active&&focus)button.focus();
    });
    for(const name of ["voice","transcript","workflow"]) if($(name+"-panel")) $(name+"-panel").hidden=name!==view;
    if(view==="workflow")requestAnimationFrame(()=>workflowCanvases.get("live-workflow")?.refresh());
    updatePresence();
  }
  function presenceState() {
    if(conversationUI.live?.active||conversationUI.status==="closing")return conversationUI.status;
    if(state.requestingMic)return "connecting";
    if(state.recording)return "listening";
    if(auxiliaryVoiceState!=="idle")return auxiliaryVoiceState;
    if(state.busy||state.transcribing)return "processing";
    return voiceEnded?"ended":"idle";
  }
  function updatePresence() {
    const status=presenceState(),labels={idle:"Ready when you are",connecting:"Connecting…",listening:"Listening",speaking:"Speaking",processing:"Processing…",muted:"Microphone muted",closing:"Finishing your transcript…",ended:"Voice ended"};
    gpfsPresence?.setState(status==="closing"?"ended":status);
    gpfsPresence?.setVisible(conversationUI.view==="voice"&&!$("interview-view")?.hidden&&!document.hidden);
    const label=$("presence-status");
    if(label){label.textContent=labels[status]||labels.idle;label.hidden=status==="idle"&&!state.started;}
    const session=$("session-presence");
    if(session){session.hidden=!conversationUI.live?.active&&status!=="closing";session.dataset.active=String(Boolean(conversationUI.live?.active));}
    const sessionLabel=$("session-status");
    if(sessionLabel)sessionLabel.textContent=status==="speaking"&&conversationUI.muted?"Speaking · mic muted":labels[status]||"";
  }
  function conversationTabKey(event) {
    const views=["voice","transcript","workflow"], index=views.indexOf(event.currentTarget.dataset.conversationView);
    const next=event.key==="Home"?0:event.key==="End"?2:event.key==="ArrowRight"?(index+1)%3:event.key==="ArrowLeft"?(index+2)%3:null;
    if(next!==null){event.preventDefault();selectConversationView(views[next],true);}
  }
  function updateConversationControls() {
    if(!$("start-live"))return;
    const active=Boolean(conversationUI.live?.active), closing=conversationUI.status==="closing";
    $("start-live").hidden=active||closing;
    $("start-live").disabled=!state.config?.live?.enabled||state.busy||Boolean(state.recording)||state.requestingMic||state.transcribing;
    $("stop-live").hidden=!active&&!closing; $("stop-live").disabled=closing;
    $("stop-live").textContent=closing?"Finishing…":"End voice";
    $("mute-live").hidden=!conversationUI.live?.connected;
    $("mute-live").textContent=conversationUI.muted?"Unmute mic":"Mute mic";
    $("mute-live").setAttribute("aria-pressed",String(conversationUI.muted));
    $("type-instead").hidden=active||closing;
    $("type-instead").textContent=conversationUI.typing?"Hide keyboard":"Type instead";
    $("composer-area").hidden=!conversationUI.typing;
    $("skip-question").hidden=!conversationUI.typing;
    $("voice-select").disabled=active||closing||Boolean(state.recording);
    $("preview-voice").disabled=active||closing||!canSpeakChoice()||state.busy||Boolean(state.recording);
    if(active||closing) for(const id of ["answer-text","send-answer","record-answer","skip-question","final-check","generate-draft","regenerate-draft"]) $(id).disabled=true;
    updatePresence();
    $("start-live").querySelector("span").textContent=state.turns.length?"Continue voice":"Start voice";
    $("presence-caption").hidden=state.started;
  }
  function ensureConversation() {
    if(state.started)return true;
    if(!$("objective").value.trim()) {setInterviewSettings(true);$("objective").reportValidity();$("objective").focus();return false;}
    state.context=readContext();state.started=true;state.example=false;state.dirty=true;updateControls();return true;
  }
  function documentContext() {
    return {context:clone(state.context||readContext()),turns:clone(state.turns.slice(-8)),focus:state.focus,
      current_question:[...state.turns].reverse().find(turn=>turn.role==="assistant"&&!turn.document_event)?.text||""};
  }
  function appendDocumentMessage(message, document, isQuestion=false) {
    if(!message||!ensureConversation())return;
    if(state.turns.length>=400||state.turns.reduce((size,turn)=>size+turn.text.length,0)+message.length>400000){
      notice("The file is ready in Files. Save this interview before starting a continuation.");return;
    }
    const pane=$("conversation-scroll"),follow=pane.scrollHeight-pane.clientHeight-pane.scrollTop<80;
    state.turns.push({id:nextTurnId(),role:"assistant",text:text(message,3000),document_event:!isQuestion,document_id:document.id});
    state.version++;state.dirty=true;renderTranscript();
    if(follow&&conversationUI.view==="transcript")scrollConversation();
  }
  function deliverDocumentContext(document, force=false) {
    if(!conversationUI.live?.active||!conversationUI.live.appendContext)return;
    const analysis=document.analysis||{},phase=analysis.summary?(analysis.phase==="complete"?"complete":"quick"):"received";
    const id=`${document.id}_${analysis.intent_version||0}_${phase}`;
    if(documentVoiceUpdates.has(id)&&!force)return;
    documentVoiceUpdates.add(id);
    const generation=state.generation;
    const content={file:document.name,state:phase,disposition:analysis.disposition||"reviewing",summary:analysis.summary||"File received. Background review is starting.",
      question:analysis.question||"",sources:(analysis.sources||[]).slice(0,3),questions_for_later:(analysis.questions||[]).slice(0,2),
      basis_question:analysis.basis_question||"",unconfirmed:true};
    conversationUI.live.appendContext(JSON.stringify(content),{id,kind:phase==="received"?"document_received":"document_findings"}).then(receipt=>{
      if(generation===state.generation&&receipt.status==="rejected")notice("The file is retained, but its update did not reach the voice session. You can review it in Files.",true);
    });
  }
  function onDocumentEvent(event) {
    const document=event.document,analysis=event.analysis||document?.analysis||{};
    if(event.type==="received") {
      state.dirty=true;updateSaveHint();
      if(conversationUI.live?.active)deliverDocumentContext(document);
      else appendDocumentMessage(`Received ${document.name}. I’ll check it against what we’re discussing while you continue.`,document);
    } else if(event.type==="analysis") {
      state.dirty=true;updateSaveHint();
      if(state.draft&&reviewUI.section==="review-report")renderReport();
      if(!analysis.summary||restoringDocuments)return;
      if(conversationUI.live?.active){deliverDocumentContext(document);return;}
      const key=`${document.id}_${analysis.intent_version||0}`;
      if(documentQuestionsHandled.has(key))return;
      const latestUser=[...state.turns].reverse().find(turn=>turn.role==="user")?.id||"";
      const currentQuestion=documentContext().current_question;
      // A late result belongs in the tray, not on top of a newer question or unsent answer.
      if(state.busy||state.recording||state.transcribing||state.requestingMic||$("answer-text").value.trim()||latestUser!==String(analysis.basis_turn_id||"")||
        String(analysis.basis_question||"")!==currentQuestion)return;
      documentQuestionsHandled.add(key);
      const question=analysis.disposition==="parked"?"":analysis.question||"";
      appendDocumentMessage([analysis.acknowledgement,question].filter(Boolean).join(" "),document,Boolean(question));
      if(analysis.disposition==="needs_reason"&&question)pendingDocumentReason={id:document.id};
    } else if(event.type==="question") {
      if(conversationUI.live?.active){
        conversationUI.live.appendContext(JSON.stringify({participant_selected_question:event.question.text,file:document.name,sources:event.question.sources||[],unconfirmed:true}),
          {id:`${document.id}_selected_${Date.now()}`,kind:"selected_document_question"});
      }else {
        if(!ensureConversation())return;
        conversationUI.typing=true;selectConversationView("transcript");
        appendDocumentMessage(`From ${document.name}: ${event.question.text}`,document,true);updateControls();$("answer-text").focus();
      }
    }
  }
  async function resolveDocumentPurpose(answer) {
    const pending=pendingDocumentReason,scope=documentController?.exportState().scope;
    if(!pending||!scope)return;
    const generation=state.generation;
    pendingDocumentReason=null;
    try {
      await request("/api/documents/action",{scope,id:pending.id,action:"purpose",purpose:text(answer,2000)});
      if(generation===state.generation)documentController?.refresh();
    }catch(error){if(generation===state.generation)notice("Your answer is retained. You can give the file a short purpose or save it for later in Files.",true);}
  }
  async function startLiveConversation() {
    if(state.busy||state.recording||state.transcribing||state.requestingMic||conversationUI.live?.active)return;
    if(!ensureConversation())return;
    stopSpeaking(); voiceEnded=false; conversationUI.typing=false; conversationUI.muted=false;
    if(!conversationUI.live) {
      if(!window.CollectorLiveVoice){notice("Live voice could not load. Refresh or continue by typing.",true);return;}
      conversationUI.live=new window.CollectorLiveVoice({request,
        onStatus:status=>{conversationUI.status=status;updateControls();},
        onTranscript:receiveLiveCaption,
        onError:message=>notice(message,true),
        onAudioFrame:frame=>gpfsPresence?.setAudio(frame)
      });
    }
    selectConversationView(conversationUI.view);
    await conversationUI.live.start({context:clone(state.context),turns:clone(state.turns.filter(turn=>!turn.document_event)),document_scope:documentController?.exportState().scope});
    if(conversationUI.live?.active)for(const document of documentController?.exportState().documents||[])deliverDocumentContext(document,true);
  }
  function receiveLiveCaption(caption) {
    if(!caption.text||!["user","assistant"].includes(caption.role))return;
    const scroll=$("conversation-scroll"), follow=scroll.scrollHeight-scroll.clientHeight-scroll.scrollTop<80;
    const key=`${caption.role}:${caption.id}`;
    let ids=conversationUI.captions.get(key)||[];
    const unchanged=ids.length && ids.map(id=>state.turns.find(t=>t.id===id)?.text||"").join("")===caption.text;
    if(unchanged){if(caption.role==="user"&&caption.final&&conversationUI.applied!==conversationUI.revision)scheduleWorkflow();return;}
    const chunks=caption.text.match(/[\s\S]{1,6000}/g)||[];
    const other=state.turns.filter(t=>!ids.includes(t.id));
    if(other.length+chunks.length>400||other.reduce((n,t)=>n+t.text.length,0)+caption.text.length>400000){
      conversationUI.live?.stop();notice("Interview limit reached. Save this session before continuing in a new interview.",true);return;
    }
    chunks.forEach((chunk,i)=>{
      let turn=state.turns.find(t=>t.id===ids[i]);
      if(!turn){turn={id:nextTurnId(),role:caption.role,text:chunk};ids[i]=turn.id;state.turns.push(turn);}else turn.text=chunk;
    });
    conversationUI.captions.set(key,ids);state.version++;state.dirty=true;
    renderTranscript();
    if(conversationUI.view==="transcript"){if(follow)scrollConversation();else if($("jump-latest"))$("jump-latest").hidden=false;}
    if(caption.role==="user"){conversationUI.revision++; if(caption.final)scheduleWorkflow();}
    if(caption.final&&caption.role==="assistant"&&/[?？]/.test(caption.text)&&/file|document|upload/i.test(caption.text)){
      const candidate=(documentController?.exportState().documents||[]).find(document=>document.analysis?.disposition==="needs_reason");
      if(candidate&&/why|reason|look for|relat|help|notice|share|purpose/i.test(caption.text))pendingDocumentReason={id:candidate.id};
    }
    if(caption.final&&caption.role==="user"&&pendingDocumentReason)resolveDocumentPurpose(caption.text);
  }
  function scheduleWorkflow() {
    if(!state.turns.some(t=>t.role==="user")||!state.config?.api_configured)return;
    clearTimeout(conversationUI.flowTimer);
    conversationUI.flowTimer=setTimeout(refreshWorkflow,1000);
  }
  async function refreshWorkflow() {
    if(state.busy){scheduleWorkflow();return;}
    if(conversationUI.flowBusy||conversationUI.applied===conversationUI.revision)return;
    if(!state.turns.some(t=>t.role==="user"))return;
    const revision=conversationUI.revision,generation=state.generation, captured=snapshot();
    conversationUI.flowBusy=true;conversationUI.flowAbort=new AbortController();
    $("workflow-status").textContent="Updating from your latest answers…";$("retry-workflow").hidden=true;
    if($("coverage-update-status"))$("coverage-update-status").textContent="Updating your memo…";
    try{
      const result=await request("/api/workflow",captured,{signal:conversationUI.flowAbort.signal});
      if(generation!==state.generation)return;
      if(revision!==conversationUI.revision)return;
      const workflow=normalizeDraft(result.workflow,captured.turns);
      // Validate the entire snapshot before committing any part; stale replies never overwrite newer evidence.
      const memo=result.memo_findings===undefined ? null : {
        memo_findings:normalizeFindings(result.memo_findings,captured.turns),coverage:normalizeCoverage(result.coverage),
        summary:text(result.summary,6000),focus:text(result.focus,500),parking_lot:strings(result.parking_lot,50)
      };
      conversationUI.workflow=workflow;
      applyProcessTitle(workflow.title);
      if(memo) {Object.assign(state,memo);announceReadiness();}
      conversationUI.applied=revision;state.dirty=true;updateSaveHint();renderCoverage();
      if($("coverage-update-status"))$("coverage-update-status").textContent="Up to date with your conversation";
      renderWorkingMap();$("workflow-status").textContent="Up to date · Changes follow what you tell us.";
    }catch(error){if(generation===state.generation&&error.name!=="AbortError"){
      $("workflow-status").textContent="Update paused. Your conversation and previous flow are retained.";$("retry-workflow").hidden=false;
      if($("coverage-update-status"))$("coverage-update-status").textContent="Update paused · retry in Workflow";
    }}finally{
      if(generation===state.generation){conversationUI.flowBusy=false;conversationUI.flowAbort=null;if(revision!==conversationUI.revision)scheduleWorkflow();}
    }
  }
  function workflowGapSummary(graph) {
    if(!graph || !Array.isArray(graph.steps) || graph.steps.length<2)return "";
    const connected=new Set();
    for(const edge of graph.connections||[]) if(edge.from!==edge.to){connected.add(edge.from);connected.add(edge.to);}
    const isolated=graph.steps.filter(step=>!connected.has(step.id));
    if(!isolated.length)return "";
    return `Connections need clarification: ${isolated.map(step=>`${step.title||"Untitled step"} (${step.id})`).join(", ")}. Confirm how these steps fit, if at all.`;
  }
  function renderWorkingMap() {
    const gap=$("workflow-gaps"),message=workflowGapSummary(conversationUI.workflow);
    if(gap){gap.textContent=message;gap.hidden=!message;}
    renderMap($("live-workflow"),conversationUI.workflow);
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
          throw new Error(message || "The interviewer is unavailable. Please try again.");
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
    auxiliaryVoiceState="idle";gpfsPresence?.setAudio({input:0,output:0,inputActive:false,outputActive:false});updatePresence();
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
    auxiliaryVoiceState="processing";updatePresence();
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
      operation.audio.addEventListener("playing",()=>{if(version===state.speechVersion){auxiliaryVoiceState="speaking";updatePresence();}});
      operation.audio.addEventListener("waiting",()=>{if(version===state.speechVersion){auxiliaryVoiceState="processing";updatePresence();}});
      operation.audio.addEventListener("pause",()=>{if(version===state.speechVersion){auxiliaryVoiceState="idle";updatePresence();}});
      operation.audio.addEventListener("error",()=>{if(version===state.speechVersion){stopSpeaking();notice("The AI voice audio could not play. Try Listen again or choose another voice.",true);}},{once:true});
      await operation.audio.play();
      if(version===state.speechVersion)$("voice-status").textContent=`Speaking · ${voice.label}`;
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
    auxiliaryVoiceState="processing";updatePresence();
    $("stop-speaking").hidden = false;
    $("stop-speaking").textContent = "Stop voice";
    utterance.onend = () => {
      if (version === state.speechVersion) {state.utterance = null;auxiliaryVoiceState="idle";updatePresence(); $("stop-speaking").hidden = true;}
    };
    utterance.onstart=()=>{if(version===state.speechVersion){auxiliaryVoiceState="speaking";updatePresence();}};
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
  function snapshot(action = "answer") {
    return {context:clone(state.context),turns:clone(state.turns),session:{closure_requested:action === "close"},...(documentController?.exportState().scope?{document_scope:documentController.exportState().scope}:{})};
  }
  function memoComplete(findings=state.memo_findings) {
    return findings.length===TOPICS.length && TOPICS.every(([key])=>findings.filter(f=>f.key===key&&["captured","not_applicable"].includes(f.status)).length===1);
  }
  function announceReadiness() {
    const complete=memoComplete();
    if(complete&&!conversationUI.readyAnnounced) notice("All 11 memo topics are captured. There is enough detail to review the process; you can keep talking.",false,"ready");
    if(!complete&&noticeKind==="ready") {clearTimeout(noticeTimer);$("global-notice").hidden=true;}
    conversationUI.readyAnnounced=complete;
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
    if($("interview-error")?.dataset.errorKind==="capture")$("interview-error").hidden=true;
    renderTranscript();
    scrollConversation();
    announceReadiness();
    if ($("speak-questions").checked && !conversationUI.live?.active) speak(result.question, true);
  }
  async function startInterview(event) {
    event.preventDefault();
    if (state.busy || state.recording || state.transcribing || state.requestingMic) return;
    if (state.started) {
      if (!confirm("Start a new interview? Unsaved conversation and draft edits in this tab will be cleared. Save the session first if you want to keep them.")) return;
      const existing = state.context;
      clearState(existing);
      $("process-name").focus();
      notice("Update the context, then select Start interview.");
      return;
    }
    if (!$("context-form").reportValidity()) return;
    state.context = readContext();
    state.example = false;
    ensureConversation();
    updateControls();$("start-live").focus();
  }

  async function sendAnswer(event) {
    event.preventDefault();
    const answer = $("answer-text").value.trim();
    if (!answer || !state.started || state.busy || state.recording || state.transcribing || state.requestingMic) return;
    if (answer.length > 6000 || state.turns.length >= 399 || state.turns.reduce((n,t) => n+t.text.length,answer.length) > 400000) {notice("This answer or interview exceeds the prototype’s technical size limit. Shorten the answer, or create a draft and save this session.", true); return;}
    stopSpeaking();
    const generation = state.generation;
    const turn = {id: nextTurnId(), role: "user", text: answer};
    state.turns.push(turn);
    conversationUI.revision++;
    state.version++;
    state.dirty = true;
    $("answer-text").value = "";
    renderTranscript();
    setBusy(true);
    scrollConversation();
    try {
      if(pendingDocumentReason)await resolveDocumentPurpose(answer);
      const result = await request("/api/interview", {...snapshot(), action: "answer"});
      if (generation === state.generation) {applyInterview(result);$("retry-question").hidden=true;}
    } catch (error) {
      if (generation !== state.generation) return;
      $("retry-question").hidden=false;
      renderTranscript();
      notice("Your answer is kept in the conversation. The next question could not be prepared. Continue with more detail, or select Retry question.", true);
    } finally {
      if (generation === state.generation) {setBusy(false);scheduleWorkflow();$("answer-text").focus();}
    }
  }
  async function retryQuestion() {
    if(state.busy||conversationUI.live?.active)return;
    const generation=state.generation;setBusy(true);
    try{const result=await request("/api/interview",{...snapshot(),action:"answer"});if(generation===state.generation){applyInterview(result);$("retry-question").hidden=true;}}
    catch(error){if(generation===state.generation)notice(error.message+" Your answers remain in the conversation.",true);}
    finally{if(generation===state.generation)setBusy(false);}
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
        gpfsPresence?.setAudio({input:Math.min(1,Math.max(0,(rms-.006)/.12)),output:0,inputActive:rms>.009,outputActive:false});
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
    gpfsPresence?.setAudio({input:0,output:0,inputActive:false,outputActive:false});
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
  // Explicit uncertainty is a conservative veto, not proof that other answers
  // are complete. This also protects reopened interviews saved by older versions.
  const uncertainMemo = /\b(?:unknown|tbd|unclear|uncertain|unsure|unconfirmed|maybe|perhaps|possibly|probably|likely|might|guess(?:ed|ing)?|assum(?:e|es|ed|ing|ption|ptions)|conflicting|disagree(?:ment|s|d)?|(?:i|we)\s+(?:think|believe)|(?:do(?:es)?\s+not|don['’]t|doesn['’]t)\s+know|(?:cannot|can['’]t|unable\s+to)\s+(?:identify|say|confirm|determine|tell|establish)|not\s+(?:yet\s+)?(?:sure|certain|clear|known|confirmed|established)|(?:needs?|requires?|pending|awaiting)\s+(?:further\s+)?(?:clarification|confirmation)|to\s+be\s+(?:confirmed|clarified|determined))\b/i;
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
      const answer=text(item?.answer,12000)||"UNKNOWN / TBD — not established in the interview.";
      const evidence_turns=evidenceSources(item?.evidence_turns||[],sourceTurns);
      let status=["partial","captured","not_applicable"].includes(item?.status)?item.status:"unknown";
      if (["captured","not_applicable"].includes(status) && (!evidence_turns.length || uncertainMemo.test(answer) || evidence_turns.some(id=>uncertainMemo.test(sourceTurns.find(t=>t.role==="user"&&t.id===id)?.text||"")))) status="partial";
      return {key,status,answer,evidence_turns};
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
    if (conversationUI.live?.active) {notice("End live voice before creating the review draft.");return;}
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
      if($("review-error"))$("review-error").hidden=true;
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
  function renderReport() {
    const root=$("report-content"),d=state.draft;
    if(!root)return;
    root.replaceChildren();if(!d)return;
    root.append(el("h1","report-title",d.title||state.context?.process_name||"Business process"));
    root.append(el("p","report-status","Current-practice draft · Process owner review required"));
    if(state.example)root.append(el("p","report-warning","Synthetic example — fictional process data."));
    if(state.draftVersion!==state.version)root.append(el("p","report-warning","The interview has changed since this draft was created. Reconcile new answers before approval."));
    const list=(parent,values,empty="Not established in this interview.")=>{const ul=el("ul");(values?.length?values:[empty]).forEach(value=>ul.append(el("li","",value)));parent.append(ul);};
    const fields=(parent,pairs)=>{const dl=el("dl","report-fields");pairs.forEach(([label,value])=>{dl.append(el("dt","",label),el("dd","",value||"UNKNOWN / TBD"));});parent.append(dl);};
    const contents=$("report-contents");contents?.replaceChildren(el("option","","Jump to section…"));
    const section=(title)=>{const part=el("section","report-section");part.id=`report-section-${root.querySelectorAll(".report-section").length+1}`;part.tabIndex=-1;part.append(el("h2","",title));root.append(part);if(contents){const option=el("option","",title);option.value=part.id;contents.append(option);}return part;};
    let part=section("1. Business context");
    fields(part,[["Process",state.context?.process_name],["Process owner / role",state.context?.process_owner],["Interview objective",state.context?.objective],["Supplied context and material",state.context?.background]]);
    part=section("2. Overview and boundaries");part.append(el("p","",d.overview));fields(part,[["Trigger / starting condition",d.trigger]]);part.append(el("h3","","Inputs"));list(part,d.inputs);part.append(el("h3","","Outputs"));list(part,d.outputs);
    part=section("3. Memo foundation");
    (d.memo_summary||[]).forEach(f=>{const item=el("section","report-finding");item.append(el("h3","",MEMO_HEADINGS[f.key]||f.key),el("span","report-finding-status",f.status.replaceAll("_"," ")),el("p","",f.answer),evidenceRow(f.evidence_turns));part.append(item);});
    part=section("4. Detailed business process");
    (d.steps||[]).forEach((step,i)=>{const item=el("section","report-step");item.append(el("h3","",`${i+1}. ${step.title} · ${step.id}`),el("p","",step.description));fields(item,[["Owner / role",step.actor],["System / tool",step.system],["Type",step.type],["Input",step.input],["Output",step.output],["Completion criteria",step.completion_criteria],["Next handoff",step.handoff]]);item.append(evidenceRow(step.evidence_turns));part.append(item);});
    part=section("5. Decisions, branches and connections");
    if(!d.connections?.length)part.append(el("p","","No connections established."));
    (d.connections||[]).forEach(c=>{const item=el("div","report-connection");item.append(el("p","",`${c.from} → ${c.to}${c.label?" · "+c.label:""}`),evidenceRow(c.evidence_turns||[]));part.append(item);});
    part=section("6. Work item lifecycles");
    if(!d.lifecycle_items?.length)part.append(el("p","","UNKNOWN / TBD — no lifecycle established."));
    (d.lifecycle_items||[]).forEach(item=>{part.append(el("h3","",item.item));for(const [label,key] of [["Stages","stages"],["Locations","locations"],["Handoffs","handoffs"]]){part.append(el("h4","",label));list(part,item[key]);}part.append(evidenceRow(item.evidence_turns));});
    part=section("7. Variations and boundaries");
    if(!d.variations?.length)part.append(el("p","","No variations established; this does not confirm there are none."));
    (d.variations||[]).forEach((item,i)=>{part.append(el("h3","",`Variation ${i+1}`));fields(part,[["Applies to",item.applies_to],["Difference",item.difference],["Reason",item.reason],["Cost / effort",item.cost],["Charging / billing",item.charging],["Removability / standardization",item.removability],["Boundary",item.boundary.replaceAll("_"," ")],["Boundary reason",item.boundary_reason]]);part.append(evidenceRow(item.evidence_turns));});
    for(const [heading,values,empty] of [["8. Exceptions and recovery",d.exceptions],["9. Controls and checks",d.controls],["10. Open questions",d.open_questions,"No open questions recorded."],["11. Validation notes",d.validation_notes],["12. Parked topics",state.parking_lot,"No topics parked."]]){part=section(heading);list(part,values,empty);}
    part=section("13. Complete interview evidence");part.append(el("p","report-evidence-note","The participant’s account and supplied context are evidence, not independent verification. AI questions are retained for conversational context."));
    state.turns.forEach(turn=>{part.append(el("h3","",`${turn.id} · ${turn.role==="user"?"Process participant":"AI interviewer"}`),el("p","report-transcript",turn.text));});
    const files=documentController?.exportState().documents||[];
    if(files.length){
      part=section("14. Supporting files and document review");
      part.append(el("p","report-evidence-note","Document claims and AI interpretations are reference material, not participant-confirmed process facts. Originals remain on this computer; saved interviews contain references, not the original files."));
      for(const file of files){
        const analysis=file.analysis||{};part.append(el("h3","",file.name));
        fields(part,[["Status",analysis.disposition||file.status],["Indexed units",`${file.coverage?.indexed_units||0} / ${file.coverage?.total_units||0}`],["Reviewed sections",`${analysis.reviewed_chunks||0} / ${analysis.total_chunks||file.chunk_count||0}`],["Document summary",analysis.summary||"Review is pending."],["Purpose supplied",analysis.purpose||"Not specified"]]);
        const open=el("button","text-button","Open file notes and sources ↗");open.type="button";open.addEventListener("click",()=>documentController?.open(file.id));part.append(open);
        const limitations=[...(file.coverage?.limitations||[]),...(analysis.limitations||[])];if(file.error)limitations.push(file.error);if(analysis.error)limitations.push(analysis.error);
        if(limitations.length){part.append(el("h4","","Reading limitations"));list(part,[...new Set(limitations)]);}
        if(analysis.observations?.length){part.append(el("h4","","Unconfirmed document observations"));list(part,analysis.observations.map(item=>`${item.text} — ${(item.sources||[]).map(source=>source.label||source.source_id).join("; ")}`));}
        const questions=analysis.questions?.length?analysis.questions:analysis.question?[{text:analysis.question,sources:analysis.sources||[]}]:[];
        if(questions.length){part.append(el("h4","","Questions to explore"));list(part,questions.map(item=>`${item.text} — ${(item.sources||[]).map(source=>`${source.label||file.name} (${source.source_id})`).join("; ")}`));}
        if(analysis.sources?.length){part.append(el("h4","","Document sources"));list(part,analysis.sources.map(source=>`${source.label||file.name} (${source.source_id})`));}
      }
    }
    refreshReadingSearch("report",false);
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
  function jumpToTurn(id,remember=true) {
    if(remember)rememberSourceOrigin();
    setMemoSheet(false,false);
    tab("interview");
    if (id === "context") {
      revealContext();
      const context = $("context-details");
      context.scrollIntoView({behavior:"smooth",block:"center"});
      context.tabIndex = -1;
      context.focus({preventScroll:true});
      if($("settings-source-return"))$("settings-source-return").hidden=false;
      notice("This step cites the interview context. Validate it with the process owner.");
      return;
    }
    const turn = document.getElementById(`turn-${id}`);
    if (!turn) { notice(`Source ${id} is not present in this session. Validate this step with the process owner.`, true); return; }
    selectConversationView("transcript");
    revealAncestors(turn);
    turn.scrollIntoView({behavior: "smooth", block: "center"});
    turn.classList.remove("highlight");
    void turn.offsetWidth;
    turn.classList.add("highlight");
    turn.tabIndex = -1;
    turn.focus({preventScroll: true});
    if($("source-return"))$("source-return").hidden=!sourceOrigin;
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
    if(id==="review-report")renderReport();
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
    if (turn.document_event) return "File update";
    const position = state.turns.filter(item => item.role === turn.role&&!item.document_event).findIndex(item => item.id === id) + 1;
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
  function evidenceRow(ids = [], beforeJump = null) {
    const evidence = el("div","evidence-row");
    evidence.append(el("span","","Sources:"));
    if (!ids.length) evidence.append(el("span","needs-evidence","UNKNOWN / TBD · needs validation"));
    ids.forEach(id => {
      const source = el("button","evidence-link",sourceCaption(id));
      source.title = `Source: ${id}`;
      source.dataset.sourceTurn=id;
      source.setAttribute("aria-label",`Read ${sourceCaption(id)}`);
      source.addEventListener("click",() => {rememberSourceOrigin();beforeJump?.();jumpToTurn(id,false);});
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
  function showWorkflowStep(step, containerId, refresh=false) {
    const dialog=$("workflow-step-dialog"),body=$("workflow-step-content");if(!dialog)return;
    if(!refresh)workflowDetailReturn=document.activeElement;
    workflowDetailSource={containerId,stepId:step.id};
    $("workflow-step-title").textContent=step.title||step.id;
    $("workflow-step-kind").textContent=`${step.id} · ${step.type==="decision"?"Decision":"Activity"}`;
    body.replaceChildren(el("p","",step.description||"Detail has not been established yet."));
    const dl=el("dl","report-fields");
    for(const [label,value] of [["Owner / role",step.actor],["System / tool",step.system],["Input",step.input],["Output",step.output],["Completion",step.completion_criteria],["Handoff",step.handoff]])dl.append(el("dt","",label),el("dd","",value||"Not established"));
    body.append(dl,evidenceRow(step.evidence_turns||[],()=>{workflowDetailReturn=null;dialog.close();}));
    const follow=el("button","button secondary small","Follow this path");follow.type="button";follow.addEventListener("click",()=>{workflowDetailReturn=null;dialog.close();workflowCanvases.get(containerId)?.followPath(step.id);});body.append(follow);
    if(!dialog.open)dialog.showModal();
  }
  function updateCanvasControls(id,info) {
    const prefix=id==="live-workflow"?"workflow":"map";
    if($(prefix+"-zoom-label"))$(prefix+"-zoom-label").textContent=`${Math.round(info.scale*100)}%`;
    for(const suffix of ["zoom-out","zoom-in","fit"])if($(prefix+"-"+suffix))$(prefix+"-"+suffix).disabled=!info.hasGraph;
    if($(prefix+"-direction")){$(prefix+"-direction").disabled=!info.hasGraph;$(prefix+"-direction").textContent=info.direction==="DOWN"?"Vertical":"Horizontal";$(prefix+"-direction").setAttribute("aria-label",info.direction==="DOWN"?"Vertical layout. Switch to horizontal layout":"Horizontal layout. Switch to vertical layout");$(prefix+"-direction").title=$(prefix+"-direction").getAttribute("aria-label");}
    updateWorkflowNavigation(id,info);
    const exportButton=$(id==="live-workflow"?"export-working-map":"export-map");
    if(exportButton)exportButton.disabled=!info.hasGraph||Boolean(info.updating)||info.exportReady===false;
  }
  function updateWorkflowNavigation(id,info) {
    const prefix=id==="live-workflow"?"workflow":"map";
    if(!$(prefix+"-navigation"))return;
    const bar=$(prefix+"-navigation"),select=$(prefix+"-step-select"),canvas=workflowCanvases.get(id),steps=canvas?.getSteps?.()||(id==="live-workflow"?conversationUI.workflow:state.draft)?.steps||[],path=info.path||canvas?.getPathNavigation?.();
    bar.hidden=!info.hasGraph;if(bar.hidden)return;
    const selected=path?.current?.id||select.value;
    const stepSignature=JSON.stringify(steps.map(step=>[step.id,step.title]));if(select.dataset.signature!==stepSignature){select.replaceChildren(...steps.map(step=>{const option=el("option","",`${step.id} · ${step.title}`);option.value=step.id;return option;}));select.dataset.signature=stepSignature;}
    if(steps.some(step=>step.id===selected))select.value=selected;
    $(prefix+"-follow").setAttribute("aria-pressed",String(Boolean(path?.following)));$(prefix+"-follow").textContent=path?.following?"Show all":"Follow path";
    for(const [direction,label] of [["previous","← Previous"],["next","Next →"]]){const control=$(prefix+"-path-"+direction),choices=path?.[direction]||[];control.hidden=!path?.following;control.disabled=!choices.length;const signature=JSON.stringify([path?.current?.id,choices]);if(control.dataset.signature!==signature){const placeholder=el("option","",choices.length?label:(direction==="next"?"End of reported path":"Start of reported path"));placeholder.value="";control.replaceChildren(placeholder,...choices.map(choice=>{const option=el("option","",`${choice.label||"Continue"} · ${choice.id}`);option.value=choice.id;return option;}));control.value="";control.dataset.signature=signature;}}
    $(prefix+"-path-status").textContent=path?.following?`${path.current?.title||""}${path.next?.length>1?" · Choose a branch":""}`:"";
  }
  function renderMap(target = null, graph = state.draft) {
    const root = target || $("process-map");
    if(window.CollectorWorkflow){
      if(workflowDetailSource?.containerId===root.id&&$("workflow-step-dialog")?.open){
        const current=graph?.steps.find(step=>step.id===workflowDetailSource.stepId);
        if(current)showWorkflowStep(current,root.id,true);
        else {workflowDetailReturn=null;$("workflow-step-dialog").close();}
      }
      if(!graph?.steps.length){workflowCanvases.get(root.id)?.destroy();workflowCanvases.delete(root.id);root.replaceChildren(el("p","view-empty","Describe what starts the work. Your workflow will take shape here."));updateCanvasControls(root.id,{scale:1,hasGraph:false});return;}
      let canvas=workflowCanvases.get(root.id);
      if(!canvas){canvas=window.CollectorWorkflow.create(root,{onSelectStep:step=>showWorkflowStep(step,root.id),onViewChange:info=>updateCanvasControls(root.id,info)});workflowCanvases.set(root.id,canvas);}
      const generation=state.generation;
      canvas.update(graph).then(applied=>{if(!applied||state.generation!==generation||workflowCanvases.get(root.id)!==canvas)return;const retry=$(root.id==="live-workflow"?"retry-workflow":"map-retry-layout");if(retry?.dataset.layoutRetry){delete retry.dataset.layoutRetry;retry.hidden=true;if(root.id==="live-workflow")$("workflow-status").textContent="Diagram ready · Changes follow what you tell us.";const region=$(root.id==="live-workflow"?"interview-error":"review-error");if(region?.dataset.errorKind==="layout")region.hidden=true;}}).catch(()=>{if(state.generation!==generation||workflowCanvases.get(root.id)!==canvas)return;notice("The diagram could not be laid out. Your captured process is retained. Retry the layout.",true,"layout");const retry=$(root.id==="live-workflow"?"retry-workflow":"map-retry-layout");if(retry){retry.hidden=false;retry.dataset.layoutRetry="true";}if(root.id==="live-workflow")$("workflow-status").textContent="Diagram layout paused. Retry locally; your process is retained.";});
      return;
    }
    root.replaceChildren();
    if (!graph?.steps.length) { root.append(el("p", "muted", "Add process steps to build the map.")); if(!target)applyMapView(); return; }
    const steps = graph.steps;
    const connections = graph.connections;
    const positions = new Map();
    const height = steps.length * 157 + 56;
    const width = 760;
    const svg = svgEl("svg", {xmlns:svgNS, viewBox:`0 0 ${width} ${height}`, width, height, role:"img", "aria-labelledby":`${target ? "working" : "map"}-title ${target ? "working" : "map"}-description`});
    svg.append(svgEl("title", {id:target ? "working-title" : "map-title"}, `Draft process map: ${graph.title || "Untitled process"}`));
    svg.append(svgEl("desc", {id:target ? "working-description" : "map-description"}, steps.map(s => `${s.id}: ${s.title}, owner ${s.actor || "not specified"}`).join(". ")));
    svg.append(svgEl("rect", {width, height, fill:"#ffffff", "aria-hidden":"true"}));
    const defs = svgEl("defs");
    const marker = svgEl("marker", {id:target ? "working-flow-arrow" : "flow-arrow",viewBox:"0 0 10 10",refX:8,refY:5,markerWidth:7,markerHeight:7,orient:"auto-start-reverse"});
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
      const edge=svgEl("path",{d:path,"marker-end":target ? "url(#working-flow-arrow)" : "url(#flow-arrow)"});
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
    if (target) return;
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
    if(workflowCanvases.has("process-map")){workflowCanvases.get("process-map").zoom(delta);return;}
    reviewUI.mapFit = false;
    reviewUI.mapScale = Math.max(.25,Math.min(2,Math.round((reviewUI.mapScale+delta)*100)/100));
    applyMapView();
  }
  function fitMapToWidth() {
    if(workflowCanvases.has("process-map")){workflowCanvases.get("process-map").refresh();return;}
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
    return {workflow:conversationUI.workflow,schema_version:1,saved_at:new Date().toISOString(),context:state.context||readContext(),process_name_manual:state.processNameManual,documents:documentController?.exportState()||null,document_questions_handled:[...documentQuestionsHandled],turns:state.turns,coverage:state.coverage,summary:state.summary,memo_findings:state.memo_findings,focus:state.focus,parking_lot:state.parking_lot,closure:state.closure,draft:state.draft,draft_stale:Boolean(state.draft&&state.draftVersion!==state.version),draft_edited:state.draftEdited,synthetic_example:state.example,unsent_answer:$("answer-text").value,voice_choice:state.voiceChoice,knowledge_process_id:knowledgeUI?.processId||null,knowledge_status:knowledgeUI?.exportReceipt()||null};
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
    const list = (values, empty="Not established in this interview.") => values.length ? values.map(v => `- ${md(v)}`).join("\n") : `- ${md(empty)}`;
    const sources = ids => ids.length ? ids.map(md).join(", ") : "No cited answer — UNKNOWN / TBD";
    const parts = [`# ${md(d.title || state.context?.process_name || "Process procedure")}`, "**DRAFT — process owner review required**", state.example ? "**Synthetic example — fictional process data.**" : "", state.draftVersion !== state.version ? "**The interview has changed since this draft was created. Reconcile the new answers before approval.**" : "",`Final completeness check: ${state.closure.confirmed?"participant confirmed":state.closure.asked?"asked; participant confirmation pending":"not yet requested"}.`,"## Contents","- [Business context](#business-context)\n- [Overview](#overview)\n- [Memo foundation](#memo-foundation)\n- [Procedure](#procedure)\n- [Process connections](#process-connections)\n- [Item lifecycles](#item-lifecycles)\n- [Variations and boundaries](#variations-and-boundaries)\n- [Exceptions](#exceptions)\n- [Controls](#controls)\n- [Open questions](#open-questions)\n- [Validation notes](#validation-notes)\n- [Parked topics](#parked-topics)\n- [Interview evidence](#interview-evidence)","## Business context",`- Process: ${md(state.context?.process_name||d.title)}`,`- Process owner / role: ${md(state.context?.process_owner||"UNKNOWN / TBD")}`,"### Interview objective",md(state.context?.objective||"Not specified."),"### Supplied context and material",md(state.context?.background||"No additional context supplied."),"## Overview",md(d.overview),"## Memo foundation"];
    d.memo_summary.forEach(finding => parts.push(`### ${md(MEMO_HEADINGS[finding.key]||finding.key)}`,`Status: ${md(finding.status.replaceAll("_"," "))}`,md(finding.answer),`Source turns: ${sources(finding.evidence_turns)}`));
    parts.push("## Trigger",md(d.trigger),"## Inputs",list(d.inputs),"## Outputs",list(d.outputs),"## Procedure");
    d.steps.forEach((s,i) => parts.push(`### ${i+1}. ${md(s.title)} (${md(s.id)})`,`- Owner / role: ${md(s.actor||"UNKNOWN / TBD")}`,`- System / tool: ${md(s.system||"UNKNOWN / TBD")}`,`- Type: ${md(s.type)}`,`- Input: ${md(s.input||"UNKNOWN / TBD")}`,`- Output: ${md(s.output||"UNKNOWN / TBD")}`,`- Completion criteria: ${md(s.completion_criteria||"UNKNOWN / TBD")}`,`- Next handoff: ${md(s.handoff||"UNKNOWN / TBD")}`,"",md(s.description),"",`Source turns: ${sources(s.evidence_turns)}`));
    parts.push("## Process connections",d.connections.length?d.connections.map(c=>`- ${md(c.from)} → ${md(c.to)}${c.label?`: ${md(c.label)}`:""}. Source turns: ${sources(c.evidence_turns||[])}`).join("\n"):"No connections defined.","## Item lifecycles");
    if (!d.lifecycle_items.length) parts.push("UNKNOWN / TBD — no item lifecycles established.");
    d.lifecycle_items.forEach(item => parts.push(`### ${md(item.item)}`,"Stages:",list(item.stages),"Locations:",list(item.locations),"Handoffs:",list(item.handoffs),`Source turns: ${sources(item.evidence_turns)}`));
    parts.push("## Variations and boundaries");
    if (!d.variations.length) parts.push("UNKNOWN / TBD — an empty list does not confirm there are no variations.");
    d.variations.forEach((item,index)=>parts.push(`### Variation ${index+1}`,`- Applies to: ${md(item.applies_to)}`,`- Difference: ${md(item.difference)}`,`- Reason: ${md(item.reason)}`,`- Cost / effort: ${md(item.cost)}`,`- Charging / billing: ${md(item.charging)}`,`- Removability / standardization: ${md(item.removability)}`,`- Boundary: ${md(item.boundary.replaceAll("_"," "))}`,`- Boundary reason: ${md(item.boundary_reason)}`,`Source turns: ${sources(item.evidence_turns)}`));
    parts.push("## Exceptions",list(d.exceptions),"## Controls",list(d.controls),"## Open questions",list(d.open_questions,"No open questions recorded."),"## Validation notes",list(d.validation_notes),"## Parked topics",list(state.parking_lot,"No topics parked."),"## Interview evidence","The following is the interview record, not independent verification of the process. Coverage does not guarantee exhaustiveness.");
    state.turns.forEach(t => parts.push(`### ${md(t.id)} · ${t.role === "user" ? "Process participant" : "AI interviewer"}`, md(t.text)));
    const files=documentController?.exportState().documents||[];
    if(files.length){
      parts.push("## Supporting files and document review","Document claims and AI interpretations are unconfirmed reference material. They do not establish the participant's actual process or memo completeness. Originals remain on this computer; the saved interview contains references, not embedded files.");
      for(const file of files){const a=file.analysis||{};
        parts.push(`### ${md(file.name)}`,`- File reference: ${md(file.id)}`,`- State: ${md(a.disposition||file.status)}`,`- Indexed units: ${file.coverage?.indexed_units||0} / ${file.coverage?.total_units||0}`,`- Reviewed sections: ${a.reviewed_chunks||0} / ${a.total_chunks||file.chunk_count||0}`,`- Purpose: ${md(a.purpose||"Not specified")}`,md(a.summary||"Review is pending."));
        const limitations=[...(file.coverage?.limitations||[]),...(a.limitations||[]),file.error,a.error].filter(Boolean);if(limitations.length)parts.push("#### Reading limitations",list([...new Set(limitations)]));
        const questions=a.questions?.length?a.questions:a.question?[{text:a.question,sources:a.sources||[]}]:[];
        for(const [heading,items] of [["Unconfirmed document observations",a.observations],["Questions to explore",questions]])if(items?.length){parts.push(`#### ${heading}`);items.forEach(item=>parts.push(`- ${md(item.text)}\n  Sources: ${(item.sources||[]).map(source=>`${md(source.label||file.name)} (${md(source.source_id)})`).join("; ")}`));}
        if(a.sources?.length)parts.push("#### Document sources",a.sources.map(source=>`- ${md(source.label||file.name)} (${md(source.source_id)})`).join("\n"));
      }
    }
    return parts.filter(p => p !== "").join("\n\n") + "\n";
  }
  function memoMarkdown() {
    const d=state.draft,md=escapeMarkdown;
    const parts=[`# ${md(state.context?.process_name||d.title)} — process capture memo`,"**CURRENT-PRACTICE DRAFT — process owner review required**",state.example?"**Synthetic example — fictional process data.**":"",`Account confirmation: ${state.closure.confirmed?"participant confirmed":state.closure.asked?"requested; pending":"not yet requested"}. Process owner approval: pending.`,"Sources are the participant’s account and supplied context; they are not independent verification. UNKNOWN / TBD and unreviewed material remain visible gaps."];
    d.memo_summary.forEach((finding,index)=>parts.push(`## ${index+1}. ${md(MEMO_HEADINGS[finding.key]||finding.key)}`,`Status: ${md(finding.status.replaceAll("_"," "))}`,md(finding.answer),`Source: ${finding.evidence_turns.length?finding.evidence_turns.map(md).join(", "):"UNKNOWN / TBD"}`));
    if(d.variations.length){parts.push("## Variation differences");d.variations.forEach((v,index)=>parts.push(`### ${index+1}. ${md(v.applies_to)}`,`- What differs: ${md(v.difference)}`,`- Why: ${md(v.reason)}`,`- What it costs us: ${md(v.cost)}`,`- Do we charge: ${md(v.charging)}`,`- Could it go away: ${md(v.removability)}`,`- Boundary: ${md(v.boundary.replaceAll("_"," "))}. ${md(v.boundary_reason)}`));}
    parts.push("## Questions for the process owner",d.open_questions.length?d.open_questions.map((q,index)=>`${index+1}. ${md(q)}`).join("\n"):"No open questions recorded; the process owner should still review the draft.");
    parts.push("## Detailed business process and evidence",markdown().replace(/^#/gm,"##"));
    return parts.filter(Boolean).join("\n\n")+"\n";
  }
  function canReplaceSession() {
    if (conversationUI.live?.active || conversationUI.status==="closing") {notice("End live voice before replacing the session.");return false;}
    if (state.recording || state.busy || state.transcribing || state.requestingMic) { notice("Finish the current recording or request before replacing the session."); return false; }
    return !state.dirty || confirm("Replace the current session? Unsaved interview text and draft edits will be cleared. Save the session first if you want to keep them.");
  }
  function clearState(context = null) {
    knowledgeUI?.reset();
    voiceEnded=false;
    documentController?.reset();pendingDocumentReason=null;restoringDocuments=false;documentQuestionsHandled.clear();documentVoiceUpdates.clear();
    workflowCanvases.forEach(canvas=>canvas.destroy());workflowCanvases.clear();
    if($("workflow-step-dialog")?.open)$("workflow-step-dialog").close();
    conversationUI.live?.stop({immediate:true});
    clearTimeout(conversationUI.flowTimer);conversationUI.flowAbort?.abort();
    Object.assign(conversationUI,{workflow:null,revision:0,applied:-1,flowBusy:false,flowAbort:null,typing:false,status:"idle",readyAnnounced:false,captions:new Map()});
    selectConversationView("voice");renderWorkingMap();
    if($("workflow-status"))$("workflow-status").textContent="Updates after your answers. Corrections can change the flow.";
    if($("retry-workflow"))$("retry-workflow").hidden=true;
    if ($("foundation-dialog")?.open) closeFoundationTopic(false);
    setMemoSheet(false,false);setInterviewSettings(false,false);
    if($("coverage-update-status"))$("coverage-update-status").textContent="Updates as you share";
    if($("jump-latest"))$("jump-latest").hidden=true;
    stopSpeaking();
    finishRecording(true);
    state.generation++;
    sourceOrigin=null;if($("source-return"))$("source-return").hidden=true;
    if($("settings-source-return"))$("settings-source-return").hidden=true;
    for(const kind of ["transcript","report"]){Object.assign(readingUI[kind],{query:"",matches:[],index:-1});if($(kind+"-search"))$(kind+"-search").value="";}
    for(const id of ["interview-error","review-error"])if($(id))$(id).hidden=true;
    state.version++;
    Object.assign(state,{context,processNameManual:Boolean(context?.process_name),turns:[],coverage:[],summary:"",draft:null,started:false,busy:false,requestingMic:false,transcribing:false,draftVersion:null,draftEdited:false,example:false,dirty:false,memo_findings:[],focus:"",parking_lot:[],closure:{asked:false,confirmed:false}});
    $("answer-text").value = "";
    if($("retry-question"))$("retry-question").hidden=true;
    clearTimeout(noticeTimer);noticeTimer=null;noticeKind="general";
    $("global-notice").hidden = true;
    $("live-status").textContent = "";
    reviewUI.mapScale = 1; reviewUI.mapFit = true;
    selectReviewSection("review-report");
    fillContext(context);
    renderTranscript(); renderDraft(); tab("interview"); closeMenu();
  }
  async function importSession(file) {
    if (!file) return;
    if (!canReplaceSession()) return;
    if (file.size > 16 * 1024 * 1024) { notice("That file is too large. Choose a saved interview smaller than 16 MB.", true); return; }
    let generation=state.generation;
    try {
      const saved = JSON.parse(await file.text());
      if(generation!==state.generation)return;
      if (saved?.schema_version !== 1 || !saved.context || !Array.isArray(saved.turns)) throw new Error("Choose an interview file saved from this app.");
      if (saved.turns.length > 400 || text(saved.context.objective).length > 500 || text(saved.context.background).length > 8000 || (typeof saved.unsent_answer === "string" && saved.unsent_answer.length > 18000)) throw new Error("The session exceeds the prototype’s context, answer, or 400-turn technical limit.");
      const context = {
        process_name:text(saved.context.process_name,500),process_owner:text(saved.context.process_owner,500),objective:text(saved.context.objective,500),background:text(saved.context.background,8000)
      };
      const ids = new Set();
      const turns = saved.turns.map((turn,i) => {
        if (!turn || !["user","assistant"].includes(turn.role) || typeof turn.text !== "string" || typeof turn.id !== "string" || turn.id === "context" || !/^[a-zA-Z0-9_-]{1,40}$/.test(turn.id) || ids.has(turn.id)) throw new Error(`The session has an invalid, reserved, or duplicate turn ID at position ${i+1}.`);
        if (turn.text.length > 6000) throw new Error(`Turn ${turn.id} exceeds the 6,000-character limit.`);
        ids.add(turn.id); return {id:turn.id,role:turn.role,text:turn.text,...(turn.document_event===true?{document_event:true}:{}),...(typeof turn.document_id==="string"&&/^doc_[a-zA-Z0-9_]+$/.test(turn.document_id)?{document_id:turn.document_id}:{})};
      });
      if (turns.reduce((n,t) => n+t.text.length,0) > 400000) throw new Error("The interview text exceeds the prototype’s 400,000-character technical limit.");
      const draft = saved.draft ? normalizeDraft(saved.draft,turns) : null;
      const workflow=saved.workflow?normalizeDraft(saved.workflow,turns):null;
      const findings = normalizeFindings(saved.memo_findings||[],turns);
      const summary = text(saved.summary,6000);
      const focus = text(saved.focus,500);
      const parked = strings(saved.parking_lot,50);
      clearState(context);
      knowledgeUI?.restore(saved.knowledge_process_id,saved.knowledge_status);
      generation=state.generation;
      Object.assign(state,{turns,coverage:normalizeCoverage(saved.coverage),summary,draft,started:turns.length>0,example:saved.synthetic_example===true,draftEdited:saved.draft_edited===true,memo_findings:findings,focus,parking_lot:parked,closure:{asked:saved.closure?.asked===true,confirmed:saved.closure?.confirmed===true}});
      state.processNameManual=saved.process_name_manual===undefined?Boolean(context.process_name):saved.process_name_manual===true;
      (Array.isArray(saved.document_questions_handled)?saved.document_questions_handled:[]).filter(value=>typeof value==="string"&&value.length<160).slice(0,200).forEach(value=>documentQuestionsHandled.add(value));
      if(saved.documents&&documentController){restoringDocuments=true;try{await documentController.restoreState(saved.documents);}finally{if(generation===state.generation)restoringDocuments=false;}}
      if(generation!==state.generation)return;
      if (typeof saved.voice_choice === "string" && saved.voice_choice.length <= 400 && /^(ai:[a-z]+|local:.+)$/.test(saved.voice_choice)) {
        state.voiceChoice=saved.voice_choice;state.voiceChoiceUser=true;populateVoiceOptions();
      }
      conversationUI.workflow=workflow;renderWorkingMap();
      state.draftVersion = draft ? (saved.draft_stale ? state.version-1 : state.version) : null;
      $("answer-text").value = text(saved.unsent_answer);
      renderTranscript(); renderDraft();
      if(state.example)knowledgeUI?.activateExample();
      notice("Interview opened. Continue whenever you’re ready.");
      if (draft) tab("review");
    } catch (error) { if(generation===state.generation)notice(`Could not open session: ${error.message}`, true); }
  }
  function loadExample() {
    if (!canReplaceSession()) return;
    clearState({process_name:"Invoice approval and payment handoff",process_owner:"Accounts payable manager",objective:"Document invoice intake, checks, decisions, exceptions and handoff to Treasury.",background:"Synthetic example only. All names, roles, systems, amounts and process details are fictional."});
    state.example = true;
    state.started = true;
    state.turns = [
      {id:"t001",role:"assistant",text:"What process are we documenting, and who is accountable for it?"},
      {id:"t002",role:"user",text:"This is invoice approval and payment handoff, also called AP invoice sign-off. The accounts payable manager is accountable from supplier receipt through Treasury's acceptance of the approved payment package. Treasury's payment execution is a separate process. The purpose is to send accurate, authorized supplier invoices to Treasury without paying the same invoice twice."},
      {id:"t003",role:"assistant",text:"What starts the work and what happens when an invoice arrives?"},
      {id:"t004",role:"user",text:"A supplier email to the shared AP mailbox starts a case. Each business day by 10 a.m. the AP analyst saves the invoice in the invoice folder and enters supplier, invoice number, amount and receipt date in the invoice register with status Received. The analyst uses the register to route the case into the duplicate check."},
      {id:"t005",role:"assistant",text:"How is a duplicate treated?"},
      {id:"t006",role:"user",text:"The AP analyst searches the invoice register for the same supplier and invoice number. A matching earlier invoice is a duplicate: the analyst links the two entries, sends the supplier a duplicate notice, marks the new entry Duplicate closed, and ends that case. If there is no match, the analyst marks it New and starts the purchase-order and receipt match."},
      {id:"t007",role:"assistant",text:"What is checked and how are mismatches resolved?"},
      {id:"t008",role:"user",text:"For a new invoice, the AP analyst compares supplier, amount and line items with the purchase order in the purchasing system and receipt in the receiving register. The analyst records the outcome in the invoice register. A complete match goes to the value decision. For a mismatch the analyst marks Hold and opens a case in the exception log, sends the buyer the difference, and follows up daily. The buyer obtains a corrected invoice or receiving record, records the resolution in the exception log, and returns it to AP. The analyst repeats the match before the hold is released."},
      {id:"t009",role:"assistant",text:"Describe the approval routes and any extra checks."},
      {id:"t010",role:"user",text:"The AP analyst checks the invoice value in the register. Below $50,000 the matched invoice goes directly to the department manager. At $50,000 or above, the controller first checks the matched package in the invoice folder and records an approve or reject decision in the approval register. A controller approval goes to the department manager; a controller rejection goes to the correction route. The approval matrix requires this threshold. This extra controller review adds one business day of staff effort, is included in the existing AP service with no separate charge, and remains mandatory for high-value invoices. Both routes are variations of the same invoice process."},
      {id:"t011",role:"assistant",text:"What happens with the manager's decision and a rejected invoice?"},
      {id:"t012",role:"user",text:"The department manager reviews the matched invoice and purchase order from the invoice folder through the approval portal and records Approve or Reject. For either controller or manager rejection, the AP analyst records the reason in the exception log, sends it to the buyer, and sets status Correction required. The buyer resolves the reason with the supplier or receiving department and returns corrected documents to AP. The analyst then repeats the purchase-order and receipt match; the invoice follows the value and approval decisions again."},
      {id:"t013",role:"assistant",text:"How does the process finish after approval?"},
      {id:"t014",role:"user",text:"After manager approval, the AP analyst saves the manager decision and any controller decision with the invoice and purchase order in the invoice folder, marks the register Ready for Treasury, and sends the package link through the Treasury queue. A Treasury analyst checks that the package link opens and records Accepted in the queue. AP marks the case Handed off and closes it when that acceptance is recorded. The package and register remain available as the handoff evidence."},
      {id:"t015",role:"assistant",text:"What controls and supporting proof are retained?"},
      {id:"t016",role:"user",text:"The duplicate search, three-way match, value threshold and manager approval are required controls. The controller review is required at the high-value threshold. The AP analyst prepares the package, while the department manager approves it; the controller separately reviews high-value items. The register, exception log, approval register, portal decisions and Treasury acceptance provide the evidence for each check and handoff."},
      {id:"t017",role:"assistant",text:"How are delays and escalation handled?"},
      {id:"t018",role:"user",text:"The AP analyst checks open holds and rejections each business day. If a buyer has not supplied corrected material by the end of the second business day, the analyst escalates the exception log entry to the AP manager. The manager assigns a backup buyer and records the assignment in the log; the backup returns the correction to AP for the same recheck. Standard matched invoices target handoff within two business days, and high-value invoices target three business days."},
      {id:"t019",role:"assistant",text:"What are the main pain points and their effects?"},
      {id:"t020",role:"user",text:"The analyst copies invoice details from email into the register and follows up on exceptions manually. These activities consume about fifteen minutes of staff effort per invoice and are the main reported friction. Waiting for corrected documents is the main source of delay; the team tracks overdue cases in the exception log."},
      {id:"t021",role:"assistant",text:"What is the impact if the work fails or is delayed?"},
      {id:"t022",role:"user",text:"A duplicate payment can cause cash loss and recovery work. An incorrect or unapproved invoice can cause a supplier dispute or inaccurate payment. A late handoff can delay supplier payment. The AP manager reviews these risks with the team each month using the exception log."},
      {id:"t023",role:"assistant",text:"What existing materials guide or document this work?"},
      {id:"t024",role:"user",text:"The AP operating procedure describes the steps and escalation. The invoice register template, exception log template, approval matrix, purchase order, receiving register, portal decision record and Treasury queue receipt document the work. The AP manager maintains the procedure and templates."},
      {id:"t025",role:"assistant",text:"Is there anything else needed to understand this process?"},
      {id:"t026",role:"user",text:"That covers the process from supplier email to Treasury acceptance, including duplicate closure, mismatch rework, the high-value approval route, manager rejection, escalation and the evidence retained. Treasury executes payment as a separate process."}
    ];
    state.memo_findings = normalizeFindings([
      {key:"name",status:"captured",answer:"Invoice approval and payment handoff, also AP invoice sign-off; from supplier email through Treasury acceptance. Treasury payment execution is separate.",evidence_turns:["t002","t026"]},
      {key:"purpose",status:"captured",answer:"Provide Treasury with accurate, authorized supplier invoices while preventing duplicate payments.",evidence_turns:["t002"]},
      {key:"trigger",status:"captured",answer:"A supplier email to the shared AP mailbox starts a case; the analyst logs invoices by 10 a.m. each business day.",evidence_turns:["t004"]},
      {key:"completion",status:"captured",answer:"A duplicate closes when linked, notified and marked Duplicate closed. An approved case closes when Treasury records Accepted and AP marks it Handed off.",evidence_turns:["t006","t014"]},
      {key:"accountable",status:"captured",answer:"The accounts payable manager is accountable for the end-to-end result through Treasury acceptance.",evidence_turns:["t002"]},
      {key:"lifecycle",status:"captured",answer:"Invoices move through received, duplicate check, match or hold/rework, value and approval decisions, ready for Treasury, accepted and handed off; a duplicate closes separately. Records pass among AP, buyer, controller, manager and Treasury.",evidence_turns:["t004","t006","t008","t010","t012","t014"]},
      {key:"checks",status:"captured",answer:"Duplicate search, three-way match, high-value controller review, manager approval and retained decision/acceptance evidence; preparation and approval are performed by separate roles.",evidence_turns:["t016"]},
      {key:"variations",status:"captured",answer:"Invoices of $50,000 or more receive a controller review before manager approval; lower-value invoices go directly to the manager. The variation adds one business day and no separate charge.",evidence_turns:["t010"]},
      {key:"pain_points",status:"captured",answer:"Manual copying and follow-up take about fifteen minutes of staff effort per invoice; waiting for corrections delays cases.",evidence_turns:["t020"]},
      {key:"risk",status:"captured",answer:"Duplicate payment risks cash loss and recovery work; inaccurate or unauthorized payment can cause supplier disputes; delays can delay payment.",evidence_turns:["t022"]},
      {key:"materials",status:"captured",answer:"AP procedure, invoice and exception templates, approval matrix, purchase order, receiving register, portal decisions and Treasury queue receipts; the AP manager maintains the procedure and templates.",evidence_turns:["t024"]}
    ],state.turns);
    state.coverage = state.memo_findings.map(f=>({key:f.key,label:TOPICS.find(([key])=>key===f.key)[1],status:"covered"}));
    state.focus = "Complete account ready for process-owner review";
    state.summary = "AP receives and logs supplier invoices, closes duplicates, resolves mismatches through buyer rework, applies controller review at the high-value threshold, obtains manager approval, and closes after Treasury accepts the documented handoff.";
    const step=(id,title,type,actor,system,description,input,output,completion_criteria,handoff,evidence_turns)=>({id,title,type,actor,system,description,input,output,completion_criteria,handoff,evidence_turns});
    const steps=[
      step("S1","Receive and register invoice","activity","AP analyst","Shared AP mailbox, invoice folder and invoice register","Save the supplier invoice and record its identifying details by 10 a.m. each business day.","Supplier invoice email and attachment","Invoice filed and register entry marked Received","Supplier, invoice number, amount and receipt date are recorded and the file is saved","AP analyst moves the registered invoice to the duplicate check",["t004"]),
      step("S2","Is this a duplicate invoice?","decision","AP analyst","Invoice register","Search for an earlier entry with the same supplier and invoice number.","Received invoice and supplier/invoice number","Duplicate or new classification","Register search establishes whether a matching earlier entry exists","Duplicate goes to closure; new invoice goes to the three-way match",["t006"]),
      step("S3","Close duplicate case","activity","AP analyst","Invoice register and supplier email","Link the new and earlier entries, notify the supplier and close the new case.","Duplicate classification and earlier register entry","Linked entry, supplier notice and Duplicate closed status","Entries are linked, notice sent and new case marked Duplicate closed","Case ends; supplier receives the duplicate notice",["t006"]),
      step("S4","Do invoice, order and receipt match?","decision","AP analyst","Purchasing system, receiving register and invoice register","Compare supplier, amount and line items on the invoice, purchase order and receiving record.","New or corrected invoice, purchase order and receiving record","Match or mismatch decision","All three records are compared and the outcome recorded for routing","Match goes to value decision; mismatch goes to buyer correction",["t008"]),
      step("S5","Resolve mismatch and release hold","activity","AP analyst and buyer; AP manager for escalation","Invoice register and exception log","Record the difference, follow up daily and receive corrected material; escalate after two business days and use the assigned backup buyer when required.","Mismatch details, invoice, purchase order and receiving record","Corrected invoice or receiving record and documented exception resolution","Buyer returns corrected material and the resolution is recorded in the exception log","Buyer returns corrected material to AP, which repeats the match before releasing the hold",["t008","t018"]),
      step("S6","Does the value require controller review?","decision","AP analyst","Invoice register and approval matrix","Route matched invoices by the $50,000 value threshold.","Matched invoice and recorded amount","Standard or high-value route","Amount is compared with the threshold","Below $50,000 goes to manager; $50,000 or above goes to controller",["t010","t024"]),
      step("S7","Review high-value invoice","decision","Controller","Approval register and invoice folder","Review the matched high-value package and record an approval or rejection.","Matched invoice package of $50,000 or more","Controller approval or rejection recorded","Controller records the decision in the approval register","Approval goes to the manager; rejection goes to AP correction",["t010"]),
      step("S8","Approve or reject invoice","decision","Department manager","Approval portal and invoice folder","Review the matched invoice and purchase order and record the decision.","Matched invoice and purchase order, with controller approval for high-value items","Manager approval or rejection in the portal","Manager records Approve or Reject","Approval goes to AP for package handoff; rejection goes to correction",["t010","t012"]),
      step("S9","Correct a rejected invoice","activity","AP analyst and buyer","Exception log and supplier or receiving communications","Record the rejection, send the reason to the buyer and obtain corrected documents for another match.","Controller or manager rejection and its reason","Correction required status, documented reason and corrected documents","Reason is logged and corrected documents are returned to AP","Buyer returns the correction to AP for matching and a fresh approval route",["t012"]),
      step("S10","Save approvals and send package","activity","AP analyst","Invoice folder, invoice register and Treasury queue","File approval evidence, mark the invoice ready and send the package link to Treasury.","Manager approval, controller approval when required, invoice and purchase order","Filed package, Ready for Treasury status and queue handoff","Required decisions are filed and the package link is sent in the Treasury queue","Treasury analyst receives the package link for acceptance",["t014","t016"]),
      step("S11","Accept handoff and close case","activity","Treasury analyst and AP analyst","Treasury queue and invoice register","Treasury opens the package link and records acceptance; AP closes its case.","Treasury queue package link and register entry","Treasury Accepted receipt and AP Handed off status","Treasury records Accepted and AP marks the case Handed off","AP case closes; Treasury proceeds with its separate payment process",["t014","t026"])
    ];
    const edge=(from,to,label,evidence_turns)=>({from,to,label,evidence_turns});
    const connections=[
      edge("S1","S2","Registered",["t004","t006"]),edge("S2","S3","Duplicate",["t006"]),edge("S2","S4","New",["t006","t008"]),
      edge("S4","S5","Mismatch",["t008"]),edge("S5","S4","Corrected; recheck",["t008","t018"]),edge("S4","S6","Match",["t008","t010"]),
      edge("S6","S7","$50,000 or more",["t010"]),edge("S6","S8","Below $50,000",["t010"]),edge("S7","S8","Controller approves",["t010"]),
      edge("S7","S9","Controller rejects",["t010","t012"]),edge("S8","S9","Manager rejects",["t012"]),edge("S9","S4","Corrected; recheck",["t012"]),
      edge("S8","S10","Manager approves",["t012","t014"]),edge("S10","S11","Package sent to Treasury",["t014"])
    ];
    state.draft = normalizeDraft({
      title:"Invoice approval and payment handoff — current-state procedure",
      overview:"Fictional current-state process from supplier email through duplicate closure or Treasury acceptance. Treasury executes payment separately.",
      trigger:"Supplier invoice email arrives in the shared AP mailbox.",
      inputs:["Supplier invoice email and invoice","Purchase order","Receiving record","Approval matrix"],
      outputs:["Duplicate case closed with supplier notice","Approved package accepted by Treasury with AP case marked Handed off"],
      memo_summary:state.memo_findings,
      lifecycle_items:[{item:"Supplier invoice case",stages:["Received and registered","Duplicate closed or matched","Hold and corrected when mismatched","Value-routed and approved","Ready for Treasury","Treasury accepted and AP handed off"],locations:["Shared AP mailbox","Invoice folder","Invoice register","Purchasing system","Receiving register","Exception log","Approval register and portal","Treasury queue"],handoffs:["Supplier to AP","AP to buyer for corrections and back to AP","AP to controller for high-value review","AP to department manager","AP to Treasury"],evidence_turns:["t004","t006","t008","t010","t012","t014"]}],
      variations:[{applies_to:"Invoices of $50,000 or more",difference:"Controller reviews the matched package before manager approval; lower-value items go directly to the manager.",reason:"The approval matrix requires controller review at the threshold.",cost:"One extra business day of staff effort.",charging:"Included in the existing AP service; no separate charge.",removability:"Mandatory for high-value invoices under the approval matrix.",boundary:"variation",boundary_reason:"Both routes share the same intake, matching, manager approval and Treasury handoff.",evidence_turns:["t010"]}],
      steps,connections,
      exceptions:["Duplicates are linked, notified and closed without entering the payment route.","Mismatches and rejected invoices return to the buyer for correction and to AP for a repeated match.","Open corrections are followed up daily and escalated to the AP manager after two business days."],
      controls:["Search the register for a duplicate supplier and invoice number.","Match the invoice to the purchase order and receiving record before approval.","Controller reviews invoices at or above $50,000; department manager approves every payment package.","Retain approval and Treasury-acceptance evidence; AP preparation and manager approval are separate roles."],
      open_questions:[],validation_notes:["Synthetic example — all people, tools, amounts and process details are fictional.","This participant account is complete for the fictional scope and remains subject to process-owner review."]
    });
    state.closure={asked:true,confirmed:true};state.parking_lot=[];
    state.draftVersion = state.version;
    conversationUI.workflow=clone(state.draft);renderWorkingMap();
    state.dirty = false;
    renderTranscript(); renderDraft(); scrollConversation();
    knowledgeUI?.activateExample();
    notice("Complete synthetic example opened. Explore the transcript, map, memo and procedure.");
  }
  function initEvents() {
    for(const kind of ["transcript","report"]){
      $(kind+"-search").addEventListener("input",()=>{readingUI[kind].index=0;refreshReadingSearch(kind);});
      $(kind+"-search").addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();moveReadingSearch(kind,event.shiftKey?-1:1);}if(event.key==="Escape"){$(kind+"-search").value="";refreshReadingSearch(kind,false);}});
      for(const [name,direction] of [["previous",-1],["next",1]])$(kind+"-search-"+name).addEventListener("click",()=>moveReadingSearch(kind,direction));
    }
    $("report-contents").addEventListener("change",()=>{const target=$($("report-contents").value);if(target){target.scrollIntoView({block:"start",behavior:"smooth"});target.focus({preventScroll:true});}});
    $("back-to-source").addEventListener("click",returnToSource);
    $("settings-source-return").addEventListener("click",returnToSource);
    for(const id of ["interview-error","review-error"])$(id).querySelector("button").addEventListener("click",()=>{$(id).hidden=true;});
    for(const [prefix,id] of [["workflow","live-workflow"],["map","process-map"]]){
      $(prefix+"-step-select").addEventListener("change",()=>{const canvas=workflowCanvases.get(id),step=$(prefix+"-step-select").value;if(canvas?.getPathNavigation?.().following)canvas.followPath(step);else canvas?.focusStep(step,{readable:true,keyboard:false,select:true});});
      $(prefix+"-follow").addEventListener("click",()=>{const canvas=workflowCanvases.get(id);if(canvas?.getPathNavigation?.().following)canvas.leavePath();else canvas?.followPath($(prefix+"-step-select").value);});
      for(const direction of ["previous","next"])$(prefix+"-path-"+direction).addEventListener("change",event=>workflowCanvases.get(id)?.navigatePath(event.target.value,direction));
    }
    const narrowMemo=window.matchMedia("(max-width:760px), (max-height:500px) and (max-width:1100px)");
    const placeMemo=()=>{
      if(!narrowMemo.matches)setMemoSheet(false,false);
      (narrowMemo.matches?$("memo-sheet-body"):$("memo-host")).append($("memo-rail"));
    };
    placeMemo();narrowMemo.addEventListener("change",placeMemo);
    $("open-memo").addEventListener("click",()=>setMemoSheet(true));
    $("close-memo").addEventListener("click",()=>setMemoSheet(false));
    $("memo-sheet").addEventListener("close",()=>{if(memoRestoreFocus)$("open-memo").focus({preventScroll:true});});
    $("jump-latest").addEventListener("click",()=>{scrollConversation();$("jump-latest").hidden=true;});
    $("conversation-scroll").addEventListener("scroll",()=>{const pane=$("conversation-scroll");$("jump-latest").hidden=!state.turns.length||pane.scrollHeight-pane.clientHeight-pane.scrollTop<80;});
    $("start-live").addEventListener("click",startLiveConversation);
    $("stop-live").addEventListener("click",async()=>{voiceEnded=true;const wasConnected=conversationUI.live?.connected;const result=await conversationUI.live?.stop();updatePresence();if(wasConnected&&!result?.finalized)notice("Voice ended. Check the last transcript lines; the connection closed before final captions were confirmed.");});
    $("mute-live").addEventListener("click",()=>{conversationUI.muted=!conversationUI.muted;conversationUI.live?.setMuted(conversationUI.muted);updateControls();});
    $("type-instead").addEventListener("click",async()=>{
      if(!ensureConversation())return;
      conversationUI.typing=!conversationUI.typing;selectConversationView("transcript");updateControls();
      if(conversationUI.typing){$("answer-text").focus();if(!state.turns.some(turn=>!turn.document_event)&&!state.busy){const generation=state.generation;setBusy(true);try{const result=await request("/api/interview",{...snapshot(),action:"start"});if(generation===state.generation)applyInterview(result);}catch(error){notice(error.message,true);}finally{if(generation===state.generation)setBusy(false);}}}
    });
    $("retry-workflow").addEventListener("click",()=>{$("retry-workflow").dataset.layoutRetry?renderWorkingMap():refreshWorkflow();});
    $("map-retry-layout").addEventListener("click",()=>renderMap());
    $("workflow-zoom-out").addEventListener("click",()=>workflowCanvases.get("live-workflow")?.zoom(-.15));
    $("workflow-zoom-in").addEventListener("click",()=>workflowCanvases.get("live-workflow")?.zoom(.15));
    $("workflow-fit").addEventListener("click",()=>workflowCanvases.get("live-workflow")?.fit());
    for(const [button,id] of [["workflow-direction","live-workflow"],["map-direction","process-map"]])$(button).addEventListener("click",()=>{const canvas=workflowCanvases.get(id);if(canvas)canvas.setDirection(canvas.getDirection()==="DOWN"?"RIGHT":"DOWN").catch(()=>notice("The layout could not be changed. Your process is retained.",true));});
    $("export-working-map").addEventListener("click",()=>{const svg=workflowCanvases.get("live-workflow")?.exportSVG();if(svg)download(svg,`${safeFilename(state.context?.process_name)}-working-flow.svg`,"image/svg+xml");});
    $("close-workflow-step").addEventListener("click",()=>$("workflow-step-dialog").close());
    $("workflow-step-dialog").addEventListener("close",()=>{workflowDetailReturn?.focus?.({preventScroll:true});workflowDetailReturn=null;workflowDetailSource=null;});
    $("workflow-expand").addEventListener("click",()=>{const expanded=$("interview-view").classList.toggle("workflow-expanded");$("workflow-expand").setAttribute("aria-pressed",String(expanded));$("workflow-expand").textContent=expanded?"Exit focus":"Focus";requestAnimationFrame(()=>workflowCanvases.get("live-workflow")?.refresh());});
    $("retry-question").addEventListener("click",retryQuestion);
    document.querySelectorAll("[data-conversation-view]").forEach(button=>{button.addEventListener("click",()=>selectConversationView(button.dataset.conversationView));button.addEventListener("keydown",conversationTabKey);});
    $("open-interview-settings").addEventListener("click",()=>setInterviewSettings(true));
    $("close-interview-settings").addEventListener("click",()=>setInterviewSettings(false));
    $("interview-settings").addEventListener("close",()=>{if(settingsRestoreFocus)$("open-interview-settings").focus({preventScroll:true});});
    initFoundationDialog();
    initReviewTabs();
    document.querySelectorAll(".nav-tab").forEach(button => button.addEventListener("click", () => tab(button.dataset.tab)));
    $("map-zoom-out")?.addEventListener("click",() => zoomMap(-.25));
    $("map-zoom-in")?.addEventListener("click",() => zoomMap(.25));
    $("map-fit")?.addEventListener("click",()=>{const canvas=workflowCanvases.get("process-map");if(canvas)canvas.fit();else fitMapToWidth();});
    window.addEventListener("resize",() => {if(reviewUI.mapFit)fitMapToWidth();});
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
    $("generate-draft").addEventListener("click",generateDraft);
    $("regenerate-draft").addEventListener("click",generateDraft);
    $("back-to-interview").addEventListener("click",() => tab("interview",true));
    $("empty-start").addEventListener("click",() => tab("interview",true));
    $("dismiss-notice").addEventListener("click",() => {clearTimeout(noticeTimer);$("global-notice").hidden = true;});
    $("session-menu-toggle").addEventListener("click",() => {const open = $("session-menu").hidden; $("session-menu").hidden = !open; $("session-menu-toggle").setAttribute("aria-expanded",String(open));});
    document.addEventListener("click",event => {if (!$("session-menu").contains(event.target) && !$("session-menu-toggle").contains(event.target)) closeMenu();});
    document.addEventListener("keydown",event => {if (event.key === "Escape") closeMenu();});
    $("export-session").addEventListener("click",exportSession);
    $("import-session").addEventListener("click",() => {closeMenu(); $("session-file").click();});
    $("session-file").addEventListener("change",event => {importSession(event.target.files[0]); event.target.value = "";});
    $("reset-session").addEventListener("click",() => {if (canReplaceSession()) clearState();});
    $("load-example").addEventListener("click",loadExample);
    $("welcome-example").addEventListener("click",loadExample);
    $("leave-example").addEventListener("click",() => {if (canReplaceSession()) {clearState(); $("process-name").focus();}});
    $("export-markdown").addEventListener("click",() => {if (state.draft) download(markdown(),`${safeFilename(state.draft.title)}-DRAFT.md`,"text/markdown;charset=utf-8");});
    $("export-memo").addEventListener("click",()=>{if(state.draft)download(memoMarkdown(),`${safeFilename(state.context?.process_name||state.draft.title)}-memo-DRAFT.md`,"text/markdown;charset=utf-8");});
    $("export-map").addEventListener("click",() => {const canvas=workflowCanvases.get("process-map"),svg=$("process-map").querySelector("svg"),exported=canvas?canvas.exportSVG():svg?new XMLSerializer().serializeToString(svg):null;if(exported)download(exported,`${safeFilename(state.draft.title)}-DRAFT-map.svg`,"image/svg+xml");});
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
    document.querySelectorAll("#process-name,#process-owner,#objective,#background").forEach(input => input.addEventListener("input",() => {state.dirty = true;updateSaveHint();}));
    $("process-name").addEventListener("input",()=>{
      state.processNameManual=Boolean($("process-name").value.trim());
      if(state.context){state.context.process_name=$("process-name").value.trim();state.version++;conversationUI.revision++;scheduleWorkflow();}
      updateControls();
    });
    $("process-name").addEventListener("change",()=>{if(conversationUI.live?.active)conversationUI.live.appendContext(`The participant edited the process title to: ${$("process-name").value}`,{id:`title_${Date.now()}`,kind:"process_title"});});
    window.addEventListener("beforeunload",event => {if (state.dirty || state.recording || state.requestingMic || state.transcribing) {event.preventDefault(); event.returnValue = "";}});
    document.addEventListener("visibilitychange",updatePresence);
    window.addEventListener("pagehide",() => {stopSpeaking(); finishRecording(true);gpfsPresence?.setVisible(false);});
    bindDraftFields();
  }
  async function init() {
    if(window.GPFSPresence)gpfsPresence=window.GPFSPresence.create($("gpfs-presence"));
    initEvents(); renderCoverage(); updateControls();
    if(window.CollectorDocuments)documentController=window.CollectorDocuments.create({requestJSON:request,getContext:documentContext,config:()=>state.config,
      canUpload:()=>Boolean(state.config?.api_configured),onEvent:onDocumentEvent,notice,onDirty:()=>{state.dirty=true;updateSaveHint();}});
    if(window.CollectorKnowledge)knowledgeUI=window.CollectorKnowledge.create({request,session:sessionObject,notice,onSubmitted:()=>{state.dirty=true;updateSaveHint();}});
    refreshVoices();
    window.speechSynthesis?.addEventListener("voiceschanged", refreshVoices);
    try {
      const response = await fetch("/api/config",{credentials:"same-origin",cache:"no-store"});
      if (!response.ok) throw new Error("The interviewer is unavailable. Please try again.");
      const config = await response.json();
      if (typeof config.csrf_token !== "string") throw new Error("The interviewer is unavailable. Please try again.");
      state.config = config;
      knowledgeUI?.configure(config);
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
    documentController?.render();
  }
  init();
})();
