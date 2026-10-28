# DP3 기능 정확성 × 처리량 — 문헌 근거와 품질 시나리오 목표 (v2, 제안)

> 상태: **제안**(사용자 확정 전). v1(`DP3-QS-accuracy-throughput_superseded.md`)은 PPT 67p의 1/2/3% 경계를 앞세웠다. 사용자 정정("기존 1/2/3%를 무시하고 문헌 근거를 찾아라")에 따라 **PPT의 경계를 전혀 쓰지 않고** 문헌·표준에서 직접 확인한 수치만으로 다시 정했다.
> 측정 결과(r-sweep, R_acc, 재현성 결함)는 `Evaluation/DP3/results/2026-10-28_dp3-accuracy-throughput-evidence.md`. 이 문서는 그 결과와 무관하게 **목표 수치의 근거**만 다룬다.
> 확인 방법: 아래 표의 모든 수치는 원문을 직접 받아 문장을 grep으로 확인했다(arXiv HTML, MLCommons 규칙 원문 adoc). 검색 결과의 요약 문장은 근거로 쓰지 않았다. 직접 확인하지 못한 것은 §6에 따로 적었다.

# 1. 한 줄 결론

- 문헌이 **받아들이는 정확도 손실의 기준점은 두 개**다: **상대 1%**(MLPerf LLM 대부분의 행이 쓰는 "reference의 99%"), **상대 3%**(MLPerf가 잡음 있는 지표에 쓰는 97%, KV 서빙 논문 KVServe의 97% 제약, EVICPRESS의 3% 허용). **3%를 넘는 값을 "허용"이라고 정의한 문헌·표준은 찾지 못했다.** 중간의 2%는 독립 근거가 없다(CacheGen의 헤드라인 수치가 있을 뿐).
- **정확도와 처리량을 같이 평가하는 방식에도 선례가 있다**: "정확도 기준을 만족하는 조건에서만 성능을 인정"(MLPerf), "97% 상대 정확도 제약 하에서 압축률 최대화"(KVServe), "품질 목표/3% 허용 하에서 처리량 보고"(EVICPRESS), "<1% 하락에서 처리량·TTFT 보고"(FastKV). 우리 R_acc는 이 관행과 같은 형식이다.
- **iso-accuracy 처리량 이득의 문헌 범위는 하한 약 2×, 상한 약 3.6~5×**다(§3). 목표 하한 2.0×는 문헌의 하한과 일치한다.
- 정확도는 **평균만으로 판정하면 안 된다**: 같은 KVServe 표에서 평균 상대 정확도 97.4%인 KIVI가 task 하나에서는 −5.3%, 평균 95.5%인 DuoAttention은 Multi-News에서 −13.9%다.

# 2. 정확도 허용 한도의 문헌 근거 (직접 확인)

| # | 출처 | 직접 확인한 내용 | 시사점 | 확인 범위 |
|---|---|---|---|---|
| E1 | **MLPerf Inference 규칙**(MLCommons, `inference_rules.adoc` master) | Datacenter 표 Quality 열: Llama3.1-8B 요약 "99% of FP32 and 99.9% of FP32", Llama2-70b "99.9% of FP32", Llama3.1-405B(GovReport·LongBench·RULER 혼합) "99% of FP16", Mixtral-8x7B "99% of FP16", DeepSeek-r1 "99% of FP16", **E2E-RAG "97% of FP32 (LLM Judge score = ~35%; +/- ~3%)"**, 에지 **Agentic Function Calling "97% of validated Q4_K_M reference, 3% one-sided band"**. LLM 행은 TTFT/TPOT 제한과 함께 정의됨(예: Llama3.1-405B Server 6000 ms/175 ms) | 업계 표준은 "정확도를 reference의 99%로 묶고 그 조건에서의 처리량·지연을 겨룬다". 지표 자체가 잡음이 큰 행(LLM judge RAG, agent)만 97%로 완화 | 표 원문. 99%의 통계적 의미(신뢰구간)를 정의하는 문장은 규칙 문서에서 찾지 못함 |
| E2 | **"Give Me BF16 or Give Me Death?" (Kurtić et al., ACL 2025)** | 양자화 모델의 BF16 대비 recovery: Leaderboard V1 "all quantization schemes, across model sizes, recover approximately 99%", "8-bit quantization achieves 99.75% recovery", **task별 최저 96.88%**(TruthfulQA, W4A16-INT 8B). V2 "maintain 99% of the baseline's average score, with all models recovering at least 96%". HumanEval 8-bit 99.9%, 4-bit 98.9% | KV 압축이 아니라 **양자화**다. 배포되는 lossy 압축의 평균 손실은 대체로 1% 안쪽이고, task 단위 최악이 3~4%까지 간다는 경험적 범위 | 본문 텍스트 |
| E3 | **KVServe** (arXiv 2605.13734, 2026-05) | 오프라인 Pareto 탐색을 **"97% relative accuracy constraint"** 하에서 수행. 정적 baseline인 "CacheGen and KIVI frequently violate the 97% relative accuracy threshold". 최대 3.15× JCT 개선. Table 1(Qwen2.5-7B, BF16 대비 6개 task 평균 상대 정확도): CacheGen 65.76%(압축 6.17×), KIVI 97.43%(4.40×), DuoAttention 95.48%(3.10×), KVServe-Unified 98.20%(7.42×), KVServe-Aware 100.35%(8.28×) | KV 서빙 시스템 논문이 **97%를 설계 제약으로 채택**. 같은 방법도 설정에 따라 정확도가 크게 다름(CacheGen) | 본문과 Table 1. 97%를 고른 이유는 확인하지 못함(설계 선택으로 보임) |
| E4 | **EVICPRESS** (arXiv 2512.14946, 2025-12) | "reduces TTFT by 1.22 to 1.56 within 3% quality drop" (LRU eviction 대비), "improves inference throughput by 2.0–3.6 compared best baseline at a quality score target of 80%" | KV 재사용·압축 시스템이 **3% 품질 하락 허용**과 **품질 목표 하 처리량**으로 보고 | 본문 intro. 품질 점수의 정의(task별)는 확인하지 못함 |
| E5 | **FastKV** (arXiv 2502.01068v2) | "up to 1.97 and 4.82 improvements in time-to-first-token (TTFT) and throughput ... compared to baseline without KV cache compression", "maintains accuracy within 1% of the baseline on long-context benchmarks". 동시에 저자들의 동기 서술: "there are currently no KV cache compression techniques that can adequately preserve accuracy while simultaneously improving TTFT and throughput". SnapKV/AdaKV/HeadKV는 LLaMA-3.1-8B-UltraLong-1M에서 평균 정확도 하락 0.69%(budget 512), 0.19%(2048) | **1% 이내 + 처리량 이득**을 동시에 주장하는 논문이 있으나, 저자 스스로 기존 기법은 둘을 동시에 만족하지 못한다고 서술 | 본문. 4.82×가 나온 정확한 설정(문맥 길이, budget)은 확인하지 못함 |
| E6 | **CacheGen** (arXiv 2310.07240) | "the degradation is no more than 2% in accuracy, less than 0.1% in F1 score, and less than 0.1 in perplexity", "3.1-4.7 faster than loading the text contexts with less than 2% accuracy drop", KV 크기 3.5–4.3× 감소 | F1과 accuracy 지표가 다르게 보고됨: F1 <0.1%, accuracy ≤2%. KVServe Table 1에서는 CacheGen이 65.76%까지 떨어짐(다른 설정·모델·task) | 본문 |
| E7 | **CacheBlend** (arXiv 2405.16444, EuroSys'25) | "CacheBlend's reduction in F1 and Rouge-L score is within 0.02" (full recompute, prefix caching 대비), 요약부 "no more than 0.01-0.03 quality drop", Yi-34B 재계산 5~18%에서 "at most 0.002". TTFT 2.2–3.3× 감소, 처리량 2.8–5×. **비교 대상이 원문 안에서 불일치**: 초록은 "from full KV recompute", 서론 한 문장은 "prefix caching" 대비로 쓰고, 기여 요약 bullet은 "up to 5 compared with full KV recompute and 3.3 compared with prefix caching". 기본 재계산 15% | KV **재사용 + 선택 재계산**(우리 DP3 구조)에 가장 가까운 선례. **절대값(F1 0~1 척도의 0.02)**이라 상대 하락으로 환산하려면 기준 F1이 필요한데 본문 텍스트에는 없다(그림에만 있음) | 본문. task별 기준 F1은 확인하지 못함 → **상대 %로 환산하지 않았다** |
| E8 | **KVzip** (arXiv 2505.23416, NeurIPS 2025) | 3–4× KV 축소, FlashAttention 디코딩 지연 약 2×, "negligible performance loss"; 본문 "consistently maintains inference accuracy even when evicting up to 70% of the KV cache"(30% 유지), GSM8K는 "near-lossless compression down to 20–30%". query-aware eviction 방법은 "suffer from performance degradation even at a 90% cache budget ratio under multi-query scenarios". 점수 chunk 크기 변경에 따른 성능 차이는 0.3 비율에서 "below 2%" | **Query-agnostic 압축 후 재사용**(우리 C1 계열)이 multi-query에서 유지되는 유일한 직접 증거. task별 상대 성능은 그림이라 수치 미확인 | 본문 텍스트 |
| E9 | **SCBench** (arXiv 2412.10319) | "sub-O(n) memory methods suffer in multi-turn scenarios". 본문: MInference의 Ret.KV가 multi-turn 51.2에서 multi-request 46.8로 하락(상대 −8.6%, 계산) | 단일 질의 평가는 재사용 시나리오에서 정확도를 과대평가할 수 있음 | 초록, 본문 |
| E10 | **KV Cache Compression, But What Must We Give in Return?** (arXiv 2407.01527) | 한 token dropping 방법이 passkey 7자리에서 100%이던 것이 64자리에서 4× 압축 시 35.0%, KIVI-2bit는 100%→91.0% | task 난이도에 따라 정확도가 급락 → **task별 보고가 필수**. 방법 이름은 HTML 추출에서 빠져 확인하지 못함 | 본문 한 문단 |

# 3. 정확도 제약 하 처리량(iso-accuracy)의 문헌 범위

| 출처 | 처리량/지연 이득 | 그때의 정확도 | 비교 baseline | 비고 |
|---|---|---|---|---|
| FastKV (E5) | 처리량 최대 4.82×, TTFT 최대 1.97× | 평균 <1% 하락 | 압축 없음 | "up to" 값(최대) |
| CacheBlend (E7) | 처리량 2.8–5×, 최대 5×(full recompute 대비)·3.3×(prefix caching 대비) 기여 요약. TTFT 2.2–3.3× | F1/Rouge-L ≤0.02 절대 | full recompute, prefix caching | 우리 Baseline(전체 KV 재사용)에 가까운 것은 prefix caching 쪽 |
| EVICPRESS (E4) | 처리량 2.0–3.6×, TTFT 1.43–3.77×(같은 quality) | 품질 목표 80%, 3% 하락 허용 | 최선 baseline | 지연 이득 1.22–1.56×은 3% 하락 이내 |
| CacheGen (E6) | 지연 3.1–4.7×(텍스트 대비), 3.2–3.7×(양자화 대비) | accuracy ≤2%, F1 <0.1% | 텍스트 재적재 / 기본 양자화 | 처리량이 아니라 지연 |
| KVServe (E3) | JCT 최대 3.15× | 상대 정확도 ≥97% | 정적 압축 baseline | 최대값 |
| KVzip (E8) | 디코딩 attention 지연 약 2× | negligible | full KV | 처리량 아님 |

읽는 법: 이득 수치의 **하한은 약 2×**(EVICPRESS 처리량 2.0×, KVzip 약 2×, CacheBlend TTFT 2.2×), **상한은 약 3.6×(EVICPRESS)~5×(CacheBlend, FastKV 4.82×)**이다. 상한값은 대부분 "up to"이고 baseline이 제각각이라 서로 직접 비교할 수 없다. **F1 같은 task 정확도 제약 하에서 SLO를 만족하는 goodput**을 같은 설정으로 보고한 논문은 찾지 못했다(§6).

# 4. 선례가 말해주는 평가 방식

| 관행 | 선례 | 우리 평가에 대응 |
|---|---|---|
| 정확도 기준을 통과한 구성의 성능만 인정 | MLPerf(E1) | R_acc = 정확도 gate를 통과하는 r 중 최대 goodput |
| 정확도 제약 하에서 압축률(또는 처리량) 최대화 | KVServe(E3), EVICPRESS(E4) | 동일 |
| 평균과 task별을 분리 보고 | KVServe Table 1, KV benchmark(E10) | task별 gate |
| 정적 설정은 task·환경에 따라 gate를 깰 수 있음 | KVServe: CacheGen·KIVI 위반 | gate 실패 시 압축 해제(fallback), DP3-FR-10 |

**평균 gate는 task 하나의 큰 손실을 가린다**(KVServe Table 1에서 직접 계산, BF16 대비 task별 상대 하락 %):

| 방법 (압축률) | 6개 task 평균 하락 | task별 최악 | 최악 task |
|---|---:|---:|---|
| KIVI (4.40×) | 2.6% | 5.3% | Qasper |
| DuoAttention (3.10×) | 4.5% | 13.9% | Multi-News |
| KVServe-Unified (7.42×) | 1.8% | 5.7% | HotpotQA |
| KVServe-Aware (8.28×) | −0.3% | 4.2% | HotpotQA |
| CacheGen (6.17×) | 34.2% | 58.1% | HotpotQA |

→ 97% **평균** 제약을 통과한 KVServe-Unified도 task 하나는 5.7% 하락이다. 평균 기준만 쓰면 이런 task가 보이지 않는다.

# 5. 제안: 정확도 기준과 품질 시나리오 목표 (문헌 기반)

## 5.1 정확도 기준 — 두 단계(문헌이 지지하는 만큼만)

| 단계 | 상대 F1(또는 task 지표) 하락 | 근거 | 지지 강도 |
|---|---|---|---|
| **목표(우수)** | **≤ 1%** | MLPerf LLM 행의 99%(E1), BF16 논문 8-bit 평균 recovery 99.75%(E2), FastKV <1%(E5) | 강함: 표준과 복수 논문 |
| **최소(허용)** | **≤ 3%** | MLPerf 잡음 있는 지표의 97%(E1), KVServe 97% 제약(E3), EVICPRESS 3% 허용(E4), BF16 논문 task 최저 96.88%(E2) | 강함: 표준과 KV 서빙 논문 2편이 같은 값을 설계 제약으로 사용 |
| 중간 단계(2%) | — | CacheGen 헤드라인 ≤2%(E6), KVzip chunk 변동 <2%(E8)뿐 | **약함: 허용 한도로 정의한 문헌 없음. 별도 단계로 두지 않기를 권장** |
| 3% 초과 | **미충족** | 허용으로 정의한 문헌·표준을 찾지 못함. 관측값은 있음(KIVI task 최악 5.3%, DuoAttention 13.9%) | — |

별을 3단계로 유지해야 하면 중간 경계는 근거가 없으므로 (a) 2%(산술 중간, 문헌 근거 없음) 또는 (b) 별 2개만 사용 중 사용자가 정해야 한다(§7 Q-1). 이 문서는 (b)를 권장한다.

**지표 정의도 문헌에 맞춘다:** MLPerf는 "reference 대비 %"이므로 **상대 하락**(기준 = 같은 모델·task·precision의 압축 전 full 결과)이 맞다. CacheBlend처럼 절대 F1 차이로 보고한 논문과 비교할 때는 기준 F1을 알아야 상대로 환산할 수 있다(E7 주의).

## 5.2 품질 시나리오 DP3-QS-12 (6요소)

#### DP3-QS-12  Functional correctness × Capacity — 정확도 한도 안에서의 Max SLO goodput   (구분: 선정, DP3-QA1 + DP3-QA4 결합)

| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 다수의 agent/RAG 세션 클라이언트(long-context 재사용 요청), 평가 시에는 부하 생성기와 task 정확도 평가기 |
| 2. 자극 | 문맥 8K~256K token의 재사용 요청이 Baseline 용량의 0.5×~8× 도착률로 들어오고, 압축 유지 비율 r이 정책 변수로 주어진다 |
| 3. 환경 | SYS-H100·SYS-B200, Llama-3.1-70B BF16(TP8), HBM이 KV 전체를 못 담는 과부하 구간, 정상 모드. 정확도는 같은 모델 계열·task·precision의 압축 전 결과를 기준으로 측정 |
| 4. 자극 대상체 | DP3 압축 KV 선택 모듈(Recompute Token Selector, Selective Recomputer, Comp.KV 정책)과 정확도 검증·fallback(DP3-FR-10) |
| 5. 응답 | 정확도 gate를 통과하는 r에서만 압축을 적용해 SLO(TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms) 하의 최대 처리량을 올리고, gate를 통과하지 못하면 압축을 해제(full KV)하거나 r을 늘린다 |
| 6. 응답 측정 | 아래 표 |

| 항목 | 목표 | 측정 조건 | 근거 | 라벨 |
|---|---|---|---|---|
| (a) 정확도 gate — 최소 | **상대 하락 ≤ 3%** | task별로 분리(단일 평균 금지), 95% CI **상한** ≤ 3% | E1(97%), E3, E4 | [기준] 문헌 |
| (a') 정확도 gate — 목표 | **상대 하락 ≤ 1%** | 동일, CI 상한 ≤ 1% | E1(99%), E2, E5 | [기준] 문헌 |
| (b) task별 gate | 각 task가 같은 한도를 따로 만족. 평균 통과·task 위반은 **미충족** | task ≥ 3종(단락 QA, 요약·다중 hop, 코드류) | E3 Table 1(평균 97% 통과인데 task −5.7%), E10 | **[가정]** 문헌은 평균만 보고. MLPerf가 행의 각 지표를 따로 기준화한다는 점만 근거 |
| (c) 처리량 — 최소 | gate (a) 통과 조건에서 **Max SLO goodput ≥ 2.0× Baseline** | 32쌍 기하평균, seed ≥ 5, `PYTHONHASHSEED` 고정, 부하 sweep | 문헌 iso-accuracy 이득의 하한 ≈ 2×(E4 2.0×, E8 ≈2×, E7 TTFT 2.2×). Stakeholder 요구 2×(PPT, 다른 baseline: GPU-only)와도 일치 | [기준] 문헌 + [DP문서] |
| (c') 처리량 — 목표 | gate (a') 통과 조건에서 **≥ 3.6×** | 동일 | E4 상한 3.6×, E7 3.3×(prefix caching 대비, 우리 Baseline에 가까움). 5×(E5 4.82×, E7 5×)는 "up to" 최대값이라 목표로 쓰지 않음 | [기준] 문헌, baseline 불일치 주의 |
| (d) 측정 표본 | 후보·task별 예시 n ≥ **4,300** | CI 반폭 ±1%(상대)를 얻기 위한 값, 실측 SD 0.24 기준 | 통계식(우리 실측). MLPerf 평가 데이터셋(QSL) 크기 824~24,576 범위와 같은 자릿수 | [가정] 실측 SD 의존 |
| (e) 꼬리 점검 | Baseline보다 나쁜 쌍(P99 TTFT/goodput)의 수와 최악 쌍 보고 | 기존 평가 방식 | evaluation skill §10 | [기준] |
| 연결 | DP3-QA1, DP3-QA4, UC-2, DP3-FR-03·07·10, DP3-C-4. 평가: `Evaluation/DP3/results/2026-10-28_dp3-accuracy-throughput-evidence.md` |

**현재 측정과의 대조(요구가 아니라 gap):** C1 Offline은 측정한 모든 r에서 F1 하락 12.5~39%로 3% 한도를 넘는다. C2 Online은 점추정은 한도 안이나 CI 반폭 1.5~7.3%(n=93)라 인증되지 않고, goodput은 r=0.1에서도 ×1.35라 2.0×에 못 미친다. 문헌과 같은 설정으로 비교하면 R_acc(3%) = ×1.0(인증형)이다.

# 6. 찾지 못했거나 확인하지 못한 것

1. **F1 같은 task 정확도 제약 하의 SLO goodput**을 같은 설정으로 보고한 논문. EVICPRESS가 가장 가깝지만 "품질 점수 80% 목표"이고 SLO 기반 goodput이 아니다.
2. **1%, 3%라는 값이 통계적으로 왜 허용 가능한지**를 설명하는 문헌. MLPerf는 규칙으로 정할 뿐 근거를 적지 않았고(내가 읽은 규칙 문서 범위), KVServe의 97% 선택 이유도 확인하지 못했다. 즉 **이 값들은 "업계가 쓰는 값"이지 "데이터로 도출된 값"이 아니다.**
3. **KV 압축의 task별 상대 하락(%)**: KVzip(그림), CacheBlend(그림)는 수치를 확인하지 못했다. CacheBlend는 절대 F1 차이만 확인.
4. **Quest, H2O의 처리량·정확도**: Quest abstract의 수치가 HTML 수식에서 추출되지 않아 쓰지 않았다. H2O 초록의 처리량 배수("up to ... on OPT-6.7B and OPT-30B")와 "20% heavy hitters"도 같은 이유로 수치가 추출되지 않았다(요약 도구로는 29×/29×/3×로 보였으나 원문 확인 전이라 쓰지 않았다). H2O의 정확도 수치도 확인하지 못했다. 이 논문들의 이득은 서로 다른 시스템 대비라서 이 표에 넣지 않았다.
5. **검색 요약에만 있던 것은 쓰지 않았다**: MosaicKV(평균 1.76% 손실, 7.3× 처리량), MiniKV, CompressKV는 원문을 확인하지 못해 제외했다.
6. 위 논문들은 대부분 **A100/H100 단일 노드, 7~8B 모델**이다. 우리 70B TP8 시뮬레이션과 규모가 다르다.
7. **우리 정확도 실측**은 1.5B 모델·단일 task·n=93이라 이 목표의 인증에 쓸 수 없다(`evidence` 문서 §4.3).

# 7. 사용자 확정 필요

| ID | 질문 | 현재 가정 | 영향 |
|---|---|---|---|
| Q-1 | 정확도 단계: 문헌이 지지하는 **2단계(≤1% 목표, ≤3% 최소)**로 갈 것인가, 3단계가 필요하면 중간(2% 등)을 무근거 정책값으로 둘 것인가 | 2단계 | 별점 정의 |
| Q-2 | task별 gate(§5.2 b)를 요구할 것인가, 평균 gate(문헌 관행)로 할 것인가 | task별(보수적) | 합격 판정 |
| Q-3 | 처리량 목표를 2.0×(최소)/3.6×(목표)로 할 것인가. 기준 baseline은 DP3의 "전체 KV 재사용"이며 PPT 55p의 GPU-only와 다르다 | 2.0× / 3.6× | 달성 판정 |
| Q-4 | R_acc를 공식 지표로 등록할 것인가(결과를 보기 전 정의 필요) | 임시 정의 | 별점 |
| Q-5 | 정확도 측정 확대(n ≥ 4,300, task 3종 이상, 7B 이상 모델)를 진행할 것인가 | 필요 | gate 인증 가능 여부 |
| Q-6 | `dp3sim.py` 해시 시드 결함 수정과 기존 DP3 결과 재생성 | 수정 안 함 | 재현성 |

# 8. 읽은 입력

PPT 10, 55, 56, 67, 73p 텍스트(추출). 원문 직접 확인: MLCommons `inference_rules.adoc`, arXiv 2310.07240, 2405.16444, 2505.23416(v2), 2411.02355(v3), 2412.10319, 2407.01527, 2306.14048, 2605.13734, 2512.14946, 2502.01068(v2). 읽지 못한 것: 67p [1]의 KVzip 발표 페이지, PPT 55p가 인용한 InferCept·LMCache·Pensieve 원문.
