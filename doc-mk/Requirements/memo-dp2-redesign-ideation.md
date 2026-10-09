# 메모: DP2 재설계 ideation 정리 (다른 AI에게 의견을 구하기 위한 자기완결 문서)

> 작성: 2026-10-09. 상태: **논의 기록, 미확정**. 사용자(AI SW 연구원)와 Claude가 한 세션에서 나눈 DP2 재설계 논의를 한 문서로 모았다. 이 문서만 읽고도 맥락을 알 수 있도록 썼다. 선행 메모: [`memo-dp2-dp4-boundary.md`](memo-dp2-dp4-boundary.md).
> 표기: **[사용자 결정]** 사용자가 정한 것 / **[Claude 제안]** 아직 사용자가 확정하지 않은 제안 / **[추정]** Claude의 계산·추론(검증 안 됨) / **[문서 근거]** repo 문서에서 읽은 사실.

## 0. 이 문서로 다른 AI에게 묻고 싶은 것

1. 아래 §4의 **DP2 재정의**(P/D를 구분하지 않는 attention 연산 배치 결정)는 타당한가? 빈틈이나 더 나은 정식화는?
2. §7의 **후보 구조**(X1 이동 후 GPU 연산 / X2 Tier 제자리 연산 / X3 분할-병합)는 적절한가? 빠진 후보나 현실성 문제는?
3. §6의 **QA 선정**(QA1·QA2·QA3 유지, QA4·QA5 제외)과 QA3 정의(HBM 점유율, 낮을수록 좋음)는 적절한가?
4. §9의 **미결 질문**에 대한 의견.

답할 때 [사용자 결정]은 전제로 두고, [Claude 제안]과 [추정]을 비판적으로 검토해 달라. 수치는 모두 가정이 붙은 추정이다.

## 1. 프로젝트 맥락

- 과제: 계층적 메모리 시스템(HBM, DRAM, SSD, CXL, HBF, 연산 가능 메모리인 ScHBM·CXL-PNM·PIM 등)에서 **메모리를 효율적으로 써서 LLM serving 성능을 높이는 런타임**. 엔진은 vLLM 고정. 초점은 **스케줄링(무엇을, 어디에, 언제 둘지·실행할지의 결정)** 이다. 전송·commit·driver 같은 실행 메커니즘은 주어진 것으로 본다.
- 환경: GPU 8장 서버 2대(서버 간 PCIe 64 GB/s), HBM·DRAM·SSD는 실장, HBF·ScHBM·PIM·CXL-PNM은 **시뮬레이션**(성능은 profile 값). 노드 = 8-GPU TP8 vLLM 인스턴스 1개. 모델 Llama-3.1-70B BF16(64 query head, 8 KV head, 80 layer). 기본 SLO: TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms.
- 제약: 연산 가능 메모리의 kernel·compiler는 범위 밖이며 **지원 연산과 성능은 profile 값으로 주어진다**(GC-5). 지원 연산은 attention 계열뿐(QK_GEMM, SOFTMAX, AV_GEMM, CAUSAL_MASK). 모델 출력은 위치와 무관하게 동일해야 한다(bit-exact). device runtime 오버헤드는 고려하지 않는다. 학습·보안·장애 복구는 범위 밖.
- Design Point(DP) 구분:

| DP | 결정하는 것 |
|---|---|
| DP1 | 데이터를 어느 메모리 Tier로, 언제 이동할지 (evict, promote, prefetch). 단일 노드 안 |
| DP2 | (이 문서의 대상) 연산을 어디서 실행할지. 아래 §4에서 재정의 |
| DP3 | KV에서 무엇을 제거·재사용하고 어떤 토큰을 재계산할지 |
| DP4 | 멀티 노드에서 요청을 어느 서버로 보내고 P/D를 어떻게 분배할지 |

## 2. 출발점: DP2와 DP4의 경계가 모호했다

**[문서 근거]** 기존 DP2는 Turn마다 Prefill 위치 `n_p`와 Decode 시작 위치 `n_d`를 하나의 `ExecutionPlan`으로 결정한다(`n = (노드, 노드 안 자원)`). 후보를 가르는 변수는 **결정 시점**이다.
- C1: Scheduler가 request·token budget을 확정한 시점에 최신 상태로 inline 결정.
- C2: waiting 중 background planner가 ranked candidate를 캐시하고 dispatch 직전 Late Validation(hard/soft 조건)을 거치며, 실패 시 백업 후보 → 동기 재계획 → 기본 vLLM 경로로 폴백.
- 평가(시뮬레이션 [B+C], 실측 아님) 결과 C1과 C2는 별 합계 13 대 13 동점이었다. 확장성 QA5만 크게 갈렸다(η(N=32): C1 0.00, C2 0.56, top-k=8이면 C1 1.00, C2 0.94).

**[문서 근거]** 기존 DP4는 여러 vLLM 인스턴스 위의 요청 조율 계층(cluster level)이며, 후보는 OSS(llm-d 등) 확장 대 자체 구현이다. 정책 P1~P5(Tier 가중 적중 점수, 상태 반영, 비용 기반 적중 점수, 비용 기반 P/D 판단, 요청별 노드 지시)는 DP2의 Cost Model(`Tmove`, `Tprefill` 항)과 겹친다.

**문제**: 두 DP가 모두 per-request 결정이고 정보 해상도와 "플랫폼이냐"만 다르다. 사용자는 "DP4가 설계 이슈가 아니라 구현 이슈처럼 보인다"고 지적했다.

**관찰 [문서 근거]**: P-retain(Prefill을 History가 있는 노드에서 유지하는 단순 휴리스틱)이 QA2에서 C1보다 높았다(x1.80 대 x1.58). Baseline-PD-fixed가 SLO를 거의 못 지키게 설계된 시나리오가 이득을 키웠다(DP2-C-11).

## 3. 논의 경과 (요약)

1. 연결 방식 ①(DP2 = 노드 안, DP4 = 노드 간 확장)과 ②(DP2 = 노드·자원 전부, DP4 = 플랫폼)가 제시되었다. Claude가 ③(DP4가 후보 노드를 줄이고 DP2가 최종 결정)과 ④(DP2는 요청 단위, DP4는 pool 단위)를 추가했다.
2. "노드 안에서 P/D 분리를 적용할 수 있는가"를 검토했다. 방식은 (a) 인스턴스 분리(NVLink로 KV 전달, vLLM이 이미 지원), (b) GPU 내부 공간 분할(SM partition), (c) 시간 분할(chunked prefill), (d) **연산자·자원 단위 분리**(Decode attention을 KV가 있는 Tier에서 실행)이다. **(d)가 이 과제의 핵심**이라는 데 사용자가 동의했다.
3. 사용자가 **P/D 어휘를 DP2에서 제거**하고 "연산(attention)을 어디서 실행할지"로 재정의하자고 제안했다(§4).
4. 사용자가 처리량 관점을 강조했다. KV를 HBM으로 끌어오는 것은 단일 요청 지연에는 유리해도, 동시성이 높으면 HBM 용량·대역폭·링크를 소모해 처리량이 떨어진다(§5).
5. Claude가 제안한 iteration 단위 스케줄링, 배치 분할(ping-pong), layer 스트리밍은 **사용자가 비현실적이라고 기각**했다(§7.2). 남은 것은 Turn 시작 시 KV 구간별 실행 자원 배정뿐이다.
6. QA 재선정(§6)과 "결정 이후 실행 방식"에 대한 후보 구조 제안(§7.3)으로 이어졌다.

## 4. 재정의된 DP2 (연산 배치 관점)

- **[사용자 결정]** DP2는 P, D, disaggregation을 구분하지 않는다. DP2의 질문은 "**attention 연산을 (KV 구간별로) 어디서 실행할 것인가**"이다. DP1이 메모리에 데이터를 배치한 위치를 입력으로 삼아 실행 위치를 정한다.
- **[사용자 결정]** 연산 범위는 **attention으로 한정**한다. 연산의 시작은 항상 GPU(QKV 투영, FFN 등)이고 attention만 메모리 측으로 이동할 수 있다.
- **[사용자 결정]** DP2는 **노드 내** 결정이다. **DP4는 이를 멀티 노드로 확장**해 P 노드와 D 노드를 어떻게 분별할지를 다룬다.
- **[사용자 결정]** DP1과 DP2는 순차 결정이 아니다. **DP1은 DP1대로, DP2는 DP2대로 따로 평가**한다(통합 단계에서 결합 효과를 본다).
- **[Claude 제안]** 노드 역할(P형/D형)은 DP2의 배치 후보 공간에 가하는 제한으로 정식화할 수 있다. 그러면 DP4의 P3·P4와 DP2의 Cost Model 중복이 사라진다(Cost 함수는 DP2가 소유하고 DP4는 거친 입력으로 호출).
- **[Claude 제안]** 소유권 구분: DP1 = 이동 후 데이터가 **남는** 것(영속 배치), DP2 = 실행을 위한 **일시적 staging**(연산 후 폐기).
- **주의 [문서 근거]** `project-scope.md` S-16은 노드 간 데이터 이동을 DP4 소관으로 둔다. 이 틀이면 DP4는 노드 간 데이터 이동과 연산 배치를 함께 다루는 확장이 되어 범위가 커진다.

### 4.1 P/D 구분이 사라지는 이유 [추정]

attention의 연산 강도는 대략 **Tq × 8 FLOP/byte**(GQA 8, KV BF16)이다. Decode(Tq=1)는 약 8로 완전한 memory-bound이고, H100의 ridge point는 약 300(990 TFLOPS ÷ 3.35 TB/s)이므로 Tq가 약 40을 넘으면 같은 attention이 GPU에서 compute-bound가 된다. Prefill과 Decode는 별개 범주가 아니라 Tq에 따른 연속 구간이다. 실질적 차이는 Tq 말고 **데이터 재사용 횟수**다(Prefill의 attention은 1회, Decode는 출력 길이만큼 같은 KV를 반복해 읽음).

## 5. 처리량 관점: 왜 "끌어오기"가 항상 이득이 아닌가

**[사용자 주장]** CXL 등에 있는 KV를 HBM으로 가져와 GPU에서 계산하는 편이 단일 요청에는 빠를 수 있다. 하지만 동시성이 높으면 가져오는 것 자체가 비용이다. 그래서 지연만 보면 손해로 보여도 처리량으로는 이득일 수 있다.

**[Claude 정련]** "다음 요청을 모르니 HBM을 비운다"보다 **기회비용**으로 설명한다.
1. HBM 용량: 그만큼 running batch의 KV 자리가 줄어 Decode batch가 작아진다.
2. HBM write BW 소모.
3. 공유 링크의 직렬 상한: 128K 컨텍스트의 KV는 약 320KB/token × 131,072 ≈ **43GB** [추정]. PCIe 64 GB/s에서 링크 하나가 처리할 수 있는 끌어오기는 약 1.5건/s다. 이는 GPU와 무관한 상한이다.

그래서 Cost의 목적함수가 부하에 따라 달라진다. 저부하에서는 자원 가격이 거의 0이라 지연 최소화(끌어오기)가 맞고, 고부하에서는 가격이 올라 제자리 계산이 유리하다. **교차점이 어디인가**가 DP2의 핵심 결과가 된다.

**break-even 스케치 [추정]**: 가정은 Llama-70B, History 128K, 링크 64 GB/s, 전 layer 일괄 이동, 겹침 없음, 메모리 측 FLOPS는 profile(ScHBM 198 TFLOPS, CXL-PNM 3.3 TFLOPS)이다. History KV를 GPU로 옮기는 데 약 0.67초, 128K에 대한 attention FLOPs는 Tq 1토큰당 약 0.34 TFLOP이다. 제자리 계산이 이기는 조건은 Tq가 ScHBM에서 약 390 이하, CXL-PNM에서 약 6 이하이다. 즉 CXL-PNM에서 제자리 계산이 이득인 영역은 사실상 Decode 한정이다. 링크 경합, partial attention 병합 비용, GPU와의 겹침 실행은 반영하지 않은 방향성 값이다.

## 6. QA 논의 결과

**[문서 근거]** 기존 DP2 QA: QA1 Throughput(Max SLO Goodput), QA2 Latency(P99·P50), QA3 Resource Utilization(useful P/D 풀 GPU 사용률, 높을수록 좋음), QA4 Modifiability, QA5 Scalability(노드 수 N=32에서 η). DP1의 QA3는 HBM 사용량(낮을수록 좋음)이라 DP 간 정의가 달랐다.

**최종 방향**
- **[사용자 결정] QA1, QA2, QA3을 본다.**
- **[사용자 결정] QA3 = HBM 점유율, 낮을수록 좋음.** 근거: GPU를 많이 쓰는 것은 QA1/QA2의 영역이며, 같은 처리량·지연이라면 HBM을 덜 쓰는 편이 좋다. DP1의 QA3와 정의가 같아져 DP 간 불일치도 해소된다.
  - **[Claude 보정]** iso-load와 SLO 통과를 조건으로 비교해야 한다. 그렇지 않으면 batch가 작아서 낮은 점유율이 좋은 점수로 나온다. weight는 고정이므로 KV 및 staging 점유를 본다.
- **QA2를 남기는 이유 [Claude]**: QA1은 SLO 임계값을 넘는 비율이라 분포가 SLO 안쪽이면 후보 간 차이가 안 보인다. QA2는 그 구간을 본다. 꼬리를 봐야 하는 시나리오는 (1) 잘못 배치된 요청이 Decode 내내 TPOT 꼬리를 만드는 경우(기존 결과에서도 QA1 x1.66인데 TPOT 개선 배수 x0.89), (2) HBM 압박으로 대기·강등이 생기는 사건의 TTFT 꼬리, (3) agent 멀티턴에서 세션 시간이 꼬리에 지배되는 경우(20턴이면 P99 턴을 한 번이라도 만날 확률 약 18%)이다.
- **QA4 제외 [사용자]**: 신규 메모리는 Cost Evaluator에 위치 정보를 plug-in하면 된다. **[Claude 보정]** 제외 기준은 "후보 간에 차이가 나는가"이며, 기존 결과(C1 1.50 모듈, C2 1.75 모듈 모두 ★★★)는 변별력이 없었다. 다만 학습 기반 후보를 넣으면 신규 Tier마다 재학습이 필요해 변별력이 생긴다. 확장 가능성은 제약(FR-08)과 smoke 검증으로 남긴다.
- **QA5 제외 [사용자]**: 노드 수 확장성은 DP4로 이동했다. **[Claude 보정]** 노드 수와 무관하게 attention 구간 단위로 결정하면 step당 결정 횟수가 늘어나므로 **결정 비용 민감도**(0.1/1/10 ms)를 QA1 sweep에 포함하길 권한다.
- 지연을 별점이 아니라 SLO 게이트로만 두자는 Claude의 초기 제안은 사용자의 최종 결정(QA2 유지)으로 대체되었다.

## 7. 후보 구조

### 7.1 기존 후보: 결정 시점 (C1/C2)
- **[사용자]** "후보 구조는 기존 그대로 가자."
- **[Claude 의견, 미검증]** 노드 내 + Turn 단위로 한정하면 후보 수가 Tier 수(대략 4 이하)라 결정 비용이 무시할 만하고, C2의 존재 이유(결정 지연 숨기기)가 사라져 C1이 항상 앞설 가능성이 높다. QA5를 빼면 C1/C2를 가르는 QA가 남지 않는다(QA1 954/956 tok/s, TTFT P99 984/1015 ms로 기존에도 거의 동점). **이 가설은 시뮬레이션으로 확인하지 않았다.**

### 7.2 기각된 후보 (사용자가 비현실적이라 판단)
Claude가 제안했던 S-B(iteration 경계마다 GPU와 메모리 측에 attention 분배), S-C(배치를 둘로 나눠 한쪽은 GPU dense, 다른 쪽은 메모리 측 attention을 겹침), S-D(layer 단위로 KV를 HBM ring buffer에 스트리밍)는 기각했다. 이유: 연산은 항상 GPU에서 시작해야 하고, 남는 현실적 구조는 **Turn 시작 시 KV 구간별 실행 자원 배정**(S-A)뿐이다.

### 7.3 [Claude 제안, 미확정] 결정 이후의 실행 방식(How to compute) 후보

배정이 정해졌다고 할 때 attention을 어떻게 실행할지의 후보. 제약: GPU에서 시작, Turn 단위 배정, layer 스트리밍 없음. 오프로드 단위는 fused attention(q 전송, o 수신)만 현실적이다(QK만 오프로드하면 반환 점수 크기가 컨텍스트 길이에 비례).

| 후보 | 구조 | QA1 (고동시성) | QA2 (꼬리) | QA3 (HBM 점유) |
|---|---|---|---|---|
| X1 이동 후 GPU 연산 | KV 구간을 HBM의 임시 staging 영역으로 적재 후 GPU attention (HBF는 직접 읽기 변형) | 링크 상한과 HBM 압박으로 붕괴 | 저부하에서 최선 | 최악 |
| X2 Tier 제자리 연산 | q를 메모리 측으로 보내 fused attention, o 수신. HBM 상주 시퀀스의 GPU attention과 병렬 실행 | 최선 (메모리 측 포화 전까지) | TPOT 꼬리 악화 위험 | 최선 |
| X3 분할-병합 | KV가 여러 Tier에 걸치면 Tier별 부분 attention 후 (m, l, o)를 log-sum-exp로 병합 | 중간 | 중간 | 중간 |

(위 표의 QA 평가는 정성적 추정이다.) X1과 X2는 QA1·QA3 대 QA2에서 반대로 움직이므로 QA1·QA2·QA3을 모두 보는 의미가 이 축에서 생긴다. X3은 X1/X2를 구간별로 혼합하는 일반화이며 부분 결과를 내는 kernel이 주어졌다는 가정이 필요하다(GC-5).

## 8. 평가 시 알아야 할 시뮬레이터 사실 [문서 근거: `Evaluation/DP2/m0-spec.md`, `sim/configs/dp2_params.json`]

- KV 풀 용량 제약이 모델링되어 있다(A08). HBM 풀이 부족한 승격은 idle LRU 세션을 다음 Tier로 강등해 자리를 만들고, 후보가 없으면 요청이 대기한다(A24). 따라서 HBM 압박 메커니즘은 시뮬레이션에서 나타날 수 있다.
- **확인 필요**: 고동시성에서 병목이 HBM 풀인지, `max_num_seqs=256`(A06c)이나 token budget 8192(A06b)가 먼저 걸리는지. 후자라면 용량 효과가 가려진다.
- staging과 연산은 **순차(overlap 없음)** 로 모델링되어 있다(보수적). 겹침 실행을 평가하려면 확장이 필요하다.
- 오프로드 Prefill attention은 PNM 연산(3.28 TFLOPS)으로 비현실적이라 허용하지 않는다(m0-spec 4.3). 노드 내 attention 오프로드는 Decode 위주다.
- Decode 가능 Tier: `hbm`, `custom_hbm`, `cxl_pnm`, `hbf`. `dram`, `ssd_pim`은 Decode 불가하며 blocking swap-in 후 HBM에서 Decode(A14).
- 현재 시뮬레이터는 Turn 단위 `(n_p, n_d)` 모델이라, KV 구간 단위 배치로 바꾸려면 확장이 필요하다. `sim-extension-scope.md`는 읽지 못했다.
- 모든 값은 시뮬레이션 [B+C]이며 실측 [A]가 아니다. 노드 간 링크는 RDMA(ASSUMED)로, 사용자 환경(PCIe 64 GB/s)과 다르다(DP2-C-6).

## 9. 미결 질문 (다른 AI에게 특히 의견을 구함)

1. **후보 축**: X1/X2/X3(실행 방식)을 DP2의 주 후보 축으로 삼는 것이 적절한가? 사실상 "X1 대 X2"는 배치 결정 자체의 결과이지 "결정 후의 실행 방식"이 아니라는 반론이 있을 수 있다. 더 나은 축은?
2. **X3의 현실성**: 부분 attention 병합(log-sum-exp)을 kernel이 지원한다는 가정(GC-5)은 허용 가능한가? 이 가정 없이도 의미 있는 후보가 있는가?
3. **결정 시점(C1/C2)**: 노드 내 + Turn 단위에서 C1/C2가 사실상 의미를 잃는다는 추정이 맞는가? 보조 축으로 남길 가치가 있는가?
4. **QA3 정의**: HBM 점유율(KV·staging, iso-load, SLO 통과 조건)이 충분한가? 점유 "평균" 대 "peak" 중 무엇을 쓸 것인가? 링크 바이트도 자원 지표에 포함해야 하는가?
5. **QA4·QA5 제외**: 근거(후보 간 변별력 없음, 노드 확장성은 DP4)가 충분한가? 결정 비용 민감도를 QA1 sweep에 넣는 방식으로 충분한가?
6. **DP1/DP2 경계**: 영속 배치(DP1) 대 일시 staging(DP2)의 구분이 실제 시스템에서 깔끔히 서는가? 같은 HBM·링크를 쓰므로 상호작용이 1차 효과인데, 따로 평가한 뒤 통합 단계에서 2×2(DP1 on/off × DP2 on/off)로 본다는 계획은 충분한가?
7. **DP4 확장**: 노드 역할(P형/D형)을 "DP2 배치 후보 공간의 제한"으로 정식화하는 것이 DP4를 설계 질문으로 만드는가? 노드 간 데이터 이동까지 DP4가 맡는 범위 확대(S-16)는 적절한가?
8. **평가 가능성**: 이 재정의가 기존 DP2 평가 자산(QS-2 세션 재개, QS-3 long-context)을 어디까지 살리는가? QS-1(P 포화, 링크 경합)과 QS-4(P 유휴)는 노드 간 현상이라 DP4로 옮겨야 하는가?

## 10. 근거 자료 위치와 읽지 못한 것

- 읽은 것: `Requirements/memo-dp2-dp4-boundary.md`, `Requirements/DP2-requirements.md`, `Requirements/project-scope.md`, `Requirements/DP4-requirements.md`(앞 80줄), `Evaluation/DP2/m0-spec.md`(일부 발췌), `Evaluation/DP2/sim/configs/dp2_params.json`(일부).
- **읽지 못한 것**: `DP0-1/`(요청 조율 계층의 중앙 결정형 S1 대 2단계 위임형 S2 비교, 사용자 지시로 무시했으나 경계 논의와 관련이 클 수 있음), `Evaluation/DP2/sim-extension-scope.md`, simulator 코드(`sim/dp2sim/`), DP2 설계 문서 `DP2/*.md` 원문, 결과 문서의 §1 이후.
- 위 수치와 추정(§4.1, §5, §7.3 표, §7.1 가설)은 시뮬레이션이나 실측으로 검증하지 않았다.
