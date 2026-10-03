# DP2 Benchmark (DP2 맞춤형)

> 상태: **TBD**
>
> 최종 결과 = **Common Benchmark (`../common-benchmark.md`) + 이 문서의 DP2-specific benchmark**.
>
> 공통 시나리오 CB-1~CB-3은 `../common-benchmark.md` 2.1장에 정의되어 있으므로 여기에 다시 정의하지 않는다. 이 문서에는 **DP2 전용 시나리오만** 둔다.

## 이 문서가 최종적으로 포함해야 할 내용

1. **Common Benchmark 실현**: CB-1~3을 이 DP 구조에서 어떻게 실현하는지(압박 방식·비율 포함), serving framework / topology, 고정 파라미터 구현 방식, sweep grid, 반복 횟수 (`../common-benchmark.md` 8장 요건).
2. **Common Reference Baseline**: As-Is 구조 정의, 구현 위치/revision, T_ref.
3. **사용 System profile**: `../system-specs.md`의 SYS-id 선택과 이유 (필요 시 새 SYS 프로파일 추가). 모든 결과에 SYS id + model + config revision 인용.
4. **DP2-specific benchmark**: 이 DP의 trade-off / failure mode를 드러내는 시나리오 집합. 각 시나리오의 존재 이유, 탐지하는 As-Is 실패 모드, 대상 metric (`../DP1/benchmark.md` 구조 참고). 시나리오는 코드 또는 데이터 파일을 단일 소스로 두고 표는 생성한다.
5. **Benchmark-fit 분류**: comparison-valid / infeasible / saturated (`../DP1/benchmark.md` 3장). baseline이 SLO를 못 맞추는 시나리오는 flag하며 제외하지 않는다.
6. **QA / diagnostic metrics**: 공통 QA1~QA4 + DP2 diagnostic. 예상 후보: Prefill/Decode node utilization, GPU idle ratio, inter-node KV transfer utilization, decision latency, prefill latency, queue delay (`qa-evaluation-criteria.md` 6장 DP2 예시).

## 현재 내용

TBD.
