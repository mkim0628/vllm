---
date: 2026-10-04
dp: DP4
candidates: [C1, C2]
status: preregistered (측정 전 작성, 이후 수정 금지; 변경 시 아래 '변경 이력'에만 추가)
evidence: [B+C] (simulator proxy 구현 + 가정 기반 추정)
---

# DP4 QA4 Modifiability 사전 등록

QA4를 **세 sub-metric**으로 본다(H21): (M1) 변경 module 수, (M2) 개발 공수(man-month), (M3) code-agent 토큰 **비용(달러)**. 이 문서는 측정 전에 작성했다.

**DP1과 같은 공식·상수·별 경계·집계(시나리오 평균)를 쓴다**([`../DP1/qa4-preregistration.md`](../DP1/qa4-preregistration.md) §4, §5, v2). DP1 v2의 "최악값 → 평균" 집계는 소유자 결정이며, 그 사후 변경을 피하기 위해 DP4는 **처음부터 평균 집계**를 쓴다(DP1 결과와 직접 비교 가능). 기존 정의(`qa-evaluation-criteria.md` §7: ★★★ ≤ 2 / ★★ 3~5 / ★ ≥ 6)는 M1에 그대로 쓰고 M2, M3와 집계는 **임시 정의**(H8)다.

## 1. 변경 시나리오 (각 시나리오를 C1, C2 각각에 시뮬레이터 코드로 실제 구현한다)

| ID | 시나리오 | 구체 spec | "동작한다"의 합격 기준 (smoke) |
|---|---|---|---|
| S1 | **신규 하드웨어 capability** | CXL 3.x `CoherentRegion`: 64 KiB의 하드웨어 일관 영역에서 cross-node CAS를 쓸 수 있다. 메타데이터 중 동기화 객체(C1: RPC 슬롯 flag, C2: 전역 락 배열)를 이 영역으로 옮긴다 | `d4_hot_prefix_fanout`에서 동기화 연산의 CAS 경로 호출 ≥ 1건이고, C2는 락 매니저의 grant 연산이 0건, C1은 슬롯 flush 호출이 0건 |
| S2 | **신규 객체 class** | 가변 길이 `COMP_KV` 객체(길이 1~16 블록 분량, `format_version` 필드 포함)를 풀에 publish/lookup한다 | 새 class 객체가 trace에서 생성되어 publish되고 lookup이 길이·버전을 반환 |
| S3 | **정책 교체** | 퇴출 정책을 LRU에서 "빈도×재구성비용" 점수 기반으로 교체한다(생성자 주입) | 교체한 구현의 호출 횟수 > 0이고 기존 구현 호출 0 (spy), 퇴출된 블록 집합이 변화 |
| S4 | **신규 topology 요소** | 풀 2개(샤딩): 객체 ID에 `pool_id`를 포함하고 두 풀에 걸쳐 allocate/lookup한다 | 객체가 두 풀에 분산 저장되고 lookup이 올바른 풀을 반환 |

시나리오 선택 의존성: 4개를 사전에 고정했고 한 후보에 유리하게 추가·삭제하지 않는다(H4). S1은 C2의 락 매니저, C1의 RPC 슬롯 protocol에 각각 닿으므로 후보 간 비대칭이 있을 수 있다 — 이는 의도된 신호다.

## 2. Module 정의 (설계 문서 component 기준)

세는 단위는 **파일이 아니라 설계 component**다. 한 component에서 코드·표·config를 1줄이라도 바꾸면 변경 module 1개다.

| 구분 | Component |
|---|---|
| 공통 | GPU↔CXL Copy/DMA handler, KV block object format (불변 블록, prefix 체인 해시), Client library API, Publish/Visibility protocol (publish 순서, flush/invalidate 규칙), Failure/Recovery handler |
| C1 | CXL-RPC channel (요청·응답 슬롯, status flag), Metadata server (prefix index, allocator, refcount, LRU/퇴출) |
| C2 | Shared metadata layout (offset 주소, 고정 크기 해시 테이블, cacheline 정렬), Two-tier lock + lock manager, Shared allocator (전역 chunk + 노드별 heap), Refcount/LRU in shared memory, Cacheline flush layer |

규칙(DP1과 동일):
- **Shared module**은 두 후보 모두 바꿔야 하는 component이며 각 후보의 module 수에 모두 포함한다(후보를 단독 도입한다고 가정). shared 수를 따로 표시한다.
- **Harness는 module이 아니다**: workload 생성기, 접근 비용 physics, 테스트. LOC에도 넣지 않고 별도로 기록만 한다.
- major interface 변경(기존 필드·protocol의 의미 변경)이 필요하면 module 수와 무관하게 M1 = ★. 필드·enum **추가**는 interface 변경이 아니다(append-only).

## 3. 측정 프로토콜 (DP1과 동일)

1. pristine 복사본을 기준으로 시나리오별 **작동하는 최소 변경**을 후보마다 구현한다(C1 전용 / C2 전용 / shared로 hunk 분리).
2. 합격 기준을 실제 실행으로 확인한다. 통과하지 못한 변경은 수정해 다시 확인하며 통과 전 수치는 쓰지 않는다. 기존 test 통과 확인.
3. `diff -u` 기준 hunk별 **추가된 비공백·비주석 줄 수(LOC)**를 센다(삭제 줄은 `loc_deleted`로만 기록). 각 hunk를 component에 귀속한다.
4. touched component의 **현재 크기(LOC)**를 pristine 소스에서 AST 줄 수로 잰다.
5. 측정값은 `results/data/qa4_measured_counts.json`에 기록하고, `tools/qa4_modifiability.py`(DP 인자로 일반화)가 공식으로 `qa4_modifiability.json`을 만든다.

## 4. 공식·상수·별 경계
DP1 `qa4-preregistration.md` §4(M2, M3 공식과 ASSUMED 상수: c_mod 3일, k_real 5, P 40 LOC/일, f_ovh 2.0, tpl 12, C0 25k, a_read 1.5, n0 10, n_m 5, n_iter 2, o_turn 300, 가격 T1 15/1.5/75, T2 3/0.3/15, mult 0.6/1.0)와 §5(M1 ≤2/≤5, M2 ≤0.5/≤1.0 MM, M3 ≤$3/≤$10 at T1)를 **그대로** 쓴다. **sub-metric 별 = 4개 시나리오 평균값에 위 threshold 적용**, QA4 별 = 세 sub-star의 중앙값, 세 값을 모두 병기한다.

## 5. 민감도·한계
- 상수 low/high 조합에서 별점이 바뀌는지 보고하고, 경계 근처 값은 그렇게 적는다.
- 한계: simulator proxy 구현이며 실제 시스템 통합이 아님, 공수·가격·배율은 가정, 실제 에이전트 세션 측정이 아님, Evidence [B+C] 이하. component 귀속은 판단이다.

## 변경 이력
- 2026-10-04 최초 작성(사전 등록).
