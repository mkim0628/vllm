# 인계: DP 구조 설계 규칙 정립 + DP1/DP2 문서·프로토타입·덱

- 세션: `2026-09-06-dp-structure-design` · 기간 `2026-09-02T17:19Z ~ 2026-09-06T02:46Z`
- 브랜치: `claude/dp-structure-design-rules-hoyf13` @ `32a6fcf`
- 원문: `prompts.md` (사용자 발화 38건) · `dialogue.md` (응답 81건) · `stats.md` · `transcript.jsonl.gz`

> 이 문서가 **현재 참인 것**이다. 원문에는 세션 중간에 철회된 주장이 그대로 남아 있으므로
> 이것을 먼저 읽고, 원문은 근거를 캘 때만 연다. (5절 정정 이력을 반드시 볼 것)

---

## 1. 한 문단 요약

vLLM 위에서 **이기종 메모리 설계 연구**를 하며 DP(설계포인트) 문서를 쓰고 있다.
먼저 사용자의 DP 구조 설계 규칙을 `dp-design` 스킬로 고정했고(9 Phase + Gate A~I),
그 규칙으로 DP2(연산가능 메모리)와 DP1(메모리 배치 결정 기준)을 작성했다.
DP1은 본문 12절 + 부록 A~D, 두 후보의 동작하는 프로토타입(테스트 35건 통과),
PPT 덱 3종까지 나와 있다. 현재 걸려 있는 지점은 **DP1 배경 §1.3** 하나다 —
"오늘은 계층이 깨끗하다"고 써 둔 문장을 **오늘 이미 존재하는 구조적 결함** 서술로
바꿔야 하고, 근거 조사는 이미 끝났다(2절).

---

## 2. 확정 사실

### 2.1 vLLM 코드 사실 (재조사 불필요)

| 사실 | 근거 | 검증 |
|---|---|---|
| `allocate_slots()`는 위치 인자가 없고 인자가 이미 9개다 | `vllm/v1/core/kv_cache_manager.py` | 확인 |
| `BlockPool.get_new_blocks(n)` / `get_num_free_blocks() -> int` — tier 개념 없음 | `vllm/v1/core/block_pool.py` | 확인 |
| `KVCacheBlock`은 필드 6개, 위치 정보 없음 (`block_id: int`) | 같은 파일 | 확인 |
| `Scheduler.schedule()` 595줄 | `vllm/v1/core/sched/scheduler.py` | 확인 |
| 스케줄러의 커넥터는 **단일 객체** `self.connector` (팩토리 생성). 각 메모리를 명시 호출하지 않는다 | `KVConnectorFactory.create_connector()` | 확인 |
| **[핵심]** 스케줄러가 `hasattr(self.connector, "bind_gpu_block_pool")`로 덕타이핑해 `kv_cache_manager.block_pool`을 통째로 넘긴다 | `vllm/v1/core/sched/scheduler.py:243-246` | 확인 |
| **[핵심]** `bind_gpu_block_pool`은 `KVConnector` ABC에 **없다** (grep 0건). 구현체에만 있다 (`vllm/v1/simple_kv_offload/manager.py:206`, `simple_cpu_offload_connector.py:169`) | `.../kv_connector/v1/base.py` grep | 확인 |
| **[핵심]** `KVCacheBlocks` docstring은 "hide KVCacheManager's internal data structure from the Scheduler"라고 선언하는데, 정작 스케줄러가 `block_pool`을 그대로 건네준다 | docstring vs 위 코드 | 확인 |
| `allocate_slots(..., num_external_computed_tokens)` — KVCacheManager가 이미 "외부 메모리 존재"를 안다 | 시그니처 | 확인 |
| `KVConnector` 인터페이스는 `num_external_tokens` / `blocks`(GPU)로 **GPU↔외부 이분법** 전제. "tier i → tier j"를 표현 못 함 | ABC 시그니처 | 확인 |
| `KVCacheSpec` 서브클래스 11개, `Platform` 82메서드×6구현, `AttentionBackendEnum` 25개, 기본 CUDA graph capture size 51개 | grep 집계 | 확인 |
| `CacheConfig.DEFAULT_BLOCK_SIZE = 16`, `SchedulerConfig.DEFAULT_MAX_NUM_SEQS = 128` | config | 확인 |

> **위 3개 [핵심] 항목의 의미**: 구조적 결함은 "6-tier로 확장하면 생길 일"이 아니라
> **메모리 계층이 1개에서 2개(GPU + CPU offload)로 늘어난 그 지점에서 이미 생겼다.**
> 계층이 6개가 되면 같은 방식으로 5번 더 반복된다. 이것이 YAGNI 반박을 닫는 근거다.

### 2.2 자체 계산 (근거 있는 수치)

| 사실 | 계산식 | 검증 |
|---|---|---|
| 70B GQA KV = **320 KB/token** | 80층 × 8 KV헤드 × 128 dim × 2(K,V) × 2B | 계산 |
| 128K 컨텍스트 = 요청당 **40 GB** | 320KB × 128K | 계산 |
| 70B 가중치는 **140 GB로 고정** (KV만 요청수에 비례) | 70B × 2B | 계산 |
| 6-tier 스프레드: 대역폭 **533배**, 용량 **256배**, 지연 **240배** | 아래 tier 표 | 계산 |

6-tier 모델 (문서·프로토타입 공통, `DEFAULT_TIERS`):

| tier | 대역폭 GB/s | 용량 |
|---|---|---|
| HBM | 3200 | 40 GB |
| Custom HBM | 1600 | 80 GB |
| DRAM | 200 | 320 GB |
| CXL | 64 | 640 GB |
| HBF | 16 | 2.5 TB |
| SSD | 6 | 10 TB |

### 2.3 프로토타입이 문서로 되먹인 발견 4개

| 발견 | 수치 | 검증 |
|---|---|---|
| 오분류가 배치를 **역전**시킨다 (C2) | separation ratio 0.43 < 1.0 | 테스트 |
| C2도 tier 상태를 읽지만 **아래 방향으로만** 작동한다 | `object_indexed.py` 동작 | 테스트 |
| 예약 카운터는 완화책이 아니라 **정합성 요구**다 — 없으면 **두 후보 모두** overcommit 72 | `reserve_within_step=False` 실행 | 테스트 |
| 블록당 비용모델에서 **크기는 상쇄된다**(무시되는 게 아니라) | value/price 양쪽에 size가 들어감 | 테스트 |
| C2 steelman: 유보 없이 2.11 ≈ C1 2.06 / 유보 있으면 8.40 이지만 homogeneous 이용률 1.000→0.500 | `--steelman` 실행 | 테스트 |

---

## 3. 확정된 결정

- **결정 A**: DP 설계 규칙은 스킬 **하나**(`dp-design`)로 통합. 배경/설계를 분리하지 않았다.
  - 근거: Phase 0의 QA가 Phase 5 평가축을 그대로 규정하므로 사슬이 끊기면 안 된다.
  - 포기한 것: 배경만 따로 재사용하는 편의.

- **결정 B**: DP1 결정 변수 = **"배치 정책이 무엇에 매달리는가"** (자원 축 vs 객체 축).
  - C1 = Tier-Indexed Placement, C2 = Object-Indexed Placement.
  - 근거: 상위호환 논란을 이 축으로 잘랐을 때만 양립 불가가 성립한다(3중 논증: 불변식 충돌 / 결정 단위 충돌 / 지배 반박).
  - 포기한 것: "누가 배치를 결정하는가"라는 초안 축(주체 축은 두 후보를 갈라내지 못했다).

- **결정 C**: DP1 최종 구조 = **C1 + 컨텍스트 길이 보강**.
  - 근거: QA 가중치상 정보비용 스케일 차이(C1은 T=6, C2는 N=요청수)가 배치품질 격차보다 크다.
  - 포기한 것: 객체별 등급 구분 능력(QA1 미해소로 남김 → 잔여 R2).
  - 뒤집히는 조건: PoC에서 오분류율과 대역폭 매칭 격차가 사전 고정한 임계를 넘을 때(§11).
  - **혼합 판정**: 이것은 하이브리드가 아니라 "C1 + 보강"이다 — 단일 진실 원천이 여전히 하나(tier 상태)다.

- **결정 D**: DP2 결정 변수 = **"연산 능력의 단일 진실 원천을 누가 소유하는가"**.
  - 근거: 초안 후보들이 지배 테스트에서 탈락 → 축을 다시 잘랐다.

- **결정 E**: 배경(§1)은 **응용에서 시작하는 탑다운**으로 쓴다.
  - AI 메모리 월 → KV 캐시 증가 → 차세대 메모리 → 이기종 혼재 → 런타임 배치 필요 → 현재 스케줄러의 명시 배치 → 계층 위반 → 배치 결정 기준 필요.
  - **계층 문제 해결 자체는 QA 축이 아니다** — 두 후보 모두 그것을 하므로 공통 문턱이고, §10 검증에서 판정한다.

---

## 4. 기각한 대안

| 기각한 안 | 기각 이유 | 되살릴 조건 |
|---|---|---|
| DP1 축을 "배치 결정의 주체"로 잡기 | 두 후보가 같은 주체를 가질 수 있어 배타성이 안 나온다 | — |
| C1+C2 하이브리드를 세 번째 후보로 | 단일 진실 원천이 여전히 하나 → 후보가 아니라 "C1 + 보강" | 결정 단위가 실제로 분리되면 |
| C2에 런타임 재분류(실행 후 관측 기반)를 포함 | 결정 변수가 달라진다 → 별개 DP | 잔여 R1 → **DP3(재배치 트리거)** 로 이관 |
| C2가 "크기를 안 본다"고 서술하기 | 사용자 지적: steelman 위반. 비용모델에서 크기는 **상쇄**되지 별도로 무시되지 않는다 | — |
| C2가 "tier 상태를 전혀 안 본다"고 가정하기 | 무리한 가정. 실제로는 읽되 아래 방향으로만 작동한다 | — |
| 원래 DP2 후보 2안(초안) | 지배 테스트 탈락 — 한쪽이 명확히 우월 | — |
| 배경에서 후보 1·2 구체 설계 도면 노출 | 배경은 As-Is만 그린다. 후보 도면은 §3 | — |
| DIP를 배경의 필수 프레이밍으로 삼기 | 사용자: "dip가 아니더라도 어떤 구조적 결함이 있다는 걸 말하고 싶은거야" | — |

---

## 5. 정정 이력 (누적 — 삭제하지 않는다)

사용자가 직접 틀렸다고 지적한 내 주장이다. **다시 쓰지 마라.**

- ~~"prefix cache hit 시 100명이 각자 자기 등급에 맞는 자리인지 묻는다"~~
  → **틀림.** hit에서는 **배치 결정 자체가 일어나지 않는다.** 두 후보 동작이 완전히 동일하다.
- ~~"C2의 계약은 capacity-blind다"~~
  → **과장.** C2도 tier 상태를 읽는다. 다만 **아래 방향으로만** 작동한다.
- ~~"C2는 위로 올릴 때 크기를 안 본다"~~ / ~~"크기 편향은 구조적 성질이다"~~
  → **틀림.** 그것은 순진한 `upgrade_if_free` 규칙(등급도 크기도 안 읽던)의 **구현 artifact**였다.
    steelman한 블록당 비용모델에서는 size가 value와 price 양쪽에 들어가 **상쇄**된다.
- ~~"스케줄러가 각 메모리를 명시적으로 호출한다"~~
  → **틀림.** `self.connector`는 단일 객체이고 스케줄러는 추상 인터페이스 메서드만 부른다.
- ~~"오늘 vLLM에서 DIP는 지켜져 있다"~~
  → **틀림.** 커넥터 바인딩 경로에 실제 위반이 있다(2.1의 [핵심] 3항목).
    최초 판단은 **핵심 할당 경로만 봤기 때문**이었다.
- ~~비용모델 1판(occupancy 항 ×100)~~ → 항이 지배해서 다른 항이 무의미해졌다.
- ~~비용모델 2판(demand ∝ prompt_len)~~ → value/price 비율이 상수가 되어 아무것도 구분 못 했다.
  → **3판(현재)**: 블록당 정규화. `cost = -(intensity × bw) + (PRICE_SCALE/capacity) × bw × scarcity + migration`

> **패턴 경고**: 이 사용자는 과장·미검증 주장을 정확히 잡아낸다.
> 확인하지 않은 것은 확인하지 않았다고 쓰고, 후보를 깎아내리는 서술은
> steelman 검사(6절)를 통과시킨 뒤에만 쓴다.

---

## 6. 용어 (세션 안에서 정의됨)

- **DP / 설계포인트**: 문제 → 쟁점 → 두 후보 → QA 별점 트레이드오프 → 검증 → 선택 → 잔여 인계의 단일 사슬 문서.
- **steelman 원칙**: 각 후보를 **최선의 형태**로 세운 뒤 비교한다. 후보를 고치면 사라지는 약점은 구조적 비용이 아니라 구현 artifact다. 고쳤더니 다른 축이 나빠지면 **그 교환이 진짜 트레이드오프**다.
  - 이래야 한다: "다 고려했는데도 **구조적으로** 이 축에서는 이럴 수밖에 없더라"
  - 이래선 안 된다: "이 후보는 X를 고려하지 않으므로 나쁘다"
- **양립 불가 3검사**: T1 병합 검사 / T2 지배(상위호환) 검사 / T3 별점 지배 검사.
- **유보 A**: step 안에서만 유효한 예약. **계산으로 나오는 값**, 정합성 요구, 오버커밋 방지.
- **유보 B**: 미래 여유분. **튜닝 파라미터**, 성능 요구, 관측 불가능한 도착 분포에 의존.
- **overcommit**: 같은 스텝에서 여러 결정이 각자 여유를 보고 잡아, 합계가 실제 용량을 넘는 것.
- **separation ratio**: 등급이 높은 객체가 실제로 빠른 tier에 놓였는지의 비율. 1.0 미만이면 역전.
- **덱 3종**: full(21장) / detail(10장) / comparison(5장).

---

## 7. 산출물 지도

| 경로 | 담고 있는 것 | 상태 |
|---|---|---|
| `.claude/skills/dp-design/` | DP 설계 규칙 스킬. SKILL.md(9 Phase, Gate A~I) + references 6 + template 1 | 완료 |
| `.claude/skills/session-handoff/` | 이 인계 스킬 | 신규 |
| `doc-mk/vllm-dp1-placement-decision-basis.md` | DP1 본문 12절 + 부록 A~D (65 KB) | **§1.3만 재작성 대기** |
| `doc-mk/vllm-dp2-compute-capable-memory.md` | DP2 전문 (30 KB) | 완료 |
| `doc-mk/prototype/dp1/` | 두 후보 구현 (`tier_indexed.py`, `object_indexed.py`, `model.py`, `policies.py`, `cases.py`, `harness.py`, `workload.py`) | 완료 |
| `doc-mk/prototype/tests/test_dp1_claims.py` | 주장 검증 테스트 35건 | **35/35 통과** |
| `doc-mk/prototype/TESTING.md` | 케이스표·정책표·발견·미모델링 | `--policies c1,c2-steelman` 예시가 오해 소지 |
| `doc-mk/ppt/vllm-dp1-full.pptx` (+`build-dp1-full-deck.js`) | 21장 | **5장 부제 갱신 대기** |
| `doc-mk/ppt/vllm-dp1-candidate-structure-detail.pptx` (+js) | 10장 | 새 배경 미정렬 |
| `doc-mk/ppt/vllm-dp1-dp2-candidate-comparison.pptx` (+js) | 5장 | 새 배경 미정렬 |

재현 명령:

```bash
# 테스트 (pytest는 시스템 python3에 없다. unittest로 돌린다)
cd doc-mk/prototype && python3 -m unittest discover -s . -q      # Ran 35 tests ... OK

# 실험
cd doc-mk/prototype
python3 -m dp1.cases                          # 케이스 카탈로그
python3 -m dp1.run_experiment --list
python3 -m dp1.run_experiment --steelman      # 두 후보의 최선 형태 비교

# 덱 재생성 (pptxgenjs가 프로젝트에 없어 NODE_PATH로 잡아 준다)
export NODE_PATH=<pptxgenjs가 설치된 node_modules 경로>
cd doc-mk/ppt && node build-dp1-full-deck.js
```

**환경 주의사항**
- `.claude/`는 upstream `.gitignore` 196행에 걸려 있다 → 스킬 커밋은 `git add -f`.
- 이 컨테이너의 LibreOffice는 **어떤 pptx도 못 연다**(최소 생성 파일도 동일 실패).
  그래서 덱 QA는 분석적으로 했다: 텍스트 맞춤 검사(한글 1.0em / 라틴 0.52em 글리프 폭)와
  바운딩박스 충돌 + 캔버스 이탈 검사 스크립트. 사내에서 실제로 열어 보면 더 좋다.
- 팔레트: INK `1F2933`, C1 `0B6E6E`(teal), C2 `B0503F`(terracotta), WARN `B7791F`, Arial.

---

## 8. 다음 한 수

**다음 한 수**: `doc-mk/vllm-dp1-placement-decision-basis.md` **§1.3**을 고쳐 쓴다.

- 지금 문장(70행 부근):
  > **DIP는 지켜져 있다 — 다만 지킨 것이 아니라 메모리가 하나여서 지킬 필요가 없었던 것에 가깝다.**
- 이것을 **오늘 이미 존재하는 구조적 결함** 서술로 교체한다. 근거는 2.1의 [핵심] 3항목:
  1. 스케줄러가 ABC에 없는 메서드를 `hasattr`로 찔러 부른다 (`scheduler.py:243-246`)
  2. `KVCacheBlocks`가 숨기겠다고 선언한 `block_pool`을 스케줄러가 그대로 넘긴다
  3. `allocate_slots`가 `num_external_computed_tokens`로 외부 메모리 존재를 이미 안다
- 프레이밍은 **DIP라는 이름에 매이지 않는다**(사용자 지시). 다음 형태를 쓴다:
  > 추상화는 **두 번째 메모리 계층이 생긴 그 지점에서 이미 새고 있고, 계층마다 반복된다.**
- 이 재작성으로 §1.5 문제 한 문장도 손봐야 한다. 현재:
  > "vLLM v1에는 배치 결정을 담는 자리가 없기 때문에, 6단 이기종 메모리로 확장하면 tier 지식이 스케줄러로 올라와 DIP가 깨지고, 새 메모리를 도입하는 비용이 스케줄러를 수정하는 비용으로 전가된다."
  → "확장하면 깨진다"(가정법)를 "이미 새고 있고 계층마다 반복된다"(현재형)로 바꾼다.

**대기 (우선순위 순)**

1. full deck **5장(계층 위반)** 을 새 §1.3에 맞춰 갱신. 현재 부제가
   "오늘은 계층이 깨끗하다 — 단, 지킨 것이 아니라 메모리가 하나여서 지킬 필요가 없었다" 로
   틀린 주장을 그대로 담고 있다. `build-dp1-full-deck.js` 수정 후 재생성.
2. comparison 덱(5장)·detail 덱(10장)의 대표 도면을 새 배경의 `Scheduler → Placer → tiers` 형태로 정렬.
   (제안했으나 사용자 승인 전)
3. `TESTING.md`의 `--policies c1,c2-steelman` 예시 정정 — 비대칭 비교라 오해를 부른다.
   (제안했으나 사용자 승인 전)
4. 미착수 제안: **DP3(재배치 트리거)** / **DP4(요청 특성 예측)** 을 실제 DP 문서로 작성,
   DP2 프로토타입, DP2 full deck.

### 배경 §1의 현재 구성 (재작성 시 유지할 골격)

```text
1.1 응용    — 메모리 월 + KV 산식 표
1.2 대응    — 6-tier 표 + 533배/256배 콜아웃
1.3 SW 구조 문제 — 계층 위반 다이어그램 ② + 빈 자리 다이어그램 ③ + 대가 3개
                   + "새 메모리를 도입하는 비용이 스케줄러를 수정하는 비용이 된다"
1.4 QA      — 4개. 계층 문제는 QA 축이 아니라 §10에서 판정하는 공통 문턱이라는 주석 포함
1.5 문제    — 한 문장
```

§3의 대표 도면은 배경의 `???` 자리를 채우는 형태로 이미 정렬돼 있다 —
§1.3을 고칠 때 이 정렬이 깨지지 않는지 확인할 것.

```text
C1: Scheduler ──"n 블록"──► Placer ──► HBM│cHBM│DRAM│CXL│HBF│SSD
                (요청은 익명)     ▲
                             Tier 상태표        ← 자원이 결정한다

C2: Scheduler ─"n 블록+요청"─► Placer ──► HBM│cHBM│DRAM│CXL│HBF│SSD
                (요청이 특성 동반) ▲
                            객체 등급/비용       ← 객체가 결정한다
```
