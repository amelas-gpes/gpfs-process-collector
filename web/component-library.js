/* Read-only catalog. The map, inspector and library share the same local artwork. */
(function (scope) {
  "use strict";
  const meaning = {
    start:"An explicitly reported trigger starts this route.", end:"An explicitly reported outcome closes this route.",
    activity:"A task performed by a person or system.", decision:"A test or choice with reported outcomes on its outgoing routes.",
    parallel_split:"Every named branch proceeds independently.", parallel_join:"All reported prerequisites must arrive before work continues.",
    merge:"Any one of the alternative incoming routes can continue.", wait:"Work pauses until a reported event or condition occurs.",
    subprocess:"A named procedure whose internal steps are represented as one component.",
    document:"A step creates, handles or sends a document.", data_store:"A step reads from or writes to a persistent register or database."
  };
  function node(tag, css, text) {
    const item = document.createElement(tag);
    if (css) item.className = css;
    if (text) item.textContent = text;
    return item;
  }
  function records() {
    const business = scope.CollectorComponents.all.map(variant => ({
      key:variant.id, label:variant.label, family:variant.family, description:variant.description,
      detail:scope.CollectorComponentArt?.detail(variant.id), type:"activity", variant
    }));
    const structural = Object.entries(scope.CollectorWorkflow.types).map(([type, meta]) => ({
      key:"type/" + type, type, label:meta.label, family:"Workflow symbols",description:meaning[type]
    }));
    return [...business,...structural];
  }
  function create() {
    const items = records();
    const dialog = node("dialog","cl-dialog");
    dialog.setAttribute("aria-labelledby","cl-title");
    const header = node("header","cl-header"), title = node("h2","","Component library");
    title.id = "cl-title";
    const close = node("button","dialog-close");
    close.type = "button"; close.setAttribute("aria-label","Close component library");
    close.addEventListener("click",()=>dialog.close());
    header.append(title,close);
    const bar = node("div","cl-toolbar"), search = node("input","cl-search"), family = node("select","cl-family");
    search.type = "search"; search.placeholder = "Search components";
    search.setAttribute("aria-label","Search components");
    family.setAttribute("aria-label","Component family");
    const all = node("option","","All families"); all.value = ""; family.append(all);
    for (const name of [...new Set(items.map(item=>item.family))].sort()) {
      const option = node("option","",name); option.value = name; family.append(option);
    }
    const count = node("output","cl-count"); count.setAttribute("aria-live","polite");
    bar.append(search,family,count);
    const body = node("div","cl-body"), grid = node("div","cl-grid"), detail = node("section","cl-detail");
    grid.setAttribute("role","group"); grid.setAttribute("aria-label","Components");
    detail.setAttribute("aria-label","Component design");
    body.append(grid,detail); dialog.append(header,bar,body); document.body.append(dialog);
    let opener, fallbackFocus, selected, observer, applyDesign, stepType;
    function preview(host, record) {
      scope.CollectorWorkflowStage.createComponentPreview(host,{type:applyDesign ? stepType : record.type,variant:record.variant});
      host.setAttribute("aria-hidden","true");
    }
    function display(record, moveToDetail = false) {
      selected = record?.key;
      for (const tile of grid.querySelectorAll(".cl-tile")) tile.setAttribute("aria-pressed",String(tile.dataset.key===selected));
      detail.replaceChildren();
      detail.hidden = !record;
      if (!record) return;
      const art = node("div","cl-study"); preview(art,record);
      const copy = node("div","cl-copy"), familyName = node("p","cl-eyebrow",record.family);
      const name = node("h3","",record.label); name.tabIndex = -1;
      copy.append(familyName,name,node("p","cl-description",record.description));
      if (record.detail) copy.append(node("h4","cl-eyebrow","Design detail"),node("p","cl-design-notes",record.detail));
      if (applyDesign) {
        const actions = node("div","cl-actions");
        for (const [label,id] of [["Use this design",record.key],["Use automatic design",null]]) {
          const action = node("button","",label); action.type = "button";
          action.addEventListener("click",()=>{
            if (applyDesign(id) !== false) { dialog.close(); return; }
            actions.replaceChildren(node("p","","The step has changed. Close the library and select the step again."));
            actions.setAttribute("role","status");
          });
          actions.append(action);
        }
        copy.append(actions);
      }
      detail.append(art,copy);
      if (moveToDetail && scope.matchMedia("(max-width: 680px)").matches) {
        detail.scrollIntoView({block:"nearest"});
      }
    }
    function filter() {
      observer?.disconnect(); grid.replaceChildren();
      const words = search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      const matches = items.filter(item => (!applyDesign || item.variant) && (!family.value || family.value===item.family) &&
        words.every(word => (item.label+" "+item.family+" "+item.description).toLowerCase().includes(word)));
      count.textContent = matches.length + (matches.length===1 ? " design" : " designs");
      if (!matches.length) grid.append(node("p","cl-empty","No components match this search."));
      const visibleRecords = new Map(matches.map(record=>[record.key,record]));
      observer = scope.IntersectionObserver ? new scope.IntersectionObserver((entries,self)=>{
        for (const entry of entries) if (entry.isIntersecting) {
          const host = entry.target; self.unobserve(host);
          if (!host.firstChild && host.isConnected) preview(host,visibleRecords.get(host.dataset.key));
        }
      },{root:grid,rootMargin:"100px"}) : null;
      for (const record of matches) {
        const tile = node("button","cl-tile"), thumb = node("span","cl-thumb");
        tile.type = "button"; tile.dataset.key = thumb.dataset.key = record.key;
        tile.setAttribute("aria-label",record.label);
        tile.append(thumb,node("span","cl-tile-label",record.label)); grid.append(tile);
        if (observer) observer.observe(thumb); else preview(thumb,record);
        tile.addEventListener("click",()=>display(record,true));
      }
      display(matches.find(record=>record.key===selected) || matches[0]);
      grid.scrollTop = 0;
    }
    search.addEventListener("input",filter); family.addEventListener("change",filter);
    dialog.addEventListener("close",()=>{
      observer?.disconnect();
      grid.replaceChildren(); detail.replaceChildren();
      const target = opener?.isConnected ? opener : fallbackFocus;
      target?.focus({preventScroll:true}); applyDesign = null;
    });
    return function open({variant,type,opener:trigger,returnFocus,onApply,stepTitle}={}) {
      opener = trigger || document.activeElement;
      fallbackFocus = returnFocus; applyDesign = onApply; stepType = type || "activity";
      title.textContent = onApply ? "Choose a design for " + (stepTitle || "this step") : "Component library";
      for (const option of family.options) option.hidden = Boolean(onApply && option.value==="Workflow symbols");
      selected = variant?.id || (type ? "type/"+type : items[0]?.key);
      search.value = ""; family.value = "";
      if (!dialog.open) dialog.showModal();
      filter();
      for (const tile of grid.querySelectorAll(".cl-tile")) {
        if (tile.dataset.key===selected) { tile.scrollIntoView({block:"nearest"}); break; }
      }
      search.focus({preventScroll:true});
    };
  }
  let openLibrary;
  scope.CollectorComponentLibrary = {open(options) {
    openLibrary ||= create();
    openLibrary(options);
  }};
})(window);
