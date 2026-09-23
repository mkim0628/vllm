# 동작 시나리오 모음 (구현 참고용)

`doc-mk/`에 흩어져 있던 sequence diagram들을 시나리오 단위로 뽑아 모은
폴더입니다. **각 파일은 나중에 실제로 구현할 때 "이 시퀀스대로 만들면 된다"는
참고 자료로 쓰는 것을 목표로 합니다.**

## 상태 범례

- ✅ **기존** — 지금 vLLM 코드에 이미 그대로 존재하는 동작. 새 설계가 이 흐름과
  어긋나지 않는지 검증하는 기준선(baseline)으로 사용하세요.
- 🧩 **설계 제안** — 아직 vLLM에 구현되어 있지 않은, `doc-mk`의 설계 문서에서
  제안한 동작. 구현 시 이 시퀀스를 그대로 클래스/메서드 설계의 출발점으로
  삼으면 됩니다.

## 목록

| 번호 | 파일 | 요약 | 상태 | 출처 |
|---|---|---|---|---|
| 01 | [kv-cache-init-startup.md](./01-kv-cache-init-startup.md) | 엔진 기동 시 KV cache 텐서를 실제로 할당하는 초기화 시퀀스 | ✅ 기존 | `vllm-kv-cache-analysis.md` §9.1 |
| 02 | [mal-tier-discovery-negotiation.md](./02-mal-tier-discovery-negotiation.md) | MAL이 플러그인으로 등록된 메모리 티어를 찾아 능력치를 수집하고 DIRECT/STAGED를 확정하는 시퀀스 | 🧩 설계 제안 | `vllm-kv-cache-memory-abstraction-layer.md` §2.1 |
| 03 | [mal-runtime-block-placement-gather.md](./03-mal-runtime-block-placement-gather.md) | 매 스텝 블록을 어느 티어에 둘지 정하고, attention이 DIRECT/STAGED에 따라 다르게 gather하는 시퀀스 | 🧩 설계 제안 | `vllm-kv-cache-memory-abstraction-layer.md` §2.2 |
| 04 | [cxl-offload-eviction-cascade.md](./04-cxl-offload-eviction-cascade.md) | CXL을 오프로드 티어로 추가했을 때의 prefix-cache 히트/미스 및 eviction 캐스케이드 | 🧩 설계 제안 | `vllm-kv-cache-memory-tiering.md` §1.4 |
| 05 | [mal-tiering-and-compute-axes-per-step.md](./05-mal-tiering-and-compute-axes-per-step.md) | 같은 스텝 안에서 Tiering 축(스케줄러)과 Compute 축(워커)이 서로 몰라도 되게 독립적으로 흐르는 시퀀스 | 🧩 설계 제안 | `vllm-kv-cache-memory-abstraction-layer.md` §7.3 |
| 06 | [dp1-candidate1-placement-decision.md](./06-dp1-candidate1-placement-decision.md) | DP-1 후보1(범용 인터페이스)의 배치 결정 흐름 | 🧩 설계 제안 | `vllm-memory-abstraction-level-candidates.md` §3.4 |
| 07 | [dp1-candidate2-placement-decision.md](./07-dp1-candidate2-placement-decision.md) | DP-1 후보2(확장 인터페이스)의 배치 결정 흐름 — 확장 유무를 고려한 판단과 `TieredBlockTable` 기록 포함 | 🧩 설계 제안 | `vllm-memory-abstraction-level-candidates.md` §4.4 |
| 08 | [dp1-candidate2-compute-dispatch.md](./08-dp1-candidate2-compute-dispatch.md) | DP-1 후보2의 `ComputeDispatcher`가 forward pass 내부에서 호출되는 연결 구조 (실행 타이밍은 DP-3로 위임) | 🧩 설계 제안 | `vllm-memory-abstraction-level-candidates.md` §4.6 |
| 09 | [dp2-candidateA-centralized-migration.md](./09-dp2-candidateA-centralized-migration.md) | DP-2 후보A(중앙집중 오케스트레이션)의 티어 간 재배치 시퀀스 | 🧩 설계 제안 | `vllm-memory-coordination-locus-candidates.md` §2.3 |
| 10 | [dp2-candidateB-distributed-migration.md](./10-dp2-candidateB-distributed-migration.md) | DP-2 후보B(분산 자율 협상)의 티어 간 재배치 시퀀스 | 🧩 설계 제안 | `vllm-memory-coordination-locus-candidates.md` §3.3 |

## 읽는 순서 제안

1. **01**로 실제 vLLM이 지금 어떻게 초기화하는지 감을 잡습니다.
2. **02 → 03**으로 MAL의 기본 동작(티어 등록 → 매 스텝 배치/gather)을 봅니다.
3. **04**로 오프로드 전용 시나리오(옵션 A)를, **05**로 연산-티어까지 섞인
   시나리오(옵션 C)를 봅니다.
4. **06 vs 07 vs 08**을 나란히 비교하면 DP-1(추상화 수준) 두 후보의 실질적
   구현 차이가 드러납니다.
5. **09 vs 10**을 나란히 비교하면 DP-2(조정 주체 위치) 두 후보의 실질적
   구현 차이가 드러납니다.

## 관련 설계 문서

- `doc-mk/vllm-call-path-analysis.md`
- `doc-mk/vllm-kv-cache-analysis.md`
- `doc-mk/vllm-kv-cache-memory-tiering.md`
- `doc-mk/vllm-kv-cache-memory-abstraction-layer.md`
- `doc-mk/vllm-memory-abstraction-level-candidates.md` (DP-1)
- `doc-mk/vllm-memory-coordination-locus-candidates.md` (DP-2)
