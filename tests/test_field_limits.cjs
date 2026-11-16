"use strict";
// Text longer than a field allows must never be cut without a word. The reply, the goal and the
// background keep the whole text and say that it is too long; the Review editor refuses a paste that
// does not fit; a name or owner is shortened and says so. Lengths are counted as the server counts
// them (code points). The real web/app.js runs against the real web/index.html in the page of
// tests/fixtures/interview_form_page.cjs. No browser, audio device, provider, package or network.
const assert=require("node:assert/strict");
const {openPage,standInMicrophone}=require("./fixtures/interview_form_page.cjs");
const EXPOSE=["state","conversationUI","sessionObject","importSession","tab"];
const FAMILY="\u{1F468}‍\u{1F469}‍\u{1F467}‍\u{1F466}"; // one joined emoji: 7 code points, 11 UTF-16 units
const RARE="\u{20BB7}"; // one CJK character outside the basic plane: 1 code point, 2 UTF-16 units
const points=value=>[...value].length;
let checks=0;
async function check(name,fn){try{await fn();checks++;}catch(error){error.message=name+": "+error.message;throw error;}}

async function open(options={}){
 const posts=[];
 const page=await openPage({expose:EXPOSE,...options,fetch:async(url,init)=>{
  posts.push({url,body:typeof init.body==="string"?JSON.parse(init.body):init.body});
  if(url==="/api/interview")return {ok:true,status:200,json:async()=>({question:`Question ${posts.filter(post=>post.url===url).length}?`})};
  if(url==="/api/transcribe")return {ok:true,status:200,json:async()=>({text:"and then the controller signs it off."})};
  throw new Error("Unexpected request: "+url);
 }});
 const write=(id,value)=>{page.$(id).value=value;page.fire(page.$(id),"input");};
 return {page,posts,write,interviews:()=>posts.filter(post=>post.url==="/api/interview"),
  async typeInstead(){page.$("type-instead").click();await page.settle();},
  async submit(){page.fire(page.$("answer-form"),"submit");await page.settle();},
  paste(id,text,selection){const field=typeof id==="string"?page.$(id):id;if(selection)[field.selectionStart,field.selectionEnd]=selection;return page.fire(field,"paste",{clipboardData:{getData:()=>text}});}};
}

(async()=>{
 await check("the fields that hold what was said have no browser-enforced cut; the short identity fields keep theirs",async()=>{
  const {page}=await open();
  for(const id of ["answer-text","objective","background"]){
   const field=page.$(id),note=page.$(id+"-limit");
   assert.equal(field.hasAttribute("maxlength"),false,id+" must not be cut by the browser");
   assert.equal(field.maxLength,-1);
   assert.ok(note,id+" has a place for its message");assert.equal(note.shown,false);assert.equal(note.textContent,"");
   assert.ok(field.getAttribute("aria-describedby").split(/\s+/).includes(note.id));
   assert.equal(note.hasAttribute("role"),false,"The count changes with every keystroke, so the message is not a live region");
   assert.equal(note.hasAttribute("aria-live"),false);
  }
  // Above the box, where it stays in view however tall a long reply makes the box.
  assert.equal(page.$("answer-text-limit").nextElementSibling,page.$("answer-form"));
  assert.equal(page.$("process-name").maxLength,180);assert.equal(page.$("process-owner").maxLength,180);
 });

 await check("an over-long reply is kept whole, cannot be sent, and says why until it is shortened",async()=>{
  const t=await open(),{page}=t;
  await t.typeInstead();
  const reply=page.$("answer-text"),note=page.$("answer-text-limit"),status=page.$("live-status");
  const prepared="The supplier sends the invoice. ".repeat(250).trim(); // a prepared description, pasted in one go
  assert.equal(prepared.length,7999);
  t.write("answer-text",prepared);
  const message="Your reply is 7,999 characters; the limit is 6,000. Nothing was removed. Shorten it or send it in two parts.";
  assert.equal(reply.value,prepared,"The whole text stays in the box");
  assert.equal(page.$("send-answer").disabled,true);
  assert.equal(note.shown,true);assert.equal(note.textContent,message);
  assert.equal(reply.getAttribute("aria-invalid"),"true");
  assert.equal(status.textContent,message,"Going over the limit is said once");
  const said=status.writes;
  t.write("answer-text",prepared+" x");
  assert.match(note.textContent,/^Your reply is 8,001 characters/);
  assert.equal(status.writes,said,"The count is not announced on every keystroke");
  // Ctrl + Enter does not go through the disabled Send button.
  page.fire(reply,"keydown",{key:"Enter",ctrlKey:true});await page.settle();
  assert.equal(t.interviews().length,1,"Nothing was sent");
  assert.equal(reply.value,prepared+" x");
  assert.match(page.$("notice-text").textContent,/^Your reply is 8,001 characters; the limit is 6,000\. Nothing was removed\./);
  assert.equal(page.app.state.turns.filter(turn=>turn.role==="user").length,0);
  assert.equal(page.$("interview-error").shown,true,"The refusal is also on the error line");
  // It does not disappear by itself.
  page.runTimeouts(60000);
  assert.equal(note.shown,true,"The message stays for as long as the reply is too long");
  // Emptying the box takes the message away as well (Send is then disabled for another reason).
  t.write("answer-text","");
  assert.equal(note.shown,false,"An emptied reply is not too long");assert.equal(reply.hasAttribute("aria-invalid"),false);
  assert.equal(page.$("interview-error").hidden,true,"The error line about the length goes with it");
  assert.equal(page.$("send-answer").disabled,true);
  t.write("answer-text",prepared);
  assert.equal(note.shown,true);
  const shortened=prepared.slice(0,6000);
  t.write("answer-text",shortened);
  assert.equal(note.shown,false);assert.equal(note.textContent,"");assert.equal(reply.hasAttribute("aria-invalid"),false);
  assert.equal(page.$("send-answer").disabled,false);
  await t.submit();
  assert.equal(t.interviews().length,2);
  assert.equal(t.interviews()[1].body.turns.at(-1).text,shortened.trim(),"The reply is sent exactly as written");
 });

 await check("the limit is counted in characters as the server counts them, and nothing is cut inside one",async()=>{
  const t=await open(),{page}=t;
  await t.typeInstead();
  const atLimit="a".repeat(5993)+FAMILY;
  assert.equal(points(atLimit),6000);assert.equal(atLimit.length,6004,"More UTF-16 units than the limit");
  t.write("answer-text",atLimit);
  assert.equal(page.$("answer-text-limit").shown,false);assert.equal(page.$("send-answer").disabled,false);
  await t.submit();
  const sent=t.interviews()[1].body.turns.at(-1).text;
  assert.equal(sent,atLimit);assert.equal(sent.endsWith(FAMILY),true,"The joined emoji arrives whole");
  // What was sent can be saved and opened again.
  const saved=JSON.stringify(page.app.sessionObject());
  await page.app.importSession({size:saved.length,text:async()=>saved});await page.settle();
  assert.equal(page.app.state.turns.find(turn=>turn.role==="user")?.text,atLimit,"A saved copy with that reply opens");
  assert.doesNotMatch(page.$("notice-text").textContent,/exceeds|too long/);
  const rare=RARE.repeat(6000);
  t.write("answer-text",rare);
  assert.equal(page.$("answer-text-limit").shown,false,"6,000 characters are 6,000 characters whatever their encoding");
  t.write("answer-text",rare+"a");
  assert.match(page.$("answer-text-limit").textContent,/^Your reply is 6,001 characters; the limit is 6,000\./);
  assert.equal(page.$("send-answer").disabled,true);
  t.write("answer-text","a".repeat(5994)+FAMILY);
  assert.match(page.$("answer-text-limit").textContent,/^Your reply is 6,001 characters/);
 });

 await check("dictated words that take the reply over the limit are added whole, with the same message",async()=>{
  const microphone=standInMicrophone(),t=await open({globals:microphone.globals}),{page}=t;
  await t.typeInstead();
  const typed="b".repeat(5990);
  t.write("answer-text",typed);
  page.$("record-answer").click();await page.settle();
  microphone.clock+=3000;page.$("record-answer").click();await page.settle();
  const combined=typed+"\n\nand then the controller signs it off.";
  assert.equal(page.$("answer-text").value,combined);
  const message=`Your reply is ${points(combined).toLocaleString("en-US")} characters; the limit is 6,000. Nothing was removed. Shorten it or send it in two parts.`;
  assert.equal(page.$("answer-text-limit").textContent,message);assert.equal(page.$("answer-text-limit").shown,true);
  assert.equal(page.$("notice-text").textContent,message);
  assert.equal(page.$("send-answer").disabled,true);
 });

 await check("an over-long background or goal is kept whole and stops the interview from starting, at the field",async()=>{
  for(const [id,limit,label] of [["background",8000,"The background"],["objective",500,"The goal for this interview"]]){
   const t=await open(),{page}=t,field=page.$(id),note=page.$(id+"-limit");
   const closing=" No invoice is paid without the controller’s approval.";
   const long=("c".repeat(limit+1-closing.length)+closing);
   assert.equal(long.length,limit+1);
   t.write(id,long);
   const start=`${label} is ${(limit+1).toLocaleString("en-US")} characters; the limit is ${limit.toLocaleString("en-US")}. Nothing was removed.`;
   assert.equal(field.value,long,"The closing sentence is still there");
   assert.equal(note.textContent.startsWith(start),true,note.textContent);
   assert.equal(field.getAttribute("aria-invalid"),"true");
   assert.equal(page.$("live-status").textContent,note.textContent);
   for(const button of ["type-instead","start-live"]){
    page.$("interview-settings").close();
    page.$(button).click();await page.settle();
    assert.equal(page.app.state.started,false,button+" does not start an interview whose context would be refused");
    assert.equal(t.posts.length,0);assert.equal(page.app.conversationUI.live,null,"The microphone is not opened");
    assert.equal(page.$("interview-settings").open,true,"Settings opens");assert.equal(page.$("context-details").open,true);
    assert.equal(note.shown,true,"with the reason beside the field");
    assert.equal(page.document.activeElement,field);
    assert.equal(page.$("notice-text").textContent,note.textContent);
   }
   assert.equal(page.$("interview-error").hidden,false);
   t.write(id,long.slice(1));
   assert.equal(note.shown,false);assert.equal(field.hasAttribute("aria-invalid"),false);
   assert.equal(page.$("interview-error").hidden,true,"The error line does not outlive the problem");
   page.$("interview-settings").close();
   await t.typeInstead();
   assert.equal(page.app.state.started,true);
   assert.equal(t.interviews()[0].body.context[id],long.slice(1),"Exactly the limit is sent whole");
   assert.equal(t.interviews()[0].body.context[id].endsWith(closing),true);
  }
 });

 await check("Review editor: a paste that does not fit is refused whole and says why; one that fits is left alone",async()=>{
  const t=await open(),{page}=t;
  const saved=JSON.stringify({schema_version:1,context:{process_name:"Invoice approval",objective:"QA"},turns:[],draft_stale:false,
   draft:{title:"Invoice approval",overview:"d".repeat(11990),steps:[{id:"S1",title:"Receive the invoice"}]}});
  await page.app.importSession({size:saved.length,text:async()=>saved});await page.settle();
  page.app.tab("review");
  const overview=page.$("draft-overview");
  assert.equal(overview.maxLength,12000);assert.equal(overview.value.length,11990);
  let event=t.paste("draft-overview","e".repeat(1400));
  assert.equal(event.defaultPrevented,true,"The browser must not be left to cut the paste");
  const message="The text you pasted is 1,400 characters and this field has room for 10 (its limit is 12,000). Nothing was pasted, so nothing was cut. Shorten the text or split it across fields.";
  assert.equal(page.$("review-error").shown,true);assert.equal(page.$("review-error").querySelector("span").textContent,message);
  assert.equal(overview.value.length,11990);assert.equal(page.app.state.draft.overview.length,11990);
  page.runTimeouts(60000);
  assert.equal(page.$("review-error").shown,true,"The reason stays until it is dismissed");
  page.$("review-error").hidden=true;
  assert.equal(t.paste("draft-overview","e".repeat(10)).defaultPrevented,false,"A paste that fits is the browser's business");
  // Replacing a selection frees its room; line endings are counted as the field stores them.
  assert.equal(t.paste("draft-overview","e".repeat(1400),[0,2000]).defaultPrevented,false);
  assert.equal(t.paste("draft-overview","line\r\n".repeat(2),[0,0]).defaultPrevented,false,"Two lines of five characters fit in ten");
  assert.equal(t.paste("draft-overview","line\r\n".repeat(3),[0,0]).defaultPrevented,true);
  assert.equal(page.$("review-error").shown,true);page.$("review-error").hidden=true;
  // Text dragged into the field is cut by the browser in the same way. It is inserted beside what
  // is there (a selection frees no room); text moved within the field adds nothing; a dropped file
  // carries no text and is not this guard's business.
  const drop=(text,from)=>{if(from)page.fire(from,"dragstart");const event=page.fire(overview,"drop",{dataTransfer:{getData:()=>text}});page.fire(page.document.body,"dragend");return event;};
  [overview.selectionStart,overview.selectionEnd]=[0,2000];
  event=drop("e".repeat(1400));
  assert.equal(event.defaultPrevented,true);
  assert.equal(page.$("review-error").querySelector("span").textContent,"The text you dropped is 1,400 characters and this field has room for 10 (its limit is 12,000). Nothing was dropped, so nothing was cut. Shorten the text or split it across fields.");
  page.$("review-error").hidden=true;
  assert.equal(drop("e".repeat(10)).defaultPrevented,false);
  assert.equal(drop("e".repeat(1400),overview).defaultPrevented,false,"A move inside the field");
  assert.equal(drop("e".repeat(1400),page.$("draft-trigger")).defaultPrevented,true,"Text dragged from another field is new text");
  assert.equal(drop("").defaultPrevented,false,"A file");
  assert.equal(drop("e".repeat(1400)).defaultPrevented,true,"The earlier drag is over");
  page.$("review-error").hidden=true;
  // A field the editor builds for each step.
  const stepTitle=page.$("procedure-steps").querySelector("input");
  assert.equal(stepTitle.maxLength,500);
  event=t.paste(stepTitle,"f".repeat(600));
  assert.equal(event.defaultPrevented,true);assert.equal(stepTitle.value,"Receive the invoice");
  assert.match(page.$("review-error").querySelector("span").textContent,/^The text you pasted is 600 characters and this field has room for 481 \(its limit is 500\)\. Nothing was pasted/);
  // The connection dialog shows the reason inside the dialog.
  page.$("global-notice").hidden=true;
  event=t.paste("connection-condition","g".repeat(301));
  assert.equal(event.defaultPrevented,true);
  assert.equal(page.$("connection-error").hidden,false);
  assert.match(page.$("connection-error").textContent,/^The text you pasted is 301 characters and this field has room for 300/);
  assert.equal(page.$("global-notice").hidden,true);
  assert.equal(page.$("report-search").maxLength,180);
  assert.equal(t.paste("report-search","h".repeat(400)).defaultPrevented,false,"A search box is not evidence");
 });

 await check("a process name or owner is shortened to its limit, and says so",async()=>{
  const t=await open(),{page}=t;
  for(const id of ["process-owner","process-name"]){
   page.$("global-notice").hidden=true;page.$("notice-text").textContent="";
   assert.equal(t.paste(id,"Head of accounts payable").defaultPrevented,false);
   assert.equal(page.$("global-notice").hidden,true,"A name that fits needs no note");
   const event=t.paste(id,"i".repeat(251));
   assert.equal(event.defaultPrevented,false,"The browser shortens it as before");
   assert.equal(page.$("global-notice").hidden,false);
   assert.equal(page.$("notice-text").textContent,"That was longer than this field allows, so it was shortened to 180 characters.");
   assert.equal(page.$("global-notice").classList.contains("error"),false);
  }
 });

 console.log(JSON.stringify({checks_passed:checks,provider_calls:0,network_calls:0}));
})().catch(error=>{console.error(error);process.exitCode=1;});
