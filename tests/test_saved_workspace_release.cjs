"use strict";
const assert = require("node:assert/strict");
const {open} = require("./fixtures/app_page.cjs");

async function main() {
  const page = await open({modules:["documents.js","document-intake.js"], expose:"sessionObject,applySavedSession,getFiles:()=>documentController,getIntake:()=>documentIntake,searchRanges,foldSearch"});
  for(const [original,query,shown] of [["Straße","STRASSE","Straße"],["cafe\u0301","CAFÉ","cafe\u0301"],
      ["İstanbul","istanbul","İstanbul"],["xﬂower","flower","ﬂower"],["عرضَ","عرض","عرضَ"]]){
    const matches=Array.from(page.t.searchRanges(original,page.t.foldSearch(query)),range=>original.slice(range.start,range.end));
    assert.deepEqual(matches,[shown]);
  }
  const scope = "1".repeat(48);
  const file = {id:"doc_old", name:"Fictional register.csv", kind:"csv", size:24, status:"ready"};
  const previous = [{scope, documents:[file]}];
  page.t.getFiles().unavailableWorkspaces = previous;
  const saved = JSON.parse(JSON.stringify(page.t.sessionObject({includePresentation:true})));
  assert.deepEqual(saved.documents.unavailable_workspaces, previous);
  page.t.getFiles().unavailableWorkspaces = [];
  assert.equal(await page.t.applySavedSession(() => saved), true);
  assert.deepEqual(JSON.parse(JSON.stringify(page.t.getFiles().unavailableWorkspaces)), previous);
  assert.equal(page.state.coverageNeedsReview, false);
  const bad = {...saved, documents:{...saved.documents, unavailable_workspaces:[{scope, documents:"invalid"}]}};
  assert.equal(await page.t.applySavedSession(() => bad), false);
  assert.deepEqual(JSON.parse(JSON.stringify(page.t.getFiles().unavailableWorkspaces)), previous);
  const fileState=page.t.getFiles();
  fileState.documents=[{...file,chunk_count:1,analysis:{phase:"complete",disposition:"relevant"}}];
  const intake=page.t.getIntake();intake.phase="reviewing";intake.ids.add(file.id);
  const interrupted=JSON.parse(JSON.stringify(page.t.sessionObject({includePresentation:true})));
  assert.deepEqual(interrupted.unfinished_file_review,{ids:[file.id]});
  const prior=page.requests.filter(request=>request.url.startsWith("/api/interview")).length;
  assert.equal(await page.t.applySavedSession(()=>interrupted),true);
  assert.equal(page.t.getIntake().active,false);
  assert.equal(page.$("saved-file-followup").hidden,false);
  assert.match(page.$("saved-file-followup-text").textContent,/unfinished|unavailable/);
  assert.equal(page.requests.filter(request=>request.url.startsWith("/api/interview")).length,prior);
  console.log("Passed saved file workspace round trip, empty coverage and malformed import.");
}
main().catch(error => {console.error(error); process.exitCode=1;});
