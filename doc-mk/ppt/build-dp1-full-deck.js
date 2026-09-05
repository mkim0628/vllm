const pptxgen=require("pptxgenjs");
const INK="1F2933",BODY="3E4C59",MUTED="7B8794",RULE="DCE1E7",BG="FFFFFF",DARK="16202B";
const C1="0B6E6E",C2="B0503F",C1S="E8F2F1",C2S="F8EBE7",PANEL="F5F7F8",WARN="B7791F";
const F="Arial";
const pres=new pptxgen(); pres.layout="LAYOUT_WIDE";
pres.title="DP1 — Memory Placement Decision Basis";
const L=0.5,R=12.8,W=13.3,H=7.5;
const AX=0.5,BX=6.85,CW=5.95;
let PAGE=0; const TOTAL=21;

function head(s,kicker,title,sub){
  s.addText(kicker,{x:L,y:0.32,w:9.5,h:0.24,isTextBox:true,margin:0,
    fontFace:F,fontSize:10.5,bold:true,color:MUTED,charSpacing:1.5});
  s.addText(title,{x:L,y:0.58,w:12.3,h:0.44,isTextBox:true,margin:0,
    fontFace:F,fontSize:23,bold:true,color:INK});
  if(sub) s.addText(sub,{x:L,y:1.06,w:12.3,h:0.28,isTextBox:true,margin:0,
    fontFace:F,fontSize:11,color:MUTED});
}
function page(s){ PAGE++; const n=PAGE;
  s.addText(`DP1 · ${n} / ${TOTAL}`,{x:R-2.2,y:7.06,w:2.2,h:0.24,isTextBox:true,margin:0,
    fontFace:F,fontSize:8.5,color:MUTED,align:"right",valign:"middle"});
}
function slide(kicker,title,sub){const s=pres.addSlide();s.background={color:BG};head(s,kicker,title,sub);page(s);return s;}
function card(s,x,y,w,h,fill,line){s.addShape(pres.ShapeType.roundRect,{x,y,w,h,rectRadius:0.05,
  fill:{color:fill||"FFFFFF"},line:{color:line||RULE,width:0.75}});}
function txt(s,x,y,w,h,t,o){o=o||{};s.addText(t,{x,y,w,h,isTextBox:true,margin:o.margin!==undefined?o.margin:0,
  fontFace:F,fontSize:o.fs||10,bold:!!o.b,italic:!!o.i,color:o.c||BODY,align:o.al||"left",
  valign:o.va||"top",lineSpacingMultiple:o.ls||1.15,charSpacing:o.cs});}
function bullets(s,x,y,w,h,items,fs,color){
  const runs=items.map((t,i)=>({text:t,options:{bullet:{code:"2022"},breakLine:i!==items.length-1}}));
  s.addText(runs,{x,y,w,h,isTextBox:true,margin:0,fontFace:F,fontSize:fs||10,color:color||BODY,
    paraSpaceAfter:6,lineSpacingMultiple:1.12,valign:"top"});
}
function box(s,x,y,w,h,ac,sf,t,fs){
  s.addShape(pres.ShapeType.roundRect,{x,y,w,h,rectRadius:0.05,fill:{color:sf},line:{color:ac,width:1}});
  txt(s,x,y,w,h,t,{fs:fs||9,b:true,c:INK,al:"center",va:"middle",ls:1.05,margin:0.03});
}
function arrow(s,x1,y1,x2,y2,color,dashed){
  const o={x:Math.min(x1,x2),y:Math.min(y1,y2),w:Math.abs(x2-x1),h:Math.abs(y2-y1),
    line:{color:color||MUTED,width:1,endArrowType:"triangle"}};
  if(dashed)o.line.dashType="dash"; o.flipH=x2<x1; o.flipV=y2<y1;
  s.addShape(pres.ShapeType.line,o);
}
function chip(s,x,y,ac,label,fs){
  s.addShape(pres.ShapeType.roundRect,{x,y:y+0.03,w:0.18,h:0.18,rectRadius:0.09,fill:{color:ac},line:{color:ac}});
  txt(s,x+0.27,y,CW,0.26,label,{fs:fs||12,b:true,c:ac});
}
function table(s,rows,opt){
  s.addTable(rows,Object.assign({x:L,w:R-L,border:{type:"solid",pt:0.75,color:RULE},
    fontFace:F,valign:"middle",margin:[5,8,5,8]},opt));
}
function hdr(t,al){return {text:t,options:{bold:true,color:"FFFFFF",fill:{color:INK},fontSize:10.5,align:al||"left"}};}

/* ---------- 1. 표지 ---------- */
{
  const s=pres.addSlide(); s.background={color:DARK};
  txt(s,L,1.85,11,0.3,"DESIGN POINT 1",{fs:12,b:true,c:"8AA4A4",cs:2.5});
  txt(s,L,2.28,11.5,1.5,"Memory Placement\nDecision Basis",{fs:40,b:true,c:"FFFFFF",ls:1.1});
  txt(s,L,3.92,11.5,0.32,"메모리 배치 결정 기준",{fs:16,c:"9BAAB4"});
  s.addShape(pres.ShapeType.line,{x:L,y:4.50,w:2.2,h:0,line:{color:"3E5A5A",width:2}});
  txt(s,L,4.78,11.8,0.24,"설계 질문",{fs:10,b:true,c:"8AA4A4",cs:1.5});
  txt(s,L,5.06,11.8,0.7,"스케줄러가 \"얼마나\"만 요구하고 런타임이 \"어디에\"를 정하는 구조에서,\n그 배치 결정의 단일 기준을 무엇에 매달 것인가?",{fs:15,b:true,c:"FFFFFF",ls:1.25});
  txt(s,L,6.20,11.8,0.3,"대상: vLLM v1 Scheduler ↔ BlockPool 할당 경계   |   6단 이기종 메모리 (HBM / DRAM / CXL / Custom HBM / SSD / HBF)",
    {fs:10,c:"7A8B95"});
  s.addNotes("DP1 전체 흐름: 배경 → 문제 → 쟁점 → 두 후보 → 트레이드오프 → 문제 해결 검증 → 최종 선택 → 잔여 인계.");
}

/* ---------- 2. 한 장 요약 ---------- */
{
  const s=slide("DP1 · EXECUTIVE SUMMARY","한 장 요약");
  const rows=[
    ["문제","할당 경계가 \"얼마나\"만 표현하고 \"어디에\"를 표현하지 않는다. 6-tier로 확장하면 tier 선택이 호출 지점 조건문으로 흩어진다"],
    ["설계 쟁점","배치 정책의 인덱스 축을 어디에 둘 것인가 — 자원(tier)인가, 객체 특성인가"],
    ["후보 1","Tier-Indexed — 요청은 익명, 자원 상태가 결정을 지배. 불변식 = 자원 제약 우선"],
    ["후보 2","Object-Indexed — 객체 등급이 목표 tier를 지시, tier는 조정 대상. 불변식 = 객체 계약 우선"],
    ["트레이드오프","9 : 9 동점, 지배 없음. 각 후보가 ★★★ 2개"],
    ["문제 해결 검증","두 후보 모두 핵심 문제를 해결하고 제약을 지킨다. 다만 서로 다른 잔여를 남긴다 — C1은 QA1, C2는 QA3"],
    ["최종 선택","Candidate 1 (Tier-Indexed) + 컨텍스트 길이 보강. C2의 이득이 아직 알 수 없는 값 두 가지 — 수명 예측 정확도와 유보량 — 에 걸려 있기 때문"],
    ["잔여 인계","R1 재분류 → DP3(신규)   ·   R2 구분 능력 → DP4(신규)   ·   R3 재현성 → 관측성 작업"],
  ];
  let y=1.36;
  rows.forEach((r,i)=>{
    const h=(i===0||i===6)?0.68:0.58;
    card(s,L,y,R-L,h,i===6?C1S:"FFFFFF",i===6?C1:RULE);
    txt(s,L+0.16,y,2.05,h,r[0],{fs:10.5,b:true,c:i===6?C1:MUTED,va:"middle"});
    txt(s,L+2.30,y,R-L-2.5,h,r[1],{fs:10.5,b:i===6,c:INK,va:"middle",ls:1.15});
    y+=h+0.08;
  });
  s.addNotes("이 장만 봐도 DP1의 결론까지 전달되도록 구성. 이후 장은 각 줄의 근거.");
}

/* ---------- 3. 응용: 메모리 월 ---------- */
{
  const s=slide("DP1 · 1.1 응용","AI 서빙의 병목은 연산이 아니라 메모리다",
    "그 사실을 가장 단적으로 보여주는 것이 KV 캐시다");
  card(s,L,1.46,5.95,2.05,PANEL,RULE);
  txt(s,L+0.20,1.58,5.55,0.24,"70B급 모델 (GQA · 80 layer · KV head 8 · head_dim 128 · fp16)",{fs:9.5,b:true,c:MUTED});
  txt(s,L+0.20,1.92,5.55,1.00,
    "80 layer × 8 head × 128 dim × 2 (K,V) × 2 byte\n\n        =  327,680 byte  ≈  320 KB / 토큰",
    {fs:12,b:true,c:INK,ls:1.35});
  txt(s,L+0.20,3.02,5.55,0.36,"여기에 컨텍스트 길이를 곱하면 규모가 드러난다",{fs:10,i:true,c:MUTED});

  const rows=[[hdr("컨텍스트"),hdr("요청 1건의 KV","center"),hdr("")]];
  [["4 K","1.25 GB",""],["32 K","10 GB",""],
   ["128 K","40 GB","H100 80GB의 절반을 요청 하나가 쓴다"]].forEach((d,i)=>rows.push([
    {text:d[0],options:{bold:true,color:INK,fontSize:11}},
    {text:d[1],options:{bold:true,color:i===2?WARN:C1,fontSize:i===2?15:12,align:"center"}},
    {text:d[2],options:{color:i===2?WARN:BODY,bold:i===2,fontSize:9.5}},
  ]));
  s.addTable(rows,{x:6.85,y:1.46,w:5.95,colW:[1.30,1.60,3.05],
    rowH:[0.34,0.55,0.55,0.61],border:{type:"solid",pt:0.75,color:RULE},
    fontFace:F,valign:"middle",margin:[4,8,4,8]});

  card(s,L,3.80,R-L,1.34,C1S,C1);
  txt(s,L+0.24,3.94,R-L-0.48,0.30,"가중치는 고정, KV는 곱으로 늘어난다",{fs:14,b:true,c:C1});
  txt(s,L+0.24,4.30,R-L-0.48,0.72,
    "모델 가중치 140 GB는 상수다. KV는 컨텍스트 길이 × 동시 요청 수로 늘어난다.\n"+
    "128K 요청 4건이면 KV만 160 GB — 가중치를 넘어선다. 컨텍스트가 길어지고 동시성이 높아질수록 KV 캐시가 시스템의 지배적 메모리 소비자가 된다.",
    {fs:11,c:INK,ls:1.3});
  txt(s,L,5.36,R-L,0.30,"→ 이 벽을 한 종류의 메모리로는 넘을 수 없다",{fs:12,b:true,c:INK});
  s.addNotes("배경은 응용에서 시작한다. 여기서는 사실만 말하고 문제를 꺼내지 않는다.");
}

/* ---------- 4. 대응: 이기종 메모리 ---------- */
{
  const s=slide("DP1 · 1.2 대응","용량·대역폭·비용 조합이 다른 메모리가 등장하고, 시스템에 혼재한다",
    "성격이 자릿수 단위로 다른 메모리가 한 노드 안에 함께 놓인다");
  const data=[
    ["GPU HBM","3,200 GB/s","40 GB","0.5 us","1.0"],
    ["Custom HBM","1,600 GB/s","80 GB","0.8 us","1.2"],
    ["CPU DRAM","200 GB/s","320 GB","1.2 us","1.8"],
    ["CXL Memory","64 GB/s","640 GB","2.5 us","2.0"],
    ["HBF","16 GB/s","2.5 TB","20 us","4.0"],
    ["SSD","6 GB/s","10 TB","120 us","8.0"],
  ];
  const rows=[[hdr("tier"),hdr("대역폭","center"),hdr("용량(예시)","center"),
               hdr("지연","center"),hdr("이동비용","center")]];
  data.forEach((d,i)=>rows.push([
    {text:d[0],options:{bold:true,color:INK,fontSize:11}},
    {text:d[1],options:{bold:true,color:i<2?C1:BODY,fontSize:11,align:"center"}},
    {text:d[2],options:{color:BODY,fontSize:11,align:"center"}},
    {text:d[3],options:{color:BODY,fontSize:11,align:"center"}},
    {text:d[4],options:{color:MUTED,fontSize:11,align:"center"}},
  ]));
  table(s,rows,{y:1.62,colW:[3.10,2.40,2.30,2.20,2.30],
    rowH:[0.36].concat(new Array(6).fill(0.46))});

  const cards=[["533 배","양 끝 tier의 대역폭 차이 (3,200 → 6 GB/s)"],
               ["256 배","양 끝 tier의 용량 차이 (40 GB → 10 TB)"],
               ["240 배","양 끝 tier의 지연 차이 (0.5 → 120 us)"]];
  const cw=(R-L-2*0.26)/3;
  cards.forEach((c,i)=>{
    const x=L+i*(cw+0.26);
    card(s,x,4.66,cw,1.00,"FFFFFF",C1);
    txt(s,x+0.18,4.76,cw-0.36,0.42,c[0],{fs:22,b:true,c:C1});
    txt(s,x+0.18,5.22,cw-0.36,0.34,c[1],{fs:9.5,c:BODY,ls:1.15});
  });
  card(s,L,5.86,R-L,0.78,C1S,C1);
  txt(s,L+0.24,5.86,R-L-0.48,0.78,
    "같은 30 GB라도 어디에 놓느냐가 처리량을 좌우한다  →  런타임이 각 메모리의 성격에 맞게 데이터를 배치해야 한다",
    {fs:12.5,b:true,c:C1,va:"middle"});
  s.addNotes("여기까지가 '왜 배치가 필요한가'. 다음 장부터 SW 구조 문제.");
}

/* ---------- 5. SW 구조 문제: 계층 위반 ---------- */
{
  const s=slide("DP1 · 1.3 SW 구조 문제","자리 없이 확장하면 tier 지식이 스케줄러로 올라온다",
    "오늘은 계층이 깨끗하다 — 단, 지킨 것이 아니라 메모리가 하나여서 지킬 필요가 없었다");

  const LX=L, LW=6.55;
  const layers=[
    ["L1","Entrypoint / API","",0.52,false],
    ["L2","Engine · Scheduler","if tier == HBM: ...   elif tier == CXL: ...\nmigration(HBM → CXL) ...",0.86,true],
    ["L3","KVCacheManager","allocate_slots(req, n, tier)",0.58,true],
    ["L4","BlockPool[tier]","get_new_blocks(n)",0.58,true],
    ["L5","Memory","",0.86,true],
  ];
  let ly=1.70; const ys=[];
  layers.forEach(([id,name,sub,h,hot])=>{
    const top = !!sub || id === "L5";     // L5는 안에 tier 박스가 들어가므로 위쪽 정렬
    card(s,LX,ly,LW,h,hot?"FDF6E7":"FFFFFF",hot?WARN:RULE);
    txt(s,LX+0.14,ly+(top?0.08:0),0.42,top?0.24:h,id,
      {fs:10,b:true,c:MUTED,va:top?"top":"middle"});
    txt(s,LX+0.60,ly+(top?0.08:0),LW-0.75,top?0.24:h,name,
      {fs:11.5,b:true,c:INK,va:top?"top":"middle"});
    if(sub) txt(s,LX+0.60,ly+0.34,LW-0.75,h-0.40,sub,{fs:8.5,c:WARN,ls:1.2});
    ys.push(ly+h/2);
    ly+=h+0.10;
  });
  // L5 안의 tier 박스
  const tw=(LW-0.30-5*0.07)/6; let tx=LX+0.15;
  const y5=1.70+0.52+0.10+0.86+0.10+0.58+0.10+0.58+0.10;
  ["HBM","cHBM","DRAM","CXL","HBF","SSD"].forEach(t=>{
    box(s,tx,y5+0.36,tw,0.38,WARN,"FFFFFF",t,8);
    tx+=tw+0.07;
  });
  // 계층 건너뛰는 의존
  s.addShape(pres.ShapeType.line,{x:LX+LW+0.16,y:ys[1],w:0,h:ys[4]-ys[1],
    line:{color:WARN,width:1.5,dashType:"dash"}});
  arrow(s,LX+LW+0.16,ys[4],LX+LW,ys[4],WARN);
  txt(s,LX+LW+0.20,ys[1]+0.04,0.62,0.50,"✖ 계층\n건너뜀",{fs:8.5,b:true,c:WARN,ls:1.15});
  txt(s,LX,ly+0.02,LW,0.26,"✖ 상위 모듈(요청 수명주기)이 하위 세부(메모리 종류)에 직접 의존 = DIP 위반",
    {fs:10,b:true,c:WARN});

  const RX=7.95, RW=R-RX;
  txt(s,RX,1.44,RW,0.24,"그 대가",{fs:10,b:true,c:MUTED,cs:1.2});
  const costs=[
    ["변경 파급","배치 경로 6개 + 이동 경로 6×5 = 30쌍\n→ 스케줄러 안의 분기 36개.\n메모리 구성이 바뀌면 스케줄러를 고쳐야 한다"],
    ["임계 경로 팽창","스텝당 수십~수백 건의 배치·이동 판정이\nschedule() 안에서 일어난다 (이미 595줄)"],
    ["책임 혼재","스케줄링 결정과 배치 결정이 한 모듈에 섞여\n회귀가 나도 어느 쪽 탓인지 분리할 수 없다"],
  ];
  let cy=1.72;
  costs.forEach(c=>{
    card(s,RX,cy,RW,1.18,"FFFFFF",RULE);
    txt(s,RX+0.18,cy+0.12,RW-0.36,0.26,c[0],{fs:11.5,b:true,c:INK});
    txt(s,RX+0.18,cy+0.42,RW-0.36,0.68,c[1],{fs:9.5,c:BODY,ls:1.2});
    cy+=1.30;
  });
  card(s,L,5.86,R-L,0.78,INK,INK);
  txt(s,L+0.24,5.86,R-L-0.48,0.78,
    "새 메모리를 도입하는 비용이  →  스케줄러를 수정하는 비용이 된다",
    {fs:14,b:true,c:"FFFFFF",al:"center",va:"middle"});
  s.addNotes("이동은 이미 KVConnector로 분리되어 있으나 GPU↔외부 이분법 전제라 N-tier로 일반화되지 않는다. 배치에는 그런 자리조차 없다.");
}

/* ---------- 6. 필요한 것: 비어 있는 자리 ---------- */
{
  const s=slide("DP1 · 1.3 → 1.5","필요한 것 — 배치 결정을 담는 자리",
    "이동에는 KVConnector라는 자리가 이미 있다. 배치에는 없다.");

  const cx=R/2+L/2;
  box(s,cx-1.85,1.60,3.70,0.72,INK,"F2F5F6","L2  Scheduler\n'얼마나'만 말한다",10.5);
  arrow(s,cx,2.32,cx,2.76,MUTED);

  s.addShape(pres.ShapeType.roundRect,{x:cx-3.30,y:2.76,w:6.60,h:1.06,rectRadius:0.06,
    fill:{color:"FDF6E7"},line:{color:WARN,width:1.75,dashType:"dash"}});
  txt(s,cx-3.30,2.86,6.60,0.36,"???   배치 결정을 담는 자리",{fs:16,b:true,c:WARN,al:"center"});
  txt(s,cx-3.30,3.26,6.60,0.46,"이 DP의 설계 대상 — 무엇을 근거로 tier를 고를 것인가",
    {fs:10.5,c:BODY,al:"center"});
  arrow(s,cx,3.82,cx,4.26,MUTED);

  const tw=1.55, gp=0.14, n=6;
  let tx=cx-(n*tw+(n-1)*gp)/2;
  ["HBM","cHBM","DRAM","CXL","HBF","SSD"].forEach(t=>{
    box(s,tx,4.26,tw,0.56,C1,C1S,t,10);
    tx+=tw+gp;
  });
  txt(s,L,4.94,R-L,0.26,"L5  Memory",{fs:10,c:MUTED,al:"center"});

  card(s,L,5.36,R-L,1.26,PANEL,INK);
  txt(s,L+0.24,5.48,R-L-0.48,0.26,"문제 한 문장",{fs:10,b:true,c:MUTED,cs:1.2});
  txt(s,L+0.24,5.76,R-L-0.48,0.76,
    "vLLM v1에는 배치 결정을 담는 자리가 없기 때문에, 6단 이기종 메모리로 확장하면 tier 지식이 스케줄러로 올라와 DIP가 깨지고, "+
    "새 메모리를 도입하는 비용이 스케줄러를 수정하는 비용으로 전가된다.",
    {fs:12.5,b:true,c:INK,ls:1.3});
  s.addNotes("스케줄러가 tier를 지정하면 스케줄러가 메모리 토폴로지를 알아야 한다. '얼마나'만 말하고 런타임이 '어디에'를 정하는 분리는 전제이고, DP1은 그 안에서 무엇을 근거로 정하는가를 다룬다.");
}

/* ---------- 5. 관련 QA ---------- */
{
  const s=slide("DP1 · 1장 관련 QA","이 DP의 결정 변수에 의해 실제로 갈리는 QA 4개",
    "두 후보에서 같은 값이 나올 QA는 축으로 쓰지 않는다. 각 QA에는 측정 가능한 정량 프록시를 붙인다.");
  const qs=[
    ["QA1","Placement Quality\n배치 품질","성격이 다른 메모리 객체를 얼마나 잘 구분해 tier에 배치하는가?","구분 가능한 객체 등급 수 · 동일 tier 내 hot/cold 혼재율"],
    ["QA2","Decision Information Cost\n결정 정보 비용","결정에 필요한 정보를 얻는 비용과 관측 가능성은?","관측 지표 수 · 관측 불가(추정 필요) 비율 · 갱신 복잡도의 N 의존성"],
    ["QA3","Adaptivity\n적응성 · 자기 교정","상태 변화와 잘못된 배치를 얼마나 빨리 교정하는가?","오배치 교정까지 필요한 결정 횟수 · 스텝 내 staleness 노출"],
    ["QA4","Explainability\n설명 가능성 · 재현성","배치 결정을 설명하고 재현할 수 있는가?","동일 요청 재실행 시 동일 배치 확률 · 결정 근거 기록 항목 수"],
  ];
  const cw=(R-L-3*0.24)/4;
  qs.forEach((q,i)=>{
    const x=L+i*(cw+0.24);
    card(s,x,1.62,cw,4.40,"FFFFFF",RULE);
    s.addShape(pres.ShapeType.roundRect,{x:x,y:1.62,w:cw,h:0.42,rectRadius:0.05,fill:{color:INK},line:{color:INK}});
    txt(s,x,1.62,cw,0.42,q[0],{fs:11,b:true,c:"FFFFFF",al:"center",va:"middle"});
    txt(s,x+0.16,2.18,cw-0.32,0.66,q[1],{fs:12,b:true,c:INK,ls:1.15});
    txt(s,x+0.16,2.94,cw-0.32,1.30,q[2],{fs:10,c:BODY,ls:1.2});
    s.addShape(pres.ShapeType.line,{x:x+0.16,y:4.36,w:cw-0.32,h:0,line:{color:RULE,width:0.75}});
    txt(s,x+0.16,4.50,cw-0.32,0.24,"정량 프록시",{fs:8.5,b:true,c:MUTED,cs:0.8});
    txt(s,x+0.16,4.76,cw-0.32,1.10,q[3],{fs:9.5,c:C1,ls:1.2});
  });
  txt(s,L,6.22,R-L,0.26,"이 4개 축이 그대로 트레이드오프 평가축이 되고, 문제 해결 검증의 항목이 된다. 이후 새 축을 만들지 않는다.",
    {fs:10.5,i:true,c:MUTED});
  s.addNotes("QA는 문제 정의보다 먼저 뽑는다. 문제 정의는 '무엇이 나빠지는가'의 서술이고 그 무엇이 QA다.");
}

/* ---------- 6. 제약 / 가정 / 범위 밖 ---------- */
{
  const s=slide("DP1 · 1장 제약","설계를 구속하는 것과 다루지 않는 것");
  const cols=[
    ["제약 — 반드시 지킨다",C1,C1S,[
      "allocate_slots(request, num_new_tokens, ...) 호출 규약 유지. 스케줄러는 tier를 지정하지 않는다",
      "할당은 블록 단위 점진 할당 — 기본 block size 16토큰. \"30GB를 한 번에\" 하는 호출 지점은 존재하지 않는다",
      "배치 결정은 스케줄 스텝의 임계 경로에 있다. 기본 max_num_seqs=128, 스텝당 결정 수십~수백 건",
    ]],
    ["가정",MUTED,PANEL,[
      "tier 수 T = 6 (GPU HBM / CPU DRAM / CXL / Custom HBM / SSD / HBF)",
      "tier별 가용량·대역폭은 런타임에 관측 가능하다",
    ]],
    ["범위 밖 — 다른 DP",WARN,"FDF6E7",[
      "재배치(migration) 트리거와 주체 — 최초 배치만 다룬다",
      "배치된 메모리에서 무엇을 실행할 수 있는가 → DP2",
      "eviction 대상 선정 알고리즘(LRU/ARC) 자체",
    ]],
  ];
  const cw=(R-L-2*0.28)/3;
  cols.forEach((c,i)=>{
    const x=L+i*(cw+0.28);
    card(s,x,1.42,cw,4.20,c[2],c[1]);
    txt(s,x+0.18,1.58,cw-0.36,0.28,c[0],{fs:12,b:true,c:c[1]});
    bullets(s,x+0.18,1.98,cw-0.36,3.50,c[3],10);
  });
  card(s,L,5.86,R-L,0.80,"FFFFFF",RULE);
  txt(s,L+0.20,5.86,R-L-0.4,0.80,
    "제약은 Phase 7(문제 해결 검증)에서 그대로 판정 항목이 된다. 제약을 위반한 후보는 별점과 무관하게 탈락한다.",
    {fs:11.5,b:true,c:INK,va:"middle"});
  s.addNotes("범위 밖 선언은 나중에 잔여를 다른 DP로 넘길 때 정당성의 근거가 된다.");
}

/* ---------- 7. 설계 쟁점 ---------- */
{
  const s=slide("DP1 · 2장 설계 쟁점","자리를 만들려면 그 자리의 소유자를 먼저 정해야 한다",
    "문제의 뿌리는 배치 기준을 담을 자리가 없다는 것이다. 소유자가 정해지면 배치 결정은 그 축 위의 함수가 되고, 호출 지점의 조건문이 사라진다.");
  card(s,L,1.50,R-L,1.06,INK,INK);
  txt(s,L+0.24,1.62,R-L-0.48,0.30,"설계 결정 변수",{fs:10,b:true,c:"8AA4A4",cs:1.5});
  txt(s,L+0.24,1.94,R-L-0.48,0.48,"배치 정책의 인덱스 축을 어디에 둘 것인가?",{fs:20,b:true,c:"FFFFFF"});
  arrow(s,4.6,2.70,3.4,3.10,C1); arrow(s,8.7,2.70,9.9,3.10,C2);
  const vals=[
    [AX,C1,C1S,"값 A — 자원 축","정책의 1급 개체는 Tier다.\n요청은 익명이며, tier 상태가 결정을 지배한다.",
     "불변식: 자원 제약을 절대 위반하지 않는다"],
    [BX,C2,C2S,"값 B — 객체 축","정책의 1급 개체는 메모리 객체의 특성 클래스다.\n클래스가 목표 tier를 지시하고, tier 상태는 그 지시를 만족시키기 위해 조정된다.",
     "불변식: 객체 클래스의 배치 계약을 지킨다"],
  ];
  vals.forEach(v=>{
    card(s,v[0],3.16,CW,1.90,v[2],v[1]);
    txt(s,v[0]+0.20,3.32,CW-0.4,0.30,v[3],{fs:13,b:true,c:v[1]});
    txt(s,v[0]+0.20,3.70,CW-0.4,0.90,v[4],{fs:10.5,c:BODY,ls:1.25});
    txt(s,v[0]+0.20,4.62,CW-0.4,0.32,v[5],{fs:10.5,b:true,c:v[1]});
  });
  card(s,L,5.30,R-L,1.32,"FFFFFF",RULE);
  txt(s,L+0.20,5.42,R-L-0.4,0.26,"이 변수가 배타적인 이유",{fs:10,b:true,c:MUTED});
  txt(s,L+0.20,5.70,R-L-0.4,0.80,
    "인덱스는 하나여야 한다. 두 축에 동시에 정책을 매달면 경합 상황에서 두 결정이 서로 반대 방향을 가리킨다.\n쟁점 문장에 후보 이름을 넣지 않는다 — 답을 선점하면 후보 비교가 형식화된다.",
    {fs:10.5,c:BODY,ls:1.25});
  s.addNotes("결정 변수는 하나. 두 개면 DP를 쪼갠다.");
}

/* ---------- 8. 두 후보 비교표 ---------- */
{
  const s=slide("DP1 · 3장 후보 구조","두 후보 구조 비교");
  const ROWS=[{y:1.44,h:0.82,label:"후보 구조"},{y:2.26,h:1.06,label:"대표 구조도"},
              {y:3.32,h:1.32,label:"장점"},{y:4.64,h:1.32,label:"단점"},{y:5.96,h:0.74,label:"TRADE-OFF"}];
  const LBLW=1.75, A=2.32, COLW=5.19, B=7.61;
  ROWS.forEach((r,i)=>{
    if(i>0) s.addShape(pres.ShapeType.line,{x:L,y:r.y,w:R-L,h:0,line:{color:RULE,width:0.75}});
    txt(s,L,r.y,LBLW,r.h,r.label,{fs:11,b:true,c:MUTED,va:"middle"});
  });
  s.addShape(pres.ShapeType.line,{x:L,y:ROWS[0].y,w:R-L,h:0,line:{color:INK,width:1.5}});
  s.addShape(pres.ShapeType.line,{x:L,y:6.70,w:R-L,h:0,line:{color:INK,width:1.5}});
  [A-0.14,B-0.14].forEach(vx=>s.addShape(pres.ShapeType.line,{x:vx,y:ROWS[0].y,w:0,h:6.70-ROWS[0].y,line:{color:RULE,width:0.75}}));
  const cands=[
    [A,C1,C1S,"Candidate 1 — Tier-Indexed",
     "요청을 익명으로 두고 자원 상태만으로 결정을 닫아 자기 교정력을 얻는 대신, 구분 능력과 재현성을 포기",
     ["할당 요청\n(크기만)","Tier 상태\n용량·대역폭","최적 tier\n선택","배치"],
     ["(정보비용) 추정이 필요한 지표 0%","(정보비용) 갱신 O(6), 요청 수와 무관","(적응성) 오배치가 다음 할당 1회로 교정","요청 인터페이스 무변경, 신규 모듈 2개"],
     ["(배치품질) 구분 가능한 등급 1종","(배치품질) 상위 tier를 도착 순서로 점유","(적응성) 스텝 내 herding — 예약 카운터 필요","(재현성) 재현 불가, 24개 상태 스냅샷 필요"]],
    [B,C2,C2S,"Candidate 2 — Object-Indexed",
     "객체 특성으로 결정을 고정해 구분 능력과 재현성을 얻는 대신, 미래 정보 추정과 오분류 고착을 감수",
     ["할당 요청\n(크기+객체)","객체 등급\nhot·수명","등급→Tier\n계약","배치"],
     ["(배치품질) 구분 등급 8종, hot / cold 분리","(배치품질) 같은 스텝이 분산되어 herding 없음","(재현성) 결정론적 배치, 근거 로깅 1항목","(재현성) 배치 정책을 단위 테스트로 고정"],
     ["(정보비용) 결정 입력 100%가 미래 정보","(적응성) 오분류가 객체 수명 내내 고착","공유 블록은 최초 소유자 등급으로 고착","신규 tier 추가 시 8개 계약 재정의"]],
  ];
  cands.forEach(c=>{
    const x=c[0];
    s.addShape(pres.ShapeType.roundRect,{x:x,y:1.58,w:0.20,h:0.20,rectRadius:0.10,fill:{color:c[1]},line:{color:c[1]}});
    txt(s,x+0.30,1.54,COLW-0.4,0.28,c[3],{fs:14,b:true,c:c[1]});
    txt(s,x,1.88,COLW-0.10,0.34,c[4],{fs:9.5,c:BODY,ls:1.15});
    const n=c[5].length,bw=1.01,gp=0.30,used=n*bw+(n-1)*gp; let bx=x+(COLW-used)/2;
    c[5].forEach((t,i)=>{ box(s,bx,2.44,bw,0.70,c[1],c[2],t,8.5);
      if(i<n-1) txt(s,bx+bw,2.44,gp,0.70,"→",{fs:13,b:true,c:c[1],al:"center",va:"middle"});
      bx+=bw+gp;});
    bullets(s,x,3.42,COLW-0.10,1.16,c[6],10);
    bullets(s,x,4.74,COLW-0.10,1.16,c[7],10);
  });
  card(s,A-0.06,6.06,(B+COLW)-A+0.06,0.54,"F4F6F8","F4F6F8");
  txt(s,A+0.06,6.06,(B+COLW)-A-0.18,0.54,
    "관측 가능한 상태만으로 결정을 닫아 얻는 자기 교정력  ↔  객체 특성으로 결정을 고정해 얻는 구분 능력과 재현성",
    {fs:12.5,b:true,c:INK,al:"center",va:"middle"});
  s.addNotes("dp-design 스킬의 PPT 페이지 규격: 가로=두 후보, 세로=이름/대표 구조도/장점/단점/TRADEOFF.");
}

/* ---------- 9. 양립 불가 논증 ---------- */
{
  const s=slide("DP1 · 3.3장 양립 불가 논증","두 후보가 대등한 대안인 이유 — 3중 논증",
    "가장 먼저 나오는 반박은 \"C2도 tier 정보를 쓰니 C1의 상위호환 아닌가?\" 이다. 답은 아니오.");
  const items=[
    ["①  불변식 충돌","상위 tier가 가득 찬 상태에서 hot 객체가 도착하면 두 정책의 결정이 정반대다.",
     ["C1: 새 객체를 하위 tier로 흘림 (기존 객체 유지)","C2: 기존 cold를 밀어내고 새 객체를 넣음"],
     "두 불변식은 같은 순간에 성립할 수 없다. 우선순위를 정하는 순간 하위가 된 쪽은 정책이 아니라 tie-breaker로 격하된다 — 이미 하나를 고른 것이다."],
    ["②  결정 단위 충돌","C1은 할당 1건 단위, C2는 객체(요청) 단위로 결정하고 블록이 클래스를 상속한다.",
     ["C1: 블록에 소유자 개념이 없다","C2: 블록은 어느 객체에 속한 블록이다"],
     "소유자 개념의 유무 자체가 갈리므로 두 결정 단위는 공존할 수 없다. (prefix 캐시 hit 경로는 배치 결정이 없으므로 두 후보가 동일하게 동작한다 — 그 문제는 QA3에서 다룬다)"],
    ["③  상위호환 반박","C2가 tier 정보를 읽는 것은 맞다. 그러나 포함 관계는 성립하지 않는다.",
     ["권한이 반대: C1은 하드 제약(불변 입력), C2는 비용 항(조정 대상)","C2가 C1을 흉내내려면 특성 추정 비용을 그대로 내고 이득만 버려야 한다 = C1보다 비싼 C1","역방향은 원리적 불가 — hotness·lifetime은 할당 시점에 관측 불가능한 미래 정보다"],
     "기능이 포개져 보여도 정보에 대한 권한과 정보 획득 비용의 축이 다르면 상위호환이 아니다."],
  ];
  const cw=(R-L-2*0.26)/3;
  items.forEach((it,i)=>{
    const x=L+i*(cw+0.26);
    card(s,x,1.62,cw,4.62,"FFFFFF",RULE);
    txt(s,x+0.18,1.76,cw-0.36,0.30,it[0],{fs:13,b:true,c:INK});
    txt(s,x+0.18,2.14,cw-0.36,0.62,it[1],{fs:10,c:BODY,ls:1.2});
    card(s,x+0.18,2.84,cw-0.36,1.42,PANEL,RULE);
    bullets(s,x+0.32,2.96,cw-0.62,1.20,it[2],9.5);
    txt(s,x+0.18,4.40,cw-0.36,1.70,it[3],{fs:9.5,c:C1,ls:1.25});
  });
  txt(s,L,6.44,R-L,0.26,"세 논증이 모두 성립하므로 두 후보는 어느 쪽도 다른 쪽의 특수 케이스가 아니다.",{fs:10.5,i:true,c:MUTED});
  s.addNotes("이 장이 DP1에서 리뷰 질문이 가장 많이 나오는 지점.");
}

/* ---------- 10. 백데이터 정량 종합 ---------- */
{
  const s=slide("DP1 · 4장 백데이터 종합","다이어그램에서 뽑은 정량 지표 — 별점의 근거",
    "모듈뷰 · 컴포넌트 · 시퀀스 · 클래스 상세는 별도 덱(vllm-dp1-candidate-structure-detail.pptx) 참조");
  const data=[
    ["결정 입력 지표 수","클래스","24 (6 tier × 4)","3 (객체 특성) + tier 제약"],
    ["관측 불가(추정 필요) 지표 비율","클래스","0 %","0~100 % — 특성 집합 선택에 달림"],
    ["구분 가능한 객체 등급","컴포넌트","1 (익명)","8 (2³)"],
    ["상태 갱신 비용","컴포넌트","스텝당 O(T)=6, 요청 수 무관","스텝당 O(new_N·D)"],
    ["dispatch 메시지 수","시퀀스","5","7 (경합 시 9)"],
    ["오배치 교정까지 결정 횟수","시퀀스","1","불가 (수명 내 고착)"],
    ["스텝 내 herding 노출","컴포넌트","있음 (예약 카운터 필요)","없음"],
    ["동일 요청 재실행 시 동일 배치","시퀀스","보장 안 됨","보장"],
    ["신규 tier 1개 추가 비용","클래스","테이블 행 1개","8개 클래스 계약 재정의"],
    ["신규 모듈 수","모듈 뷰","2","4"],
  ];
  const rows=[[hdr("지표"),hdr("출처","center"),hdr("C1 · Tier-Indexed","center"),hdr("C2 · Object-Indexed","center")]];
  data.forEach(d=>rows.push([
    {text:d[0],options:{bold:true,color:INK,fontSize:9.5}},
    {text:d[1],options:{color:MUTED,fontSize:9,align:"center"}},
    {text:d[2],options:{color:C1,bold:true,fontSize:9.5,align:"center"}},
    {text:d[3],options:{color:C2,bold:true,fontSize:9.5,align:"center"}},
  ]));
  table(s,rows,{y:1.66,colW:[4.10,1.20,3.50,3.50],rowH:[0.38].concat(new Array(10).fill(0.42))});
  txt(s,L,6.40,R-L,0.28,"별점을 매길 때 근거가 다이어그램에서 나오지 않는다면, 별점이 아니라 다이어그램이 부족한 것이다.",
    {fs:10,i:true,c:MUTED});
  s.addNotes("이 표가 다음 장 별점 매트릭스의 근거 원본.");
}

/* ---------- 11. 별점 매트릭스 ---------- */
{
  const s=slide("DP1 · 5장 트레이드오프","QA 별점 평가 — 지배 없음, 9 : 9 동점",
    "★★★ 구조적으로 유리 · ★★☆ 가능하나 비용 발생 · ★☆☆ 구조적으로 불리");
  const data=[
    ["QA1. 이기종 환경 배치 품질","★★☆","★★★","구분 가능 등급 1종 vs 8종. C1은 상위 tier 점유가 도착 순서로 결정됨. C2의 ★★★는 분류가 맞고 유보량이 적절할 때의 값이다"],
    ["QA2. 결정 정보 비용","★★★","★★☆","갱신 O(T)=6 · 요청 수 무관 vs O(new_N·D) + 외부 특성 소스 1개. 관측 불가 지표 0% vs 최대 100% — QA1 이득을 내는 특성일수록 미래 정보다"],
    ["QA3. 적응성 / 자기 교정","★★★","★☆☆","오배치 교정까지 결정 1회 vs 교정 불가(수명 내 고착). C1은 herding 대비 예약 카운터 필요 (시퀀스)"],
    ["QA4. 설명 가능성 / 재현성","★☆☆","★★★","동일 배치 재현 보장 없음(24개 상태 스냅샷 필요) vs 보장(클래스 라벨 1개)"],
  ];
  const rows=[[hdr("QA"),hdr("C1 · Tier-Indexed","center"),hdr("C2 · Object-Indexed","center"),hdr("정량 근거")]];
  data.forEach(d=>rows.push([
    {text:d[0],options:{bold:true,color:INK,fontSize:10.5}},
    {text:d[1],options:{color:C1,bold:true,fontSize:14,align:"center"}},
    {text:d[2],options:{color:C2,bold:true,fontSize:14,align:"center"}},
    {text:d[3],options:{color:BODY,fontSize:9.5}},
  ]));
  rows.push([
    {text:"합계  (★ = 1 / 2 / 3점)",options:{bold:true,color:INK,fontSize:10.5,fill:{color:"F4F6F8"}}},
    {text:"9",options:{bold:true,color:C1,fontSize:15,align:"center",fill:{color:"F4F6F8"}}},
    {text:"9",options:{bold:true,color:C2,fontSize:15,align:"center",fill:{color:"F4F6F8"}}},
    {text:"모든 축에서 별점이 갈리고 각 후보가 ★★★ 2개 보유 — 선택은 QA 가중치가 결정한다",
     options:{bold:true,color:INK,fontSize:9.5,fill:{color:"F4F6F8"}}},
  ]);
  table(s,rows,{y:1.66,colW:[2.70,1.70,1.70,6.20],rowH:[0.42,1.02,1.02,1.02,1.02,0.58]});
  s.addNotes("동점은 우연이 아니라 두 후보가 서로 다른 잔여를 남기기 때문. 다음 장에서 드러난다.");
}

/* ---------- 12. 핵심 트레이드오프 ---------- */
{
  const s=slide("DP1 · 8장 핵심 트레이드오프","무엇과 무엇을 맞바꾸는가");
  const rows=[
    ["정책의 정의","f(현재 자원 상태)","f(객체 특성 클래스)"],
    ["관측 불가 지표","0 %","최대 100 %"],
    ["구분 등급","1 종","8 종"],
    ["오배치 교정","1회 만에 자동","고착 (불가)"],
    ["재현성","보장 안 됨","보장"],
  ];
  chip(s,AX,1.46,C1,"Candidate 1 — Tier-Indexed (자원 축)");
  chip(s,BX,1.46,C2,"Candidate 2 — Object-Indexed (객체 축)");
  let y=1.94;
  rows.forEach(r=>{
    txt(s,L,y,2.6,0.52,r[0],{fs:10,b:true,c:MUTED,va:"middle",al:"right"});
    card(s,3.30,y,4.30,0.52,C1S,C1); txt(s,3.30,y,4.30,0.52,r[1],{fs:11,b:true,c:C1,al:"center",va:"middle"});
    txt(s,7.72,y,0.56,0.52,"↔",{fs:13,b:true,c:MUTED,al:"center",va:"middle"});
    card(s,8.40,y,4.30,0.52,C2S,C2); txt(s,8.40,y,4.30,0.52,r[2],{fs:11,b:true,c:C2,al:"center",va:"middle"});
    y+=0.64;
  });
  card(s,L,5.30,R-L,0.92,INK,INK);
  txt(s,L+0.24,5.30,R-L-0.48,0.92,
    "관측 가능한 상태만으로 결정을 닫아 얻는 자기 교정력   ↔   객체 특성으로 결정을 고정해 얻는 구분 능력과 재현성",
    {fs:14,b:true,c:"FFFFFF",al:"center",va:"middle"});
  txt(s,L,6.42,R-L,0.28,"두 후보는 같은 축의 양 끝이다. 중간값을 후보로 세우면 비교가 무의미해진다.",{fs:10.5,i:true,c:MUTED});
  s.addNotes("대구로 읽히도록 배치. 한쪽만 서술하면 트레이드오프가 아니라 평가다.");
}

/* ---------- 13. 문제 해결 검증 ---------- */
{
  const s=slide("DP1 · 10장 문제 해결 검증","배경에서 정의한 것으로 되돌아가 절대 판정한다",
    "트레이드오프는 상대 비교(어느 쪽이 나은가), 이 절은 절대 판정(애초에 풀려던 것을 푸는가)");
  const P=(t)=>({text:t,options:{fontSize:9,bold:true,align:"center",
    color:t.indexOf("미해소")>=0?WARN:(t.indexOf("부분")>=0?MUTED:C1)}});
  const data=[
    ["문제 한 문장 — 기준을 담을 자리가 없다","참","자리 = TierStateTable\n조건문 소멸","자리 = Class-Tier Contract\n조건문 소멸","둘 다 해결"],
    ["QA1 구분 가능한 등급","1종","1종 — 미해소","8종 — 해소","C1 부분 / C2 해결"],
    ["QA2 지표 수 · 갱신 정의","1개, 미정의","24개, 갱신 정의됨","24개+특성3, 갱신 정의됨","둘 다 해결"],
    ["QA3 오배치 교정 경로","없음","자동 반영 — 해소","없음 — 미해소","C1 해결 / C2 미해소"],
    ["QA4 결정 근거 기록","없음","24개 스냅샷 — 부분","라벨 1개 — 해소","C1 부분 / C2 해결"],
    ["제약 allocate_slots 규약","—","준수","준수","위반 없음"],
    ["제약 블록 단위 점진 할당","—","준수","조건부 준수","위반 없음"],
    ["제약 스텝 임계 경로","—","O(6), 요청 수 무관","O(new_N·D), 부하 비례","위반 없음"],
  ];
  const rows=[[hdr("배경에서 정의한 것"),hdr("As-Is","center"),hdr("Candidate 1","center"),hdr("Candidate 2","center"),hdr("판정","center")]];
  data.forEach(d=>rows.push([
    {text:d[0],options:{bold:true,color:INK,fontSize:9.5}},
    {text:d[1],options:{color:MUTED,fontSize:9,align:"center"}},
    {text:d[2],options:{color:d[2].indexOf("미해소")>=0?WARN:C1,bold:true,fontSize:9,align:"center"}},
    {text:d[3],options:{color:d[3].indexOf("미해소")>=0?WARN:C2,bold:true,fontSize:9,align:"center"}},
    P(d[4]),
  ]));
  table(s,rows,{y:1.72,colW:[3.30,1.30,2.90,2.90,1.90],rowH:[0.36].concat(new Array(8).fill(0.44))});
  card(s,L,5.62,R-L,1.00,C1S,C1);
  txt(s,L+0.22,5.72,R-L-0.44,0.30,"판정 요약 — 제약 위반 없음. 두 후보 모두 핵심 문제를 해결한다.",{fs:12,b:true,c:C1});
  txt(s,L+0.22,6.06,R-L-0.44,0.48,
    "그러나 어느 후보도 QA 4개를 모두 해결하지 못한다. C1은 QA1을, C2는 QA3을 미해소로 남긴다 — 이것이 9:9 동점의 실체다. "+
    "선택은 \"어느 쪽이 더 나은가\"가 아니라 \"어느 잔여를 감당할 수 있는가\"의 문제다.",
    {fs:10.5,c:INK,ls:1.2});
  s.addNotes("제약 위반은 별점을 이긴다. 두 후보 모두 미해결이면 설계 쟁점으로 복귀해야 한다.");
}

/* ---------- 14. 최종 선택 ---------- */
{
  const s=slide("DP1 · 11장 최종 구조 선택","Candidate 1 (Tier-Indexed) + 컨텍스트 길이 보강");
  card(s,L,1.42,R-L,1.34,C1S,C1);
  txt(s,L+0.24,1.54,R-L-0.48,0.28,"선택 근거",{fs:10,b:true,c:C1,cs:1.2});
  txt(s,L+0.24,1.84,R-L-0.48,0.84,
    "우리 맥락에서 QA3(적응성)은 QA1(배치 품질)보다 중요하다. 근거는 1장의 제약 두 가지 — 배치 결정이 스케줄 스텝 임계 경로에 있고, 요청 인터페이스를 건드리지 않아야 한다.\n"+
    "그리고 C2를 최선 형태(블록 단위 비용 모델)로 세워 실측해도, C2가 QA1에서 얻는 이득은 아직 알 수 없는 값 두 가지에 걸려 있다.",
    {fs:10.5,c:INK,ls:1.28});
  const unc=[
    ["① 수명 예측 정확도","크기가 가치·가격에서 상쇄되고 나면 배치를 가르는 것은 블록당 읽기 강도뿐인데, 그 주성분인 수명은 할당 시점에 관측 불가"],
    ["② 유보량","유보하지 않으면 구분 지표가 2.11로 C1(2.06)과 같아져 객체 축을 쓴 이득이 0이 된다"],
  ];
  unc.forEach((u,i)=>{
    const x=L+i*((R-L)/2+0.14), w=(R-L)/2-0.14;
    card(s,x,2.82,w,0.94,"FFFFFF",C2);
    txt(s,x+0.16,2.90,w-0.32,0.26,u[0],{fs:11,b:true,c:C2});
    txt(s,x+0.16,3.16,w-0.32,0.56,u[1],{fs:9.5,c:BODY,ls:1.18});
  });
  txt(s,L,3.86,R-L,0.24,
    "둘 중 ②가 더 나쁘다 — 예측 정확도는 로그로 사후 측정이라도 되지만, 적정 유보량은 아직 오지 않은 요청의 분포에 달려 있어 요청별로 잴 수조차 없다.",
    {fs:10,i:true,c:MUTED});
  txt(s,L,4.14,6.0,0.26,"포기한 축과 완화책",{fs:10.5,b:true,c:MUTED});
  const mit=[
    ["QA1 구분 능력","관측 가능한 특성 중 컨텍스트 길이를 TierState.score()의 한 항으로 넣는다","스텝당 대역폭 요구는 구분 가능. 읽기 빈도(미래 정보)는 여전히 불가"],
    ["QA4 재현성","배치 결정 시 tier score 스냅샷을 결정 로그로 남긴다 (24개 값 → 요약 스칼라 3~4개)","재현은 불가하나 사후 설명은 가능해진다"],
  ];
  let y=4.44;
  mit.forEach(m=>{ card(s,L,y,6.0,1.02,"FFFFFF",RULE);
    txt(s,L+0.18,y+0.10,5.64,0.26,m[0],{fs:11,b:true,c:INK});
    txt(s,L+0.18,y+0.38,5.64,0.36,m[1],{fs:9.5,c:BODY,ls:1.15});
    txt(s,L+0.18,y+0.74,5.64,0.24,"→ "+m[2],{fs:9,c:C1});
    y+=1.10;});
  txt(s,6.80,4.14,6.0,0.26,"혼합 판정 — 이것은 혼합이 아니라 \"C1 + 보강\"이다",{fs:10.5,b:true,c:MUTED});
  card(s,6.80,4.44,6.0,2.22,PANEL,C1);
  txt(s,6.98,4.56,5.64,0.30,"판정 질문: 단일 진실 원천이 여전히 하나인가?",{fs:11,b:true,c:C1});
  bullets(s,6.98,4.92,5.64,1.62,[
    "그렇다 — 단일 진실 원천은 여전히 TierStateTable 하나다",
    "객체 정보(컨텍스트 길이)는 정책의 인덱스가 아니라 score의 한 항(가중치)으로만 들어간다",
    "경합 시 불변식은 그대로 \"자원 제약 우선\"이다",
    "인덱스 축이 바뀌지 않았으므로 3.3장의 배타성 논증은 그대로 유효하다",
  ],9.5);

  s.addNotes("별점 합계로 고르지 않는다. 가중치는 1장의 제약에서 도출한다.");
}

/* ---------- 15. PoC와 반전 조건 ---------- */
{
  const s=slide("DP1 · 11장 검증 계획","측정으로 가를 항목과 선택이 뒤집히는 조건",
    "판정 임계값을 미리 고정한다 — 측정 후에 해석을 바꾸지 않기 위해서다");
  const data=[
    ["출력 길이 예측 정확도","프로덕션 로그에서 (endpoint, model, prompt_len_bucket)별 실제 출력 길이 분포 수집 → p50 예측의 상대 오차",
     "중앙값 상대 오차 < 30 % 그리고 상위 25 % 장수명 요청을 재현율 0.7 이상으로 식별 → C2 재검토"],
    ["스텝 내 herding 실측","C1 프로토타입에서 예약 카운터 유무별 tier 점유 분포 비교",
     "예약 카운터로 편중이 해소되면 QA3 우려 소멸 → C1 확정"],
    ["상위 tier 점유의 워크로드 편향","도착 순서 배치 시 상위 tier를 차지한 요청의 KV 읽기량 비중 측정",
     "상위 20 % 요청이 전체 읽기량의 80 % 미만이면 구분의 이득이 작음 → C1 유지"],
    ["유보량 민감도","C2 비용 모델에서 상위 tier 유보 비율을 0~50 %로 훑으며 구분 지표와 활용률 곡선을 그린다",
     "두 지표가 동시에 허용치를 넘는 유보 비율이 없으면 C2는 튜닝 불가능한 구조 → C1 확정"],
  ];
  const rows=[[hdr("측정 대상"),hdr("측정 방법"),hdr("판정 임계값")]];
  data.forEach(d=>rows.push([
    {text:d[0],options:{bold:true,color:INK,fontSize:10}},
    {text:d[1],options:{color:BODY,fontSize:9.5}},
    {text:d[2],options:{color:C1,bold:true,fontSize:9.5}},
  ]));
  table(s,rows,{y:1.66,colW:[3.10,5.10,4.10],rowH:[0.34,0.74,0.68,0.68,0.80]});
  txt(s,L,5.34,R-L,0.26,"반전 조건 — 다음 중 하나가 성립하면 이 선택은 뒤집힌다",{fs:11,b:true,c:MUTED});
  const rev=[
    ["1","출력 길이 예측 정확도가 위 임계값을 넘는다","C2의 QA1 이득이 확실해진다"],
    ["2","배치 재현성이 SLA · 과금 근거로 요구된다","QA4가 수용 불가 축이 된다"],
    ["3","한 메모리에 여러 실행 리소스가 붙는 토폴로지가 확정된다","객체별 목표 지정이 필요해진다"],
  ];
  const cw=(R-L-2*0.26)/3; 
  rev.forEach((r,i)=>{ const x=L+i*(cw+0.26);
    card(s,x,5.64,cw,1.06,"FFFFFF",C2);
    s.addShape(pres.ShapeType.ellipse,{x:x+0.18,y:5.76,w:0.22,h:0.22,fill:{color:C2},line:{color:C2}});
    txt(s,x+0.18,5.76,0.22,0.22,r[0],{fs:8.5,b:true,c:"FFFFFF",al:"center",va:"middle"});
    txt(s,x+0.48,5.74,cw-0.66,0.46,r[1],{fs:9.5,b:true,c:INK,ls:1.12});
    txt(s,x+0.48,6.24,cw-0.66,0.40,"→ "+r[2],{fs:8.5,c:C2,ls:1.12});
  });
  s.addNotes("선택하지 않은 후보는 폐기가 아니라 조건부 재검토 대상.");
}

/* ---------- 16. 두 종류의 유보 ---------- */
{
  const s=slide("DP1 · 부록 D.3 / 실측","두 종류의 유보 — 같은 단어, 다른 메커니즘",
    "구현 시 두 개를 한 코드로 합치려 들면 안 된다. 대비 대상도, 유보량을 정하는 방법도 다르다.");
  const rows=[[hdr(""),hdr("유보 A — 스텝 내 예약","center"),hdr("유보 B — 미래를 위한 여유","center")]];
  [["누가 필요한가","C1 (그리고 C2도)","C2만"],
   ["무엇을 대비하나","이미 내린 같은 스텝의 다른 결정","아직 오지 않은 고강도 요청"],
   ["왜 필요한가","tier 상태가 스텝 경계에서만 갱신되어\n앞선 결정이 다음 결정에 보이지 않는다","지금 상위 tier를 채우면 나중에 올\n고강도 요청이 들어갈 자리가 없다"],
   ["메커니즘","reserved[tier] += blocks\nfree = capacity - used - reserved","빈 tier에도 값을 매긴다\n(희소성 항 바닥을 0이 아닌 값으로)"],
   ["유보량은?","계산된다 — 이번 스텝에서 이미 약속한 양","튜닝 파라미터 — 미래 도착 분포에 의존"],
   ["정답이 있나","있다","없다 (관측만으로는)"],
   ["없으면","용량 초과 커밋 (실측 overcommit 72회)","구분 능력 0 (2.11 ≈ C1의 2.06)"],
   ["성격","정합성 요건","성능 요건"],
  ].forEach(d=>rows.push([
    {text:d[0],options:{bold:true,color:MUTED,fontSize:9.5}},
    {text:d[1],options:{color:C1,fontSize:9.5,align:"center"}},
    {text:d[2],options:{color:C2,fontSize:9.5,align:"center"}},
  ]));
  table(s,rows,{y:1.72,colW:[2.40,4.95,4.95],rowH:[0.34].concat(new Array(8).fill(0.50))});
  card(s,L,6.02,R-L,0.62,PANEL,RULE);
  txt(s,L+0.20,6.02,R-L-0.40,0.62,
    "식당 좌석에 비유하면 A는 예약 접수(이미 받은 예약을 빈자리로 세면 오버부킹), B는 VIP석 남겨두기(몇 개 남길지는 오늘 VIP가 몇 명 올지에 달렸다).",
    {fs:10.5,b:true,c:INK,va:"middle"});
  s.addNotes("C1은 A만 필요하다. C2는 A도 B도 필요하다 — 이것이 C2가 추가로 지는 구현·운영 부담이다.");
}

/* ---------- 17. 프로토타입 실측 ---------- */
{
  const s=slide("DP1 · 프로토타입 실측","코드를 돌려 문서로 되돌린 것",
    "doc-mk/prototype — 두 후보의 배치 결정 로직을 구현하고 문서의 주장을 31개 테스트로 검증했다");
  const items=[
    ["오분류는 이득을 없애는 정도가 아니라 배치를 역전시킨다",
     "misclassification 시나리오에서 C2 구분 지표 0.43 (1.0 미만 = 역전). C1은 1.00 — 구분 못 하지만 역전도 없다",
     "→ QA1 ★★★는 분류가 맞았을 때의 조건부 값"],
    ["예약 카운터는 완화책이 아니라 정합성 요건이다",
     "예약 없는 C1은 overcommit 72회 — 자기 불변식(자원 제약)을 스스로 어긴다",
     "→ C1 정의의 일부로 승격"],
    ["크기는 무시하는 것이 아니라 상쇄되는 것이 옳다",
     "블록 단위 비용 모델에서 큰 객체는 값도 이득도 비례해 커진다. 초기 구현의 크기 편향은 구조가 아니라 아티팩트였다",
     "→ 후보를 최선 형태(steelman)로 세운 뒤 재측정"],
    ["구분은 유보를 요구하고, 유보량은 미래에 달려 있다",
     "유보 없음 2.11 (≈ C1의 2.06) / 유보 있음 8.40. 대신 저부하 활용률 1.000 → 0.500",
     "→ 선택 근거에 두 번째 불확실성으로 추가"],
  ];
  const cw=(R-L-0.26)/2, ch=2.20;
  items.forEach((it,i)=>{
    const x=L+(i%2)*(cw+0.26), y=1.72+Math.floor(i/2)*(ch+0.24);
    card(s,x,y,cw,ch,"FFFFFF",RULE);
    s.addShape(pres.ShapeType.ellipse,{x:x+0.18,y:y+0.18,w:0.26,h:0.26,fill:{color:WARN},line:{color:WARN}});
    txt(s,x+0.18,y+0.18,0.26,0.26,String(i+1),{fs:9,b:true,c:"FFFFFF",al:"center",va:"middle"});
    txt(s,x+0.54,y+0.14,cw-0.72,0.56,it[0],{fs:11.5,b:true,c:INK,ls:1.15});
    txt(s,x+0.18,y+0.80,cw-0.36,0.90,it[1],{fs:9.5,c:BODY,ls:1.2});
    txt(s,x+0.18,y+1.78,cw-0.36,0.32,it[2],{fs:9.5,b:true,c:C1,ls:1.15});
  });
  txt(s,L,6.60,R-L,0.26,
    "문서의 수치가 예측이라면 이 값들은 실측이다. 테스트가 깨지면 코드가 틀렸거나 문서가 틀린 것이며, 별점을 맞추려고 테스트를 고치지 않는다.",
    {fs:10,i:true,c:MUTED});
  s.addNotes("네 건 모두 코드를 돌려보지 않았으면 나오지 않았을 발견이다.");
}

/* ---------- 16. 잔여와 DP 결합 ---------- */
{
  const s=slide("DP1 · 12장 잔여 문제와 DP 연결","무엇을 남겼고, 어디서 푸는가",
    "\"왜 이 DP에서 풀 수 없는가\"에 답하지 못하면 잔여 인계는 회피로 읽힌다");
  const res=[
    ["R1","재분류","배치 정확도를 올리려면 실행 후 관측으로 재분류해야 하는데 두 후보 모두 갖지 않는다",
     "결정 변수가 다르다 — 재분류는 \"언제 다시 결정하는가\"라는 별도 축이다",
     "DP3 (신규) 재배치 트리거","DP1의 인덱스 축이 DP3의 신호원을 제약한다 (C1 선택 → tier 상태 기반)"],
    ["R2","구분 능력","C1 선택으로 QA1이 미해소로 남는다",
     "구분하려면 미래 정보 추정이 필요 — 배치 구조가 아니라 예측기 설계 문제다",
     "DP4 (신규) 요청 특성 예측","DP4의 예측 정확도가 DP1의 반전 조건을 공급한다"],
    ["R3","재현성","배치 결정의 재현성이 부분 미해소로 남는다",
     "결정 로그 설계는 결정 구조가 아니라 관측성 설계다",
     "관측성 작업 (소규모)","DP1의 선택이 로그 스키마를 결정한다"],
  ];
  const cw=(R-L-2*0.26)/3;
  res.forEach((r,i)=>{
    const x=L+i*(cw+0.26);
    card(s,x,1.72,cw,3.02,"FFFFFF",RULE);
    s.addShape(pres.ShapeType.roundRect,{x:x,y:1.72,w:cw,h:0.40,rectRadius:0.05,fill:{color:WARN},line:{color:WARN}});
    txt(s,x+0.16,1.72,cw-0.32,0.40,r[0]+"  ·  "+r[1],{fs:11,b:true,c:"FFFFFF",va:"middle"});
    txt(s,x+0.18,2.24,cw-0.36,0.62,r[2],{fs:9.5,b:true,c:INK,ls:1.2});
    txt(s,x+0.18,2.94,cw-0.36,0.24,"왜 여기서 못 푸는가",{fs:8.5,b:true,c:MUTED});
    txt(s,x+0.18,3.18,cw-0.36,0.60,r[3],{fs:9,c:BODY,ls:1.2});
    txt(s,x+0.18,3.84,cw-0.36,0.24,"어디서 푸는가",{fs:8.5,b:true,c:MUTED});
    txt(s,x+0.18,4.08,cw-0.36,0.26,r[4],{fs:10,b:true,c:C1});
    txt(s,x+0.18,4.38,cw-0.36,0.30,"결합: "+r[5],{fs:8.5,c:MUTED,ls:1.15});
  });
  txt(s,L,4.86,R-L,0.26,"DP 결합 맵",{fs:11,b:true,c:MUTED});
  const rows=[[hdr("관계"),hdr("상대 DP"),hdr("내용")]];
  [["상류 (이 DP를 제약)","—","없음. DP1이 배치 사슬의 시작이다"],
   ["하류","DP2 · Compute-Capable Memory Abstraction","배치가 곧 실행 가능성을 결정한다. tier 기준에 capability를 넣을 수 있는지는 DP2의 선택에 달려 있다 — Capability-in-Memory면 tier 속성으로 표현 가능, Capability-in-Binding이면 불가"],
   ["하류","DP3 · 재배치 트리거 (신규)","DP1의 인덱스 축이 DP3의 신호원을 제약한다"],
   ["하류","DP4 · 요청 특성 예측 (신규)","DP4의 예측 정확도가 DP1의 반전 조건을 공급한다"],
  ].forEach(d=>rows.push([
    {text:d[0],options:{bold:true,color:INK,fontSize:9.5}},
    {text:d[1],options:{bold:true,color:C1,fontSize:9.5}},
    {text:d[2],options:{color:BODY,fontSize:9}},
  ]));
  table(s,rows,{y:5.14,colW:[2.30,3.40,6.60],rowH:[0.30,0.30,0.54,0.30,0.30]});
  s.addNotes("DP 간 결합을 명시하는 것이 DP 문서의 가치를 높인다.");
}

/* ---------- 17. 결론 ---------- */
{
  const s=pres.addSlide(); s.background={color:DARK}; PAGE++;
  txt(s,L,1.20,11.5,0.3,"DP1 · CONCLUSION",{fs:12,b:true,c:"8AA4A4",cs:2.5});
  txt(s,L,1.60,11.8,0.55,"결론",{fs:32,b:true,c:"FFFFFF"});
  const items=[
    ["두 후보는 같은 문제를 풀고 서로 다른 잔여를 남긴다","9 : 9 동점의 실체. 선택은 어느 쪽이 나은가가 아니라 어느 잔여를 감당할 수 있는가다"],
    ["Candidate 1 (Tier-Indexed) + 컨텍스트 길이 보강을 선택한다","제약 두 가지가 C1 편이고, C2의 이득은 아직 측정되지 않은 예측 정확도에 전적으로 의존한다"],
    ["포기한 QA1 · QA4는 보강과 로깅으로 부분 회복한다","단일 진실 원천은 여전히 하나이므로 이것은 혼합이 아니라 C1 + 보강이다"],
    ["선택은 데이터로 재검증한다","출력 길이 예측 정확도 · herding 실측 · 워크로드 편향 — 임계값은 미리 고정했다"],
    ["잔여는 DP3 · DP4로 넘긴다","재분류와 요청 특성 예측. DP1의 선택이 두 DP의 후보를 제약한다"],
  ];
  let y=2.50;
  items.forEach((it,i)=>{
    s.addShape(pres.ShapeType.ellipse,{x:L,y:y+0.04,w:0.28,h:0.28,fill:{color:"1E4F4F"},line:{color:"3E5A5A"}});
    txt(s,L,y+0.04,0.28,0.28,String(i+1),{fs:10,b:true,c:"5FBFB0",al:"center",va:"middle"});
    txt(s,L+0.46,y,11.6,0.30,it[0],{fs:14,b:true,c:"FFFFFF"});
    txt(s,L+0.46,y+0.32,11.6,0.28,it[1],{fs:10.5,c:"9BAAB4"});
    y+=0.86;
  });
  s.addNotes("결론은 조건부 선택 + 재검증 계획 + 잔여 인계 세 가지로 닫는다.");
}

pres.writeFile({fileName:"DP1-full.pptx"}).then(f=>console.log("wrote "+f));
