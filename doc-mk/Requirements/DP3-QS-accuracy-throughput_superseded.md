> **[superseded 2026-10-28]** 이 초안은 PPT 67p의 1/2/3% 경계를 앞세워 목표를 잡았다. 사용자가 "기존 1/2/3%를 무시하고 문헌 근거로 정하라"고 정정해 `DP3-QS-accuracy-throughput-v2.md`로 대체한다. 이력 보존을 위해 내용은 그대로 둔다.

# DP3 품질 시나리오 추가안 — 정확도 제약 하 처리량 (DP3-QS-12, 제안)

> 상태: **제안**. 기존 `DP3-requirements.md`는 수정하지 않고(버전 규칙), QS-1(Goodput)과 QS-5(Accuracy)의 임계값이 `TBD(통합 단계)`인 부분을 근거 기반 수치로 채우는 결합 시나리오를 추가한다. 근거 문서: `Evaluation/DP3/results/2026-10-28_dp3-accuracy-throughput-evidence.md`.
> 입력으로 읽은 것: PPT 10, 55, 56, 67, 73p(추출 텍스트), `DP3-requirements.md`, `qa-star-criteria-unified.md`, DP3 평가 결과·정확도 README·sim 코드. 읽지 못한 것: 67p의 [1] 인용 원문(NeurIPS 2025 KVzip 발표 페이지), PPT 55p가 인용한 InferCept·LMCache 원문.

#### DP3-QS-12  Functional correctness × Capacity — 정확도 한도 안에서의 Max SLO goodput   (구분: 선정, DP3-QA1 + DP3-QA4 결합 · ISO: Time behavior/Capacity + Functional correctness)

| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 (Source of Stimulus) | 다수의 agent/RAG 세션 클라이언트(long-context 재사용 요청). 평가 시에는 부하 생성기와 정확도 task 평가기 |
| 2. 자극 (Stimulus) | 문맥 길이 8K~256K token의 재사용 요청이 Baseline 용량의 0.5×~8× 도착률(Poisson)로 들어오고(Baseline 용량의 70%가 기본 부하), 압축 유지 비율 r이 정책 변수로 주어진다 |
| 3. 환경 (Environment) | SYS-H100·SYS-B200, Llama-3.1-70B BF16(TP8), HBM이 KV 전체를 못 담는 과부하 구간, 정상 모드(장애 없음). 정확도 측정은 같은 모델 계열·task·precision에서 압축 전 + full recompute를 기준으로 한다 |
| 4. 자극 대상체 (Artifact) | DP3 설계의 압축 KV 선택 모듈(Recompute Token Selector, Selective Recomputer, Comp.KV 정책)과 정확도 검증·fallback(DP3-FR-10) |
| 5. 응답 (Response) | 정확도 gate를 통과하는 r 범위 안에서만 압축을 적용해 SLO(TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms)를 만족하는 최대 처리량을 올리고, gate를 통과하지 못하는 r에서는 압축을 적용하지 않거나(full KV) 완화한다 |
| 6. 응답 측정 (Response Measure) | 아래 표 |

**응답 측정 (R4/R5)**

| 항목 | 목표 | 통계량·측정 조건 | 근거 | 라벨 |
|---|---|---|---|---|
| (a) 정확도 gate | F1 상대 하락 ≤ **1%** | (F1_full − F1_후보) ÷ F1_full, task별 분리·단일 평균 금지. 95% CI(paired bootstrap 2,000회) **상한 ≤ 1%**일 때만 통과로 인정. 예시 수 n ≥ **4,300**/task (aware r=0.1~0.2 실측 SD 0.24 기준 ±1% 반폭), task ≥ 3종(단락 QA, 요약·다중 hop, 코드). Drop이 없는 실행(r=1.0)이 Baseline과 bit-exact가 아니면 측정 오류로 판정 | 소유자 확정 허용 한도(2026-10-09), PPT 67p ★★★ | [DP문서][사용자] |
| (a') 정확도 하한(허용 최소) | ≤ **3%** | 동일. 3% 초과는 미충족 | PPT 67p ★ 경계. "정책 선택"이며 문헌 근거 없음. 67p의 "KV 선택적 재계산 연구 3% 관측" 원출처 미확인 | [기준] 근거 약함 |
| (b) 처리량 | gate (a) 통과 r에서 **Max SLO goodput ≥ 2.0 × Baseline** (Baseline = 압축 없는 full KV 재사용) | 쌍별 비율의 기하평균, 시나리오 comparison-valid 쌍(현재 32쌍), seed ≥ 5, 부하 sweep ×0.5~8(최대가 끝이면 ×64까지 확장), `PYTHONHASHSEED` 고정. 0-goodput 쌍은 수를 별도 보고 | Stakeholder "처리량 2배 이상이어야 제품화 논의"(PPT 10p, 55p, 56p), 단순 offloading 문헌 하한 2.0~2.3×(PPT 인용값) | [DP문서][기준] |
| (c) 결합 지표 | **R_acc(1%) ≥ 2.0×** = F1 하락 CI 상한 ≤ 1%를 만족하는 r 중 최대 goodput 배수 | `analyze_acc_tput.py`의 R_acc 인증형 | 위 (a)(b)의 결합. R_acc는 **신규 metric(임시 정의)** | [가정] 정의 |
| (d) 꼬리 점검 | Baseline보다 나쁜 쌍(P99 TTFT 또는 goodput)을 쌍 수와 최악 쌍으로 보고 | 기존 평가 방식 | evaluation skill §10 | [기준] |
| 연결 | DP3-QA1, DP3-QA4(= unified QA5), UC-2, DP3-FR-03, 07, 10, DP3-C-4. 평가 위치: `Evaluation/DP3/results/2026-10-28_dp3-accuracy-throughput-evidence.md` |

**현재 상태 (같은 정의로 측정한 값, 참고 — 요구사항이 아니라 gap)**

| 후보 | R_acc(1%) 인증형 | R_acc(1%) 점추정형 | 막는 요소 |
|---|---:|---:|---|
| C1 Offline | ×1.00 | ×1.00 | 정확도: 하락 12.5~39% (측정 r 전 구간) |
| C2 Online | ×1.00 | ×1.35 (r=0.1) | 인증: n=93, CI 반폭 1.5~7.3%. 처리량: r=0.1에서도 ×1.35 < 2.0 |

→ 목표 (c)는 현재 미달성이다. [C] 보간으로 C1이 2.0×가 되려면 r ≲ 0.23(4.3× 압축)이 필요한데, 직접 확인한 문헌(KVzip)의 negligible-loss 구간은 3~4×(r≈0.25~0.33)이라 **목표 (b)와 (a)가 문헌 경계에서 충돌한다.** 이 목표가 달성 가능한지는 측정으로 확인되지 않았다.

## 근거의 출처와 직접 확인 범위

| 근거 | 확인 범위 |
|---|---|
| KVzip (arXiv 2505.23416) | abstract와 arXiv HTML 본문 텍스트에서 직접 확인: KV 3~4× 축소, 디코딩 지연 약 2×, "negligible performance loss", 30% 유지까지 정확도 유지(본문), query-aware 방법은 multi-query에서 90% 유지에서도 열화. 그림으로만 제시된 task별 상대 성능 수치는 확인하지 못함 |
| CacheBlend (arXiv 2405.16444) | abstract만: TTFT 2.2~3.3× 감소, 처리량 2.8~5× 증가(full KV recompute 대비), "품질 저하 없이". 정확도 수치는 확인하지 못함 |
| SnapKV (arXiv 2404.14469) | abstract만: 생성 속도 3.6×, 16K 입력에서 메모리 효율 8.2×, Needle-in-a-Haystack 정확도 하락 미미. F1 수치 없음 |
| KIVI (arXiv 2402.02750) | abstract만: 피크 메모리 2.6× 감소, 처리량 2.35~3.47×, "거의 같은 품질". 정확도 수치 없음 |
| 위 논문들의 공통 한계 | 처리량과 정확도를 **같은 설정에서 F1 제약 하 goodput**으로 보고한 값은 확인하지 못했다. abstract의 처리량·정확도 문장은 서로 다른 benchmark에서 나온 것이라 이 문서의 R_acc와 직접 비교할 수 없다 |
| 내부 | DP3 시뮬레이터 [B+C], 소형 모델 정확도 [A 소형, n=93] |

## 사용자 확정 필요 (§4.3)

| ID | 질문 | 현재 가정값 | 영향 |
|---|---|---|---|
| Q-1 | 정확도 별 기준: 67p(≤1/2/3%) vs `qa-star-criteria-unified.md`(1%/3%) vs 73p(<1/<2/<3, ☆ ≥3%) 중 최종은? | 67p | QS-5, 별점, 선택 로직 |
| Q-2 | 처리량 목표 2.0×를 정확도 gate 통과 조건에서 요구할 것인가, 완화할 것인가(예: 1.5×) | 2.0× | (b), (c) 달성 판정 |
| Q-3 | R_acc를 공식 지표로 등록할 것인가(등록하면 `qa-evaluation-criteria.md` §9 형식으로 결과 보기 전 정의 필요) | 임시 정의 | (c) |
| Q-4 | 정확도 측정 표본 확대(n ≥ 4,300, task 3종, 7B 이상 모델)를 진행할 것인가 | 필요 | (a) 인증 가능 여부 |
| Q-5 | `dp3sim.py`의 `hash(sc.sid)` RNG seed 결함을 수정하고 DP3 기존 결과를 재생성할 것인가 | 수정 안 함 | 기존 숫자 재현성 |
