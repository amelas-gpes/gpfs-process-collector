"use strict";
// An excerpt that is a model's transcription of an image (origin "ai_visual_transcription",
// verified false) says so beside the text wherever it is shown or exported: the Assets source
// preview, the interview's source dialog, citation captions, the report export and the saved file.
// An excerpt taken from the file's own text carries no such mark.
// Real web/app.js and web/documents.js behind synthetic DOMs. No browser, provider or network.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const {setup,run}=require("./support/interview_page.cjs");
const web=name=>fs.readFileSync(path.join(__dirname,"..","web",name),"utf8");
let passed=0;
const check=async(name,fn)=>{try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}};
const NOTE="AI visual transcription is unverified; inspect the original before relying on it.";
const SUFFIX=" · AI transcription, unverified";
// As the server's catalog sends them (server.document_evidence_catalog): the mark is on `location`.
const IMAGE={id:"doc_limits_image_c1",document_id:"doc_limits",name:"carrier-claim-limits.png",label:"image",location:{image:true,requires_vision:false,origin:"ai_visual_transcription",verified:false},text:"Carrier | Service | Maximum claim per consignment\nNorthline | Standard | $2,875"};
const PAGE={id:"doc_returns_p3_c1",document_id:"doc_returns",name:"returns-procedure.pdf",label:"page 3",location:{page:3},text:"A return over $500 needs a supervisor's approval."};
const textOf=node=>typeof node==="string"?node:(node.textContent||"")+(node.children||[]).map(textOf).join("\n");
const all=node=>[node,...(node.children||[]).flatMap(all)];
function page(){
  const h=setup({expose:"normalizeDocumentEvidence,mergeDocumentEvidence,sourceCaption,showDocumentEvidence,jumpToTurn,normalizeDraft,markdown,memoMarkdown,sessionObject"});
  h.t.state.turns=[{id:"t001",role:"assistant",text:"How are claims limited?"},{id:"t002",role:"user",text:"The carrier table sets the maximum claim."}];
  h.load=sources=>{h.t.state.documentEvidence=h.t.mergeDocumentEvidence(sources);return h.t.state.documentEvidence;};
  return h;
}

run(async()=>{
  await check("the mark the server puts on an excerpt is kept, and only there",async()=>{
    const h=page(),[image,plain]=h.t.normalizeDocumentEvidence([IMAGE,PAGE]);
    assert.equal(image.origin,"ai_visual_transcription");assert.equal(image.verified,false);
    assert.deepEqual(Object.keys(plain),["id","document_id","name","label","text","retained_only","archived","disposition"],"An ordinary excerpt keeps the shape it had");
    assert.equal(Object.hasOwn(plain,"origin"),false);assert.equal(Object.hasOwn(plain,"verified"),false);
    // Either half of the mark is enough, on the location or on the excerpt itself (the saved-file shape).
    const variants=[{location:{origin:"ai_visual_transcription"}},{location:{verified:false}},{origin:"ai_visual_transcription"},{verified:false},{origin:"ai_visual_transcription",verified:false,location:{}}];
    for(const extra of variants){const [kept]=h.t.normalizeDocumentEvidence([{...PAGE,location:undefined,...extra}]);assert.equal(kept.origin,"ai_visual_transcription",JSON.stringify(extra));assert.equal(kept.verified,false,JSON.stringify(extra));}
    // Other origins, a verified transcription flag of true, and stray values are not the mark.
    for(const extra of [{location:{origin:"visual_placeholder"}},{location:{origin:"native_text",verified:true}},{origin:"AI_VISUAL_TRANSCRIPTION"},{verified:"false"},{verified:null},{location:null},{location:"ai_visual_transcription"}]){
      const [kept]=h.t.normalizeDocumentEvidence([{...PAGE,location:undefined,...extra}]);assert.equal(Object.hasOwn(kept,"origin"),false,JSON.stringify(extra));assert.equal(Object.hasOwn(kept,"verified"),false,JSON.stringify(extra));
    }
  });

  await check("captions of such an excerpt say it is an unverified AI transcription",async()=>{
    const h=page();h.load([IMAGE,PAGE,{...IMAGE,id:"doc_limits_image_c2",retained_only:true}]);
    assert.equal(h.t.sourceCaption(IMAGE.id),"carrier-claim-limits.png · image"+SUFFIX);
    assert.equal(h.t.sourceCaption(PAGE.id),"returns-procedure.pdf · page 3");
    assert.equal(h.t.sourceCaption("doc_limits_image_c2"),"carrier-claim-limits.png · image · saved excerpt"+SUFFIX);
    assert.equal(h.t.sourceCaption("context"),"Starting context");assert.equal(h.t.sourceCaption("t002"),h.t.sourceCaption("t002").replace(SUFFIX,""),"Answers are never marked");
  });

  await check("the source dialog puts the warning above the transcribed text",async()=>{
    const h=page();h.load([IMAGE,PAGE]);
    h.t.showDocumentEvidence(h.t.state.documentEvidence[0],null);
    const dialog=[...h.nodes.values()].find(node=>node.id==="document-evidence-dialog");assert.ok(dialog);assert.equal(dialog.open,true);
    const parts=all(dialog),note=parts.find(node=>node.className==="excerpt-note excerpt-origin"),excerpt=parts.find(node=>node.className==="excerpt-text");
    assert.ok(note,"The dialog carries a per-excerpt marker");assert.equal(note.textContent,NOTE);assert.equal(excerpt.textContent,IMAGE.text);
    assert.ok(parts.indexOf(note)<parts.indexOf(excerpt),"The warning is read before the text");
    assert.match(textOf(dialog),/carrier-claim-limits\.png · image · AI transcription, unverified/,"The dialog title says so as well");
    assert.match(textOf(dialog),/Confirm current practice and approval with the process owner\./,"The standing note stays");
    // An ordinary excerpt opened next shows no marker (the dialog is reused).
    h.t.jumpToTurn(PAGE.id);
    assert.equal(all(dialog).some(node=>/excerpt-origin/.test(node.className||"")),false);assert.doesNotMatch(textOf(dialog),/AI visual transcription|AI transcription/);assert.match(textOf(dialog),/supervisor's approval/);
  });

  await check("the report export marks the excerpt and every citation of it",async()=>{
    const h=page();h.load([IMAGE,PAGE]);
    h.t.state.draft=h.t.normalizeDraft({title:"Carrier claims",overview:"How claims are limited.",trigger:"A damaged consignment.",inputs:[],outputs:[],exceptions:[],controls:[],open_questions:[],validation_notes:[],memo_summary:[],
      steps:[{id:"S1",title:"Check the carrier limit",actor:"Claims analyst",description:"Look up the maximum claim.",evidence_turns:["t002",IMAGE.id]},{id:"S2",title:"Ask for approval",actor:"Supervisor",description:"Approve returns over the limit.",evidence_turns:[PAGE.id]}],
      connections:[{from:"S1",to:"S2",label:"",evidence_turns:["t002"]}]},h.t.state.turns,h.t.state.documentEvidence);
    const report=h.t.markdown(),block=report.slice(report.indexOf("## Cited document excerpts"));
    assert.ok(block.length>30,"The export lists the cited excerpts");
    const image=block.slice(block.indexOf("### carrier-claim-limits.png"),block.indexOf("### returns-procedure.pdf")),plain=block.slice(block.indexOf("### returns-procedure.pdf"));
    assert.match(image,/^### carrier-claim-limits\.png · image · AI transcription, unverified\n\nReference: doc\\_limits\\_image\\_c1\n\n\*\*AI visual transcription is unverified; inspect the original before relying on it\.\*\*\n\nCarrier \\\| Service/,"The marker stands between the reference and the transcribed text");
    assert.doesNotMatch(plain,/AI visual transcription|AI transcription/);assert.match(plain,/Reference: doc\\_returns\\_p3\\_c1\n\nA return over \$500/);
    const before=report.slice(0,report.indexOf("## Cited document excerpts"));
    assert.match(before,/carrier-claim-limits\.png · image · AI transcription, unverified \(doc\\_limits\\_image\\_c1\)/,"A step that cites the transcription says so where it is cited");
    assert.doesNotMatch(before,/returns-procedure\.pdf · page 3 · AI/);
    // The memo export embeds the same report text.
    const memo=h.t.memoMarkdown();assert.match(memo,/\*\*AI visual transcription is unverified; inspect the original before relying on it\.\*\*/);
  });

  await check("the mark survives saving and reopening, and follows what the server says later",async()=>{
    const h=page();h.load([IMAGE,PAGE]);
    assert.equal(h.t.sessionObject().document_evidence.length,0,"Uncited document text is omitted from the saved interview");
    h.t.state.memo_findings=[{key:"inputs",answer:"Document input",evidence_turns:[IMAGE.id,PAGE.id]}];
    const saved=JSON.parse(JSON.stringify(h.t.sessionObject())).document_evidence;
    assert.deepEqual(saved.map(source=>[source.id,source.origin,source.verified]),[[IMAGE.id,"ai_visual_transcription",false],[PAGE.id,undefined,undefined]]);
    const reopened=h.t.normalizeDocumentEvidence(saved);
    assert.equal(reopened[0].origin,"ai_visual_transcription");assert.equal(reopened[0].verified,false);assert.equal(Object.hasOwn(reopened[1],"origin"),false);
    // A file saved before the mark was kept has none; the next catalog from the server supplies it.
    const old=page();old.t.state.documentEvidence=old.t.normalizeDocumentEvidence([{...IMAGE,location:undefined}]);
    assert.equal(old.t.sourceCaption(IMAGE.id),"carrier-claim-limits.png · image");
    old.load([IMAGE]);assert.equal(old.t.sourceCaption(IMAGE.id),"carrier-claim-limits.png · image"+SUFFIX);assert.equal(old.t.state.documentEvidence.length,1);
  });

  await check("the Assets source preview shows the same warning for such a source",async()=>{
    // The documents panel, as tests/test_documents_frontend.cjs builds it.
    class Element{
      constructor(tag,doc){this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.children=[];this.parentElement=null;this.listeners={};this.attributes={};this.dataset={};this.className="";this.id="";this.hidden=false;this.open=false;this.value="";this._text="";
        this.classList={contains:name=>this.className.split(/\s+/).includes(name),add:name=>{this.className+=" "+name;},remove:name=>{this.className=this.className.split(/\s+/).filter(item=>item!==name).join(" ");},toggle:(name,on)=>{const has=this.classList.contains(name),yes=on===undefined?!has:on;if(yes&&!has)this.classList.add(name);if(!yes&&has)this.classList.remove(name);return yes;}};}
      get textContent(){return this._text+this.children.map(child=>child.textContent).join("");}
      set textContent(value){this.replaceChildren();this._text=String(value);}
      get isConnected(){let node=this;while(node.parentElement)node=node.parentElement;return node===this.ownerDocument.body;}
      append(...children){for(const child of children){if(child.parentElement)child.parentElement.children=child.parentElement.children.filter(item=>item!==child);child.parentElement=this;this.children.push(child);}}
      replaceChildren(...children){this.children.forEach(child=>child.parentElement=null);this.children=[];this._text="";this.append(...children);}
      setAttribute(name,value){this.attributes[name]=String(value);}getAttribute(name){return this.attributes[name]??null;}removeAttribute(name){delete this.attributes[name];}
      addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}removeEventListener(){}
      focus(){this.ownerDocument.activeElement=this;}scrollIntoView(){}setSelectionRange(){}
      contains(node){return all(this).includes(node);}remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(child=>child!==this);this.parentElement=null;}
      showModal(){this.open=true;}close(){this.open=false;}
      querySelectorAll(selector){return all(this).filter(node=>node!==this&&(selector.startsWith(".")?node.className.split(/\s+/).includes(selector.slice(1)):selector.startsWith("[")?(selector.match(/^\[data-document-id="([^"]+)"\]$/)||[])[1]===node.dataset.documentId:node.tagName===selector.toUpperCase()));}
      querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
    }
    const preview=async(source,inline)=>{
      const document={activeElement:null};document.body=new Element("body",document);document.createElement=tag=>new Element(tag,document);document.createElementNS=(_,tag)=>new Element(tag,document);document.getElementById=id=>all(document.body).find(node=>node.id===id)||null;
      const host=document.createElement("section");host.id="interview-view";document.body.append(host);
      for(const id of inline?["document-assets"]:["document-controls","document-strip","documents-dialog"]){const node=document.createElement(id.endsWith("dialog")?"dialog":"div");node.id=id;(id.endsWith("dialog")?document.body:host).append(node);}
      const window={document,addEventListener(){},removeEventListener(){}},context={window,DOMException,AbortController,setTimeout:()=>0,clearTimeout(){}};
      vm.createContext(context);vm.runInContext(web("documents.js"),context);
      const api=window.CollectorDocuments.create({document,config:()=>({csrf_token:"test-csrf"}),getContext:()=>({context:{},turns:[],focus:"",current_question:""}),canUpload:()=>true,
        requestJSON:async url=>url==="/api/documents/source"?{source}:{scope:"local-scope",documents:[]},fetch:async()=>({ok:true,json:async()=>({})}),onEvent(){},onDirty(){},notice(){},onOpen(){},onDiscuss(){},onCountChange(){}});
      const file={id:"doc_limits",name:"carrier-claim-limits.png",kind:"png",size:1200,status:"ready",analysis:{phase:"complete",disposition:"relevant",summary:"A table of claim limits.",version:1,sources:[{source_id:"doc_limits_image_c1",label:"image"}]}};
      api.scope="local-scope";api.setDocuments([file],false);
      await api.openSource(file,{source_id:"doc_limits_image_c1",label:"image"});
      const box=api.body.querySelector(".documents-source-preview");api.dispose();return box;
    };
    // What /api/documents/source returns for a transcribed image (documents._chunk flattens the location).
    const transcribed={id:"doc_limits_image_c1",source_id:"doc_limits_image_c1",document_id:"doc_limits",name:"carrier-claim-limits.png",label:"image",text:IMAGE.text,location:IMAGE.location,...IMAGE.location};
    for(const inline of [true,false]){
      const box=await preview(transcribed,inline),note=box.querySelector(".documents-source-origin"),body=box.querySelector(".documents-source-text");
      assert.ok(note,"The preview carries the marker");assert.equal(note.textContent,NOTE);assert.equal(body.textContent,IMAGE.text);
      assert.ok(box.children.indexOf(note)<box.children.indexOf(body),"The warning is read before the text");
      const plain=await preview({id:"doc_limits_p1_c1",source_id:"doc_limits_p1_c1",document_id:"doc_limits",name:"carrier-claim-limits.png",label:"page 1",text:"Native text.",location:{page:1},page:1},inline);
      assert.equal(plain.querySelector(".documents-source-origin"),null);assert.doesNotMatch(plain.textContent,/AI visual transcription/);
    }
    assert.ok(await preview({...transcribed,origin:undefined,location:undefined,verified:false},true).then(box=>box.querySelector(".documents-source-origin")),"verified false alone is enough");
  });

  await check("one sentence is used in the Assets preview, the source dialog, the export and Admin",async()=>{
    const count=(name,pattern)=>(web(name).match(pattern)||[]).length;
    assert.equal(count("app.js",/const AI_TRANSCRIPTION_NOTE="AI visual transcription is unverified; inspect the original before relying on it\.";/g),1);
    assert.equal(count("documents.js",/const AI_TRANSCRIPTION_NOTE = "AI visual transcription is unverified; inspect the original before relying on it\.";/g),1);
    assert.ok(count("knowledge-ui.js",/"AI visual transcription is unverified; inspect the original before relying on it\."/g)>=1,"The Admin view's wording is the one reused");
    assert.match(web("style.css"),/\.excerpt-note\.excerpt-origin \{/);assert.match(web("documents.css"),/\.documents-source-origin \{/);
  });

  console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0}));
});
