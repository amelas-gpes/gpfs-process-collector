"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const dialog = $("interview-settings");
  if (!dialog) return;
  const panels = Array.from(dialog.querySelectorAll("[data-settings-panel]"));
  const tabs = Array.from(dialog.querySelectorAll("[data-settings-target]"));
  const tabList = dialog.querySelector('[role="tablist"]');
  const narrow = window.matchMedia("(max-width: 760px)");
  const syncOrientation = () => tabList.setAttribute("aria-orientation", narrow.matches ? "horizontal" : "vertical");
  syncOrientation(); narrow.addEventListener("change", syncOrientation);
  const finder = $("settings-search");
  const voice = $("voice-select");
  let active = "preferences-details", voiceItems = [];
  const index = [
    ["Appearance", "System, light or dark theme", "preferences-details", "theme-select", "appearance theme light dark system display look"],
    ["Interviewer voice", "Choose a natural AI or installed computer voice", "preferences-details", "voice-picker-toggle", "voice speaker sound audio computer natural playback"],
    ["Preview voice", "Hear the voice selected for question playback", "preferences-details", "preview-voice", "voice preview test sound listen"],
    ["Read questions aloud when typing", "Hear each question during the text interview", "preferences-details", "speak-questions", "read questions aloud typing speech playback"],
    ["Stop recording when I pause", "Finish a dictated reply after a natural pause", "preferences-details", "stop-on-silence", "dictation silence recording pause microphone"],
    ["Edit each reviewed-voice answer", "Review transcribed answers before sending", "preferences-details", "review-voice-transcript", "reviewed voice answer transcript edit transcription"],
    ["Participant", "Name or role of the person sharing the process", "context-details", "interview-participant", "participant person name role interview"],
    ["Process owner", "Who is responsible for this process?", "context-details", "process-owner", "owner responsible person context"],
    ["Interview goal", "What you want to learn about the process", "context-details", "objective", "goal objective purpose context"],
    ["Background", "Useful context, boundaries and areas to focus on", "context-details", "background", "background context focus scope"],
    ["Recovery copy", "Keep unfinished work on this computer", "data-details", "recovery-enabled", "recovery save copy unsaved restore autosave backup crash restart"],
    ["Data handling", "What stays here and what goes to the AI service", "data-details", "data-notice", "privacy data handling retention files service policies"],
    ["AI usage", "Daily and interview token counts and workspace limits", "usage-details", "usage-check", "AI usage tokens daily limits quota count"],
    ["Agents", "See the app workflow and read or copy agent prompts", "agents-details", "agents-details", "AI agent prompt library instructions workflow administrator"],
    ["Application logs", "Search recent or current-session activity", "logs-details", "logs-search", "application activity logs logging history events trace"],
    ["How this works", "A short guide to the interview and review", "help-guide", "help-guide", "help guide how works interview review workflow"],
    ["Definition of done", "When an interview is complete and what goes to the process owner", "help-guide", "definition-of-done", "completion gaps hold handoff partial wrap up approval coverage topics follow-ups"],
    ["Keyboard shortcuts", "Keys for Settings, saving and sending a reply", "help-guide", "keyboard-shortcuts", "keyboard shortcuts keys hotkeys send escape"],
    ["App version", "Version and build of this app", "help-guide", "build-identity", "version about build update release"],
  ];
  const panelName = id => tabs.find(tab => tab.dataset.settingsTarget === id)?.children[1]?.childNodes[0]?.textContent.trim() || id;

  function closeVoice(restore = false) {
    $("voice-picker-panel").hidden = true;
    $("voice-picker-toggle").setAttribute("aria-expanded", "false");
    if (restore) $("voice-picker-toggle").focus();
  }
  function show(id, focusId) {
    if (!tabs.some(tab => tab.dataset.settingsTarget === id && !tab.hidden)) return;
    active = id;
    finder.value = "";
    delete dialog.dataset.searching;
    $("settings-search-results").hidden = true;
    closeVoice();
    for (const panel of panels) panel.hidden = panel.id !== id;
    for (const tab of tabs) {
      const selected = tab.dataset.settingsTarget === id;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    }
    $("settings-body").scrollTop = 0;
    dialog.dispatchEvent(new CustomEvent("settings:section", {detail:{id}}));
    if (focusId) {
      let target = $(focusId);
      if (focusId === "theme-select") target = dialog.querySelector('input[name="settings-theme"]:checked');
      if (focusId === "data-notice") target.closest("details").open = true;
      if (target?.disabled) target = $(id);
      if (target) { target.tabIndex = target.tabIndex < 0 ? 0 : target.tabIndex; target.focus({preventScroll:true}); target.scrollIntoView({block:"nearest"}); }
    }
  }
  function available(entry) {
    const target = $(entry[3]);
    if (!target || !tabs.some(tab => tab.dataset.settingsTarget === entry[2] && !tab.hidden)) return false;
    // A hidden tabpanel is a navigation state, not an unavailable control.
    for (let node = target; node && node !== dialog; node = node.parentElement)
      if (node.hidden && !node.hasAttribute("data-settings-panel")) return false;
    return true;
  }
  function search() {
    const query = finder.value.trim().toLowerCase();
    if (!query) { show(active); return; }
    closeVoice();
    // No section is on screen while results are listed, so none is drawn as the current one.
    dialog.dataset.searching = "true";
    for (const panel of panels) panel.hidden = true;
    $("settings-search-results").hidden = false;
    const matches = index.filter(entry => available(entry) && query.split(/\s+/).every(word => entry.join(" ").toLowerCase().includes(word)));
    $("settings-search-count").textContent = matches.length ? `${matches.length} matching ${matches.length === 1 ? "setting" : "settings"}` : `No settings match “${finder.value.trim()}”.`;
    $("settings-search-suggestions").hidden = matches.length > 0;
    const list = $("settings-search-matches");
    list.replaceChildren();
    for (const entry of matches) {
      const button = document.createElement("button");
      button.type = "button"; button.className = "settings-result";
      const text = document.createElement("span"), title = document.createElement("strong"), description = document.createElement("small"), section = document.createElement("span");
      title.textContent = entry[0]; description.textContent = entry[1]; section.textContent = panelName(entry[2]);
      text.append(title, description); button.append(text, section);
      button.addEventListener("click", () => show(entry[2], entry[3]));
      list.append(button);
    }
    $("settings-body").scrollTop = 0;
  }
  function syncTheme() {
    for (const radio of dialog.querySelectorAll('input[name="settings-theme"]')) radio.checked = radio.value === $("theme-select").value;
  }
  function renderVoices() {
    const selected = Array.from(voice.options).find(option => option.value === voice.value);
    $("voice-picker-name").textContent = selected?.textContent || "Choose a voice";
    $("voice-picker-kind").textContent = voice.value.startsWith("ai:") ? "Natural AI voice" : voice.value.startsWith("local:") ? "Installed computer voice" : "Question playback";
    $("voice-picker-toggle").disabled = voice.disabled;
    if (voice.disabled) closeVoice();
    const query = $("voice-picker-search").value.trim().toLowerCase();
    const list = $("voice-picker-list");
    list.replaceChildren(); voiceItems = [];
    let group = null;
    for (const option of Array.from(voice.options)) {
      if (option.disabled || !option.textContent.toLowerCase().includes(query)) continue;
      const label = option.parentElement?.label || "Available voices";
      if (label !== group) {
        const heading = document.createElement("p"); heading.className = "voice-group-label"; heading.textContent = label;
        list.append(heading); group = label;
      }
      const button = document.createElement("button");
      button.type = "button"; button.className = "voice-option"; button.setAttribute("role", "option");
      button.setAttribute("aria-selected", String(option.value === voice.value)); button.textContent = option.textContent;
      button.tabIndex = option.value === voice.value ? 0 : -1;
      button.addEventListener("click", () => {
        if (voice.disabled || option.disabled) return;
        voice.value = option.value;
        voice.dispatchEvent(new Event("change", {bubbles:true}));
        closeVoice(true); renderVoices();
      });
      button.addEventListener("keydown", event => {
        const i = voiceItems.indexOf(button);
        if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
          event.preventDefault();
          const next = event.key === "Home" ? 0 : event.key === "End" ? voiceItems.length - 1 : (i + (event.key === "ArrowDown" ? 1 : -1) + voiceItems.length) % voiceItems.length;
          for(const item of voiceItems)item.tabIndex=item===voiceItems[next]?0:-1;
          voiceItems[next]?.focus();
        }
      });
      voiceItems.push(button); list.append(button);
    }
    if(voiceItems.length&&!voiceItems.some(item=>item.tabIndex===0))voiceItems[0].tabIndex=0;
    if (!voiceItems.length) { const empty = document.createElement("p"); empty.textContent = query ? "No voices match your search." : "No voices are available right now."; list.append(empty); }
  }
  function setUsage(usage) {
    $("usage-check").disabled = !usage;
    for (const [scope, used, cap] of [["day", usage?.day_tokens, usage?.daily_token_cap], ["interview", usage?.interview_tokens, usage?.interview_token_cap]]) {
      const known = typeof used === "number" && Number.isFinite(used);
      $("usage-" + scope + "-value").textContent = known ? used.toLocaleString("en-US") : "—";
      $("usage-" + scope + "-limit").textContent = !usage ? "Usage unavailable" : Number(cap) > 0 ? `Limit: ${Number(cap).toLocaleString("en-US")} tokens` : "No workspace limit set";
      const meter = $("usage-" + scope + "-meter"), limited = known && Number(cap) > 0;
      meter.hidden = !limited; meter.max = Math.max(1, Number(cap) || 1); meter.value = known ? Math.min(used, meter.max) : 0;
      // Past three quarters the bar turns to the caution color, and past nine tenths to the alert color.
      meter.optimum = 0; meter.low = meter.max * .75; meter.high = meter.max * .9;
      $("usage-" + scope + "-percent").textContent = limited ? Math.min(999, Math.round(used / Number(cap) * 100)) + "%" : "";
    }
  }
  for (const tab of tabs) {
    tab.addEventListener("click", () => show(tab.dataset.settingsTarget));
    tab.addEventListener("keydown", event => {
      if (!["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const visibleTabs = tabs.filter(item => !item.hidden);
      const i = visibleTabs.indexOf(tab), direction = ["ArrowDown", "ArrowRight"].includes(event.key) ? 1 : -1;
      const step = direction * (narrow.matches && ["ArrowDown", "ArrowUp"].includes(event.key) ? 3 : 1);
      const next = visibleTabs[event.key === "Home" ? 0 : event.key === "End" ? visibleTabs.length - 1 : (i + step + visibleTabs.length) % visibleTabs.length];
      next.focus(); show(next.dataset.settingsTarget);
    });
  }
  for (const button of dialog.querySelectorAll("[data-settings-jump]")) button.addEventListener("click", () => show(button.dataset.settingsJump, button.dataset.settingsJump));
  for (const radio of dialog.querySelectorAll('input[name="settings-theme"]')) radio.addEventListener("change", () => {
    if (!radio.checked) return;
    $("theme-select").value = radio.value;
    $("theme-select").dispatchEvent(new Event("change", {bubbles:true}));
  });
  $("theme-select").addEventListener("change", syncTheme);
  voice.addEventListener("change", renderVoices);
  if (typeof MutationObserver === "function") {
    new MutationObserver(renderVoices).observe(voice, {attributes:true, childList:true, subtree:true});
    new MutationObserver(syncTheme).observe(document.documentElement, {attributes:true, attributeFilter:["data-theme"]});
  }
  $("voice-picker-toggle").addEventListener("click", () => {
    const open = $("voice-picker-panel").hidden;
    $("voice-picker-panel").hidden = !open;
    $("voice-picker-toggle").setAttribute("aria-expanded", String(open));
    if (open) { $("voice-picker-search").value = ""; renderVoices(); $("voice-picker-search").focus(); $("voice-picker-panel").scrollIntoView({block:"nearest"}); }
  });
  $("voice-picker-search").addEventListener("input", renderVoices);
  $("voice-picker-search").addEventListener("keydown", event => { if (event.key === "ArrowDown" && voiceItems.length) { event.preventDefault(); (voiceItems.find(item=>item.tabIndex===0)||voiceItems[0]).focus(); } });
  dialog.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    if (!$("voice-picker-panel").hidden) { event.preventDefault(); event.stopPropagation(); closeVoice(true); }
    else if (finder.value) { event.preventDefault(); event.stopPropagation(); show(active); finder.focus(); }
  });
  dialog.addEventListener("click", event => { if (!$("voice-picker").contains(event.target)) closeVoice(); });
  dialog.addEventListener("close", () => { finder.value = ""; show(active); });
  finder.addEventListener("input", search);
  for (const chip of dialog.querySelectorAll("[data-settings-suggest]")) chip.addEventListener("click", () => {
    finder.value = chip.dataset.settingsSuggest; search(); finder.focus();
  });
  finder.addEventListener("keydown", event => {
    if (event.key === "Enter" && finder.value.trim()) { event.preventDefault(); $("settings-search-matches").querySelector("button")?.click(); }
    if (event.key === "ArrowDown" && finder.value.trim()) { event.preventDefault(); $("settings-search-matches").querySelector("button")?.focus(); }
  });
  for (const button of dialog.querySelectorAll("[data-log-scope]")) button.addEventListener("click", () => {
    for (const item of dialog.querySelectorAll("[data-log-scope]")) item.setAttribute("aria-pressed", String(item === button));
    $("logs-scope").value = button.dataset.logScope;
    $("logs-scope").dispatchEvent(new Event("change", {bubbles:true}));
  });
  window.CollectorSettings = {show, syncTheme, refreshVoice:renderVoices, setUsage, opened:() => { show(active); syncTheme(); renderVoices(); }};
  syncTheme(); renderVoices();
})();
