---
date: 2026-10-04
dp: DP4
candidates: [C1-central-serialization, C2-distributed-lock]   # Baseline-RDMA 포함
sys_ids: [SYS-H100, SYS-B200]   # 통합 INT-H100-B200
git_rev: cb98109 (dirty flags as recorded in data meta: INT dirty, SYS-H100 clean, SYS-B200 dirty)
evidence: { QA1: "[B+C]", QA2: "[B+C]", QA3: "[B+C]", QA4: "[B+C]", protocol_check: "[C]" }
status: draft
---

# DP4 QA Evaluation — C1 중앙 직렬화 vs C2 분산 락 (비일관 CXL 공유 메모리 KV 일관성 구조)

> 기준 문서: [`qa-evaluation-criteria.md`](../../qa-evaluation-criteria.md), [`common-benchmark.md`](../../common-benchmark.md), [`system-specs.md`](../../system-specs.md), [`DP4/benchmark.md`](../benchmark.md), [`DP4/simulation-plan.md`](../simulation-plan.md), [`qa-criteria-dp4.md`](../qa-criteria-dp4.md), [`qa4-preregistration.md`](../qa4-preregistration.md)
> 절차: `.claude/skills/evaluation/SKILL.md`. 이 문서의 모든 simulation 수치는 Evidence [B+C]이며 [A] 실측이 아니다(CXL 공유 풀 하드웨어 없음). model check는 [C]. 이 문서는 `tools/gen_dp4_result.py`가 `results/data/`에서 생성했다(같은 데이터에서 두 번 돌리면 같은 출력).

# 0. 최종 요약

> 발표용 요약이다. H100과 B200 두 세대를 **하나로 통합**했고(시나리오 x 시스템 쌍이 단위), 별점은 사전 등록된 공통 기준(`qa-evaluation-criteria.md`, Common Benchmark 6쌍)이다. 근거 표는 4장, 분석은 5장, 한계는 6장. **이 DP의 선택 질문은 'CXL 풀을 쓸 것인가'가 아니라 'CXL 풀 위에서 메타데이터 일관성의 책임을 누가 지는가(C1 중앙 직렬화 vs C2 분산 락, control plane 책임)'이다.** C1과 C2의 별점 차이는 QA4에서만 나오며 0.5 man-month 경계 근처이고, 두 후보가 Baseline-RDMA보다 낮은 QA1~QA3의 격차는 일관성 구조가 아니라 **data plane 상수**에서 온다.

## 0.1 QA별 비교

| QA | 평가 metric | Baseline (T_ref) | C1 중앙 직렬화 | C2 분산 락 |
|---|---|---:|---|---|
| **QA1 Throughput** | Max SLO goodput (tok/s) ↑ | 589 (Baseline 별 ★★) | **★** 415 (x0.704 ±0.032) [B+C] | **★** 415 (x0.704 ±0.032) [B+C] |
| **QA2 Latency — TTFT** (각 arm의 Max-goodput load) | TTFT (ms) ↓ | P99 6,283 · P50 1,009 | P99 4,205 (x0.67) · P50 907 (x0.90) [B+C] | P99 4,205 (x0.67) · P50 907 (x0.90) [B+C] |
| **QA2 Latency — TTFT** (공통 load = Baseline peak load) | TTFT (ms) ↓ | P99 6,283 · P50 1,009 | P99 31,271 (x4.98) · P50 6,548 (x6.49) [B+C] | P99 31,271 (x4.98) · P50 6,549 (x6.49) [B+C] |
| **QA2 Latency — TPOT** (각 arm의 Max-goodput load) | TPOT (ms) ↓ | P99 4.07 · P50 4.07 | P99 4.04 (x0.99) · P50 3.99 (x0.98) [B+C] | P99 4.04 (x0.99) · P50 3.99 (x0.98) [B+C] |
| **QA2 Latency — TPOT** (공통 load) | TPOT (ms) ↓ | P99 4.07 · P50 4.07 | P99 4.04 (x0.99) · P50 4.04 (x0.99) [B+C] | P99 4.04 (x0.99) · P50 4.04 (x0.99) [B+C] |
| QA2 별점 | 6쌍 중 최악 P99 (criteria §5: <=2 s & <=50 ms ★★★, <=4 s & <=100 ms ★★) | ★ (TTFT 28,234 · TPOT 6.4) | **★** (TTFT 80,568 · TPOT 6.4) [B+C] | **★** (TTFT 80,568 · TPOT 6.4) [B+C] |
| **QA3 Resource usage** | 클러스터 KV 상주 메모리 (GiB, 시간 평균, Baseline peak load) ↓ | 15.9 (Baseline 별 ★★) | **★** 71.3 (x4.48; 절감 배수 x0.22) [B+C] | **★** 71.3 (x4.49; 절감 배수 x0.22) [B+C] |
| **QA4 Modifiability** | 변경 module 수 · 공수(man-month) · 에이전트 비용($, frontier tier), 시나리오 4종 평균 ↓ | — | **★★★** 2.25 · 0.46 · $1.21 (sub-star ★★/★★★/★★★) [B+C] | **★★** 2.25 · 0.51 · $1.35 (sub-star ★★/★★/★★★) [B+C] |
| **별 합계** (QA1..QA4) | | — | **6** | **5** |

**평가한 시스템:** **SYS-H100** (H100x8, HBM3 (H100 SXM5 80GB), PCIe 5.0, CXL 2.0 (PCIe 5.0 PHY)); **SYS-B200** (B200x8, HBM3e (B200), PCIe 5.0, CXL 2.0 (PCIe 5.0 PHY)). 시스템당 P/D 분리 클러스터(CB 기본 P 1대 + D 1대, 노드 = GPU 8장), Llama-3.1-70B BF16(KV 327,680 B/token), 두 시스템을 **통합**했다(통합 결과 하나, 시나리오 x 시스템 쌍이 단위). 별점의 집계 단위는 **Common Benchmark 6쌍**(CB-1~3 x 2시스템, 모두 comparison-valid; 사전 등록 규칙: 공통 별점은 Common set에서만 산출). DP4-specific는 38쌍(비교 가능 37, 포화 1, 비교 불가 0)이며 diagnostic과 QA4 근거로만 쓴다. 값은 쌍별 값의 **기하평균**, 괄호는 **후보 ÷ Baseline 배수**(↑ 높을수록 좋음, ↓ 낮을수록 좋음), QA1의 ±는 seed 묶음 기하평균의 95% CI(t=2.776, 5 seeds)이다. Evidence [B+C]; QA4는 [B+C] proxy 구현.

**메모리 구성** (H24: 용량 · host 연결과 세대 · 대역폭 · 연산 능력과 지원 연산 · 시뮬레이터 반영 여부):

| 메모리 / 경로 | 용량 | host 연결 (세대) | 대역폭 | 연산 능력 (FP16) · 지원 연산 | 시뮬레이터 반영 |
|---|---|---|---|---|---|
| HBM (노드의 GPU 8장 합) | H100 640 GiB (HBM3) / B200 1,536 GiB (HBM3e) | GPU on-package (host CPU와는 PCIe 5.0) | H100 26.8 / B200 64.0 TB/s (노드 합) | GPU FP16 dense 989 / 2,250 TFLOPS/GPU, attention·FFN 실행 | decode step·prefill 시간(DP1 물리 재사용), 잔류량 집계. **용량 한계(OOM)는 미반영** |
| CXL 공유 풀 (후보 C1·C2의 KV 저장소) | 8 TiB | CXL 2.0 (PCIe 5.0 PHY) 스위치 풀, 노드당 어댑터 2개 x PCIe 5.0 x16 | 어댑터 63 GB/s x 2 = 노드당 126 GB/s (방향별), 풀 집계 1 TB/s, 유효 효율 η_cxl 0.5 (ASSUMED) → 노드 유효 63 GB/s | 없음 (순수 저장소) · 지원 연산 없음 | 대역폭(η 포함), 접근 지연의 control plane 비용, 풀 점유율(퇴출 연산). 스위치 혼잡·bank 경합은 **미반영** |
| RDMA NIC (Baseline-RDMA의 KV 경로) | — (전송 버퍼만) | 노드당 4 x 200 Gbps | 100 GB/s x η_rdma 0.85 (ASSUMED) = 85 GB/s | 없음 · 지원 연산 없음 | 대역폭(η 포함), 중앙 인덱스 조회 100 us. fragmentation 페널티는 의도적으로 **미반영**(강한 baseline) |
| host DRAM | — | PCIe 5.0 | — | — | **사용하지 않음** (모든 arm에서 0) |
| ScHBM, CXL-PNM, HBF, SSD-PIM (DP1 6종 메모리 중 나머지) | — | — | — | — | **DP4 평가 범위 밖**(profile에는 있으나 이 시뮬레이터는 쓰지 않음) |

Baseline = Baseline-RDMA(CXL 풀 없음, P→D RDMA 점대점 + 중앙 인덱스, 노드 간 prefix 공유 없음). 별 경계는 결과를 본 뒤 바꾸지 않았다. 'Baseline 별'은 같은 기준을 Baseline에 적용한 참고값이다. QA2의 두 행(각 arm의 own-peak load / 공통 load)은 **서로 다른 질문**이다: 후보는 Baseline보다 낮은 load에서 goodput peak를 갖기 때문에 own-peak 값만 보면 후보 TTFT가 더 좋아 보이지만, 같은 offered load(Baseline의 peak)에서는 후보가 크게 나쁘다(위 두 행).

## 0.2 Trade-off와 그 이유

**두 후보는 QA1~QA3에서 값이 사실상 같고(차이 0.005% 이하), 둘 다 Baseline-RDMA보다 낮다. 별이 갈리는 곳은 QA4뿐이다. 성능 쪽 격차는 data plane(CXL 풀 경로 대 RDMA 경로)에서 오고, control plane 책임(C1 대 C2)에서 오지 않는다.**

- **왜 Baseline보다 낮은가 (QA1 x0.704, QA3 절감 x0.22, 공통 load TTFT P99 x4.98).** 8K 요청 하나의 KV는 2.50 GiB다. Common 압박(background 0.85)에서 Baseline은 RDMA 유효 85 GB/s로 한 번 보내 링크 시간 211 ms이고, 후보는 풀에 쓴 뒤(P egress) publish·pin 이후 다시 읽어야 하므로(D ingress, Iteration 2에서 순차로 수정) 노드 CXL 유효 63 GB/s로 쓰기 284 ms + 읽기 284 ms가 든다(config 상수로 계산한 어림값, 시뮬레이터 출력 아님). prefill은 H100 337 ms, B200 148 ms라 B200에서는 링크가 병목이 되어 격차가 크다(QA1: H100 x0.783, B200 x0.634). QA3는 같은 offered load(Baseline peak)에서 후보가 이미 포화해 P 노드 전송 버퍼에 요청이 쌓이는 효과다(P buffer 평균 114.4 GiB 대 Baseline 6.3 GiB). 이 격차는 η_cxl(ASSUMED 0.5)과 η_rdma(ASSUMED 0.85)에 좌우되며 break-even η_cxl*는 QA1 parity 0.703(H100 0.739, B200 0.695), QA3 절감 0.803이다(**ASSUMED 대 ASSUMED 비교**, 둘 다 C1=C2).
- **C1과 C2는 왜 같은 값이 나오는가.** control plane은 연산당 µs 규모다(C1 P50 2.1~7.3 µs, C2 2.6~804 µs; 연산별 C2 ÷ C1 P50은 lookup 1.2~61배, publish 9.2~313배, pin 20.6~240배, unpin 20.6~119배). 그러나 요청 하나의 TTFT는 수백~수천 ms이고 KV 이동·prefill이 지배한다. 두 후보의 Common QA 차이는 0.005% 이하, 장애 행을 뺀 DP4 쌍의 goodput 차이는 최대 0.017%다. data plane은 두 후보가 공유하므로 control plane은 성능 레버가 아니다.
- **C1과 C2가 실제로 갈리는 곳(별점 밖).** (1) **확장 한계:** control plane 포화 rate는 C2에서 S x N에 따라 줄고(stripe 1 -> 512에서 6,400 -> 400 req/s, 노드 4 -> 16에서 409,600 -> 102,400 req/s), C1은 서버 스레드로 늘어난다(204,800 -> 819,200 req/s, 1 -> 4 스레드). 다만 이 시뮬레이션의 제공 rate(최대 222 req/s)보다 최소 16배 위라 N <= 16에서는 어느 쪽도 포화하지 않았다(Scaling Efficiency는 제안 지표라 별 없음: N=16에서 C1 1.261, C2 1.261, Baseline 1.252; 1을 넘는 것은 P 노드가 늘며 대기열이 풀링되는 효과). (2) **장애:** C1은 메타데이터 서버가 SPOF여서 노드 손실(30 s 재구성)에서 Baseline 대비 goodput B200 x0.46, H100 x0.65(C2 B200 x1.00, H100 x0.99); 프로세스 재시작(0.5 s)은 영향이 없다. C2는 as-published 락이 풀리지 않아 요청 B200 41, H100 41건이 고착되고 가용성 창이 ∞이며(goodput B200 x0.976, H100 x0.978), lease 1 s 보완안은 B200 x0.997, H100 x0.999로 회복한다(보완안은 평가자의 가정). (3) **정확성(model check [C], 별점 아님):** 정상 C1·C2는 2노드에서 전수 탐색했고 4개 불변식에 반례가 없다. 결함 변종 7개 중 7개가 2노드에서 기대한 위반을 냈다. 3노드는 탐색 상한(1,500,000 상태)에 걸려 불완전하다(4.9).
- **QA4가 갈리는 이유와 취약성.** 두 후보의 module 수 평균은 같다(2.25). 갈리는 것은 공수 평균이다: C1 0.461 MM, C2 0.509 MM. 신규 topology(풀 2개, S4)에서 C2의 diff가 더 크다(측정 기록: proxy가 락 배열을 하나로 묶어 둬 풀별 분리 변경이 큼): LOC 28 대 14, module 크기 194 대 101 줄이라 공수가 0.905 대 0.738 MM다. 그런데 이 차이가 별을 가르는 것은 ★★★/★★ 경계(0.5 MM)가 두 값 사이에 있기 때문이다: C1은 경계보다 7.7% 아래, C2는 1.8% 위다. 경계를 ±10% 옮기거나 가정 상수를 바꾸면 두 후보가 같은 별이 되는 경우가 많다(0.3).
- **이득의 조건.** 후보가 Baseline을 이기는 것으로 판정된 쌍은 4쌍(44쌍 중, C1 = C2)이지만 **goodput이 95% CI 밖으로 좋아진 쌍은 0쌍**이고 4쌍 모두 지연 등급(QA2 별) 판정이다. 그 중 3쌍(H100 CB-1, CB-2, reference 행 `d4_node_scale_n2`)은 각 arm의 own-peak load를 비교한 효과라 같은 load에서는 후보가 더 느리다(5.2). 나머지 1쌍은 reuse 시나리오 `d4_agent_multiturn@H100`로 같은 load에서 TTFT P99 3,414 -> 698 ms, TPOT P99 17.9 -> 9.9 ms이지만, 이는 Baseline의 seed 5개 중 일부에서 goodput이 붕괴한 결과다(seed별 goodput Baseline 3,557/3,753/3,840/389/46 대 C1 3,557/3,761/3,865/4,038/3,976 tok/s, Baseline CV 83%; goodput 판정은 tie). 같은 시나리오가 B200에서는 goodput x0.52로 반대다. 따라서 **통계적으로 확정된 이득은 없고, 이득의 단서는 특정 조건(H100, 에이전트 reuse)에만 있으며 시스템에 따라 부호가 바뀐다.**

## 0.3 선택과 근거

1. **선택 질문:** C1(중앙 직렬화) 대 C2(분산 락). 둘 다 같은 CXL 풀 data plane을 쓰므로 후보 간 비교는 control plane 책임의 비교다. CXL 풀 data plane 대 RDMA 비교(도입 여부)는 Baseline 비교이며 결론은 '이득 없음'이다(0.1, 7장).
2. **QA 우선순위: QA2 > QA1 > QA4 > QA3, status = "proposal (사용자 확정 전)"**, 즉 사용자가 확정하지 않은 **제안**이다. 근거: DP4의 목적은 비일관 CXL 공유 풀에서 일관성 보장 비용이 지연(QA2)과 처리량(QA1)을 해치지 않게 하는 것이다. 사전 예측(simulation-plan.md §10)상 QA1~QA3는 두 후보가 같을 가능성이 높고, 그 경우 변경 용이성(QA4)이 실질적 판별 축이다. QA3는 두 후보의 data plane이 같아 차이가 없을 것으로 예상해 마지막에 둔다.
3. **규칙(`tools/dp_selection.py`, H13):** 별 합계가 높은 후보를 선택하고, 합계가 같을 때만 우선순위 위에서부터 처음으로 별이 갈리는 QA가 결정한다.
4. **결과:** C1 6점(QA1 ★, QA2 ★, QA3 ★, QA4 ★★★), C2 5점(QA4 ★★). 합계가 달라 **선택: C1** (규칙: total). QA1~QA3은 두 후보가 같아 1점 차이는 전부 QA4(★★★ 대 ★★)에서 온다.
5. **결정 민감도(우선순위를 뒤집었을 때):** 합계로 정해졌으므로 우선순위와 무관하다. 우선순위를 뒤집어도(QA3 > QA4 > QA1 > QA2) 첫 차이 QA는 QA4이고 승자는 C1로 같다. **그러나 QA4가 같은 별이 되면 QA1~QA3이 모두 같아 어떤 우선순위로도 선택이 정해지지 않는다(미결정).**
6. **별 경계 민감도.** (a) QA1~QA3 경계를 x0.9/x1.1로 옮겨도 두 후보의 별은 변하지 않는다(둘 다 1/1/1, 합 3; Baseline만 바뀜). (b) **QA4가 선택을 좌우한다.** M2(공수) 경계 0.5 MM와의 거리는 C1 7.7%(아래), C2 1.8%(위)다. 경계/집계/가정 상수/구조 대안 24가지 변형 중 C1이 선택되는 경우는 5가지, **미결정(동점)은 19가지**다:

| QA4 변형 | C1 QA4 | C2 QA4 | 합계 C1 / C2 | 선택 |
|---|---|---|---|---|
| main: 시나리오 평균 집계, 중간 상수 | ★★★ | ★★ | 6 / 5 | C1 |
| 최악값 집계 (v1, 사전 정의 이전 형태) | ★★ | ★★ | 5 / 5 | **미결정(동점)** |
| 상수 optimistic (low/high 동시) | ★★★ | ★★★ | 6 / 6 | **미결정(동점)** |
| 상수 pessimistic (low/high 동시) | ★★ | ★★ | 5 / 5 | **미결정(동점)** |
| 상수 교차 mm_low_tokens_low | ★★★ | ★★★ | 6 / 6 | **미결정(동점)** |
| 상수 교차 mm_low_tokens_high | ★★★ | ★★★ | 6 / 6 | **미결정(동점)** |
| 상수 교차 mm_high_tokens_low | ★★ | ★★ | 5 / 5 | **미결정(동점)** |
| 상수 교차 mm_high_tokens_high | ★★ | ★★ | 5 / 5 | **미결정(동점)** |
| 상수 1개만 c_mod=2.0 | ★★★ | ★★★ | 6 / 6 | **미결정(동점)** |
| 상수 1개만 c_mod=5.0 | ★★ | ★★ | 5 / 5 | **미결정(동점)** |
| 상수 1개만 k_real=3.0 | ★★★ | ★★★ | 6 / 6 | **미결정(동점)** |
| 상수 1개만 k_real=10.0 | ★★ | ★★ | 5 / 5 | **미결정(동점)** |
| 상수 1개만 P=80.0 | ★★★ | ★★★ | 6 / 6 | **미결정(동점)** |
| 상수 1개만 P=25.0 | ★★ | ★★ | 5 / 5 | **미결정(동점)** |
| 상수 1개만 f_ovh=1.5 | ★★★ | ★★★ | 6 / 6 | **미결정(동점)** |
| 상수 1개만 f_ovh=3.0 | ★★ | ★★ | 5 / 5 | **미결정(동점)** |
| 상수 1개만 tpl=8.0 | ★★★ | ★★ | 6 / 5 | C1 |
| 상수 1개만 tpl=16.0 | ★★★ | ★★ | 6 / 5 | C1 |
| 구조 대안 S1_coherent_region_counted_as_shared_module | ★★ | ★★ | 5 / 5 | **미결정(동점)** |
| 구조 대안 S3_C2_entry_layout_extended | ★★★ | ★★ | 6 / 5 | C1 |
| 구조 대안 S1_C2_flagged_major_interface_change | ★★★ | ★★ | 6 / 5 | C1 |
| 구조 대안 all_analytic_alternatives_together | ★★ | ★★ | 5 / 5 | **미결정(동점)** |
| 별 경계 x0.9 (M1/M2/M3 threshold 동시) | ★★ | ★★ | 5 / 5 | **미결정(동점)** |
| 별 경계 x1.1 (M1/M2/M3 threshold 동시) | ★★★ | ★★★ | 6 / 6 | **미결정(동점)** |

7. **정의 의존성(참고, H20).** QA3는 사전 등록 정의(Baseline peak load에서의 같은 요청 구간 비교)를 썼다. 후보가 이미 포화한 load에서 비교되어 값이 크게 나빠진다. 각 arm의 own-peak load에서의 KV 상주는 Baseline 15.9 GiB, 후보 13.6 GiB(절감 배수 x1.17, 별 ★★ 구간), x1.0 load에서는 절감 배수 x0.35이다. 이는 **민감도 보고일 뿐 정의를 바꾼 것이 아니며** 어느 정의에서도 C1=C2라 선택은 변하지 않는다(두 후보에 같은 별이 가산됨).
8. **선택 근거(문장).** QA1~QA3에서 두 후보는 구분되지 않으므로 성능은 근거가 아니다. C1을 고르는 근거는 (i) QA4에서 개발 공수·에이전트 비용이 낮다는 점(단 경계 근처의 작은 차이), (ii) 일관성 논증이 단일 직렬화 지점 하나로 단순하다는 구조적 특성이다(model check에서 정상 C1·C2 모두 2노드 전수 통과로 정확성 차이는 없었다). C1을 고를 때의 대가는 서버 SPOF(노드 손실 시 goodput x0.46, x0.65)이고, C2를 고를 때의 대가는 as-published 락 고착이다(lease 같은 보완안이 필요). **선택 C1은 QA4 하나에 기댄 약한 선택이다.**

## 0.4 선택한 구조의 부족한 부분과 보완 설계

택틱 상세는 `doc-mk/DP4/DP4-complement-design-tactics.pptx`. **검증 상태:** [B] = 구현·측정됨(시뮬레이터 출력, [B+C]) / [C] = 논증·미구현. **미구현 택틱의 효과는 수치로 주장하지 않는다**(H14).

| # | 약점 (평가 근거 수치) | 보완 택틱 | 개선 대상 | 검증 상태 |
|---|---|---|---|---|
| W1 | 메타데이터 서버 SPOF: 노드 손실(인덱스 재구성 30 s)에서 Baseline 대비 goodput B200 x0.46, H100 x0.65 (C2는 영향 없음). 프로세스 재시작(0.5 s, 인덱스는 CXL에 보존)은 B200 x0.999, H100 x0.992로 영향 없음 | 스탠바이 메타데이터 서버를 다른 노드에 두고 CXL에 있는 인덱스를 그대로 인계(takeover). 재구성 풀 스캔을 피하는 것이 목적 | QA1·QA2 (장애 시) | [B] 프로세스 재시작 경로(인덱스 CXL 보존)는 구현·측정됨. [C] 스탠바이 인계는 미구현, 효과 수치 없음 |
| W2 | 서버 포화 rate가 유한: 1 스레드 204,800 req/s(hot prefix, 노드 8), block 16에서 51,200 req/s. 제공 rate 대비 여유는 최소 4,212배라 N <= 16에서는 포화 없음. 서버 busy-poll 코어 1.0개 상시 점유 | 서버 스레드 증설(1 -> 2 -> 4). 큰 block(256)으로 연산 수 감소 | QA1 (확장 시) | [B] 구현·측정됨: 서버 스레드 2/4에서 포화 rate 409,600/819,200 req/s (`d4_server_threads_*`), block 256에서 1,638,400 req/s. CPU 코어 비용 증가는 별도 |
| W3 | 정확성이 서버의 CLFLUSH-before-read와 슬롯 프로토콜에 의존: model check에서 `C1_no_clflush_on_server`는 I1 위반(반례 21 step, 2·3노드 모두 검출). 이 결과는 '슬롯 body 줄은 이전 요청의 값을 담은 채 서버 캐시에 있을 수 있다'는 저자 가정에 의존 | 요청 슬롯의 body와 flag를 같은 cacheline 안의 sequence-numbered 항목으로 두거나 body에 검증값(checksum, seq)을 넣어 stale body를 서버가 감지하게 함(누락된 flush를 safety가 아닌 liveness 문제로 낮춤). 프로토콜 conformance 시험 추가 | 정확성 (별점 밖) | [C] 논증·미구현. 모델 README의 가정 설명에 근거, 효과 수치 없음 |
| W4 | QA1 x0.704, QA3 절감 x0.22, 공통 load TTFT P99 x4.98: **data plane**(풀 경유 쓰기 + 읽기 순차)이 원인이며 C2도 같다. break-even η_cxl* 0.703(ASSUMED) | (a) 풀에서 필요한 블록만 읽는 partial read와 풀 사본 제거, (b) 청크 단위 publish로 쓰기와 읽기를 겹침(publish가 가시성 경계라는 제약 유지), (c) 단일 사용 KV는 RDMA 직접 경로로 두고 풀은 공유·재사용 객체에만 쓰는 하이브리드 | QA1·QA2·QA3 | [C] 논증·미구현. Iteration 2의 원인 분석(순차 read)에 근거. **효과 수치를 주장하지 않으며** 시뮬레이터 적용은 새 iteration으로 사전 등록해야 함 |
| W5 | reuse 이득이 시스템에 의존하고 통계적으로 확정되지 않음: `d4_agent_multiturn` goodput 비 B200 x0.52, H100 x1.66. H100의 이득은 Baseline의 seed 5개 중 일부 붕괴(CV 83%)에서 오며 goodput 판정은 tie | reuse가 있는 객체(History KV, 공유 prefix)에만 풀을 쓰는 선택적 경로(W4-c와 동일 계열)와 시스템별 경로 선택 기준 마련. seed 수를 늘려 Baseline 붕괴의 빈도 확인(class N) | QA1·QA2 | [C] 논증·미구현 (seed 추가는 미실시). 두 시스템 외 일반화 근거 없음 |
| W6 | QA4 별이 경계 근처: C1 0.461 MM이 0.5 MM보다 7.7% 아래이고 C2와의 차이는 0.048 MM. 측정 기준 시뮬레이터 소스가 Iteration 2 이전이라 재측정이 필요(4.5, 4.10) | Iteration 2 이후 소스에서 QA4 변경 시나리오 4종 재구현·재측정, 가능하면 실제 vLLM 통합에서 module/LOC 측정 | QA4 | [C] 미실시. 재측정 전에는 QA4 별을 확정하지 않음 |

## 0.5 어떤 시나리오를 고려했는지

서버 두 종류(prefill 담당, decode 담당)로 나뉜 클러스터에서 prefill 서버가 만든 KV cache(대화 문맥의 중간 계산 결과)를 decode 서버로 넘기는 경로를 비교했다. 현재 방식(Baseline)은 서버 사이를 네트워크(RDMA)로 직접 복사하고, 후보는 두 서버가 함께 쓰는 CXL 공유 메모리 풀에 한 번 두고 서로 읽는다. 공유 풀은 서버 간 캐시 일관성을 하드웨어가 주지 않아서 '누가 목록(메타데이터)을 관리하고 어떻게 서로 안전하게 읽는가'가 문제이며, 그 두 가지 답이 C1(한 서버가 전부 직렬로 처리)과 C2(모든 노드가 락을 잡고 직접 갱신)다.

총 **6쌍(공통 3개 시나리오 x 2시스템)과 38쌍(DP4 전용 17개 시나리오, 변종 포함 19행 x 2시스템)** = 44쌍을 평가했다. Baseline도 SLO를 만족하는 비교 가능 쌍 43쌍, 모든 arm이 같아 구분하지 못하는 포화 1쌍(d4_fail_lockholder[lease]@H100), Baseline이 SLO를 못 맞춰 비교할 수 없는 쌍 0쌍이다. 비교할 수 없는 쌍은 없었고, 승/무/패(Baseline 대비, 95% CI·1% 기준)는 C1 4/33/7, C2 4/33/7이다.

- **압박이 걸린 기본 서비스 상황(공통 3개).** 8K 토큰 입력·256 토큰 생성의 대화 서비스에서 서버 사이 링크가 다른 트래픽으로 거의 차 있는 경우(background 0.85), 처음에는 여유가 있다가 점점 막히는 경우(0.2에서 0.9로 증가), KV 외에 LoRA·MoE·Agent·Tool 데이터가 섞여 풀을 오가는 경우다. **별점은 여기서만** 나온다. 대표 예: 링크가 85% 차 있을 때 KV 2.5 GiB를 옮기는 데 Baseline은 한 번(211 ms), 후보는 쓰고 다시 읽어 두 번(568 ms) 걸린다(config 어림값).
- **접근이 쏠린 경우.** 요청의 90%가 같은 긴 prefix를 공유하는 경우(`d4_hot_prefix_fanout`: 같은 메타데이터 항목에 요청이 몰려 C1 서버 대기열과 C2 락 경합을 건드림). 고르게 흩어진 접근만 따로 본 시나리오는 없다.
- **데이터 종류별.** KV cache가 중심이고, 8턴 에이전트처럼 History KV가 쌓이며 재사용되는 경우(`d4_agent_multiturn`, 재사용을 켠 별도 행)와 KV·LoRA·MoE·Agent·Tool이 섞인 혼합(공통 CB-3)을 본다. 종류별 접근 패턴 차이는 모델링하지 않았다.
- **자원 조건과 규모의 변화.** 서버 수를 4·8·16대로 늘리는 경우, 한 번에 옮기는 블록 크기를 16·256 토큰으로 바꾸는 경우, 작은 prompt를 높은 rate로 받는 경우, 풀이 95% 차서 매번 퇴출이 필요한 경우, C2의 락 stripe 수와 C1의 서버 스레드 수를 바꾸는 경우를 본다.
- **장애.** C1 메타데이터 서버가 죽었다가 재시작하는 경우와 노드 손실로 인덱스를 다시 만드는 경우, C2 락을 쥔 노드가 죽는 경우(as-published는 락이 풀리지 않음, lease 보완안은 풀림).
- **정확성(별점 밖).** 비일관 캐시를 추상화한 모델에서 두 프로토콜과 결함 변종 7개를 검사했다(4.9).
- **아직 없는 것.** 실제 CXL 풀 하드웨어 측정, 서버 2대 초과의 실측, 다중 테넌트 격리, 풀 장치 장애, 스위치 혼잡, KV 외 객체의 종류별 접근 패턴, 균일 접근 전용 시나리오, 실제 trace. 전체 시나리오 목록은 3장과 [`benchmark.md`](../benchmark.md).

# 1. 시스템 환경

| 항목 | 값 |
|---|---|
| SYS id | **SYS-H100** (HBM3 (H100 SXM5 80GB), PCIe 5.0, CXL 2.0 (PCIe 5.0 PHY)), **SYS-B200** (HBM3e (B200), PCIe 5.0, CXL 2.0 (PCIe 5.0 PHY)), 통합 `INT-H100-B200`. SYS-A100/SYS-VR은 평가하지 않았다(DP1과 같은 세대 축, profile은 유지) |
| 클러스터 profile | `DP4/sim/configs/cluster_dp4.json`(신규, 모든 파라미터에 value/range/provenance PAPER·SPEC·ASSUMED), sha1 `8812188fbd34bee16c9160502154e5e1c1e28ac3`. 기존 profile은 수정하지 않았다(H10) |
| 노드 / topology | 노드 1개 = GPU 8장(TP=8), P/D 분리. CB 기본 P1+D1(사용자 환경 서버 2대와 같은 규모), DP4-specific는 P2+D2 기본, 노드 수 sweep 4/8/16 |
| Model / precision | Llama-3.1-70B, BF16 (`DP1/sim/configs/models.json`), KV 327,680 B/token (8K = 2.50 GiB). 8K prefill 337 ms(H100) / 148 ms(B200) (DP1 물리 재사용) |
| Git revision | cb98109 (integrated file: dirty; SYS-H100 run: clean, SYS-B200 run: dirty; flags as recorded in `qa_result.json` meta; `dirty` = uncommitted changes under `doc-mk/Evaluation/DP4` at run time) |
| Seeds / loads | seeds 11, 23, 37, 53, 71 (5회) / load x0.5, x1, x1.5, x2, peak가 grid 끝이면 x8까지 상향 확장, 최저점이 peak이면 x0.0625까지 하향 확장(시나리오별 실제 load는 `meta.loads_run`). 95% CI t(0.975, df=4)=2.776, tie 판정 상대 차이 1% |
| Evidence | 시뮬레이션 [B+C] (입력 파라미터: PAPER 문헌값 [B], ASSUMED 가정), QA4 [B+C] proxy 구현, protocol model check [C]. **CXL 공유 풀 하드웨어가 없어 [A] 실측은 없다** |
| 재현 command | `cd doc-mk/Evaluation/DP4/sim && uv run --no-project python -m unittest test_sim -v && uv run --no-project python qa_eval.py --system SYS-H100 --jobs 4 --out-dir ../results/data/SYS-H100 && uv run --no-project python qa_eval.py --system SYS-B200 --jobs 4 --out-dir ../results/data/SYS-B200 && uv run --no-project python merge_systems.py SYS-H100 SYS-B200` ; ablation `python ablation.py --system SYS-H100` (SYS-B200도, 이후 `merge_systems.py SYS-H100 SYS-B200 --data-dir ../results/data/ablation`), `python star_basis.py --system SYS-H100`, `python sensitivity.py run --group grid` ; model check `cd sim/protocol_check && python check.py --nodes 2` (`--nodes 3`) ; 문서 `uv run --no-project python doc-mk/Evaluation/tools/gen_dp4_result.py` |
| 기록된 실행 명령 | 통합: `python merge_systems.py SYS-H100 SYS-B200`; SYS-H100: `python3 qa_eval.py --system SYS-H100 --jobs 4 --out-dir ../results/data/SYS-H100`; SYS-B200: `python3 qa_eval.py --system SYS-B200 --jobs 4 --out-dir ../results/data/SYS-B200` |
| Raw data | `DP4/results/data/`: `INT-H100-B200/`, `SYS-H100/`, `SYS-B200/`(`qa_result.json`, `*_runs.csv`), `ablation/`, `star_basis/`, `sensitivity/`(`summary.json`, `tables.md`), `pre_serial_read/`(수정 전 모델, 대체됨), `protocol_check.json`, `protocol_check_n3.json`, `qa4_measured_counts.json`, `qa4_modifiability.json` |
| 데이터 revision 참고 | 주 결과는 `cb98109`. 아래 파일은 다른 revision에서 생성되었다(기록값): ablation `fb9ecab`, pre_serial_read `0e44b58`. sensitivity/star_basis는 meta에 revision이 없다. 모두 같은 `cluster_dp4.json`(sha1 일치)과 같은 모델 코드를 쓴 것으로 대조군 일치로 확인했다(4.5) |

시스템 profile 상세: [system-specs.md](../../system-specs.md). H100/B200 규격은 PUBLIC(확인 필요)이며, CXL·RDMA·락 관련 파라미터의 provenance는 `cluster_dp4.json`과 `simulation-plan.md` §4에 필드별로 있다. **C2의 락 상수(scan 비용, critical section 길이, stripe 수, 장애 처리)는 논문에 없어 ASSUMED이다.**

| 메모리 / 경로 | 용량 | host 연결 (세대) | 대역폭 | 연산 능력 (FP16) · 지원 연산 | 시뮬레이터 반영 |
|---|---|---|---|---|---|
| HBM (노드의 GPU 8장 합) | H100 640 GiB (HBM3) / B200 1,536 GiB (HBM3e) | GPU on-package (host CPU와는 PCIe 5.0) | H100 26.8 / B200 64.0 TB/s (노드 합) | GPU FP16 dense 989 / 2,250 TFLOPS/GPU, attention·FFN 실행 | decode step·prefill 시간(DP1 물리 재사용), 잔류량 집계. **용량 한계(OOM)는 미반영** |
| CXL 공유 풀 (후보 C1·C2의 KV 저장소) | 8 TiB | CXL 2.0 (PCIe 5.0 PHY) 스위치 풀, 노드당 어댑터 2개 x PCIe 5.0 x16 | 어댑터 63 GB/s x 2 = 노드당 126 GB/s (방향별), 풀 집계 1 TB/s, 유효 효율 η_cxl 0.5 (ASSUMED) → 노드 유효 63 GB/s | 없음 (순수 저장소) · 지원 연산 없음 | 대역폭(η 포함), 접근 지연의 control plane 비용, 풀 점유율(퇴출 연산). 스위치 혼잡·bank 경합은 **미반영** |
| RDMA NIC (Baseline-RDMA의 KV 경로) | — (전송 버퍼만) | 노드당 4 x 200 Gbps | 100 GB/s x η_rdma 0.85 (ASSUMED) = 85 GB/s | 없음 · 지원 연산 없음 | 대역폭(η 포함), 중앙 인덱스 조회 100 us. fragmentation 페널티는 의도적으로 **미반영**(강한 baseline) |
| host DRAM | — | PCIe 5.0 | — | — | **사용하지 않음** (모든 arm에서 0) |
| ScHBM, CXL-PNM, HBF, SSD-PIM (DP1 6종 메모리 중 나머지) | — | — | — | — | **DP4 평가 범위 밖**(profile에는 있으나 이 시뮬레이터는 쓰지 않음) |

# 2. 평가 항목

| 항목 | 정의 / formula | 출처 |
|---|---|---|
| QA1 Max SLO Goodput | 요청별 SLO(TTFT <= 2 s and TPOT <= 50 ms)를 만족한 request의 output token/s. load sweep(x0.5~2.0, 필요 시 확장)의 최대값. **별점:** Common Benchmark 6쌍의 (후보 ÷ Baseline) **기하평균**, < 0.90 ★ / 0.90~1.10 ★★ / >= 1.10 ★★★ (공통 기준 그대로). T_ref = Baseline-RDMA | criteria §4, `qa-criteria-dp4.md` §1 |
| QA2 TTFT P99 / TPOT P99 | 두 metric을 **별도 행**으로 보고(P50/P95/P99 모두 저장). 별 = 6쌍 중 각 arm의 Max-goodput load에서의 **최악 P99**: <= 2 s & <= 50 ms ★★★ / <= 4 s & <= 100 ms ★★ / 그 외 ★. 같은 offered load(Baseline peak)에서의 값(`*_common`)과 x1.0 load의 값(`*_load1`)을 병기 | criteria §5, DESIGN_NOTES A.8 |
| QA3 Resource usage | **클러스터 KV 상주 메모리 시간 평균 GiB**(P 노드 전송 버퍼 + D HBM + 풀), Baseline peak load에서 같은 요청 구간 비교, 낮을수록 좋음. 별 = 절감 배수(Baseline ÷ 후보) < 0.95 ★ / 0.95~1.25 ★★ / >= 1.25 ★★★ (DP1 QA3 경계를 가져옴). 성능을 섞지 않는다(H20) | **임시 정의**: `qa-criteria-dp4.md` §2 |
| QA4 Modifiability | 변경 시나리오 4종(신규 HW capability / 객체 class / 정책 교체 / topology)을 시뮬레이터 proxy에 구현해 (M1) 변경 module 수, (M2) 개발 공수(man-month), (M3) 에이전트 토큰 비용($, T1 frontier). 시나리오 평균에 경계 적용(M1 <= 2 / <= 5, M2 <= 0.5 / <= 1.0 MM, M3 <= $3 / <= $10), QA4 별 = 세 sub-star의 중앙값 | M1은 criteria §7, M2·M3·집계는 **임시 정의**(`qa4-preregistration.md`, DP1과 같은 공식·상수) |
| Scalability (제안) | Scaling Efficiency = Goodput(N) / ((N/2) x Goodput(2)), N = 4/8/16, 노드당 부하 고정. **공식 QA가 아니며 값만 보고, 별점 없음**(사용자 확정 전, H11) | `qa-criteria-dp4.md` §3 |
| 정확성 (별점 아님) | protocol model check: 불변식 I1 가시성 / I2 use-after-free / I3 상호 배제 / I4 stale index. 제약이지 QA가 아님 | `simulation-plan.md` §8, 4.9 |
| 집계 범위 | **별점 = Common Benchmark 6쌍만**(사전 등록, `common-benchmark.md` §7). DP4-specific 38쌍은 diagnostic과 QA4 근거이며 별점에 섞지 않는다. 승/무/패, fit 라벨, 결론은 두 set 44쌍 모두를 쓴다 (H3) | `qa-criteria-dp4.md` §1 |
| Diagnostic | control-plane op latency P50/P99(lookup/publish/pin/unpin), control-plane 포화 rate(open-loop sweep, P99 chain latency가 10배가 되는 최저 rate), 서버·락·풀·링크 점유율, 락 대기, coherence CPU core-equivalent, 장애 시 SLO 위반 수·가용성 창 | DP4 전용 |
| 승/무/패 | 쌍별로 goodput(상대 차이 < 1% 또는 95% CI 이내는 tie)과 지연 등급을 비교(`qa_eval.compare_pair`) | DP1과 같은 규칙 |
| 모델 오차 sweep (H17) | **해당 없음**: DP4 후보는 estimator/predictor에 의존하지 않는다 | — |

# 3. 벤치마크 / 시나리오

정의와 시나리오당 한 줄 설명은 [`DP4/benchmark.md`](../benchmark.md)(생성: `tools/gen_dp4_benchmark_doc.py`, 단일 소스 `DP4/sim/scenarios.py`)와 [`common-benchmark.md`](../../common-benchmark.md). fit 라벨: **V** comparison-valid / **S** saturated / **I** infeasible (H100 / B200 순, SKILL §4 정의). 제외한 시나리오는 없다(비교 불가 0).

| Benchmark set | 시나리오 (행) | 드러내는 As-Is 약점 (`Scenario.exposes`) | Fit (H100 / B200) | 비고 |
|---|---|---|---|---|
| Common | `cb_kv_8k_b32` — KV만, 8K/256, batch 32, 링크 background 0.85 | KV 이동 경로(링크/풀) 경합 | V / V |  |
| Common | `cb_kv_8k_b32_ramp` — KV만, 8K/256, 링크 background 0.2→0.9 증가 | 시간에 따라 이동 경로 여유가 줄어드는 경우 | V / V |  |
| Common | `cb_mixed_8k_b32` — KV50/LoRA15/MoE15/Agent10/Tool10 혼합, background 0.85 | 객체 종류가 섞여 풀 트래픽·메타데이터 연산이 늘어나는 경우 | V / V |  |
| DP4-specific | `d4_agent_multiturn` — 8턴 에이전트, History KV 누적 (reuse 켬, 별도 행) | Baseline의 D→P 왕복 전송 vs 풀 공유 | V / V | reuse 켬(별도 행) |
| DP4-specific | `d4_block16` — block 16 tokens (블록당 연산 수 4배) | 블록당 control plane 연산 수 ∝ 1/block | V / V |  |
| DP4-specific | `d4_block256` — block 256 tokens (블록당 연산 수 1/4) | 블록당 control plane 연산 수 ∝ 1/block | V / V |  |
| DP4-specific | `d4_fail_lockholder[as_published]` — C2 락 보유 노드 crash (as-published / lease) | 락 고착, 영향 범위 | V / V | as-published(락 해제 없음) |
| DP4-specific | `d4_fail_lockholder[lease]` — C2 락 보유 노드 crash (as-published / lease) | 락 고착, 영향 범위 | S / V | lease 1 s 보완안 (평가자의 가정) |
| DP4-specific | `d4_fail_server[node_loss]` — C1 메타데이터 서버 crash 후 복구 | 가용성 창, SLO 위반 (C1 SPOF) | V / V | 노드 손실, 인덱스 재구성 30 s |
| DP4-specific | `d4_fail_server[restart]` — C1 메타데이터 서버 crash 후 복구 | 가용성 창, SLO 위반 (C1 SPOF) | V / V | 프로세스 재시작 0.5 s |
| DP4-specific | `d4_hot_prefix_fanout` — 긴 공통 prefix를 request의 90%가 공유 | C1 서버 대기열, C2 hot 락 경합·refcount 갱신 | V / V |  |
| DP4-specific | `d4_lock_stripes_1` — C2 락 stripe 1개 (hot prefix, 노드 8) | stripe 수의 contention vs scan 비용 | V / V |  |
| DP4-specific | `d4_lock_stripes_512` — C2 락 stripe 512개 (hot prefix, 노드 8) | stripe 수의 contention vs scan 비용 | V / V |  |
| DP4-specific | `d4_lock_stripes_8` — C2 락 stripe 8개 (hot prefix, 노드 8) | stripe 수의 contention vs scan 비용 | V / V |  |
| DP4-specific | `d4_node_scale_n16` — 노드당 부하 고정, 노드 16개 (P 8 + D 8) | Scalability: C1 서버 포화, C2 scan 비용 S×N | V / V |  |
| DP4-specific | `d4_node_scale_n2` — Scaling 기준 행: 노드 2개 (P1 + D1) | Scaling Efficiency 분모 (공식 시나리오 아님) | V / V | Scaling Efficiency 분모용 reference 행(benchmark.md의 공식 시나리오가 아니나 집계 쌍에 포함됨) |
| DP4-specific | `d4_node_scale_n4` — 노드당 부하 고정, 노드 4개 (P 2 + D 2) | Scalability: C1 서버 포화, C2 scan 비용 S×N | V / V |  |
| DP4-specific | `d4_node_scale_n8` — 노드당 부하 고정, 노드 8개 (P 4 + D 4) | Scalability: C1 서버 포화, C2 scan 비용 S×N | V / V |  |
| DP4-specific | `d4_pool_full_eviction` — 풀 점유 95%, publish마다 퇴출 연산 | refcount 경합, 퇴출 지연 | V / V |  |
| DP4-specific | `d4_server_threads_2` — C1 서버 스레드 2개 (hot prefix, 노드 8) | 중앙 직렬화의 확장 여지 | V / V |  |
| DP4-specific | `d4_server_threads_4` — C1 서버 스레드 4개 (hot prefix, 노드 8) | 중앙 직렬화의 확장 여지 | V / V |  |
| DP4-specific | `d4_small_prompt_highqps` — 512 in/64 out, 높은 request rate | control plane 연산률 지배 영역 | V / V |  |

fit 집계: Common {'comparison_valid': 6, 'saturated': 0, 'infeasible': 0} / DP4 {'comparison_valid': 37, 'saturated': 1, 'infeasible': 0}. saturated 쌍: `d4_fail_lockholder[lease]@H100`. 참고: Iteration 2 이전 모델에서는 DP4 행의 comparison-valid가 6쌍, saturated가 32쌍이었다. 순차 read로 수정한 뒤 read가 TTFT에 노출되어 대부분 쌍에서 TTFT가 Baseline과 유의하게 달라져 라벨이 바뀌었다(기계적 변화, loop-log Iteration 2).

**시나리오 선택 의존성.** 시나리오는 결과 전에 `simulation-plan.md` §6에 사전 등록했다. 압박(background 0.85, 0.2~0.9)은 ASSUMED이며 결과를 본 뒤 바꾸지 않았다. Common의 압박 정의(링크 background)는 DP1의 HBM 용량 축소와 의미가 달라 DP 간 공통 별점 직접 비교에 한계가 있다.

# 4. 결과

표의 모든 숫자는 `results/data/INT-H100-B200/qa_result.json`(및 SYS-*, ablation, sensitivity 등 아래 명시한 파일)에서 `tools/gen_dp4_result.py`가 옮겼다. 손으로 쓴 수치는 없다.

## 4.1 최종 QA 표 (Common 별점 기준, 통합 H100 + B200)

| QA | 평가 metric | Baseline (T_ref) | C1 중앙 직렬화 | C2 분산 락 |
|---|---|---:|---|---|
| **QA1 Throughput** | Max SLO goodput (tok/s) ↑ | 589 (Baseline 별 ★★) | **★** 415 (x0.704 ±0.032) [B+C] | **★** 415 (x0.704 ±0.032) [B+C] |
| **QA2 Latency — TTFT** (각 arm의 Max-goodput load) | TTFT (ms) ↓ | P99 6,283 · P50 1,009 | P99 4,205 (x0.67) · P50 907 (x0.90) [B+C] | P99 4,205 (x0.67) · P50 907 (x0.90) [B+C] |
| **QA2 Latency — TTFT** (공통 load = Baseline peak load) | TTFT (ms) ↓ | P99 6,283 · P50 1,009 | P99 31,271 (x4.98) · P50 6,548 (x6.49) [B+C] | P99 31,271 (x4.98) · P50 6,549 (x6.49) [B+C] |
| **QA2 Latency — TPOT** (각 arm의 Max-goodput load) | TPOT (ms) ↓ | P99 4.07 · P50 4.07 | P99 4.04 (x0.99) · P50 3.99 (x0.98) [B+C] | P99 4.04 (x0.99) · P50 3.99 (x0.98) [B+C] |
| **QA2 Latency — TPOT** (공통 load) | TPOT (ms) ↓ | P99 4.07 · P50 4.07 | P99 4.04 (x0.99) · P50 4.04 (x0.99) [B+C] | P99 4.04 (x0.99) · P50 4.04 (x0.99) [B+C] |
| QA2 별점 | 6쌍 중 최악 P99 (criteria §5: <=2 s & <=50 ms ★★★, <=4 s & <=100 ms ★★) | ★ (TTFT 28,234 · TPOT 6.4) | **★** (TTFT 80,568 · TPOT 6.4) [B+C] | **★** (TTFT 80,568 · TPOT 6.4) [B+C] |
| **QA3 Resource usage** | 클러스터 KV 상주 메모리 (GiB, 시간 평균, Baseline peak load) ↓ | 15.9 (Baseline 별 ★★) | **★** 71.3 (x4.48; 절감 배수 x0.22) [B+C] | **★** 71.3 (x4.49; 절감 배수 x0.22) [B+C] |
| **QA4 Modifiability** | 변경 module 수 · 공수(man-month) · 에이전트 비용($, frontier tier), 시나리오 4종 평균 ↓ | — | **★★★** 2.25 · 0.46 · $1.21 (sub-star ★★/★★★/★★★) [B+C] | **★★** 2.25 · 0.51 · $1.35 (sub-star ★★/★★/★★★) [B+C] |
| **별 합계** (QA1..QA4) | | — | **6** | **5** |

**평가한 시스템:** **SYS-H100** (H100x8, HBM3 (H100 SXM5 80GB), PCIe 5.0, CXL 2.0 (PCIe 5.0 PHY)); **SYS-B200** (B200x8, HBM3e (B200), PCIe 5.0, CXL 2.0 (PCIe 5.0 PHY)). 시스템당 P/D 분리 클러스터(CB 기본 P 1대 + D 1대, 노드 = GPU 8장), Llama-3.1-70B BF16(KV 327,680 B/token), 두 시스템을 **통합**했다(통합 결과 하나, 시나리오 x 시스템 쌍이 단위). 별점의 집계 단위는 **Common Benchmark 6쌍**(CB-1~3 x 2시스템, 모두 comparison-valid; 사전 등록 규칙: 공통 별점은 Common set에서만 산출). DP4-specific는 38쌍(비교 가능 37, 포화 1, 비교 불가 0)이며 diagnostic과 QA4 근거로만 쓴다. 값은 쌍별 값의 **기하평균**, 괄호는 **후보 ÷ Baseline 배수**(↑ 높을수록 좋음, ↓ 낮을수록 좋음), QA1의 ±는 seed 묶음 기하평균의 95% CI(t=2.776, 5 seeds)이다. Evidence [B+C]; QA4는 [B+C] proxy 구현.

### 4.1a 시스템별 단독 (일관성 확인용, 0장에는 매트릭스로 내지 않음)

| 범위 | 쌍 수 | Baseline goodput (tok/s) | QA1 C1 (=C2) | QA2 별 (TTFT 최악 ms) C1 | QA3 절감 배수 C1 (=C2) | 승/무/패 C1 (44쌍 기준, 시스템별) |
|---|---:|---:|---|---|---|---|
| SYS-H100 | 3 | 440 | **★** x0.783 (C2 x0.783) | **★★** (2,993) | **★** x0.46 (C2 x0.46) | 4/16/2 |
| SYS-B200 | 3 | 789 | **★** x0.634 (C2 x0.634) | **★** (80,568) | **★** x0.11 (C2 x0.11) | 0/17/5 |
| INT-H100-B200 | 6 | 589 | **★** x0.704 (C2 x0.704) | **★** (80,568) | **★** x0.22 (C2 x0.22) | 4/33/7 |

### 4.1b 전체 benchmark 합산 참고 (Common + DP4-specific 44쌍, **별점 산출에 쓰지 않음**)

| 지표 (기하평균) | Baseline | C1 | C2 |
|---|---:|---:|---:|
| Max SLO goodput (tok/s), 전체 44쌍 | 2,231 | 2,058 (x0.923) | 2,113 (x0.947) |
| TTFT P99 공통 load (ms), 전체 44쌍 | 1,976 | 2,891 (x1.46) | 4,447 (x2.25) |
| KV 상주 (GiB), 전체 44쌍 | 34.6 | 44.2 (x1.28) | 46.8 (x1.35) |
| Max SLO goodput (tok/s), 장애 행 제외 36쌍 | 2,407 | 2,257 (x0.938) | 2,257 (x0.938) |
| TTFT P99 공통 load (ms), 장애 행 제외 36쌍 | 1,731 | 2,379 (x1.37) | 2,379 (x1.37) |
| KV 상주 (GiB), 장애 행 제외 36쌍 | 37.6 | 50.1 (x1.33) | 50.1 (x1.33) |

DP4-specific 행은 background 0이라 링크 압박이 없어 Common보다 Baseline에 가깝다. 전체 쌍의 TTFT 행은 장애 행에서 고착된 요청(기록값 1e9 ms)이 기하평균을 왜곡하므로 장애 행 제외 값을 함께 둔다. C1과 C2의 차이는 장애 행에서만 온다. 별점은 Common 6쌍에서만 산출하므로 이 표는 H3(최종 결론은 두 benchmark 합산)을 위한 참고다.

## 4.2 시나리오별 결과

n_seeds = 5, 95% CI = t(0.975, df=4)=2.776, CV = 표준편차/평균(seed 간). 'g'=goodput 판정, 'ttft', 'tpot' = 해당 P99 판정(win/tie/loss). 후보 CV 범위: Common C1 1.6%~6.1%, DP4 C1 1.3%~6.9%; Baseline DP4 최대 83.0%(`d4_agent_multiturn@H100`).

### 4.2.1 Common (각 arm의 Max-goodput load 기준)

| 시나리오 @ 시스템 | Fit | Baseline goodput ±CI (CV) | C1 goodput (ratio) | C2 goodput (ratio) | TTFT P99 ms B / C1 / C2 | TPOT P99 ms B / C1 / C2 | 판정 vs Baseline C1 / C2 |
|---|---|---|---|---|---|---|---|
| `cb_kv_8k_b32@B200` | V | 972.5 ±36.0 (3.0%) | 512.1 (x0.527) | 512.1 (x0.527) | 3,195 / 1,630 / 1,631 | 2.60 / 2.56 / 2.56 | loss (g loss, ttft win, tpot win) / loss (g loss, ttft win, tpot win) |
| `cb_kv_8k_b32@H100` | V | 459.9 ±37.4 (6.6%) | 450.6 (x0.980) | 450.6 (x0.980) | 6,371 / 2,166 / 2,166 | 6.41 / 6.41 / 6.41 | win (g tie, ttft win, tpot tie) / win (g tie, ttft win, tpot tie) |
| `cb_kv_8k_b32_ramp@B200` | V | 1,282.0 ±69.7 (4.4%) | 1,108.5 (x0.865) | 1,108.5 (x0.865) | 28,234 / 80,568 / 80,568 | 2.67 / 2.67 / 2.67 | loss (g loss, ttft loss, tpot tie) / loss (g loss, ttft loss, tpot tie) |
| `cb_kv_8k_b32_ramp@H100` | V | 459.5 ±37.1 (6.5%) | 451.0 (x0.981) | 451.0 (x0.981) | 6,372 / 2,188 / 2,188 | 6.41 / 6.41 / 6.41 | win (g tie, ttft win, tpot tie) / win (g tie, ttft win, tpot tie) |
| `cb_mixed_8k_b32@B200` | V | 394.3 ±33.8 (6.9%) | 220.6 (x0.559) | 220.6 (x0.559) | 4,314 / 2,966 / 2,967 | 2.53 / 2.51 / 2.51 | loss (g loss, ttft win, tpot tie) / loss (g loss, ttft win, tpot tie) |
| `cb_mixed_8k_b32@H100` | V | 402.2 ±13.3 (2.7%) | 200.6 (x0.499) | 200.6 (x0.499) | 3,894 / 2,993 / 2,993 | 6.29 / 6.17 / 6.17 | loss (g loss, ttft win, tpot win) / loss (g loss, ttft win, tpot win) |

#### 같은 offered load(Baseline peak load)에서의 비교

각 arm의 peak load는 다르므로 위 표의 TTFT는 서로 다른 load 점의 값이다. 아래는 Baseline의 peak load에서 세 arm을 같은 요청 흐름으로 비교한 값이다(QA3와 `*_common` QA2의 기준).

| 시나리오 @ 시스템 | Baseline peak load | goodput B / C1 / C2 (tok/s, 그 load에서) | TTFT P99 ms B / C1 / C2 | KV 상주 GiB B / C1 / C2 | 각 arm의 own-peak load (B / C1 / C2) |
|---|---:|---|---|---|---|
| `cb_kv_8k_b32@B200` | x1 | 972 / 0 / 0 | 3,195 / 80,290 / 80,291 | 16.7 / 385.7 / 385.7 | x1 / x0.5 / x0.5 |
| `cb_kv_8k_b32@H100` | x1.5 | 460 / 402 / 402 | 6,371 / 6,703 / 6,703 | 14.8 / 19.2 / 19.2 | x1.5 / x1 / x1 |
| `cb_kv_8k_b32_ramp@B200` | x1.5 | 1,282 / 1,108 / 1,108 | 28,234 / 80,568 / 80,568 | 26.6 / 58.0 / 58.0 | x1.5 / x1.5 / x1.5 |
| `cb_kv_8k_b32_ramp@H100` | x1.5 | 460 / 432 / 432 | 6,372 / 7,245 / 7,245 | 14.8 / 16.9 / 16.9 | x1.5 / x1 / x1 |
| `cb_mixed_8k_b32@B200` | x0.5 | 394 / 0 / 0 | 4,314 / 75,142 / 75,142 | 12.5 / 200.6 / 200.6 | x0.5 / x0.25 / x0.25 |
| `cb_mixed_8k_b32@H100` | x1 | 402 / 16 / 16 | 3,894 / 39,611 / 39,612 | 13.2 / 90.0 / 90.0 | x1 / x0.5 / x0.5 |

### 4.2.2 DP4-specific

| 시나리오 @ 시스템 | Fit | Baseline goodput ±CI (CV) | C1 goodput (ratio) | C2 goodput (ratio) | TTFT P99 ms B / C1 / C2 | TPOT P99 ms B / C1 / C2 | 판정 vs Baseline C1 / C2 |
|---|---|---|---|---|---|---|---|
| `d4_agent_multiturn@B200` | V | 8,549.4 ±377.9 (3.6%) | 4,454.2 (x0.521) | 4,454.2 (x0.521) | 588 / 368 / 372 | 7.48 / 3.22 / 3.21 | loss (g loss, ttft tie, tpot win) / loss (g loss, ttft tie, tpot win) |
| `d4_agent_multiturn@H100` | V | 2,317.1 ±2,387.6 (83.0%) | 3,839.5 (x1.657) | 3,839.5 (x1.657) | 3,414 / 698 / 710 | 17.89 / 9.93 / 9.92 | win (g tie, ttft tie, tpot win) / win (g tie, ttft tie, tpot win) |
| `d4_block16@B200` | V | 3,094.3 ±52.9 (1.4%) | 3,092.7 (x0.999) | 3,092.7 (x0.999) | 1,458 / 1,502 / 1,502 | 2.72 / 2.73 / 2.73 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_block16@H100` | V | 1,220.2 ±71.4 (4.7%) | 1,210.1 (x0.992) | 1,209.9 (x0.992) | 3,318 / 3,360 / 3,361 | 6.53 / 6.57 / 6.56 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_block256@B200` | V | 3,094.3 ±52.9 (1.4%) | 3,092.7 (x0.999) | 3,092.7 (x0.999) | 1,458 / 1,502 / 1,502 | 2.72 / 2.73 / 2.73 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_block256@H100` | V | 1,220.2 ±71.4 (4.7%) | 1,210.1 (x0.992) | 1,210.1 (x0.992) | 3,318 / 3,360 / 3,360 | 6.53 / 6.57 / 6.57 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_fail_lockholder[as_published]@B200` | V | 1,897.0 ±43.9 (1.9%) | 1,892.6 (x0.998) | 1,852.0 (x0.976) | 6,306 / 6,360 / never | 2.71 / 2.73 / never | tie (g tie, ttft tie, tpot tie) / loss (g loss, ttft loss, tpot loss) |
| `d4_fail_lockholder[as_published]@H100` | V | 882.6 ±15.4 (1.4%) | 882.2 (x1.000) | 863.0 (x0.978) | 5,382 / 5,425 / never | 6.49 / 6.48 / never | tie (g tie, ttft tie, tpot tie) / loss (g loss, ttft loss, tpot loss) |
| `d4_fail_lockholder[lease]@B200` | V | 1,897.0 ±43.9 (1.9%) | 1,892.6 (x0.998) | 1,891.2 (x0.997) | 6,306 / 6,360 / 6,391 | 2.71 / 2.73 / 2.73 | tie (g tie, ttft tie, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_fail_lockholder[lease]@H100` | S | 882.6 ±15.4 (1.4%) | 882.2 (x1.000) | 881.5 (x0.999) | 5,382 / 5,425 / 5,641 | 6.49 / 6.48 / 6.49 | tie (g tie, ttft tie, tpot tie) / tie (g tie, ttft tie, tpot tie) |
| `d4_fail_server[node_loss]@B200` | V | 3,094.3 ±52.9 (1.4%) | 1,419.8 (x0.459) | 3,092.7 (x0.999) | 1,458 / 29,056 / 1,502 | 2.72 / 2.69 / 2.73 | loss (g loss, ttft loss, tpot win) / tie (g tie, ttft loss, tpot tie) |
| `d4_fail_server[node_loss]@H100` | V | 1,220.2 ±71.4 (4.7%) | 789.9 (x0.647) | 1,210.0 (x0.992) | 3,318 / 27,798 / 3,360 | 6.53 / 6.44 / 6.57 | loss (g loss, ttft loss, tpot win) / tie (g tie, ttft loss, tpot tie) |
| `d4_fail_server[restart]@B200` | V | 3,094.3 ±52.9 (1.4%) | 3,091.5 (x0.999) | 3,092.7 (x0.999) | 1,458 / 1,516 / 1,502 | 2.72 / 2.73 / 2.73 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_fail_server[restart]@H100` | V | 1,220.2 ±71.4 (4.7%) | 1,210.0 (x0.992) | 1,210.0 (x0.992) | 3,318 / 3,360 / 3,360 | 6.53 / 6.55 / 6.57 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_hot_prefix_fanout@B200` | V | 3,094.3 ±52.9 (1.4%) | 3,092.7 (x0.999) | 3,092.7 (x0.999) | 1,458 / 1,502 / 1,502 | 2.72 / 2.73 / 2.73 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_hot_prefix_fanout@H100` | V | 1,220.2 ±71.4 (4.7%) | 1,210.1 (x0.992) | 1,209.9 (x0.992) | 3,318 / 3,360 / 3,360 | 6.53 / 6.57 / 6.57 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_lock_stripes_1@B200` | V | 6,192.7 ±98.2 (1.3%) | 6,192.7 (x1.000) | 6,192.7 (x1.000) | 793 / 843 / 842 | 2.72 / 2.73 / 2.73 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_lock_stripes_1@H100` | V | 2,690.0 ±74.0 (2.2%) | 2,684.8 (x0.998) | 2,684.8 (x0.998) | 1,803 / 1,846 / 1,846 | 6.53 / 6.53 / 6.53 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_lock_stripes_512@B200` | V | 6,192.7 ±98.2 (1.3%) | 6,192.7 (x1.000) | 6,192.7 (x1.000) | 793 / 843 / 842 | 2.72 / 2.73 / 2.72 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_lock_stripes_512@H100` | V | 2,690.0 ±74.0 (2.2%) | 2,684.8 (x0.998) | 2,684.6 (x0.998) | 1,803 / 1,846 / 1,848 | 6.53 / 6.53 / 6.52 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_lock_stripes_8@B200` | V | 6,192.7 ±98.2 (1.3%) | 6,192.7 (x1.000) | 6,192.7 (x1.000) | 793 / 843 / 842 | 2.72 / 2.73 / 2.73 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_lock_stripes_8@H100` | V | 2,690.0 ±74.0 (2.2%) | 2,684.8 (x0.998) | 2,684.8 (x0.998) | 1,803 / 1,846 / 1,846 | 6.53 / 6.53 / 6.53 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_node_scale_n16@B200` | V | 12,385.4 ±196.4 (1.3%) | 12,385.4 (x1.000) | 12,385.4 (x1.000) | 467 / 512 / 512 | 2.72 / 2.72 / 2.72 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_node_scale_n16@H100` | V | 5,444.1 ±86.3 (1.3%) | 5,444.1 (x1.000) | 5,444.1 (x1.000) | 1,064 / 1,107 / 1,108 | 6.52 / 6.52 / 6.52 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_node_scale_n2@B200` | V | 1,462.0 ±82.1 (4.5%) | 1,456.4 (x0.996) | 1,456.4 (x0.996) | 2,800 / 2,843 / 2,843 | 2.67 / 2.67 / 2.67 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_node_scale_n2@H100` | V | 459.9 ±37.4 (6.6%) | 455.2 (x0.990) | 455.2 (x0.990) | 6,371 / 1,876 / 1,876 | 6.41 / 6.41 / 6.41 | win (g tie, ttft win, tpot tie) / win (g tie, ttft win, tpot tie) |
| `d4_node_scale_n4@B200` | V | 3,094.3 ±52.9 (1.4%) | 3,092.7 (x0.999) | 3,092.7 (x0.999) | 1,458 / 1,502 / 1,502 | 2.72 / 2.73 / 2.73 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_node_scale_n4@H100` | V | 1,220.2 ±71.4 (4.7%) | 1,210.1 (x0.992) | 1,210.0 (x0.992) | 3,318 / 3,360 / 3,360 | 6.53 / 6.57 / 6.57 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_node_scale_n8@B200` | V | 6,192.7 ±98.2 (1.3%) | 6,192.7 (x1.000) | 6,192.7 (x1.000) | 793 / 843 / 841 | 2.72 / 2.73 / 2.73 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_node_scale_n8@H100` | V | 2,690.0 ±74.0 (2.2%) | 2,684.8 (x0.998) | 2,684.8 (x0.998) | 1,803 / 1,846 / 1,846 | 6.53 / 6.53 / 6.54 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_pool_full_eviction@B200` | V | 3,094.3 ±52.9 (1.4%) | 3,092.7 (x0.999) | 3,092.7 (x0.999) | 1,458 / 1,502 / 1,502 | 2.72 / 2.73 / 2.73 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_pool_full_eviction@H100` | V | 1,220.2 ±71.4 (4.7%) | 1,210.1 (x0.992) | 1,210.0 (x0.992) | 3,318 / 3,360 / 3,360 | 6.53 / 6.57 / 6.57 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_server_threads_2@B200` | V | 6,192.7 ±98.2 (1.3%) | 6,192.7 (x1.000) | 6,192.7 (x1.000) | 793 / 843 / 842 | 2.72 / 2.73 / 2.73 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_server_threads_2@H100` | V | 2,690.0 ±74.0 (2.2%) | 2,684.8 (x0.998) | 2,684.8 (x0.998) | 1,803 / 1,846 / 1,846 | 6.53 / 6.53 / 6.53 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_server_threads_4@B200` | V | 6,192.7 ±98.2 (1.3%) | 6,192.7 (x1.000) | 6,192.7 (x1.000) | 793 / 843 / 842 | 2.72 / 2.73 / 2.73 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_server_threads_4@H100` | V | 2,690.0 ±74.0 (2.2%) | 2,684.8 (x0.998) | 2,684.8 (x0.998) | 1,803 / 1,846 / 1,846 | 6.53 / 6.53 / 6.53 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_small_prompt_highqps@B200` | V | 14,134.8 ±224.2 (1.3%) | 14,134.8 (x1.000) | 14,134.8 (x1.000) | 82 / 85 / 85 | 2.51 / 2.51 / 2.51 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |
| `d4_small_prompt_highqps@H100` | V | 6,213.0 ±98.5 (1.3%) | 6,213.0 (x1.000) | 6,213.0 (x1.000) | 187 / 190 / 190 | 6.01 / 6.01 / 6.01 | tie (g tie, ttft loss, tpot tie) / tie (g tie, ttft loss, tpot tie) |

**주의 (`d4_agent_multiturn@H100`):** Baseline goodput의 CV가 83%인 것은 seed 5개 중 일부에서 TTFT P99가 폭증하며 goodput이 붕괴하기 때문이다. seed별 goodput(tok/s, seed 11, 23, 37, 53, 71): Baseline 3,557 / 3,753 / 3,840 / 389 / 46; C1 3,557 / 3,761 / 3,865 / 4,038 / 3,976; seed별 TTFT P99(ms): Baseline 894 / 1,752 / 1,962 / 6,961 / 5,499; C1 642 / 630 / 704 / 776 / 737. 이 쌍의 goodput 판정은 tie(쌍별 차이의 95% CI ±2,572 tok/s)이다.

## 4.3 Diagnostic

| 지표 (Common 6쌍 평균, Baseline peak load) | Baseline | C1 | C2 |
|---|---:|---:|---:|
| 링크 점유율 egress / ingress | 64% / 64% | 80% / 80% | 80% / 80% |
| 풀 점유율 | 0.0% | 10.5% | 10.5% |
| 서버 점유율 (C1 metadata server) | 0.00e+00 | 1.44e-05 | 0.00e+00 |
| 전역 락 점유율 최대 (C2) | 0.00e+00 | 0.00e+00 | 1.41e-05 |
| 락 대기 P99 (ms) | 0.00 | 0.00 | 0.04 |
| coherence CPU core-equivalent | 0.00 | 1.00 | 1.00 |
| KV 상주 구성 (GiB, P buffer / D HBM / 풀) | 6.3 / 10.1 / 0.0 | 114.4 / 9.9 / 4.1 | 114.4 / 9.9 / 4.1 |

| control-plane 연산 (DP4 행 38쌍의 Baseline-peak load 기준) | C1 P50 (us) | C2 P50 (us) | C2 ÷ C1 (P50) |
|---|---|---|---|
| lookup | 2.11 ~ 4.04 | 2.6 ~ 245.7 | 1.2 ~ 60.8 |
| publish | 2.11 ~ 7.30 | 21.6 ~ 737.8 | 9.2 ~ 313.0 |
| pin | 2.11 ~ 7.30 | 53.4 ~ 803.8 | 20.6 ~ 240.2 |
| unpin | 2.11 ~ 7.30 | 52.7 ~ 399.2 | 20.6 ~ 119.3 |

**Control-plane 포화(open-loop sweep).** 연산(lookup/publish/pin/unpin)만 실행하는 요청 흐름을 100 req/s부터 2배씩 올려 P99 chain latency가 100 req/s 때의 10배가 되는 최저 rate를 포화로 본다. 제공 rate는 해당 행의 own-peak load에서 시뮬레이션이 실제로 낸 rate다.

| 시나리오 @ 시스템 | 제공 request rate (req/s, 클러스터) | C1 포화 rate (req/s) | C2 포화 rate (req/s) | 여유 배수 C1 / C2 |
|---|---:|---:|---:|---|
| `d4_block16@B200` | 12.2 | 51,200 | 102,400 | 4,212 / 8,424 |
| `d4_block16@H100` | 5.3 | 51,200 | 102,400 | 9,582 / 19,164 |
| `d4_block256@B200` | 12.2 | 1,638,400 | 409,600 | 134,777 / 33,694 |
| `d4_block256@H100` | 5.3 | 1,638,400 | 409,600 | 306,621 / 76,655 |
| `d4_hot_prefix_fanout@B200` | 12.2 | 204,800 | 6,400 | 16,847 / 526 |
| `d4_hot_prefix_fanout@H100` | 5.3 | 204,800 | 6,400 | 38,328 / 1,198 |
| `d4_lock_stripes_1@B200` | 24.3 | 204,800 | 6,400 | 8,424 / 263 |
| `d4_lock_stripes_1@H100` | 10.7 | 204,800 | 6,400 | 19,164 / 599 |
| `d4_lock_stripes_512@B200` | 24.3 | 204,800 | 400 | 8,424 / 16 |
| `d4_lock_stripes_512@H100` | 10.7 | 204,800 | 400 | 19,164 / 37 |
| `d4_lock_stripes_8@B200` | 24.3 | 204,800 | 6,400 | 8,424 / 263 |
| `d4_lock_stripes_8@H100` | 10.7 | 204,800 | 6,400 | 19,164 / 599 |
| `d4_node_scale_n16@B200` | 48.6 | 409,600 | 102,400 | 8,424 / 2,106 |
| `d4_node_scale_n16@H100` | 21.4 | 409,600 | 102,400 | 19,164 / 4,791 |
| `d4_node_scale_n2@B200` | 6.1 | 409,600 | 409,600 | 67,388 / 67,388 |
| `d4_node_scale_n2@H100` | 1.8 | 409,600 | 409,600 | 229,966 / 229,966 |
| `d4_node_scale_n4@B200` | 12.2 | 409,600 | 409,600 | 33,694 / 33,694 |
| `d4_node_scale_n4@H100` | 5.3 | 409,600 | 409,600 | 76,655 / 76,655 |
| `d4_node_scale_n8@B200` | 24.3 | 409,600 | 204,800 | 16,847 / 8,424 |
| `d4_node_scale_n8@H100` | 10.7 | 409,600 | 204,800 | 38,328 / 19,164 |
| `d4_pool_full_eviction@B200` | 12.2 | 409,600 | 409,600 | 33,694 / 33,694 |
| `d4_pool_full_eviction@H100` | 5.3 | 409,600 | 409,600 | 76,655 / 76,655 |
| `d4_server_threads_2@B200` | 24.3 | 409,600 | 3,200 | 16,847 / 132 |
| `d4_server_threads_2@H100` | 10.7 | 409,600 | 3,200 | 38,328 / 299 |
| `d4_server_threads_4@B200` | 24.3 | 819,200 | 3,200 | 33,694 / 132 |
| `d4_server_threads_4@H100` | 10.7 | 819,200 | 3,200 | 76,655 / 299 |
| `d4_small_prompt_highqps@B200` | 222.0 | 3,276,800 | 409,600 | 14,762 / 1,845 |
| `d4_small_prompt_highqps@H100` | 97.6 | 3,276,800 | 409,600 | 33,584 / 4,198 |

## 4.4 C1 vs C2 직접 비교 / Scalability / 장애

**성능:** C2 대 C1의 Common QA 차이 QA1 goodput 0.0000%, 공통 load TTFT P99 0.0012%, QA3 KV 상주 0.0051%; 장애 행을 뺀 DP4 쌍의 goodput 차이 최대 0.0167%. 값은 같고 C1과 C2는 QA1~QA3에서 구분되지 않는다.

**Scalability (제안 지표, 별 없음, 노드당 부하 고정, 통합=시스템 기하평균):** 1을 넘는 값은 P 노드 수가 늘며 대기열이 풀링되는 효과(DESIGN_NOTES A.22)이며 control plane 병목 부재를 뜻하지 않는다. 값은 Baseline도 같은 범위다.

| 노드 수 N (P+D) | Baseline | C1 | C2 | Baseline H100 / B200 | C1 H100 / B200 |
|---|---:|---:|---:|---|---|
| 4 (2+2) | 1.185 | 1.188 | 1.188 | 1.327 / 1.058 | 1.329 / 1.062 |
| 8 (4+4) | 1.244 | 1.252 | 1.252 | 1.462 / 1.059 | 1.475 / 1.063 |
| 16 (8+8) | 1.252 | 1.261 | 1.261 | 1.480 / 1.059 | 1.495 / 1.063 |

**장애** (as-published와 보완안을 분리 보고, 시스템별):

| 행 @ 시스템 | goodput ÷ Baseline C1 / C2 | SLO 위반 증가 (요청) B / C1 / C2 | 미완료(고착) 요청 C1 / C2 | 가용성 창 (s) C1 / C2 | 고착 stripe C2 | TTFT P99 (ms, 장애 포함) B / C1 / C2 |
|---|---|---|---|---|---|---|
| `d4_fail_lockholder[as_published]@B200` | x0.998 / x0.976 | 163 / 167 / 202 | 0 / 41 | 0.0 / ∞ | 1 | 6,306 / 6,360 / never |
| `d4_fail_lockholder[as_published]@H100` | x1.000 / x0.978 | 67 / 68 / 106 | 0 / 41 | 0.0 / ∞ | 1 | 5,382 / 5,425 / never |
| `d4_fail_lockholder[lease]@B200` | x0.998 / x0.997 | 163 / 167 / 168 | 0 / 0 | 0.0 / 1.0 | 0 | 6,306 / 6,360 / 6,391 |
| `d4_fail_lockholder[lease]@H100` | x1.000 / x0.999 | 67 / 68 / 69 | 0 / 0 | 0.0 / 1.0 | 0 | 5,382 / 5,425 / 5,641 |
| `d4_fail_server[node_loss]@B200` | x0.459 / x0.999 | 0 / 1,892 / 0 | 0 / 0 | 30.0 / 0.0 | 0 | 1,458 / 30,031 / 1,502 |
| `d4_fail_server[node_loss]@H100` | x0.647 / x0.992 | 0 / 1,307 / 0 | 0 / 0 | 30.0 / 0.0 | 0 | 3,318 / 30,001 / 3,360 |
| `d4_fail_server[restart]@B200` | x0.999 / x0.999 | 0 / 1 / 0 | 0 / 0 | 0.5 / 0.0 | 0 | 1,458 / 1,516 / 1,502 |
| `d4_fail_server[restart]@H100` | x0.992 / x0.992 | 0 / 0 / 0 | 0 / 0 | 0.5 / 0.0 | 0 | 3,318 / 3,360 / 3,360 |

## 4.5 시스템·파일 간 일관성 확인

| 확인 항목 | 비교 수 | 최대 편차 | 결과 |
|---|---:|---:|---|
| 통합 파일의 (시나리오, 시스템) 쌍별 Max SLO goodput = 시스템별 파일 | 132 | 0.00e+00 | 일치 |
| C1 Common QA1 geomean 재계산(시스템별 쌍 6개) vs 통합 파일 | 6 | 0.00e+00 | 일치 |
| C2 Common QA1 geomean 재계산(시스템별 쌍 6개) vs 통합 파일 | 6 | 0.00e+00 | 일치 |
| ablation 대조군(full C1/C2/Baseline) = 본 결과 (SKILL §9) | 132 | 0.00e+00 | 일치 |
| sensitivity 통제 셀(eta_cxl 0.5, bg 0.85) = 본 결과 | 3 | 0.00e+00 | 일치 |
| star_basis 첫 seed 묶음(11..71) = 본 결과 Baseline | 6 | 0.00e+00 | 일치 |
| loop-log 본문의 수치 (QA1 0.733 -> 0.704, QA3 0.230 -> 0.223) 가 데이터와 일치 | 4 | 0.00e+00 | 일치 |
| loop-log의 승/무/패 (2/34/8 -> 4/33/7) 가 데이터와 일치 | 2 | 0.00e+00 | 일치 |
| QA4 측정 기준 소스(sha1)와 현재 `DP4/sim` 소스 일치 (불일치: sensitivity.py, simulator.py, test_sim.py) | 12 | 3.00e+00 | **불일치** |

**불일치 보고:** QA4 변경 시나리오의 측정은 Iteration 2(순차 read) 이전의 시뮬레이터 복사본(측정 기준 소스 중 `sensitivity.py, simulator.py, test_sim.py`가 현재와 다름)에서 이루어졌다. QA4가 센 module(CXL-RPC channel, metadata server, 락·할당기·flush 계층)은 `arms.py`에 있고 `arms.py`와 `cluster_dp4.json`은 base와 일치하지만, 공통 module인 GPU↔CXL Copy/DMA handler는 `simulator.py`에 있어 Iteration 2에서 바뀐 부분이다(S4의 shared 크기 산정에 영향 가능). 재측정하지 않았으며 6장에 한계로 적었다.

## 4.6 Ablation (SKILL §9, `DP4/sim/ablation.py`)

각 후보의 핵심 구성요소를 제거한 변형을 같은 시나리오·시스템·seed로 실행했다. `C1-no-batch` = RPC당 블록 hash 1개(batch 제거), `C2-no-scan` = 락 매니저 scan 대기 제거(직접 hand-off). 대조군(full 후보)은 본 결과와 일치한다(4.5). 데이터 revision은 `fb9ecab`이다.

| arm | Common QA1 (ratio) | Common QA3 절감 | Common TTFT P99 공통 load (ms) | DP4 38쌍 QA1 ratio | 별 합계 (QA1~3, Common) |
|---|---|---|---|---|---|
| Baseline-RDMA | ★★ x1.0000 | x1.0000 | 6,283 | x1.0000 | 5 |
| C1-central-serialization | ★ x0.7044 | x0.2230 | 31,271 | x0.9627 | 3 |
| C1-no-batch | ★ x0.7044 | x0.2230 | 31,271 | x0.9627 | 3 |
| C2-distributed-lock | ★ x0.7044 | x0.2230 | 31,271 | x0.9925 | 3 |
| C2-no-scan | ★ x0.7044 | x0.2230 | 31,271 | x0.9925 | 3 |

제거 변형과 full 후보의 goodput 차이는 최대 0.0000%(C1-no-batch), 0.0084%(C2-no-scan)이며 별 합계와 선정 결과는 변하지 않는다 -> **제거해도 순위가 바뀌지 않는다.** 단 control-plane 지연에는 영향이 있다(`d4_hot_prefix_fanout@B200`, Baseline peak load): C2 pin P50 112.7 us -> scan 제거 시 68.1 us, C1 publish P50 2.4 us -> batch 제거 시 4.7 us(lookup 3.1 -> 10.0 us). 이 영향은 TTFT의 0.028% 미만이라 QA에 드러나지 않는다. 효과가 어느 하위 메커니즘에서 오는지 분해하면: 성능(QA1~QA3) 차이는 어느 구성요소에서도 나오지 않고(data plane 지배) control-plane 지연 차이만 각 구성요소(scan, batching)에서 나온다.

## 4.7 별점 경계의 근거 (SKILL §10, `DP4/sim/star_basis.py`)

| 시스템 | Baseline끼리 QA1 잡음 (겹치지 않는 seed 묶음 4개, 쌍 6개) 최대 편차 / 평균 편차 | 하한 0.90 ÷ 잡음 (여유 배수) | QA3 절감 배수 잡음 최대 편차 | QA3 하한 0.95 대비 |
|---|---|---|---|---|
| SYS-H100 | 1.7% / 1.0% | 6.0 | 24.3% (평균 12.3%) | 잡음이 경계(5%)보다 큼 |
| SYS-B200 | 5.0% / 2.6% | 2.0 | 8.1% (평균 4.4%) | 잡음이 경계(5%)보다 큼 |

- **하한(★/★★) QA1 0.90:** Baseline-vs-Baseline 잡음(겹치지 않는 seed 묶음 4개의 같은 집계)의 최대 편차보다 크다(여유 배수 위 표). 측정은 시뮬레이션 잡음이며 하드웨어 잡음이 아니다 [B+C].
- **QA3 하한 0.95는 잡음 안에 있다:** Baseline 간 QA3 절감 배수의 흔들림이 SYS-H100에서 24.3%, SYS-B200에서 8.1%로 5%보다 크다. 후보의 QA3 절감 배수(x0.22)는 경계(0.95)보다 훨씬 아래라 ★ 판정은 잡음에 민감하지 않지만, Baseline의 ★★ 판정과 0.95 경계의 의미는 측정으로 뒷받침되지 않는다.
- **상한(★★/★★★) 1.10, 1.25와 QA2의 시간 경계, QA4 경계:** 측정으로 정해지는 값이 아니라 정책 선택(공통 문서의 사전 정의)이다. 환산 근거를 만들지 않았다(미구현). 후보가 상한 근처에 있지 않으므로(QA1 x0.704, QA3 절감 x0.22) 상한 민감도는 선택에 영향이 없다.


**QA1~QA3 경계 x0.9 / x1.1 (모든 경계 동시) 시 별** (INT, 사전 등록 경계를 결과 후 바꾼 것이 아닌 민감도):

| 경계 배율 (모든 QA1~QA3 경계에 동시 적용) | Baseline (QA1/QA2/QA3, 합) | C1 | C2 |
|---|---|---|---|
| x0.9 | 3/1/2 (합 6) | 1/1/1 (합 3) | 1/1/1 (합 3) |
| x1.0 | 2/1/2 (합 5) | 1/1/1 (합 3) | 1/1/1 (합 3) |
| x1.1 | 2/1/1 (합 4) | 1/1/1 (합 3) | 1/1/1 (합 3) |

## 4.8 민감도 (Iteration 1, 파라미터 재조정이 아닌 보고; main 값은 불변)

모든 설정을 SYS-H100·SYS-B200에서 같은 benchmark로 재실행했고 (η_cxl 0.5, bg 0.85) 셀은 main 결과를 정확히 재현했다(4.5). **어떤 셀도 main으로 승격하지 않았다.** 배경 부하 bg는 ASSUMED 시나리오 상수다(CB-1/3의 수준 c로 모든 bg를 c/0.85배, CB-2는 형태 유지).

**QA1 geomean ratio (>= 1.00이면 Baseline 도달; C1 = C2)** (통합, 12셀; η_cxl x 배경 부하 상한)

| η_cxl \ bg | 0.0 | 0.5 | 0.85 |
|---|---|---|---|
| 0.5 | 0.992 / 0.992 | 0.937 / 0.937 | 0.704 / 0.704 |
| 0.7 | 0.993 / 0.993 | 0.991 / 0.991 | 0.988 / 0.988 |
| 0.85 | 0.994 / 0.994 | 0.992 / 0.992 | 1.077 / 1.077 |
| 1 | 0.995 / 0.995 | 0.993 / 0.993 | 1.150 / 1.150 |

**QA3 절감 배수 (Baseline peak load; >= 1.00이면 도달)** (통합, 12셀; η_cxl x 배경 부하 상한)

| η_cxl \ bg | 0.0 | 0.5 | 0.85 |
|---|---|---|---|
| 0.5 | 0.923 / 0.923 | 0.600 / 0.599 | 0.223 / 0.223 |
| 0.7 | 0.944 / 0.944 | 0.901 / 0.901 | 0.872 / 0.872 |
| 0.85 | 0.954 / 0.953 | 0.922 / 0.922 | 1.043 / 1.043 |
| 1 | 0.960 / 0.960 | 0.934 / 0.934 | 1.135 / 1.135 |

**TTFT P99 악화 쌍 수 (공통 load, 6쌍 중) C1 / C2**

| η_cxl \ bg | 0.0 | 0.5 | 0.85 |
|---|---|---|---|
| 0.5 | 4 / 4 | 6 / 6 | 6 / 6 |
| 0.7 | 3 / 3 | 4 / 4 | 2 / 2 |
| 0.85 | 1 / 1 | 4 / 4 | 1 / 2 |
| 1 | 1 / 1 | 4 / 4 | 1 / 1 |

**Break-even** (후보가 Baseline에 도달하는 η_cxl; 보간값). 대역폭 동등점(후보 노드 CXL 유효 대역 = Baseline RDMA 유효 대역)은 η_cxl = 0.675(= 85 GB/s ÷ 126 GB/s)이다.

| 범위 | 기준 | bg 0.0 | bg 0.5 | bg 0.85 (main 배경) |
|---|---|---|---|---|
| INT-H100-B200 | QA1 ratio >= 0.99 (parity, 1% tie 기준) | η 0.5(격자 최소)에서 이미 충족 | η_cxl* 0.698 | η_cxl* 0.703 |
| INT-H100-B200 | QA1 ratio >= 1.00 | 격자 내 없음 (최고 0.995 @ η 1) | 격자 내 없음 (최고 0.993 @ η 1) | η_cxl* 0.720 |
| INT-H100-B200 | QA3 절감 배수 >= 0.99 | 격자 내 없음 (최고 0.960 @ η 1) | 격자 내 없음 (최고 0.934 @ η 1) | η_cxl* 0.803 |
| SYS-H100 | QA1 ratio >= 0.99 (parity, 1% tie 기준) | η_cxl* 0.737 | 격자 내 없음 (최고 0.989 @ η 1) | η_cxl* 0.739 |
| SYS-H100 | QA1 ratio >= 1.00 | 격자 내 없음 (최고 0.992 @ η 1) | 격자 내 없음 (최고 0.989 @ η 1) | η_cxl* 0.768 |
| SYS-H100 | QA3 절감 배수 >= 0.99 | 격자 내 없음 (최고 0.977 @ η 1) | 격자 내 없음 (최고 0.955 @ η 1) | 격자 내 없음 (최고 0.953 @ η 1) |
| SYS-B200 | QA1 ratio >= 0.99 (parity, 1% tie 기준) | η 0.5(격자 최소)에서 이미 충족 | η_cxl* 0.696 | η_cxl* 0.695 |
| SYS-B200 | QA1 ratio >= 1.00 | 격자 내 없음 (최고 0.997 @ η 1) | 격자 내 없음 (최고 0.996 @ η 1) | η_cxl* 0.700 |
| SYS-B200 | QA3 절감 배수 >= 0.99 | 격자 내 없음 (최고 0.945 @ η 1) | 격자 내 없음 (최고 0.914 @ η 1) | η_cxl* 0.754 |

**provenance:** η_cxl* 값은 모두 사전 등록 ASSUMED 범위 [0.25, 0.9] 안이다. η_cxl 자체가 ASSUMED(PAPER 근거는 어댑터 63 GB/s x 2)이고 비교 대상인 η_rdma도 ASSUMED(0.85)이므로 **ASSUMED 대 ASSUMED 비교**다. 어느 쪽이 맞는지 이 평가는 알지 못한다. TTFT P99 악화 쌍 0은 격자의 어떤 설정에서도 달성되지 않았다(최소 1쌍).

**단일 파라미터 민감도 (통합, Common)**

| 변경 | 값 | QA1 ratio C1 / C2 | QA3 절감 C1 / C2 | TTFT P99 악화 쌍 (공통 load) |
|---|---|---|---|---|
| bg_pm01 | bg0.75 | 0.918 / 0.918 | 0.509 / 0.508 | 6 / 6 |
| bg_pm01 | bg0.95 | 0.674 / 0.674 | 0.602 / 0.602 | 3 / 3 |
| eta_rdma | eta_rdma0.6 | 0.987 / 0.987 | 0.852 / 0.852 | 4 / 4 |
| eta_rdma | eta_rdma0.95 | 0.660 / 0.660 | 0.194 / 0.194 | 6 / 6 |
| overlap | overlap0.5 | 0.705 / 0.705 | 0.224 / 0.224 | 6 / 6 |
| overlap | overlap0.9 | 0.705 / 0.705 | 0.223 / 0.223 | 6 / 6 |

**Control-plane 파라미터 민감도 (S, probe, critical section 수, metadata 비용, RPC batch, 서버 스레드)** — **Iteration 2에서 재실행하지 않았다**(loop-log: move path 수정과 무관하며 Iteration 1에서 Common 결과를 움직이지 않음). 아래는 수정 전 모델(`pre_serial_read`, git 0e44b58)의 값이며 대체된 모델의 값이라 절대값(예: 0.733)을 현재 값과 섞지 말 것. 결론(Common 결과가 control-plane 상수에 무관)만 인용한다.

| 파라미터 | 값 | Common QA1 ratio C1 / C2 | Common QA3 절감 C1 / C2 |
|---|---|---|---|
| lock_stripes | S1 | 0.733 / 0.733 | 0.230 / 0.230 |
| lock_stripes | S512 | 0.733 / 0.733 | 0.230 / 0.230 |
| lock_stripes | S8 | 0.733 / 0.733 | 0.230 / 0.230 |
| probe_us | probe0.1 | 0.733 / 0.733 | 0.230 / 0.230 |
| probe_us | probe0.7 | 0.733 / 0.733 | 0.230 / 0.230 |
| cs_per_request | cs2 | 0.733 / 0.733 | 0.230 / 0.187 |
| cs_per_request | cs5 | 0.733 / 0.733 | 0.230 / 0.230 |
| meta_cost_us | meta0.7 | 0.733 / 0.733 | 0.230 / 0.230 |
| meta_cost_us | meta2.0 | 0.733 / 0.733 | 0.230 / 0.230 |
| rpc_hash_batch | batch16 | 0.733 / 0.733 | 0.230 / 0.230 |
| rpc_hash_batch | batch4 | 0.733 / 0.733 | 0.230 / 0.230 |
| server_threads | T2 | 0.733 / 0.733 | 0.230 / 0.230 |
| server_threads | T4 | 0.733 / 0.733 | 0.230 / 0.230 |

## 4.9 Protocol model check (정확성, [C], 별점 아님)

모델: DP4 protocol model check (abstract non-coherent CXL shared memory), Evidence [C] design-level model. explicit-state BFS(정확 상태 dedupe, 최단 반례). 한 block 수명 동안 eviction 1회와 재할당, 전역 락 stripe 1개, 노드 2개(또는 3개) + 락 매니저 호스트(C2) / 서버 호스트(C1), 상태 상한 1,500,000. 불변식: **I1** payload visibility: after seeing READY the payload read is the complete value the writer wrote; **I2** no use-after-free: a block with refcount>0 (a reader holds a pin) is never evicted/reallocated; **I3** mutual exclusion: at most one node inside the critical section of the global lock (C2); **I4** no stale index resurrect: a READY entry observed after the block was freed is never used.

### 4.9.1 2노드 (`protocol_check.json`)

| 변종 | 종류 | 기대 위반 | 탐색 (상태 수, 전수 여부) | I1 가시성 | I2 use-after-free | I3 상호 배제 | I4 stale index | 반례 최단 길이 |
|---|---|---|---|---|---|---|---|---|
| C1 | normal | — | 349,431 (전수) | 통과(전수) | 통과(전수) | 통과(전수) | 통과(전수) | — |
| C2 | normal | — | 322,000 (전수) | 통과(전수) | 통과(전수) | 통과(전수) | 통과(전수) | — |
| C2_clflushopt | defect | I2 | 1,500,000 (**상한 도달**) | 반례 없음(상한 도달, 불완전) | **위반** | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | I2:79 |
| C2_no_invalidate_before_read | defect | I2 | 1,400,740 (전수) | **위반** | **위반** | 통과(전수) | **위반** | I1:79, I2:72, I4:77 |
| C2_no_flush_before_unlock | defect | I2 | 1,500,000 (**상한 도달**) | **위반** | **위반** | 반례 없음(상한 도달, 불완전) | **위반** | I1:82, I2:76, I4:80 |
| C2_manager_double_grant | defect | I3 | 1,310,948 (전수) | **위반** | **위반** | **위반** | 통과(전수) | I1:78, I2:69, I3:58 |
| publish_before_dma_complete | defect | I1 | 669,736 (전수) | **위반** | 통과(전수) | 통과(전수) | 통과(전수) | I1:61 |
| C1_no_clflush_on_server | defect | I1 | 1,500,000 (**상한 도달**) | **위반** | **위반** | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | I1:21, I2:71 |
| payload_via_cpu_cache | defect | I1 | 1,500,000 (**상한 도달**) | **위반** | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | I1:62 |

- **정상 프로토콜:** C1과 C2 모두 상태 349,431 / 322,000개를 **전수 탐색**했고 I1~I4에 반례가 없다(모델 안에서의 통과, 구현의 정확성이 아님).
- **결함 변종 검출(검사기 자체의 검증):** 결함 변종 7개 중 기대한 불변식 위반을 낸 것은 7개(C2_clflushopt, C2_no_invalidate_before_read, C2_no_flush_before_unlock, C2_manager_double_grant, publish_before_dma_complete, C1_no_clflush_on_server, payload_via_cpu_cache). 각 변종이 위반한 불변식: `C2_clflushopt` -> I2; `C2_no_invalidate_before_read` -> I1, I2, I4; `C2_no_flush_before_unlock` -> I1, I2, I4; `C2_manager_double_grant` -> I1, I2, I3; `publish_before_dma_complete` -> I1; `C1_no_clflush_on_server` -> I1, I2; `payload_via_cpu_cache` -> I1. 일부는 기대 외의 불변식도 위반했다(예: `C2_manager_double_grant`는 기대한 I3 외에 I1, I2도 위반).
- **탐색 상한(cap)에 걸려 전수가 아닌 변종:** `C2_clflushopt`, `C2_no_flush_before_unlock`, `C1_no_clflush_on_server`, `payload_via_cpu_cache`. 이 변종들에서 '반례 없음'으로 표시된 불변식은 **탐색한 부분에서 못 찾았다는 뜻일 뿐 통과가 아니다**. 이미 위반으로 찾은 불변식은 반례(최단 경로)가 있으므로 그 위반은 모델 안에서 실재한다(trace는 `check.py`가 행동열을 처음부터 replay해 생성). 예: `C2_clflushopt`는 I2 위반만 찾았고 I1·I3·I4는 상한 도달로 불완전하며, `payload_via_cpu_cache`는 I1 위반을 찾았으나 I2~I4는 불완전하다. 정상 C1/C2와 `C2_no_invalidate_before_read`, `C2_manager_double_grant`, `publish_before_dma_complete`는 상한 안에서 전수 탐색했다(전수 탐색에서 '통과'로 표시된 불변식은 모델 안에서 완전한 결과).

### 4.9.2 3노드 (`protocol_check_n3.json`) — **n=3 caveat**

| 변종 | 종류 | 기대 위반 | 탐색 (상태 수, 전수 여부) | I1 가시성 | I2 use-after-free | I3 상호 배제 | I4 stale index | 반례 최단 길이 |
|---|---|---|---|---|---|---|---|---|
| C1 | normal | — | 1,500,000 (**상한 도달**) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | — |
| C2 | normal | — | 1,500,000 (**상한 도달**) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | — |
| C2_clflushopt | defect | I2 | 1,500,000 (**상한 도달**) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | — |
| C2_no_invalidate_before_read | defect | I2 | 1,500,000 (**상한 도달**) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | — |
| C2_no_flush_before_unlock | defect | I2 | 1,500,000 (**상한 도달**) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | — |
| C2_manager_double_grant | defect | I3 | 1,500,000 (**상한 도달**) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | — |
| publish_before_dma_complete | defect | I1 | 1,500,000 (**상한 도달**) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | — |
| C1_no_clflush_on_server | defect | I1 | 1,500,000 (**상한 도달**) | **위반** | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | I1:21 |
| payload_via_cpu_cache | defect | I1 | 1,500,000 (**상한 도달**) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | 반례 없음(상한 도달, 불완전) | — |

- **n=3에서는 모든 변종의 탐색이 상한(1,500,000 상태)에 걸렸다**(정상 C1·C2 포함). 따라서 3노드의 정상 C1·C2 결과는 '탐색한 범위에서 반례 없음'일 뿐 통과가 아니다. 결함 변종 7개 중 3노드에서 위반을 검출한 것은 **1개(`C1_no_clflush_on_server`)뿐**이다. 나머지 변종이 3노드에서 검출되지 않은 것은 결함이 없어서가 아니라(2노드에서는 검출됨) 상태 공간이 상한 안에서 해당 반례에 닿지 못했기 때문이다. 즉 3노드 결과는 검사기의 한계를 보여 주며 후보에 대한 증거로 쓰지 않는다. 2노드 전수 결과가 이 DP의 정확성 증거이고, N >= 3 확장은 **미검증**이다.
- **`C1_no_clflush_on_server`의 결과를 결정하는 가정(stale slot-body).** 이 변종은 I1을 위반했다(반례 21 step, 2노드·3노드 모두). 그러나 이 결과는 **저자 가정**에 의존한다: 요청 슬롯이 flag 줄과 별도의 body 줄로 나뉘고 body 줄은 재사용되어 이전 요청(UNPIN)의 내용을 담은 채 서버 캐시에 이미 있을 수 있다. 이 가정이 없고 sequence-numbered 핸드셰이크를 쓰면 서버의 CLFLUSH 누락은 안전성 위반이 아니라 liveness 문제(영원히 stale 값을 기다림)가 되며, 이 검사기는 safety만 본다(liveness 미검사). 논문에는 이 슬롯 배치가 규정되어 있지 않다(모델 README의 '논문 근거 대 저자 가정' 표). 락 매니저 배치, 슬롯 재사용 규칙도 저자 가정이다.
- **검사하지 않은 것:** safety만(I1~I4), liveness/progress 미검사, 단일 워드 cell, 한 block 수명, 락 stripe 1개, DMA read는 워드 단위 동기, allocator 상태는 entry cell에 흡수(다중 writer allocator 경합 미모델), 실제 CPU/CXL 하드웨어 메모리 모델의 검증이 아님. 한계 원문: Design-level abstract model of non-coherent caches; not a verification of real CPU/CXL hardware memory models. / A pass means 'no counterexample inside this model and this explored scope', not correctness of an implementation. / Safety only (I1..I4); liveness/progress (e.g. spinning forever on a stale line) is not checked.

## 4.10 QA4 상세 (측정: `qa4_measured_counts.json`, 계산: `qa4_modifiability.json`, 도구 `tools/qa4_modifiability.py`)

| 변경 시나리오 | C1 module (shared) · LOC · module 크기 · 공수 MM · 비용 $ (T1) | C2 module (shared) · LOC · module 크기 · 공수 MM · 비용 $ (T1) |
|---|---|---|
| S1: new hardware capability (CXL 3.x CoherentRegion: cross-node CAS in a 64 KiB hardware-coherent region) | 1 (0) · 11 · 20 · 0.274 · $0.86 | 1 (0) · 13 · 109 · 0.298 · $1.06 |
| S2: new object class (variable-length COMP_KV object, 1..16 blocks, format_version) | 3 (2) · 16 · 86 · 0.619 · $1.46 | 3 (2) · 16 · 85 · 0.619 · $1.45 |
| S3: policy swap (pool eviction: LRU -> access frequency x reconstruction cost score, constructor injection) | 1 (0) · 6 · 16 · 0.214 · $0.83 | 1 (0) · 6 · 18 · 0.214 · $0.83 |
| S4: new topology element (two pools, object id carries pool_id, sharded allocate/lookup) | 4 (3) · 14 · 101 · 0.738 · $1.71 | 4 (3) · 28 · 194 · 0.905 · $2.08 |
| **평균 (별 판정 기준)** | **2.25 · 0.461 MM · $1.21** | **2.25 · 0.509 MM · $1.35** |

sub-star(시나리오 평균): C1 ★★/★★★/★★★, C2 ★★/★★/★★★ (M1/M2/M3). 최악값 집계(v1)에서는 두 후보 모두 ★★이다. M2 공수 평균 C1 0.461, C2 0.509 MM (경계 0.5). M1 평균 module 2.25은 ★★★ 경계(2)보다 12.5% 위다.

QA4의 가정 상수 민감도와 구조 대안별 별은 0.3의 표에 있다. 구조 대안 설명: S1_coherent_region_counted_as_shared_module: analytic: +1 shared module, +4 LOC (config 2 + Params 2) for both candidates; size 36 = Sim.on_xfer+on_move_done+on_pinned; S3_C2_entry_layout_extended: analytic: C2 +1 module, +2 LOC (two per-entry fields); C1 unchanged; S1_C2_flagged_major_interface_change: preregistration rule: M1 = one star for C2 (module count irrelevant); all_analytic_alternatives_together: (a)+(b)+(c). 측정은 실제 에이전트 세션이 아니라 **시뮬레이터 proxy 구현**의 diff이며, 공수·가격·배율은 가정이다. component 귀속은 판단이다.

## 4.11 Iteration summary (Baseline-regression loop, [`iterations/loop-log.md`](iterations/loop-log.md))

| Iteration | Class (P/B/S/M/N) | Change | Effect (전체 benchmark 기준) |
|---|---|---|---|
| 0 (initial, git 0e44b58) | — | 변경 없음. 기준 실행 | **Trigger 발동.** Common QA1 C1=C2 x0.733 (H100 x0.812, B200 x0.663), QA3 절감 x0.230, TTFT P99 악화 쌍 5/6(최악 x25.0), 승/무/패 2/34/8 |
| 1 | S (진단, main 불변) | η_cxl {0.5, 0.7, 0.85, 1.0} x 배경 부하 {0, 0.5, 0.85} 12셀 + η_rdma, overlap, bg ±0.1, control-plane 파라미터(S, probe, cs, threads, batch, metadata cost), 별 경계 ±10% 민감도. main 값은 바꾸지 않음 | 격차는 data plane 효율 가정에서 옴. 당시 모델의 break-even η_cxl* (QA1 parity, bg 0.85) = 0.671. C1/C2는 모든 셀에서 QA1~QA3 동일(loop-log 기록: 차이 <= 0.03%). 모델 결함 1건(read가 write와 겹침) 확인 -> Iteration 2 |
| 2 | M | 후보 move path를 write(prefill과만 겹침) -> publish -> pin -> read -> decode의 순차로 수정 (read는 publish 이후에만 시작). Baseline 경로·모든 파라미터 불변. 수정 전 결과는 `results/data/pre_serial_read/`에 보존 | QA1 x0.733 -> **x0.704** (H100 x0.812 -> x0.783, B200 x0.663 -> x0.634); QA3 절감 x0.230 -> x0.223; TTFT P99 악화 쌍 5/6 -> 6/6 (최악 x25.0 -> x25.1); 승/무/패 2/34/8 -> 4/33/7; break-even η_cxl* 0.671 -> 0.703. 판정: 후보는 Baseline 미만 -> **사전 등록 규칙에 따라 중단**, 추가 iteration으로 파라미터를 조정하지 않음 |

**중단 규칙 결과.** 모든 comparison-valid 시나리오와 집계 QA에서 후보 >= Baseline이어야 한다는 중단 조건 (i)은 충족되지 않았다(후보 < Baseline인 Common 쌍이 남고, goodput이 95% CI 밖으로 좋아진 쌍(N_win)도 0쌍으로 기준 3 미만). 로그의 사전 등록 판정 규칙(Iteration 2)에 따라 추가 iteration으로 η_cxl 등 가정을 조정하지 않고 멈췄다(최대 6 iteration 중 2회 사용). 시도한 변경: Iteration 1 = 민감도 진단(변경 없음, class S), Iteration 2 = 순차 read 수정(class M). 문장: **under the tested conditions the architecture shows no benefit over the baseline** (CXL 공유 풀 data plane 대 RDMA data plane; 후보 C1·C2 모두). 이 문서가 사용자에게 올리는 escalation이다.

## 4.12 수정 전 결과와의 대조 (H16, H9)

| 지표 (통합 Common, C1 = C2) | 수정 전 (`pre_serial_read`, git 0e44b58) | 수정 후 (main, git cb98109) |
|---|---|---|
| QA1 ratio | 0.733 (★) | 0.704 (★) |
| QA1 ratio SYS-H100 | 0.812 | 0.783 |
| QA1 ratio SYS-B200 | 0.663 | 0.634 |
| QA2 별 / TTFT P99 공통 load (ms) | ★ / 30,763 | ★ / 31,271 |
| QA3 절감 배수 / KV 상주 (GiB) | 0.230 / 69.2 | 0.223 / 71.3 |
| 승/무/패 (44쌍) C1 | 2/34/8 | 4/33/7 |
| fit (DP4 행) comparison-valid / saturated | 6 / 32 | 37 / 1 |
| QA1 parity break-even η_cxl* (통합, bg 0.85) | 0.671 | 0.703 |
| 별 (QA1/QA2/QA3) | ★/★/★ | ★/★/★ |

사유: 후보 move path가 write와 read를 한 cut-through flow로 겹쳐 후보에 유리하게 편향되어 있었다(read는 publish 이후에만 가능). 수정으로 별은 바뀌지 않았고 격차가 커졌다. 수정은 사전 등록(loop-log Iteration 2)했고 이전 결과는 `results/data/pre_serial_read/`에 보존했다.

# 5. 결과 분석

## 5.1 Baseline 미만 (또는 이득이 의심스러운) 모든 쌍의 root cause

| 쌍 | 후보 < Baseline? (C1 / C2 판정) | Root cause | Class | 근거 diagnostic |
|---|---|---|---|---|
| `cb_kv_8k_b32@B200` | loss / loss | data plane: 풀 경유 쓰기 + 읽기 순차가 Baseline의 단일 RDMA 전송보다 링크를 더 오래 점유(config 어림값: RDMA 211 ms 대 CXL 568 ms/요청, bg 0.85)하고 η_cxl 0.5 대 η_rdma 0.85(둘 다 ASSUMED). 후보는 더 낮은 load(x0.5)에서 goodput peak를 갖고 Baseline peak load(x1)에서는 포화한다 | S (η 가정) + M (순차 read 모델 수정, Iteration 2); P 아님 | goodput x0.527; 공통 load TTFT P99 3,195 -> 80,290 ms; 링크 점유 B 86% / C1 57%; KV 상주 16.7 -> 385.7 GiB |
| `cb_kv_8k_b32_ramp@B200` | loss / loss | data plane: 풀 경유 쓰기 + 읽기 순차가 Baseline의 단일 RDMA 전송보다 링크를 더 오래 점유(config 어림값: RDMA 211 ms 대 CXL 568 ms/요청, bg 0.85)하고 η_cxl 0.5 대 η_rdma 0.85(둘 다 ASSUMED). 후보도 같은 load(x1.5)에서 peak이나 goodput이 낮고 TTFT P99가 악화된다 | S (η 가정) + M (순차 read 모델 수정, Iteration 2); P 아님 | goodput x0.865; 공통 load TTFT P99 28,234 -> 80,568 ms; 링크 점유 B 55% / C1 68%; KV 상주 26.6 -> 58.0 GiB |
| `cb_mixed_8k_b32@B200` | loss / loss | data plane: 풀 경유 쓰기 + 읽기 순차가 Baseline의 단일 RDMA 전송보다 링크를 더 오래 점유(config 어림값: RDMA 211 ms 대 CXL 568 ms/요청, bg 0.85)하고 η_cxl 0.5 대 η_rdma 0.85(둘 다 ASSUMED). 후보는 더 낮은 load(x0.25)에서 goodput peak를 갖고 Baseline peak load(x0.5)에서는 포화한다 | S (η 가정) + M (순차 read 모델 수정, Iteration 2); P 아님 | goodput x0.559; 공통 load TTFT P99 4,314 -> 75,142 ms; 링크 점유 B 85% / C1 57%; KV 상주 12.5 -> 200.6 GiB |
| `cb_mixed_8k_b32@H100` | loss / loss | data plane: 풀 경유 쓰기 + 읽기 순차가 Baseline의 단일 RDMA 전송보다 링크를 더 오래 점유(config 어림값: RDMA 211 ms 대 CXL 568 ms/요청, bg 0.85)하고 η_cxl 0.5 대 η_rdma 0.85(둘 다 ASSUMED). 후보는 더 낮은 load(x0.5)에서 goodput peak를 갖고 Baseline peak load(x1)에서는 포화한다 | S (η 가정) + M (순차 read 모델 수정, Iteration 2); P 아님 | goodput x0.499; 공통 load TTFT P99 3,894 -> 39,611 ms; 링크 점유 B 75% / C1 50%; KV 상주 13.2 -> 90.0 GiB |
| `d4_agent_multiturn@B200` | loss / loss | reuse 시나리오에서 Baseline은 세션 고정 D가 History KV를 보유해 후속 턴에 D-local 증분 prefill만 하는 반면, 후보는 매 턴 전체 context를 풀에서 읽는다(D ingress)(DESIGN_NOTES A.11). B200은 prefill이 빨라 Baseline의 D-local 경로가 유리하고, H100에서는 같은 구조가 반대로 나온다(5.2, Baseline seed 불안정). 한 시나리오 쌍의 진단이며 일반화하지 않는다 | B/S (benchmark·시스템 의존, 구조 결함 단정 불가) | goodput B 8,549 / C1 4,454 (peak load x1 / x0.5); C1 ingress 점유 57% (Baseline 6%); 풀 상주 414 GiB |
| `d4_fail_lockholder[as_published]@B200` | tie / loss | C2 락 보유 노드 장애에서 as-published 락이 풀리지 않아 stripe 고착 | P (후보 구조의 장애 특성; 설계 결함이 아니라 문서화된 한계. 보완안: 스탠바이 / lease) | C2 goodput x0.976; 가용성 창 ∞ s; 고착 요청 41 |
| `d4_fail_lockholder[as_published]@H100` | tie / loss | C2 락 보유 노드 장애에서 as-published 락이 풀리지 않아 stripe 고착 | P (후보 구조의 장애 특성; 설계 결함이 아니라 문서화된 한계. 보완안: 스탠바이 / lease) | C2 goodput x0.978; 가용성 창 ∞ s; 고착 요청 41 |
| `d4_fail_server[node_loss]@B200` | loss / tie | C1 메타데이터 서버 노드 손실 후 30 s 인덱스 재구성 동안 요청이 대기(SPOF) | P (후보 구조의 장애 특성; 설계 결함이 아니라 문서화된 한계. 보완안: 스탠바이 / lease) | C1 goodput x0.459; 가용성 창 30.0 s; 고착 요청 0 |
| `d4_fail_server[node_loss]@H100` | loss / tie | C1 메타데이터 서버 노드 손실 후 30 s 인덱스 재구성 동안 요청이 대기(SPOF) | P (후보 구조의 장애 특성; 설계 결함이 아니라 문서화된 한계. 보완안: 스탠바이 / lease) | C1 goodput x0.647; 가용성 창 30.0 s; 고착 요청 0 |

**Common Benchmark 6쌍 모두에서 TTFT P99(공통 load)가 Baseline보다 나쁘다**(꼬리 점검, SKILL §10): B200 cb_kv_8k_b32 x25.13, H100 cb_kv_8k_b32 x1.05, B200 cb_kv_8k_b32_ramp x2.85, H100 cb_kv_8k_b32_ramp x1.14, B200 cb_mixed_8k_b32 x17.42, H100 cb_mixed_8k_b32 x10.17. TPOT P99는 악화 쌍 0쌍. 이 꼬리 악화는 이득이 아니라 같은 data plane 원인(순차 read와 낮은 유효 대역)에서 오며 Baseline-regression loop를 돈 이유다.

**DP4-specific 행의 꼬리.** 장애 행을 뺀 30쌍에서 후보 TTFT P99(own-peak)는 Baseline의 x0.204~x1.095이고 1% 넘게 나쁜 쌍이 27쌍, TTFT 판정이 loss인 쌍이 27쌍이다. 중앙값 x1.024로 크기는 작지만 거의 모든 쌍에서 같은 방향이며, 순차 read가 TTFT에 노출된 효과다(goodput 판정은 tie라 쌍 판정은 tie). 이 방향성은 이득이 아니라 약한 비용으로 읽는다.

## 5.2 이득으로 판정된 쌍의 원인 (과대평가 점검)

'win' 판정은 4쌍(C1 = C2)이며 **goodput이 95% CI 밖으로 좋아진 쌍은 0쌍**이다. 4쌍 모두 지연 등급 판정이다(`compare_pair`: QA2 별이 올라가고 TTFT 또는 TPOT 판정이 win).

| 쌍 | goodput 판정 / 지연 등급 판정 | 같은 load 비교? | 원인 |
|---|---|---|---|
| `cb_kv_8k_b32@H100` | tie / win | 아니오 | **own-peak 비교 효과**: goodput은 tie(x0.980)이고 후보의 peak load(x1)가 Baseline(x1.5)보다 낮아 own-peak TTFT P99가 6,371 -> 2,166 ms로 보일 뿐, Baseline peak load에서는 6,371 -> 6,703 ms로 후보가 더 느리다. 이득 근거로 쓰지 않는다 |
| `cb_kv_8k_b32_ramp@H100` | tie / win | 아니오 | **own-peak 비교 효과**: goodput은 tie(x0.981)이고 후보의 peak load(x1)가 Baseline(x1.5)보다 낮아 own-peak TTFT P99가 6,372 -> 2,188 ms로 보일 뿐, Baseline peak load에서는 6,372 -> 7,245 ms로 후보가 더 느리다. 이득 근거로 쓰지 않는다 |
| `d4_agent_multiturn@H100` | tie / win | 예 | 같은 load(x1)에서 TTFT P99 3,414 -> 698 ms, TPOT P99 17.9 -> 9.9 ms. goodput은 x1.66이나 tie(쌍별 차이 95% CI ±2,572 tok/s): Baseline seed별 goodput 3,557/3,753/3,840/389/46 대 C1 3,557/3,761/3,865/4,038/3,976으로 Baseline이 일부 seed에서 붕괴(CV 83%)해 생긴 차이다. 후보의 TTFT/TPOT가 seed 간 안정적이라는 신호는 있으나(후보 CV 5%) 5 seed로는 확정할 수 없고 B200에서는 반대다 |
| `d4_node_scale_n2@H100` | tie / win | 아니오 | **own-peak 비교 효과**: goodput은 tie(x0.990)이고 후보의 peak load(x1)가 Baseline(x1.5)보다 낮아 own-peak TTFT P99가 6,371 -> 1,876 ms로 보일 뿐, Baseline peak load에서는 6,371 -> 6,413 ms로 후보가 더 느리다. 이득 근거로 쓰지 않는다 |

## 5.3 QA별 '왜 이 값인가' 요약

- **QA1 (x0.704):** 쌍별 비 B200 kv_8k_b32 x0.53, H100 kv_8k_b32 x0.98, B200 kv_8k_b32_ramp x0.86, H100 kv_8k_b32_ramp x0.98, B200 mixed_8k_b32 x0.56, H100 mixed_8k_b32 x0.50. B200의 prefill이 빨라 링크가 병목이라 낮고, H100 CB-1/2는 거의 같으나 CB-3(혼합, 객체 수 증가)은 x0.50.
- **QA2:** Baseline도 TTFT P99 최악 28,234 ms로 ★이다. 후보는 80,568 ms(★). TPOT P99는 4.07 vs 4.04 ms로 거의 같다 — TPOT는 decode의 HBM 대역폭이 정하고 DP4는 decode 방식을 바꾸지 않기 때문이다(KV는 decode 시작 전에 HBM에 도착). TTFT는 KV 이동이 TTFT에 노출되는 경로라 영향을 받는다.
- **QA3:** 사전 등록 정의에서 후보가 Baseline peak load에서 포화해 P buffer에 쌓인 요청이 KV 상주를 키운다(P buffer 114.4 vs 6.3 GiB). 풀 사본(평균 4.1 GiB)은 후보 값의 작은 부분이다. 각 arm의 own-peak에서는 13.6 vs 15.9 GiB로 후보가 낮다. 정의 의존성은 0.3의 7번.
- **QA4:** 4.10. 신규 HW capability(S1)와 정책 교체(S3)는 두 후보 모두 module 1개, 객체 class(S2)와 topology(S4)는 shared module이 지배한다. 차이는 S4와 S1에서 C2의 module이 더 커서 생긴다.

## 5.4 사전 등록 예측(`simulation-plan.md` §10)과 결과

결과를 보기 전에 기록한 5개 예측을 결과로 채점한다. 예측을 고쳐 쓰지 않았다(H16).

| 사전 예측 | 판정 | 근거 (데이터) |
|---|---|---|
| 1. control plane 지연은 µs 규모, KV 이동·prefill은 수십~수백 ms라 C1과 C2의 QA1·QA2 차이는 노이즈 수준일 것 | **성립 (단, 'saturated 라벨'은 아님)** | C1 대비 C2 차이: Common QA1 0.000%, 공통 load TTFT P99 0.001%, QA3 0.005%; 장애 행을 뺀 DP4 쌍의 goodput 차이 최대 0.017%. 연산당 control plane P50은 C1 2.1~7.3 µs, C2 2.6~803.8 µs이고 `d4_hot_prefix_fanout@H100`에서 요청 하나의 4연산 합은 C1 12.1 µs, C2 439.1 µs로 TTFT P50의 0.001% / 0.051%. **그러나** 계획 §6.2는 대부분이 saturated일 것이라 예상했는데 실제 fit 라벨은 DP4 38쌍 중 comparison-valid 37, saturated 1이다. saturated는 모든 arm(Baseline 포함)이 같을 때만 붙는데 Baseline과 후보의 data plane 차이가 있어 C1≈C2여도 comparison-valid가 된다(Iteration 2 이후 read가 TTFT에 노출되어 6쌍 -> 37쌍으로 바뀜). 예측의 '후보 간 차이 없음'은 맞고 '라벨'은 틀렸다 |
| 2. 차이는 control plane 연산률이 지배하는 영역(작은 prompt, 작은 block, 높은 rate, 많은 노드)에서만 나타나고, 현실적 rate(노드당 수십 req/s)에서는 두 구조 모두 포화하지 않을 것 | **부분 성립** | 제공 rate는 클러스터 최대 222.0 req/s, 노드당 최대 55.5 req/s(`d4_small_prompt_highqps`, 노드 4개)이고 이 범위에서 두 구조 모두 포화하지 않았다(포화 rate ÷ 제공 rate 최소 16배: C2 `d4_lock_stripes_512@B200`, 포화 400 req/s ÷ 제공 24.3 req/s). 작은 prompt·작은 block·16노드 행에서도 C1≈C2(위 1.)라 '그 영역에서 차이가 나타난다'는 부분은 **확인되지 않았다**. 다만 C2는 S x N에 따라 포화 rate가 줄어(아래 3.) `d4_lock_stripes_512`(노드 8개)의 C2 포화 rate 400 req/s는 노드당 50 req/s에 해당해, 계획이 말한 '노드당 수십 req/s'를 이 구성에 가하면 포화 영역에 들어간다(산술 환산이며 시뮬레이션하지 않은 외삽) |
| 3. C2는 락 매니저 scan 비용(S x N x t_probe)과 hot 락 경합에서 갈리고, C1은 서버 단일 큐 포화와 SPOF에서 갈릴 것 | **성립 (포화 rate와 장애에서 확인, QA에는 안 드러남)** | C2 포화 rate는 stripe 1/8/(64)/512에서 6,400/6,400/3,200/400 req/s, 노드 수 4/8/16에서 409,600/204,800/102,400 req/s로 S x N이 커질수록 낮아진다. C1 포화 rate는 서버 스레드 1/2/4에서 204,800/409,600/819,200 req/s. SPOF: 서버 프로세스 재시작(0.5 s, 인덱스 보존)은 영향이 없고(x0.999, x0.992) 노드 손실(인덱스 재구성 30 s)은 Baseline 대비 goodput B200 x0.459, H100 x0.647. C2 락 보유 노드 장애(as-published)는 stripe가 풀리지 않아 요청 41, 41건 고착, 가용성 창 ∞, goodput x0.976, x0.978; lease 1 s 보완안은 x0.997, x0.999. hot 락 경합은 락 대기 P99 0.09 ms로 존재하나 goodput에는 보이지 않는다 |
| 4. Baseline-RDMA 대비 후보의 이득은 data plane 상수(η_cxl, η_rdma, 중첩 비율)가 지배하고 두 후보가 같으므로 선택 근거가 못 된다. 이득 주장은 reuse 시나리오와 민감도로 한정 | **부분 성립 (data plane 지배는 성립, reuse 이득은 확정 못 함)** | Common QA1 격차는 두 후보에서 같고(위 1.) η_cxl 격자에서 x0.704 -> x1.150로 움직인다(break-even η_cxl* 0.703). overlap 0.5/0.9는 거의 영향 없음, η_rdma 0.6/0.95에서 x0.987/x0.660. reuse 시나리오 `d4_agent_multiturn`의 goodput 비는 B200 x0.521, H100 x1.657로 H100에서는 높고 B200에서는 낮다. H100의 이득은 Baseline seed 일부의 붕괴에서 오며 goodput 판정은 tie라(5.2) '이득이 reuse에 있다'는 예측도 통계적으로 확정되지 않았고 시스템에 의존한다 |
| 5. 실질적 trade-off는 QA1/QA2가 아니라 QA4, 확장 한계, 장애·정확성에 있고, 확인되면 '정합성 구조는 성능 레버가 아니다'가 결론 | **성립 (QA4 차이는 경계 근처)** | QA1~QA3은 C1=C2(별 같음). 별이 갈리는 곳은 QA4뿐이며 C1 ★★★ (MM 0.461) 대 C2 ★★ (0.509), 경계 0.5 MM와의 거리 C1 7.7%(아래) / C2 1.8%(위). 장애 특성(C1 SPOF 노드 손실, C2 락 고착)과 model check(C1 vs C2)는 별점 밖에서 갈린다. 결론은 '성능 레버가 아니다'로 확인되며, QA1~QA3의 Baseline 격차는 후보가 아니라 data plane에서 온다 |

**맞지 않은 부분:** (i) 'saturated' 라벨 예측(위 1.) — Baseline과 후보의 data plane 차이 때문에 라벨이 comparison-valid가 되었다; (ii) '차이는 control plane이 지배하는 영역에서 나타난다'(위 2.) — 그런 영역을 만들어도 C1≈C2였다; (iii) '이득을 reuse 시나리오로 한정'(위 4.) — reuse 시나리오의 H100 이득은 통계적으로 확정되지 않았고(Baseline seed 붕괴) B200에서는 반대였다. 나머지 예측(C1≈C2, scan 비용과 SPOF/락 고착, QA4·장애에서의 trade-off)은 데이터로 확인되었다.

# 6. 한계

1. **Evidence:** 사용자 환경에 CXL 공유 풀이 없어 **모든 성능 수치는 [B+C]이며 [A] 실측은 없다.** 입력은 두 논문(Beluga, TraCT)의 서버 2대·단일 벤더 장치 조건 측정이고, 8·16노드는 외삽이다. η_cxl, η_rdma, 중첩 비율, background 부하, lease는 ASSUMED이다.
2. **Baseline 대비 결론은 ASSUMED 상수에 의존한다.** 격차의 크기와 break-even(η_cxl* 0.703)은 η_cxl(0.5)과 η_rdma(0.85) 두 ASSUMED 값의 비교다. 문헌값(PAPER)으로 확정된 효율은 없다. '이득 없음'은 이 가정 범위의 결과이며 CXL 풀이 일반적으로 이득이 없다는 주장이 아니다. 풀의 이득은 prefix 공유·reuse에서 기대하는 것이고 이 평가의 reuse 시나리오는 1개(`d4_agent_multiturn`)다.
3. **C2의 락 관련 상수는 논문에 없는 ASSUMED**(scan 비용 t_probe, critical section 길이/수, stripe 수, 장애 처리)이다. C2의 절대 성능 주장은 하지 않으며, C2의 control-plane 지연·포화 rate는 이 가정에 의존한다. 락 보유 노드 장애의 보완안(lease)은 평가자의 가정이다. control-plane 파라미터 민감도는 Iteration 2 이후 재실행하지 않았고 수정 전 모델의 결과만 있다(4.8).
4. **Model checker는 추상 모델**이다. 실제 CPU·CXL 하드웨어 메모리 모델의 검증이 아니며 safety만 본다. 2노드 전수 탐색이 증거이고 3노드는 모든 변종이 탐색 상한에 걸려 불완전하다(4.9). 일부 2노드 결함 변종도 상한에 걸렸다. `C1_no_clflush_on_server` 결과는 stale slot-body 가정에 의존한다.
5. **QA4는 proxy 구현이다.** 실제 vLLM이 아니라 시뮬레이터 복사본에 변경을 구현해 diff를 센 것이고 공수·가격·배율은 가정이다. 두 후보의 차이는 M2 경계(0.5 MM)에서 C1 7.7% 아래, C2 1.8% 위로 근소하며 경계/집계/상수 변형 24가지 중 상당수에서 두 후보가 같은 별이 된다(0.3). **별 차이가 경계 선택에 의존한다**(H11 (d)). QA4 측정에 쓴 시뮬레이터 소스 중 sensitivity.py, simulator.py, test_sim.py는 측정 이후 바뀌었다(Iteration 2: `simulator.py`의 move path). 재측정하지 않았다.
6. **QA4 집계(시나리오 평균)는 DP1 v2의 소유자 결정과 같은 규칙을 처음부터 등록한 것**이며(사후 변경 아님) 최악값 집계에서는 두 후보 모두 ★★이다.
7. **Scalability는 공식 QA가 아닌 제안**이다. 값만 보고하고 별점을 매기지 않았다. 값이 1을 넘는 것은 P 노드 대기열 풀링 효과이며 N=2 기준(단일 P 노드)이 대기열 한계라 해석에 주의.
8. **`qa_priority.json`은 proposal (사용자 확정 전)**이다. 선택(0.3)은 이 제안 우선순위와 무관하게 별 합계로 정해지지만(합계 6 대 5) 합계 차이는 QA4 한 칸이다.
9. **정의 이력(H16).** (i) Iteration 2에서 후보 move path를 순차 read로 수정했다(M). 수정 전→후: Common QA1 x0.733 → x0.704, QA3 절감 x0.230 → x0.223, 공통 load TTFT P99 악화 쌍 5/6 → 6/6, 승/무/패 2/34/8 → 4/33/7. 별은 두 경우 모두 QA1 ★, QA2 ★, QA3 ★로 변하지 않았다(4.12). (ii) 평가 정의(QA1~QA3 경계, SLO, Baseline)는 결과를 본 뒤 바꾸지 않았다. (iii) QA3 정의는 DP1 경계를 가져온 임시 정의이며 DP4에서의 적정성은 검증되지 않았다.
10. **Common의 '압박' 정의는 임의적이다.** 링크 background load(0.85, 0.2→0.9)는 DP1의 HBM 용량 축소와 의미가 달라 DP 간 공통 별점 직접 비교에 한계가 있다. 압박을 0.5로 낮추면 QA1 ratio가 0.937, 0으로 낮추면 0.992이다(4.8).
11. **QA3와 QA2의 load 의존성.** QA3(사전 등록: Baseline peak load, 같은 요청 구간)는 후보가 포화한 load에서 비교되어 값이 크게 나쁘다. own-peak 기준으로는 ★★ 구간이다(0.3의 7번). QA2의 별은 각 arm의 own-peak load 기준이라 후보 TTFT가 더 좋아 보이는 효과가 있으며 공통 load 행을 병기했다. 별 경계 하한 QA3 0.95는 Baseline 잡음 안에 있다(4.7).
12. **시뮬레이터가 모델링하지 않는 것:** 실제 CXL 장치·CPU 캐시 동작, GPU↔CXL DMA 세부(scatter/gather는 평균 효율에 흡수), 풀 장치 bank 경합·인터리빙·스위치 혼잡(집계 BW 상한만), 락 매니저·서버 스레드의 CPU 스케줄링 간섭, 풀 장치 장애, HBM·풀 용량 한계, node-local 락 대기열, host DRAM tier, DP3 압축, KV 외 객체의 종류별 접근 패턴, 다중 테넌트. Baseline의 fragmentation 페널티는 의도적으로 넣지 않았다(강한 baseline).
13. **Fit 라벨과 승/무/패 해석:** DP4 행 대부분이 comparison-valid인 것은 Baseline과 후보 사이 data plane 차이 때문이며 C1과 C2의 차이가 아니다. `d4_node_scale_n2`는 reference 행인데 집계 쌍(38쌍)에 포함되어 있다(DESIGN_NOTES A.5). Baseline의 `d4_agent_multiturn@H100` goodput CV가 83%로 커서 그 이득의 정밀도는 낮다.
14. **통합 파일 meta의 git dirty 플래그:** 통합 및 SYS-B200 실행은 dirty, SYS-H100 실행은 clean으로 기록되어 있다(1장). dirty는 `doc-mk/Evaluation/DP4` 아래의 미커밋 변경을 뜻하며 같은 `cluster_dp4.json`(sha1 일치)과 대조군 일치로 숫자의 동일성은 확인했으나 코드 revision 완전 일치는 아니다. 같은 명령 + 같은 revision에서 같은 숫자가 나오는지는 `test_sim.py`의 `test_same_seed_same_result`가 검증한다. ablation(`fb9ecab`)과 수정 전 결과(`0e44b58`)는 다른 revision에서 생성되었다.
15. **미구현·미실시 항목:** 0.4의 보완 택틱 중 [C]로 표시한 것(W1 스탠바이 인계, W3 슬롯 검증값, W4 partial read·청크 publish·하이브리드, W5, W6)은 구현하지 않았고 효과를 측정하지 않았다. [B]는 이미 시뮬레이터에 있는 기능(프로세스 재시작, 서버 스레드, block 크기)의 측정이다. QA4 재측정, 서버 2대 초과·실제 CXL 풀 측정, `d4_agent_multiturn`의 seed 추가, control-plane 민감도의 재실행, N >= 3 model check의 전수 탐색도 미실시다.
16. **H17(모델 오차 sweep)은 해당 없음**(estimator 비의존). **DP1의 H10 profile 규칙**: 기존 profile은 수정하지 않았고 DP4 profile을 신규 추가했다.

# 7. 결론

- **결정 관련 진술 (1): Baseline 대비.** **under the tested conditions the architecture shows no benefit over the baseline** — CXL 공유 풀 data plane은 C1과 C2 모두에서 Baseline-RDMA보다 QA1 x0.704(★), QA3 절감 x0.22(★), 공통 load TTFT P99 x4.98로 낮다. Baseline-regression loop를 2회 수행(iteration 0 기준, 1 진단 sweep, 2 모델 수정)했고 후보는 Baseline 미만으로 남아 로그의 사전 등록 규칙에 따라 중단했다. 시도한 변경: Iteration 1(η_cxl x 배경 부하 등 민감도, 변경 없음), Iteration 2(순차 read 수정). **break-even η_cxl*는 QA1 parity 0.703(H100 0.739, B200 0.695), QA1 >= 1.00 0.720, QA3 절감 0.803**(bg 0.85 기준; bg 0.5에서는 QA1 parity 0.698, QA3는 격자 내 없음)이며 **둘 다 ASSUMED 상수(η_cxl 대 η_rdma)의 비교**라 어느 쪽이 맞는지 이 평가로는 모른다. 대역폭 동등점은 0.675이다. 이 문서가 skill §5의 escalation이다: 사용자 판단이 필요한 것은 η_cxl/η_rdma의 확정(실측 또는 문헌)이다.
- **결정 관련 진술 (2): C1 대 C2.** 선택 질문은 control plane 책임(중앙 직렬화 vs 분산 락)이다. QA1~QA3에서는 구분되지 않고(차이 0.005% 이하) 별 차이는 QA4에서만 나온다: C1 ★★★ 대 C2 ★★, 합계 6 대 5. 이 차이는 M2 경계(0.5 MM) 근처(0.461 대 0.509)이고 변형 24가지 중 19가지에서 동점이 된다. **제안 우선순위(proposal)** 기준 선택은 **C1**이나 **약한 선택**이다. 그 밖의 차이는 별점 밖에 있다: C1은 서버 SPOF, C2는 락 고착과 scan 비용(S x N)이라는 서로 다른 장애·확장 특성이며 정상 프로토콜의 정확성은 2노드 전수 모델 검사에서 둘 다 문제가 없었다. C1·C2의 QA1~QA3 격차 대 Baseline은 데이터 plane 상수에서 오며 일관성 구조 선택으로 줄일 수 없다.
- **이득이 존재하는 조건 / 존재하지 않는 조건.** goodput이 95% CI 밖으로 좋아진 쌍은 **0쌍**이다(N_win = 0 < 3). 'win' 4쌍은 모두 지연 등급 판정이며, 이득의 단서는 `d4_agent_multiturn`(8턴 에이전트, History KV 재사용)의 H100 한 쌍(같은 load에서 TTFT P99 3,414 -> 698 ms; goodput x1.66이나 Baseline seed 일부 붕괴로 CV 83%, 판정 tie)뿐이며 같은 시나리오가 B200에서는 x0.52로 손해다. Common CB-1/2의 H100 'win'은 own-peak 지연 등급 판정이며 같은 load에서는 후보가 느리다. 이득이 없는 조건: 링크 압박이 큰 모든 Common 쌍(특히 B200), 장애 시 C1(노드 손실)과 C2(as-published). 압박이 없고(bg 0) η_cxl >= 0.70 근처의 가정이면 QA1이 Baseline에 근접한다(민감도, main 아님).
- **다음 단계(사용자 결정 필요).** (1) **η_cxl, η_rdma, background 부하**를 실측 또는 문헌으로 확정한다(현재 결론의 핵심 가정). (2) 풀의 이득이 있다고 기대하는 prefix 공유·reuse 시나리오를 늘린다(현재 1개; 후보 구조 변경이 아니라 시나리오 추가, 실패한 것도 유지). (3) 보완 설계 W4(partial read, 청크 publish, 하이브리드 경로)를 새 iteration으로 사전 등록해 구현·측정한다(P class). (4) QA4를 Iteration 2 이후 소스에서 재측정하고 가능하면 실제 vLLM 통합에서 측정한다. (5) `qa_priority.json`(proposal)과 Scalability QA 추가 여부를 확정한다. (6) 정확성: N >= 3 노드 검증은 탐색 상한 때문에 미완이며 stale slot-body 가정의 논문 확인이 필요하다.
- **선택 질문과 별점 차이의 위치(재확인).** DP4의 선택 질문은 C1 대 C2이며, C1-대-C2 별 차이는 **QA4에서만** 나오고 0.5 MM 경계 근처이며, QA1~QA3의 Baseline 격차는 **data plane 상수**가 정하고 coherence 구조가 정하지 않는다.

---
