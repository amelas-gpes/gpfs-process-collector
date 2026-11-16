"use strict";
// Raw CDP leaves Chrome's native background throttling and visibility state enabled.
// Serve the production polling controller and a delayed, loopback-only result.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const {spawn} = require("node:child_process");
const {once} = require("node:events");
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const hold = Number(process.argv[2] || 95000);
const html = `<button id="send">Send answer</button><output></output><script src="/concurrent-interview.js"></script><script>
const snapshot={context:{},turns:[{id:"a",role:"user",text:"The registrar files the waiver."}]};
const service=new CollectorConcurrentInterview({getSnapshot:()=>snapshot,getGeneration:()=>0,
 request:async(url,payload)=>{const response=await fetch(url,{method:"POST",body:JSON.stringify(payload)});return response.json();},
 applyCapture:()=>{document.querySelector("output").textContent=document.visibilityState;window.appliedAt=Date.now();}});
document.getElementById("send").onclick=()=>service.turn(snapshot);</script>`;

async function main(){
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),"collector-browser-hidden-"));
  const script=fs.readFileSync(path.join(__dirname,"../../web/concurrent-interview.js"));
  const polls=[];
  let started=0;
  const server=http.createServer((req,res)=>{
    if(req.url==="/concurrent-interview.js"){res.writeHead(200,{"Content-Type":"text/javascript"});return res.end(script);}
    if(req.url==="/api/conversation/turn"){started=Date.now();return res.end(JSON.stringify({conversation_token:"hidden-fixture",revision:"one"}));}
    if(req.url.startsWith("/api/conversation/status")){
      const now=Date.now();polls.push(now);const ready=now-started>=hold;
      return res.end(JSON.stringify({conversation_token:"hidden-fixture",revision:"one",current:true,
        state:ready?"ready":"working",workflow_state:ready?"ready":"working",...(ready?{capture:{memo_findings:[],summary:"Filed"}}:{})}));
    }
    res.writeHead(200,{"Content-Type":"text/html"});res.end(html);
  });
  server.listen(0,"127.0.0.1");await once(server,"listening");
  const origin="http://127.0.0.1:"+server.address().port;
  const chrome=spawn(process.env.COLLECTOR_BROWSER||"chrome",["--headless=new","--remote-debugging-port=0",
      "--user-data-dir="+profile,"--no-first-run","--disable-background-networking","--disable-component-update",
      "--disable-sync","--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1","about:blank"],
    {windowsHide:true,stdio:["ignore","ignore","pipe"]});
  let socket;
  try{
    const endpoint=await new Promise((resolve,reject)=>{
      const timeout=setTimeout(()=>reject(Error("Browser startup timed out")),15000);timeout.unref();
      chrome.once("error",reject);chrome.once("exit",code=>reject(Error("Browser exited "+code)));
      let log="";chrome.stderr.on("data",chunk=>{log+=chunk;const match=log.match(/DevTools listening on (ws:\/\/[^\s]+)/);if(match){clearTimeout(timeout);resolve(match[1]);}});
    });
    socket=new WebSocket(endpoint);await once(socket,"open");
    let id=0;const pending=new Map();
    socket.addEventListener("message",event=>{
      const message=JSON.parse(event.data);const request=pending.get(message.id);
      if(request){pending.delete(message.id);message.error?request.reject(Error(message.error.message)):request.resolve(message.result);}
    });
    const send=(method,params={},sessionId)=>new Promise((resolve,reject)=>{
      const key=++id,timer=setTimeout(()=>{pending.delete(key);reject(Error("Browser response timed out: "+method));},10000);
      pending.set(key,{resolve:value=>{clearTimeout(timer);resolve(value);},reject:error=>{clearTimeout(timer);reject(error);}});
      socket.send(JSON.stringify({id:key,method,params,sessionId}));
    });
    const {targetId}=await send("Target.createTarget",{url:origin});
    const {sessionId}=await send("Target.attachToTarget",{targetId,flatten:true});
    const evaluate=async expression=>(await send("Runtime.evaluate",{expression,returnByValue:true},sessionId)).result.value;
    for(let i=0;i<100&&!await evaluate("Boolean(window.CollectorConcurrentInterview)");i++)await sleep(50);
    await send("Target.activateTarget",{targetId});await evaluate("document.getElementById('send').click()");
    const other=await send("Target.createTarget",{url:"about:blank"});
    await send("Target.activateTarget",{targetId:other.targetId});await sleep(200);
    assert.equal(await evaluate("document.visibilityState"),"hidden","Chrome must actually hide the interview tab");
    const deadline=Date.now()+hold+15000;
    while(Date.now()<deadline&&!await evaluate("window.appliedAt"))await sleep(300);
    assert.equal(await evaluate("document.querySelector('output').textContent"),"hidden");
    const completed=await evaluate("window.appliedAt");
    assert(completed-started-hold<5000,"Hidden result took over five seconds to apply");
    const tail=polls.filter(time=>time-started>=Math.max(0,hold-10000));
    assert(tail.length>=2);const maxGap=Math.max(...tail.slice(1).map((time,i)=>time-tail[i]));
    console.log(JSON.stringify({hidden_ms:hold,applied_after_ms:completed-started-hold,max_poll_gap_ms:maxGap,provider_calls:0}));
    assert(maxGap<5000,"Hidden status poll stalled");
  }finally{
    socket?.close();chrome.kill();if(chrome.exitCode===null)await Promise.race([once(chrome,"exit"),sleep(2000)]);
    server.closeAllConnections();server.close();
    assert.equal(path.dirname(path.resolve(profile)),path.resolve(os.tmpdir()));
    assert(path.basename(profile).startsWith("collector-browser-hidden-"));
    fs.rmSync(profile,{recursive:true,force:true,maxRetries:8,retryDelay:200});
  }
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
