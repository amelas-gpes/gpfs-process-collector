#!/usr/bin/env python3
"""Headless participant harness for AI Process Collector (isolated test servers only).

  pc.py start  CASE --port P --name "Process name" [--objective TEXT] [--background TEXT]
  pc.py upload CASE FILE [FILE...]            # Assets > Add files, then the file follow-up question
  pc.py answer CASE "text" [--voice] [--rate WPM] [--think SECONDS]
  pc.py skip   CASE
  pc.py wrap   CASE [--mapwait SECONDS]
  pc.py show   CASE                           # notes, map and graph checks as text
  pc.py timings CASE                          # JSON of every timed event

State lives in <cases dir>/CASE.json. Every command prints what a participant would see plus timings.
"""
import argparse, json, os, re, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = os.path.join(os.path.dirname(HERE), "cases")
os.makedirs(CASES, exist_ok=True)
DOC_EVENT_TEXT = "Thanks for sharing. Give me a moment to digest the file. Then I’ll follow up with a question."


def now():
    return time.time()


class Case:
    def __init__(self, name):
        self.path = os.path.join(CASES, name + ".json")
        self.s = json.load(open(self.path)) if os.path.exists(self.path) else None

    def save(self):
        tmp = self.path + ".tmp"
        json.dump(self.s, open(tmp, "w"), indent=1)
        os.replace(tmp, self.path)

    # --- http
    def base(self):
        return f"http://127.0.0.1:{self.s['port']}"

    def csrf(self, refresh=False):
        if refresh or not self.s.get("csrf"):
            with urllib.request.urlopen(self.base() + "/api/config", timeout=20) as r:
                self.s["csrf"] = json.load(r)["csrf_token"]
        return self.s["csrf"]

    def post(self, path, body=None, raw=None, headers=None, timeout=340, label=None):
        """POST; returns (status, json, seconds). Retries 429/503 and a rejected token like the browser."""
        data = raw if raw is not None else json.dumps(body).encode()
        t0 = now(); retries = 0
        while True:
            h = {"X-CSRF-Token": self.csrf(), "X-Interview-Id": self.s["interview_id"],
                 "Content-Type": "application/json" if raw is None else "application/octet-stream"}
            h.update(headers or {})
            req = urllib.request.Request(self.base() + path, data=data, headers=h, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    status, text = r.status, r.read()
            except urllib.error.HTTPError as e:
                status, text = e.code, e.read()
            except Exception as e:  # timeout / connection
                status, text = 0, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode()
            try:
                out = json.loads(text) if text else {}
            except ValueError:
                out = {"error": text[:300].decode("utf-8", "replace")}
            if status == 403 and out.get("code") == "request_token_rejected" and retries < 2:
                self.csrf(refresh=True); retries += 1; continue
            if status in (429, 503) and retries < 15 and out.get("code") not in ("budget_reached", "quota"):
                retries += 1; time.sleep(2); continue
            dt = now() - t0
            self.event(label or path, seconds=round(dt, 3), status=status, retries=retries,
                       error=(out.get("error") if status >= 400 or status == 0 else None))
            return status, out, dt

    def event(self, kind, **kw):
        row = {"kind": kind, "at": round(now(), 3), "turn": len(self.s["turns"])}
        row.update({k: v for k, v in kw.items() if v is not None})
        self.s["events"].append(row)

    # --- snapshot
    def snapshot(self, action, extra=None):
        s = self.s
        body = {"context": s["context"], "turns": s["turns"], "action": action,
                "session": {"closure_requested": action == "close"},
                "document_revision": s.get("document_revision", '[""]'), "document_source_ids": []}
        if s.get("capture_token"): body["capture_token"] = s["capture_token"]
        if s.get("document_scope"): body["document_scope"] = s["document_scope"]
        if s.get("conversation_token"): body["conversation_token"] = s["conversation_token"]
        body.update(extra or {})
        return body

    def next_id(self):
        ids = {t["id"] for t in self.s["turns"]}
        n = len(self.s["turns"]) + 1
        while f"t{n:03d}" in ids: n += 1
        return f"t{n:03d}"

    def add_turn(self, role, text, **kw):
        t = {"id": self.next_id(), "role": role, "text": text}; t.update(kw)
        self.s["turns"].append(t); return t

    def take_turn_reply(self, out):
        if out.get("conversation_token"): self.s["conversation_token"] = out["conversation_token"]
        if out.get("revision"): self.s["revision"] = out["revision"]
        if out.get("capture_token"): self.s["capture_token"] = out["capture_token"]

    # --- background results
    def poll(self, t0, budget, want_notes=True, want_map=True, tag="turn"):
        """Poll status like the browser (but every 0.5 s) until notes and map are current, or budget ends."""
        s = self.s
        got_notes = not want_notes; got_map = not want_map
        last = {}
        deadline = now() + budget
        while now() < deadline and s.get("conversation_token") and s.get("revision"):
            body = {"conversation_token": s["conversation_token"], "revision": s["revision"]}
            if s.get("document_scope"): body["document_scope"] = s["document_scope"]
            req = urllib.request.Request(self.base() + "/api/conversation/status", data=json.dumps(body).encode(),
                                         headers={"X-CSRF-Token": self.csrf(), "Content-Type": "application/json",
                                                  "X-Interview-Id": s["interview_id"]}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=30) as r: out = json.load(r)
            except urllib.error.HTTPError as e:
                try: out = json.loads(e.read())
                except Exception: out = {}
                out["_http"] = e.code
                if e.code not in (429, 503):
                    last = out; break
                time.sleep(1); continue
            except Exception as e:
                last = {"error": str(e)}; time.sleep(1); continue
            last = out
            if not got_notes and (out.get("capture") or out.get("capture_preserved")):
                got_notes = True
                if out.get("capture"): s["capture"] = out["capture"]
                self.event(tag + ".notes_ready", seconds=round(now() - t0, 2))
            if not got_notes and out.get("state") == "error":
                got_notes = True
                self.event(tag + ".notes_error", seconds=round(now() - t0, 2), error=out.get("error"), code=out.get("error_code"))
            # The map through an earlier answer, shown while the map of this revision is still being drawn.
            pv = out.get("workflow_checkpoint") or out.get("workflow_provisional")
            if pv:
                checked = bool(pv.get("checked", pv.get("audited")))
                key = [pv.get("revision"), pv.get("version"), checked]
                seen = s.setdefault("seen_provisional", [])
                if key not in seen:
                    seen.append(key)
                    wfp = (pv.get("workflow_capture") or {}).get("workflow") or {}
                    users = [t["id"] for t in s["turns"] if t["role"] == "user"]
                    behind = len(users) - 1 - users.index(pv["through_turn_id"]) if pv.get("through_turn_id") in users else None
                    s["workflow_shown"] = wfp
                    self.event(tag + ".map_shown", seconds=round(now() - t0, 2), audited=checked, answers_behind=behind,
                               through=pv.get("through_turn_id"), steps=len(wfp.get("steps", [])), connections=len(wfp.get("connections", [])))
            if not got_map and out.get("workflow_capture"):
                got_map = True
                s["workflow"] = out["workflow_capture"].get("workflow"); s["workflow_revision"] = s["revision"]
                s["workflow_checked"] = bool(out.get("workflow_checked")); s["workflow_shown"] = s["workflow"]
                self.event(tag + ".map_ready", seconds=round(now() - t0, 2), audited=bool(out.get("workflow_checked")),
                           check_state=out.get("workflow_check_state"), check_error=out.get("workflow_check_error"), answers_behind=0,
                           steps=len((s["workflow"] or {}).get("steps", [])), connections=len((s["workflow"] or {}).get("connections", [])))
            if not got_map and out.get("workflow_state") == "error":
                got_map = True
                self.event(tag + ".map_error", seconds=round(now() - t0, 2), error=out.get("workflow_error"), code=out.get("workflow_error_code"))
            if got_notes and got_map: break
            time.sleep(0.5)
        state = {"notes": last.get("state"), "map": last.get("workflow_state"), "waited": round(now() - t0, 1)}
        if not (got_notes and got_map):
            self.event(tag + ".left_pending", notes_state=last.get("state"), map_state=last.get("workflow_state"),
                       seconds=round(now() - t0, 2), http=last.get("_http"), error=last.get("error"))
        return state


def speak_to_wav(text, rate):
    d = tempfile.mkdtemp(prefix="pcvoice")
    aiff, wav = os.path.join(d, "a.aiff"), os.path.join(d, "a.wav")
    subprocess.run(["/usr/bin/say", "-r", str(rate), "-o", aiff, text], check=True)
    subprocess.run(["/usr/bin/afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav], check=True)
    data = open(wav, "rb").read()
    return data, (len(data) - 44) / 32000.0


def word_diff(a, b):
    """Rough word error rate of b against reference a."""
    A = re.findall(r"[a-z0-9']+", a.lower()); B = re.findall(r"[a-z0-9']+", b.lower())
    prev = list(range(len(B) + 1))
    for i, x in enumerate(A, 1):
        cur = [i]
        for j, y in enumerate(B, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return round(prev[-1] / max(1, len(A)), 3)


def cmd_start(a):
    c = Case(a.case)
    c.s = {"case": a.case, "port": a.port, "interview_id": uuid.uuid4().hex,
           "context": {"process_name": a.name, "process_owner": "", "objective": a.objective or f"Document how we carry out {a.name}, the controls and what needs confirmation.", "background": a.background or ""},
           "turns": [], "events": [], "started": now()}
    if a.nofirst:
        c.save(); print("case created (no opening question yet)"); return
    st, out, dt = c.post("/api/conversation/turn", c.snapshot("start"), label="start")
    if st != 200: c.save(); sys.exit(f"START FAILED {st}: {out}")
    c.take_turn_reply(out); c.add_turn("assistant", out["question"]); c.save()
    print(f"[{dt:.1f}s] INTERVIEWER: {out['question']}")


def cmd_answer(a, action="answer"):
    c = Case(a.case); s = c.s
    if action == "answer" and getattr(a, "file", None):
        a.text = open(a.file, encoding="utf-8").read().strip()
    if action == "answer" and not (a.text or "").strip():
        sys.exit("answer needs text or --file")
    text = a.text if action == "answer" else None
    extra = ""
    if action == "answer" and a.voice:
        audio, secs = speak_to_wav(text, a.rate)
        hints = [w for w in dict.fromkeys(re.findall(r"\b(?:[A-Z]{2,}[A-Za-z0-9-]*|[A-Z][a-z]+(?: [A-Z][A-Za-z]*)+)\b", " ".join(t["text"] for t in s["turns"] if t["role"] == "user")))][:20]
        st, out, dt = c.post("/api/transcribe", raw=audio, headers={"Content-Type": "audio/wav", **({"X-Transcription-Hints": urllib.parse.quote(",".join(hints))} if hints else {})}, timeout=160, label="transcribe")
        c.s["events"][-1]["hints"] = len(hints)
        if st != 200:
            c.save(); sys.exit(f"TRANSCRIBE FAILED {st}: {out}")
        heard = out.get("text", "")
        c.s["events"][-1].update({"audio_seconds": round(secs, 1), "audio_bytes": len(audio), "wer": word_diff(text, heard),
                                  "spoken": text, "heard": heard})
        extra = f"[voice: {secs:.0f}s of audio transcribed in {dt:.1f}s, word error ~{word_diff(text, heard):.0%}]\nHEARD AS: {heard}\n"
        text = heard
    if action == "answer":
        c.add_turn("user", text)
    t0 = now()
    st, out, dt = c.post("/api/conversation/turn", c.snapshot(action), label="question")
    if st != 200:
        c.save(); print(extra + f"TURN FAILED after {dt:.1f}s: HTTP {st} {out.get('error')}"); return
    c.take_turn_reply(out)
    synced = ""
    if out.get("sync_required"):
        st2, out2, dt2 = c.post("/api/conversation/sync", c.snapshot(action), label="sync_required")
        synced = f" (interviewer asked for a review; sync took {dt2:.1f}s, HTTP {st2})"
        if st2 == 200:
            c.take_turn_reply(out2); out = out2
            if out2.get("memo_findings") is not None: s["capture"] = {k: out2.get(k) for k in ("memo_findings", "coverage", "summary", "focus", "parking_lot", "connections_out", "taxonomy")}
            if out2.get("workflow_capture"): s["workflow"] = out2["workflow_capture"].get("workflow")
            s["last_kind"] = (out2.get("speech_authorization") or {}).get("kind"); s["review_ticket"] = out2.get("review_ticket")
    q = out.get("question") or ""
    if q: c.add_turn("assistant", q)
    c.save()
    print(extra + f"[question in {dt:.1f}s]{synced} INTERVIEWER: {q or '(no question returned)'}")
    state = c.poll(t0, a.think)
    c.save()
    ev = [e for e in s["events"] if e["at"] >= t0 and e["kind"].startswith("turn.")]
    print("background after this answer: " + "; ".join(f"{e['kind'][5:]} at {e['seconds']}s" + (f" ({e.get('steps')} steps)" if 'steps' in e else "") + (f" [{e.get('error')}]" if e.get('error') else "") for e in ev) + f" | notes={state['notes']} map={state['map']}")


def cmd_upload(a):
    c = Case(a.case); s = c.s
    ctx = {"context": s["context"], "turns": s["turns"][-8:], "focus": "", "current_question": next((t["text"] for t in reversed(s["turns"]) if t["role"] == "assistant"), "")}
    t_sel = now()
    if not s.get("document_scope"):
        st, out, dt = c.post("/api/documents/session", ctx, label="doc.session")
        if st != 200: c.save(); sys.exit(f"DOC SESSION FAILED {st}: {out}")
        s["document_scope"] = out["scope"]
    ids = []
    for f in a.files:
        data = open(f, "rb").read()
        st, out, dt = c.post("/api/documents/upload", raw=data, timeout=130, label="doc.upload",
                             headers={"X-Document-Scope": s["document_scope"], "X-Document-Filename": urllib.parse.quote(os.path.basename(f), safe="")})
        c.s["events"][-1].update({"file": os.path.basename(f), "bytes": len(data)})
        if st not in (200, 202): c.save(); print(f"UPLOAD FAILED {st}: {out}"); return
        ids.append(out["document"]["id"])
        print(f"[{dt:.2f}s] accepted {os.path.basename(f)} ({len(data)} bytes)")
    seen = {}; docs = []
    deadline = now() + a.readwait
    used = set()
    while now() < deadline:
        st, out, _ = c.post("/api/documents/status", dict(ctx, scope=s["document_scope"]), label="_poll")
        s["events"].pop()  # polls are not events
        docs = [d for d in out.get("documents", []) if d.get("id") in ids]
        done = 0
        for d in docs:
            an = d.get("analysis") or {}
            marks = {"extracted": d.get("status") in ("ready", "partial") and (d.get("chunk_count") or 0) > 0,
                     "review_started": an.get("phase") in ("quick", "deep", "complete"),
                     "review_deep": an.get("phase") in ("deep", "complete"),
                     "review_complete": an.get("phase") == "complete",
                     "failed": d.get("status") == "error" or an.get("phase") == "error" or bool(an.get("error"))}
            for k, v in marks.items():
                if v and (d["id"], k) not in seen:
                    seen[(d["id"], k)] = 1
                    c.event("doc." + k, seconds=round(now() - t_sel, 2), file=d.get("name"), chunks=d.get("chunk_count"),
                            status=d.get("status"), phase=an.get("phase"), disposition=an.get("disposition"),
                            error=(d.get("error") or an.get("error")), coverage=d.get("coverage"))
                    print(f"  {now() - t_sel:6.1f}s  {d.get('name')}: {k} (status={d.get('status')}, phase={an.get('phase')}, chunks={d.get('chunk_count')}, disposition={an.get('disposition')})")
            if an.get("disposition") == "needs_reason" and d["id"] not in used:
                used.add(d["id"])
                st2, o2, _ = c.post("/api/documents/action", {"scope": s["document_scope"], "id": d["id"], "action": "use", "purpose": "This file describes the process being documented."}, label="doc.use_after_needs_reason")
                print(f"  app asked why the file is relevant; told it to use the file (HTTP {st2})")
            if marks["review_complete"] or marks["failed"] or an.get("review_stopped"): done += 1
        if docs and done == len(docs): break
        time.sleep(0.5)
    else:
        c.event("doc.read_timeout", seconds=round(now() - t_sel, 2))
        print(f"  file review still running after {a.readwait}s")
    s["documents"] = [{k: d.get(k) for k in ("id", "name", "kind", "size", "status", "chunk_count", "analysis", "coverage", "error", "revision", "intent_version")} for d in docs]
    s["document_revision"] = json.dumps([s["document_scope"]] + [[d["id"], d.get("intent_version", 0)] for d in docs])
    # the browser starts a new conversation for the file follow-up
    s.pop("conversation_token", None)
    c.add_turn("assistant", DOC_EVENT_TEXT, document_event=True, document_id="doc_intake")
    t0 = now()
    st, out, dt = c.post("/api/conversation/turn", c.snapshot("document_followup", {"document_required_ids": ids}), timeout=160, label="doc.followup_question")
    if st != 200:
        c.save(); print(f"FILE FOLLOW-UP FAILED after {dt:.1f}s: HTTP {st} {out.get('error')}"); return
    c.take_turn_reply(out)
    q = out.get("question") or ""
    if q: c.add_turn("assistant", q)
    c.event("doc.first_question", seconds=round(now() - t_sel, 2), reading=out.get("document_reading"))
    c.save()
    print(f"[first question {now() - t_sel:.1f}s after choosing the file; the question call itself took {dt:.1f}s]\nINTERVIEWER: {q}")
    state = c.poll(t0, a.think, tag="doc")
    c.save()
    ev = [e for e in s["events"] if e["at"] >= t0 and e["kind"].startswith("doc.") and "seconds" in e and e["kind"] not in ("doc.followup_question", "doc.first_question")]
    print("background after the file: " + "; ".join(f"{e['kind'][4:]} at {e['seconds']}s" + (f" ({e.get('steps')} steps)" if 'steps' in e else "") + (f" [{e.get('error')}]" if e.get('error') else "") for e in ev) + f" | notes={state['notes']} map={state['map']}")


def cmd_wrap(a):
    c = Case(a.case); s = c.s
    t0 = now()
    st, out, dt = c.post("/api/conversation/sync", c.snapshot("close"), label="wrap.sync", timeout=340)
    if st != 200:
        c.save(); print(f"WRAP UP FAILED after {dt:.1f}s: HTTP {st} {out.get('error')}")
    else:
        c.take_turn_reply(out)
        s["capture"] = {k: out.get(k) for k in ("memo_findings", "coverage", "summary", "focus", "parking_lot", "connections_out", "taxonomy", "completion", "coverage_assessment")}
        kind = (out.get("speech_authorization") or {}).get("kind")
        if out.get("question"): c.add_turn("assistant", out["question"])
        if out.get("workflow_capture"):
            s["workflow"] = out["workflow_capture"].get("workflow"); s["workflow_revision"] = s.get("revision")
        print(f"[wrap up {dt:.1f}s] kind={kind} workflow_state={out.get('workflow_state')} INTERVIEWER: {out.get('question')}")
        c.s["events"][-1].update({"reply_kind": kind, "workflow_state": out.get("workflow_state"), "workflow_error": out.get("workflow_error")})
        c.save()
        if kind == "review_pending" and out.get("review_ticket"):
            body = c.snapshot("close"); body["review_ticket"] = out["review_ticket"]; body.pop("conversation_token", None)
            st2, o2, dt2 = c.post("/api/agent-team/review", body, label="wrap.review", timeout=340)
            k2 = (o2.get("speech_authorization") or {}).get("kind")
            c.s["events"][-1].update({"reply_kind": k2})
            if st2 == 200:
                if o2.get("capture_token"): s["capture_token"] = o2["capture_token"]
                if o2.get("question"): c.add_turn("assistant", o2["question"])
                if o2.get("memo_findings") is not None:
                    s["capture"].update({k: o2.get(k) for k in ("memo_findings", "coverage", "summary", "completion", "coverage_assessment") if o2.get(k) is not None})
            print(f"[independent review {dt2:.1f}s, HTTP {st2}] kind={k2} INTERVIEWER: {o2.get('question') or o2.get('error')}")
        if not (out.get("workflow_capture")):
            state = c.poll(t0, max(5, min(a.mapwait, 560 - (now() - t0))), want_notes=False, tag="wrap")
            print(f"map after wrap up: {state}")
    s["finished"] = now()
    c.save()
    cmd_show(a)


def cmd_live(a):
    """Live voice, simulated with text: the routes the page calls after each finalised spoken answer.

    In Live mode the browser holds the conversation with GPT-Live over WebRTC. After each answer it
    sends the transcript so far to /api/agent-team/interview with live_notes (the managed team's notes)
    and to /api/agent-team/workflow with the notes and map it holds (the map); with the managed team on,
    the page rewrites /api/interview and /api/workflow to those routes and adds a run id. The spoken lines here are the turns of
    a finished typed case, replayed one exchange at a time.
    """
    src = json.load(open(os.path.join(CASES, a.source + ".json")))
    c = Case(a.case)
    c.s = {"case": a.case, "port": a.port, "interview_id": uuid.uuid4().hex, "context": src["context"], "turns": [], "events": [],
           "started": now(), "mode": "live_simulated", "replayed_from": a.source}
    s = c.s
    spoken = [t for t in src["turns"] if not t.get("document_event")]
    answers = 0
    for t in spoken:
        s["turns"].append({"id": c.next_id(), "role": t["role"], "text": t["text"]})
        if t["role"] != "user":
            continue
        answers += 1
        base = {"context": s["context"], "turns": s["turns"], "session": {"closure_requested": False},
                "document_revision": '[""]', "document_source_ids": []}
        if s.get("capture_token"): base["capture_token"] = s["capture_token"]
        st, out, dt = c.post("/api/agent-team/interview", dict(base, action="answer", live_notes=True, agent_run_id=uuid.uuid4().hex), label="live.notes", timeout=340)
        if st == 200:
            if out.get("capture_token"): s["capture_token"] = out["capture_token"]
            s["capture"] = {k: out.get(k) for k in ("memo_findings", "coverage", "summary", "focus", "parking_lot", "connections_out", "taxonomy", "completion")}
            print(f"[answer {answers}: notes in {dt:.1f}s] topics with notes: {sum(1 for f in out.get('memo_findings') or [] if f.get('status') != 'unknown')}")
        else:
            print(f"[answer {answers}: NOTES FAILED after {dt:.1f}s] HTTP {st} {out.get('error')}")
        cap = s.get("capture") or {}; wf = s.get("workflow") or {}
        prev = {"workflow": {"title": wf.get("title", ""), "steps": wf.get("steps", []), "connections": wf.get("connections", []),
                             "open_questions": wf.get("open_questions", [])},
                "memo_findings": cap.get("memo_findings") or [], "summary": cap.get("summary") or "",
                "focus": cap.get("focus") or "", "parking_lot": cap.get("parking_lot") or []}
        base2 = dict(base);
        if s.get("capture_token"): base2["capture_token"] = s["capture_token"]
        st, out, dt = c.post("/api/agent-team/workflow", dict(base2, previous_capture=prev, agent_run_id=uuid.uuid4().hex), label="live.map", timeout=520)
        if st == 200 and out.get("workflow"):
            s["workflow"] = out["workflow"]; s["workflow_revision"] = s.get("revision")
            print(f"[answer {answers}: map in {dt:.1f}s] {len(out['workflow'].get('steps', []))} steps, {len(out['workflow'].get('connections', []))} connections")
        else:
            print(f"[answer {answers}: MAP FAILED after {dt:.1f}s] HTTP {st} {out.get('error')}")
        c.save()
        if answers >= a.max:
            break
    s["finished"] = now(); c.save()
    cmd_show(a)


def draft_body(c):
    s = c.s
    cap = s.get("capture") or {}; wf = s.get("workflow") or s.get("workflow_shown") or {}
    prev = {"workflow": {"title": wf.get("title", ""), "steps": wf.get("steps", []), "connections": wf.get("connections", []),
                         "open_questions": wf.get("open_questions", [])},
            "memo_findings": cap.get("memo_findings") or [], "summary": cap.get("summary") or "",
            "focus": cap.get("focus") or "", "parking_lot": cap.get("parking_lot") or []}
    body = c.snapshot("answer", {"previous_capture": prev})
    body.pop("conversation_token", None); body.pop("action", None)
    return body


def cmd_prepare(a):
    """What the page sends when the participant has wrapped up: the first half of the draft, ahead of the click."""
    c = Case(a.case)
    st, out, dt = c.post("/api/draft", {**draft_body(c), "prepare_only": True}, label="draft.prepare", timeout=600)
    c.save()
    print(f"[prepare in {dt:.1f}s] HTTP {st} {out}")


def cmd_draft(a):
    """Review > Create draft, as the page sends it: the snapshot plus the notes and map it holds."""
    c = Case(a.case); s = c.s
    body = draft_body(c)
    st, out, dt = c.post("/api/draft", body, label="draft", timeout=1160)
    if st != 200:
        s["draft_error"] = {"status": st, "error": out.get("error"), "code": out.get("code")}
        c.save(); print(f"CREATE DRAFT FAILED after {dt:.1f}s: HTTP {st} {out.get('error')}"); return
    d = out.get("draft") or {}
    s["draft"] = d
    s["draft_meta"] = {k: out.get(k) for k in ("coverage_assessment", "generated_by", "audit", "draft_audit", "validation", "document_evidence") if out.get(k) is not None}
    s["draft_keys"] = sorted(out.keys())
    c.save()
    print(f"[draft in {dt:.1f}s] title: {d.get('title')}")
    print("overview:", (d.get("overview") or "")[:1200])
    print("trigger:", d.get("trigger"))
    for k in ("inputs", "outputs", "exceptions", "controls", "open_questions", "validation_notes"):
        print(f"{k}:"); [print("  -", x) for x in (d.get(k) or [])]
    print("steps:")
    for x in d.get("steps") or []:
        print(f"  {x.get('id')} [{x.get('type')}] {x.get('title')} | actor={x.get('actor') or '-'} | system={x.get('system') or '-'} | {x.get('description') or ''}")
    for e in d.get("connections") or []:
        print(f"    {e.get('from')} -> {e.get('to')}" + (f"  [{e.get('label')}]" if e.get("label") else ""))
    print("memo topics:")
    for f in d.get("memo_summary") or []:
        print(f"  - [{f.get('status')}] {f.get('key')}: {f.get('answer')}")
    for v in d.get("variations") or []:
        print("  variation:", json.dumps(v)[:400])


def cmd_waitmap(a):
    c = Case(a.case); s = c.s
    t0 = next((e["at"] - e["seconds"] for e in reversed(s["events"]) if e["kind"] == "wrap.sync"), now())
    state = c.poll(t0, a.mapwait, want_notes=False, tag="wrap")
    s["finished"] = now(); c.save()
    print(f"map: {state}")
    cmd_show(a)


def graph_checks(wf):
    steps = wf.get("steps") or []; conns = wf.get("connections") or []
    ids = [x["id"] for x in steps]; out = {i: [] for i in ids}; inc = {i: [] for i in ids}
    for e in conns:
        if e["from"] in out and e["to"] in inc: out[e["from"]].append(e); inc[e["to"]].append(e)
    by = {x["id"]: x for x in steps}
    comp = {}; n = 0
    for i in ids:
        if i in comp: continue
        n += 1; stack = [i]
        while stack:
            x = stack.pop()
            if x in comp: continue
            comp[x] = n
            stack += [e["to"] for e in out[x]] + [e["from"] for e in inc[x]]
    types = {}
    for x in steps: types[x.get("type")] = types.get(x.get("type"), 0) + 1
    entries = [i for i in ids if not inc[i]]; exits = [i for i in ids if not out[i]]
    return {"steps": len(steps), "connections": len(conns), "types": types, "components": n,
            "isolated_steps": [i for i in ids if not inc[i] and not out[i]],
            "entry_points": entries, "typed_start": [i for i in ids if by[i].get("type") == "start"],
            "exit_points": exits, "typed_end": [i for i in ids if by[i].get("type") == "end"],
            "decisions_with_under_two_exits": [i for i in ids if by[i].get("type") == "decision" and len(out[i]) < 2],
            "decision_exits_without_label": [f"{e['from']}->{e['to']}" for i in ids if by[i].get("type") == "decision" for e in out[i] if not (e.get("label") or "").strip()],
            "non_decision_with_multiple_exits": [i for i in ids if by[i].get("type") not in ("decision", "parallel_split") and len(out[i]) > 1],
            "steps_without_actor": [i for i in ids if not (by[i].get("actor") or "").strip() and by[i].get("type") not in ("start", "end", "merge")],
            "actors": sorted({(x.get("actor") or "").strip() for x in steps if (x.get("actor") or "").strip()}),
            "open_questions": len(wf.get("open_questions") or [])}


def cmd_show(a):
    c = Case(a.case); s = c.s
    cap = s.get("capture") or {}
    print("\n=== NOTES ===")
    print("summary:", cap.get("summary"))
    for f in cap.get("memo_findings") or []:
        print(f"- [{f.get('status')}] {f.get('key')}: {f.get('answer')}")
    for x in cap.get("connections_out") or []:
        print(f"- link: {x.get('relationship_type')} -> {x.get('counterpart')} when {x.get('condition')}")
    wf = s.get("workflow")
    print("\n=== WORKFLOW MAP ===" + ("" if wf else " (none produced)"))
    if wf:
        current = s.get("workflow_revision") == s.get("revision")
        print(f"title: {wf.get('title')}  (drawn for the latest answers: {current})")
        for x in wf.get("steps", []):
            print(f"{x['id']} [{x.get('type')}] {x.get('title')} | actor={x.get('actor') or '-'} | system={x.get('system') or '-'} | {x.get('description') or ''}")
        for e in wf.get("connections", []):
            print(f"  {e['from']} -> {e['to']}" + (f"  [{e.get('label')}]" if e.get("label") else ""))
        for q in wf.get("open_questions", []):
            print("  open question:", q if isinstance(q, str) else json.dumps(q))
        g = graph_checks(wf); s["graph_checks"] = g; c.save()
        print("\n=== GRAPH CHECKS ===\n" + json.dumps(g, indent=1))


def cmd_timings(a):
    c = Case(a.case)
    print(json.dumps([e for e in c.s["events"]], indent=1))


def timing_summary(s):
    ev = s.get("events") or []
    def secs(kind, ok=True):
        return [e["seconds"] for e in ev if e["kind"] == kind and "seconds" in e and (not ok or e.get("status", 200) in (200, 202))]
    def med(v):
        v = sorted(v); return round(v[len(v) // 2], 1) if v else None
    q = secs("question")
    notes = [e["seconds"] for e in ev if e["kind"].endswith(".notes_ready")]
    shown = [e for e in ev if e["kind"].endswith(".map_shown")]
    ready = [e for e in ev if e["kind"].endswith(".map_ready")]
    users = sum(1 for t in s.get("turns", []) if t["role"] == "user")
    return {"answers": users, "question_seconds": [round(x, 1) for x in q], "question_median": med(q), "question_max": round(max(q), 1) if q else None,
            "notes_ready_seconds": [round(x, 1) for x in notes], "notes_median": med(notes),
            "answers_with_notes_before_next_answer": len(notes),
            "map_events": [{"kind": e["kind"], "seconds": e["seconds"], "audited": e.get("audited"), "answers_behind": e.get("answers_behind"), "steps": e.get("steps")} for e in shown + ready],
            "notes_errors": [e for e in ev if e["kind"].endswith(".notes_error")],
            "map_errors": [e for e in ev if e["kind"].endswith(".map_error")],
            "left_pending": [{"kind": e["kind"], "notes": e.get("notes_state"), "map": e.get("map_state"), "seconds": e.get("seconds")} for e in ev if e["kind"].endswith(".left_pending")],
            "transcribe": [{"seconds": e["seconds"], "audio_seconds": e.get("audio_seconds"), "wer": e.get("wer")} for e in ev if e["kind"] == "transcribe"],
            "documents": [{k: e.get(k) for k in ("kind", "seconds", "file", "status", "phase", "disposition", "error", "chunks", "bytes")} for e in ev if e["kind"].startswith("doc.")],
            "wrap": [{k: e.get(k) for k in ("kind", "seconds", "status", "reply_kind", "workflow_state", "workflow_error", "error")} for e in ev if e["kind"].startswith("wrap.")],
            "draft": [{k: e.get(k) for k in ("seconds", "status", "error")} for e in ev if e["kind"] == "draft"],
            "failed_requests": [{k: e.get(k) for k in ("kind", "seconds", "status", "retries", "error")} for e in ev if e.get("error") or e.get("status") not in (None, 200, 202) or e.get("retries")]}


def cmd_report(a):
    """Everything about a case in one readable page: transcript with turn ids, timings, notes, map, draft."""
    c = Case(a.case); s = c.s
    print(f"CASE {s['case']} | process: {s['context']['process_name']} | port {s['port']}")
    print("\n=== TRANSCRIPT (turn id, speaker) ===")
    for t in s["turns"]:
        who = "INTERVIEWER" if t["role"] == "assistant" else "PARTICIPANT"
        print(f"[{t['id']}] {who}: {t['text']}\n")
    print("=== TIMINGS (seconds) ===")
    print(json.dumps(timing_summary(s), indent=1))
    if s.get("documents"):
        print("\n=== FILES ===")
        for d in s["documents"]:
            an = d.get("analysis") or {}
            print(f"- {d.get('name')} | {d.get('kind')} | {d.get('size')} bytes | status={d.get('status')} | chunks={d.get('chunk_count')} | review phase={an.get('phase')} disposition={an.get('disposition')} | coverage={json.dumps(d.get('coverage'))[:300]} | error={d.get('error') or an.get('error')}")
    cmd_show(a)
    d = s.get("draft")
    print("\n=== DRAFT ===" + ("" if d else f" (none: {json.dumps(s.get('draft_error'))})"))
    if d:
        print("title:", d.get("title")); print("overview:", d.get("overview")); print("trigger:", d.get("trigger"))
        for k in ("inputs", "outputs", "exceptions", "controls", "open_questions", "validation_notes"):
            print(f"{k}:"); [print("  -", x) for x in (d.get(k) or [])]
        print("steps:")
        for x in d.get("steps") or []:
            print(f"  {x.get('id')} [{x.get('type')}] {x.get('title')} | actor={x.get('actor') or '-'} | system={x.get('system') or '-'} | {x.get('description') or ''}")
        for e in d.get("connections") or []:
            print(f"    {e.get('from')} -> {e.get('to')}" + (f"  [{e.get('label')}]" if e.get("label") else ""))
        print("memo topics:")
        for f in d.get("memo_summary") or []:
            print(f"  - [{f.get('status')}] {f.get('key')}: {f.get('answer')}")
        for v in d.get("variations") or []:
            print("  variation:", json.dumps(v)[:500])


def main():
    p = argparse.ArgumentParser(); sub = p.add_subparsers(dest="cmd", required=True)
    x = sub.add_parser("start"); x.add_argument("case"); x.add_argument("--port", type=int, required=True); x.add_argument("--name", required=True); x.add_argument("--objective"); x.add_argument("--background"); x.add_argument("--nofirst", action="store_true")
    x = sub.add_parser("answer"); x.add_argument("case"); x.add_argument("text", nargs="?", default=""); x.add_argument("--file"); x.add_argument("--voice", action="store_true"); x.add_argument("--rate", type=int, default=185); x.add_argument("--think", type=float, default=45)
    x = sub.add_parser("skip"); x.add_argument("case"); x.add_argument("--think", type=float, default=20)
    x = sub.add_parser("upload"); x.add_argument("case"); x.add_argument("files", nargs="+"); x.add_argument("--readwait", type=float, default=600); x.add_argument("--think", type=float, default=60)
    x = sub.add_parser("wrap"); x.add_argument("case"); x.add_argument("--mapwait", type=float, default=450)
    x = sub.add_parser("waitmap"); x.add_argument("case"); x.add_argument("--mapwait", type=float, default=540)
    x = sub.add_parser("show"); x.add_argument("case")
    x = sub.add_parser("draft"); x.add_argument("case")
    x = sub.add_parser("prepare"); x.add_argument("case")
    x = sub.add_parser("report"); x.add_argument("case")
    x = sub.add_parser("live"); x.add_argument("case"); x.add_argument("--source", required=True); x.add_argument("--port", type=int, required=True); x.add_argument("--max", type=int, default=6)
    x = sub.add_parser("timings"); x.add_argument("case")
    a = p.parse_args()
    if a.cmd == "start": cmd_start(a)
    elif a.cmd == "answer": cmd_answer(a)
    elif a.cmd == "skip": cmd_answer(a, action="skip")
    elif a.cmd == "upload": cmd_upload(a)
    elif a.cmd == "wrap": cmd_wrap(a)
    elif a.cmd == "waitmap": cmd_waitmap(a)
    elif a.cmd == "show": cmd_show(a)
    elif a.cmd == "draft": cmd_draft(a)
    elif a.cmd == "prepare": cmd_prepare(a)
    elif a.cmd == "report": cmd_report(a)
    elif a.cmd == "live": cmd_live(a)
    elif a.cmd == "timings": cmd_timings(a)


if __name__ == "__main__":
    main()
