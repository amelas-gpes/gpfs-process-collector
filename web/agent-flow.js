"use strict";

(() => {
  // Each pair describes work at the same stage. A separate lane below the
  // interview shows requests a participant can make before or after wrap-up.
  function render(container, openAgent) {
    const element = (tag, className, text) => {
      const item = document.createElement(tag);
      if (className) item.className = className;
      if (text) item.textContent = text;
      return item;
    };

    function agent(id, label) {
      if (typeof openAgent !== "function") return element("strong", "", label);
      const button = element("button", "agent-flow-link", label);
      button.type = "button";
      button.dataset.agent = id;
      button.setAttribute("aria-label", `View prompts for ${label}`);
      button.addEventListener("click", () => openAgent(id));
      return button;
    }

    function path(title, ...content) {
      const card = element("div", "agent-flow-path");
      const detail = element("p");
      detail.append(...content);
      card.append(element("strong", "agent-flow-path-title", title), detail);
      return card;
    }

    function stage(icon, title, ...paths) {
      const row = element("li", "agent-flow-stage");
      const marker = element("span", "agent-flow-marker");
      marker.dataset.icon = icon;
      marker.setAttribute("aria-hidden", "true");
      const body = element("div", "agent-flow-stage-body");
      const branches = element("div", "agent-flow-branches");
      branches.append(...paths);
      body.append(element("h5", "", title), branches);
      row.append(marker, body);
      return row;
    }

    const figure = element("figure", "agent-flow");
    const caption = element("figcaption");
    caption.append(element("h4", "", "How the agents work together"));
    const flow = element("ol", "agent-flow-trunk");
    flow.append(
      stage("folder", "Gather the evidence",
        path("Participant account", "The participant describes the work by typing or speaking."),
        path("Reference files",
          "When files are supplied for review, the ", agent("document_analyst", "Document analyst"),
          " identifies what the files support and what to confirm.")),
      stage("swap", "Each answer feeds two paths",
        path("Next question", "In spoken interviews, the ", agent("live_interviewer", "Live interviewer"),
          " asks the next question directly over GPT Live. For typed answers and reviewed voice, the ",
          agent("lead_interviewer", "Lead interviewer"), " selects the next question."),
        path("Background capture", "The ", agent("lead_interviewer", "Lead interviewer"),
          " updates the notes and working map. The Document analyst checks map changes that use file evidence.")),
      stage("shield", "At completion review, two reviewers check the same account",
        path("Topic coverage", "The ", agent("coverage_reviewer", "Coverage reviewer"),
          " checks the sixteen required topics against the participant’s evidence."),
        path("Process accuracy", "The ", agent("process_reviewer", "Process reviewer"),
          " checks steps, handoffs, and exceptions for gaps or contradictions.")),
      stage("route", "The app coordinates wrap-up",
        path("Follow-up", "If the reviewers find a gap, the app can ask a follow-up. The participant can also pause and keep a partial account."),
        path("Final confirmation", "When the checks pass, the app asks whether anything is missing. The participant can confirm or add details."))
    );

    const optional = element("details", "agent-flow-optional");
    const summary = element("summary", "", "Other paths for voice, drafts, and filed processes");
    const options = element("div", "agent-flow-options");
    options.append(
      path("When using dictation or AI read-aloud", "The ", agent("transcriber", "Transcriber"),
        " turns dictated audio into text. The ", agent("voice_reader", "Voice reader"), " speaks the approved question when selected."),
      path("When a draft is requested", "The ", agent("draft_writer", "Draft writer"),
        " prepares the memo and map. The ", agent("draft_auditor", "Draft auditor"), " checks them against the sources before human review."),
      path("When a process is filed", "If matching is available, the ", agent("knowledge_analyst", "Knowledge analyst"),
        " compares the filed revision with eligible processes and proposes connections.")
    );
    optional.append(summary, options);
    figure.append(caption, flow, optional);
    container.replaceChildren(figure);
  }

  window.AgentFlow = {render};
})();
