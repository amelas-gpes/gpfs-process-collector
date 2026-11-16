"use strict";
// Checks tests/run_all.cjs, the one command for the Node suites, against throwaway fixture
// folders. It never starts the real suites, so the runner can safely include this file.
// No package, provider or network is used.
const assert=require("node:assert/strict"),fs=require("node:fs"),os=require("node:os"),path=require("node:path"),{spawnSync}=require("node:child_process");
if(process.env.COLLECTOR_RUN_ALL_CHECK){console.error("test_run_all.cjs was started by the runner it is checking");process.exit(1);}
const runner=path.join(__dirname,"run_all.cjs"),root=path.join(__dirname,"..");
const scratch=fs.mkdtempSync(path.join(os.tmpdir(),"collector-run-all-"));
const folder=(name,files)=>{const dir=path.join(scratch,name);fs.mkdirSync(dir);for(const [file,body] of Object.entries(files))fs.writeFileSync(path.join(dir,file),body);return dir;};
// Every call names a fixture folder or only lists; the marker stops a nested copy of this file at once.
const run=(...args)=>{
 const result=spawnSync(process.execPath,[runner,...args],{cwd:root,encoding:"utf8",timeout:120000,env:{...process.env,COLLECTOR_RUN_ALL_CHECK:"1"}});
 const out=result.stdout||"",err=result.stderr||"";
 return {status:result.status,out,err,all:out+err,lines:out.split(/\r?\n/),reports:out.split(/\r?\n/).filter(line=>/^(?:PASS|FAIL) /.test(line))};
};
const report=(result,label)=>result.reports.filter(line=>line.slice(5).startsWith(label+" ")||line.slice(5).trimEnd()===label);
let passes=0;
try{
 const dir=folder("suites",{
  "test_alpha.cjs":'console.log(JSON.stringify({tests_passed:1+2,provider_calls:0}));',
  "test_beta.cjs":'console.log("Beta registry: every design passed.");',
  "run_all.cjs":'console.error("The runner started a file with its own name");process.exitCode=1;',
  "notes.txt":"not a suite","helper.js":"process.exitCode=1;"});
 {
  const green=run("--dir",dir);
  assert.equal(green.status,0,green.all);
  assert.equal(green.reports.length,2,"One report line per suite; other files and the runner itself are not suites");
  assert.match(report(green,"test_alpha.cjs")[0],/^PASS .*\b3 passed/);
  assert.match(report(green,"test_beta.cjs")[0],/^PASS .*Beta registry: every design passed\./);
  assert.match(green.out,/2 run, 2 passed, 0 failed/);passes++;
 }
 {
  // A suite added to the folder runs without being registered anywhere.
  fs.writeFileSync(path.join(dir,"test_added_later.cjs"),'require("node:assert/strict").equal(1,1);');
  const grown=run("--dir",dir);
  assert.equal(grown.status,0,grown.all);assert.equal(report(grown,"test_added_later.cjs").length,1);
  assert.match(grown.out,/3 run, 3 passed, 0 failed/);passes++;
 }
 {
  // A failing suite fails the run, shows why, and does not hide the suites after it.
  fs.writeFileSync(path.join(dir,"test_a_broken.cjs"),'console.log("before the failure");require("node:assert/strict").equal(1,2,"synthetic regression marker");');
  const red=run("--dir",dir);
  assert.equal(red.status,1,red.all);
  assert.equal(red.reports.length,4);assert.match(red.reports[0],/^FAIL test_a_broken\.cjs .*exit 1/);
  assert.equal(red.reports.slice(1).every(line=>line.startsWith("PASS ")),true,"Suites after a failure still run and report");
  assert.match(red.all,/synthetic regression marker/,"The failing suite's own output is shown");
  assert.match(red.out,/4 run, 3 passed, 1 failed/);assert.match(red.out,/Failed: test_a_broken\.cjs/);passes++;
 }
 {
  // Each suite is started once, with no extra arguments: a plain run of a suite is its whole run.
  // A node:test suite's own "pass N" line is reported as its total.
  const plain=run("--dir",folder("plain",{"test_ui_state.cjs":'console.log(JSON.stringify({checks:process.argv.length}));',
   "test_node_style.cjs":'const mark=String.fromCharCode(0x2139);for(const line of ["tests 4","pass 4","fail 0","duration_ms 12.5"])console.log(mark+" "+line);'}));
  assert.equal(plain.status,0,plain.all);assert.equal(plain.reports.length,2);
  assert.match(plain.reports[0],/^PASS test_node_style\.cjs .*\b4 passed/);assert.match(plain.reports[1],/^PASS test_ui_state\.cjs .*\b2 passed/);passes++;
 }
 {
  // A suite that prints several summary lines (test_ui_state.cjs prints one per block) has every
  // total reported, in the order printed: the last one alone would understate what ran.
  const blocks=run("--dir",folder("blocks",{
   "test_two_blocks.cjs":'console.log(JSON.stringify({tests_passed:40,provider_calls:0,voice_tests:0}));console.log("between the blocks");console.log(JSON.stringify({tests_passed:161,provider_calls:0,checks:7}));',
   "test_one_block.cjs":'console.log(JSON.stringify({checks_passed:5,provider_calls:0}));'}));
  assert.equal(blocks.status,0,blocks.all);assert.equal(blocks.reports.length,2);
  assert.match(report(blocks,"test_two_blocks.cjs")[0],/^PASS test_two_blocks\.cjs +\d+\.\d s {2}40 \+ 161 passed$/,"Every printed total is reported, one per summary line");
  assert.match(report(blocks,"test_one_block.cjs")[0],/^PASS test_one_block\.cjs +\d+\.\d s {2}5 passed$/,"A single total is reported as before");passes++;
 }
 {
  const stuck=folder("stuck",{"test_stuck.cjs":"setInterval(()=>{},1000);"});
  const timed=run("--dir",stuck,"--timeout","1");
  assert.equal(timed.status,1,timed.all);assert.match(timed.reports[0],/^FAIL test_stuck\.cjs .*timed out after 1 s/);passes++;
 }
 {
  // Nothing to run is an error, never a green result.
  const none=run("--dir",folder("empty",{"notes.txt":"nothing to run"}));
  assert.notEqual(none.status,0);assert.equal(none.reports.length,0);assert.match(none.all,/No suites/);
  const unknown=run("--dir",dir,"--no-such-option");
  assert.equal(unknown.status,2);assert.equal(unknown.reports.length,0);assert.match(unknown.all,/Usage/);passes++;
 }
 {
  // Without --dir the runner covers this folder: every *.cjs here except itself.
  const listed=run("--list");
  assert.equal(listed.status,0,listed.all);
  const expected=fs.readdirSync(__dirname).filter(name=>name.endsWith(".cjs")&&name!=="run_all.cjs").sort();
  assert.deepEqual(listed.lines.filter(Boolean),expected);
  for(const name of ["test_agent_experience.cjs","test_controlled_voice.cjs","test_knowledge_ui.cjs","test_ui_state.cjs","test_run_all.cjs"])assert(expected.includes(name),name);
  assert.equal(/tests[\\/]run_all\.cjs/.test(fs.readFileSync(path.join(root,"README.md"),"utf8")),true,"The README names the command that runs every Node suite");passes++;
 }
 {
  // A printed total must come from what ran. A literal keeps saying the same number whatever happened.
  const suites=fs.readdirSync(__dirname).filter(name=>name.endsWith(".cjs")&&name!==path.basename(__filename));
  for(const name of suites)assert.doesNotMatch(fs.readFileSync(path.join(__dirname,name),"utf8"),/(?:tests|checks)_passed["']?\s*:\s*\d/,name+" prints a hard-coded total");
  for(const [name,key] of [["test_gpfs_capture.cjs","checks_passed"],["test_memo_ui.cjs","tests_passed"]]){
   const source=fs.readFileSync(path.join(__dirname,name),"utf8"),summary=source.lastIndexOf("console.log(");
   const copy=folder("counted-"+name,{});
   const total=text=>{
    fs.writeFileSync(path.join(copy,name),text.replaceAll("__dirname",JSON.stringify(__dirname)));
    const result=spawnSync(process.execPath,[path.join(copy,name)],{cwd:root,encoding:"utf8",timeout:120000});
    assert.equal(result.status,0,name+": "+result.stderr);return JSON.parse(result.stdout.trim().split(/\r?\n/).at(-1))[key];
   };
   const counted=total(source);
   assert.equal(Number.isInteger(counted)&&counted>0,true,name+" reports "+counted);
   assert.equal(total(source.slice(0,summary)+"assert.equal(1,1);assert(true);\n"+source.slice(summary)),counted+2,name+" must count the assertions that actually ran");
  }passes++;
 }
 console.log(JSON.stringify({tests_passed:passes,provider_calls:0,network_calls:0}));
}finally{fs.rmSync(scratch,{recursive:true,force:true});}
