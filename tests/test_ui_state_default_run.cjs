"use strict";
// A plain run of tests/test_ui_state.cjs must reach both of its test blocks. The usability block
// used to run only with --usability-only, so a pass over every tests/*.cjs silently skipped it.
// The checks use temporary copies of the suite in which the main block, which takes most of the
// suite's time and is run in full by the suite itself, only reports that it was reached.
// No browser, provider or network is used.
const assert=require("node:assert/strict"),fs=require("node:fs"),os=require("node:os"),path=require("node:path"),{spawnSync}=require("node:child_process");
const source=fs.readFileSync(path.join(__dirname,"test_ui_state.cjs"),"utf8"),root=path.join(__dirname,"..");
const mainStart=/\}else\s*\(async\(\)=>\{/,usabilitySummary='console.log(JSON.stringify({tests_passed:passes,provider_calls:0,voice_tests:0}));';
assert.equal(source.split(mainStart).length,2,"The start of the main block was not found");
assert.equal(source.split(usabilitySummary).length,2,"The usability block's summary line was not found");
const scratch=fs.mkdtempSync(path.join(os.tmpdir(),"collector-ui-state-"));
const run=(name,edit)=>{
 const file=path.join(scratch,name);
 fs.writeFileSync(file,edit(source).replace(mainStart,start=>start+'console.log("main block reached");return;').replaceAll("__dirname",JSON.stringify(__dirname)));
 const result=spawnSync(process.execPath,[file],{cwd:root,encoding:"utf8",timeout:300000}),lines=(result.stdout||"").split(/\r?\n/);
 return {status:result.status,stderr:result.stderr||"",usability:lines.filter(line=>line.startsWith('{"tests_passed":')&&"voice_tests" in JSON.parse(line)),main:lines.filter(line=>line==="main block reached")};
};
let passes=0;
try{
 {
  const plain=run("plain.cjs",text=>text);
  assert.equal(plain.status,0,plain.stderr);
  assert.equal(plain.usability.length,1,"A plain run must also run the usability block");
  assert.equal(JSON.parse(plain.usability[0]).tests_passed>0,true);
  assert.equal(plain.main.length,1,"A plain run runs the main block once; the flagged run it starts must not run it again");passes++;
 }
 {
  // A failure in the usability block fails the plain run and does not hide the main block.
  const failed=run("broken.cjs",text=>text.replace(usabilitySummary,'assert.fail("synthetic usability failure");'+usabilitySummary));
  assert.notEqual(failed.status,0,"A failing usability block must fail the plain run");
  assert.match(failed.stderr,/synthetic usability failure/);
  assert.equal(failed.usability.length,0);assert.equal(failed.main.length,1,"The main block still runs after a usability failure");passes++;
 }
 console.log(JSON.stringify({tests_passed:passes,provider_calls:0,network_calls:0,real_browser:false}));
}finally{fs.rmSync(scratch,{recursive:true,force:true});}
