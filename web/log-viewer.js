"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const section = $("logs-details");
  if (!section) return;
  let entries = [], request = 0;

  function render() {
    const query = $("logs-search").value.trim().toLowerCase();
    const matching = entries.filter(row => JSON.stringify(row).toLowerCase().includes(query));
    $("logs-count").textContent = `${matching.length} of ${entries.length} loaded entries · newest first`;
    const list = $("logs-entries");
    list.replaceChildren();
    if (!matching.length) {
      const empty = document.createElement("p");
      empty.textContent = query ? "No loaded entries match your search." : "No saved entries in this view yet. Refresh after using the app, or choose Recent sessions.";
      list.append(empty);
    }
    for (const row of matching) {
      const detail = document.createElement("details");
      detail.className = "log-entry";
      const summary = document.createElement("summary");
      const time = document.createElement("span");
      const date = new Date(row.recorded_at || row.observed_at);
      time.textContent = Number.isNaN(date.getTime()) ? "Time unavailable" : date.toLocaleString();
      const type = document.createElement("strong");
      type.textContent = row.type;
      summary.setAttribute("aria-label", `${row.type} · ${time.textContent}`);
      summary.append(time, type);
      const content = document.createElement("pre");
      content.tabIndex = 0;
      content.textContent = JSON.stringify(row, null, 2);
      detail.append(summary, content);
      list.append(detail);
    }
  }

  async function refresh() {
    const generation = ++request;
    const hadFocus = document.activeElement === $("logs-refresh");
    $("logs-refresh").disabled = true;
    $("logs-status").textContent = "Loading saved logs…";
    entries = [];
    $("logs-entries").replaceChildren();
    $("logs-count").textContent = "";
    try {
      // Fetch the current token so a server restart does not require reloading an interview.
      const configResponse = await fetch("/api/config", {credentials:"same-origin"});
      if (!configResponse.ok) throw Error();
      const config = await configResponse.json();
      const response = await fetch(`/api/trace/logs?scope=${$("logs-scope").value}`, {
        credentials:"same-origin", headers:{"X-CSRF-Token":config.csrf_token}
      });
      if (!response.ok) throw Error();
      const data = await response.json();
      if (generation !== request) return;
      entries = data.events;
      const mode = data.status.mode === "content" ? "Interview content and activity are being logged locally."
        : data.status.enabled ? "Activity is being logged locally; interview content is excluded." : "Logging is off. Previously saved entries remain available.";
      const problem = data.status.space_pause ? " Recording is paused because local storage is unavailable."
        : data.status.failed || data.status.dropped ? " Some events could not be saved." : "";
      const bounds = data.limited ? " Showing a recent window of up to 100 entries." : "";
      const clipped = data.clipped ? " Large entries are shortened in this view; saved files keep their full content." : "";
      $("logs-status").textContent = mode + problem + bounds + clipped;
      render();
    } catch {
      if (generation !== request) return;
      $("logs-status").textContent = "The local logs could not be loaded. Choose Refresh to try again.";
    } finally {
      if (generation === request) {
        $("logs-refresh").disabled = false;
        if(hadFocus && $("interview-settings").open && !section.hidden &&
          (document.activeElement === document.body || document.activeElement === $("interview-settings"))) $("logs-refresh").focus({preventScroll:true});
      }
    }
  }
  $("interview-settings").addEventListener("settings:section", event => {
    if(event.detail.id === "logs-details" && $("interview-settings").open) void refresh();
  });
  $("logs-refresh").addEventListener("click", refresh);
  $("logs-scope").addEventListener("change", refresh);
  $("logs-search").addEventListener("input", render);
})();
