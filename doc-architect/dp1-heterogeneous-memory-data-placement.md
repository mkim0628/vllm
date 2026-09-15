# DP1. 이기종 메모리 기반 KV 캐시 배치 구조

## 1. Design Point 개요

### 목적

LLM/Agent 추론 시스템 내에서 HBM, DRAM, CXL-PNM, Custom HBM, HBF, SSD-PIM 등 저장·연산 특성이 서로 다른 메모리가 혼재할 때, **활성 실행에서 벗어난 KV 캐시를 어느 메모리에 둘 것인지**를 어떤 기준으로 결정할지 설계한다.

### 핵심 설계 질문

> **메모리 자원 특성과 KV 캐시의 데이터 특성 중 무엇을 1차 기준으로 배치·이동을 결정할 것인가?**

### 결정 시점 — 이 DP가 다루는 순간

**KV가 비활성으로 전환되는 순간**이다. 활성 Decode 중인 KV는 대상이 아니다.

```text
       Prefill ──► Decode  ◄── 활성 구간: KV는 연산이 닿는 메모리에 있어야 한다
                     │           (본 DP의 결정 대상 아님)
                     ▼
              ┌─────────────┐
              │  비활성 전환 │  ◄── 본 DP의 결정 시점
              └──────┬──────┘
                     │  "이 KV를 어디에 둘 것인가?"
      ┌──────┬───────┼───────┬──────┬──────┐
      ▼      ▼       ▼       ▼      ▼      ▼
    HBM  Custom  CXL-PNM   DRAM   HBF  SSD-PIM
          HBM
                     │
                     ▼
              ┌─────────────┐
              │   재활성    │  ◄── 복원 비용 또는 연산 오프로드
              └─────────────┘
```

비활성 전환의 계기는 넷이다.

| 계기 | 언제 | 다시 필요해지는 시점 | 재사용 확률 |
|---|---|---|---|
| **턴 종료 (Agent Multi-turn)** | Turn N Decode 완료, Tool 실행 대기 진입 | Turn N+1의 Incremental Prefill | 높음 (세션이 계속되면) |
| **재사용분 보존** | Block 완성 시 (Prefix Cache 후보) | 다른 Request의 Prefix Cache Hit | 중간 (공유도에 따라) |
| **선점 (Preemption)** | HBM 부족으로 Request가 밀려남 | 재개 시 | 매우 높음 |
| **세션 종료 후 보관** | Request 완료 | 이후 세션의 Prefix Cache Hit | 낮음 |

네 계기의 공통점이 이 DP의 성립 근거다.

> **지금 Decode 중이 아니고, 언제 다시 필요해질지 불확실한 KV.**
> 그래서 "어디에 둘 것인가"가 자명하지 않고 정책이 필요하다.

### 대상 범위

| | |
|---|---|
| **대상** | 비활성 전환 시점의 KV 캐시 배치 및 이후의 재배치 |
| **대상 아님** | **활성 Decode 중인 KV** — 연산이 닿는 메모리에 있어야 하므로 선택지가 없다. 예외는 §4의 Attention 오프로드이며, 그 경우에도 결정은 비활성 시점에 내려진다 |
| **대상 아님** | Model Weight, MoE Expert Weight, LoRA Adapter, Activation, Embedding/RAG Index |
| **대상 아님** | **어떤 KV를 회수(Evict)할 것인가** — DP3의 쟁점. 경계는 §14 참조 |
| **대상 아님** | **Prefill 연산을 어느 Node에서 수행할 것인가** — DP2의 쟁점 |

> **왜 "할당 시점 배치"가 아닌가.** Prefill 직후 곧바로 Decode가 시작되므로, 갓 생성된 KV를 연산이 닿지 않는 메모리에 쓰는 것은 즉시 되가져와야 하는 순손실이다. 실제 vLLM의 offloading 경로도 활성 KV를 옮기지 않는다 — 블록이 완성될 때 하위 매체에 **사본**을 만들고, 그 사본은 이후 Prefix Cache Hit 시점에 다시 로드된다. **계층화 결정은 비활성 KV에 대해서만 실재한다.**

---

## 2. 배경 / 문제 정의

### ① AI 워크로드의 메모리 병목 심화에 따라 용량·대역폭 특성이 상이하고 연산 기능까지 지원하는 메모리 솔루션이 등장

메모리 병목 해소를 위해 단일 시스템 내에 용량·대역폭·지연시간 특성이 서로 다른 이기종 메모리가 혼재할 수 있다.

```text
                    Heterogeneous Memory

  HBM          Custom HBM      CXL-PNM       DRAM       HBF        SSD-PIM
  High BW      High BW         High Cap      Normal     High BW    High Cap
                 + 연산          + 연산                   Flash      + 연산
```

특히 일부 메모리는 데이터 저장뿐 아니라 **연산 기능(Compute Capability)** 까지 제공한다. **CXL-PNM, Custom HBM, SSD-PIM**이 여기 해당하며, 이들은 데이터를 연산 유닛으로 옮기는 대신 **연산을 데이터가 있는 곳으로 보내는** 실행 경로를 연다. 각 메모리의 구체적 특성과 이 실행 경로의 성립 조건은 §3, §4에서 다룬다.

일부 메모리는 **Read/Write 비대칭성**과 **유한한 Write Endurance**도 갖는다(HBF, SSD-PIM). Capacity / BW / Latency만으로 판단하면 쓰기 왕복이 잦은 데이터를 저내구성 메모리에 배치하여 성능 저하와 수명 소모를 동시에 유발할 수 있다.

### ② Agent 환경에서 Tool을 호출하며 Multi-turn을 수행함에 따라 워크로드가 다양해지고, KV 캐시가 Locality·Hotness·Lifetime 등 상이한 데이터 특성을 보임

Agent 워크로드는 단일 `Prefill → Decode`로 끝나지 않고 **LLM 추론 → Tool Call → Tool Result → LLM 추론**을 반복한다. 이 구조가 KV 캐시의 특성을 균질하지 않게 만든다.

```text
Turn 1        Turn 2              Turn 3                  Turn N
Prefill       Tool 대기           Tool 대기               ...
  │             │                   │
Decode ──► Tool 호출 ──► Decode ──► Tool 호출 ──► Decode ──► ...
  │             │                   │
  ▼             ▼                   ▼
System       Tool Result A       Tool Result B
Prompt       (재사용 없음)       (다음 턴에 즉시 사용)
(여러 세션
 공유)
```

같은 세션 안에서도 구간마다 특성이 갈린다.

| 데이터 특성 | Agent 워크로드에서 무엇이 이를 만드는가 | 관측되는 분포 |
|---|---|---|
| **Locality** | Tool 종류에 따라 다음 턴이 참조하는 Context 구간이 달라짐 | 일부 구간에 집중 vs 전 구간 균등 |
| **Hotness** | System Prompt·공통 Instruction은 여러 세션이 공유, 사용자 고유 구간은 단일 세션 전용 | 공유도가 자릿수로 차이 |
| **Lifetime** | Tool 실행 시간(수백 ms ~ 수십 초)과 세션의 남은 턴 수가 제각각 | 유휴 시간과 잔여 수명이 넓게 분포 |

Turn이 반복될수록 누적 Context는 커지고, **접근은 없으면서 용량만 점유하는 KV**가 구조적으로 늘어난다. 동시에 유휴 구간이 길다는 것은 **KV를 옮길 시간적 여유가 있다**는 뜻이기도 하다 — 활성 Decode 중에는 없는 여유다.

```text
Context Length ↑          Concurrency ↑
        │                       │
        └───────────┬───────────┘
                    ▼
            KV Cache Size ↑
                    │
                    ▼
        HBM Capacity Pressure ↑
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
  신규 Request 수용 제한     Preemption / 재계산
```

**즉 특성에 따라 적합한 메모리 자원이 달라진다.** 다음 턴에 즉시 쓰일 KV와 이미 종료된 세션의 KV는 같은 곳에 있을 이유가 없고, 여러 세션이 공유하는 Prefix와 단일 세션 전용 구간도 마찬가지다.

### ③ 따라서 기존 HBM 우선의 단순 배치 정책에서 벗어나, KV 캐시의 데이터 특성과 메모리 자원 특성을 함께 고려한 배치 구조가 필요

기존 HBM–DRAM–SSD 구조에서는 계층이 사실상 용량 확장 수단이었으므로 **HBM 우선 할당 + 부족 시 순차 Spill**이 합리적이었다. 그러나 연산 기능을 포함해 역할이 서로 다른 메모리가 추가되고 KV 특성이 다양해진 지금, 이 정책은 두 가지를 놓친다.

- **메모리 쪽:** 신규 메모리가 용량 확장 수단으로만 쓰이고 연산 기능이 활용되지 않는다.
- **데이터 쪽:** 다음 턴에 즉시 쓰일 KV와 종료된 세션의 KV를 구별하지 않는다.

### As-Is

**KV 특성을 고려하지 않은 단순 배치 정책 (HBM 우선 유지, 부족 시 하위 계층으로 순차 Spill)**
→ 신규 메모리 도입 시 연산 기능과 계층별 특성이 활용되지 않고 비효율적 자원 사용 발생

### To-Be

**메모리 자원 특성 및 KV 캐시의 데이터 특성을 함께 고려한 배치·이동 정책**
→ 신규 메모리의 저장·연산 특성을 활용하여 HBM Pressure를 완화하고 재활성 비용을 최소화

---
## 3. 대상 메모리 구성

시뮬레이션에서 판단 근거로 쓸 6종 메모리의 구성을 고정한다. **모든 수치는 공개 자료 기반 대표값이며 벤더 데이터가 아니다** — §3.5에 항목별 출처와 가정 여부를 명시한다.

### 3.1 6종 메모리와 연산 가능 여부

| 메모리 | 역할 | 연산 가능 | 연산 성향 | 용량 | GPU가 직접 읽는가 |
|---|---|:---:|---|---|:---:|
| **HBM** | GPU 주 메모리 | ✗ | — | 소 | ✓ |
| **Custom HBM** | 연산 기능 내장 HBM | **✓** | GEMM 계열 | 소 | ✓ |
| **CXL-PNM** | 대용량 연산형 확장 메모리 | **✓** | GEMM 계열 | **대** | ✗ (CPU 경유) |
| **DRAM** | CPU 측 주 메모리 | ✗ | — | 중 | ✗ (CPU 경유) |
| **HBF** | 고대역 플래시 | ✗ | — | **대** | ✓ (on-package) |
| **SSD-PIM** | 연산 기능 내장 스토리지 | **✓** | GEMV 계열 | **최대** | ✗ |

연산 가능 메모리는 **CXL-PNM, Custom HBM, SSD-PIM** 세 종이다. HBF는 대역폭이 높지만 연산 기능이 없으므로 **용량 계층**으로만 쓴다.

### 3.2 Interconnect Exploration

배치 결정에서 결정적인 것은 메모리 자체의 대역폭이 아니라 **그 메모리에 도달하는 경로의 대역폭**이다. 네 가지를 각각 짚는다.

#### Custom HBM ↔ GPU

현재 공개된 방향은 **on-package 통합**이다. HBM4가 인터페이스를 2048-bit / 32채널로 넓혀 스택당 2.0~3.3 TB/s에 도달하고, Custom HBM은 여기에 **로직/가속기 회로를 얹은 base die**를 쓴다. 메모리 다이와 컴퓨트 다이를 묶는 방식으로 **UCIe 기반 die-to-die 인터페이스**가 거론된다.

```text
   GPU Die ──[ UCIe die-to-die, on-package ]── Custom HBM Base Die ── DRAM Core Dies
                     낮은 지연                        (연산 유닛)         2.0~3.3 TB/s
```

- **외부 대역폭:** HBM4 급 (스택당 2.0~3.3 TB/s). GPU가 직접 읽는다.
- **내부 대역폭:** base die의 연산 유닛은 PHY를 거치지 않고 DRAM core에 접근하므로 외부보다 **높게** 잡을 수 있다. 다만 공개된 정량값이 없어 본 구성에서는 **외부의 1.5배**로 가정한다.
- **함의:** 외부/내부 비대칭이 작다. **연산을 여기로 보내는 이득은 대역폭 절감이 아니라 GPU 연산 유닛을 비워주는 데서 나온다.** 목적함수에 GPU Occupancy 항이 없는 한(§11) 이 이득은 측정되지 않으므로, Custom HBM 관련 수치는 특히 하한 성격이 강하다.

#### CXL-PNM ↔ GPU

**이 구성에서 가장 중요한 비대칭이 여기서 나온다.** CXL-PNM은 CPU에 PCIe로 붙으므로 GPU에서 보면 **두 홉**이다.

```text
   GPU ──[ PCIe ]── CPU ──[ CXL over PCIe ]── CXL-PNM
                                              LPDDR5X, ~512 GB
        └────────── 64 GB/s 급 ──────────┘    내부 ~1.1 TB/s
                  (링크가 병목)
```

| | 값 | 근거 |
|---|---|---|
| CXL 링크 (PCIe 5.0 x16) | 방향당 **64 GB/s** | PCIe 5.0 x16 규격 |
| (참고) PCIe 6.0 / 7.0 x16 | 128 / 256 GB/s | 세대별 목표치 |
| 장치 내부 대역폭 | **~1.1 TB/s** | LPDDR5X 기반 CXL-PNM 플랫폼 공개값 |
| 용량 | ~512 GB | 동상 |
| 링크 지연 | ~170~250 ns (load-to-use), CPU 홉 포함 시 더 큼 | CXL.mem 공개 측정 범위 |

- **외부/내부 비대칭 ≈ 17배.** KV를 링크로 끌어내는 순간 1.1 TB/s짜리 메모리를 64 GB/s로 쓰는 셈이 된다.
- **함의:** **CXL-PNM에 둔 KV는 옮기면 안 되고, 연산을 보내야 한다.** 이것이 §4의 Attention/FFN 분리가 필요한 직접적 이유다. 링크를 건너는 것은 KV(GB 단위)가 아니라 활성화 텐서(MB 단위)여야 한다.

#### HBF ↔ GPU

2026년 FMS에서 SK hynix·SanDisk가 **OCP 기술 규격 초판**을 공개했다. HBM과 SSD 사이를 메우는 계층으로, NAND를 HBM식 패키지에 적층하고 **UCIe**로 프로세서에 붙인다.

| | 값 |
|---|---|
| 스택 용량 | 최대 **512 GB** (8-high / 16-high) |
| 대역폭 등급 | **약 0.4 ~ 3.0 TB/s** (3개 등급) |
| 차세대 | Gen2 > 2 TB/s, Gen3 > 3.2 TB/s / 스택 1 TB~1.5 TB |
| 인터커넥트 | UCIe (CPU·GPU 모두 통합 가능) |

- **읽기 대역폭은 HBM에 근접하지만 매체가 NAND**이므로 읽기 지연이 DRAM보다 크고, **쓰기 대역폭과 Write Endurance가 제약**이다.
- **함의:** 읽기 위주·대용량 보관에 적합하다. 다만 **비활성 전환마다 쓰고 재활성마다 읽는 왕복이 반복되면 수명이 소모**되므로(§11 M-E1), 왕복 빈도가 높을 KV를 여기 두면 안 된다.

#### SSD-PIM ↔ GPU

NVMe 경로이므로 호스트 링크가 가장 좁다.

| | 값 |
|---|---|
| 호스트 링크 (PCIe 5.0 x4) | ~16 GB/s |
| 내부 NAND 집계 대역폭 | 호스트 링크보다 높음 (PIM의 존재 이유) |
| 지연 | 수십 μs 급 |
| 연산 성향 | GEMV 계열 |

- **외부/내부 비대칭이 크다.** CXL-PNM과 같은 이유로 **끌어내지 말고 연산을 보내야** 하지만, 지연이 μs 급이라 대화형 경로에 넣기 어렵다.
- **함의:** 재사용 확률이 낮은 장기 보관용. 연산 오프로드는 지연 허용치가 큰 배치성 경로에서만 성립한다.

### 3.3 외부/내부 대역폭 비대칭 — 연산 오프로드 판단의 1차 기준

위 탐색을 하나의 표로 모으면, **어떤 메모리에서 연산 오프로드가 값을 하는지**가 바로 읽힌다.

| 메모리 | 외부(링크) 대역폭 | 내부 대역폭 | 비대칭 | 연산 오프로드 |
|---|---:|---:|---:|---|
| HBM | 2.0~3.3 TB/s | = 외부 | 1× | 불가 (연산 기능 없음) |
| Custom HBM | 2.0~3.3 TB/s | ~1.5× 가정 | **~1.5×** | 가능하나 대역폭 이득은 작음 — 이득은 GPU Occupancy |
| DRAM | 링크 ~64 GB/s | 400~800 GB/s | ~10× | 불가 (연산 기능 없음) |
| **CXL-PNM** | **64 GB/s** | **~1.1 TB/s** | **~17×** | **가장 값이 큼** |
| HBF | 0.4~3.0 TB/s | — | — | 불가 (연산 기능 없음) |
| SSD-PIM | ~16 GB/s | 수백 GB/s 급 | ~10× 이상 | 가능하나 지연이 커서 배치성 경로 한정 |

> **이 표가 §4와 §7 C2의 근거다.** 비대칭이 큰 메모리일수록 "KV를 옮길지 연산을 보낼지"의 답이 명확해지며, 그 판단을 하려면 **이 KV가 다음에 어떤 연산을 받는지**를 알아야 한다 — 그것이 데이터 특성 기반 후보(C2)의 고유 입력이다.

### 3.4 시뮬레이션 Configuration

`configs/memories_default.json` 형태로 고정한다. 코드 수정 없이 수치를 교체할 수 있어야 하며, 사내 스펙 시트로 갈아끼우는 경로가 된다.

```json
{
  "memories": [
    {
      "name": "hbm", "medium": "HBM",
      "capacity_bytes": 206158430208,
      "ext_bw_bytes_per_s": 3.0e12,
      "int_bw_bytes_per_s": 3.0e12,
      "latency_s": 3.0e-7,
      "gpu_reachable": true,
      "supported_primitives": [],
      "write_amplification": 1.0,
      "endurance_budget_bytes": null,
      "provenance": "HBM4 class, 2.0-3.3 TB/s per stack (public)"
    },
    {
      "name": "custom_hbm", "medium": "CUSTOM_HBM",
      "capacity_bytes": 103079215104,
      "ext_bw_bytes_per_s": 3.0e12,
      "int_bw_bytes_per_s": 4.5e12,
      "latency_s": 3.0e-7,
      "gpu_reachable": true,
      "supported_primitives": ["QK_GEMM", "SOFTMAX", "AV_GEMM", "CAUSAL_MASK"],
      "write_amplification": 1.0,
      "endurance_budget_bytes": null,
      "provenance": "ext=HBM4 public; int=ASSUMED 1.5x ext (no public figure)"
    },
    {
      "name": "cxl_pnm", "medium": "CXL_PNM",
      "capacity_bytes": 549755813888,
      "ext_bw_bytes_per_s": 6.4e10,
      "int_bw_bytes_per_s": 1.1e12,
      "latency_s": 2.5e-7,
      "hops": ["gpu->cpu:pcie", "cpu->dev:cxl"],
      "gpu_reachable": false,
      "supported_primitives": ["QK_GEMM", "SOFTMAX", "AV_GEMM", "CAUSAL_MASK"],
      "write_amplification": 1.0,
      "endurance_budget_bytes": null,
      "provenance": "ext=PCIe 5.0 x16 spec; int/cap=LPDDR5X CXL-PNM public"
    },
    {
      "name": "dram", "medium": "DRAM",
      "capacity_bytes": 1099511627776,
      "ext_bw_bytes_per_s": 6.4e10,
      "int_bw_bytes_per_s": 4.0e11,
      "latency_s": 2.0e-7,
      "gpu_reachable": false,
      "supported_primitives": [],
      "write_amplification": 1.0,
      "endurance_budget_bytes": null,
      "provenance": "DDR5-6400 51.2 GB/s per channel (public); ext via PCIe"
    },
    {
      "name": "hbf", "medium": "HBF",
      "capacity_bytes": 2199023255552,
      "ext_bw_bytes_per_s": 1.0e12,
      "int_bw_bytes_per_s": 1.0e12,
      "write_bw_bytes_per_s": 5.0e10,
      "latency_s": 5.0e-6,
      "gpu_reachable": true,
      "supported_primitives": [],
      "write_amplification": 3.0,
      "endurance_budget_bytes": 1.0e17,
      "provenance": "cap 512GB/stack, BW 0.4-3.0 TB/s, UCIe (OCP spec, FMS 2026); write BW/endurance ASSUMED"
    },
    {
      "name": "ssd_pim", "medium": "SSD_PIM",
      "capacity_bytes": 17592186044416,
      "ext_bw_bytes_per_s": 1.6e10,
      "int_bw_bytes_per_s": 2.0e11,
      "latency_s": 6.0e-5,
      "gpu_reachable": false,
      "supported_primitives": ["QK_GEMM", "AV_GEMM"],
      "write_amplification": 4.0,
      "endurance_budget_bytes": 1.0e16,
      "provenance": "ext=PCIe 5.0 x4 spec; int/endurance ASSUMED"
    }
  ]
}
```

세 가지가 이 스키마에 의도적으로 들어 있다.

**`ext_bw`와 `int_bw`를 분리한다.** 하나로 합치면 §3.3의 비대칭이 표현되지 않고, **연산 오프로드가 왜 값을 하는지가 모델에서 사라진다.** 연산 가능 메모리는 `int_bw`를 반드시 선언해야 하며, 없으면 loader가 거부한다 — 기본값을 외부 속도로 두면 memory-side compute가 링크 속도로 도는 것으로 조용히 모델링되어 그 기능이 존재하는 이유가 없어진다.

**`supported_primitives`가 연산 단위가 아니라 원시 연산 단위다.** "GEMV를 지원한다"와 "Attention을 처리할 수 있다"는 다르다. Softmax가 없으면 Attention을 그 메모리에서 끝낼 수 없으므로, `ssd_pim`처럼 `SOFTMAX`가 빠진 구성은 Attention 오프로드 대상이 되지 않는다. 연산을 `ATTENTION` 하나로 두면 이 구분이 사라지고 §11 M-P7이 과대평가된다.

**`hops`가 경로를 명시한다.** CXL-PNM은 GPU에서 두 홉이므로 실효 대역폭과 지연이 단일 링크 값과 다르다.

### 3.5 수치의 출처와 가정

| 항목 | 출처 | 상태 |
|---|---|---|
| HBM4 스택당 2.0~3.3 TB/s, 2048-bit/32ch | 공개 스펙·벤더 발표 | 공개값 |
| HBF 스택 512 GB, 0.4~3.0 TB/s, UCIe | OCP 기술 규격 초판 (FMS 2026) | 공개값 |
| HBF 쓰기 대역폭·Endurance Budget | — | **가정값** |
| CXL-PNM 내부 1.1 TB/s, 용량 512 GB | LPDDR5X 기반 플랫폼 공개값 | 공개값 |
| PCIe 5.0/6.0/7.0 x16 대역폭 | PCIe 규격 | 공개값 |
| Custom HBM 내부 대역폭 (외부의 1.5배) | — | **가정값** (공개 정량값 없음) |
| SSD-PIM 내부 대역폭·Endurance | — | **가정값** |
| CXL 지연 170~250 ns | 공개 측정 범위 | 공개값(범위) |

> **가정값이 결론을 지배하지 않는지 확인해야 한다.** §11.6의 Sweep에 **Custom HBM 내부/외부 비율**과 **HBF 쓰기 대역폭**을 반드시 포함한다. 두 값은 각각 "Custom HBM에 연산을 보낼 값이 있는가"와 "HBF를 왕복 매체로 쓸 수 있는가"를 직접 좌우한다.

---

## 4. Attention / FFN 분리 실행

§3.3에서 본 외부/내부 비대칭을 실제로 활용하는 실행 구조다. **KV를 링크로 끌어내지 않고, Attention 연산을 KV가 있는 메모리에서 수행한다.**

### 4.1 Transformer Layer의 분해

Transformer 한 계층은 **KV에 접근하는 부분(Attention)** 과 **접근하지 않는 부분(Projection · FFN)** 으로 나뉜다. KV가 연산형 메모리에 있으면 이 경계를 그대로 실행 경계로 쓸 수 있다.

```text
                  계층 l (Decode 1 token 기준)

   GPU                                    Compute-capable Memory
   ───                                    ──────────────────────
   h_in
    │
    ├─ LayerNorm
    ├─ QKV Projection  ──► Q, K_new, V_new
    │                          │
    │                          └──[ 링크 ]──► K_new, V_new append
    │                          Q  ─[ 링크 ]──►     │
    │                                              ▼
    │                                    Attention(Q, K_cache, V_cache)
    │                                      = softmax(QKᵀ/√d) · V
    │                                              │   내부 대역폭으로
    │                                              │   KV 전체를 읽음
    │                          ◄──[ 링크 ]─────────┘
    ├─ O Projection            attn_out
    ├─ Residual + LayerNorm
    ├─ FFN                     ◄── KV에 접근하지 않음. GPU가 수행
    └─ Residual
   h_out
```

**KV는 링크를 건너지 않는다.** 건너는 것은 Q, K_new/V_new, attn_out — 모두 **토큰 수 × hidden** 크기의 활성화 텐서다.

이 구조는 이전 판에서 검토했던 "Attention을 GPU와 메모리에 쪼개 partial softmax를 병합하는" 방식보다 단순하다. **신규 토큰의 K/V도 같은 메모리에 append하므로 Attention 전체가 한 곳에서 끝나고, softmax 재정규화가 필요 없다.**

### 4.2 링크를 건너는 바이트 — 정량

아래는 **가정 모델**(dense 70B급: hidden 8192, 계층 80, heads 64, head_dim 128, GQA kv_heads 8, fp16)에서의 계산이다. 숫자 자체보다 **자릿수 차이**가 요점이다.

```text
KV 크기
  토큰·계층당 = 2(K,V) × 8 heads × 128 dim × 2B = 4 KiB
  토큰당 전체 = 4 KiB × 80 계층          = 320 KiB
  32K context                            = 10 GiB   ← 세션 하나

Decode 1 token, 계층당 링크 통과량
  Q          64 × 128 × 2B = 16 KiB
  K_new,V_new                =  4 KiB
  attn_out   64 × 128 × 2B = 16 KiB
  ─────────────────────────────────
  계층당                     ≈ 36 KiB
  × 80 계층                  ≈ 2.8 MiB   ← Decode 1 token 전체
```

| | 링크를 건너는 양 | PCIe 5.0 x16 (64 GB/s) 기준 시간 |
|---|---:|---:|
| **KV를 HBM으로 복원** (Attention을 GPU에서) | **10 GiB** (재활성 시 1회) | **~164 ms** |
| **Attention 오프로드** (§4.1) | **2.8 MiB** (Decode token당) | **~46 μs** |

**약 3,600배 차이**다. 좁은 링크 뒤에 있는 메모리일수록 이 구조가 값을 한다.

### 4.3 계층당 왕복 지연 — 이 구조의 비용

바이트는 작지만 **왕복 횟수가 계층 수만큼 늘어난다.** 이것이 Attention 오프로드의 고유 비용이다.

```text
Decode 1 token당 링크 왕복 = 80회 (계층당 1회)

  전송 시간      ≈  46 μs   (§4.2)
  왕복 지연      ≈  80 × 2 μs = 160 μs   (CXL 경로, 가정값)
  ──────────────────────────────────────
  링크 오버헤드  ≈ 206 μs / token
```

TPOT 목표가 30 ms라면 0.7% 수준이다. 다만 **지연이 μs 급인 SSD-PIM에서는 같은 계산이 성립하지 않는다** — 80회 × 60 μs = 4.8 ms가 되어 대화형 경로에서 무시할 수 없다. §3.2가 SSD-PIM의 연산 오프로드를 배치성 경로로 한정한 이유다.

배치 안의 여러 요청이 같은 계층을 함께 처리하면 왕복이 상쇄(amortize)되므로, **이 비용은 배치 크기에 반비례**한다. 시뮬레이션에서 배치 크기를 Sweep 축에 넣어야 하는 이유다.

### 4.4 언제 오프로드가 이기는가 — 손익분기

재활성 이후의 동작을 두 방식으로 비교하면 손익분기가 **턴당 생성 토큰 수**로 나온다. (§4.2와 같은 가정 모델, 세션 KV 10 GiB, CXL-PNM 내부 1.1 TB/s, HBM 3.0 TB/s)

```text
방식 B. 복원 후 GPU Attention
  재활성 1회      10 GiB / 64 GB/s        ≈ 164 ms
  Decode step당   10 GiB / 3.0 TB/s       ≈ 3.4 ms
  총              164 + 3.4 N

방식 C. Attention 오프로드
  재활성 1회      복원 없음                ≈ 0
  Decode step당   10 GiB / 1.1 TB/s + 0.2 ≈ 9.5 ms
  총              9.5 N

손익분기   164 + 3.4 N = 9.5 N  →  N ≈ 27 tokens
```

> **턴당 생성 길이가 약 27 토큰보다 짧으면 Attention 오프로드가 유리하고, 길면 복원이 유리하다.**
>
> Agent 워크로드는 이 경계의 **유리한 쪽**에 있는 경우가 많다 — Tool Call을 결정하는 턴의 출력은 대개 짧은 구조화 텍스트다. 반대로 최종 답변을 길게 생성하는 턴은 복원이 유리하다. **같은 세션 안에서도 턴마다 답이 달라진다**는 뜻이며, 이 판단을 하려면 §5의 Expected Remaining Lifetime과 Agent Tool Info가 필요하다.

### 4.5 성립 조건

이 구조는 무상이 아니다. 네 조건이 모두 만족해야 한다.

| 조건 | 내용 |
|---|---|
| **원시 연산 지원** | 해당 메모리가 `QK_GEMM`, `SOFTMAX`, `AV_GEMM`, `CAUSAL_MASK`를 모두 지원해야 한다. 하나라도 빠지면 Attention이 그곳에서 끝나지 않는다 (§3.4) |
| **지연 예산** | 계층당 왕복 × 계층 수가 TPOT 예산 안에 들어와야 한다 (§4.3) |
| **용량** | 연산형 메모리가 모든 세션의 History를 담을 수 없다. **선택받은 일부만** 갈 수 있다 — 배치 정책이 필요한 이유를 강화한다 |
| **재사용 확률** | 세션이 돌아오지 않으면 연산형 메모리 자리를 낭비한 것이다. §5의 Reuse Probability 추정이 필요하다 |

---
## 5. 배치 결정에 사용할 수 있는 정보

C1/C2 모두 동일한 정보를 받는다. 차이는 정보의 차이가 아니라 **그 중 무엇을 1차 기준으로 삼는가**이므로, 먼저 사용 가능한 정보와 그 **관측 가능성**을 정리한다.

### 5.1 KV 캐시 특성 — 무엇을 분석하는가

§2②에서 서술한 Locality·Hotness·Lifetime을 **배치 결정이 실제로 소비할 수 있는 네 개의 값**으로 구체화한다. 모호한 "뜨겁다/차갑다"가 아니라 **언제·얼마나 확실하게·얼마나 오래·무슨 연산으로** 다시 쓰이는가를 묻는다.

| 특성 | 정의 | 무엇을 결정하는가 | 결정 시점에 |
|---|---|---|---|
| **Next-access Time** | 다음 접근까지 남은 시간. 턴 종료면 Tool 실행 시간, 선점이면 재개까지, Prefix 보존이면 다음 Hit까지 | **계층 깊이** — 곧 쓰일수록 얕게 | **추정 필요** |
| **Reuse Probability** | 이 KV가 다시 쓰이긴 하는가. 세션 지속 확률, Prefix 재사용 확률 | **자리를 잡아둘 가치** — 특히 §4의 연산형 메모리 자리 배정 | **추정 필요** |
| **Expected Remaining Lifetime** | 앞으로 남은 유효 기간. 남은 턴 수 × 턴당 길이, Prefix면 잔류 기대 시간 | **왕복 횟수** → 저내구성 매체 회피 (§11 M-E1), §4.4의 손익분기 | **추정 필요** |
| **Agent Tool Info** | 호출된 Tool의 종류·예상 실행 시간·결과 크기 | **위 세 값의 가장 강한 관측 근거** | **선언 가능** |

#### Agent Tool Info가 특별한 이유

나머지 세 특성은 추정값이지만, **Agent Tool Info는 결정 시점에 이미 알려진 사실**이다. 어떤 Tool이 호출됐는지는 Decode가 만들어낸 출력이므로 Scheduler가 안다.

```text
Tool 호출                     →  추정에 주는 정보
──────────────────────────────────────────────────────────
web_search                    →  Next-access Time ~ 수 초
                                 Reuse Probability 높음 (턴 계속)
code_execution (장기)         →  Next-access Time ~ 수십 초
                                 → 더 깊은 계층이 유리
db_query (단기)               →  Next-access Time ~ 수백 ms
                                 → 계층을 내리면 손해
final_answer / 종료 신호      →  Reuse Probability 낮음
                                 → 회수 대상
```

**Tool 종류별 실행 시간 분포는 워크로드 통계로 직접 잡힌다.** 이것이 §5.2에서 다루듯 이 DP의 추정을 "원리적으로 불가능한 예측"이 아니라 "추정 품질의 문제"로 만드는 핵심 근거다.

#### 파생 특성

위 네 값에서 다음이 따라 나오며, 별도로 관측되기도 한다.

- **공유도 (Share Count)** — 이 Block을 Prefix로 참조하는 세션 수. 현재 값은 관측 가능, 미래는 Reuse Probability의 일부.
- **재활성 연산 (Next Operation)** — 재활성 시 받을 Attention의 원시 연산 집합. §3.4의 `supported_primitives`와 매칭되어 §4의 오프로드 가능 여부를 결정한다. **선언 가능.**

### 5.2 이 DP에서 중요한 세 가지 제약

**(1) 미지값은 "언제·다시 쓰이는가"이며, 이는 부분적으로 추정 가능하다.**

결정 시점에 알 수 없는 것은 Next-access Time, Reuse Probability, Expected Remaining Lifetime이다. 다만 이 값들은 "출력 길이" 같은 원리적 미지값과 성질이 다르다 — **Tool 실행 시간 분포, 세션당 턴 수 분포, Prefix 재사용률은 워크로드 통계로 상당 부분 잡히며, Agent Tool Info가 매 결정마다 직접적인 관측 근거를 준다.** 따라서 C2의 추정은 원리적으로 불가능한 예측이 아니라 **추정 품질의 문제**이며, 이 점이 §10의 QA 가설과 §11의 민감도 측정(M-P8)을 읽는 전제다.

계기별로 추정 난이도가 다르다는 점도 중요하다.

| 계기 | Next-access Time | Reuse Probability | 가장 강한 근거 |
|---|---|---|---|
| 선점 | 쉬움 (Scheduler가 재개 예정을 안다) | 거의 1.0 | Scheduler 상태 |
| 턴 종료 | 중간 | 중간 (세션 지속률) | **Agent Tool Info** |
| 재사용분 보존 | 어려움 | 어려움 | 공유도 |
| 세션 종료 후 보관 | 어려움 | 낮음 | 과거 Hit 이력 |

**(2) 재접근이 all-or-nothing이다.**

비활성 KV는 재활성 시 **History 전체가 한꺼번에** 필요하다. 절반만 복원해서 시작할 수 없다. 따라서 배치 단위가 개별 Block이 아니라 **세션 단위 Block 집합**이고, 한 집합을 여러 계층에 흩으면 재활성 비용이 가장 느린 계층에 지배된다.

**(3) Block 크기가 균일하다.**

KV Block은 `block_size × num_layers × num_kv_heads × head_dim × dtype`으로 크기가 고정된다. 결정 변수는 "이 큰 객체를 어디 둘까"가 아니라 **"균일한 Block 집합을 계층 간에 어떻게 분배할까"** 이다.

### 5.3 Memory State

두 후보 모두 관측 가능하다. §3.4 Configuration의 런타임 상태에 해당한다.

- Available Capacity
- Bandwidth (외부/내부 분리, §3.3) / Latency
- **Compute Capability** — `supported_primitives` (§4.5의 오프로드 성립 조건)
- Current Load
- Write Cost (Write Amplification) / Endurance Headroom

---

## 6. 설계 쟁점

1. **이기종 메모리 환경에서 AI 응용 추론 성능 최적화를 위한 KV 캐시 배치 구조 설계**
2. **신규 메모리 및 데이터 특성 추가 시 변경 범위 최소화를 위한 확장 가능한 KV 캐시 배치 구조 설계**

> **메모리 자원 특성과 KV 캐시의 데이터 특성 중 무엇을 1차 기준으로 배치·이동을 결정할 것인가?**

본 DP의 핵심은 입력 정보의 차이가 아니라, **동일한 정보 중 어떤 것을 Placement의 1차 기준으로 삼는가**에 있다.

공통 Allocation Request 예시:

```text
Allocation Request
(KV block size, KV metadata, op info, ...)

  KV metadata = session id, block set, bytes, trigger,
                agent tool info, share count
  op info     = 재활성 시 필요한 attention 원시 연산 집합
  trigger     = TURN_END | PREFIX_RETAIN | PREEMPTION | SESSION_DONE
```

---

## 7. 후보 구조

## Candidate 1. 메모리 특성 중심 배치 구조

### 한 줄 정의

> **메모리 특성(Capacity / BW / Compute Capability / Load)을 기준으로 배치**

### 구조

```text
                        Scheduler
                            │
          Allocation Request (KV block size, KV metadata, op info, ...)
                            │
        ┌───────────────────┼───────────────────┐
        │             Placement Manager         │
        │                                       │
        │  Memory State Collector               │
        │   - Available Capacity                │
        │   - Bandwidth (ext / int)             │
        │   - Compute Capability                │
        │   - Current Load                      │
        │              │                        │
        │              ▼                        │
        │  Placement Planner                    │
        │   - Tier Scoring                      │
        │     (capacity, BW, compute, load)     │
        │              │                        │
        │              ▼                        │
        │   - Best Tier Selection (arg max)     │
        │              │                        │
        │              ▼                        │
        │  Placement Executor  ── 할당 / 이동 수행│
        └───────────────────┬───────────────────┘
                            │  Place / Migrate
   ┌────────┬────────┬──────┴────┬────────┬────────┐
   ▼        ▼        ▼           ▼        ▼        ▼
  HBM     DRAM    CXL-PNM   Custom HBM   HBF   SSD-PIM
```

### 특징

- 메모리의 현재 상태 및 Capability가 배치의 1차 의사결정 기준이다.
- HBM Pressure가 급증하면 **즉시** 더 깊은 계층으로 내려보낸다. 자원 혼잡 회피가 즉각적이다.
- KV 특성(§5.1) 분석이 불필요하여 구조가 단순하고, 비활성 전환 경로에 추가되는 비용이 작다.
- Compute Capability는 **실행 가능성 확인**과 Scoring 가점에 쓰이지만, **KV 특성이 배치의 주 기준은 아니다.**
- Write Endurance Headroom은 관측 가능한 Memory State이므로 직접 반영할 수 있다. 다만 **어떤 KV가 이후 왕복을 반복해 내구성을 소모할지는 사전에 판단하지 않는다.**

### 장점

- 자원 상태 변화에 따른 배치 정책의 동적 적용 용이
- KV 캐시 특성 분석이 불필요해 구조 단순, 낮은 의사결정 Overhead

### 단점

- 데이터별 Access/Lifetime 특성을 반영하지 못해 Placement 최적화에 한계
- Operation–Compute Capability 간 적합성 판단에 한계 — **§4의 Attention 오프로드를 고를 근거가 약하다.** "CXL-PNM에 여유가 있다"는 알지만 "이 KV는 곧 Attention을 받으므로 거기 두면 링크를 안 건넌다"는 판단은 나오지 않는다

### 한계가 드러나는 지점

같은 시점에 비활성으로 전환된 두 세션 — 하나는 `db_query`를 호출해 300 ms 뒤 돌아오고, 다른 하나는 `final_answer`를 내고 종료됐다 — 이 **Memory State 관점에서 구별되지 않는다.** 둘 다 같은 계층으로 가고, 300 ms 뒤 첫 번째 세션은 복원 비용을 지불한다.

---

## Candidate 2. Data 특성 중심 배치 구조

### 한 줄 정의

> **KV 캐시 특성(Next-access Time / Reuse Probability / Expected Remaining Lifetime / Agent Tool Info)을 기준으로 배치**

### 구조

```text
                        Scheduler
                            │
          Allocation Request (KV block size, KV metadata, op info, ...)
                            │
        ┌───────────────────┼─────────────────────────────┐
        │              Placement Manager                  │
        │                                                 │
        │  KV Characteristic Analyzer                     │
        │   - Next-access Time                            │
        │   - Reuse Probability                           │
        │   - Expected Remaining Lifetime                 │
        │   - Agent Tool Info                             │
        │              │                                  │
        │              ▼                                  │
        │  KV Classifier                                  │
        │   ┌─────────────────────────────┐               │
        │   │ Hot & Compute-heavy         │               │
        │   │ Warm & Read-intensive       │               │
        │   │ Cold & Long-term            │               │
        │   └─────────────────────────────┘               │
        │              │                                  │
        │              ▼                                  │
        │  Placement Policy                               │
        │   Hot  → HBM, Custom HBM                        │
        │   Warm → HBM, DRAM, CXL-PNM                     │
        │   Cold → CXL-PNM, HBF, SSD-PIM                  │
        │              │                                  │
        │              ▼                                  │
        │  Memory State-aware Refiner                     │
        │   - Capacity / Load / BW / Endurance 보정        │
        │              │                                  │
        │              ▼                                  │
        │  Placement Executor                             │
        └───────────────────┬─────────────────────────────┘
                            │  Place / Migrate
   ┌────────┬────────┬──────┴────┬────────┬────────┐
   ▼        ▼        ▼           ▼        ▼        ▼
  HBM     DRAM    CXL-PNM   Custom HBM   HBF   SSD-PIM
```

### 분류 기준

`KV Classifier`는 §5.1의 네 특성에서 Class를 유도한다.

| Class | 조건 | 배치 후보 | 근거 |
|---|---|---|---|
| **Hot & Compute-heavy** | Next-access Time 짧음 + Reuse Probability 높음 + 재활성 연산이 오프로드 가능 | HBM, **Custom HBM** | 곧 쓰이고 확실히 쓰인다. 연산까지 받으므로 연산형 메모리 자리를 쓸 가치가 있다 |
| **Warm & Read-intensive** | Next-access Time 중간 + 공유도 높음 | HBM, DRAM, **CXL-PNM** | 여러 세션이 참조하는 Prefix. CXL-PNM의 대용량과 §4 오프로드가 맞는 구간 |
| **Cold & Long-term** | Next-access Time 김 또는 Reuse Probability 낮음 | CXL-PNM, **HBF, SSD-PIM** | 보관이 목적. 단 Expected Remaining Lifetime이 짧으면 왕복이 잦으므로 저내구성 매체를 피한다 |

### 특징

- KV 특성을 기준으로 적합한 메모리 후보를 먼저 결정한다. **곧 돌아올 세션과 이미 끝난 세션이 후보 형성 단계에서 갈라진다.**
- 이후 `Memory State-aware Refiner`가 Capacity/Load/BW/Endurance로 feasibility를 보정한다. 단 이는 1차 후보가 정해진 뒤의 필터이므로, **자원 상태가 후보 형성 자체에 미치는 영향은 C1보다 간접적**이다.
- **재활성 연산을 후보 형성에 쓸 수 있다는 것이 C2의 고유한 이점**이다. §4의 Attention 오프로드를 고르려면 "이 KV가 다음에 어떤 원시 연산을 받는가"를 알아야 하며, 이 판단은 §5.1의 특성 분석에서만 나온다.
- Next-access Time·Reuse Probability는 §5.2에 따라 추정 대상이므로 분석 비용과 오분류 가능성이 존재한다.

### 장점

- KV 캐시 접근 특성에 적합한 맞춤형 Placement 가능
- 연산 가능 메모리 활용도를 높여 **메모리 B/W 한계 극복** (§3.3의 비대칭을 §4로 활용)

### 단점

- KV 캐시 특성 수집·분석에 따른 관리 및 의사결정 Overhead 증가
- Next-access Time / Reuse Probability 등의 예측·측정 오류에 따른 잘못된 Placement 가능

### 한계가 드러나는 지점

HBM Pressure가 급변할 때, 후보 집합이 이미 데이터 특성으로 고정된 상태에서 Memory State는 그 안에서만 선택할 수 있다. **자원 혼잡 회피의 즉시성이 C1보다 낮다.**

---
## 8. C1 vs C2 핵심 차이

```text
              Same Allocation Request
        (KV block size, KV metadata, op info, ...)
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
        C1 메모리 특성 중심    C2 Data 특성 중심
              │                   │
       Memory 특성이          KV 캐시 특성이
       1차 배치 기준          1차 배치 기준
              │                   │
              │            Memory State-aware
              │              Refiner로 보정
              └─────────┬─────────┘
                        ▼
                 Place / Migrate
```

두 후보 모두 Memory State를 확인할 수 있다. 차이는 **실시간 상태를 볼지 여부가 아니라 어떤 특성이 Placement 후보를 형성하느냐**이다.

### 직교 축: 유휴 중 재조정 (본 DP의 쟁점이 아님)

본 DP의 배치 결정은 비활성 전환이라는 **이벤트에 의해 트리거**된다. 여기에 더해 **유휴 구간 동안 상태 변화에 따라 배치를 다시 조정할 것인가**는 별개의 설계 축이다.

```text
                  전환 시 1회 결정    유휴 중 재조정
memory-first      C1-static          C1-reactive
data-first        C2-static          C2-reactive
```

재조정이 의미를 갖는 경우는 실재한다 — 예상보다 Tool 실행이 길어져 Next-access Time 추정이 빗나갔거나, 다른 세션의 압력으로 계층 상황이 바뀐 경우다. 그러나 두 후보 모두 어느 쪽으로도 구현할 수 있으므로, "동적 자원 변화에 대응 가능한가"를 C1 또는 C2의 고유 장점으로 기술하면 두 변수가 교란되어 후보 비교가 성립하지 않는다.

> **본 DP의 쟁점은 오직 "1차 배치 기준을 Memory 특성으로 둘지 KV 특성으로 둘지"이며, 후보 비교는 동일한 재조정 수준 내에서만 수행한다.**

---

## 9. 장단점

| 구분 | C1. 메모리 특성 중심 | C2. Data 특성 중심 |
|---|---|---|
| 주요 기준 | Capacity / BW / Compute Capability / Load / Endurance Headroom | Next-access Time / Reuse Probability / Expected Remaining Lifetime / Agent Tool Info |
| 장점 1 | 자원 상태 변화에 따른 배치 정책의 동적 적용 용이 | KV 캐시 접근 특성에 적합한 맞춤형 Placement 가능 |
| 장점 2 | KV 캐시 특성 분석이 불필요해 구조 단순, 낮은 의사결정 Overhead | 연산 가능 메모리 활용도를 높여 메모리 B/W 한계 극복 (§3.3 + §4) |
| 장점 3 | 정책 구현·분석·검증이 상대적으로 단순 | Expected Remaining Lifetime으로 왕복 횟수를 예측해 Endurance 소모를 사전 회피 |
| 단점 1 | 데이터별 Access/Lifetime 특성을 반영하지 못해 Placement 최적화에 한계 | KV 캐시 특성 수집·분석에 따른 관리 및 의사결정 Overhead 증가 |
| 단점 2 | 곧 돌아올 KV와 끝난 KV를 구별하지 못함 | Next-access Time / Reuse Probability 등의 예측·측정 오류에 따른 잘못된 Placement 가능 |
| 단점 3 | Operation–Compute Capability 간 적합성 판단에 한계 — §4 오프로드를 고를 근거가 약함 | 잘못된 분류 시 부적절한 계층 선택 및 불필요한 복원/왕복 발생 |

### 핵심 Trade-off

**C1**
> 단순성·자원 상태 반영의 즉시성 ↑ / 재활성 비용 최적화 및 연산형 메모리 활용 ↓

**C2**
> 데이터·연산 특성 기반 최적화 및 연산형 메모리 활용도 ↑ / 분석 복잡도·오분류 Risk ↑

---

## 10. SW Quality Attribute 관점 비교

§6의 설계 쟁점 두 개에 대응하는 QA를 선별한다.

> **아래 등급은 정성적 가설이며 §11의 Metric으로 정량 검증할 대상이다.** 측정 결과가 등급과 다를 수 있으며, 그 경우 측정 결과를 따른다.

| QA | 평가 관점 | 대응 쟁점 | C1 (가설) | C2 (가설) |
|---|---|:---:|:---:|:---:|
| **Performance Efficiency** | 시스템 성능·자원 활용 | 쟁점 1 | ★★☆ | ★★★ |
| **Flexibility** | 신규 Memory/데이터 특성 추가 시 대응 가능성 | 쟁점 2 | ★★☆ | ★★★ |
| **Maintainability** | Placement 정책의 구현·검증·변경 용이성 | — | ★★★ | ★★☆ |

### Performance Efficiency

- C2는 KV 특성과 재활성 연산을 Memory Capability와 직접 매칭할 수 있어, 재활성 비용 절감과 §4 Attention 오프로드 활용에 유리하다.
- 반대로 C2는 특성 분석이 비활성 전환 경로에 추가되므로 **의사결정 Overhead는 불리**하다. 이 QA 안에서 상반된 두 힘이 작용한다.
- C2의 오분류도 결국 이 QA로 나타난다 — 곧 쓰일 KV를 깊이 내리면 재활성 TTFT를 때리고, 끝난 KV를 얕게 두면 수용량을 깎는다.

### Flexibility

- C2는 저장 특성뿐 아니라 KV 및 재활성 연산 특성을 정책에 반영하므로, Compute Capability까지 다변화되는 메모리 환경에서 더 많은 종류를 실제 배치 대상으로 편입할 수 있다.

### Maintainability

- C1은 Memory State → Scoring → Placement 구조로 비교적 단순하다.
- C2는 Characteristic Analyzer → Classifier → Placement Policy → Refiner가 추가되어 정책 및 테스트 복잡도가 높다.

### QA 선정에서 제외한 것 — Functional Correctness

초기 검토에서는 "Placement 결정의 적절성"을 Functional Correctness로 두었으나 **제외한다.**

- 이 DP에서 "틀린 배치"는 모델 출력이 틀리는 것이 아니다. **KV는 어느 메모리에 있든 값이 동일**하며, 배치가 틀려도 결과는 정확하다. 달라지는 것은 **비용뿐**이다.
- 배치 오류의 귀결은 전부 시간·용량 비용으로 나타나므로 §11.2의 Performance Efficiency 지표에 이미 포함된다. 별도 QA로 두면 같은 현상을 두 번 세게 된다.
- 다만 "C1은 추정을 쓰지 않아 오차에 노출되지 않는다"는 구조적 차이는 여전히 후보 비교의 핵심이므로, **Performance Efficiency 안의 민감도 축(M-P8)** 으로 유지한다.

> KV Eviction으로 실제 출력 품질이 달라지는 문제는 **DP3의 쟁점**이며, 그쪽에서는 Accuracy가 Functional Correctness로 정당하게 성립한다. DP1에서는 성립하지 않는다.

---

## 11. QA별 평가 Metric

§10의 등급은 가설이므로 QA마다 **무엇을 재면 그 가설이 검증/반증되는지**를 먼저 고정한다. 실제 수치는 Prototype 실측으로 채우며 **본 문서에 가정값을 기재하지 않는다.**

### 11.1 Metric 선정 요약

| QA | 하위 특성 | Metric | 증거 종류 |
|---|---|---|---|
| **Performance Efficiency** | (종합) | **M-P1 Effective Throughput (Goodput)** — 주 지표 | 측정 |
| | Time Behaviour | M-P2 재활성 TTFT / M-P3 TPOT / M-P4 Offload·Restore·Migration Time / M-P5 Placement Decision Latency | 측정 (**발생 빈도가 달라 각각 측정**) |
| | Resource Utilization | M-P6 HBM KV Footprint & Peak Occupancy / M-P7 Attention 오프로드 채택률 | 측정 |
| | (민감도) | M-P8 추정 오차에 대한 Goodput 민감도 | 측정 (오차 주입) |
| **Flexibility** | Adaptability | **M-F1 지원 가능한 신규 Memory 수** | **실험** |
| **Maintainability** | Analysability·Modifiability·Testability | M-M1 정책 결정 경로 복잡도 / M-M2 신규 Memory 추가 시 변경 지점 수 / M-M3 Tuning Knob 수 / M-M4 결정 분기 커버리지 비용 | **대리 지표** |
| (공통 Risk) | | M-E1 Endurance Pressure | 측정 |

### 11.2 Performance Efficiency

#### 11.2.1 먼저 고정할 것 — 재활성 방식 세 가지

배치 비용을 시간 지표로 환산하려면, **선택한 메모리가 재활성 시 어떤 방식을 강제하는지**를 먼저 구분해야 한다. §3.4의 `gpu_reachable`과 `supported_primitives`에서 유도된다.

```text
Mode A. Resident        GPU가 직접 읽는 메모리에 유지 (HBM, Custom HBM, HBF)
                        → 유휴 중에도 비싼 자리 점유, 재활성 시 복원 0

Mode B. Restore         GPU가 직접 못 읽고 연산도 못 하는 메모리 (DRAM)
                        → 유휴 중 싸게 보관, 재활성 시 History 전량 복원 → TTFT 타격

Mode C. Attention 오프로드   연산 원시집합을 모두 지원하는 메모리 (CXL-PNM, Custom HBM)
                        → KV는 이동하지 않고 Attention을 그곳에서 수행,
                          GPU는 Projection·FFN 담당 (§4)
                        → 링크를 건너는 것은 활성화 텐서뿐
```

세 방식의 선택은 §4.4의 손익분기로 갈리며, 그 부등식의 변수인 **턴당 생성 길이와 유휴 시간**이 §5.1의 추정 대상이다. **이것이 C1/C2 비교의 핵심 연결 고리**다.

#### 11.2.2 비용 항의 발생 빈도 (측정 단위 고정)

| 비용 항 | 언제 발생하는가 | 곱해지는 횟수 | 지표 |
|---|---|---|---|
| Offload Write (하위 계층으로 내림) | **비활성 전환마다 1회** | 전환 횟수 | M-P4 |
| Restore Read (**Mode B**) | **재활성마다 1회, History 전량** | 재활성 횟수 | M-P2, M-P4 |
| 재활성 Attention (**Mode C**) | 재활성마다, 복원 없이 in-place | 재활성 횟수 | M-P2 |
| Prefix Cache Hit 시 복원 | Hit한 Request당 1회 | Hit 수 | M-P2 |
| Decode Attention (**Mode A**) | 매 Decode Step, 해당 메모리에서 | Step 수 | M-P3 |
| Decode Attention (**Mode B** 복원 후) | 매 Decode Step, HBM에서 | Step 수 | M-P3 |
| Decode Attention (**Mode C**) | 매 Decode Step, in-place + 계층당 활성화 왕복 | Step 수 × 계층 수 | M-P3 |
| 유휴 중 재조정 Migration | 재조정 이벤트 발생 시 | 이벤트 수 | M-P4 |
| Placement Decision | **비활성 전환마다 1회** (+ 재조정 시) | 결정 횟수 | M-P5 |

> **활성 Decode 중인 KV의 최초 배치 비용은 이 표에 없다.** §1에서 밝혔듯 이 DP의 결정 대상이 아니며, 모든 정책에 공통이므로 후보 비교에서 상쇄된다.

#### M-P1. Effective Throughput / Goodput (주 지표)

```text
Goodput = SLO를 만족한 Request의 출력 Token 수 / 실행 시간   [tokens/s]

SLO: 재활성 TTFT ≤ T_ttft  AND  TPOT ≤ T_tpot
```

**왜 Throughput을 주 지표로 두는가.**

1. **DP1의 본질이 Capacity ↔ 재활성 비용 교환이기 때문이다.** 비활성 KV를 깊은 계층으로 내리면 HBM이 비어 동시 수용 Request가 늘지만 재활성 비용을 낸다. **Latency 단독 지표는 "전부 HBM에 두라"고만 답하며, 계층을 쓰는 이유 자체를 볼 수 없다.**
2. **세션마다 턴 수·유휴 시간·History 크기가 모두 다르다.** 어느 한 Request의 Latency를 대표값으로 쓰면 워크로드 구성이 결론을 지배한다.
3. **발생 빈도가 다른 비용 항(§11.2.2)을 공통 단위로 합산한다.** 전환당·재활성당·Step당 비용이 각각 몇 번 발생하는지가 실행 안에서 결정되므로, 가중치를 사람이 정하지 않아도 된다.

> **반드시 SLO 제약을 걸어야 한다.** 제약 없는 raw Throughput은 **모든 Request를 느리게 만들고 Batch만 키워도 올라간다.** 그러면 "전부 가장 싼 계층으로 내리기"가 최적해가 되어 지표가 무의미해진다.

**보고 형태:** 단일 수치가 아니라 **Throughput–SLO 곡선**으로 보고한다. **정규화:** As-Is(HBM 우선 유지 + 순차 Spill) = 1.0.

> **Scheduler가 이 지표에 개입한다.** 비교 조건은 **§11.6.1의 Scheduler 고정 규칙**을 따른다.

#### M-P2. 재활성 TTFT

**비활성 KV가 다시 필요해진 시점부터 첫 Token이 나오기까지의 시간.** 이 DP의 배치 결정이 가장 직접적으로 지불하는 대가다.

```text
Mode A → 복원 없음.  재활성 TTFT = Incremental Prefill 연산 시간

Mode B → 복원 있음.  재활성 TTFT = History 전량 복원 시간 (all-or-nothing)
                                  + Incremental Prefill 연산 시간
                     ※ 세션 Block이 여러 계층에 흩어져 있으면
                       가장 느린 계층이 이 항을 지배한다 (§5.2(2))

Mode C → 복원 없음.  재활성 TTFT = in-place Attention 시간 (내부 대역폭 기준)
                                  + 계층당 활성화 왕복 × 계층 수 (§4.3)
```

**측정 구분:** 계기별로 분리 보고한다 — 턴 재개 / Prefix Cache Hit / 선점 재개는 History 크기와 빈도가 다르므로 한 수치로 합치면 해석이 불가능하다.

**보조:** Prefix Cache Hit Rate, Hit / Miss 분리 TTFT, p50 / p99, 최초 Request의 TTFT(배치 결정 이전이므로 **대조군**으로만 사용).

#### M-P3. TPOT

Decode Token 1개당 생성 시간.

```text
Mode A  = 배치 메모리의 외부 대역폭으로 KV 전체 read
Mode B  = HBM 대역폭으로 KV 전체 read (복원 이후)
Mode C  = 배치 메모리의 내부 대역폭으로 KV 전체 read
          + 계층당 활성화 왕복 × 계층 수   ← §4.3, 배치 크기에 반비례
```

**Mode C의 링크 오버헤드를 반드시 분리 계상한다.** §4.3에서 보였듯 이 항은 **배치 크기에 반비례**하므로, 배치 크기를 Sweep 축에 넣지 않으면 오프로드의 이득이 과대 또는 과소 평가된다.

Offload/Restore와 Migration은 **여기에 포함하지 않는다** — Step 단위로 발생하지 않으므로 M-P4로 분리한다.

> **이 지표가 재지 않는 것:** GPU Occupancy와 에너지 항이 없다. Mode C에서 Attention을 메모리로 보내면 GPU 연산 유닛이 비어 다른 일을 할 수 있는데 그 이득이 보이지 않으므로, **연산 가능 메모리에 관한 모든 수치는 이득의 하한**이다. §3.2에서 보였듯 **Custom HBM은 대역폭 이득이 거의 없고 이득이 전적으로 이 항에 있으므로, 이 한계가 특히 크게 작용한다.**

#### M-P4. Offload / Restore / Migration Time

**Step 단위가 아닌 이벤트 단위 비용.**

```text
Offload Time   = Σ over 비활성 전환 (내린 bytes / 유효대역폭 + 지연)
Restore Time   = Σ over 재활성      (복원 bytes / 유효대역폭 + 지연)   ※ Mode B만
Migration Time = Σ over 재조정 이벤트 (이동 bytes / 유효대역폭 + 지연)

보고 시 반드시 함께 낸다:
  - 총 시간 / 이벤트 횟수 / 이벤트당 평균 비용
  - 왕복 횟수 분포 (세션당 offload-restore 반복 수)
```

**왕복 횟수를 함께 보고하지 않으면 해석할 수 없다.** 턴이 많은 세션은 같은 History를 여러 번 내렸다 올리므로, 총 시간이 같아도 "많은 세션이 한 번씩"과 "적은 세션이 여러 번"은 M-E1(Endurance)에 미치는 영향이 전혀 다르다.

재조정을 하지 않는 정적 정책은 Migration Time이 0이므로, **이 지표 단독으로 정책을 평가하면 안 된다.**

#### M-P5. Placement Decision Latency

```text
Decision Cost = 정책 실행 연산 수 또는 CPU 시간 / 결정 건수
```

- C1: Memory State Collector → Tier Scoring → Best Tier Selection
- C2: KV Characteristic Analyzer → KV Classifier → Placement Policy → Memory State-aware Refiner
- **정규화 기준을 As-Is로 둔다.** C1 = 1.0으로 정규화하면 "C1 자신이 As-Is 대비 몇 배인가"가 감춰진다.
- **M-P1에 되먹여 합산한다.** 독립적으로만 보고하면 "C2의 분석 비용이 언제부터 배치 이득을 상쇄하는가"라는 Crossover 질문에 답할 수 없다.
- 활성 Decode의 Critical Path에는 없다는 점이 §1 프레이밍의 귀결이다. **이 여유가 C2의 특성 분석 비용을 감당할 수 있게 만드는 구조적 이유**이므로 결과 해석에 명시한다.

#### M-P6. HBM KV Footprint & Peak Occupancy

```text
HBM KV Footprint          = Step별 HBM에 상주하는 KV bytes (평균 / 최대)
  그 중 유휴 KV 비중       = 접근되지 않으면서 HBM을 점유하는 bytes 비율   ← 핵심
HBM Peak Occupancy        = max(HBM 사용량) / HBM Capacity
Memory Utilization        = §3.1의 6종별 점유 bytes 비중
```

**"유휴 KV가 HBM을 점유하는 비율"이 이 DP의 직접적인 개선 대상**이다. M-P1이 올라간 이유가 "동시 수용량이 늘어서"인지 설명한다. **DP3와 공유하는 지표.**

**보조:** Max Concurrent Sessions / 유효 Batch Size, KV 부족으로 인한 Preemption 발생률.

#### M-P7. Attention 오프로드 채택률

연산 가능 메모리(CXL-PNM / Custom HBM / SSD-PIM)에서 실제로 Attention이 수행된 비율.

```text
오프로드 채택률
= # 재활성/Decode Attention processed in compute-capable memory
  / # 오프로드 가능했던 Attention (원시 연산 집합을 만족하는 메모리가 존재)
```

**메모리별로 나눠 보고한다** — §3.3에서 보였듯 CXL-PNM과 Custom HBM은 오프로드의 이득 구조가 전혀 다르다(전자는 대역폭 절감, 후자는 GPU Occupancy). 합산하면 이 차이가 사라진다.

> **주의 1 — Pool 의존성.** Pool 내에 원시 연산 집합을 만족하는 메모리가 없으면 어느 정책을 쓰든 0이며, 이는 정책의 실패가 아니라 Pool 구성의 귀결이다. §3.4의 구성을 결과와 함께 명시해야 해석 가능하다.
>
> **주의 2 — eligible의 정의.** §4.5에 따라 "GEMV를 지원한다"가 곧 "Attention을 처리할 수 있다"가 아니다. eligible 판정은 **원시 연산 집합을 모두 지원하는가**로 내려야 하며, 그렇지 않으면 이 지표가 과대평가된다.

#### M-P8. 추정 오차에 대한 Goodput 민감도

C2의 특성 추정(§5.1)에 **알려진 크기의 오차를 주입**하고 M-P1에 얼마나 전달되는지 잰다.

```text
증폭률 = (해당 오차에서의 Goodput / 오차 0에서의 Goodput − 1) / 입력 오차
```

- **추정을 사용하지 않는 정책은 증폭률이 정확히 0이다** — 정의상 그렇고 검증 가능하다. C1의 강점은 여기서 수치로 나타난다.
- **오차 축을 특성별로 분리한다.** 셋이 서로 다른 경로로 비용을 만든다.

| 오차 축 | 틀렸을 때 나타나는 곳 |
|---|---|
| **Next-access Time** | Mode A/B 손익분기 오판 → 곧 쓸 KV를 깊이 내려 M-P2 폭증, 또는 안 쓸 KV를 얕게 둬 M-P6 악화 |
| **Reuse Probability** | 연산형 메모리 자리 낭비 → 안 돌아올 세션이 CXL-PNM을 점유해 M-P7 분자는 늘지만 Goodput은 안 오름 |
| **Expected Remaining Lifetime** | §4.4 손익분기 오판 + 저내구성 매체 선택 오판 → M-E1 폭증 |

- **Agent Tool Info의 기여를 분리 측정한다.** Tool Info를 입력에서 제거한 C2 변형을 함께 돌리면, §5.1이 주장한 "Tool Info가 가장 강한 관측 근거"가 수치로 확인되거나 반증된다.
- 무작위 노이즈(ε)와 **계통 편향(bias)** 을 분리한다. 계통 편향은 평균해서 사라지지 않는다.
- **계기별로 나눠 훑는다.** §5.2의 표대로 선점은 추정이 쉽고 Prefix 보존은 어렵다.

**원인 분해용 보조 지표 (독립 QA가 아님).**

| 보조 지표 | 정의 | 주의 |
|---|---|---|
| KV–Memory Matching Rate | 배치된 메모리가 해당 세션의 재접근 시점·연산 요구를 만족하는가 | **절대 기준으로 정의할 것.** "가장 싼 메모리 대비 허용오차 내"로 정의하면 지표가 정책 판단이 아니라 Pool의 희소성을 재게 된다 |
| Mis-placement Rate | 사후 관측된 실제 재접근 이력 기준으로 배치가 틀린 세션 비율 | 세션 수 기준과 바이트 기준 모두 보고 |
| 불필요 Migration 비율 | 이득이 없던 재조정 / **Mis-placement 건수** | 분모를 Migration 건수로 두면 재조정을 안 하는 정적 정책이 "0건 중 0%"로 만점을 받는다 |
| Mode 오판율 | Mode B로 내렸으나 유휴 시간이 짧아 복원 비용을 회수하지 못한 비율 / Mode C에 뒀으나 재활성이 없었던 비율 | §4.4 부등식의 사후 검증 |

### 11.3 Flexibility

#### M-F1. 지원 가능한 신규 Memory 수 (단일 주 지표)

§6의 설계 쟁점 2("신규 메모리 및 데이터 특성 추가 시 변경 범위 최소화")에 직접 대응한다.

```text
Flexibility = # 정책이 실제로 배치에 활용한 신규 Memory 종류
              / # 투입한 신규 Memory 종류
```

**투입 세트는 실행 전에 고정하고 사후에 바꾸지 않는다.** §3.1의 6종에 없던 특성 조합을 N종 준비해 하나씩 Pool에 추가하고, 그 메모리로 **실제 배치가 발생하는지** 관찰한다.

투입 세트 예시 (각각 §3.1 구성이 갖지 못한 조합을 하나씩 대표한다):

| 신규 Memory | 기존 6종에 없던 점 |
|---|---|
| LPDDR 기반 저전력 대용량 | DRAM급 대역폭에 CXL-PNM급 용량, 연산 없음 |
| Softmax까지 지원하는 SSD-PIM | 현재 `ssd_pim`은 `SOFTMAX` 미지원 — 지원 시 Mode C 대상이 되는가 |
| 고내구성 HBF | Endurance Budget이 한 자릿수 큰 변형 — 왕복 매체로 쓸 수 있는가 |
| GPU 직결 CXL (CPU 홉 없음) | §3.2의 두 홉 제약이 사라진 경우 |

**계수 규칙**

| 관찰 | 계수 |
|---|---|
| 해당 메모리에 배치된 bytes = 0 | **미지원.** 존재를 견딘 것이지 적응한 것이 아니다 |
| 배치는 발생했으나 코드 수정이 필요했음 | **미지원.** 필요한 변경 지점 수는 M-M2로 별도 보고 |
| 코드 수정 없이(Configuration 교체만으로) 배치 발생 | **지원** |
| 지원이지만 Goodput이 악화 | **지원으로 계수하되 별도 표기** |

> 마지막 행이 중요하다. **"몇 종류의 새 Memory를 쓸 수 있는가"(Flexibility)와 "그래서 Goodput이 좋아지는가"(Performance Efficiency)는 별개의 질문**이며, 두 값이 같은 방향으로 움직인다고 가정하면 안 된다. M-F1은 **반드시 M-P1과 분리해서 보고**한다.
>
> §3.4의 Configuration이 이 실험의 전제다. 신규 메모리를 **JSON 항목 추가만으로** 투입할 수 있어야 이 실험이 enum 편집이 아니라 **정책의 적응력**을 측정하게 된다.

**보조 관찰:** 새 메모리로 배치된 Block 수·바이트·트래픽 비중, 워크로드 급변 후 배치 재수렴에 걸린 Step 수(재조정 구성 한정).

### 11.4 Maintainability

> **이하 4개는 모두 대리 지표(proxy)다.** 변경 비용과 상관은 있지만 그것을 직접 측정하지 않는다. **논증의 방향으로 읽어야 하고 결론으로 읽으면 안 된다.**

| Metric | 정의 | 무엇을 대리하는가 |
|---|---|---|
| **M-M1** 정책 결정 경로 복잡도 | 결정 경로의 분기·루프 수, 정책 내부 state 수, 정의된 method 수, 유효 LoC | Analysability |
| **M-M2** 신규 Memory 추가 시 변경 지점 수 | 새 메모리 하나를 추가할 때 수정이 필요한 파일/클래스/enum 수 | Modifiability — §6 쟁점 2의 "변경 범위" |
| **M-M3** Tuning Knob 수 | 동작을 바꾸는 정책 파라미터/Threshold 수 | Analysability |
| **M-M4** 결정 분기 커버리지 비용 | 모든 결정 분기를 커버하는 데 필요한 테스트 케이스 수 | Testability |

**대조군으로 As-Is를 함께 측정한다.** C1–C2 간 격차보다 "정책이 있는가 없는가"의 격차가 훨씬 클 가능성이 높고, 그 경우 이 QA에서 의미 있는 대비가 무엇인지가 결과로 드러난다.

M-M2는 §11.3의 M-F1과 짝을 이룬다 — **M-F1은 "쓸 수 있는가"(동적), M-M2는 "쓰게 만드는 데 얼마가 드는가"(정적)** 이다.

### 11.5 공통 Risk 지표

#### M-E1. Write Amplification / Endurance Pressure

```text
Endurance Pressure
= Σ (배치된 KV의 Write Bytes × 해당 메모리의 Write Amplification)
  / 해당 메모리의 Endurance Budget
```

**HBF와 SSD-PIM이 대상이다.** 비활성 전환마다 쓰고 재활성마다 되읽으므로 **왕복 횟수가 세션당 턴 수에 비례해 누적**된다. 턴이 많은 Agent 세션 하나가 짧은 세션 수십 개보다 특정 매체의 수명을 더 소모할 수 있으므로, M-P4의 왕복 횟수 분포와 함께 읽는다.

§3.5에서 밝혔듯 **HBF의 쓰기 대역폭과 Endurance Budget은 가정값**이므로, 이 지표의 절대 수준은 신뢰하지 말고 **정책 간 상대 비교로만** 사용한다.

### 11.6 보고 원칙

단일 수치 비교는 파라미터 선택에 취약하므로, **조건에 따른 곡선과 유효 범위**로 보고한다.

- **정규화 지표 사용** — As-Is(HBM 우선 유지 + 순차 Spill)를 1.0 기준선으로 삼는다.
- **Scheduler를 고정하고 병기한다** — §11.6.1.
- **Sweep 필수** — 후보의 우열이 바뀔 수 있는 파라미터를 범위로 훑고 **교차 지점의 위치**를 Band로 보고한다. 아래 축은 반드시 포함한다.

| Sweep 축 | 왜 필요한가 |
|---|---|
| 특성별 추정 오차 (Next-access Time / Reuse Probability / Remaining Lifetime) | M-P8의 축 |
| **턴당 생성 길이** | §4.4 손익분기(N≈27)가 이 값에 걸려 있다 |
| **유휴 시간 분포 (Tool 실행 시간)** | Mode A/B/C 선택을 직접 좌우 |
| **배치 크기** | §4.3의 계층당 왕복 비용이 배치 크기에 반비례 |
| **Custom HBM 내부/외부 대역폭 비율** | §3.5의 가정값. "Custom HBM에 연산을 보낼 값이 있는가"를 좌우 |
| **HBF 쓰기 대역폭 / Endurance Budget** | §3.5의 가정값. "HBF를 왕복 매체로 쓸 수 있는가"를 좌우 |
| **CXL 링크 세대 (PCIe 5.0 / 6.0 / 7.0)** | §3.2의 비대칭 비율이 17× → 4×로 줄면 Mode C의 이득이 달라진다 |
| Context Length · Concurrency · Profiling 표본율 | 일반 축 |

- **통계적 판정 규칙을 사전 고정** — 동일 seed 쌍으로 반복하고 **신뢰구간이 0을 지나면 "차이 없음"** 으로 판정한다. 점 추정의 부호로 판정하지 않으며 사후에 규칙을 바꾸지 않는다.
- **Memory Configuration 병기** — M-P7과 M-F1은 Pool의 연산 커버리지에 의존하므로, §3.4의 구성을 결과와 함께 명시하지 않으면 시나리오 간 비교가 성립하지 않는다.
- **가정값과 공개값을 구분해 표기** — §3.5의 표를 결과 문서에도 싣는다. 가정값에 의존하는 결론은 그 사실을 함께 적는다.
- **개수 편중 보정** — 모든 비율 지표를 **세션 수 기준과 바이트 기준 양쪽으로** 보고한다.
- **무결성 표시** — Rejection이나 Dropped Migration이 발생한 실행은 **비교 불가**로 표시한다.

#### 11.6.1 Scheduler 고정 규칙

Goodput을 주 지표로 쓰는 이상 **Scheduler가 결과에 개입한다.** 후보 간 차이보다 Scheduler 설정 차이가 더 클 수 있으므로 다음을 지킨다.

**(1) 동일 Scheduler 구성 내에서만 비교한다.** As-Is 기준선을 포함한 모든 정책이 같은 구성을 쓴다. 정책마다 Scheduler를 조정하면 비교가 "누가 Scheduler를 더 잘 튜닝했는지"를 재게 된다.

**(2) 구성을 결과와 함께 명시한다.**

| 항목 | 왜 기록해야 하는가 |
|---|---|
| 최대 동시 시퀀스 수 / Batch Token 예산 | Goodput의 상한을 직접 정하고, §4.3의 왕복 상쇄율을 바꾼다 |
| Preemption 방식 (Recompute / Swap) | **(4) 참조** |
| Chunked Prefill on/off 및 chunk 크기 | 재활성 Prefill이 한 번에 발생하는지 나뉘는지를 바꿔 M-P2를 바꾼다 |
| Scheduling Policy (FCFS / Priority 등) | Request 혼합 순서를 바꿔 유휴 시간 분포를 바꾼다 |
| Prefix Caching on/off | M-P2의 Hit 경로와 공유도의 의미 자체를 바꾼다 |

**(3) Scheduler 설정 하나 이상을 Sweep 축에 넣는다.** 최소한 **동시성 한계(Batch 크기)** 는 훑는다 — §4.3 때문에 이 축은 Mode C의 이득에 직접 영향을 준다. 배치 정책의 우열이 Scheduler 설정에 따라 뒤집힌다면 **그 사실 자체가 결과**이며 §13의 조건부 선정에 들어가야 한다.

**(4) Preemption 방식은 섞지 않는다.** Swap 기반 선점은 쫓겨난 KV를 하위 계층으로 밀어내므로 **배치 정책과 같은 자원·대역폭을 놓고 경쟁**하고 M-P4·M-E1에 직접 기여한다. Recompute 기반은 그 경로가 없는 대신 Prefill 부하로 나타난다. 하나를 고정하고 다른 하나는 별도 조건으로 보고한다.

> **Scheduler를 고정해도 남는 한계:** 결론은 "선택한 Scheduler 구성 위에서" 성립한다. 실제 환경의 Scheduler가 크게 다르면 Goodput 서열이 달라질 수 있으며, 이는 §14에서 확인할 항목이다.

---

## 12. 구현 구조

두 후보의 구현 구조(Module View, Class Diagram, Sequence Diagram)는 분량 관계로 별도 문서에 둔다.

> **[`dp1-implementation-uml.md`](dp1-implementation-uml.md)**

해당 문서는 vLLM v1의 실제 통합 지점 — 비활성 전환 이벤트(`KVCacheManager.free()` / 선점 경로 / `BlockPool.cache_full_blocks()`), 재활성 경로(`get_computed_blocks()`), `kv_offload`의 `OffloadingManager`/`LoadStoreSpec` — 에 정착시켜 다음을 명세한다.

- C1의 `Memory State Collector → Placement Planner → Placement Executor`와 C2의 `KV Characteristic Analyzer → KV Classifier → Placement Policy → Memory State-aware Refiner → Placement Executor`를 클래스로 1:1 대응
- C1/C2가 **동일한 `TierScorer`와 `MemoryStateView`를 공유**하고, 다른 것은 후보 집합 형성 방식뿐임을 구조로 강제
- **C1이 특성 분석 모듈에 의존 간선을 갖지 않음** — M-P8의 증폭률이 C1에서 0인 것이 구현 구조에서 보장된다
- **채점 모듈이 정책을 import하지 않음** — 정책이 자기 답을 채점하면 §11의 Metric이 의미를 잃는다
- §4의 Attention/FFN 분리 실행 경로와 계층당 활성화 왕복
- **결정이 활성 Decode의 Critical Path 밖에 있음** — C2의 분석 비용을 감당 가능하게 만드는 구조적 이유

---

## 13. 후보 선정 (본 문서 범위 밖)

본 문서는 **Design Point의 정의, 대상 메모리 구성, 후보 구조의 제시, 평가 Metric의 명세**까지를 범위로 한다. 후보 선정은 §11의 Metric으로 산출한 정량 Trade-off 분석 결과를 근거로 **별도 문서에서 다룬다.**

이 시점에 어느 후보도 선정하지 않는 이유:

- §10의 QA 등급과 §11의 Metric은 모두 정량 검증 이전의 가설 수준이다.
- 두 후보의 우열은 추정 오차, 유휴 시간 분포와 턴당 생성 길이(§4.4), Memory Pool의 연산 커버리지, CXL 링크 세대 등 **운용 조건에 따라 역전될 수 있다.**
- §3.5의 가정값 두 개(Custom HBM 내부 대역폭, HBF 쓰기 특성)가 결론에 영향을 줄 수 있으므로, 선정 문서는 **그 값이 어느 범위일 때 결론이 유지되는지**를 함께 밝혀야 한다.
- 선정 근거를 먼저 고정하면 이후 측정이 그 결론을 확인하는 방향으로 편향될 위험이 있다.

### 선정 문서가 갖춰야 할 형태

> **조건부 선정 + 유효 범위(Envelope).** "조건 X 범위에서는 C_i, 조건 Y 범위에서는 C_j" 형태로 기술한다. 단일 후보를 무조건 선정하는 서술은 §11.6의 Sweep 결과가 전 구간에서 일관된 경우에만 허용한다.

---

## 14. 향후 검증 항목

§11에서 정의한 Metric 중 다음은 **GPU 실측 또는 실제 하드웨어가 필요**하며 시뮬레이션만으로는 답할 수 없다.

| 항목 | 왜 시뮬레이션으로 부족한가 |
|---|---|
| **Goodput / TTFT / TPOT 실측 (M-P1~M-P3)** | 실제 Attention Kernel, Scheduler, Batching 동작이 필요 |
| **GPU Occupancy** | Attention을 메모리로 보낼 때 GPU 연산 유닛이 비는 이득. **이 항이 없으면 연산 가능 메모리 수치가 전부 하한**이며, 특히 Custom HBM은 이득이 사실상 전부 여기에 있다 (§3.2) |
| **계층당 왕복 지연 실측 (§4.3)** | CXL 두 홉 경로의 실제 round-trip은 2 μs 가정값이다. 이 값이 §4.4 손익분기를 직접 움직인다 |
| **Custom HBM 내부 대역폭 (§3.5 가정값)** | 벤더 스펙 또는 실측 필요. 없으면 "Custom HBM에 연산을 보낼 값이 있는가"에 답할 수 없다 |
| **HBF 쓰기 대역폭·Endurance (§3.5 가정값)** | OCP 규격에 쓰기 측 정량값이 아직 없다 |
| **Decision Latency 되먹임 (M-P5)** | 실제 CPU 시간 측정 필요 |
| **Scheduler 구성 의존성** | §11.6.1로 고정해도 결론은 그 구성 위에서만 성립한다 |
| **Energy** | 메모리별 전력 특성 데이터 필요 |

### DP2 / DP3와의 관계

- **DP2**는 DP1의 배치 결과를 입력으로 받아 **Prefill 실행 위치**를 결정한다. §3.4 Configuration의 메모리별 Access/Transfer Cost가 그대로 DP2 Cost Model의 `C_data` 항이 된다. **§4의 Attention 오프로드가 성립하면 DP2의 선택지도 달라진다** — KV를 옮기지 않고도 원격 Prefill이 가능해지기 때문이다.
- **DP3**와의 경계는 **트리거와 판단 기준**으로 구분한다. 둘 다 KV를 하위 계층으로 보내지만 같은 결정이 아니다.

| | DP1 (본 문서) | DP3 |
|---|---|---|
| **트리거** | **수요 소멸** — 이 KV가 지금 안 쓰인다 | **공급 부족** — HBM이 모자란다 |
| **판단 기준** | **언제 다시 쓰이는가** (Next-access Time / Reuse Probability) | **결과에 얼마나 중요한가** (Attention Importance) |
| **대상 단위** | 세션 단위 Block 집합 (§5.2(2)) | 개별 Token/Block |
| **되돌릴 수 있는가** | 예 — 재활성 시 복원 또는 오프로드 | 손실 가능 — 회수한 KV는 출력 품질에 영향 |

DP1이 유휴 KV를 제때 내려주면 DP3가 발동할 상황 자체가 줄어든다. 반대로 DP1이 실패하면 HBM이 차서 DP3가 **활성 세션의 KV를 중요도 기준으로 깎아야** 한다. **M-P6(유휴 KV 점유 비중)을 공유 지표로 사용**하여 이 관계를 관측한다.

- DP3는 Eviction이 모델 출력 품질을 바꾸므로 Accuracy가 Functional Correctness로 성립하지만, **DP1은 어느 메모리에 두든 KV 값이 동일하므로 성립하지 않는다**(§10).
