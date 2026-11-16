"use strict";
// A saved interview, a transcript export and Settings name the code that produced them: the
// release number and the build the server reports. The real exporters run against a minimal
// DOM; no browser, provider, file or network request is used.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");
const page = fs.readFileSync(path.join(__dirname, "..", "web", "index.html"), "utf8");
let passed = 0;

function harness(config) {
  const nodes = new Map(["process-name","process-owner","objective","background","answer-text","build-identity"]
    .map(id => [id,{value:"",textContent:"",hidden:true}]));
  const downloads = [];
  const scope = {
    console, window:{}, document:{getElementById:id => nodes.get(id)||null},
    fetch:() => {throw Error("Naming the build must stay local.");},
    setTimeout:() => 0, clearTimeout:() => {}, AbortController,
    captureDownload:(...args) => downloads.push(args)
  };
  const hook = `
    download=(...args)=>captureDownload(...args);
    notice=()=>{};closeMenu=()=>{};updateSaveHint=()=>{};
    window.stampTest={state,appStamp,showBuildIdentity,exportSession,sessionObject,transcriptObject,transcriptMarkdown};
  })();`;
  const patched = source.replace(/  init\(\);\s*\}\)\(\);\s*$/,hook);
  assert.notEqual(patched,source,"Install a test hook only at application initialization");
  vm.createContext(scope); vm.runInContext(patched,scope,{filename:"app.js"});
  const app = scope.window.stampTest;
  app.state.context = {process_name:"Supply order",process_owner:"Office manager",objective:"Understand the work",background:""};
  app.state.turns = [{id:"t001",role:"assistant",text:"What work would you like to walk through?"},
    {id:"t002",role:"user",text:"Every Monday I count the supply cupboard."}];
  app.state.config = config;
  return {app,nodes,downloads};
}
async function check(name,fn) {try {await fn();passed++;} catch(error) {error.message=name+": "+error.message;throw error;}}
const release = {version:"0.29.0",build:"0123456789ab",release_commit:"0123456789abcdef0123456789abcdef01234567"};
const tree = {version:"0.29.0",build:"dev+0c30417a9a85",release_commit:""};

(async () => {
  await check("Save copy names the release and the build that wrote it",async () => {
    for (const config of [release,tree]) {
      const {app,downloads} = harness(config);
      await app.exportSession();
      assert.equal(downloads.length,1);
      const saved = JSON.parse(downloads[0][0]);
      assert.equal(saved.app_version,"0.29.0");assert.equal(saved.app_build,config.build);
      // Still a saved interview of this app, with everything it carried before.
      assert.equal(saved.schema_version,1);assert.equal(saved.turns.length,2);assert.equal(saved.context.process_name,"Supply order");
    }
  });

  await check("the stamp is added to the saved file only, not to what is submitted or compared",() => {
    const {app} = harness(release), plain = app.sessionObject();
    assert.equal("app_build" in plain,false);assert.equal("app_version" in plain,false);
  });

  await check("transcript exports name the build in both formats",() => {
    const {app} = harness(release), data = app.transcriptObject();
    assert.equal(data.app_version,"0.29.0");assert.equal(data.app_build,"0123456789ab");
    const header = app.transcriptMarkdown(data).split("\n").find(line => line.startsWith("Format: "));
    assert.equal(header,"Format: ai-process-collector-transcript · schema 1 · app 0.29.0 · build 0123456789ab");
    const dev = harness(tree).app;
    assert.match(dev.transcriptMarkdown(dev.transcriptObject()),/ · app 0\.29\.0 · build dev\\?\+0c30417a9a85\n/);
  });

  await check("an older or unreachable server is named as unknown, never guessed",async () => {
    for (const config of [null,{},{version:"0.29.0"},{version:7,build:{}},{version:"",build:""}]) {
      const {app,downloads} = harness(config), stamp = app.appStamp();
      assert.equal(stamp.app_build,"unknown");
      assert.equal(stamp.app_version,config?.version==="0.29.0"?"0.29.0":"unknown");
      await app.exportSession();
      assert.equal(JSON.parse(downloads[0][0]).app_build,"unknown");
      assert.equal(app.transcriptObject().app_build,"unknown");
    }
    // Only a short label is taken from what the server reports: nothing long, no markup.
    for (const build of ["x".repeat(101),"<b>0123</b>","0123 4567","a\nb"])
      assert.equal(harness({version:"0.29.0",build}).app.appStamp().app_build,"unknown");
    assert.equal(harness({version:"0.29.0",build:"x".repeat(100)}).app.appStamp().app_build,"x".repeat(100));
  });

  await check("Settings shows the release and the build",() => {
    assert.match(page,/<p id="build-identity"[^>]*hidden[^>]*><\/p>/,"Settings needs a place for the build");
    const settings = page.slice(page.indexOf('<dialog id="interview-settings"'));
    assert.ok(settings.indexOf('id="build-identity"')>0&&settings.indexOf('id="build-identity"')<settings.indexOf("</dialog>"));
    const shown = harness(release);shown.app.showBuildIdentity();
    assert.equal(shown.nodes.get("build-identity").textContent,"Version 0.29.0 · build 0123456789ab");
    assert.equal(shown.nodes.get("build-identity").hidden,false);
    const dev = harness(tree);dev.app.showBuildIdentity();
    assert.equal(dev.nodes.get("build-identity").textContent,"Version 0.29.0 · build dev+0c30417a9a85");
    // A page without that line (an older index.html served from cache) does not stop the start.
    const without = harness(release);without.nodes.delete("build-identity");without.app.showBuildIdentity();
  });

  console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0}));
})().catch(error => {console.error(error);process.exitCode=1;});
