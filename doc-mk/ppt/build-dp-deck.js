const pptxgen = require("pptxgenjs");

const INK   = "1F2933";
const BODY  = "3E4C59";
const MUTED = "7B8794";
const RULE  = "DCE1E7";
const BG    = "FFFFFF";
const DARK  = "16202B";
const C1    = "0B6E6E";   // Candidate 1 identity (teal)
const C2    = "B0503F";   // Candidate 2 identity (terracotta)
const C1S   = "E8F2F1";
const C2S   = "F8EBE7";
const F     = "Arial";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";           // 13.3 x 7.5
pres.author = "DP Review";
pres.title  = "DP1 / DP2 Candidate Structure Comparison";

const W = 13.3, H = 7.5;
const L = 0.5, R = 12.8;

// ---------- geometry of the comparison table ----------
const LBL_X = L,    LBL_W = 1.75;
const A_X   = 2.32, COL_W = 5.19;
const B_X   = 7.61;
const ROWS = [
  { y: 1.30, h: 0.86, label: "후보 구조" },
  { y: 2.16, h: 1.16, label: "대표 구조도" },
  { y: 3.32, h: 1.42, label: "장점" },
  { y: 4.74, h: 1.42, label: "단점" },
  { y: 6.16, h: 0.80, label: "TRADE-OFF" },
];

function slideTitle(s, kicker, title) {
  s.addText(kicker, {
    x: L, y: 0.34, w: 8, h: 0.24, isTextBox: true, margin: 0,
    fontFace: F, fontSize: 11, bold: true, color: MUTED, charSpacing: 1.5,
  });
  s.addText(title, {
    x: L, y: 0.60, w: 12.3, h: 0.52, isTextBox: true, margin: 0,
    fontFace: F, fontSize: 23, bold: true, color: INK,
  });
}

function tableFrame(s) {
  ROWS.forEach((r, i) => {
    if (i > 0) {
      s.addShape(pres.ShapeType.line, {
        x: L, y: r.y, w: R - L, h: 0,
        line: { color: RULE, width: 0.75 },
      });
    }
    s.addText(r.label, {
      x: LBL_X, y: r.y, w: LBL_W, h: r.h, isTextBox: true, margin: 0,
      fontFace: F, fontSize: 11.5, bold: true, color: MUTED,
      valign: "middle", align: "left",
    });
  });
  // outer top / bottom
  s.addShape(pres.ShapeType.line, {
    x: L, y: ROWS[0].y, w: R - L, h: 0, line: { color: INK, width: 1.5 },
  });
  const last = ROWS[ROWS.length - 1];
  s.addShape(pres.ShapeType.line, {
    x: L, y: last.y + last.h, w: R - L, h: 0, line: { color: INK, width: 1.5 },
  });
  // vertical separators
  [A_X - 0.14, B_X - 0.14].forEach((vx) => {
    s.addShape(pres.ShapeType.line, {
      x: vx, y: ROWS[0].y, w: 0, h: last.y + last.h - ROWS[0].y,
      line: { color: RULE, width: 0.75 },
    });
  });
}

function nameCell(s, x, accent, soft, name, oneLiner) {
  const r = ROWS[0];
  s.addShape(pres.ShapeType.roundRect, {
    x: x, y: r.y + 0.14, w: 0.22, h: 0.22, rectRadius: 0.11,
    fill: { color: accent }, line: { color: accent },
  });
  s.addText(name, {
    x: x + 0.32, y: r.y + 0.10, w: COL_W - 0.4, h: 0.30, isTextBox: true, margin: 0,
    fontFace: F, fontSize: 15, bold: true, color: accent,
  });
  s.addText(oneLiner, {
    x: x, y: r.y + 0.44, w: COL_W - 0.1, h: 0.38, isTextBox: true, margin: 0,
    fontFace: F, fontSize: 9.5, color: BODY, lineSpacingMultiple: 1.15,
  });
}

// flow diagram of n boxes with arrows, centred in the column
function flowCell(s, x, accent, soft, steps) {
  const r = ROWS[1];
  const n = steps.length;
  const gap = 0.30;
  const bw = 1.01;                       // 두 후보 공통 폭 (4-box 기준)
  const bh = 0.72;
  const by = r.y + (r.h - bh) / 2;
  const used = n * bw + (n - 1) * gap;
  let bx = x + (COL_W - used) / 2;       // 박스 수가 달라도 열 가운데 정렬
  steps.forEach((t, i) => {
    s.addShape(pres.ShapeType.roundRect, {
      x: bx, y: by, w: bw, h: bh, rectRadius: 0.06,
      fill: { color: soft }, line: { color: accent, width: 0.75 },
    });
    s.addText(t, {
      x: bx, y: by, w: bw, h: bh, isTextBox: true, margin: 0.02,
      fontFace: F, fontSize: 8.5, bold: true, color: INK,
      align: "center", valign: "middle", lineSpacingMultiple: 1.05,
    });
    if (i < n - 1) {
      s.addText("→", {
        x: bx + bw, y: by, w: gap, h: bh, isTextBox: true, margin: 0,
        fontFace: F, fontSize: 13, bold: true, color: accent,
        align: "center", valign: "middle",
      });
    }
    bx += bw + gap;
  });
}

function bulletCell(s, x, rowIdx, items, accent) {
  const r = ROWS[rowIdx];
  const runs = items.map((t, i) => ({
    text: t,
    options: { bullet: { code: "2022" }, breakLine: i !== items.length - 1 },
  }));
  s.addText(runs, {
    x: x, y: r.y + 0.10, w: COL_W - 0.10, h: r.h - 0.18, isTextBox: true, margin: 0,
    fontFace: F, fontSize: 10.5, color: BODY,
    paraSpaceAfter: 7, lineSpacingMultiple: 1.1, valign: "top",
  });
}

function tradeoffCell(s, text) {
  const r = ROWS[4];
  s.addShape(pres.ShapeType.roundRect, {
    x: A_X - 0.06, y: r.y + 0.12, w: (B_X + COL_W) - A_X + 0.06, h: r.h - 0.26,
    rectRadius: 0.06, fill: { color: "F4F6F8" }, line: { color: "F4F6F8" },
  });
  s.addText(text, {
    x: A_X + 0.06, y: r.y + 0.12, w: (B_X + COL_W) - A_X - 0.18, h: r.h - 0.26,
    isTextBox: true, margin: 0,
    fontFace: F, fontSize: 12.5, bold: true, color: INK,
    align: "center", valign: "middle",
  });
}

function comparisonSlide(cfg) {
  const s = pres.addSlide();
  s.background = { color: BG };
  slideTitle(s, cfg.kicker, cfg.title);
  tableFrame(s);
  nameCell(s, A_X, C1, C1S, cfg.a.name, cfg.a.one);
  nameCell(s, B_X, C2, C2S, cfg.b.name, cfg.b.one);
  flowCell(s, A_X, C1, C1S, cfg.a.flow);
  flowCell(s, B_X, C2, C2S, cfg.b.flow);
  bulletCell(s, A_X, 2, cfg.a.pros, C1);
  bulletCell(s, B_X, 2, cfg.b.pros, C2);
  bulletCell(s, A_X, 3, cfg.a.cons, C1);
  bulletCell(s, B_X, 3, cfg.b.cons, C2);
  tradeoffCell(s, cfg.tradeoff);
  s.addNotes(cfg.notes);
  return s;
}

// ---------- QA star matrix slide ----------
function qaSlide(cfg) {
  const s = pres.addSlide();
  s.background = { color: BG };
  slideTitle(s, cfg.kicker, cfg.title);

  const rows = [];
  rows.push([
    { text: "QA", options: { bold: true, color: "FFFFFF", fill: { color: INK }, fontSize: 11 } },
    { text: cfg.aName, options: { bold: true, color: "FFFFFF", fill: { color: INK }, fontSize: 11, align: "center" } },
    { text: cfg.bName, options: { bold: true, color: "FFFFFF", fill: { color: INK }, fontSize: 11, align: "center" } },
    { text: "정량 근거", options: { bold: true, color: "FFFFFF", fill: { color: INK }, fontSize: 11 } },
  ]);
  cfg.rows.forEach((r) => {
    rows.push([
      { text: r.qa, options: { bold: true, color: INK, fontSize: 10.5 } },
      { text: r.a, options: { color: C1, bold: true, fontSize: 14, align: "center" } },
      { text: r.b, options: { color: C2, bold: true, fontSize: 14, align: "center" } },
      { text: r.why, options: { color: BODY, fontSize: 9.5 } },
    ]);
  });
  rows.push([
    { text: "합계  (★ = 1 / 2 / 3점)", options: { bold: true, color: INK, fontSize: 10.5, fill: { color: "F4F6F8" } } },
    { text: cfg.sumA, options: { bold: true, color: C1, fontSize: 14, align: "center", fill: { color: "F4F6F8" } } },
    { text: cfg.sumB, options: { bold: true, color: C2, fontSize: 14, align: "center", fill: { color: "F4F6F8" } } },
    { text: cfg.sumWhy, options: { bold: true, color: INK, fontSize: 9.5, fill: { color: "F4F6F8" } } },
  ]);

  s.addTable(rows, {
    x: L, y: 1.30, w: R - L,
    colW: [2.70, 1.70, 1.70, 6.20],
    rowH: cfg.rowH,
    border: { type: "solid", pt: 0.75, color: RULE },
    fontFace: F, valign: "middle",
    margin: [6, 8, 6, 8],
  });

  s.addText(cfg.foot, {
    x: L, y: 6.62, w: R - L, h: 0.34, isTextBox: true, margin: 0,
    fontFace: F, fontSize: 10, italic: true, color: MUTED, valign: "middle",
  });
  s.addNotes(cfg.notes);
  return s;
}

// ================= Slide 1 — cover =================
{
  const s = pres.addSlide();
  s.background = { color: DARK };
  s.addText("MEMORY SYSTEM DESIGN POINTS", {
    x: L, y: 2.15, w: 11, h: 0.3, isTextBox: true, margin: 0,
    fontFace: F, fontSize: 12, bold: true, color: "8AA4A4", charSpacing: 2.5,
  });
  s.addText("이기종 메모리 런타임\n설계 포인트 검토", {
    x: L, y: 2.62, w: 11, h: 1.5, isTextBox: true, margin: 0,
    fontFace: F, fontSize: 40, bold: true, color: "FFFFFF", lineSpacingMultiple: 1.1,
  });
  s.addShape(pres.ShapeType.line, {
    x: L, y: 4.42, w: 2.2, h: 0, line: { color: "3E5A5A", width: 2 },
  });
  const items = [
    { n: "DP1", t: "Memory Placement Decision Basis", d: "배치 결정의 기준을 무엇에 매달 것인가" },
    { n: "DP2", t: "Compute-Capable Memory Abstraction", d: "연산 능력의 단일 진실 원천을 누가 소유하는가" },
  ];
  items.forEach((it, i) => {
    const y = 4.78 + i * 0.82;
    s.addText(it.n, {
      x: L, y: y, w: 0.9, h: 0.32, isTextBox: true, margin: 0,
      fontFace: F, fontSize: 15, bold: true, color: i === 0 ? "5FBFB0" : "E08A72",
    });
    s.addText(it.t, {
      x: L + 0.95, y: y, w: 6.2, h: 0.32, isTextBox: true, margin: 0,
      fontFace: F, fontSize: 15, bold: true, color: "FFFFFF",
    });
    s.addText(it.d, {
      x: L + 0.95, y: y + 0.32, w: 8.5, h: 0.28, isTextBox: true, margin: 0,
      fontFace: F, fontSize: 10.5, color: "9BAAB4",
    });
  });
  s.addNotes("DP1과 DP2 각각에 대해 후보 구조 비교 표 1장 + QA 별점 매트릭스 1장으로 구성.");
}

// ================= Slide 2 — DP1 comparison =================
comparisonSlide({
  kicker: "DP1  ·  MEMORY PLACEMENT DECISION BASIS",
  title: "설계 질문: 배치 결정의 단일 기준을 무엇에 매달 것인가?",
  a: {
    name: "Candidate 1 — Tier-Indexed",
    one: "요청을 익명으로 두고 자원 상태만으로 결정을 닫아 자기 교정력을 얻는 대신, 구분 능력과 재현성을 포기",
    flow: ["할당 요청\n(크기만)", "Tier 상태\n용량·대역폭", "최적 tier\n선택", "배치"],
    pros: [
      "(정보비용) 추정이 필요한 지표 0%",
      "(정보비용) 갱신 O(6), 요청 수와 무관",
      "(적응성) 오배치가 다음 할당 1회로 교정",
      "요청 인터페이스 무변경, 신규 모듈 2개",
    ],
    cons: [
      "(배치품질) 구분 가능한 등급 1종",
      "(배치품질) 상위 tier를 도착 순서로 점유",
      "(적응성) 스텝 내 herding — 예약 카운터 필요",
      "(재현성) 재현 불가, 24개 상태 스냅샷 필요",
    ],
  },
  b: {
    name: "Candidate 2 — Object-Indexed",
    one: "객체 특성으로 결정을 고정해 구분 능력과 재현성을 얻는 대신, 미래 정보 추정과 오분류 고착을 감수",
    flow: ["할당 요청\n(크기+객체)", "객체 등급\nhot·수명", "등급→Tier\n계약", "배치"],
    pros: [
      "(배치품질) 구분 등급 8종, hot / cold 분리",
      "(배치품질) 같은 스텝이 분산되어 herding 없음",
      "(재현성) 결정론적 배치, 근거 로깅 1항목",
      "(재현성) 배치 정책을 단위 테스트로 고정",
    ],
    cons: [
      "(정보비용) 결정 입력 100%가 미래 정보",
      "(적응성) 오분류가 객체 수명 내내 고착",
      "공유 블록은 최초 소유자 등급으로 고착",
      "신규 tier 추가 시 8개 계약 재정의",
    ],
  },
  tradeoff:
    "관측 가능한 상태만으로 결정을 닫아 얻는 자기 교정력  ↔  객체 특성으로 결정을 고정해 얻는 구분 능력과 재현성",
  notes:
    "결정 변수: 배치 정책의 인덱스 축(자원 축 vs 객체 축). 배타성 근거는 (1) 상위 tier가 꽉 찬 상태에서 hot 객체가 오면 두 불변식이 정반대 결정을 내고, (2) C2가 tier 상태를 읽더라도 그 값을 제약이 아니라 조정 대상으로 다루므로 포함 관계가 아니다.",
});

// ================= Slide 3 — DP1 QA matrix =================
qaSlide({
  kicker: "DP1  ·  QA TRADE-OFF",
  title: "QA 별점 평가 — 지배 없음, 9 : 9 동점",
  aName: "C1 · Tier-Indexed",
  bName: "C2 · Object-Indexed",
  rowH: [0.52, 1.00, 1.00, 1.00, 1.00, 0.60],
  rows: [
    { qa: "QA1. 이기종 환경 배치 품질", a: "★★☆", b: "★★★",
      why: "구분 가능 등급 1종 vs 8종. C1은 상위 tier 점유가 도착 순서로 결정됨 (컴포넌트 다이어그램)" },
    { qa: "QA2. 결정 정보 비용", a: "★★★", b: "★★☆",
      why: "관측 불가(추정 필요) 지표 0% vs 100%. 갱신 O(T)=6 · 요청 수 무관 vs O(new_N·D) + 외부 특성 소스 1개" },
    { qa: "QA3. 적응성 / 자기 교정", a: "★★★", b: "★☆☆",
      why: "오배치 교정까지 결정 1회 vs 교정 불가(수명 내 고착). C1은 herding 대비 예약 카운터 필요" },
    { qa: "QA4. 설명 가능성 / 재현성", a: "★☆☆", b: "★★★",
      why: "동일 배치 재현 보장 없음(24개 상태 스냅샷 필요) vs 보장(클래스 라벨 1개)" },
  ],
  sumA: "9", sumB: "9",
  sumWhy: "모든 축에서 별점이 갈리고 각 후보가 ★★★ 2개 보유 — 선택은 QA 가중치가 결정",
  foot: "★★★ 구조적으로 유리 · ★★☆ 가능하나 비용 발생 · ★☆☆ 구조적으로 불리",
  notes:
    "동점이므로 결론은 '조건부 선택'. 판단을 가르는 두 질문: (1) 요청 특성을 얼마나 신뢰할 수 있는가 (2) 배치 재현성이 운영 요구인가 편의인가.",
});

// ================= Slide 4 — DP2 comparison =================
comparisonSlide({
  kicker: "DP2  ·  COMPUTE-CAPABLE MEMORY ABSTRACTION",
  title: "설계 질문: 연산 능력의 단일 진실 원천을 누가 소유할 것인가?",
  a: {
    name: "Candidate 1 — Capability-in-Memory",
    one: "메모리가 연산 능력을 함께 소유해 최소 실행 경로와 재현성을 확보하는 대신, 조합 표현력을 포기",
    flow: ["Block", "메모리\n(연산 내장)", "실행"],
    pros: [
      "(효율) 메시지 3개, 전역 상태 조회 0회",
      "(예측성) 데이터 의존 분기 0개",
      "(예측성) CUDA graph 캡처 51개 유지",
      "GPU 전용 경로 오버헤드 0, 신규 모듈 0개",
    ],
    cons: [
      "(조합성) 카디널리티 1종, 후보 1개",
      "(조합성) 부하 편중 시 재배치 수단 없음",
      "(확장성) 신규 조합은 구조 변경 필요",
      "op 증가 시 메모리 추상화가 비대화",
    ],
  },
  b: {
    name: "Candidate 2 — Capability-in-Binding",
    one: "관계를 런타임 데이터로 승격해 조합·확장을 확보하는 대신, 조회 비용과 실행 재현성을 포기",
    flow: ["Block", "메모리", "바인딩 +\n플래너", "실행"],
    pros: [
      "(조합성) 카디널리티 3종, 후보 N개",
      "(조합성) 부하·locality 기반 선택 가능",
      "(확장성) 리소스 등록 1줄, 기존 수정 0개",
      "(확장성) 신규 조합 시 코드 변경 0라인",
    ],
    cons: [
      "(효율) 메시지 6개, step당 약 16us 추정",
      "(예측성) 캡처 조합 51 × 리소스 수",
      "메타데이터 최대 16엔트리 일관성 유지",
      "1:1 고정 HW에서는 과설계, 신규 모듈 2개",
    ],
  },
  tradeoff:
    "실행 경로의 최소 오버헤드와 재현성  ↔  메모리–실행 조합의 표현력과 무변경 확장성",
  notes:
    "결정 변수: capability 사실의 단일 진실 원천. 합성 테스트 — 둘 다 두면 불일치 시 어느 쪽이 참인지 정의되지 않고 교차 검증이 필요해져 C1의 이점(조회 0회)이 소멸한다.",
});

// ================= Slide 5 — DP2 QA matrix =================
qaSlide({
  kicker: "DP2  ·  QA TRADE-OFF",
  title: "QA 별점 평가 — 지배 없음, 9 : 10",
  aName: "C1 · Capability-\nin-Memory",
  bName: "C2 · Capability-\nin-Binding",
  rowH: [0.52, 1.00, 1.00, 1.00, 1.00, 0.60],
  rows: [
    { qa: "QA1. Dispatch 경로 효율", a: "★★★", b: "★★☆",
      why: "메시지 3 vs 6, op당 전역 조회 0회 vs 2회, decode step당 0us vs 약 16us (시퀀스 다이어그램)" },
    { qa: "QA2. 실행 예측 가능성", a: "★★★", b: "★★☆",
      why: "데이터 의존 분기 0 vs 1개 이상. CUDA graph 캡처 51개 vs 51 × 선택 가능 리소스 수" },
    { qa: "QA3. 메모리–연산 조합성", a: "★☆☆", b: "★★★",
      why: "표현 가능 카디널리티 1종(1:1) vs 3종(1:1·1:N·N:M). 블록당 실행 후보 1개 vs N개" },
    { qa: "QA4. 확장성", a: "★★☆", b: "★★★",
      why: "신규 리소스 추가 시 기존 클래스 수정 1~2개 vs 0개. 신규 조합은 구조 변경 vs 0라인" },
  ],
  sumA: "9", sumB: "10",
  sumWhy: "각 후보가 ★★★ 2개 보유, 차이 1 — 어느 쪽도 전 축에서 앞서지 않음",
  foot: "★★★ 구조적으로 유리 · ★★☆ 가능하나 비용 발생 · ★☆☆ 구조적으로 불리   |   '약 16us'는 dict 조회 100ns × 160회 기준 추정치",
  notes:
    "실질 쟁점: decode 경로가 CUDA graph로 캡처되므로 C2는 리소스 선택을 캡처 이전(요청/배치 경계)으로 올려야 하고, 그만큼 QA3의 이득이 축소된다.",
});

pres.writeFile({ fileName: "DP1-DP2-candidate-comparison.pptx" }).then((f) =>
  console.log("wrote " + f)
);
