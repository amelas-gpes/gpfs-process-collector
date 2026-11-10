/* Reusable operational objects for the cinematic map. Coordinates are relative to the instrument deck.
   These objects illustrate activities and artifacts. They do not indicate case status or financial amounts. */
(function (scope) {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const alloy={face:"#81786c",edge:"#dedbd5",top:"#b2a999",side:"#4c4844"};
  const paper={face:"#e2ded9",edge:"#ffffff",top:"#f7f7f7",side:"#8b8277"};
  const copper={face:"#b4643c",edge:"#ffbd94",top:"#dc6e2c",side:"#794530"};
  const brass={face:"#9b8565",edge:"#f1e1c7",top:"#c4ad88",side:"#67563f"};
  const steel={face:"#6c809a",edge:"#d9e4ee",top:"#a6b6c8",side:"#434e61"};
  const clay={face:"#ad7363",edge:"#efd6cc",top:"#d28c79",side:"#745447"};
  const ink="#303033", light="#f7f7f7";
  function node(g,tag,attrs) {
    const n=g.ownerDocument.createElementNS(NS,tag);
    for(const [k,v] of Object.entries(attrs)) n.setAttribute(k,v);
    g.append(n);
    return n;
  }
  const group=(g,transform)=>node(g,"g",{transform});
  const face=(g,d,fill,stroke="none",width=1.3)=>node(g,"path",{d,fill,stroke,"stroke-width":width,"stroke-linejoin":"round"});
  const line=(g,d,color=light,width=2.4)=>node(g,"path",{d,fill:"none",stroke:color,"stroke-width":width,"stroke-linejoin":"round","stroke-linecap":"round"});
  const rect=(g,x,y,w,h,fill,rx=1,stroke="none",sw=1)=>node(g,"rect",{x,y,width:w,height:h,rx,fill,stroke,"stroke-width":sw});
  const ellipse=(g,cx,cy,rx,ry,fill,stroke="none",sw=1)=>node(g,"ellipse",{cx,cy,rx,ry,fill,stroke,"stroke-width":sw});
  const polygon=(g,pts,fill,stroke="none",sw=1)=>node(g,"polygon",{points:pts.map(p=>p.join(",")).join(" "),fill,stroke,"stroke-width":sw,"stroke-linejoin":"round"});

  // All solid components share the same projection and light direction as the structural deck.
  function block(g,x,y,w,d,h,m=alloy) {
    const u=w*.45,v=d*.45, a=w*.21,b=d*.21;
    const top=[[x-u+v,y-a-b-h],[x+u+v,y+a-b-h],[x+u-v,y+a+b-h],[x-u-v,y-a+b-h]];
    const down=p=>[p[0],p[1]+h];
    polygon(g,[top[3],top[2],down(top[2]),down(top[3])],m.face,m.side,.9);
    polygon(g,[top[2],top[1],down(top[1]),down(top[2])],m.side,m.side,.9);
    polygon(g,top,m.top,m.edge,1.15);
    line(g,"M"+top[3]+"L"+top[2]+"L"+top[1],m.edge,1);
  }
  function drum(g,x,y,r,h,m=brass) {
    const z=r*.33, top=y-h;
    face(g,`M${x-r} ${top}A${r} ${z} 0 0 1 ${x+r} ${top}V${y}a${r} ${z} 0 0 1 ${-2*r} 0Z`,m.face,m.side);
    ellipse(g,x,top,r,z,m.top,m.edge,1.3);
    ellipse(g,x,top,r*.69,z*.64,"none",m.face,.9);
    line(g,`M${x-r+2} ${y-1}a${r-2} ${z-1} 0 0 0 ${2*r-4} 0`,m.edge,1);
  }
  function stack(g,x,y,r,layers,m=brass) {
    for(let i=0;i<layers;i++) drum(g,x,y-i*7,r,5,m);
  }
  function panel(g,x,y,w,h,m=steel) {
    const p=group(g,`translate(${x} ${y}) skewY(-9)`);
    face(p,`M${-w/2} 0v${-h}l5 -3h${w}v${h}l-5 3z`,m.side,m.edge,1);
    rect(p,-w/2,-h,w,h,m.face,2,m.edge,1.8);
    return group(p,`translate(${-w/2} ${-h})`);
  }
  function sheet(g,x,y,w,h,mark,m=paper) {
    const p=group(g,`translate(${x} ${y}) skewY(-8)`);
    const s=group(p,`translate(${-w/2} ${-h})`), fold=Math.min(12,w*.22);
    face(s,`M3 -2h${w-fold}l${fold} ${fold}v${h-fold}l-4 3L2 ${h}z`,m.side,m.edge,.85);
    face(s,`M0 0h${w-fold}l${fold} ${fold}v${h-fold}H0z`,m.face,m.edge,1.7);
    face(s,`M${w-fold} 0v${fold}h${fold}z`,m.top,m.side,.9);
    if(mark)mark(s,w,h);
    return s;
  }
  function writing(s,x,y,width,rows,color=ink) {
    for(let i=0;i<rows;i++)line(s,`M${x} ${y+i*6}h${width*(i%3===2?.63:1)}`,color,1.8);
  }
  function grid(s,x,y,w,h,cols=3,rows=3,color=ink) {
    rect(s,x,y,w,h,"none",.5,color,1.3);
    for(let i=1;i<cols;i++)line(s,`M${x+w*i/cols} ${y}v${h}`,color,1.2);
    for(let i=1;i<rows;i++)line(s,`M${x} ${y+h*i/rows}h${w}`,color,1.2);
  }
  function wheel(g,x,y,r,m=brass) {
    const d=group(g,`translate(${x} ${y}) skewY(-9)`);
    ellipse(d,4,-1,r,r,m.side,m.edge,1);
    ellipse(d,0,0,r,r,m.face,m.edge,2);
    ellipse(d,0,0,r*.76,r*.76,ink,m.top,1.4);
    return d;
  }
  function pointerDial(g,x,y,r,m) {
    const p=wheel(g,x,y,r,m);
    for(let i=-60;i<=60;i+=30) line(group(p,"rotate("+i+")"),`M0 ${-r*.63}v3`,m.edge,1.4);
    line(p,`M0 0l${r*.46} ${-r*.48}`,m.edge,2.6);
    ellipse(p,0,0,2.6,2.6,m.top);
  }
  function arrow(g,d,tip,color=copper.top) { line(g,d,ink,7);line(g,d,color,3.3);face(g,tip,color,ink,.7); }
  function connector(g,x,y,toX,toY,color=copper.top) {
    const mid=(x+toX)/2;
    line(g,`M${x} ${y}H${mid-4}l8 ${toY-y}H${toX}`,ink,6);
    line(g,`M${x} ${y}H${mid-4}l8 ${toY-y}H${toX}`,color,2.2);
  }
  function badge(g,x,y,r,m=steel) {
    const b=wheel(g,x,y,r,m);
    ellipse(b,0,-r*.24,r*.23,r*.26,m.top);
    face(b,`M${-r*.47} ${r*.44}Q${-r*.44} 0 0 0Q${r*.44} 0 ${r*.47} ${r*.44}Z`,m.top);
  }
  function envelope(g,x,y,w,h,m=steel,open=false) {
    const p=group(g,`translate(${x} ${y}) skewY(-8)`);
    if(open) face(p,`M${-w/2} ${-h}l${w/2} ${-h*.64}l${w/2} ${h*.64}Z`,m.side,m.edge);
    face(p,`M${-w/2} ${-h}h${w}v${h}h${-w}z`,m.face,m.edge,1.8);
    line(p,`M${-w/2} ${-h}L0 ${-h*.35}l${w/2} ${-h*.65}M${-w/2+1} -1l${w*.34} ${-h*.45}M${w/2-1} -1l${-w*.34} ${-h*.45}`,m.edge,1.65);
  }
  function tray(g,x,y,w,d,m=steel) {
    block(g,x,y,w,d,8,m); block(g,x,y-8,w*.74,d*.74,2,alloy);
  }
  function ledger(g,x,y,w,h,m=paper) {
    const p=group(g,`translate(${x} ${y})`), half=w/2;
    face(p,`M${-half} ${-h-7}Q-16 ${-h-9} 0 ${-h+2}Q18 ${-h-11} ${half} ${-h-13}V-5Q16 -3 0 6Q-21 -6 ${-half} 0Z`,steel.side,steel.edge,1.8);
    face(p,`M${-half+3} ${-h-4}Q-17 ${-h-7} 0 ${-h+3}V2Q-19 -6 ${-half+3} -3Z`,m.face,m.edge,1);
    face(p,`M0 ${-h+3}Q18 ${-h-10} ${half-3} ${-h-10}V-8Q16 -5 0 2Z`,m.top,m.edge,1);
    for(let j=0;j<3;j++){
      const y=-h+14+j*8;
      line(p,`M${-half+8} ${y-4}q${half*.38} -1 ${half-15} 5M6 ${y}q${half*.34} -7 ${half-14} -8`,ink,1.4);
    }
  }
  function calendar(g,x,y,w,h) {
    const p=panel(g,x,y,w,h,paper);
    rect(p,1,1,w-2,11,steel.face); grid(p,6,17,w-12,h-23,3,2);
    for(const x of [w*.24,w*.74])rect(p,x,-5,4,12,alloy.top,2,ink,.8);
    return p;
  }
  function rail(g,x,y,w,color=copper.top) {
    block(g,x,y,w,13,5,alloy);
    line(g,`M${x-w*.36} ${y-w*.168-3}l${w*.71} ${w*.33}`,color,1.7);
  }
  function diamond(g,x,y,r,m=copper) {
    face(g,`M${x-r} ${y-r*.2}l${r*.47} ${-r*.7}h${r*1.06}l${r*.47} ${r*.7}l${-r} ${r*1.08}Z`,m.face,m.edge,2);
    line(g,`M${x-r} ${y-r*.2}h${r*2}m${-r*1.53} ${-r*.69}l${r*.18} ${r*.69}l${r*.35} ${r*1.08}l${r*.38} ${-r*1.08}l${r*.16} ${-r*.69}`,m.edge,1.2);
  }
  function building(g,x,y) {
    const p=group(g,`translate(${x} ${y}) skewY(-9)`);
    rect(p,-27,-6,54,7,alloy.face,1,alloy.edge);
    rect(p,-23,-38,46,31,ink,0);
    for(const c of [-17,0,17]) {rect(p,c-3,-37,6,31,paper.face,.8,paper.edge);rect(p,c-5,-37,10,3,alloy.top);}
    face(p,"M-31 -37L0 -55l31 18z",steel.face,steel.edge,1.7); line(p,"M-24 -38l24 -12 23 12",paper.edge,1.3);
  }
  const catalog = new Map();
  function design(id,detail,draw) { catalog.set(id,{detail,draw}); }

  design("capital_call","A call letter rises from an open envelope beside the capital stack.",g=>{
    sheet(g,-8,-19,51,64,(s)=>{rect(s,7,10,14,8,copper.top);writing(s,7,26,32,4);});
    envelope(g,-8,1,68,33,steel);stack(g,32,8,15,3);
  });
  design("investor_allocation","One capital hub branches into three separate investor positions.",g=>{
    line(g,"M-30 -65L-8 -43H11M-8 -43l18 -22M-8 -43l21 19M-8 -43l-7 33",copper.top,5);
    drum(g,-30,-57,20,13,brass);badge(g,19,-69,13);badge(g,31,-29,13);badge(g,-17,-8,13);
  });
  design("waterfall","Three stepped distribution tiers carry a single copper channel from crest to basin.",g=>{
    block(g,-29,-17,40,29,60,steel);block(g,1,-6,37,30,40,alloy);block(g,31,5,35,30,19,brass);
    line(g,"M-44 -77l23 10v16l24 11v13l28 13v9l14 7",ink,9);
    line(g,"M-44 -77l23 10v16l24 11v13l28 13v9l14 7",copper.top,5);
  });
  design("tax_withholding","A forked sluice diverts one stream into a walled reserve cup.",g=>{
    rail(g,-18,-25,83);line(g,"M-46 -44l37 16 32-19",steel.edge,5);
    line(g,"M-9 -28l25 16",copper.top,5);
    drum(g,30,-45,14,8,steel);drum(g,26,4,21,20,brass);ellipse(g,26,-16,14,4,ink);
    line(g,"M1 -50v27",paper.edge,4);line(g,"M-6 -51h14",copper.top,5);
  });
  design("in_kind","A faceted security rests in a fitted delivery crate with an open lid.",g=>{
    const lid=panel(g,-10,-30,56,39,steel);grid(lid,5,6,45,26,2,2,steel.edge);
    tray(g,4,4,66,57,brass);diamond(g,6,-43,24,steel);
  });
  design("equalization","A pivoting balance beam carries paired capital positions on suspended pans.",g=>{
    block(g,0,3,40,27,7,alloy);face(g,"M-10 -4L-2 -60h6l9 57z",brass.face,brass.edge);
    line(g,"M-42 -72L38 -72",ink,7);line(g,"M-42 -73h80",copper.top,3);
    for(const x of [-38,37]) {line(g,`M${x} -72l-13 29h26z`,steel.edge,1.7);drum(g,x,-39,15,4,steel);stack(g,x,-44,9,2);}
  });
  design("fee_waiver","A perforated fee coupon separates at its notched seam beside the original record.",g=>{
    sheet(g,-18,-5,39,66,(s)=>writing(s,6,16,21,5));
    const t=group(g,"translate(16 -43) rotate(-19)");
    face(t,"M-25 -17h43v8q-8 5 0 10v9h-43v-9q8-5 0-10z",clay.top,clay.edge,2);
    line(t,"M7 -15v3m0 4v4m0 4v4m0 4v3",ink,2);line(t,"M-14 -4h12m-12 6h8",ink,2);
    face(t,"M24 -17h9v37h-9v-11q-7-4 0-9z",brass.face,brass.edge);
  });
  design("partner_transfer","Two holder medallions share a transfer bridge with a travelling deed.",g=>{
    connector(g,-29,-16,31,-35);badge(g,-39,-42,23,steel);badge(g,39,-57,20,brass);
    sheet(g,1,-6,23,31,s=>writing(s,4,11,14,2));
  });
  design("member_change","A removable member card slides into a roster rack with two occupied bays.",g=>{
    panel(g,-15,-13,61,41,steel);
    for(const x of [-31,-9])badge(g,x,-45,10,brass);
    line(g,"M9 -20l16 8 23-11",alloy.top,4);
    const p=panel(g,28,-31,28,40,paper);badge(p,14,15,8,clay);line(p,"M6 30h16",ink,2);
  });
  design("vesting","Successive steps and a movable copper pin distinguish earned tranches over time.",g=>{
    for(let i=0;i<4;i++){const x=-36+i*24,y=-12+i*4;block(g,x,y,24,30,17+i*12,i===2?copper:steel);}
    line(g,"M8 -54v-27",alloy.edge,3);face(g,"M8 -82l15 1-5 6H8Z",copper.top,copper.edge);
  });
  design("clawback","A raised return track bends capital back into a recovery cradle.",g=>{
    tray(g,-19,5,61,38,steel);stack(g,-20,-10,15,2);
    arrow(g,"M-32 -63Q7 -95 29 -64Q48 -34 5 -26","M3 -35l-13 12 20 4z");
    drum(g,27,-49,10,5);
  });
  design("wind_down","A narrowing row of ledger positions terminates at a mechanical end stop.",g=>{
    rail(g,0,1,109);stack(g,-35,-21,16,6);stack(g,-7,-9,14,4,alloy);stack(g,20,1,12,2,steel);
    block(g,44,9,7,27,17,copper);
  });
  design("investor_onboarding","A profile card enters a keyed master-record sleeve and index rail.",g=>{
    const p=panel(g,-6,-27,44,54,paper);badge(p,19,20,11,steel);writing(p,7,39,24,2);
    block(g,0,0,71,29,22,steel);line(g,"M-24 -29l34 14",copper.top,3);
    block(g,26,-7,14,15,16,brass);
  });
  design("special_profit","A separate gated income channel crosses the main partner ledger.",g=>{
    ledger(g,-4,-2,81,37);line(g,"M-43 -64h27l26 23h30",ink,7);
    line(g,"M-43 -64h27l26 23h30",copper.top,3);
    block(g,2,-46,10,20,20,brass);drum(g,36,-38,10,6,clay);
  });
  design("holdback","A reserve cage retains one capital stack behind a fixed partition.",g=>{
    tray(g,0,0,77,51,alloy);stack(g,-19,-13,15,6);stack(g,28,0,12,2,steel);
    line(g,"M-39 -49v44l37 10v-55zM-28 -45v43m13-40v44",brass.edge,3);
    block(g,3,-9,5,34,36,copper);
  });
  design("investment_setup","A faceted investment is seated in a keyed registry socket beside its identifying card.",g=>{
    tray(g,-13,-2,50,47,steel);diamond(g,-17,-38,23,steel);
    const p=panel(g,28,-13,29,52,paper);rect(p,5,7,10,11,copper.top);writing(p,5,25,17,3);
  });
  design("loan_schedule","A bound date grid carries linked coupon tags along its payment edge.",g=>{
    const p=calendar(g,-7,-13,63,56);
    for(const [x,y] of [[15,22],[32,37],[49,37]])ellipse(p,x,y,3,3,copper.top);
    rail(g,14,1,64);
    for(const [x,y] of [[-8,-7],[11,1],[32,10]])block(g,x,y,9,12,10,brass);
  });
  design("yield_calculation","A calibrated arc and sloped earnings trace compare investment return against a base.",g=>{
    const p=panel(g,-13,-12,61,55,steel);
    line(p,"M8 7v39h45",paper.edge,2);line(p,"M10 39l10-3 8-12 10-1 12-15",copper.edge,3.6);
    pointerDial(g,30,-28,18,brass);
  });
  design("cash_interest","A detachable coupon hangs over a separate cash collection cup.",g=>{
    const s=sheet(g,-9,-19,48,62,(p)=>{writing(p,7,15,25,3);line(p,"M3 42h5m4 0h5m4 0h5m4 0h6",ink,1.6);});
    rect(s,6,48,26,7,brass.top);drum(g,24,2,21,15,steel);stack(g,24,-14,13,2);
  });
  design("pik_accrual","A new capital ring nests into the principal stack under a vertical guide.",g=>{
    stack(g,-6,-2,29,5,steel);drum(g,-6,-55,28,8,copper);
    line(g,"M-37 -6v-67m63 80v-76",alloy.face,3);line(g,"M-35 -74h12m47 8h-10",brass.edge,2);
  });
  design("oid_amortization","A declining discount wedge runs beside a rail of consecutive coupon positions.",g=>{
    rail(g,0,0,115);face(g,"M-44 -69l83 51-80-24z",clay.top,clay.edge,2);
    face(g,"M-44 -69l7-4 84 50-8 5z",brass.top,brass.edge,1.3);
    for(let i=0;i<5;i++){let x=-38+i*18;block(g,x,-9+i*4,12,20,32-i*6,steel);}
  });
  design("warrant_valuation","A warrant certificate shares a cost-allocation beam with two independent weights.",g=>{
    sheet(g,-19,-12,39,66,(p)=>{writing(p,6,13,23,3);ellipse(p,22,45,8,8,brass.top,brass.side);});
    line(g,"M-1 -21h49M22 -34v26",alloy.face,5);block(g,9,-19,12,15,16,copper);block(g,39,-18,14,13,23,steel);
  });
  design("ledger_post","An entry stylus meets a ruled double-page ledger at a single posting line.",g=>{
    ledger(g,-3,-4,87,46);
    face(g,"M42 -83l6 5-32 44-8 6 2-12z",copper.top,brass.edge,1.4);line(g,"M13 -39l3 4",ink,2);
  });
  design("dual_ledger","Two independent upright books share a base, each with its own ruled spine and balance rail.",g=>{
    for(const [x,y,m] of [[15,-24,steel],[-19,-4,brass]]){
      const p=panel(g,x,y,42,57,m);rect(p,4,2,6,53,ink);rect(p,14,11,20,9,paper.face);writing(p,14,29,18,3,m.edge);
    }
    line(g,"M-41 -8l10 5m38-11 12 5",copper.top,3);
  });
  design("reconciliation","Paired ruled records line up against a shared comparator bridge.",g=>{
    sheet(g,-27,-10,29,55,s=>writing(s,5,15,19,4));
    sheet(g,24,-10,29,55,s=>writing(s,5,15,19,4),steel);
    line(g,"M-23 -29h14l6-8h12l5 8h12",ink,8);line(g,"M-23 -29h14l6-8h12l5 8h12",copper.top,4);
    ellipse(g,3,-37,4,4,alloy.edge,ink);
  });
  design("balance_rollforward","Opening and closing balance towers are joined by a graduated movement bridge.",g=>{
    stack(g,-37,-8,14,3,steel);stack(g,34,1,17,6,brass);
    face(g,"M-34 -33l61 -14 5 7-61 15z",paper.face,alloy.edge);
    for(let i=0;i<4;i++)line(g,`M${-22+i*11} ${-34-i*2.5}l2 4`,ink,1.4);
    line(g,"M1 -31v17",copper.top,3);
  });
  design("period_close","A closing calendar is held between a hinged period cover and a transverse clasp.",g=>{
    calendar(g,-1,-13,66,53);block(g,0,0,77,31,10,alloy);
    const band=panel(g,-1,-27,68,11,steel);rect(band,26,-1,14,13,copper.top,2,copper.edge);
  });
  design("variance_analysis","Two traces diverge across a gridded comparison screen with a bracket spanning their gap.",g=>{
    const p=panel(g,0,-8,80,60,steel);grid(p,6,8,66,42,4,3,steel.top);
    line(p,"M8 41l13-15 11 8 14-17 19 8",paper.edge,3);line(p,"M8 41l13-14 12 15 14-3 18 4",copper.edge,3);
    line(p,"M66 26h5v17h-5",brass.edge,2);
  });
  design("revenue_recognition","An earned revenue strip is apportioned across consecutive period compartments.",g=>{
    const p=panel(g,-9,-15,73,45,paper);grid(p,6,10,61,26,4,1);
    rect(p,7,17,14,10,copper.top);rect(p,22,17,14,10,brass.top);rect(p,37,17,14,10,steel.top);
    block(g,12,-2,68,22,6,steel);drum(g,31,2,11,6,brass);
  });
  design("fee_calculation","A fee-basis strip feeds a raked calculator with a raised key matrix and result window.",g=>{
    sheet(g,-19,-26,31,51,(s)=>{grid(s,4,14,22,23,2,3);});
    const p=panel(g,12,0,46,59,steel);rect(p,5,6,35,12,ink,1,steel.edge);
    for(let i=0;i<9;i++)rect(p,6+(i%3)*12,25+Math.floor(i/3)*10,8,6,i===8?copper.top:paper.face,1.3);
  });
  design("expense_allocation","A receipt opens onto a three-sector allocation wheel with separately machined segments.",g=>{
    sheet(g,-22,-13,35,62,(s)=>writing(s,5,15,23,5));
    const d=wheel(g,21,-30,26,steel);
    face(d,"M0 0v-20a20 20 0 0 1 18 28z",copper.top,ink);
    face(d,"M0 0l18 8a20 20 0 0 1-34 5z",brass.top,ink);
    face(d,"M0 0l-16 13a20 20 0 0 1 16-33z",paper.face,ink);
  });
  design("receivable","An open-item statement rests in an aging rack beside a time dial.",g=>{
    sheet(g,-12,-10,48,61,s=>{grid(s,6,15,34,25,2,3);writing(s,7,49,22,1);});
    block(g,-11,1,53,24,13,steel);const d=wheel(g,27,-21,16,brass);line(d,"M0 -9v9l6 4",brass.edge,2.3);
  });
  design("invoice","A folded invoice has itemized rows, a distinct total band and a detachable payment stub.",g=>{
    sheet(g,-2,0,57,79,(p,w,h)=>{rect(p,7,8,14,7,steel.face);grid(p,7,23,w-14,24,2,3);line(p,"M29 52h20",ink,3);
      for(let i=6;i<51;i+=8)line(p,"M"+i+" 59h4",alloy.face,1.2);rect(p,8,66,31,5,brass.face);});
  });
  design("financial_statement","A matched set of statement leaves carries section rules and double-ruled totals.",g=>{
    sheet(g,12,-12,49,68,null,steel);sheet(g,3,-5,51,68,null,paper);
    sheet(g,-9,2,51,68,s=>{rect(s,6,10,20,5,steel.face);writing(s,6,25,34,4);line(s,"M23 53h21m-21 4h21",ink,1.5);});
  });
  design("expense_scrub","An optical screening bar passes across the individual lines of an expense receipt.",g=>{
    sheet(g,-4,-1,55,74,(p)=>{writing(p,7,14,35,6);});
    line(g,"M-40 -1v-38l69 -10v37",alloy.face,5);line(g,"M-37 -37l65-10",copper.top,4);
    ellipse(g,2,-43,8,5,steel.top,ink,1.2);
  });
  design("accrual","A provisional entry on a ledger sits beneath an adjustable estimation gauge.",g=>{
    ledger(g,-5,0,73,30);pointerDial(g,10,-56,21,steel);
    line(g,"M-25 -20l9-2m3-1 7-1m4-1 8-1",copper.top,2);
  });
  design("expense_transfer","Two account folios are coupled by an intercompany transfer bridge.",g=>{
    const a=panel(g,-28,-15,31,44,steel);writing(a,5,12,20,4,paper.edge);
    const b=panel(g,27,-5,31,44,brass);writing(b,5,12,20,4,paper.edge);
    arrow(g,"M-34 -13l19 6 28-11","M9 -23l13 1-8 10z");block(g,23,1,17,13,6,clay);
  });
  design("cash_application","A cash token docks against a slotted receivable record with matching contact points.",g=>{
    const p=panel(g,11,-7,47,63,paper);grid(p,7,16,31,25,2,3);rect(p,7,46,20,6,steel.face);
    stack(g,-31,-2,16,3);connector(g,-29,-22,10,-32);
    for(const x of [7,13,19])ellipse(g,x,-33,1.5,1.5,copper.top);
  });
  design("wire_release","A payment instruction passes between two release contacts and an outbound wire channel.",g=>{
    sheet(g,-28,-10,29,47,p=>writing(p,4,13,18,4));
    for(const x of [-4,16]){block(g,x,-5,11,22,51,steel);drum(g,x,-56,7,3,brass);}
    arrow(g,"M-31 -32l27 10 37-9","M27 -37l16 4-11 11z");
  });
  design("callback","A raised telephone handset and paired contact terminals mark an independent call.",g=>{
    block(g,0,-3,61,40,9,steel);
    const p=group(g,"translate(-2 -51) rotate(-18)");
    face(p,"M-40 -5q0-18 16-20l6 13-5 6q16 10 39 4l-2-9 11-9q16 5 16 17l-7 9q-38 14-71-2z",alloy.face,alloy.edge,2.2);
    line(p,"M-31 -13l6-5m51 9 7-6",copper.edge,3);
    line(g,"M27 -43c20 4 5 14 14 19s-9 9-14 8",ink,2.5);for(const x of [-13,5])drum(g,x,-10,4,4,brass);
  });
  design("settlement","A security-lot cradle and a cash cradle meet at interlocking settlement jaws.",g=>{
    tray(g,-25,-5,43,36,steel);diamond(g,-26,-36,17,steel);
    tray(g,29,3,36,33,brass);stack(g,29,-9,12,3);
    line(g,"M-14 -6h10v-7H7v8h10",ink,8);line(g,"M-14 -6h10v-7H7v8h10",copper.top,4);
  });
  design("liquidity","A cutaway cash reservoir displays its fluid level against an external sight glass.",g=>{
    const tank=panel(g,-5,-2,59,67,steel);rect(tank,5,6,49,54,ink,2,steel.edge);
    face(tank,"M7 35q12-7 23-1t22 0v23H7z",steel.top,steel.edge,1);
    for(const x of [11,26,41])line(tank,"M"+x+" 43q5-2 10 0",paper.edge,1.3);
    rect(g,32,-60,8,57,alloy.side,3,alloy.edge);rect(g,34,-28,4,24,copper.top,2);
    for(const y of [-51,-41,-31,-21])line(g,"M41 "+y+"h5",ink,1);
  });
  design("facility_draw","A facility reservoir releases a draw through a valve into a lower cash cup.",g=>{
    drum(g,-22,-15,22,43,steel);line(g,"M-12 -26h27v16h16",alloy.face,7);
    line(g,"M-12 -26h27v16h16",copper.top,2);wheel(g,10,-36,8,brass);
    drum(g,36,4,15,11,brass);line(g,"M27 -11l6 8 5-9",ink,2);
  });
  design("facility_repayment","A stepped return conveyor carries a payment back to the facility reservoir.",g=>{
    drum(g,27,-12,22,46,steel);
    for(let i=0;i<4;i++)block(g,-35+13*i,4-i*9,19,20,5,i===3?copper:alloy);
    stack(g,-34,-5,12,2);arrow(g,"M-28 -20l33-30","M-2 -53l16-5-5 16z");
  });
  design("borrowing_base","A sliding eligibility bar measures collateral columns against a signed space on a certificate.",g=>{
    sheet(g,16,-10,37,65,p=>{grid(p,5,17,26,21,2,3);line(p,"M7 47q6-5 9 0t11-1",ink,1.5);});
    for(const [x,h] of [[-37,25],[-22,39],[-7,30]])block(g,x,0,11,15,h,brass);
    line(g,"M-45 -46l48 5",steel.face,5);block(g,-16,-39,7,15,8,copper);
  });
  design("bank_setup","A bank façade sits behind a keyed account index tile.",g=>{
    building(g,-7,-8);const p=panel(g,25,1,31,27,paper);
    ellipse(p,10,12,4,4,"none",copper.face,2.7);line(p,"M14 12h10m-4 0v4",copper.face,2.7);
  });
  design("payment_entry","An instruction form feeds an input console with a bank field and separate amount field.",g=>{
    sheet(g,-10,-15,47,65,p=>{rect(p,6,15,30,7,"none",1,ink);rect(p,6,29,23,7,"none",1,ink);writing(p,7,45,26,2);});
    const k=group(g,"translate(4 -5) matrix(.95 .22 -.48 .7 0 0)");rect(k,-23,-10,48,23,steel.face,2,steel.edge);
    for(let i=0;i<8;i++)rect(k,-17+i%4*9,-5+Math.floor(i/4)*8,6,4,i===7?copper.top:paper.face,.7);
  });
  design("population_lock","A mechanical clamp surrounds an indexed population of record tiles.",g=>{
    const p=panel(g,-2,-4,63,57,steel);grid(p,6,7,50,42,4,3,steel.edge);
    line(g,"M-30 -57v-19q0-14 14-15h24q12 0 12 12v13",alloy.side,8);
    line(g,"M-30 -57v-19q0-14 14-15h24q12 0 12 12v13",alloy.top,4);
    rect(p,22,20,24,16,copper.face,2,copper.edge);ellipse(p,34,26,2.5,2.5,ink);
  });
  design("independent_review","A separate inspection loupe stands over an unmarked source record.",g=>{
    sheet(g,-14,-4,47,57,p=>{writing(p,6,17,28,5);});
    const d=group(g,"translate(13 -53) skewY(-8)");line(d,"M13 14l20 22",ink,9);line(d,"M13 14l20 22",brass.top,5);
    ellipse(d,0,0,20,20,steel.top,alloy.side,4);ellipse(d,0,0,16,16,"none",paper.edge,2);line(d,"M-9 -4q2-8 10-8",paper.edge,2);
  });
  design("approval","A raised authorization stamp hovers above a signing surface with an open signature line.",g=>{
    const leaf=group(g,"translate(1 -6) matrix(.97 .22 -.55 .58 0 0)");rect(leaf,-26,-24,53,43,paper.face,1,paper.edge);
    line(leaf,"M-17 9h31",ink,1.6);
    block(g,0,-25,49,36,9,steel);block(g,0,-34,33,24,6,alloy);
    face(g,"M-11 -38q8-11 2-22q-6-12 8-16q16-2 15 10q-9 13-2 29z",brass.face,brass.edge,2);
  });
  design("kyc","An optical reader frames an identity card and its document-matching lines.",g=>{
    const p=panel(g,-4,-10,60,49,paper);badge(p,15,21,10,steel);writing(p,31,14,19,3);writing(p,7,39,44,1);
    line(g,"M-41 -2v-67l76-11v65",alloy.face,6);line(g,"M-37 -46l67 -9",copper.top,3.2);
  });
  design("exception","A flagged record occupies a side bin off the main routing channel.",g=>{
    rail(g,-10,0,86);tray(g,25,-12,44,35,clay);
    sheet(g,21,-23,28,38,p=>writing(p,5,12,17,3));
    line(g,"M-23 -7v-64",alloy.face,4);face(g,"M-21 -73q11-5 23 1l-7 11q-8-4-16 1z",copper.top,copper.edge);
  });
  design("audit_evidence","A ring-bound evidence folio contains tabbed leaves and a chain-of-reference link.",g=>{
    const p=panel(g,-4,-4,52,71,steel);rect(p,5,3,6,64,ink);rect(p,15,14,29,23,paper.face);
    for(const [y,m] of [[23,brass],[35,copper],[47,alloy]])rect(p,50,y,7,8,m.top,1,m.edge);
    for(const [x,y] of [[34,-9],[44,-17]])ellipse(g,x,y,8,5,"none",brass.edge,3);
  });
  design("rule_lock","An engraved rules plate sits behind a movable retaining bar and keyed lock.",g=>{
    const p=panel(g,-4,-7,62,62,brass);writing(p,7,12,42,5,ink);rect(p,2,43,58,8,steel.side);
    rect(p,36,37,18,19,steel.face,2,steel.edge);ellipse(p,45,45,3,3,ink);line(p,"M45 46v5",ink,2);
  });
  design("access_control","A key approaches a slotted access gate with two permission chambers.",g=>{
    const p=panel(g,7,-8,45,68,steel);rect(p,5,5,35,58,ink,2);rect(p,8,9,14,47,steel.face);rect(p,24,9,12,47,alloy.face);
    ellipse(g,-31,-33,11,10,"none",brass.top,5);line(g,"M-20 -33h27m-6 0v7m-6-7v6",brass.top,5);
  });
  design("workbook_control","A worksheet cross-foot grid intersects a horizontal and a vertical total in one corner.",g=>{
    const p=panel(g,0,-3,67,61,paper);grid(p,6,8,54,44,4,4,ink);
    rect(p,46.5,9,12,42,steel.top);rect(p,7,41,52,10,brass.top);rect(p,47,42,11,8,copper.top);
    line(p,"M45 8v45M6 39h54",ink,2);
  });
  design("event_setup","A standing event flag pins a specific cell on a bound schedule.",g=>{
    calendar(g,-9,-5,61,53);line(g,"M13 -24v-57",brass.face,3.5);
    face(g,"M14 -81l26 2-7 9 7 5-26 -1z",copper.top,copper.edge,1.4);
  });
  design("document_pack","Staggered document leaves slide into a clasped, open-sided delivery wallet.",g=>{
    for(const [x,y,m] of [[10,-21,alloy],[0,-15,steel],[-9,-8,paper]])sheet(g,x,y,43,50,null,m);
    const p=panel(g,-4,2,67,30,brass);face(p,"M2 3h60l-10 13H16Z",brass.top,brass.edge);rect(p,29,10,10,9,copper.face,1,copper.edge);
  });
  design("workbook","A layered spreadsheet board has a cell matrix, inset formula bar and distinct sheet tabs.",g=>{
    panel(g,7,-14,70,46,alloy);const p=panel(g,-3,-3,70,51,paper);
    rect(p,5,5,59,6,steel.top);grid(p,5,15,59,27,4,3);rect(p,6,45,12,5,copper.top);
    rect(p,21,45,12,5,brass.top);rect(p,36,45,12,5,steel.top);
  });
  design("notice","A folded communication rises from an open envelope with an address window.",g=>{
    sheet(g,-1,-21,45,45,p=>{rect(p,5,9,13,6,brass.face);writing(p,6,22,27,3);});
    envelope(g,1,0,71,39,steel);rect(g,-21,-18,16,6,paper.face,1);
  });
  design("portal_release","A document crosses the opening of a portal screen with an outbound delivery track.",g=>{
    const p=panel(g,-4,-15,73,50,steel);rect(p,5,6,62,36,ink,2);rect(p,9,10,55,6,steel.face);
    block(g,-4,-4,31,27,8,alloy);sheet(g,13,-9,20,26,s=>writing(s,3,9,13,2));
    arrow(g,"M15 -20l20 7 11 -6","M41 -24l13 1-7 10z");
  });
  design("handoff","A sealed work item spans two receiving trays joined by a transfer arm.",g=>{
    tray(g,-29,-10,42,32,steel);tray(g,28,0,42,32,alloy);
    line(g,"M-37 -18v-30l55 -19 19 9v14",alloy.face,6);line(g,"M4 -59v16",brass.face,4);
    block(g,4,-22,24,21,18,copper);line(g,"M-3 -42l12 6v9",paper.edge,1.7);
  });
  design("data_migration","Two different storage arrays connect through a bridge of remapped record blocks.",g=>{
    for(const [x,y,r,m] of [[-35,-12,18,steel],[36,1,15,brass]]){for(let i=0;i<3;i++)drum(g,x,y-i*13,r,10,m);}
    line(g,"M-24 -43l17 8 28-10",alloy.face,5);
    block(g,-6,-37,10,10,8,paper);block(g,9,-40,10,10,8,copper);
  });
  design("calendar","Twin binding rings and a monthly cell grid carry an adjustable deadline marker.",g=>{
    const p=calendar(g,0,-3,69,63);rect(p,25,18,18,17,"none",2,copper.face,3);line(p,"M46 47h13",brass.face,3);
  });
  design("audit_request","An auditor-query ticket stands in a ring-indexed rack with an open response pocket.",g=>{
    const p=panel(g,-21,-12,39,52,steel);writing(p,5,12,23,4,steel.edge);
    sheet(g,14,-18,34,49,s=>{line(s,"M9 18q1-10 11-8q10 3 3 10l-5 4v4",ink,2.5);ellipse(s,18,34,1.6,1.6,copper.face);});
    block(g,15,0,43,19,18,brass);
  });
  design("data_mapping","Unequal column banks are linked by separate mapping jumpers between their terminals.",g=>{
    const left=panel(g,-30,-8,23,61,steel), right=panel(g,30,-7,23,61,brass);
    for(let i=0;i<3;i++) {rect(left,5,9+i*16,14,8,paper.face);rect(right,5,9+i*16,14,8,paper.face);}
    connector(g,-19,-55,20,-22,copper.top);connector(g,-19,-22,19,-40,steel.edge);
    connector(g,-19,-40,19,-55,brass.edge);
  });
  design("data_import","Incoming record cards drop through a broad funnel into a storage array.",g=>{
    drum(g,1,1,28,20,steel);drum(g,1,-19,28,7,steel);
    face(g,"M-28 -63l56-5-19 33-13 4z",brass.face,brass.edge,2);
    ellipse(g,0,-65,28,6,ink,brass.edge,1.5);
    for(const [x,y] of [[-13,-75],[9,-79]])block(g,x,y,14,11,4,copper);
  });
  design("data_export","An extractor lifts record cards from the storage lid into an outgoing fan.",g=>{
    drum(g,-15,0,26,16,steel);drum(g,-15,-17,26,10,steel);drum(g,-15,-29,26,8,steel);
    arrow(g,"M-14 -42v-18l24 -12","M4 -76l16-2-8 13z");
    sheet(g,29,-36,20,27,null,brass);sheet(g,36,-27,21,27,s=>writing(s,4,11,13,2));
  });
  design("reminder","A mechanical bell sits on a dated follow-up ticket with a side striker.",g=>{
    const p=group(g,"translate(-5 -4) skewY(-12)");rect(p,-26,-7,53,14,paper.face,2,paper.edge);
    face(g,"M-30 -19q13-6 12-27q2-23 22-22q17 1 19 23q-1 20 13 26z",brass.face,brass.edge,2);
    drum(g,3,-15,31,5,brass);ellipse(g,3,-71,5,5,copper.top,brass.edge);line(g,"M38 -44l7-12",alloy.face,3);ellipse(g,37,-42,4,4,alloy.top);
  });
  design("foreign_exchange","Two differently minted currency tokens flank an exchange spindle with opposing arrows.",g=>{
    const a=wheel(g,-27,-53,21,brass), b=wheel(g,29,-30,20,steel);
    line(a,"M-5 -7q15 -6 11 2q-1 3 -8 4q-10 4 4 8m-2-20v25",brass.edge,2.3);
    line(b,"M7 -8q-18-5-15 10q2 10 14 6M-11 -2h13m-13 5h11",steel.edge,2.1);
    arrow(g,"M-30 -21q17 13 32 7","M1 -20l12 1-7 9z");line(g,"M13 -60L2 -65l5-3",copper.top,2.7);
  });
  design("bank_mandate","A mandate sheet with signature lanes and a removable signatory seal stands against the bank façade.",g=>{
    building(g,-16,-18);sheet(g,17,2,41,52,p=>{writing(p,5,12,26,2);line(p,"M7 33q6-8 10 -1l6 -4m-16 10h27",ink,1.5);});
    drum(g,34,1,9,5,brass);
  });
  design("ownership_trace","Nested holder medallions form a tiered beneficial-ownership tree.",g=>{
    line(g,"M0 -64v16h-29v14m29-14h31v14M-29 -27v10h-15v9",alloy.face,4);
    badge(g,0,-74,15,brass);badge(g,-29,-35,12,steel);badge(g,31,-35,12,steel);badge(g,-43,-7,9,clay);
  });
  design("sanctions_screen","An identity token moves past an optical slit aligned with a watchlist index.",g=>{
    sheet(g,15,-10,41,62,p=>{for(let i=0;i<4;i++){rect(p,4,15+i*9,4,5,steel.face);line(p,"M11 "+(17+i*9)+"h20",ink,1.5);}});
    badge(g,-28,-34,17,brass);line(g,"M-6 -67v60",copper.top,4);
    line(g,"M-12 -60l9-8 9 4m-17 56 9 5 9-5",alloy.face,2.2);
  });
  design("risk_rating","A tiered risk scale and a movable observation pointer sit above the assessment record.",g=>{
    const p=panel(g,-4,-8,64,55,paper);
    for(let i=0;i<4;i++)rect(p,9+i*12,39-i*7,9,7+i*7,[alloy,steel,brass,clay][i].face,1);
    line(p,"M6 10h50",ink,1.8);face(p,"M26 5h9l-4 10z",copper.top,ink,.8);
    line(g,"M-26 -4l19 5 35-8",brass.face,2.4);
  });
  design("covenant_check","Independent observed and limit markers share a calibrated covenant ruler.",g=>{
    const p=panel(g,-1,-8,70,49,alloy);rect(p,6,12,58,22,ink,2);
    for(let i=0;i<=9;i++)line(p,"M"+(9+i*5.6)+" 30v"+(i%3===0?-7:-4),paper.edge,1.3);
    face(p,"M25 12h9l-4 10z",steel.top,paper.edge);
    line(p,"M46 7v30",copper.top,3.5);line(p,"M39 7h14",copper.edge,2);
  });
  design("duplicate_check","Two like-numbered record patterns overlap inside a registration frame.",g=>{
    for(const [x,y,m] of [[-13,-16,steel],[9,-3,paper]])sheet(g,x,y,42,54,(p)=>{for(const [x,w] of [[6,2],[10,4],[16,1],[20,3],[25,2]])rect(p,x,14,w,12,ink);writing(p,6,33,26,2);},m);
    line(g,"M-34 -46v-10h12m40 40h12v-9",copper.top,3);
  });
  design("blackline","Two revision leaves expose line-level underlining and strike-through in the comparison margin.",g=>{
    sheet(g,-13,-14,44,58,p=>writing(p,5,15,29,5),steel);
    sheet(g,9,0,46,63,p=>{writing(p,6,15,32,6);line(p,"M5 26h25m-17 17h25",copper.face,2.4);line(p,"M2 22v25",clay.face,2);});
  });
  design("clean_copy","A marked internal leaf and a separate clean issue leaf emerge on opposite sides of a copy roller.",g=>{
    sheet(g,-21,-17,36,54,p=>{writing(p,5,14,24,4);line(p,"M4 20h21M5 34h16",clay.face,2);});
    drum(g,0,-9,11,30,alloy);sheet(g,24,-2,34,43,p=>writing(p,5,13,22,4));
    line(g,"M-7 -10l12 4",copper.top,2.5);
  });
  design("asset_valuation","A faceted holding and a unit stack feed a quoted-price display.",g=>{
    const p=panel(g,10,-21,47,46,steel);line(p,"M6 32l8-8 6 4 9-12 9 2",paper.edge,2.4);
    diamond(g,-23,-32,19,steel);stack(g,23,2,13,3,brass);
  });
  design("security_conversion","A round security token and a faceted successor occupy opposite sides of a conversion die.",g=>{
    wheel(g,-32,-42,17,brass);block(g,0,-8,15,29,40,steel);
    line(g,"M-17 -39l15 5 15-6",copper.top,3.6);diamond(g,34,-38,17,steel);
  });
  design("billing_exclusion","A mask selects billable rows while excluded entries remain visible on the source sheet.",g=>{
    const p=panel(g,0,-4,64,66,paper);grid(p,7,11,50,44,2,5);
    for(let i=0;i<4;i++)line(p,"M11 "+(17+i*9)+"h16",ink,1.4);
    rect(p,6,29,52,9,"none",0,clay.face,3);
    face(p,"M52 29l11 3v3l-11 3z",clay.top,clay.face,1);
  });
  design("remittance_support","A withholding schedule and reserve marker travel together in a routed support folio.",g=>{
    sheet(g,-14,-15,44,62,p=>{grid(p,6,12,30,32,2,4);line(p,"M15 50h21",ink,2);});
    const p=panel(g,8,0,55,28,alloy);rect(p,7,5,23,12,paper.face);
    drum(g,27,-13,10,6,brass);line(g,"M31 -38h13l-4-5m4 5-4 5",copper.top,2.8);
  });
  design("carry_recalculation","A cumulative carry stack is measured against previously booked layers by a sliding difference gauge.",g=>{
    stack(g,-21,-4,20,7,brass);stack(g,23,3,17,4,steel);
    line(g,"M-4 -55h14v31h8",alloy.side,6);line(g,"M-4 -56h14v31h8",copper.top,3);
    block(g,12,-26,11,8,5,copper);
  });
  design("cash_classification","Cash lines enter an indexing gate and emerge on separate source and use tracks.",g=>{
    const p=panel(g,-27,-12,30,50,paper);writing(p,5,11,20,5);
    line(g,"M-12 -38h16l26-19m-26 19 28 15",alloy.side,7);
    line(g,"M-12 -38H4l26-19",steel.top,3);line(g,"M4 -38l28 15",copper.top,3);
    block(g,3,-19,10,19,32,brass);drum(g,34,-55,9,5,steel);drum(g,36,-20,9,5,brass);
  });
  design("scope_setup","An adjustable perimeter frame encloses the selected working area on a source sheet.",g=>{
    const p=panel(g,0,-6,70,53,paper);grid(p,6,8,57,36,4,3,alloy.top);
    line(p,"M12 19v-7h11m25 0h7v9m0 11v7H44m-25 0h-7v-7",copper.face,3);rect(p,25,22,13,9,steel.face);
  });
  design("record_update","A replaceable entry strip slides into a ruled master register.",g=>{
    const p=panel(g,-7,-6,55,64,steel);writing(p,7,12,39,6,paper.edge);
    rect(p,6,35,43,9,ink,1,steel.edge);const strip=panel(g,22,-28,41,10,paper);line(strip,"M4 5h24",copper.face,2);
  });
  design("route_work","A movable switch blade connects a single intake track to two destination docks.",g=>{
    line(g,"M-45 -13L-4 -31 36-17m-40-14 30-28",alloy.face,7);
    line(g,"M-45 -13L-4 -31 36-17",steel.top,2);line(g,"M-4 -31l30-28",brass.top,2);
    drum(g,-4,-30,7,4,copper);line(g,"M-4 -33l20-20",copper.top,4.6);
    block(g,35,-12,13,14,7,steel);block(g,29,-54,13,14,7,brass);
  });
  design("status_monitor","A monitor lens reads position marks from a multi-lane status board.",g=>{
    const p=panel(g,-2,-12,69,46,steel);
    for(const [y,x] of [[11,22],[22,44],[33,30]]){line(p,`M6 ${y}h54`,alloy.edge,2);rect(p,x,y-3,9,6,brass.top,1);}
    line(g,"M-31 -4v-16",alloy.side,4);ellipse(g,-31,-24,8,8,paper.face,copper.face,2.7);ellipse(g,-31,-24,3,3,steel.face);
  });
  design("close_record","A single indexed folder seats behind the latching face of an archive drawer.",g=>{
    const f=panel(g,-4,-16,46,39,paper);rect(f,5,-5,15,7,brass.top,1);writing(f,6,12,29,2);
    block(g,0,1,70,31,24,alloy);const p=panel(g,5,-3,52,19,steel);rect(p,18,4,16,7,ink,1,steel.edge);rect(p,21,4,10,2,copper.top,0);
  });
  design("source_validation","A source sheet and an input strip meet at a comparison window with paired registration pins.",g=>{
    sheet(g,-14,-10,42,61,p=>{writing(p,5,13,26,6);});
    const p=panel(g,23,-4,30,40,steel);writing(p,5,9,19,4,paper.edge);
    rect(g,-16,-39,44,11,"none",2,copper.face,2.8);ellipse(g,-17,-34,3,3,brass.edge);ellipse(g,28,-34,3,3,brass.edge);
  });
  design("rule_confirmation","A reading cursor brackets one criterion on a standing terms folio.",g=>{
    ledger(g,-5,-9,69,48);
    line(g,"M1 -47h23v13H1",copper.face,2.7);
    line(g,"M38 -15l-13 -19",alloy.side,5);ellipse(g,25,-35,4,4,brass.top,brass.side);
  });
  const allIds=Object.freeze([...catalog.keys()]);
  scope.CollectorComponentArt=Object.freeze({
    ids:()=>allIds,
    has:id=>catalog.has(id),
    detail:id=>catalog.get(id)?.detail || "",
    draw(parent,id) {
      const entry=catalog.get(id);
      if(!entry)return false;
      entry.draw(group(parent,"translate(0 -28)"));
      return true;
    }
  });
})(typeof window === "object" ? window : globalThis);
