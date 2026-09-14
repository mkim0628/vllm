# DP1 배치 구조 Trade-off 프로토타입

[`dp1-heterogeneous-memory-data-placement.md`](dp1-heterogeneous-memory-data-placement.md)의
두 후보 구조를 정량 비교한다.

- **C1 memory-centric** — 메모리 상태가 배치 후보를 형성
- **C2 data-centric** — 데이터 특성이 후보를 형성하고, 메모리 상태가 그 안에서 선택

| 문서 | 내용 |
|---|---|
| [`dp1-prototype-spec.md`](dp1-prototype-spec.md) | **무엇을 어떻게 재는가** — 목적함수, 시나리오 13개, sweep, QA 4개 측정 방법 |
| [`dp1-prototype-results.md`](dp1-prototype-results.md) | **측정 결과** — 수치, §8 가정과의 대조, 유효 범위 |
| [`results/dp1_results.json`](results/dp1_results.json) | 원자료 (커밋되어 있음) |

## 이것이 아닌 것

**후보를 선정하지 않는다.** 설계 문서 §9의 선정은 검증되지 않은 가설로 취급하며,
산출물은 Trade-off 곡면이다. 어느 후보를 채택할지는 명시된 유효 범위를 근거로
**사람이 판단한다.**

**vLLM 통합이 아니다.** GPU가 없고 `vllm.v1.kv_offload.base`가 module scope에서
torch를 import하므로, offloading 어휘를 import하지 않고 미러링했다(`vllm_shim.py`).
실제인 것은 **형태**다: `PlacementPolicy`가 `CachePolicy`의 계약 스타일을 따르고,
tier 분류가 upstream의 `Medium`으로 되돌아 매핑된다(`UPSTREAM_MEDIUM`).

## 목적함수가 무엇을 재는지 먼저 알 것

`J`는 **총 메모리 점유 시간(초)** 이고, 문서 §7의 4개 QA 중 **Performance
Efficiency 한 칸**에 대응한다. 그것도 GPU occupancy·에너지 항이 없어 부분적이다.

**`J`만 보고 판단하면 질문의 1/4에 답한 것이다.** 나머지 3개 QA는 종류가 다른
증거로 별도 산출한다 — 자세한 내용은 [명세 문서](dp1-prototype-spec.md) §1, §3.

| §7 QA | 증거 종류 | 어디서 |
|---|---|---|
| Performance Efficiency | 측정 (`J`) | `--all` |
| Functional Correctness | 측정 (오차 전달 함수) | `--quality` |
| Maintainability | **대리 지표** (소스 카운트) | `--quality` |
| Flexibility | **실험** (새 tier 투입) | `--quality` |

## 실행

stdlib만 쓴다. torch·numpy·GPU 불필요. 스위트에 `pytest`만 필요하다.

```bash
python -m venv .venv-dp1
.venv-dp1/Scripts/python -m pip install pytest ruff   # POSIX에서는 Scripts/ -> bin/

# 테스트
.venv-dp1/Scripts/python -m pytest doc-architect/ -q

# 커밋된 모든 수치 재현 (20 paired seeds, 약 20분)
cd doc-architect
PYTHONPATH=. ../.venv-dp1/Scripts/python -m dp1_placement.run_eval --all

# QA 지표만
PYTHONPATH=. ../.venv-dp1/Scripts/python -m dp1_placement.run_eval --quality

# 반복 작업 중 한 시나리오만
PYTHONPATH=. ../.venv-dp1/Scripts/python -m dp1_placement.run_eval \
    --scenario hierarchy_pressure --seeds 4
```

## 구성

| 모듈 | 역할 |
|---|---|
| `vllm_shim.py` | vLLM offloading 어휘 미러 (torch 불필요) |
| `tiers.py` | tier 스펙, 런타임 상태, 정책에게 주는 읽기 전용 view |
| `request.py` | 데이터 객체, ground-truth 행동, 정책이 보는 요청 |
| `generators.py` | LLM 추론 구산자 + 실제 접근 이력 |
| `cost_model.py` | 목적함수. 물리 어휘만 |
| `profiler.py` | 행동 추정 + 오차 주입. C2만 사용 |
| `policy.py` | `PlacementPolicy` ABC와 두 후보가 **공유하는** 추정기 |
| `policies/` | Reference 정책 3개 + 후보 2개 |
| `engine.py` | 스텝 엔진: 도착, 접근, migration, 만료 |
| `metrics.py` | §8 지표. ground truth 기반 |
| `quality.py` | §7 QA 4개 중 목적함수가 못 재는 3개의 증거 |
| `scenarios.py` | 조건 정의. 각각 **고립시키는 변수**로 명명 |
| `experiments.py` | paired seed, 신뢰구간, 판정 규칙 |
| `report.py` | 표 출력 |
| `run_eval.py` | CLI |
| `configs/` | tier pool. 사내 스펙으로 교체 가능 |

## 메모리 pool 변경

### 코드 수정 불필요

- **tier 수치 재조정** — 용량, 대역폭, 내부 대역폭, 지연, write amplification,
  endurance, 비용. 공개 추정치를 실제 스펙 시트로 교체하는 경로다.
- **pool에 이미 있는 medium의 인스턴스 추가** — CXL 장치 2개, HBM stack group 2개.
  `name`만 유일하게 주면 된다.

### 코드 수정 필요 (의도적)

- **새 medium** (LPDDR, MRAM 등 6종에 없는 것). `vllm_shim.py`의 `Medium`에 멤버를
  추가하고, **동시에** `UPSTREAM_MEDIUM`에 vLLM의 `GPU`/`CPU`/`STORAGE` 중
  무엇으로 접히는지 항목을 넣어야 한다. 그 다음 pool과 enum이 일치하도록 강제하는
  `test_dp1_tiers.py::test_default_pool_covers_every_medium_in_the_design_doc`를
  확장한다.
- **새 연산** (미래 장치가 in-place로 돌릴 sort, join 등). `tiers.py`의
  `ComputeOp`에 멤버를 추가하고, 워크로드 생성기에 그 연산을 내는 class를
  준다 — 아무 객체도 수행하지 않는 연산은 무력하다.

enum은 실수가 아니다. medium을 자유 문자열로 두면 **오타가 조용히 별개의 tier
종류를 만들고**, 실제 `SecondaryTierManager`에 연결할 때 KV event bus에 publish할
upstream medium이 없어 터진다. 매핑을 미리 요구하는 것이 `vllm_shim`을 실제
미러로 유지하는 방법이다.

compute-capable tier는 `internal_bw_bytes_per_s`를 반드시 선언해야 하고, 없으면
loader가 거부한다. 외부 속도로 기본값을 두면 memory-side compute가 host link
속도로 도는 것으로 조용히 모델링되어 **그 capability가 존재하는 이유가 사라진다.**

## 문서가 이미 가정한 결론을 확인해주지 않게 하는 장치

설계 문서는 측정 전에 C2를 선정했다. 그래서 가장 큰 위험은 시뮬레이터가 그 선정을
구조적으로 재생산하는 것 — 또는 그러지 말라는 지시를 받고 반대를 재생산하는 것이다.
여섯 가지 장치가 있다.

**목적함수는 정책의 존재를 모른다.** `cost_model.py`는 `tiers`만 import하고,
`test_dp1_objective_neutrality`가 AST로 강제한다. hotness band를 읽을 수 있는
채점자는 한쪽 후보의 목적함수를 채점하는 것이다.

**후보가 존재하기 전에 작성됐다.** 아직 쓰지 않은 정책 쪽으로 목적함수를
튜닝할 수 없다.

**산술은 공유된다.** 두 후보가 같은 `PlacementEstimator`로 tier를 저울에 올린다.
각자 다른 점수 함수를 주면 비교가 "누가 heuristic을 더 잘 썼는지"를 잰다. 다른
것은 **입력과 시간 지평**뿐이다 — 지금 1회 접근 vs 생애 전체.

**미래도 현재도 볼 수 없다.** 이용률은 **완료된** step만 평균한 load에서 복원한다.
`trace_aware`가 의도적으로 이 규칙을 깨지만 그래서 후보가 아니라 참조다 — 객체별
greedy이므로 하한도 아니고, 그래서 정규화는 As-Is 기준선을 쓴다.

**두 후보는 한 커밋에 작성됐다.** 나중에 쓴 쪽이 더 잘 만들어지지 않게. reactivity,
migration 예산, endurance 한계, committed-demand 예약이 공유 상수다.

**한쪽이 압승하면 스위트가 실패한다.** `test_no_candidate_wins_decisively_everywhere`.
동점 없이 한쪽이 전 구간을 이기면 시뮬레이터가 편향됐거나 sweep 범위가 crossover를
담지 못한다는 뜻이다 — 발견이 아니라 실험의 결함이다.

## 알려진 한계

**GPU occupancy·에너지 항이 없다.** 목적함수는 메모리 시간이다. 메모리 안에서
연산을 돌리면 GPU 연산 유닛이 비는데 그 이득이 여기서는 보이지 않으므로,
**compute-capable memory에 관한 모든 수치는 이득의 하한**이다.

**`trace_aware`는 최적해가 아니다.** 객체별 greedy이고 미래 경합을 모른다. 한
조건에서는 아예 진다. 숨기지 않고 문서화했다.

**tier 스펙은 공개 자료 기반 대표값**이고 벤더 데이터가 아니다. 모든 값에
`provenance` 문자열이 붙어 있다.

**Maintainability는 대리 지표다.** 소스에서 센 수치는 변경 비용과 상관이 있지만
그것을 측정하지 않는다. 논증의 방향으로 읽어야 한다.

**결과는 규모에 의존한다.** `scenarios.py`의 인구 규모와 런 길이가 결과의 일부다.
1/10 규모에서 헤드라인 수치 하나가 유의하게 달라졌고, 그래서
`test_dp1_findings.py`의 고정 테스트는 빠른 설정이 아니라 **보고 설정**에서 돈다.

**C2 구현을 세 번 바꿨다.** 매번 C2가 지는 것을 본 뒤였다. 각 버전의 동작·수치와
매번 적용한 기준을 [결과 문서 §7](dp1-prototype-results.md)에 공개했다.
