# DP3 Benchmark (DP3 맞춤형)

> 상태: **TBD**
>
> 최종 결과 = **Common Benchmark (`../common-benchmark.md`) + 이 문서의 DP3-specific benchmark**.

## 이 문서가 최종적으로 포함해야 할 내용

1. **Common Benchmark 실현**: serving framework / topology, 고정 파라미터 구현 방식, sweep grid, 반복 횟수 (`../common-benchmark.md` 8장 요건).
2. **Common Reference Baseline**: As-Is 구조 정의, 구현 위치/revision, T_ref.
3. **사용 System profile**: `../system-specs.md`의 SYS-id 선택과 이유 (필요 시 새 SYS 프로파일 추가). 모든 결과에 SYS id + model + config revision 인용.
4. **DP3-specific benchmark**: 이 DP의 trade-off / failure mode를 드러내는 시나리오 집합. 각 시나리오의 존재 이유, 탐지하는 As-Is 실패 모드, 대상 metric (`../DP1/benchmark.md` 구조 참고). 시나리오는 코드 또는 데이터 파일을 단일 소스로 두고 표는 생성한다.
5. **Benchmark-fit 분류**: comparison-valid / infeasible / saturated (`../DP1/benchmark.md` 3장). baseline이 SLO를 못 맞추는 시나리오는 flag하며 제외하지 않는다.
6. **QA / diagnostic metrics**: 공통 QA1~QA4 + DP3 diagnostic. 예상 후보: KV restore latency, tool-resume latency, eviction 정확도/churn, memory-pool utilization, migration bytes (DP별 정의 필요).

## 현재 내용

TBD.
