const pptxgen = require("pptxgenjs");

const INK="1F2933", BODY="3E4C59", MUTED="7B8794", RULE="DCE1E7", BG="FFFFFF", DARK="16202B";
const C1="0B6E6E", C2="B0503F", C1S="E8F2F1", C2S="F8EBE7", PANEL="F7F9FA";
const F="Arial";

const pres=new pptxgen();
pres.layout="LAYOUT_WIDE";
pres.title="DP1 Candidate Structure — Detailed Diagrams";

const L=0.5, R=12.8;
const AX=0.5, BX=6.85, CW=5.95;          // 두 후보 열
const DY=1.92, DH=3.30;                   // 다이어그램 영역
const EY=5.42, EH=1.60;                   // 설명 영역

/* ---------- 공통 요소 ---------- */
function head(s,kicker,title){
  s.addText(kicker,{x:L,y:0.32,w:9,h:0.24,isTextBox:true,margin:0,
    fontFace:F,fontSize:11,bold:true,color:MUTED,charSpacing:1.5});
  s.addText(title,{x:L,y:0.58,w:12.3,h:0.44,isTextBox:true,margin:0,
    fontFace:F,fontSize:22,bold:true,color:INK});
}
function colHead(s,x,accent,name,sub){
  s.addShape(pres.ShapeType.roundRect,{x:x,y:1.22,w:0.20,h:0.20,rectRadius:0.10,
    fill:{color:accent},line:{color:accent}});
  s.addText(name,{x:x+0.30,y:1.16,w:CW-0.35,h:0.30,isTextBox:true,margin:0,
    fontFace:F,fontSize:14,bold:true,color:accent});
  s.addText(sub,{x:x,y:1.48,w:CW,h:0.26,isTextBox:true,margin:0,
    fontFace:F,fontSize:9.5,color:MUTED});
}
function panel(s,x,accent){
  s.addShape(pres.ShapeType.roundRect,{x:x,y:DY,w:CW,h:DH,rectRadius:0.05,
    fill:{color:PANEL},line:{color:RULE,width:0.75}});
}
function box(s,x,y,w,h,accent,soft,text,fs){
  s.addShape(pres.ShapeType.roundRect,{x:x,y:y,w:w,h:h,rectRadius:0.05,
    fill:{color:soft},line:{color:accent,width:1}});
  s.addText(text,{x:x,y:y,w:w,h:h,isTextBox:true,margin:0.03,
    fontFace:F,fontSize:fs||9,bold:true,color:INK,align:"center",valign:"middle",
    lineSpacingMultiple:1.05});
}
function plainbox(s,x,y,w,h,text,fs){
  s.addShape(pres.ShapeType.roundRect,{x:x,y:y,w:w,h:h,rectRadius:0.05,
    fill:{color:"FFFFFF"},line:{color:MUTED,width:0.75}});
  s.addText(text,{x:x,y:y,w:w,h:h,isTextBox:true,margin:0.03,
    fontFace:F,fontSize:fs||9,color:BODY,align:"center",valign:"middle",
    lineSpacingMultiple:1.05});
}
function arrow(s,x1,y1,x2,y2,color,dashed){
  const o={x:Math.min(x1,x2),y:Math.min(y1,y2),w:Math.abs(x2-x1),h:Math.abs(y2-y1),
    line:{color:color||MUTED,width:1,endArrowType:"triangle"}};
  if(dashed) o.line.dashType="dash";
  o.flipH = x2<x1; o.flipV = y2<y1;
  s.addShape(pres.ShapeType.line,o);
}
function label(s,x,y,w,t,color,fs){
  s.addText(t,{x:x,y:y,w:w,h:0.20,isTextBox:true,margin:0,
    fontFace:F,fontSize:fs||7.5,color:color||BODY,align:"center",valign:"middle"});
}
function notesCol(s,x,accent,items,qa){
  const runs=items.map((t,i)=>({text:t,options:{bullet:{code:"2022"},breakLine:true}}));
  s.addText(runs,{x:x,y:EY,w:CW,h:EH-0.42,isTextBox:true,margin:0,
    fontFace:F,fontSize:9.5,color:BODY,paraSpaceAfter:5,lineSpacingMultiple:1.1,valign:"top"});
  s.addText(qa,{x:x,y:EY+EH-0.40,w:CW,h:0.32,isTextBox:true,margin:0,
    fontFace:F,fontSize:9.5,bold:true,color:accent,valign:"middle"});
}
function newSlide(kicker,title,subA,subB){
  const s=pres.addSlide(); s.background={color:BG};
  head(s,kicker,title);
  colHead(s,AX,C1,"Candidate 1 — Tier-Indexed",subA);
  colHead(s,BX,C2,"Candidate 2 — Object-Indexed",subB);
  panel(s,AX,C1); panel(s,BX,C2);
  return s;
}

/* ===== 해설 페이지 공통 렌더러 (gen_dp1.js에 주입) ===== */
function estW(t,pt){let w=0;for(const c of t){const o=c.codePointAt(0);
  const wide=(o>=0x1100&&o<=0x11FF)||(o>=0x2460&&o<=0x24FF)||(o>=0x3000&&o<=0x9FFF)||(o>=0xAC00&&o<=0xD7AF)||(o>=0xFF00&&o<=0xFF60)||o===0x26A0;
  w += wide?pt : (c===' '?pt*0.28:pt*0.52);} return w/72;}

const QY=1.14, QH=0.66;      // 질문 밴드
const IY=2.22, IH=3.52;      // 항목 영역
const MY=5.94, MH=0.98;      // 숫자 밴드

function qBand(s,q,how){
  s.addShape(pres.ShapeType.roundRect,{x:L,y:QY,w:R-L,h:QH,rectRadius:0.05,
    fill:{color:"F2F5F6"},line:{color:RULE,width:0.75}});
  s.addText([{text:"이 그림이 답하는 질문   ",options:{bold:true,color:MUTED,fontSize:9}},
             {text:q,options:{bold:true,color:INK,fontSize:11}}],
    {x:L+0.18,y:QY+0.05,w:R-L-0.36,h:0.30,isTextBox:true,margin:0,fontFace:F,valign:"middle"});
  s.addText([{text:"읽는 법   ",options:{bold:true,color:MUTED,fontSize:9}},
             {text:how,options:{color:BODY,fontSize:9.5}}],
    {x:L+0.18,y:QY+0.33,w:R-L-0.36,h:0.28,isTextBox:true,margin:0,fontFace:F,valign:"middle"});
}
function itemList(s,x,accent,list){
  let y=IY;
  list.forEach((it,i)=>{
    const tw=CW-0.40;
    const lines=Math.max(1,Math.ceil(estW(it,9.5)/(tw*0.95)));   // 경계값은 보수적으로 2줄 확보
    const h=lines*0.165+0.06;
    s.addShape(pres.ShapeType.ellipse,{x:x,y:y+0.02,w:0.22,h:0.22,
      fill:{color:accent},line:{color:accent}});
    s.addText(String(i+1),{x:x,y:y+0.02,w:0.22,h:0.22,isTextBox:true,margin:0,
      fontFace:F,fontSize:8,bold:true,color:"FFFFFF",align:"center",valign:"middle"});
    s.addText(it,{x:x+0.32,y:y,w:tw,h:h,isTextBox:true,margin:0,
      fontFace:F,fontSize:9.5,color:BODY,lineSpacingMultiple:1.12,valign:"top"});
    y+=h+0.13;
  });
  return y;
}
function metricBand(s,cards){
  const n=cards.length, gap=0.30, w=(R-L-gap*(n-1))/n;
  s.addText("이 그림이 만들어내는 숫자",{x:L,y:MY-0.28,w:5,h:0.22,isTextBox:true,margin:0,
    fontFace:F,fontSize:9,bold:true,color:MUTED,charSpacing:0.8});
  cards.forEach((c,i)=>{
    const cx=L+i*(w+gap);
    s.addShape(pres.ShapeType.roundRect,{x:cx,y:MY,w:w,h:MH,rectRadius:0.05,
      fill:{color:"FFFFFF"},line:{color:RULE,width:0.75}});
    s.addText(c[0],{x:cx+0.16,y:MY+0.08,w:w-0.32,h:0.26,isTextBox:true,margin:0,
      fontFace:F,fontSize:9,color:MUTED,valign:"middle"});
    s.addText([{text:c[1],options:{bold:true,color:C1,fontSize:13}},
               {text:"   vs   ",options:{color:MUTED,fontSize:9}},
               {text:c[2],options:{bold:true,color:C2,fontSize:13}}],
      {x:cx+0.16,y:MY+0.36,w:w-0.32,h:0.52,isTextBox:true,margin:0,fontFace:F,valign:"middle"});
  });
}
function explainSlide(cfg){
  const s=pres.addSlide(); s.background={color:BG};
  head(s,cfg.kicker,cfg.title);
  qBand(s,cfg.q,cfg.how);
  s.addShape(pres.ShapeType.roundRect,{x:AX,y:1.84,w:0.18,h:0.18,rectRadius:0.09,
    fill:{color:C1},line:{color:C1}});
  s.addText("Candidate 1 — Tier-Indexed",{x:AX+0.28,y:1.80,w:CW-0.3,h:0.26,isTextBox:true,margin:0,
    fontFace:F,fontSize:12,bold:true,color:C1});
  s.addShape(pres.ShapeType.roundRect,{x:BX,y:1.84,w:0.18,h:0.18,rectRadius:0.09,
    fill:{color:C2},line:{color:C2}});
  s.addText("Candidate 2 — Object-Indexed",{x:BX+0.28,y:1.80,w:CW-0.3,h:0.26,isTextBox:true,margin:0,
    fontFace:F,fontSize:12,bold:true,color:C2});
  itemList(s,AX,C1,cfg.a);
  itemList(s,BX,C2,cfg.b);
  metricBand(s,cfg.metrics);
  s.addNotes(cfg.notes);
  return s;
}

/* ===== 각 뷰 해설 페이지 내용 ===== */
const EXPLAIN = {
module:{
  kicker:"DP1 · 백데이터 ① 해설", title:"모듈 뷰 해설 — 그림을 요소별로 풀어보면",
  q:"코드가 어느 모듈에 살고, 의존이 어디로 향하는가?",
  how:"화살표는 의존·호출 방향이다. 좌측 세로 스택(Scheduler→Placer→BlockPool→HW)은 두 후보가 동일하므로, 오른쪽에 무엇이 붙는지만 비교하면 된다.",
  a:[
    "Scheduler — \"블록 몇 개가 필요하다\"만 전달한다. tier를 지정하지 않는다.",
    "Placer — 배치를 결정하는 유일한 지점. 결정 입력을 TierStateTable 한 곳에서만 얻는다.",
    "TierStateTable — 어느 tier에 얼마나 여유가 있는가에 대한 단일 진실 원천. 스케줄 스텝마다 갱신된다.",
    "Metrics / Device probes — 이 표를 채우는 유일한 소스. 시스템 내부 계측이라 새 파이프라인이 필요 없다.",
    "BlockPool / HW tiers — 결정된 tier의 풀에서 실제 블록을 꺼낸다. 여기에는 결정 로직이 없다.",
    "Request 타입에 대한 의존이 어디에도 없다 — 스케줄러 쪽 타입이 바뀌어도 배치 모듈로 전파되지 않는다.",
  ],
  b:[
    "Scheduler / Placer — 위치는 같지만 Placer가 request를 함께 받는다. 여기서부터 갈린다.",
    "ObjectClassifier — 요청을 등급으로 바꾸는 모듈. C1에는 없던 것이다.",
    "Feature source — hotness·lifetime을 채우는 외부 소스(힌트 API · 휴리스틱 · 과거 통계). 시스템 밖에서 정보를 들여오는 새 파이프라인이다.",
    "Class-Tier Contract — 등급에서 목표 tier로 가는 매핑. 정책이 사는 자리가 여기다.",
    "Evictor — 계약을 지키려면 자리를 만들어야 하므로 Placer가 호출 권한을 갖는다.",
    "그 결과 배치 모듈이 eviction 정책과 결합된다 — C1에는 없는 의존이다.",
  ],
  metrics:[["신규 모듈 수","2개","4개"],["외부 정보 소스","0개","1개 (Feature source)"],["Placer가 의존하는 모듈","1개","3개"]],
  notes:"핵심은 좌측 스택이 동일하다는 점. 차이는 오른쪽에 붙는 모듈 수와 그중 하나가 시스템 외부 소스라는 것.",
},
component:{
  kicker:"DP1 · 백데이터 ② 해설", title:"컴포넌트 & 커넥터 해설 — 화살표가 모이는가 흩어지는가",
  q:"런타임에 무엇이 몇 개 존재하고, 같은 스텝의 요청들이 어디로 가는가?",
  how:"왼쪽은 같은 스텝에 도착한 요청 2건, 가운데는 결정 주체와 그 결정이 참조하는 상태, 오른쪽은 tier다. 화살표가 한 곳으로 모이는지 갈라지는지가 이 그림의 전부다.",
  a:[
    "요청 A·B가 익명이다 — 크기 말고는 둘을 구별할 정보가 그림 어디에도 없다.",
    "Placer가 참조하는 것은 24개 지표 1벌. 요청이 몇 개든 이 상태는 하나뿐이다.",
    "그래서 A와 B는 같은 점수표를 보고 같은 답을 낸다 → 화살표 두 개가 HBM 하나로 수렴한다.",
    "이것이 herding이다. 스텝 경계에서만 상태를 갱신하면 그 스텝의 모든 할당이 한 tier로 몰린다.",
    "max_num_seqs=128 기준 스텝당 수십~수백 건이 동시에 몰릴 수 있다.",
    "해결하려면 스텝 내 예약 카운터가 필요하다 — 구현 부담이지 구조 변경은 아니다.",
  ],
  b:[
    "요청마다 등급이 붙는다 — A는 hot · short, B는 cold · long.",
    "Placer가 참조하는 것은 등급에서 tier로 가는 계약(이진 3특성 기준 8개 클래스).",
    "등급이 다르면 답도 다르다 → 화살표가 HBM과 SSD로 갈라진다.",
    "같은 스텝이 자연히 분산되므로 herding이 발생하지 않는다 — C1의 실패 모드가 구조적으로 없다.",
    "대신 유지할 상태가 요청 수에 비례한다(요청당 특성 벡터 1개).",
    "목표 tier가 차 있으면 계약을 지키기 위해 eviction이 발생한다 — 점선 커넥터가 그것이다.",
  ],
  metrics:[["유지 상태","24개 고정","요청 수에 비례"],["구분 가능한 등급","1종 (익명)","8종"],["스텝 내 herding","있음","없음"]],
  notes:"C1의 약점(수렴)과 C2의 강점(분산)이 같은 프레임에서 대비되도록 그린 슬라이드.",
},
sequence:{
  kicker:"DP1 · 백데이터 ③ 해설", title:"시퀀스 해설 — 화살표 하나가 곧 control path 한 단계",
  q:"할당 1건이 실제 블록을 받기까지 몇 단계를 거치는가?",
  how:"세로 점선은 참여자, 가로 화살표는 메시지다. 실선은 호출, 점선은 반환. 두 후보는 반드시 같은 시나리오(블록 4개 신규 할당)를 그려야 개수 비교가 성립한다.",
  a:[
    "allocate(4) — Scheduler는 개수만 준다. 인자에 request가 없다.",
    "read states(6) — 6개 tier 상태를 한 번 읽는다. 전역 상태 조회는 이 1회뿐이다.",
    "scores 반환 — 이미 측정되어 있는 값이라 추정 단계가 없다.",
    "get_blocks(4) — 선택된 tier의 풀에서 블록을 꺼낸다.",
    "blocks 반환 — 총 5개 메시지로 끝난다.",
    "요청 식별자가 이 경로 어디에도 등장하지 않는다. 이것이 익명 요청의 실체다.",
  ],
  b:[
    "allocate(4, request) — request가 인자에 들어온다. 갈림길이 여기다.",
    "classify(req) → class 반환 — 분류는 객체당 최초 1회이므로 반복 비용 자체는 낮다.",
    "target_tier() → 목표 tier 반환 — 계약을 조회하는 정책 단계.",
    "get_blocks(4) → blocks 반환 — 여기까지 총 7개 메시지.",
    "tier full이면 Evictor.make_room() 2단계가 임계 경로에 추가되어 9개가 된다.",
    "분류 결과는 수명 동안 재사용되지만, 그 첫 결정이 틀리면 교정 없이 고착된다.",
  ],
  metrics:[["dispatch 메시지 수","5개","7개 (경합 시 9개)"],["추정이 필요한 단계","0개","1개 (classify)"],["경로에 요청 식별자","등장 안 함","등장함"]],
  notes:"메시지 수 차이(5 vs 7)가 QA1의 정량 근거, 추정 단계 유무가 QA2, 첫 결정 고착이 QA3의 근거.",
},
klass:{
  kicker:"DP1 · 백데이터 ④ 해설", title:"클래스 해설 — 시그니처와 필드가 곧 제약이다",
  q:"새 tier나 새 객체 유형을 추가할 때 어디를 수정하는가?",
  how:"색 헤더는 그 후보가 새로 도입하는 타입이다. 필드 목록은 곧 '결정에 필요한 정보'이고, 메서드 시그니처는 '무엇을 알 수 있는가'를 강제한다.",
  a:[
    "place(num_blocks) — 인자에 request가 없다. 시그니처가 익명성을 구조적으로 강제한다.",
    "TierState의 필드 4개는 전부 런타임에 측정 가능한 값이다 — 추정할 것이 없다.",
    "정책은 score() 하나에 응축된다. 배치 규칙을 바꾸려면 이 메서드만 보면 된다.",
    "새 tier 추가는 이 표에 행 하나를 더하는 일이고, 정책 함수는 그대로다(argmax의 정의역만 넓어진다).",
    "BlockPool은 결정에 관여하지 않는다 — 꺼내는 역할만 한다.",
    "나중에 객체 정보를 쓰려면 place() 시그니처부터 바꿔야 한다. C2로 옮기는 비용에 인터페이스 변경이 포함된다.",
  ],
  b:[
    "place(num_blocks, request) — request가 시그니처에 들어와 스케줄러 타입과 결합된다.",
    "ObjectFeature의 세 필드(hotness · locality · lifetime)는 할당 시점에 측정할 수 없다 — ⚠를 붙인 이유다.",
    "값을 채우려면 힌트 API(인터페이스 오염) · 휴리스틱(정확도 미보장) · 과거 통계(콜드스타트) 중 하나를 골라야 한다.",
    "ClassTierContract가 정책이 사는 자리다. target_tier와 fallback_order를 함께 갖는다.",
    "새 tier를 넣으면 8개 클래스 전부에 대해 계약을 다시 써야 한다 — 행 추가로 끝나지 않는다.",
    "대신 결정 근거가 ObjectClass라는 값으로 남아 로깅 · 재현 · 단위 테스트가 가능하다.",
  ],
  metrics:[["결정에 쓰는 필드","4개 (전부 관측 가능)","3개 (전부 관측 불가)"],["새 tier 추가 비용","테이블 행 1개","계약 8개 재정의"],["클래스 수","3개","4개"]],
  notes:"⚠ 표시한 ObjectFeature 세 필드가 C2 비용의 본질. 관측 불가 지표 비율 0% vs 100%가 여기서 나온다.",
},
};


/* ================= 1. 표지 ================= */
{
  const s=pres.addSlide(); s.background={color:DARK};
  s.addText("DP1 · MEMORY PLACEMENT DECISION BASIS",{x:L,y:2.05,w:11,h:0.3,isTextBox:true,margin:0,
    fontFace:F,fontSize:12,bold:true,color:"8AA4A4",charSpacing:2.5});
  s.addText("후보 구조 상세 다이어그램",{x:L,y:2.52,w:11,h:0.8,isTextBox:true,margin:0,
    fontFace:F,fontSize:38,bold:true,color:"FFFFFF"});
  s.addText("설계 결정 변수: 배치 정책의 인덱스 축을 자원(tier)에 둘 것인가, 객체 특성에 둘 것인가",
    {x:L,y:3.40,w:11.5,h:0.34,isTextBox:true,margin:0,fontFace:F,fontSize:13,color:"9BAAB4"});
  s.addText("각 뷰는 그림 1장 + 해설 1장으로 구성된다",{x:L,y:3.76,w:11.5,h:0.28,isTextBox:true,margin:0,
    fontFace:F,fontSize:11,bold:true,color:"5FBFB0"});
  const rows=[
    ["모듈 뷰","코드가 어디에 살고 의존이 어디로 향하는가","QA2 · QA4"],
    ["컴포넌트 & 커넥터","런타임 인스턴스와 통신 경로, 표현 가능한 관계","QA1 · QA3"],
    ["시퀀스","할당 1건이 배치에 도달하기까지의 단계 수","QA1 · QA2 · QA3"],
    ["클래스","확장 시 수정해야 하는 지점","QA2 · QA4"],
  ];
  rows.forEach((r,i)=>{
    const y=4.28+i*0.62;
    s.addText(r[0],{x:L,y:y,w:2.5,h:0.3,isTextBox:true,margin:0,
      fontFace:F,fontSize:13,bold:true,color:"FFFFFF"});
    s.addText(r[1],{x:L+2.6,y:y,w:6.6,h:0.3,isTextBox:true,margin:0,
      fontFace:F,fontSize:11,color:"9BAAB4"});
    s.addText(r[2],{x:L+9.4,y:y,w:2.6,h:0.3,isTextBox:true,margin:0,
      fontFace:F,fontSize:11,bold:true,color:"5FBFB0"});
  });
  s.addNotes("각 다이어그램은 트레이드오프 별점의 정량 근거를 생산하는 도구다. 오른쪽 열이 그 다이어그램이 뒷받침하는 QA.");
}

/* ================= 2. 모듈 뷰 ================= */
{
  const s=newSlide("DP1 · 백데이터 ①","모듈 뷰 — 코드가 어디에 살고 의존이 어디로 향하는가",
    "신규 모듈 2개 · 갱신 소스 1곳","신규 모듈 4개 · 외부 특성 소스 추가");
  // 공통 좌측 스택 (동일 시각 문법)
  const stack=["Scheduler","Placer","BlockPool (tier별)","HW tiers"];
  [[AX,C1,C1S],[BX,C2,C2S]].forEach(([x,ac,sf])=>{
    const sx=x+0.22, sw=2.55, bh=0.56, gap=0.30;
    stack.forEach((t,i)=>{
      const by=DY+0.22+i*(bh+gap);
      if(i===1) box(s,sx,by,sw,bh,ac,sf,t,9.5); else plainbox(s,sx,by,sw,bh,t,9.5);
      if(i<stack.length-1) arrow(s,sx+sw/2,by+bh,sx+sw/2,by+bh+gap,MUTED);
    });
  });
  // C1 우측: TierStateTable ← Metrics
  {
    const rx=AX+3.05, rw=2.65, bh=0.56;
    box(s,rx,DY+0.22+1*(0.56+0.30),rw,bh,C1,C1S,"TierStateTable\n용량·대역폭·지연·이동비용",8);
    plainbox(s,rx,DY+0.22+2*(0.56+0.30),rw,bh,"Metrics / Device probes",9);
    arrow(s,rx+rw/2,DY+0.22+2*(0.86),rx+rw/2,DY+0.22+0.86+0.56,C1,false); // probes → table (위로)
    arrow(s,AX+0.22+2.55,DY+0.22+0.86+0.28,rx,DY+0.22+0.86+0.28,C1);       // placer → table
  }
  // C2 우측: Classifier / Contract / Evictor + Feature source
  {
    const rx=BX+3.05, rw=2.65, bh=0.50, gy=DY+0.18, gp=0.22;
    const items=[["ObjectClassifier",true],["Feature source\n힌트 API · 휴리스틱 · 통계",false],
                 ["Class-Tier Contract",true],["Evictor (자리 확보)",false]];
    items.forEach((it,i)=>{
      const by=gy+i*(bh+gp);
      if(it[1]) box(s,rx,by,rw,bh,C2,C2S,it[0],8.5); else plainbox(s,rx,by,rw,bh,it[0],8);
      if(i===0) arrow(s,rx+rw/2,gy+bh,rx+rw/2,gy+bh+gp,C2,true);
    });
    arrow(s,BX+0.22+2.55,DY+0.22+0.86+0.28,rx,gy+bh/2,C2);
    arrow(s,BX+0.22+2.55,DY+0.22+0.86+0.28,rx,gy+2*(bh+gp)+bh/2,C2);
    arrow(s,BX+0.22+2.55,DY+0.22+0.86+0.28,rx,gy+3*(bh+gp)+bh/2,C2);
  }
  notesCol(s,AX,C1,[
    "의존이 한 방향 — Scheduler → Placer → BlockPool",
    "capability를 아는 모듈은 TierStateTable 하나, 갱신 소스도 디바이스 계측 하나",
    "Request 타입에 대한 의존이 없어 스케줄러와의 결합이 얇다",
  ],"→ QA2 근거: 갱신 소스가 자원 쪽 하나로 국한된다");
  notesCol(s,BX,C2,[
    "Placer · Classifier · Contract · Evictor 연동으로 신규 모듈 4개",
    "Feature source는 시스템 밖에서 정보를 들여오는 새 파이프라인",
    "계약 준수를 위해 Placer가 Evictor 호출 권한을 가짐 → eviction 정책과 결합",
  ],"→ QA2 · QA4 근거: 정보 소스가 늘고, 결정 근거는 객체에 남는다");
  s.addNotes("좌측 스택(Scheduler→Placer→BlockPool→HW)은 두 후보가 동일하다. 차이는 오른쪽에 무엇이 붙는가뿐이며, 그것이 곧 결정 변수의 차이다.");
}
explainSlide(EXPLAIN.module);

/* ================= 3. 컴포넌트 & 커넥터 ================= */
{
  const s=newSlide("DP1 · 백데이터 ②","컴포넌트 & 커넥터 — 런타임에 무엇이 몇 개 존재하고 어떻게 연결되는가",
    "상태 24개 1벌 · 요청 수와 무관","특성 벡터 요청당 1개 · 8개 클래스");
  const reqW=1.45, plW=1.75, tW=1.45;
  [[AX,C1,C1S,true],[BX,C2,C2S,false]].forEach(([x,ac,sf,anon])=>{
    const rx=x+0.18, px=rx+reqW+0.48, tx=px+plW+0.48;
    const r1=DY+0.55, r2=DY+1.35;
    if(anon){
      plainbox(s,rx,r1,reqW,0.52,"할당 요청 A\n(익명)",8.5);
      plainbox(s,rx,r2,reqW,0.52,"할당 요청 B\n(익명)",8.5);
    }else{
      box(s,rx,r1,reqW,0.52,C2,C2S,"객체 A\nhot · short",8.5);
      plainbox(s,rx,r2,reqW,0.52,"객체 B\ncold · long",8.5);
    }
    box(s,px,DY+0.95,plW,0.60,ac,sf,"Placer",10);
    plainbox(s,px,DY+1.75,plW,0.62, anon?"Tier State\n24개 지표 1벌":"Class → Tier 계약\n8개 클래스",8);
    arrow(s,px+plW/2,DY+1.75,px+plW/2,DY+1.55,ac,true);
    arrow(s,rx+reqW,r1+0.26,px,DY+1.10,MUTED);
    arrow(s,rx+reqW,r2+0.26,px,DY+1.40,MUTED);
    const tiers=["HBM","CPU DRAM","SSD"];
    tiers.forEach((t,i)=>{
      const ty=DY+0.42+i*0.72;
      plainbox(s,tx,ty,tW,0.52,t,9);
    });
    if(anon){ // 둘 다 같은 tier로 (herding)
      arrow(s,px+plW,DY+1.15,tx,DY+0.68,C1);
      arrow(s,px+plW,DY+1.30,tx,DY+0.68,C1);
      label(s,tx-0.05,DY+2.62,tW+0.5,"같은 스텝 → 같은 tier",C1,8);
    }else{  // 서로 다른 tier로 분산
      arrow(s,px+plW,DY+1.10,tx,DY+0.68,C2);
      arrow(s,px+plW,DY+1.45,tx,DY+2.12,C2);
      label(s,tx-0.05,DY+2.62,tW+0.5,"클래스별로 분산",C2,8);
    }
  });
  notesCol(s,AX,C1,[
    "런타임 상태는 24개 지표 1벌 — 요청 수 N과 무관하다",
    "요청 A·B가 구분되지 않아 같은 스텝에서는 같은 점수를 보고 같은 tier를 고른다",
    "max_num_seqs=128 기준 스텝당 수십~수백 건이 몰릴 수 있어 예약 카운터가 사실상 필수",
  ],"→ QA3 감점 근거이자 QA2 가점 근거");
  notesCol(s,BX,C2,[
    "요청마다 특성 벡터가 붙어 이진 3특성 기준 8개 클래스를 구분한다",
    "같은 스텝의 서로 다른 객체가 다른 tier로 흩어져 herding이 발생하지 않는다",
    "유지 상태가 객체 수에 비례하고, 계약 위반 시 eviction 커넥터가 발생한다",
  ],"→ QA1 근거 및 QA2 비용 근거");
  s.addNotes("C1의 실패 모드(herding)와 C2의 이점(분산)이 같은 그림에서 대비된다.");
}
explainSlide(EXPLAIN.component);

/* ================= 4. 시퀀스 ================= */
function seq(s,x,accent,parts,msgs,foot){
  const step=CW/parts.length, top=DY+0.16, hH=0.40;
  const cx=i=>x+step*(i+0.5);
  parts.forEach((p,i)=>{
    const bw=Math.min(step-0.10,1.20);
    plainbox(s,cx(i)-bw/2,top,bw,hH,p,8);
    s.addShape(pres.ShapeType.line,{x:cx(i),y:top+hH,w:0,h:DH-0.62-hH,
      line:{color:RULE,width:0.75,dashType:"dash"}});
  });
  const y0=top+hH+0.30, sp=(DH-0.55-hH-0.30)/(msgs.length-1);
  msgs.forEach((m,i)=>{
    const y=y0+i*sp, a=cx(m[0]), b=cx(m[1]);
    arrow(s,a,y,b,y,m[3]?MUTED:accent,m[3]);
    const lw=Math.max(Math.abs(b-a),1.5);
    label(s,(a+b)/2-lw/2,y-0.21,lw,m[2],m[3]?MUTED:INK,7.5);
  });
  if(foot) s.addText(foot,{x:x+0.15,y:DY+DH-0.34,w:CW-0.3,h:0.26,isTextBox:true,margin:0,
    fontFace:F,fontSize:8,italic:true,color:MUTED,align:"center",valign:"middle"});
}
{
  const s=newSlide("DP1 · 백데이터 ③","시퀀스 — 동일 시나리오: 스케줄 스텝에서 한 요청에 블록 4개 신규 할당",
    "메시지 5개 · 상태 조회 1회 · 추정 0회","메시지 7개(경합 시 9개) · 분류 1회");
  seq(s,AX,C1,["Scheduler","Placer","TierState","BlockPool"],[
    [0,1,"allocate(4)",false],
    [1,2,"read states(6)",false],
    [2,1,"scores",true],
    [1,3,"get_blocks(4)",false],
    [3,0,"blocks",true],
  ],"요청 식별자가 경로에 등장하지 않는다 — 익명 요청의 구조적 의미");
  seq(s,BX,C2,["Scheduler","Placer","Classifier","Contract","BlockPool"],[
    [0,1,"allocate(4, request)",false],
    [1,2,"classify(req)",false],
    [2,1,"class(hot, short)",true],
    [1,3,"target_tier()",false],
    [3,1,"HBM",true],
    [1,4,"get_blocks(4)",false],
    [4,0,"blocks",true],
  ],"tier full이면 Evictor.make_room() 2단계가 임계 경로에 추가된다");
  notesCol(s,AX,C1,[
    "메시지 5개, 전역 상태 조회 1회(6 tier 스캔), 객체 조회 0회",
    "결정 입력이 전부 현재 관측값이라 추정 단계가 없다",
    "같은 스텝의 다음 요청도 같은 점수를 보므로 예약 반영이 필요하다",
  ],"→ QA2 · QA3 근거");
  notesCol(s,BX,C2,[
    "메시지 7개(경합 시 9개), 분류는 객체당 최초 1회",
    "분류 결과가 수명 동안 재사용되어 반복 비용은 낮다",
    "첫 결정이 틀리면 그대로 고착되고, 경합 시 eviction이 결정 지연 분산을 키운다",
  ],"→ QA1 · QA3 · QA4 근거");
  s.addNotes("두 시퀀스는 반드시 동일 시나리오여야 메시지 수 비교가 성립한다. 점선은 반환 메시지.");
}
explainSlide(EXPLAIN.sequence);

/* ================= 5. 클래스 ================= */
function umlBox(s,x,y,w,title,fields,accent,soft){
  const th=0.30, fh=fields.length? 0.20*fields.length+0.14 : 0;
  s.addShape(pres.ShapeType.roundRect,{x:x,y:y,w:w,h:th+fh,rectRadius:0.04,
    fill:{color:"FFFFFF"},line:{color:accent,width:1}});
  s.addShape(pres.ShapeType.rect,{x:x,y:y,w:w,h:th,fill:{color:accent},line:{color:accent}});
  s.addText(title,{x:x,y:y,w:w,h:th,isTextBox:true,margin:0.02,
    fontFace:F,fontSize:9,bold:true,color:"FFFFFF",align:"center",valign:"middle"});
  if(fields.length){
    const runs=fields.map((f,i)=>({text:f,options:{breakLine:i!==fields.length-1}}));
    s.addText(runs,{x:x+0.10,y:y+th+0.05,w:w-0.2,h:fh-0.08,isTextBox:true,margin:0,
      fontFace:F,fontSize:8,color:BODY,lineSpacingMultiple:1.0,valign:"top"});
  }
  return th+fh;
}
{
  const s=newSlide("DP1 · 백데이터 ④","클래스 — 신규 tier / 신규 객체 유형을 추가할 때 어디를 수정하는가",
    "클래스 3개 · 신규 tier = 행 1개","클래스 4개 · 신규 tier = 8개 계약 재정의");
  // C1
  {
    const cx=AX+CW/2, tw=2.95;
    umlBox(s,cx-tw/2,DY+0.20,tw,"TierIndexedPlacer",["+ place(num_blocks) → tier_id"],C1,C1S);
    const h1=umlBox(s,AX+0.20,DY+1.15,2.85,"TierState",
      ["+ tier_id","+ avail_capacity / avail_bandwidth","+ latency / migration_cost","+ score()"],C1,C1S);
    umlBox(s,AX+3.25,DY+1.15,2.50,"BlockPool",["+ get_new_blocks(n)"],MUTED,"FFFFFF");
    arrow(s,cx-0.75,DY+0.20+0.64,AX+0.20+1.4,DY+1.15,C1);
    arrow(s,cx+0.75,DY+0.20+0.64,AX+3.25+1.25,DY+1.15,MUTED);
    s.addText("신규 tier 추가 = TierState 행 1개 (정책 함수는 그대로)",
      {x:AX+0.20,y:DY+DH-0.42,w:CW-0.4,h:0.28,isTextBox:true,margin:0,
       fontFace:F,fontSize:8.5,italic:true,color:C1,align:"center",valign:"middle"});
  }
  // C2
  {
    const cx=BX+CW/2, tw=3.10;
    umlBox(s,cx-tw/2,DY+0.16,tw,"ObjectIndexedPlacer",["+ place(num_blocks, request) → tier_id"],C2,C2S);
    umlBox(s,BX+0.20,DY+1.00,2.85,"ObjectClassifier",["+ classify(request) → ObjectClass"],C2,C2S);
    umlBox(s,BX+0.20,DY+1.72,2.85,"ObjectFeature  ⚠ 관측 불가",
      ["+ hotness","+ locality","+ lifetime"],C2,C2S);
    umlBox(s,BX+3.25,DY+1.00,2.50,"ClassTierContract",
      ["+ target_tier(class)","+ fallback_order"],C2,C2S);
    arrow(s,cx-0.80,DY+0.16+0.64,BX+0.20+1.4,DY+1.00,C2);
    arrow(s,cx+0.80,DY+0.16+0.64,BX+3.25+1.25,DY+1.00,C2);
    arrow(s,BX+0.20+1.4,DY+1.00+0.64,BX+0.20+1.4,DY+1.72,C2);
    s.addText("신규 tier 추가 = 8개 클래스 × 새 tier 계약 재정의",
      {x:BX+0.20,y:DY+DH-0.42,w:CW-0.4,h:0.28,isTextBox:true,margin:0,
       fontFace:F,fontSize:8.5,italic:true,color:C2,align:"center",valign:"middle"});
  }
  notesCol(s,AX,C1,[
    "정책이 TierState.score() 하나에 응축된다",
    "신규 tier 추가는 테이블 행 1개 — argmax의 정의역만 넓어진다",
    "Request 의존이 없어 스케줄러 쪽 타입 변경이 배치 모듈로 전파되지 않는다",
  ],"→ QA2 · QA3 근거");
  notesCol(s,BX,C2,[
    "클래스 4개. ObjectFeature의 세 필드는 모두 할당 시점에 관측 불가능하다",
    "값을 채우려면 힌트 API · 휴리스틱 · 과거 통계 중 하나가 필요하다",
    "결정 근거가 ObjectClass 값으로 남아 로깅과 재현이 자연스럽다",
  ],"→ QA2 · QA4 근거");
  s.addNotes("⚠ 표시한 ObjectFeature 세 필드가 C2 비용의 본질 — 관측 불가 지표 100%.");
}
explainSlide(EXPLAIN.klass);

/* ================= 6. 정량 지표 추출표 ================= */
{
  const s=pres.addSlide(); s.background={color:BG};
  head(s,"DP1 · 백데이터 종합","다이어그램에서 뽑은 정량 지표 — 별점의 근거");
  const rows=[[
    {text:"지표",options:{bold:true,color:"FFFFFF",fill:{color:INK},fontSize:11}},
    {text:"출처",options:{bold:true,color:"FFFFFF",fill:{color:INK},fontSize:11,align:"center"}},
    {text:"C1 · Tier-Indexed",options:{bold:true,color:"FFFFFF",fill:{color:INK},fontSize:11,align:"center"}},
    {text:"C2 · Object-Indexed",options:{bold:true,color:"FFFFFF",fill:{color:INK},fontSize:11,align:"center"}},
  ]];
  const data=[
    ["결정 입력 지표 수","클래스","24 (6 tier × 4)","3 (객체 특성) + tier 제약"],
    ["관측 불가(추정 필요) 지표 비율","클래스","0 %","100 %"],
    ["구분 가능한 객체 등급","컴포넌트","1 (익명)","8 (2³)"],
    ["상태 갱신 비용","컴포넌트","스텝당 O(T)=6, 요청 수 무관","스텝당 O(new_N·D)"],
    ["dispatch 메시지 수","시퀀스","5","7 (경합 시 9)"],
    ["오배치 교정까지 결정 횟수","시퀀스","1","불가 (수명 내 고착)"],
    ["스텝 내 herding 노출","컴포넌트","있음 (예약 카운터 필요)","없음"],
    ["동일 요청 재실행 시 동일 배치","시퀀스","보장 안 됨","보장"],
    ["신규 tier 1개 추가 비용","클래스","테이블 행 1개","8개 클래스 계약 재정의"],
    ["신규 모듈 수","모듈 뷰","2","4"],
  ];
  data.forEach(d=>rows.push([
    {text:d[0],options:{bold:true,color:INK,fontSize:9.5}},
    {text:d[1],options:{color:MUTED,fontSize:9,align:"center"}},
    {text:d[2],options:{color:C1,bold:true,fontSize:9.5,align:"center"}},
    {text:d[3],options:{color:C2,bold:true,fontSize:9.5,align:"center"}},
  ]));
  s.addTable(rows,{x:L,y:1.20,w:R-L,colW:[4.10,1.20,3.50,3.50],
    rowH:[0.40].concat(new Array(10).fill(0.44)),
    border:{type:"solid",pt:0.75,color:RULE},fontFace:F,valign:"middle",
    margin:[4,8,4,8]});
  s.addText("별점을 매길 때 근거가 다이어그램에서 나오지 않는다면, 별점이 아니라 다이어그램이 부족한 것이다.",
    {x:L,y:6.42,w:R-L,h:0.34,isTextBox:true,margin:0,
     fontFace:F,fontSize:10,italic:true,color:MUTED,valign:"middle"});
  s.addNotes("이 표가 QA 별점 매트릭스의 정량 근거 원본이다.");
}

pres.writeFile({fileName:"DP1-candidate-structure-detail.pptx"}).then(f=>console.log("wrote "+f));
