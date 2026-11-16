"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const dialog = $("interview-settings"), tab = $("settings-tab-agents");
  const panel = $("agents-details"), content = $("agents-content");
  const agentSelect = $("agent-select"), promptSelect = $("agent-prompt-select");
  const promptText = $("agent-prompt-text"), copyStatus = $("agent-copy-status");
  let config, renewToken, browserVoicePrompts, pending = null, agents = [];

  function clearCatalog() {
    pending?.abort();
    pending = null;
    agents = [];
    content.hidden = true;
    for (const id of ["agents-overview", "agent-select", "agent-prompt-select", "agent-description",
                      "agent-prompt-when", "agent-prompt-text", "agent-copy-status", "agents-status"]) {
      $(id).replaceChildren();
    }
    $("agents-retry").hidden = true;
  }

  function configure(next, renew, voicePrompts = () => []) {
    config = next;
    renewToken = renew;
    browserVoicePrompts = voicePrompts;
    tab.hidden = config?.agent_prompts_available !== true;
    if (tab.hidden) {
      clearCatalog();
      if (tab.getAttribute("aria-selected") === "true") window.CollectorSettings.show("preferences-details");
    }
  }

  function fillOptions(select, items) {
    select.replaceChildren();
    for (const item of items) {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.label;
      select.append(option);
    }
    select.value = items[0]?.id || "";
  }

  function selectedAgent() {
    return agents.find(agent => agent.id === agentSelect.value);
  }

  function selectPrompt() {
    const prompt = selectedAgent()?.prompts.find(item => item.id === promptSelect.value);
    $("agent-prompt-when").textContent = prompt?.when || "";
    promptText.textContent = prompt?.text || "";
    promptText.scrollTop = 0;
    copyStatus.textContent = "";
  }

  function selectAgent() {
    const agent = selectedAgent();
    if (!agent) return;
    $("agent-description").textContent = agent.description;
    fillOptions(promptSelect, agent.prompts);
    $("agent-prompt-details").hidden = !agent.prompts.length;
    selectPrompt();
  }

  function showView(library) {
    $("agents-library").hidden = !library;
    $("agents-overview").hidden = library;
    $("agents-library-button").setAttribute("aria-pressed", String(library));
    $("agents-overview-button").setAttribute("aria-pressed", String(!library));
  }

  function openAgent(id) {
    if (!agents.some(agent => agent.id === id)) return;
    agentSelect.value = id;
    selectAgent();
    showView(true);
    agentSelect.focus();
  }

  async function load() {
    if (tab.hidden || !dialog.open || panel.hidden || pending || agents.length) return;
    const controller = new AbortController();
    pending = controller;
    $("agents-retry").hidden = true;
    $("agents-status").textContent = "Loading agent prompts…";
    const send = token => fetch("/api/admin/agent-prompts", {
      credentials: "same-origin", cache: "no-store", headers: {"X-CSRF-Token": token}, signal: controller.signal
    });
    try {
      const token = config.csrf_token;
      let response = await send(token);
      let body = await response.json();
      if (response.status === 403 && body.code === "request_token_rejected" && await renewToken(token)) {
        if (controller.signal.aborted) return;
        response = await send(config.csrf_token);
        body = await response.json();
      }
      if (controller.signal.aborted) return;
      if (response.status === 401 || (response.status === 403 && body.code === "admin_required")) {
        configure(null, renewToken);
        const notice = $("agents-access-notice");
        notice.textContent = "Administrator access is required to view agent prompts.";
        notice.hidden = false;
        $("settings-tab-preferences").focus();
        return;
      }
      if (!response.ok || !Array.isArray(body.agents) || !body.agents.length) {
        throw new Error("The agent prompts could not be loaded.");
      }
      agents = body.agents;
      const live = agents.find(agent => agent.id === "live_interviewer");
      if (live) live.prompts.push(...browserVoicePrompts());
      fillOptions(agentSelect, agents);
      selectAgent();
      window.AgentFlow.render($("agents-overview"), openAgent);
      showView(false);
      $("agents-status").textContent = "";
      content.hidden = false;
    } catch {
      if (!controller.signal.aborted) {
        clearCatalog();
        $("agents-status").textContent = "Agent prompts are unavailable. Try loading them again.";
        $("agents-retry").hidden = false;
      }
    } finally {
      if (pending === controller) pending = null;
    }
  }

  async function copyPrompt() {
    const text = promptText.textContent;
    if (!text) return;
    const current = () => dialog.open && !panel.hidden && !content.hidden &&
      !$("agents-library").hidden && promptText.textContent === text;
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        if (current()) copyStatus.textContent = "Prompt copied.";
        return;
      } catch { /* Try the browser's selection-based copy. */ }
    }
    if (!current()) return;
    const selection = window.getSelection?.();
    if (selection) {
      const range = document.createRange();
      range.selectNodeContents(promptText);
      promptText.focus();
      selection.removeAllRanges();
      selection.addRange(range);
      try {
        if (document.execCommand?.("copy")) {
          selection.removeAllRanges();
          $("agent-copy-prompt").focus();
          copyStatus.textContent = "Prompt copied.";
          return;
        }
      } catch { /* Leave the prompt selected for manual copying. */ }
    }
    copyStatus.textContent = selection ? "Prompt selected. Use your device’s Copy command." :
      "Select the prompt text and use your device’s Copy command.";
  }

  dialog.addEventListener("settings:section", event => {
    $("agents-access-notice").hidden = true;
    if (event.detail.id === panel.id && dialog.open) void load();
    else clearCatalog();
  });
  $("agents-retry").addEventListener("click", load);
  $("agents-overview-button").addEventListener("click", () => showView(false));
  $("agents-library-button").addEventListener("click", () => showView(true));
  agentSelect.addEventListener("change", selectAgent);
  promptSelect.addEventListener("change", selectPrompt);
  $("agent-copy-prompt").addEventListener("click", copyPrompt);
  window.CollectorAgentSettings = {configure};
})();
