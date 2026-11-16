"use strict";
// Runs every Node suite in this folder and prints one line per suite.
//
//   node tests/run_all.cjs               every tests/*.cjs, with the Node that started this file
//   node tests/run_all.cjs --list        name the suites that would run, without running them
//   --dir <folder>                       use another folder of suites (tests/test_run_all.cjs does)
//   --timeout <seconds>                  stop a suite that runs longer than this (default 600)
//
// Suites are found by listing the folder, so a new tests/<name>.cjs is included without being
// registered anywhere. Each suite runs in its own process from the repository root, one after
// another, and a failure never hides the suites after it. The exit code is 0 only when every
// suite exits 0. No package manifest, dependency, provider or network is used.
const {spawn}=require("node:child_process"),fs=require("node:fs"),path=require("node:path");
const SELF=path.basename(__filename),FAILURE_LINES=30;
const USAGE="Usage: node tests/run_all.cjs [--list] [--dir <folder>] [--timeout <seconds>]";

function options(argv){
 const chosen={dir:__dirname,timeout:600,list:false};
 for(let index=0;index<argv.length;index++){
  if(argv[index]==="--list")chosen.list=true;
  else if(argv[index]==="--dir"&&argv[index+1])chosen.dir=path.resolve(argv[++index]);
  else if(argv[index]==="--timeout"&&Number(argv[index+1])>0)chosen.timeout=Number(argv[++index]);
  else return null;
 }
 return chosen;
}
function discover(dir){
 return fs.readdirSync(dir).filter(name=>name.endsWith(".cjs")&&name!==SELF).sort();
}
// The suites report in several styles; show a counted total when one is printed (a JSON summary,
// or the "pass N" line of node:test behind its one-character marker), else the last line. A suite
// that prints several summary lines (test_ui_state.cjs prints one per block) has each line's
// total shown in the order printed, as "40 + 161 passed".
function summary(stdout){
 const counts=stdout.split(/\r?\n/).map(line=>line.match(/"(?:tests_passed|checks_passed|checks)":\s*(\d+)/)).filter(Boolean),reported=stdout.match(/^\S pass (\d+)\s*$/m);
 if(counts.length)return counts.map(count=>count[1]).join(" + ")+" passed";
 if(reported)return reported[1]+" passed";
 const last=(stdout.trim().split(/\r?\n/).at(-1)||"").trim();
 return /\w/.test(last)?last.slice(0,100):"";
}
function runSuite(dir,name,timeout){
 return new Promise(resolve=>{
  const started=Date.now(),stdout=[],output=[];let timedOut=false,settled=false;
  const finish=reason=>{
   if(settled)return;
   settled=true;clearTimeout(timer);
   resolve({reason,seconds:(Date.now()-started)/1000,stdout:Buffer.concat(stdout).toString("utf8"),output:Buffer.concat(output).toString("utf8")});
  };
  const child=spawn(process.execPath,[path.join(dir,name)],{cwd:path.dirname(dir),windowsHide:true,stdio:["ignore","pipe","pipe"]});
  const timer=setTimeout(()=>{timedOut=true;child.kill();},timeout*1000);
  child.stdout.on("data",chunk=>{stdout.push(chunk);output.push(chunk);});
  child.stderr.on("data",chunk=>output.push(chunk));
  child.on("error",error=>finish("could not start: "+error.message));
  child.on("close",(code,signal)=>finish(timedOut?`timed out after ${timeout} s`:code===0?"":code===null?`stopped by ${signal}`:`exit ${code}`));
 });
}
async function main(){
 const chosen=options(process.argv.slice(2));
 if(!chosen){console.error(USAGE);process.exitCode=2;return;}
 let suites;
 try{suites=discover(chosen.dir);}catch(error){console.error(`Cannot list ${chosen.dir}: ${error.message}`);process.exitCode=2;return;}
 if(!suites.length){console.error(`No suites (*.cjs) found in ${chosen.dir}`);process.exitCode=1;return;}
 if(chosen.list){for(const name of suites)console.log(name);return;}
 const width=Math.max(...suites.map(name=>name.length)),started=Date.now(),failed=[];
 for(const name of suites){
  const result=await runSuite(chosen.dir,name,chosen.timeout);
  console.log(`${result.reason?"FAIL":"PASS"} ${name.padEnd(width)} ${result.seconds.toFixed(1).padStart(6)} s  ${result.reason||summary(result.stdout)}`.trimEnd());
  if(result.reason){
   failed.push(name);
   for(const line of result.output.trimEnd().split(/\r?\n/).slice(-FAILURE_LINES))console.log("     "+line);
  }
 }
 console.log(`Node suites: ${suites.length} run, ${suites.length-failed.length} passed, ${failed.length} failed in ${((Date.now()-started)/1000).toFixed(1)} s`);
 if(failed.length){console.log("Failed: "+failed.join(", "));process.exitCode=1;}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
