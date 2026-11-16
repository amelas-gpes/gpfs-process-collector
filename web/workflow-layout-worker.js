/* Workflow layout worker: runs the locally bundled ELK engine off the page's thread.
   workflow-graph.js posts {id, graph} and receives {id, layout} or {id, error}. */
"use strict";
importScripts("/vendor/elk.bundled.js");
// Constructing the engine loads the layout code. In a worker that code also installs its
// own message handler, which the handler below replaces.
const engine=new self.ELK();
self.onmessage=event=>{
  const {id,graph}=event.data||{};
  const fail=error=>self.postMessage({id,error:String(error?.message||error||"The workflow layout could not be calculated.")});
  try{engine.layout(graph).then(layout=>self.postMessage({id,layout}),fail);}catch(error){fail(error);}
};
