const pptxgen = require("pptxgenjs");

const FONT = "Malgun Gothic";
const C = { line: "1F3B73", red: "C0392B", blue: "2F6DB5", orange: "D35400", grid: "E3E3E3", txt: "333333", sub: "666666", shade: "F6D9D6" };
const MB_PER_TOKEN = 0.33;
const kv = (tok) => (tok * MB_PER_TOKEN) / 1000; // GB
const GPUS = [["H100", 80], ["B200", 192], ["B300", 288]];
const TOP = 288;
const POINTS = [
  { id: "chat", name: "채팅 1×", tok: 19e3, basis: "가정 [3]" },
  { id: "agent", name: "에이전트 ≈4×", tok: 75e3, basis: "SWE-bench Pro 실측 [1]" },
  { id: "multi", name: "멀티에이전트 ≈15×", tok: 281e3, basis: "가정 [3]" },
];
const SESSIONS = 100, ASTRA_AGENTS = 10000;
const sig2 = (v) => +v.toPrecision(2);
const fmtSize = (gb) => { gb = sig2(gb); return gb >= 1e6 ? `${gb / 1e6} PB` : gb >= 1e3 ? `${gb / 1e3} TB` : `${gb} GB`; };
const fmtK = (t) => `${Math.round(t / 1e3)}K`;

// ---------- 좌측 패널 좌표 ----------
const PY = 1.3, PH = 4.1;
const LX = 1.35, LW = 5.0;           // 좌 플롯
const RX = 8.05, RW = 3.9;           // 우 플롯
const YMAX = 400;

function build(pres, mode) {
  const isLog = mode === "log";
  const s = pres.addSlide();
  s.background = { color: "FFFFFF" };
  const T = (text, o) => s.addText(text, Object.assign({ fontFace: FONT, margin: 0, isTextBox: true }, o));
  const L = (x, y, w, h, line, name, extra) => s.addShape(pres.shapes.LINE, Object.assign({ x, y, w, h, line, objectName: name }, extra || {}));

  T(`버전 ${isLog ? "B · 좌측 x축 로그" : "A · 좌측 선형 축"}`, { x: 0.5, y: 0.15, w: 4, h: 0.25, fontSize: 10, color: "999999", objectName: "version-tag" });

  // ================= ① 좌측 =================
  const XMIN = isLog ? 1e4 : 0, XMAX = isLog ? 1.1e6 : 1.03e6;
  const X = (v) => isLog ? LX + ((Math.log10(v) - 4) / (Math.log10(XMAX) - 4)) * LW : LX + ((v - XMIN) / (XMAX - XMIN)) * LW;
  const Y = (v) => PY + PH - (v / YMAX) * PH;

  T("① 단일 세션: 문맥이 길어질수록 KV cache 증가", { x: LX - 0.2, y: 0.55, w: 5.6, h: 0.4, fontSize: 14, bold: true, color: C.txt, objectName: "L-title" });
  s.addShape(pres.shapes.RECTANGLE, { x: LX, y: Y(YMAX), w: LW, h: Y(TOP) - Y(YMAX), fill: { color: C.shade, transparency: 30 }, line: { type: "none" }, objectName: "L-region-over-B300" });
  for (let v = 0; v <= YMAX; v += 50) {
    if (v > 0 && v < YMAX) L(LX, Y(v), LW, 0, { color: C.grid, width: 0.75 }, `L-grid-y-${v}`);
    T(String(v), { x: LX - 0.55, y: Y(v) - 0.12, w: 0.47, h: 0.24, align: "right", valign: "middle", fontSize: 10, color: C.txt, objectName: `L-tick-y-${v}` });
  }
  const xticks = isLog ? [[1e4, "10K"], [1e5, "100K"], [1e6, "1M"]] : [[0, "0"], [2e5, "200K"], [4e5, "400K"], [6e5, "600K"], [8e5, "800K"], [1e6, "1M"]];
  xticks.forEach(([v, lab]) => {
    if (v > XMIN) L(X(v), PY, 0, PH, { color: C.grid, width: 0.75 }, `L-grid-x-${lab}`);
    T(lab, { x: X(v) - 0.4, y: PY + PH + 0.05, w: 0.8, h: 0.24, align: "center", fontSize: 10, color: C.txt, objectName: `L-tick-x-${lab}` });
  });
  s.addShape(pres.shapes.RECTANGLE, { x: LX, y: PY, w: LW, h: PH, fill: { type: "none" }, line: { color: "222222", width: 1 }, objectName: "L-plot-frame" });
  T(isLog ? "누적 문맥 길이 (tokens, log)" : "누적 문맥 길이 (tokens)", { x: LX, y: PY + PH + 0.33, w: LW, h: 0.26, align: "center", fontSize: 11, color: C.txt, objectName: "L-axis-title-x" });
  T("KV cache 크기 (GB)", { x: LX - 0.85 - 1.05, y: PY + PH / 2 - 0.13, w: 2.1, h: 0.26, align: "center", rotate: 270, fontSize: 11, color: C.txt, objectName: "L-axis-title-y" });

  GPUS.forEach(([name, gb], i) => {
    L(LX, Y(gb), LW, 0, { color: C.red, width: 1.25, dashType: "dash", transparency: 45 - i * 20 }, `L-hbm-line-${name}`);
  });

  if (!isLog) {
    L(X(0), Y(kv(1e6)), X(1e6) - X(0), Y(0) - Y(kv(1e6)), { color: C.line, width: 3 }, "L-kv-curve", { flipV: true });
  } else {
    const N = 60, pts = [], x0 = X(1e4), yTop = Y(kv(1e6));
    for (let i = 0; i <= N; i++) { const tok = 1e4 * Math.pow(100, i / N); pts.push({ x: X(tok) - x0, y: Y(kv(tok)) - yTop, ...(i === 0 ? { moveTo: true } : {}) }); }
    s.addShape(pres.shapes.CUSTOM_GEOMETRY, { x: x0, y: yTop, w: X(1e6) - x0, h: Y(kv(1e4)) - yTop, points: pts, fill: { type: "none" }, line: { color: C.line, width: 3 }, objectName: "L-kv-curve" });
  }

  // 점 + 라벨
  const lines3 = (p) => [
    { text: p.name, options: { bold: true, breakLine: true } },
    { text: `${fmtK(p.tok)} · ≈${sig2(kv(p.tok))} GB`, options: { breakLine: true } },
    { text: `(${p.basis})`, options: {} }];
  if (!isLog) {
    const LBW = 1.95, LBH = 0.62, lx = X(6.2e5);
    const centers = { chat: 24, agent: 88, multi: 152 };
    POINTS.forEach((p) => {
      const px = X(p.tok), py = Y(kv(p.tok)), ly = Y(centers[p.id]) - LBH / 2;
      const x2 = lx, y2 = ly + LBH / 2;
      L(Math.min(px, x2), Math.min(py, y2), Math.abs(x2 - px), Math.abs(y2 - py), { color: "999999", width: 0.75 }, `L-leader-${p.id}`, { flipV: (x2 - px) * (y2 - py) < 0 });
      T(lines3(p), { x: lx, y: ly, w: LBW, h: LBH, valign: "middle", fontSize: 9, color: C.blue, fill: { color: "FFFFFF" }, margin: 0.03, objectName: `L-label-${p.id}` });
    });
  } else {
    const LH = 0.25;
    const pl = {
      chat: { x: LX + 0.05, y: Y(kv(19e3)) - 0.2 - LH, w: 1.55, align: "left" },
      agent: { x: X(75e3) + 0.1 - 1.55, y: Y(kv(75e3)) - 0.3 - LH, w: 1.55, align: "right" },
      multi: { x: X(281e3) + 0.1 - 1.9, y: Y(kv(281e3)) - 0.2 - LH, w: 1.9, align: "right" },
    };
    POINTS.forEach((p) => T(`${p.name} · ≈${sig2(kv(p.tok))} GB`, { x: pl[p.id].x, y: pl[p.id].y, w: pl[p.id].w, h: LH, align: pl[p.id].align, valign: "middle", fontSize: 9, bold: true, color: C.blue, objectName: `L-label-${p.id}` }));
  }
  POINTS.forEach((p) => s.addShape(pres.shapes.OVAL, { x: X(p.tok) - 0.07, y: Y(kv(p.tok)) - 0.07, w: 0.14, h: 0.14, fill: { color: C.blue }, line: { color: "FFFFFF", width: 0.75 }, objectName: `L-pt-${p.id}` }));
  // HBM 라벨 (좌측, 선 위)
  GPUS.forEach(([name, gb]) => T(`${name} ${gb} GB`, { x: LX + 0.06, y: Y(gb) - 0.25, w: 1.2, h: 0.22, fontSize: 9.5, color: C.red, objectName: `L-hbm-label-${name}` }));
  // 1M 별
  const sx = X(1e6), sy = Y(kv(1e6));
  s.addShape(pres.shapes.STAR_5_POINT, { x: sx - 0.16, y: sy - 0.16, w: 0.32, h: 0.32, fill: { color: C.orange }, line: { color: C.orange, width: 0.5 }, objectName: "L-pt-1M" });
  T([{ text: `1M · ≈${sig2(kv(1e6))} GB`, options: { bold: true, breakLine: true } }, { text: "단일 세션이 B300 1개 초과", options: {} }],
    { x: sx - 0.25 - 2.1, y: Y(374) - 0.22, w: 2.1, h: 0.44, align: "right", valign: "middle", fontSize: 9.5, color: C.orange, objectName: "L-label-1M" });

  // ================= ② 우측 =================
  const R_YMIN = 40, R_YMAX = 3e7;
  const lg = Math.log10;
  const RY = (v) => PY + PH - ((lg(v) - lg(R_YMIN)) / (lg(R_YMAX) - lg(R_YMIN))) * PH;
  T("② 에이전트·세션이 늘면 총 KV는 수 자릿수 증가", { x: RX - 0.9, y: 0.55, w: 5.6, h: 0.4, fontSize: 14, bold: true, color: C.txt, objectName: "R-title" });
  s.addShape(pres.shapes.RECTANGLE, { x: RX, y: RY(R_YMAX), w: RW, h: RY(TOP) - RY(R_YMAX), fill: { color: C.shade, transparency: 30 }, line: { type: "none" }, objectName: "R-region-over-B300" });
  [[1e2, "100 GB"], [1e3, "1 TB"], [1e4, "10 TB"], [1e5, "100 TB"], [1e6, "1 PB"], [1e7, "10 PB"]].forEach(([v, lab]) => {
    L(RX, RY(v), RW, 0, { color: C.grid, width: 0.75 }, `R-grid-${lab}`);
    T(lab, { x: RX - 0.75, y: RY(v) - 0.12, w: 0.68, h: 0.24, align: "right", valign: "middle", fontSize: 10, color: C.txt, objectName: `R-tick-${lab}` });
  });
  T("총 KV cache 크기 (log)", { x: RX - 0.95 - 1.05 - 0.05, y: PY + PH / 2 - 0.13, w: 2.1, h: 0.26, align: "center", rotate: 270, fontSize: 11, color: C.txt, objectName: "R-axis-title-y" });

  const bars = [
    { name: "채팅", sub: `×${SESSIONS}세션`, gb: kv(19e3) * SESSIONS, color: C.blue },
    { name: "에이전트", sub: `×${SESSIONS}세션`, gb: kv(75e3) * SESSIONS, color: C.blue },
    { name: "멀티에이전트", sub: `×${SESSIONS}세션`, gb: kv(281e3) * SESSIONS, color: C.blue },
    { name: "ASTRA [4]", sub: `1M × ${ASTRA_AGENTS.toLocaleString("en-US")} agents`, gb: kv(1e6) * ASTRA_AGENTS, color: C.orange },
  ];
  const slot = RW / bars.length, bw = slot * 0.62;
  bars.forEach((b, i) => {
    const cx = RX + slot * (i + 0.5), top = RY(b.gb), base = RY(R_YMIN);
    s.addShape(pres.shapes.RECTANGLE, { x: cx - bw / 2, y: top, w: bw, h: base - top, fill: { color: b.color }, line: { type: "none" }, objectName: `R-bar-${i + 1}` });
    const mult = b.gb / TOP, m = mult < 1e3 ? `≈${Math.round(mult)}×` : `≈${(Math.round(mult / 100) * 100).toLocaleString("en-US")}×`;
    T([{ text: fmtSize(b.gb), options: { bold: true, breakLine: true } }, { text: `(${m})`, options: {} }],
      { x: cx - 0.55, y: top - 0.44, w: 1.1, h: 0.4, align: "center", valign: "bottom", fontSize: 9.5, color: C.txt, objectName: `R-bar-label-${i + 1}` });
    T([{ text: b.name, options: { breakLine: true } }, { text: b.sub, options: {} }],
      { x: cx - slot / 2 + 0.02, y: PY + PH + 0.05, w: slot - 0.04, h: 0.5, align: "center", valign: "top", fontSize: 9, color: C.txt, objectName: `R-xlabel-${i + 1}` });
  });
  s.addShape(pres.shapes.RECTANGLE, { x: RX, y: PY, w: RW, h: PH, fill: { type: "none" }, line: { color: "222222", width: 1 }, objectName: "R-plot-frame" });
  GPUS.forEach(([name, gb], i) => {
    L(RX, RY(gb), RW, 0, { color: C.red, width: 1.25, dashType: "dash", transparency: 45 - i * 20 }, `R-hbm-line-${name}`);
    if (name !== "B200") T(`${name} ${gb} GB`, { x: RX + RW + 0.08, y: RY(gb) - 0.12, w: 1.0, h: 0.24, valign: "middle", fontSize: 9.5, color: C.red, objectName: `R-hbm-label-${name}` });
  });
  T("괄호: B300 1개 HBM(288 GB) 대비 배수", { x: RX - 0.9, y: 0.95, w: 5.6, h: 0.25, fontSize: 10, color: C.sub, objectName: "R-subtitle" });

  // ================= 각주 =================
  T([
    { text: "출처: [1] arXiv:2605.26297  [2] arXiv:2608.15127  [3] Anthropic Eng. Blog  [4] ASTRA  [10] Conceptual illustration based on Continuum (Li et al., 2025), arXiv:2511.02230", options: { breakLine: true } },
    { text: "KV cache 0.33MB/token (Llama-3.1-70B, BF16). 문맥 길이: 에이전트 ≈75K [1] (SWE-bench Pro 평균 누적 문맥 69–80K), 채팅·멀티에이전트는 [3]의 토큰 사용량 배수(≈4×/≈15×)를 적용한 가정.", options: { breakLine: true } },
    { text: "점선 = GPU 1개 HBM 총량 H100 80 / B200 192 / B300 288 GB (가중치 미차감). 동시 세션 수·ASTRA 설정은 전부 KV 상주 가정의 상한 (prefix 공유·압축·양자화 미반영).", options: {} },
  ], { x: 0.5, y: 6.6, w: 12.3, h: 0.7, fontSize: 9, color: "666666", valign: "top", objectName: "footnote" });
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  pres.title = "KV cache 수요 (단일 세션 / 에이전트·세션 증가) - 도형 편집형";
  build(pres, "linear");
  build(pres, "log");
  await pres.writeFile({ fileName: "kv-demand-full-shapes.pptx" });
  console.log("ok");
})();
