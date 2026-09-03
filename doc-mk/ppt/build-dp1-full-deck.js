const pptxgen=require("pptxgenjs");
const INK="1F2933",BODY="3E4C59",MUTED="7B8794",RULE="DCE1E7",BG="FFFFFF",DARK="16202B";
const C1="0B6E6E",C2="B0503F",C1S="E8F2F1",C2S="F8EBE7",PANEL="F5F7F8",WARN="B7791F";
const F="Arial";
const pres=new pptxgen(); pres.layout="LAYOUT_WIDE";
pres.title="DP1 — Memory Placement Decision Basis";
const L=0.5,R=12.8,W=13.3,H=7.5;
const AX=0.5,BX=6.85,CW=5.95;
let PAGE=0; const TOTAL=17;

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
    ["최종 선택","Candidate 1 (Tier-Indexed) + 컨텍스트 길이 보강. C2의 이득이 미측정 예측 정확도에 전적으로 의존하기 때문"],
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

/* ---------- 3. 배경 ---------- */
{
  const s=slide("DP1 · 1장 배경","현재 vLLM v1은 \"메모리는 한 종류\"라는 전제 위에 있다");
  card(s,L,1.42,6.0,2.30,PANEL,RULE);
  txt(s,L+0.18,1.54,5.6,0.24,"할당 인터페이스는 크기만 받는다",{fs:10,b:true,c:MUTED});
  txt(s,L+0.18,1.84,5.65,1.80,
    "def allocate_slots(\n    self, request: Request,\n    num_new_tokens: int, ...\n) -> KVCacheBlocks | None: ...\n\ndef get_new_blocks(num_blocks: int) -> list[KVCacheBlock]\ndef get_num_free_blocks() -> int   # 정수 1개",
    {fs:9.5,c:INK,ls:1.22});
  card(s,6.75,1.42,6.05,2.30,PANEL,RULE);
  txt(s,6.93,1.54,5.7,0.24,"블록에도 위치 개념이 없다",{fs:10,b:true,c:MUTED});
  txt(s,6.93,1.84,5.7,1.80,
    "@dataclass(slots=True)\nclass KVCacheBlock:\n    block_id: int        # 텐서 인덱스일 뿐\n    ref_cnt: int = 0\n    _block_hash / prev_free / next_free / is_null\n\n→ 6개 필드 중 위치·연산 능력을 나타내는 것 0개",
    {fs:9.5,c:INK,ls:1.22});
  card(s,L,3.92,R-L,0.86,C1S,C1);
  txt(s,L+0.20,3.92,R-L-0.4,0.86,
    "현재 구조의 전제:  \"메모리는 한 종류이고, 부족하면 배치가 아니라 스케줄(preempt)로 해결한다\"",
    {fs:14,b:true,c:C1,va:"middle"});
  txt(s,L,5.00,R-L,0.26,"기존 CPU offload(vllm/v1/kv_offload)도 이 전제를 깨지 않는다",{fs:11,b:true,c:INK});
  bullets(s,L,5.32,R-L,1.20,[
    "LoadStoreSpec · OffloadingManager — 이름이 말하듯 배치(placement)가 아니라 사후 이동(load/store) 모델이다",
    "정책도 policies/lru.py · arc.py 처럼 이미 발생한 접근 이력 기반 — \"새 메모리를 어디에 잡을 것인가\"를 정하는 자리가 아니다",
    "즉 지금까지는 \"얼마나\"만 알면 충분했다",
  ],10.5);
  s.addNotes("배경은 사실만. 여기서 문제를 말하지 않는다.");
}

/* ---------- 4. 변화와 문제 ---------- */
{
  const s=slide("DP1 · 1장 변화와 문제","6단 이기종 메모리가 들어오면 전제가 깨진다");
  // 좌: 런타임 스택
  txt(s,L,1.36,5.4,0.24,"문제가 발생하는 런타임 스택 위치",{fs:10,b:true,c:MUTED});
  const layers=["API / Entrypoint","Engine · Scheduler","Executor / Worker","ModelRunner","Attention / Kernel","Memory · BlockPool","HW Abstraction"];
  const lx=L, lw=4.05, lh=0.44, gap=0.11;
  layers.forEach((t,i)=>{
    const y=1.66+i*(lh+gap);
    const hot=(i===1||i===5);
    card(s,lx,y,lw,lh,hot?C1S:"FFFFFF",hot?C1:RULE);
    txt(s,lx,y,lw,lh,t,{fs:9.5,b:hot,c:hot?C1:BODY,al:"center",va:"middle"});
  });
  // 경계 브래킷
  const y1=1.66+1*(lh+gap)+lh, y2=1.66+5*(lh+gap);
  s.addShape(pres.ShapeType.line,{x:lx+lw+0.12,y:y1,w:0,h:y2-y1,line:{color:WARN,width:2}});
  txt(s,lx+lw+0.22,(y1+y2)/2-0.22,1.35,0.44,"할당 경계\n(문제 지점)",{fs:9,b:true,c:WARN,va:"middle",ls:1.1});
  // 우
  txt(s,6.15,1.36,6.65,0.24,"변화",{fs:10,b:true,c:MUTED});
  bullets(s,6.15,1.64,6.65,0.86,[
    "GPU HBM / CPU DRAM / CXL / Custom HBM / SSD / HBF — tier마다 대역폭·지연·용량이 자릿수 단위로 다르다",
    "할당이 두 질문으로 쪼개진다: \"얼마나\"(스케줄러) 와 \"어디에\"(런타임)",
  ],10.5);
  card(s,6.15,2.62,6.65,0.90,"FDF6E7",WARN);
  txt(s,6.33,2.62,6.3,0.90,
    "문제 — 위치를 정할 기준을 담을 자리가 없어 tier 선택이 호출 지점의 조건문으로 흩어지고, 결정 근거가 어디에도 남지 않는다",
    {fs:12,b:true,c:INK,va:"middle",ls:1.2});
  txt(s,6.15,3.66,6.65,0.24,"QA 영향 (As-Is)",{fs:10,b:true,c:MUTED});
  const qrows=[
    ["QA1 배치 품질","구분 가능한 객체 등급 1종 — 상위 tier 점유가 도착 순서로 결정"],
    ["QA2 정보 비용","관측 지표 1개(get_num_free_blocks) → 6-tier면 최소 24개, 갱신 주기 미정의"],
    ["QA3 적응성","오배치 개념 자체가 없다 — 배치를 되돌리는 진입점이 없다"],
    ["QA4 재현성","결정 근거 미기록 — 회귀 원인을 6^k 배치 조합에서 사후 추정해야 한다"],
  ];
  let y=3.94;
  qrows.forEach(r=>{ card(s,6.15,y,6.65,0.62,"FFFFFF",RULE);
    txt(s,6.31,y,1.55,0.62,r[0],{fs:9.5,b:true,c:INK,va:"middle"});
    txt(s,7.90,y,4.75,0.62,r[1],{fs:9,c:BODY,va:"middle",ls:1.1}); y+=0.70;});
  s.addNotes("레이어를 정확히 지목해야 설계 범위가 확정된다. Scheduler와 BlockPool 사이의 할당 경계.");
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
    ["QA1. 이기종 환경 배치 품질","★★☆","★★★","구분 가능 등급 1종 vs 8종. C1은 상위 tier 점유가 도착 순서로 결정됨 (컴포넌트)"],
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
    "그리고 C2가 QA1에서 얻는 이득은 출력 길이·재사용 예측 정확도에 전적으로 의존하는데, 그 값이 아직 측정되지 않았다. 미측정 상태에서 C2를 고르면 QA2 비용과 QA3 고착은 확실히 지불하고 QA1 이득은 불확실하다.",
    {fs:10.5,c:INK,ls:1.28});
  txt(s,L,2.94,6.0,0.26,"포기한 축과 완화책",{fs:10.5,b:true,c:MUTED});
  const mit=[
    ["QA1 구분 능력","관측 가능한 특성 중 컨텍스트 길이를 TierState.score()의 한 항으로 넣는다","스텝당 대역폭 요구는 구분 가능. 읽기 빈도(미래 정보)는 여전히 불가"],
    ["QA4 재현성","배치 결정 시 tier score 스냅샷을 결정 로그로 남긴다 (24개 값 → 요약 스칼라 3~4개)","재현은 불가하나 사후 설명은 가능해진다"],
  ];
  let y=3.24;
  mit.forEach(m=>{ card(s,L,y,6.0,1.10,"FFFFFF",RULE);
    txt(s,L+0.18,y+0.10,5.64,0.26,m[0],{fs:11,b:true,c:INK});
    txt(s,L+0.18,y+0.38,5.64,0.36,m[1],{fs:9.5,c:BODY,ls:1.15});
    txt(s,L+0.18,y+0.78,5.64,0.26,"→ "+m[2],{fs:9,c:C1});
    y+=1.22;});
  txt(s,6.80,2.94,6.0,0.26,"혼합 판정 — 이것은 혼합이 아니라 \"C1 + 보강\"이다",{fs:10.5,b:true,c:MUTED});
  card(s,6.80,3.24,6.0,2.32,PANEL,C1);
  txt(s,6.98,3.38,5.64,0.30,"판정 질문: 단일 진실 원천이 여전히 하나인가?",{fs:11,b:true,c:C1});
  bullets(s,6.98,3.76,5.64,1.66,[
    "그렇다 — 단일 진실 원천은 여전히 TierStateTable 하나다",
    "객체 정보(컨텍스트 길이)는 정책의 인덱스가 아니라 score의 한 항(가중치)으로만 들어간다",
    "경합 시 불변식은 그대로 \"자원 제약 우선\"이다",
    "인덱스 축이 바뀌지 않았으므로 3.3장의 배타성 논증은 그대로 유효하다",
  ],9.5);
  card(s,L,5.72,R-L,0.90,"FDF6E7",WARN);
  txt(s,L+0.22,5.72,R-L-0.44,0.90,
    "혼합을 최종안으로 삼는다면 \"왜 처음부터 후보가 아니었는가\"에 답해야 한다. 여기서는 진짜 혼합이 아니므로 그 부담이 없다 — 정직하게 \"C1 선택 + 보강\"으로 부른다.",
    {fs:11,b:true,c:INK,va:"middle"});
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
  ];
  const rows=[[hdr("측정 대상"),hdr("측정 방법"),hdr("판정 임계값")]];
  data.forEach(d=>rows.push([
    {text:d[0],options:{bold:true,color:INK,fontSize:10}},
    {text:d[1],options:{color:BODY,fontSize:9.5}},
    {text:d[2],options:{color:C1,bold:true,fontSize:9.5}},
  ]));
  table(s,rows,{y:1.72,colW:[3.10,5.10,4.10],rowH:[0.38,0.92,0.92,0.92]});
  txt(s,L,4.98,R-L,0.28,"반전 조건 — 다음 중 하나가 성립하면 이 선택은 뒤집힌다",{fs:11,b:true,c:MUTED});
  const rev=[
    ["1","출력 길이 예측 정확도가 위 임계값을 넘는다","C2의 QA1 이득이 확실해진다"],
    ["2","배치 재현성이 SLA · 과금 근거로 요구된다","QA4가 수용 불가 축이 된다"],
    ["3","한 메모리에 여러 실행 리소스가 붙는 토폴로지가 확정된다","객체별 목표 지정이 필요해진다"],
  ];
  const cw=(R-L-2*0.26)/3; 
  rev.forEach((r,i)=>{ const x=L+i*(cw+0.26);
    card(s,x,5.32,cw,1.32,"FFFFFF",C2);
    s.addShape(pres.ShapeType.ellipse,{x:x+0.18,y:5.46,w:0.24,h:0.24,fill:{color:C2},line:{color:C2}});
    txt(s,x+0.18,5.46,0.24,0.24,r[0],{fs:9,b:true,c:"FFFFFF",al:"center",va:"middle"});
    txt(s,x+0.52,5.44,cw-0.70,0.50,r[1],{fs:10,b:true,c:INK,ls:1.15});
    txt(s,x+0.52,6.02,cw-0.70,0.46,"→ "+r[2],{fs:9,c:C2,ls:1.15});
  });
  s.addNotes("선택하지 않은 후보는 폐기가 아니라 조건부 재검토 대상.");
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
