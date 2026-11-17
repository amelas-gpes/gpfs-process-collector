/* Public work status only. This view has no provider, timer or audio access. */
(function (global) {
  "use strict";
  const ROLES = {
    lead_interviewer: {name:"Lead interviewer", description:"Asks one focused question and keeps the conversation moving.", running:"Preparing the next response", completed:"Interviewer response prepared"},
    coverage_reviewer: {name:"Coverage reviewer", description:"Checks whether each topic can be explained clearly from the evidence.", running:"Checking topic evidence", completed:"Topic evidence check finished"},
    process_reviewer: {name:"Process reviewer", description:"Checks the steps, decisions, handoffs and unresolved inconsistencies.", running:"Reviewing the process account", completed:"Process review finished"},
    document_analyst: {name:"Document analyst", description:"Reads the supplied material and identifies relevant process evidence.", running:"Reviewing supplied material", completed:"Document review finished"}
  };
  const CORE = ["lead_interviewer","coverage_reviewer","process_reviewer"];
  const STATUSES = new Set(["idle","pending","queued","running","completed","blocked","error"]);
  const BADGES = {idle:"Standing by",pending:"Queued",queued:"Queued",running:"Working",completed:"Done",blocked:"Waiting",error:"Issue"};
  const REASONS = {
    cancelled:"This run was cancelled.", stale_revision:"The conversation changed. These results are no longer current.",
    call_budget_exhausted:"The review limit was reached for this run.", role_already_invoked:"This review has already been requested.",
    role_failed:"This review could not finish.", role_not_requested:"This review was not needed for this run.",
    invalid_result:"The review could not return a usable result.", prior_result_reused:"The earlier reviewed result was reused; this role was not called again."
  };
  let instance = 0;
  const safeText = (value, limit=240) => typeof value==="string" ? value.slice(0,limit) : "";
  function create(root) {
    if(!root?.ownerDocument)throw new TypeError("The interview team needs a mounted element.");
    const doc=root.ownerDocument, id=`agent-team-${++instance}`;
    let disposed=false, runId=null, revision=null, eventSequence=-1, signature="", statusSignature="";
    const retired=new Set(), cards=new Map();
    const make=(tag,className,text)=>{const node=doc.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node;};
    const shell=make("details","agent-team-shell");
    const summary=make("summary","agent-team-summary");
    const heading=make("span","agent-team-heading","Interview team");heading.id=id;
    const aggregate=make("span","agent-team-aggregate","Standing by");
    const disclosure=make("span","agent-team-disclosure");disclosure.setAttribute("aria-hidden","true");
    summary.append(heading,aggregate,disclosure);shell.append(summary);
    const intro=make("p","agent-team-intro","One interviewer speaks. The reviewers check the account before it is marked complete.");shell.append(intro);
    const grid=make("div","agent-team-grid");grid.setAttribute("role","list");grid.setAttribute("aria-label","Team roles");shell.append(grid);
    for(const [role,config] of Object.entries(ROLES)){
      const item=make("div","agent-team-item");item.setAttribute("role","listitem");item.dataset.role=role;
      const details=make("details","agent-card");details.dataset.status="idle";
      const trigger=make("summary","agent-card-summary");
      const line=make("span","agent-card-heading"),name=make("span","agent-card-name",config.name),badge=make("span","agent-card-badge",BADGES.idle);
      line.append(name,badge);
      const activity=make("span","agent-card-activity");trigger.append(line,activity);details.append(trigger);
      const body=make("div","agent-card-body"),description=make("p","agent-card-description",config.description),detail=make("p","agent-card-detail");
      const caveat=make("p","agent-card-caveat","A finished check can still leave open topics or questions.");
      body.append(description,detail,caveat);details.append(body);item.append(details);grid.append(item);
      cards.set(role,{item,details,trigger,badge,activity,detail,caveat});
    }
    const recent=make("div","agent-team-recent"),recentHeading=make("h3","agent-team-recent-heading","Recent completed work"),recentList=make("ul","agent-team-results");
    recent.append(recentHeading,recentList);recent.hidden=true;shell.append(recent);
    const announcement=make("p","agent-team-announcement");announcement.setAttribute("role","status");announcement.setAttribute("aria-live","polite");announcement.setAttribute("aria-atomic","true");
    root.replaceChildren(shell,announcement);root.setAttribute("aria-labelledby",id);

    function render(snapshot={},options={}) {
      if(disposed||!snapshot||typeof snapshot!=="object")return false;
      const nextId=safeText(snapshot.run_id,128),nextRevision=safeText(snapshot.revision,128);
      if(!Array.isArray(snapshot.agents??[]))return false;
      const supplied=snapshot.agents||[],byRole=new Map();
      if(supplied.length>4)return false;
      for(const row of supplied){
        if(!row||!Object.hasOwn(ROLES,row.role)||!STATUSES.has(row.status)||byRole.has(row.role))return false;
        byRole.set(row.role,row);
      }
      const events=Array.isArray(snapshot.events)?snapshot.events.filter(event=>event&&Object.hasOwn(ROLES,event.role)&&STATUSES.has(event.status)&&Number.isSafeInteger(event.sequence)&&event.sequence>=0).slice(-64):[];
      const nextSequence=events.reduce((highest,event)=>Math.max(highest,event.sequence),-1);
      // Only the request owner can explicitly reselect a cached, older run.
      // A status snapshot cannot opt itself out of stale-run protection.
      if(nextId&&nextId!==runId&&retired.has(nextId)&&options.reuse!==true)return false;
      if(nextId===runId&&((revision&&nextRevision&&revision!==nextRevision)||nextSequence<eventSequence))return false;
      if(nextId!==runId){
        retired.delete(nextId);
        if(runId){retired.add(runId);if(retired.size>64)retired.delete(retired.values().next().value);}
        if(!nextId)retired.clear();
        runId=nextId;revision=nextRevision;eventSequence=-1;
      }
      eventSequence=Math.max(eventSequence,nextSequence);
      const normalized=Object.keys(ROLES).filter(role=>CORE.includes(role)||byRole.has(role)).map(role=>({role,...(byRole.get(role)||{status:"idle"})}));
      const fingerprint=JSON.stringify([nextId,nextRevision,snapshot.stale===true,snapshot.cancelled===true,normalized,events]);
      if(fingerprint===signature)return true;
      signature=fingerprint;
      root.dataset.hasDocuments=String(byRole.has("document_analyst"));
      for(const [role,card] of cards){
        const row=normalized.find(item=>item.role===role),visible=Boolean(row);
        if(!visible&&card.item.contains(doc.activeElement))summary.focus();
        card.item.hidden=!visible;if(!visible)continue;
        const config=ROLES[role],status=row.status;
        const historical=["cancelled","stale_revision"].includes(row.reason_code);
        card.details.dataset.status=historical?"idle":status;
        const blocked={cancelled:"Cancelled",stale_revision:"Superseded",call_budget_exhausted:"Not run",role_already_invoked:"Not run"};
        card.badge.textContent=status==="blocked"?(blocked[row.reason_code]||BADGES.blocked):BADGES[status];
        const suppliedLabel=safeText(row.label,180);
        const label=suppliedLabel&&suppliedLabel!==config.name?suppliedLabel:status==="running"?config.running:status==="completed"?config.completed:status==="error"?(role==="lead_interviewer"?"Interviewer response did not finish":"Review did not finish"):"";
        card.activity.textContent=label;
        card.activity.hidden=!label;
        card.detail.textContent=REASONS[row.reason_code]||safeText(row.detail,600);
        card.detail.hidden=!card.detail.textContent;
        card.caveat.hidden=status!=="completed"||role==="lead_interviewer";
      }
      const working=normalized.filter(row=>row.status==="running"),waiting=normalized.filter(row=>["pending","queued"].includes(row.status));
      const attention=normalized.some(row=>["error","blocked"].includes(row.status)&&!["cancelled","stale_revision","role_already_invoked"].includes(row.reason_code));
      aggregate.textContent=snapshot.stale?"Earlier context":snapshot.cancelled?"Run cancelled":working.length?`${working.length} ${working.length===1?"agent":"agents"} working`:attention?"Needs attention":waiting.length?"Reviews queued":normalized.some(row=>row.status==="completed")?"Up to date":"Standing by";
      root.dataset.state=snapshot.stale||snapshot.cancelled?"idle":working.length?"running":attention?"attention":waiting.length?"queued":"idle";
      // Nothing has run yet: the strip has nothing to report and stays off the page until it does.
      root.dataset.quiet=String(aggregate.textContent==="Standing by");
      const completed=events.filter(event=>event.status==="completed").filter((item,index,rows)=>index===0||item.role!==rows[index-1].role||item.label!==rows[index-1].label).slice(-3).reverse();
      recentList.replaceChildren(...completed.map(event=>{
        const item=make("li","agent-team-result"),role=make("span","agent-team-result-role",ROLES[event.role].name);
        const suppliedLabel=safeText(event.label,180),result=make("span","agent-team-result-text",suppliedLabel&&suppliedLabel!==ROLES[event.role].name?suppliedLabel:ROLES[event.role].completed);
        item.append(role,result);return item;
      }));recent.hidden=!completed.length;
      const nextStatuses=JSON.stringify([nextId,snapshot.stale===true,snapshot.cancelled===true,normalized.map(row=>[row.role,row.status])]);
      if(statusSignature&&nextStatuses!==statusSignature){
        const activeNames=working.map(row=>ROLES[row.role].name).join(" and ");
        announcement.textContent=activeNames?`${activeNames} working.`:aggregate.textContent+".";
      }
      statusSignature=nextStatuses;
      global.CollectorRawTrace?.record("team.rendered",{state:root.dataset.state,stale:snapshot.stale===true,
        cancelled:snapshot.cancelled===true,roles:normalized.map(row=>({role:row.role,status:row.status,reason_code:row.reason_code}))},
        {aggregate:aggregate.textContent});
      return true;
    }
    render({agents:[]});
    return {render,dispose(){if(disposed)return;disposed=true;root.replaceChildren();root.removeAttribute("aria-labelledby");retired.clear();cards.clear();}};
  }
  global.CollectorAgentTeam={create};
})(window);
