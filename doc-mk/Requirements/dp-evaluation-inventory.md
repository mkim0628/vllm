# DP별 평가 정의와 환경 대장 (통합 단계 입력)

> 작성: 2026-10-09. 목적: 품질 요구사항의 정량 임계값을 통일하기 전에, 각 DP가 **무엇을 어떤 환경에서 어떤 기준으로** 정의했는지를 한곳에 모은다. **평가 결과 값은 싣지 않는다**(사용자 지시로 치워 둠). 기준값은 각 DP 문서의 **현재 정의를 옮겨 적은 것**이며 채택한 것이 아니다. DP 번호는 최종 번호.

## 1. 환경과 Baseline의 차이

| 항목 | DP1 (migration) | DP2 (P/D 실행 위치) | DP3 (KV eviction/reuse) | DP4 (요청 조율) |
|---|---|---|---|---|
| 평가 방식 | 순수 시뮬레이션 [B+C] | 순수 시뮬레이션 [B+C] (이산 사건 simulator 신규) | **없음**(TBD) | **Baseline 실측 + 시뮬레이터 연동**을 계획([A]+[C]), 모든 값은 예상치(미실행) |
| 평가 시스템 | SYS-H100, SYS-B200 통합. **8 GPU 1노드** | SYS-H100, SYS-B200 통합. 8 GPU 노드를 P/D로 2~6대(확장 sweep 최대 64) | 미정 | 보유 H100 SXM x8 **2노드(16 GPU)** |
| 노드 간 링크 | 해당 없음(단일 노드, host link PCIe 5.0 x16) | **RDMA 50 GB/s (ASSUMED)**, sweep 12.5~400 | 해당 없음 | 400 Gb/s ≈ 50 GB/s **가정**, 미확인 |
| 사용자 확인 환경(GC-9) | — | **서버 2대가 PCIe 64 GB/s** → DP2와 값이 다름 | — | → DP4 가정과도 다름 |
| 모델/SLO | Llama-3.1-70B BF16, 공통 benchmark(입력 8K, 출력 256), TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms | 동일 | (설계에 SLO 기호만 있음) | 동일 |
| **Baseline** | **Baseline-static**: 공통 initial placement 후 migration 없음(As-Is proxy) | **Baseline-PD-fixed**: Prefill은 항상 P, Decode는 항상 D, KV Tier 미고려 | **B0**(전량 HBM, Accuracy 상한) / **B1**(Demote-only = DP1 정책 포함, 진짜 기준선) | 정책 미적용 기본 라우팅(상태·캐시 비인지) |
| Baseline의 SLO 충족 | 시나리오에 따라 불가(infeasible) 존재 | 평가 문서상 일부 SLO를 못 지키는 상태에서 비교 | B0는 long-context에서 실행 불가일 수 있음 | 가정값으로 둠 |
| 시나리오 | Common 3 + Stress 23 + Dynamic 6 | Common 3 + Stress 12 + Dynamic 4 + Scalability + QA4 | 미정(sweep 축만 정의) | W1~W5(공통, 캐시 재사용, 긴 입력 P/D, 메모리 압박, 서버 증설) + S1~S6 |
| 통계 | seed 5, 95% CI | seed 5(확장 부하는 일부 1~2) | 동일 seed 쌍 반복, 신뢰구간이 0을 지나면 차이 없음 | Runs ≥ 5, CV 가정 |

## 2. QA 정의의 차이

| ISO 특성 | DP1 | DP2 | DP3 | DP4 |
|---|---|---|---|---|
| Capacity (QA1) | Max SLO Goodput, Baseline 대비 | 동일 지표, Baseline 대비 | M-C1 SLO-제약 Goodput(Accuracy와 쌍), **B1 대비** | Max SLO Goodput, Baseline 대비 |
| Time behavior (QA2) | TTFT, TPOT **둘 다** 분리(P50/P95/P99) | TTFT, TPOT 분리 | TTFT(Drop 접근/미접근 분리), 결정 latency | **TTFT 중심**(+결정 경로 추가 시간, TPOT은 악화 여부) |
| Resource utilization (QA3) | **HBM 사용량**(낮을수록 좋음) | **U_useful: P/D 풀 GPU 사용률**(높을수록 좋음) | HBM KV footprint(DP1과 같은 정의) | **제외**(Throughput과 같은 원인) |
| Modifiability (QA4) | 변경 module, 공수(MM), 에이전트 비용($), 4개 시나리오 **평균**, 별 = 세 sub-star **중앙값** | DP1과 **같은 공식** | **없음** | module, 공수(man-day), 비용($), S1~S6 **가중**, **우선순위 규칙**(비용 > 공수 > module) |
| Scalability | 없음 | **QA5 신설**: η(N=32) | 없음(sweep 축만) | SE(N), N0 = 2, N_max = 16 |
| Functional correctness | 제약(bit-exact) | 제약(출력 불변) | **QA**(Task accuracy F1, FNR, 일치율), GC-7 예외 | 제약(정확도 불변) |

## 3. 별점·임계값 기준의 출처 차이 (현재 정의)

| DP | 별 기준의 종류 | 기원 | 정의 시점 |
|---|---|---|---|
| DP1 | **Baseline 대비 효과 크기** 경계(QA1 0.97/1.30, QA2 0.95/1.25, QA3 절감 0.95/1.25). 공통 절대 기준은 참고 병기 | 소유자 판단 + 잡음 측정(하한) | **결과를 본 뒤**(`defined_after_first_look`) |
| DP2 | **DP1 값을 그대로 복사** + QA5 η 0.70/0.90(제안값) | DP1 | 후보 실행 전 사전 등록(값의 기원은 DP1의 사후 값). QA2/QA3 iso-load 집계는 결과 본 뒤 |
| DP3 | **없음** | — | — |
| DP4 | **공통 QA 문서의 절대 경계**(QA1 0.90/1.10 T_ref, QA2 SLO, QA4 module) + Q3 비용·공수 경계(DP4 사전 등록 가정) + Q4 SE 90/70% | 공통 문서, 내부 환산, HPC 관행 | 평가 전 등록. 슬라이드가 **공개 요구사항 출처를 못 찾은 경계를 가정으로 표기** |

공통 문서(`qa-evaluation-criteria.md`)의 기준: QA1 0.90/1.10 x T_ref, QA2 절대 SLO(TTFT, TPOT), QA3 useful utilization 65/85%, QA4 module 수. DP1이 이 기준을 DP 전용으로 대체한 상태.

## 4. 통합 단계에서 풀어야 할 불일치

1. **상대(Baseline 대비) 기준과 절대(SLO) 기준의 혼재**: DP1·DP2는 상대, DP4는 공통 절대, DP3는 없음.
2. **Baseline 정의가 DP마다 달라** "Baseline 대비 배수"가 다른 개선을 뜻함(특히 DP3의 B1은 DP1 정책을 포함).
3. **QA3 정의**: `memo-qa3-resource-utilization.md` 참조.
4. **Modifiability 집계 규칙**(평균+중앙값 / 가중+우선순위)과 시나리오 구성.
5. **Scalability 정의**(DP2 η, DP4 SE)와 N0, N_max.
6. **Latency 정의**(TTFT·TPOT 분리 대 TTFT 중심).
7. **링크 가정**(DP2 50 GB/s ASSUMED, DP4 50 GB/s 가정, 사용자 환경 PCIe 64 GB/s).
8. **평가 방식**(순수 시뮬레이션 대 실측 + 시뮬레이터)과 **Evidence 수준 표기**.
9. **결과를 본 뒤 정의된 경계**와 사전 등록 경계의 구분.
10. **DP1 평가의 이동 가능 범위 가정 오류**(`memo-reevaluation.md`)로 DP1 결과를 기준으로 삼기 어려움.
