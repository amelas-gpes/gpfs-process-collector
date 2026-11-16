/* App-owned observations. The transport never wraps its own POST or reads a
 * request's headers/body or a response stream into the trace. */
(() => {
  "use strict";
  const w = window;
  const producer = globalThis.crypto?.randomUUID?.();
  if (!producer || typeof w.fetch !== "function") return;
  const send = w.fetch.bind(w);
  const encoder = new TextEncoder();
  const pending = [];
  const observed = new WeakMap();
  const recordLimit = 54 * 1024;
  const queueLimit = 2 * 1024 * 1024;
  let queuedBytes = 0, sequence = 0, timer, sending = false, configured = false;
  let queueGeneration = 0;
  let enabled = true, content = false, csrf, interview, failures = 0, dropped = 0;
  const artifacts = new Set(["draft.edited","draft.rendered","workflow.applied","notes.applied"]);

  // A part keeps its full field path so the receiver applies the same exclusion
  // rules as for the original object. Do not split text or serialize it into an
  // opaque string. One exceptionally large item retains an explicit size marker.
  function artifactParts(detail) {
    const parts = [];
    const container = detail.draft ? "draft" : detail.graph ? "graph" : null;
    const fields = container ? detail[container] : detail;
    for (const [field,value] of Object.entries(fields)) {
      if (value === undefined) continue;
      const add = (slice,start) => parts.push({
        metadata:{container, field, start, ...(Array.isArray(value) ? {total:value.length} : {})},
        detail:container ? {[container]:{[field]:slice}} : {[field]:slice}
      });
      if (!Array.isArray(value) || !value.length) { add(value,0); continue; }
      let start=0, bytes=0;
      value.forEach((item,index) => {
        const size = encoder.encode(JSON.stringify(item) ?? "null").length + 1;
        if (bytes && size + bytes > 32 * 1024) {
          add(value.slice(start,index),start);start=index;bytes=0;
        }
        bytes += size;
      });
      add(value.slice(start),start);
    }
    return parts;
  }

  function schedule() {
    if (!configured || !enabled || sending || timer !== undefined || !pending.length) return;
    timer = w.setTimeout(() => { timer = undefined; void flush(); }, failures ? Math.min(10000, 500 * 2 ** failures) : 100);
  }

  function record(type, metadata = {}, detail, refs = {}) {
    if (!enabled) return;
    try {
      const payload = {...metadata};
      if (detail !== undefined) {
        if (content) payload.content = typeof detail === "function" ? detail() : detail;
        else payload.content_omitted = configured ? "metadata_mode" : "configuration_pending";
      }
      const row = {type, seq: ++sequence, at: new Date().toISOString(), payload};
      const identity = Object.hasOwn(refs, "interview_id") ? refs.interview_id : interview?.();
      if (identity) row.interview_id = identity;
      if (typeof refs.turn_id === "string" && /^[A-Za-z0-9_-]{1,80}$/.test(refs.turn_id)) row.turn_id = refs.turn_id;
      if (refs.operation_id) row.operation_id = refs.operation_id;
      let data = JSON.stringify(row), bytes = encoder.encode(data).length;
      let parts;
      if (bytes > recordLimit) {
        if (artifacts.has(type) && payload.content) parts = artifactParts(payload.content);
        row.payload = parts ? {...metadata, content_parts:parts.length, original_event_bytes:bytes}
          : {...metadata, content_omitted:"event_size_limit", original_event_bytes:bytes};
        data = JSON.stringify(row); bytes = encoder.encode(data).length;
      }
      if (bytes > recordLimit || pending.length >= 2048 || queuedBytes + bytes > queueLimit) {
        dropped++;
        return;
      }
      pending.push({data, bytes}); queuedBytes += bytes;
      for (const part of parts || [])
        record("artifact.part", {source_seq:row.seq,...part.metadata}, part.detail, refs);
      schedule();
    } catch { dropped++; }
  }

  async function flush(leaving = false) {
    if (sending || !enabled || !configured || !pending.length) return;
    sending = true;
    try {
      const rows = [];
      let bytes = 0;
      const limit = leaving ? 60 * 1024 : 220 * 1024;
      const generation = queueGeneration;
      for (const row of pending) {
        if (rows.length >= 64 || bytes + row.bytes + 1 > limit) break;
        rows.push(row.data); bytes += row.bytes + 1;
      }
      const response = await send("/api/trace/events", {method:"POST", credentials:"same-origin",
        keepalive:leaving, headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},
        body:'{"producer_id":' + JSON.stringify(producer) + ',"events":[' + rows.join(",") + ']}'});
      let lost = 0;
      if (!response.ok) {
        // An invalid batch cannot block all later observations.
        if (response.status === 400 || response.status === 413) {
          lost = rows.length;
        } else throw new Error("trace_unavailable");
      } else {
        const receipt = await response.json();
        if (receipt?.received === rows.length && Number.isInteger(receipt.accepted))
          lost = Math.max(0, rows.length - receipt.accepted);
      }
      if (generation !== queueGeneration) return;
      for (const item of pending.splice(0, rows.length)) queuedBytes -= item.bytes;
      failures = lost ? Math.min(failures + 1, 6) : 0;
      dropped += lost;
      if (!lost && dropped) {
        const count = dropped; dropped = 0;
        record("trace.dropped", {count});
      }
    } catch { failures = Math.min(failures + 1, 6); }
    finally { sending = false; schedule(); }
  }

  function configure(settings, getToken, getInterview) {
    const changed = !configured || content !== (settings?.content === true) || enabled !== (settings?.enabled === true);
    if (!settings?.enabled || (content && !settings.content)) {
      queueGeneration++;
      dropped = settings?.enabled ? dropped + pending.length : 0;
      pending.length = 0; queuedBytes = 0;
    }
    configured = true; enabled = settings?.enabled === true;
    content = enabled && settings.content === true; csrf = getToken; interview = getInterview;
    if (!enabled) return;
    if (changed) record("trace.configured", {content_enabled:content});
    schedule();
  }

  // Wrap same-origin app APIs only. Preserve external/Request-object fetch semantics.
  w.fetch = async function(input, init) {
    if (!enabled || typeof input !== "string" || !/^\/api\/[a-z0-9/-]+$/.test(input) || input === "/api/trace/events") return send(input, init);
    let options = init, refs;
    try {
      const operation = globalThis.crypto.randomUUID(), identity = interview?.() || null;
      refs = {operation_id:operation, interview_id:identity};
      const headers = new Headers(init?.headers);
      const turn = headers.get("X-Trace-Turn");
      if (turn) refs.turn_id = turn;
      headers.set("X-Trace-Operation", operation); headers.set("X-Trace-Producer", producer);
      if (identity) headers.set("X-Trace-Interview", identity);
      options = {...init, headers};
      record("http.dispatched", {path:input, method:init?.method || "GET"}, undefined, refs);
    } catch { return send(input, init); }
    try {
      const response = await send(input, options);
      observed.set(response, refs);
      record("http.response_headers", {path:input, status:response.status}, undefined, refs);
      return response;
    } catch (error) {
      record("http.rejected", {path:input, aborted:options?.signal?.aborted === true}, undefined, refs);
      throw error;
    }
  };
  function link(target, source) {
    const refs = observed.get(source);
    if (refs && target && typeof target === "object") observed.set(target, refs);
  }
  w.CollectorRawTrace = {record, configure, flush, link, references:value=>observed.get(value)};

  const staticIds = new Set(Array.from(document.querySelectorAll("[id]"), element => element.id));
  for (const name of ["click","change","input","submit","cancel","close","toggle","drop"]) {
    document.addEventListener(name, event => {
      const target = event.target?.closest?.("button,input,textarea,select,summary,dialog,form,a,[role=button]") || event.target;
      if (!target?.tagName) return;
      const data = {tag:target.tagName.toLowerCase()};
      if (staticIds.has(target.id)) data.control = target.id;
      if (target.type === "checkbox" || target.type === "radio") data.checked = Boolean(target.checked);
      if (target.tagName === "DIALOG" || target.tagName === "DETAILS") data.open = Boolean(target.open);
      let selection;
      if (name === "input" || name === "change") {
        if (target.tagName === "SELECT") {
          data.selected_index = target.selectedIndex;
          if (target.id === "theme-select" || target.id === "voice-select") selection = {value:target.value};
        } else if (target.type !== "checkbox" && target.type !== "radio") data.value_omitted = "transient_input";
      }
      record("ui." + name, data, selection);
    }, true);
  }
  document.addEventListener("visibilitychange", () => {
    record("page.visibility", {state:document.visibilityState});
    if (document.hidden) void flush(true);
  });
  w.addEventListener("pagehide", event => { record("page.hide", {persisted:event.persisted}); void flush(true); });
  w.addEventListener("pageshow", event => record("page.show", {persisted:event.persisted}));
  w.addEventListener("error", event => record("page.error", {line:event.lineno, column:event.colno}));
  w.addEventListener("unhandledrejection", () => record("page.unhandled_rejection"));
  record("page.script_loaded", {state:document.readyState});
})();
