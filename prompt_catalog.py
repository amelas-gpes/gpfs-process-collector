"""Read-only catalog of the application instructions used for provider calls.

Only application-owned prompt definitions and builders belong here. The catalog
does not accept a client, request, interview, configuration or provider trace.
"""


def _prompt(key, label, when, text):
    return {"id": key, "label": label, "when": when, "text": text}


def _agent(key, label, description, prompts):
    return {"id": key, "label": label, "description": description, "prompts": prompts}


def _coverage_prompts(api):
    coverage = api.interview_coverage
    result = [
        _prompt("all_topics", "Assess all topics", "Checks the proposed memo against the available evidence.",
                coverage.AUDIT_INSTRUCTIONS),
        _prompt("all_topics_repair", "Assess and repair all topics",
                "Checks all topics and can propose targeted corrections supported by the sources.",
                coverage.REPAIR_AUDIT_INSTRUCTIONS),
    ]
    group_labels = {"name": "Process scope", "accountable": "Roles and handoffs",
                    "checks": "Controls and data", "pain_points": "Effort and risk"}
    for group in coverage.COVERAGE_REVIEW_GROUPS:
        group_id = group[0]
        topics = ", ".join(api.COVERAGE[key] for key in group)
        for repair in (False, True):
            key = f"group_{group_id}" + ("_repair" if repair else "")
            action = "Repair" if repair else "Assess"
            result.append(_prompt(key, f"{group_labels.get(group_id, api.COVERAGE[group_id])} · {action}",
                                  f"Standard group covering {topics}. A narrower check uses only the requested topics and criteria.",
                                  coverage.group_instructions(group, repair)))
    return result


def agent_prompts(api):
    team = api.agent_team
    coordinator = api.interview_orchestrator
    roles = team.ROLE_CONTRACTS
    map_audit = _prompt("map_audit", "Audit the working map",
                        "Checks proposed changes and their source support before the app updates the map.",
                        api.WORKFLOW_AUDIT_INSTRUCTIONS)
    route_recheck = _prompt("route_recheck", "Recheck a route quotation",
                            "Runs when the app cannot verify the supporting quotation for a proposed connection.",
                            api.ROUTE_RECHECK_INSTRUCTIONS)
    return {"agents": [
        _agent("lead_interviewer", roles["lead_interviewer"]["label"],
               "Asks the next question, captures source-backed facts and builds the working map.", [
            _prompt("next_question", "Choose the next question",
                    "Responds to a participant while the app updates notes and the map in the background.",
                    api.concurrent_interview.question_policy(api)),
            _prompt("notes", "Capture notes in the background",
                    "Records facts when another interviewer handles the conversation.",
                    coordinator.capture_instructions(api, notes_only=True)),
            _prompt("capture", "Capture and ask a question",
                    "Records facts and chooses a question in the same managed interview turn.",
                    coordinator.capture_instructions(api)),
            _prompt("capture_document", "Follow up on reviewed files",
                    "Uses the accepted capture and reviewed file evidence to ask a focused follow-up.",
                    coordinator.capture_instructions(api, document_followup=True)),
            _prompt("workflow", "Update the map and findings",
                    "Proposes changes to the working map alongside the memo findings.",
                    coordinator.workflow_instructions(api, map_only=False)),
            _prompt("map_only", "Update the map in the background",
                    "Proposes map changes while a separate task maintains the notes.",
                    coordinator.workflow_instructions(api, map_only=True)),
            map_audit, route_recheck,
            _prompt("interview", "Interview and capture in one call",
                    "Used by the single-call interview route for ordinary answers, starts and skips.",
                    api.interview_instructions("answer")),
            _prompt("interview_close", "Check for omissions",
                    "Used when the participant invokes the final completeness check on the single-call interview route.",
                    api.interview_instructions("close")),
            _prompt("interview_document", "Review files in a single-call interview",
                    "Used for a document follow-up on the single-call interview route.",
                    api.interview_instructions("document_followup")),
            _prompt("question_audit", "Audit the proposed next question",
                    "Checks a question after validating a single-call interview capture.",
                    api.next_question_instructions(False)),
            _prompt("document_question_audit", "Audit a file follow-up question",
                    "Checks the proposed question against the accepted capture and reviewed documents.",
                    api.next_question_instructions(True)),
        ]),
        _agent("coverage_reviewer", roles["coverage_reviewer"]["label"],
               "Checks whether participant evidence explains each memo topic and identifies gaps.",
               _coverage_prompts(api)),
        _agent("process_reviewer", roles["process_reviewer"]["label"],
               "Reviews the reported sequence, branches, handoffs and outputs for unresolved problems.", [
            _prompt("process_review", "Review the process account",
                    "Checks a candidate account during completion review and can recheck an account repaired by the coverage reviewer.",
                    team.PROCESS_REVIEW_INSTRUCTIONS),
        ]),
        _agent("document_analyst", roles["document_analyst"]["label"],
               "Reads selected reference material and checks working maps that rely on file evidence.", [
            _prompt("document_review", "Review a reference file",
                    "Reads the selected file material in the initial and detailed review passes.",
                    api.DOCUMENT_INSTRUCTIONS),
            map_audit, route_recheck,
        ]),
        _agent("live_interviewer", "Live voice interviewer",
               "Hears participant responses, asks questions aloud and can delegate detailed checks.", [
            _prompt("voice_interview", "Conduct the live conversation",
                    "The app inserts the current process and selected document context into these placeholders.",
                    api.live_instructions("{process_context_json}") + "{document_context_json}"),
            _prompt("delegate", "Answer a delegated question",
                    "The voice model can ask the interview model for a more detailed answer.",
                    api.live_delegate_instructions("{document_context_json}")),
            _prompt("opening", "Start a voice session without files",
                    "The server sets the opening instructions before the browser connects.", api.LIVE_OPENING),
            _prompt("opening_files", "Start with readable files",
                    "The server can include reference file text in the starting voice context.", api.LIVE_OPENING_DOCUMENTS),
            _prompt("opening_unread", "Start with unread files",
                    "The server knows about the attachments but has no readable text in the starting voice context.", api.LIVE_OPENING_UNREAD),
            _prompt("resume", "Resume with condensed history",
                    "The app fills in turn counts, any clipping notice and a bounded status summary.",
                    api.LIVE_RESUME_NOTE + "{capture_status_json}"),
            _prompt("clip", "Explain a clipped turn",
                    "Replaces {clipped} in the resume message if even the newest turn exceeds the history limit.",
                    api.LIVE_RESUME_CLIPPED),
        ]),
        _agent("voice_reader", "Read-aloud voice", "Reads the supplied text aloud.", [
            _prompt("read", "Read the supplied text",
                    "Used for speech playback of an existing line.", api.VOICE_READER_INSTRUCTIONS),
        ]),
        _agent("transcriber", "Audio transcriber", "Converts a recorded answer into text.", [
            _prompt("transcribe", "Transcribe with spelling hints",
                    "Used when the transcription service accepts separate spelling hints and hints are configured.",
                    api.TRANSCRIPTION_INSTRUCTIONS),
            _prompt("keywords", "Supply hints as the prompt",
                    "Some transcription models receive the configured comma-separated spelling hints as the entire prompt.",
                    "{comma_separated_spelling_hints}"),
        ]),
        _agent("draft_writer", "Draft writer", "Builds a process draft from the interview and its supporting evidence.", [
            _prompt("draft", "Generate the process draft",
                    "Runs when a participant requests a draft.", api.draft_instructions()),
        ]),
        _agent("draft_auditor", "Draft auditor", "Checks the proposed draft against the reported work and its sources.", [
            _prompt("draft_audit", "Audit the draft",
                    "Reviews the unpublished draft, including the evidence for each connection.",
                    api.draft_audit_instructions()),
            route_recheck,
        ]),
        _agent("knowledge_analyst", "Cross-process analyst",
               "Suggests possible relationships between filed processes for review.", [
            _prompt("proposals", "Propose cross-process connections",
                    "Runs during background matching when eligible records and AI analysis are available.",
                    api.knowledge_ai.INSTRUCTIONS),
        ]),
    ]}
