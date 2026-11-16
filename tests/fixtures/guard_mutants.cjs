"use strict";
// An occasional check, not a suite (tests/run_all.cjs does not run this folder):
//   node tests/fixtures/guard_mutants.cjs
// Each line below flips one operator of the application in a throwaway copy and expects
// tests/test_guard_behaviours.cjs to fail in exactly the check that pins that behaviour. A line reported as
// SURVIVED means the suite no longer notices that defect; SKIP means the source line has changed and the
// mutant needs to be written again. Nothing outside the temporary folder is written. No provider, no network.
const fs=require("node:fs"),os=require("node:os"),path=require("node:path"),{spawnSync}=require("node:child_process");
const lane=path.resolve(__dirname,"..",".."),work=fs.mkdtempSync(path.join(os.tmpdir(),"guard-mutants-"));
const mutants=[
 ["app.js","reply box","$(\"answer-text\").disabled = working || recording || !ready;","$(\"answer-text\").disabled = working && recording || !ready;","the reply box is disabled"],
 ["app.js","draftChanged","state.draftEdited = true;\r\n    state.dirty = true;","state.draftEdited = true;\r\n    state.dirty = false;","editing the draft marks"],
 ["app.js","hasDraftSource","const hasDraftSource = state.turns.some(t => t.role === \"user\")","const hasDraftSource = state.turns.some(t => t.role !== \"user\")","a draft needs a participant answer"],
 ["app.js","128/100","taxonomy.length>128||connections_out.length>100","taxonomy.length>128&&connections_out.length>100","classifications stop at 128"],
 ["controlled-voice.js","listen muted","if(op.muted){this.tracks(op,false);this.setStatus(\"muted\");return;}","if(op.muted){this.tracks(op,true);this.setStatus(\"muted\");return;}","the microphone stays closed"],
 ["controlled-voice.js","playReviewed","async playReviewed(op,result,basis,signal){\n      if(!this.current(op)||signal.aborted||op.muted)return;","async playReviewed(op,result,basis,signal){\n      if(!this.current(op)||signal.aborted&&op.muted)return;","a reviewed response is neither applied"],
 ["documents.js","available","const available=!document.archived&&[\"ready\",\"partial\"].includes(document.status)&&Number(document.chunk_count)>0","const available=!document.archived&&[\"ready\",\"partial\"].includes(document.status)||Number(document.chunk_count)>0","a file is announced as usable"]];
let ok=0;
for(const [index,[file,label,from,to,checkName]] of mutants.entries()){
 const dir=path.join(work,"m"+index);fs.mkdirSync(dir,{recursive:true});
 fs.cpSync(path.join(lane,"web"),path.join(dir,"web"),{recursive:true});fs.cpSync(path.join(lane,"tests"),path.join(dir,"tests"),{recursive:true});
 const target=path.join(dir,"web",file);let source=fs.readFileSync(target,"utf8");
 let needle=from,replacement=to;
 if(!source.includes(needle)){needle=from.replace(/\n/g,"\r\n");replacement=to.replace(/\n/g,"\r\n");}
 const count=source.split(needle).length-1;
 if(count!==1){console.log(`SKIP ${file} ${label}: the site was found ${count} times`);continue;}
 fs.writeFileSync(target,source.replace(needle,replacement));
 const run=spawnSync(process.execPath,[path.join(dir,"tests","test_guard_behaviours.cjs")],{cwd:dir,encoding:"utf8"});
 const failedLines=run.stdout.split(/\r?\n/).filter(line=>line.startsWith("FAIL "));
 const killed=run.status!==0&&failedLines.length===1&&failedLines[0].includes(checkName);
 console.log(`${killed?"KILLED  ":"SURVIVED"} ${file} ${label}: exit ${run.status}; failing checks: ${failedLines.map(line=>line.slice(5,60)).join(" | ")||"none"}`);
 if(killed)ok++;
}
fs.rmSync(work,{recursive:true,force:true});
console.log(`${ok} of ${mutants.length} mutants killed, each by exactly its own check`);
if(ok!==mutants.length)process.exitCode=1;
