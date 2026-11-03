/* GPFS vector source: https://gpfs.com/images/logo/rev/rev_gpfs_stacked.svg
 * Source geometry and palette retained. See docs/GPFS_ASSET.md. */
(function (global) {
  "use strict";
  const SOURCE = [{"tag":"path","attrs":{"d":"M11.94633,19.05513h3.60253a1.947,1.947,0,0,1,1.947,1.947v3.60247a1.947,1.947,0,0,1-1.947,1.947H11.94653a1.94707,1.94707,0,0,1-1.94707-1.94707V21.002A1.94686,1.94686,0,0,1,11.94633,19.05513Z","transform":"translate(-12.09812 16.40127) rotate(-45.00283)","fill":"#8b7d65"}},{"tag":"path","attrs":{"d":"M21.56569,9.4359H25.168a1.947,1.947,0,0,1,1.947,1.947v3.60238a1.947,1.947,0,0,1-1.947,1.947H21.56562a1.947,1.947,0,0,1-1.947-1.947V11.38294A1.947,1.947,0,0,1,21.56569,9.4359Z","transform":"translate(-2.47857 20.38441) rotate(-45.00006)","fill":"#8b7d65"}},{"tag":"path","attrs":{"d":"M31.185,19.05525h3.60236a1.947,1.947,0,0,1,1.947,1.947V24.6046a1.947,1.947,0,0,1-1.947,1.947H31.185a1.947,1.947,0,0,1-1.947-1.947V21.0022a1.947,1.947,0,0,1,1.947-1.947Z","transform":"translate(-6.46299 30.00378) rotate(-45.00006)","fill":"#8b7d65"}},{"tag":"path","attrs":{"d":"M21.56561,28.67442H25.168a1.947,1.947,0,0,1,1.947,1.947V34.2238a1.947,1.947,0,0,1-1.947,1.947h-3.6024a1.947,1.947,0,0,1-1.947-1.947V30.62136a1.94693,1.94693,0,0,1,1.94693-1.94693Z","transform":"translate(-16.08238 26.02) rotate(-45.00114)","fill":"#8b7d65"}},{"tag":"path","attrs":{"d":"M25.29646,22.783l8.7005-8.70092a1.3122,1.3122,0,0,0,0-1.85649L24.3682,2.59689a1.31222,1.31222,0,0,0-1.8565,0l-9.62924,9.62866a1.31221,1.31221,0,0,0,0,1.85649L21.583,22.78252,17.01964,27.3463a1.31274,1.31274,0,0,0,1.85651,1.85649l4.56332-4.56328,7.77225,7.77224L23.44,40.18343,6.039,22.78247l5.95471-5.95516a1.31274,1.31274,0,0,0-1.8565-1.85649L3.25372,21.85421a1.31219,1.31219,0,0,0,0,1.85649l19.258,19.258a1.31222,1.31222,0,0,0,1.8565,0L33.997,33.34a1.31219,1.31219,0,0,0,0-1.85649ZM15.66771,13.1538,23.44,5.38212l7.77176,7.77174L23.43947,20.926Z","fill":"#c9753a"}}];
  const NS = "http://www.w3.org/2000/svg";
  const STATES = new Set(["idle", "connecting", "listening", "speaking", "processing", "muted", "ended"]);
  const CENTERS = [[13.7476,22.8038],[23.3668,13.1841],[32.9861,22.8039],[23.3668,32.4229],[23.44,22.783]];
  const DIRECTIONS = [[-1,0],[0,-1],[1,0],[0,1]];
  let sequence = 0;
  const clamp = (value, lo=0, hi=1) => Math.min(hi, Math.max(lo, Number.isFinite(value) ? value : lo));
  const ease = (current, target, dt, time) => current + (target-current)*(1-Math.exp(-dt/time));
  const round = value => Math.round(value*10000)/10000 || 0;
  function create(root, options={}) {
    if (!root || !root.ownerDocument) throw new TypeError("GPFS presence needs a mounted element.");
    const doc = root.ownerDocument;
    const view = doc.defaultView || global;
    const clock = options.now || (() => view.performance ? view.performance.now() : Date.now());
    const raf = options.requestAnimationFrame || (callback => view.requestAnimationFrame(callback));
    const caf = options.cancelAnimationFrame || (id => view.cancelAnimationFrame(id));
    const media = options.motionQuery || (view.matchMedia ? view.matchMedia("(prefers-reduced-motion: reduce)") : null);
    const id = "gpfs-light-"+(++sequence);
    const node = (tag, attrs={}, parent) => {
      const element = doc.createElementNS(NS, tag);
      for (const [key,value] of Object.entries(attrs)) element.setAttribute(key, String(value));
      if (parent) parent.appendChild(element);
      return element;
    };
    const svg = node("svg", {class:"gpfs-symbol", viewBox:"-3 -4 48 54", "aria-hidden":"true", focusable:"false"});
    const defs = node("defs", {}, svg);
    // Illumination is clipped by the original fill contours, never blurred outside them.
    const light = node("radialGradient", {id, gradientUnits:"userSpaceOnUse", cx:23.44, cy:22.783, r:29}, defs);
    const stops = [[0,0],[.24,0],[.43,.26],[.65,0],[1,0]].map(([offset,opacity]) => node("stop", {offset, "stop-color":"#fff6e9", "stop-opacity":opacity}, light));
    const tileLight = node("linearGradient", {id:id+"-tile", x1:"0%", y1:"100%", x2:"100%", y2:"0%"}, defs);
    node("stop", {offset:0,"stop-color":"#fff6e9","stop-opacity":0}, tileLight);
    node("stop", {offset:.55,"stop-color":"#fff6e9","stop-opacity":.09}, tileLight);
    node("stop", {offset:1,"stop-color":"#fff6e9","stop-opacity":.3}, tileLight);
    const parts = SOURCE.map((source,index) => {
      const group = node("g", {"data-gpfs-part":index}, svg);
      node(source.tag, source.attrs, group);
      const shine = node(source.tag, {...source.attrs, fill:"url(#"+id+(index===4?"":"-tile")+")", opacity:0}, group);
      return {group,shine};
    });
    root.replaceChildren(svg);
    root.classList.add("gpfs-presence");
    root.setAttribute("data-state","idle");
    let state="idle", mode="idle", visible=true, disposed=false, reduced=!!(media&&media.matches), rafId=null;
    let last=null, lastPaint=null, renderCount=0, outputSeen=false, activityTime=0, paintedMode="idle";
    let frame={input:0,output:0,inputActive:false,outputActive:false,playbackActive:false,muted:false,connected:false};
    const pose={input:0,output:0,gather:0,project:0,tilt:0,band:.5,light:.14,accent:0};
    let renderedParts=CENTERS.map(()=>({x:0,y:0,rotation:0}));
    const isShown=()=>visible&&!doc.hidden;
    function effectiveMode() {
      if(state==="idle"||state==="ended") return state;
      if(state==="connecting") return "connecting";
      // A real microphone interruption immediately yields the projecting posture.
      if(frame.connected&&frame.inputActive&&!frame.muted) return "listening";
      if(frame.connected&&frame.outputActive) return "speaking";
      // Typed-question playback is signaled by the audio element's actual playing event.
      // It has no WebRTC meter; retain a composed projecting posture with no fake level.
      if(state==="speaking"&&!frame.connected) return "speaking";
      // Keep the voice's posture through phrase pauses, but not after playback ends.
      if(state==="speaking"&&outputSeen&&frame.connected&&frame.playbackActive) return "speaking";
      if(state==="processing") return "processing";
      if(state==="muted"||frame.muted) return "muted";
      return "listening";
    }
    function targets(dt) {
      mode=effectiveMode();
      const signal=(level,floor)=>Math.pow(clamp((clamp(level)-floor)/(1-floor)),.72);
      const inTarget=mode==="listening"&&!frame.muted?signal(frame.input,.018):0;
      const outTarget=mode==="speaking"?signal(frame.output,.012):0;
      const previous=mode==="speaking"?pose.output:pose.input;
      pose.input=ease(pose.input,inTarget,dt,inTarget>pose.input?.06:.27);
      pose.output=ease(pose.output,outTarget,dt,outTarget>pose.output?.038:.2);
      const level=mode==="speaking"?pose.output:pose.input;
      const accent=clamp((level-previous)*6);
      pose.accent=ease(pose.accent,accent,dt,accent>pose.accent?.035:.17);
      activityTime+=dt;
      // Only actual connecting/waiting states have restrained autonomous motion.
      const connecting=mode==="connecting"?Math.sin(activityTime*2.8)*.085:0;
      const waiting=mode==="processing"?Math.sin(activityTime*1.7)*.065:0;
      const gather=mode==="listening"?.22+.95*pose.input+.16*pose.accent:mode==="connecting"?.11+connecting:0;
      const project=mode==="speaking"?.22+1.18*pose.output+.2*pose.accent:mode==="processing"?.07+waiting:0;
      const tilt=mode==="listening"?-.15-.62*pose.input:mode==="speaking"?.16+.8*pose.output:waiting;
      const band=mode==="listening"?.8-.54*pose.input:mode==="speaking"?.22+.57*pose.output:.5;
      const illumination=mode==="speaking"?.25+.54*pose.output:mode==="listening"?.19+.43*pose.input:mode==="connecting"?.21+connecting:mode==="processing"?.19+waiting:.12;
      pose.gather=ease(pose.gather,gather,dt,.15);
      pose.project=ease(pose.project,project,dt,.13);
      pose.tilt=ease(pose.tilt,tilt,dt,.19);
      pose.band=ease(pose.band,band,dt,.11);
      pose.light=ease(pose.light,illumination,dt,.12);
    }
    function paint() {
      root.setAttribute("data-state",state);
      root.setAttribute("data-mode",mode);
      root.setAttribute("data-motion",reduced?"reduced":"full");
      const distance=reduced?0:pose.project-pose.gather;
      renderedParts=parts.map(({group,shine},index)=>{
        const [cx,cy]=CENTERS[index];
        const direction=DIRECTIONS[index]||[0,0];
        const x=index===4?0:direction[0]*distance;
        const y=index===4?(reduced?0:pose.tilt*.1):direction[1]*distance;
        const rotation=reduced?0:pose.tilt*(index===4?.75:index%2===0?1:-1);
        group.setAttribute("transform",`translate(${round(x)} ${round(y)}) rotate(${round(rotation)} ${cx} ${cy})`);
        // Soft surface light: no filter, halo, opacity pulse or silhouette scaling.
        shine.setAttribute("opacity",round(pose.light*(index===4?1:.66)));
        return{x:round(x),y:round(y),rotation:round(rotation)};
      });
      const band=reduced?.5:pose.band;
      [.0,Math.max(0,band-.2),band,Math.min(1,band+.2),1].forEach((offset,index)=>stops[index].setAttribute("offset",round(offset)));
      paintedMode=mode;
      renderCount++;
    }
    function needsMotion() {
      if(reduced) return false;
      if(mode==="connecting"||mode==="processing") return true;
      if(mode==="listening"&&frame.input>.018&&!frame.muted) return true;
      if(mode==="speaking"&&frame.output>.012) return true;
      const gather=mode==="listening"?.22:0, project=mode==="speaking"?.22:0;
      const tilt=mode==="listening"?-.15:mode==="speaking"?.16:0;
      const band=mode==="listening"?.8:mode==="speaking"?.22:.5;
      const light=mode==="listening"?.19:mode==="speaking"?.25:.12;
      return pose.input>.001||pose.output>.001||pose.accent>.001||Math.abs(pose.gather-gather)>.001||Math.abs(pose.project-project)>.001||Math.abs(pose.tilt-tilt)>.001||Math.abs(pose.band-band)>.001||Math.abs(pose.light-light)>.001;
    }
    function inspect() {
      return {state,mode,input:round(pose.input),output:round(pose.output),gather:round(pose.gather),project:round(pose.project),tilt:round(pose.tilt),band:round(pose.band),light:round(pose.light),parts:renderedParts.map(part=>({...part})),visible:isShown(),reducedMotion:reduced,renderCount};
    }
    function sample(timestamp=clock()) {
      if(disposed||!isShown()) return inspect();
      const supplied=Number.isFinite(timestamp)?timestamp:clock();
      const time=last===null?supplied:Math.max(last,supplied);
      if(reduced){mode=effectiveMode();paint();return inspect();}
      // Clamp a resumed tab's elapsed time; it must not leap or replay missed animation.
      const dt=last===null?1/30:clamp((time-last)/1000,0,.1);
      last=time;
      targets(dt);paint();
      return inspect();
    }
    function schedule() {
      if(disposed||options.autoStart===false||!isShown()||rafId!==null||reduced) return;
      rafId=raf(tick);
    }
    function tick(timestamp) {
      rafId=null;
      if(disposed||!isShown()) return;
      if(lastPaint===null||timestamp-lastPaint>=1000/30-.5){sample(timestamp);lastPaint=timestamp;}
      if(needsMotion())schedule();
    }
    function cancel() {if(rafId!==null)caf(rafId);rafId=null;last=null;lastPaint=null;}
    function wake() {
      if(disposed||!isShown()) return;
      if(reduced){if(paintedMode!==mode||pose.gather||pose.project||pose.tilt){pose.input=pose.output=pose.accent=pose.gather=pose.project=pose.tilt=0;pose.band=.5;pose.light=mode==="speaking"?.32:mode==="listening"?.22:.14;paint();}}
      else if(needsMotion())schedule();
    }
    function setState(next) {
      if(disposed)return;
      const valid=STATES.has(next)?next:"idle";
      if(valid===state)return;
      const previous=state;state=valid;
      if(state==="idle"||state==="ended"||state==="connecting"){outputSeen=false;frame={...frame,input:0,output:0,inputActive:false,outputActive:false,playbackActive:false};}
      if(previous!=="speaking"&&state==="speaking")outputSeen=frame.outputActive;
      mode=effectiveMode();root.setAttribute("data-state",state);root.setAttribute("data-mode",mode);wake();
    }
    function setAudio(audio={}) {
      if(disposed)return;
      frame={input:clamp(audio.input),output:clamp(audio.output),inputActive:!!audio.inputActive,outputActive:!!audio.outputActive,playbackActive:!!audio.playbackActive,muted:!!audio.muted,connected:!!audio.connected};
      if(frame.outputActive&&frame.connected)outputSeen=true;
      mode=effectiveMode();root.setAttribute("data-mode",mode);wake();
    }
    function setVisible(next) {
      if(disposed)return;
      visible=!!next;
      if(!isShown())cancel();else wake();
    }
    function visibility(){if(!isShown())cancel();else wake();}
    function motionChange(event){reduced=!!event.matches;cancel();paintedMode=null;wake();}
    doc.addEventListener("visibilitychange",visibility);
    if(media){if(media.addEventListener)media.addEventListener("change",motionChange);else if(media.addListener)media.addListener(motionChange);}
    paint();
    return {setState,setAudio,setVisible,sample,inspect,dispose(){
      if(disposed)return;disposed=true;cancel();
      doc.removeEventListener("visibilitychange",visibility);
      if(media){if(media.removeEventListener)media.removeEventListener("change",motionChange);else if(media.removeListener)media.removeListener(motionChange);}
      // Preserve the last crisp vector as a quiet fallback after disposal.
    }};
  }
  global.GPFSPresence=Object.freeze({create});
})(typeof window!=="undefined"?window:globalThis);
