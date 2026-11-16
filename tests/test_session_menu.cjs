"use strict";
// Exercise the real session-menu bindings with a minimal DOM. No browser,
// provider, download, audio device or network request is used.
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm"),assert=require("node:assert/strict");
const root=path.join(__dirname,".."),html=fs.readFileSync(path.join(root,"web","index.html"),"utf8"),app=fs.readFileSync(path.join(root,"web","app.js"),"utf8");
const document={activeElement:null,listeners:{},modal:null,addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);},dispatch(name,event){for(const fn of this.listeners[name]||[])fn(event);}};
class Element {
 constructor(id,parent=null){this.id=id;this.parentElement=parent;this.hidden=false;this.open=false;this.value="";this.textContent="";this.listeners={};this.attributes={};this.classes=new Set();this.classList={toggle:(name,on)=>on?this.classes.add(name):this.classes.delete(name)};}
 contains(node){for(let cursor=node;cursor;cursor=cursor.parentElement)if(cursor===this)return true;return false;}
 setAttribute(name,value){this.attributes[name]=String(value);}
 getAttribute(name){return this.attributes[name]??null;}
 addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
 dispatch(name){for(const fn of this.listeners[name]||[])fn({target:this});}
 click(){this.clicks=(this.clicks||0)+1;this.dispatch("click");}
 focus(){for(let cursor=this;cursor;cursor=cursor.parentElement)assert.equal(cursor.hidden,false,"Focus cannot enter a hidden menu");if(document.modal)assert.ok(document.modal.contains(this),"Focus cannot escape open settings");document.activeElement=this;}
 showModal(){this.open=true;document.modal=this;this.focus();}
 close(){this.open=false;document.modal=null;this.dispatch("close");}
}
const nodes=new Map(),mount=(id,parent)=>{const node=new Element(id,parent);nodes.set(id,node);return node;};
document.getElementById=id=>nodes.get(id)||null;
const menu=mount("session-menu"),toggle=mount("session-menu-toggle"),settings=mount("interview-settings"),outside=mount("answer-text");menu.hidden=true;
for(const id of ["export-session","open-interview-settings","import-session"])mount(id,menu);
mount("close-interview-settings",settings);mount("save-hint");mount("session-file");
const bindings=app.split("\n").filter(line=>/\$\("(?:export-session|open-interview-settings|close-interview-settings|interview-settings|session-menu-toggle|import-session)"\)\.addEventListener/.test(line)||/document\.addEventListener\("(?:click|keydown)",event => .*closeMenu\(/.test(line)).join("\n");
const downloads=[],notices=[];
const sandbox={console,document,window:{},setTimeout,clearTimeout,AbortController,TextEncoder};
vm.createContext(sandbox);vm.runInContext(app.replace(/  init\(\);\s*\}\)\(\);\s*$/,"  download=(...args)=>window.downloads.push(args); notice=(...args)=>window.notices.push(args); "+bindings+" window.menuTests={state,closeMenu,setInterviewSettings};\n})();"),Object.assign(sandbox,{window:{downloads,notices}}),{filename:"app.js"});
const t=sandbox.window.menuTests;let checks=0;
const openMenu=()=>{toggle.focus();toggle.click();assert.equal(menu.hidden,false);assert.equal(toggle.getAttribute("aria-expanded"),"true");};

{
 const contents=html.match(/<div class="session-menu"[\s\S]*?<\/div>/)?.[0];assert.ok(contents);
 for(const id of ["export-session","open-interview-settings"]){assert.ok(contents.includes(`id="${id}"`));assert.equal((html.match(new RegExp(`id="${id}"`,"g"))||[]).length,1,"Moved controls must not be duplicated");}
 assert.match(contents,/>Save copy<\/button>/);assert.match(contents,/>Settings<\/button>/);checks++;
}
{
 openMenu();nodes.get("open-interview-settings").focus();nodes.get("open-interview-settings").click();
 assert.equal(menu.hidden,true);assert.equal(toggle.getAttribute("aria-expanded"),"false");assert.equal(settings.open,true);assert.equal(document.activeElement,settings);
 nodes.get("close-interview-settings").click();assert.equal(settings.open,false);assert.equal(document.activeElement,toggle,"Settings returns to the visible options control, not its hidden menu item");checks++;
}
{
 openMenu();nodes.get("export-session").focus();t.state.context={process_name:"Menu regression"};t.state.dirty=true;outside.value="Unsent text stays in the saved interview";
 const originalTurns=t.state.turns;nodes.get("export-session").click();
 assert.equal(downloads.length,1);assert.match(downloads[0][1],/^Menu-regression-session-\d{8}T\d{6}Z\.json$/);const saved=JSON.parse(downloads[0][0]);assert.equal(saved.unsent_answer,outside.value);assert.equal(t.state.turns,originalTurns);
 // A download cannot report whether a file was written: no "Saved", and the unsaved state stays.
 assert.equal(t.state.dirty,true);assert.equal(notices.length,1);assert.match(notices[0][0],/^Download started\./);assert.doesNotMatch(notices[0][0],/\bsaved\b/i);
 assert.equal(menu.hidden,true);assert.equal(document.activeElement,toggle);assert.equal(nodes.get("save-hint").hidden,false);assert.match(nodes.get("save-hint").textContent,/^Last copy downloaded /);checks++;
}
{
 openMenu();nodes.get("open-interview-settings").focus();document.dispatch("keydown",{key:"Escape"});assert.equal(menu.hidden,true);assert.equal(document.activeElement,toggle);
 outside.focus();document.dispatch("keydown",{key:"Escape"});assert.equal(document.activeElement,outside,"Escape outside a closed menu must preserve typing focus");checks++;
}
{
 openMenu();outside.focus();document.dispatch("click",{target:outside});assert.equal(menu.hidden,true);assert.equal(document.activeElement,outside,"Outside clicks retain their natural focus");checks++;
}
{
 openMenu();nodes.get("import-session").focus();nodes.get("import-session").click();assert.equal(menu.hidden,true);assert.equal(document.activeElement,toggle,"Cancelling the native file picker must not strand focus in the hidden menu");assert.equal(nodes.get("session-file").clicks,1);checks++;
}
{
 t.setInterviewSettings(true,false);t.setInterviewSettings(false,false);assert.notEqual(document.activeElement,toggle,"Programmatic teardown can suppress menu focus restoration");checks++;
}
console.log(JSON.stringify({checks_passed:checks,provider_calls:0,downloads_created:0,network_calls:0}));
