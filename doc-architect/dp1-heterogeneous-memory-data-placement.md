# DP1. 이기종 메모리 기반 데이터 배치 구조

## 1. Design Point 개요

### 목적
AI 추론 시스템 내에서 HBM, DRAM, CXL Memory, Custom HBM, HBF, SSD-PIM 등 서로 다른 저장/연산 특성을 가진 메모리가 혼재할 때, 데이터의 배치 및 이동을 어떤 기준으로 결정할 것인지 설계한다.

### 핵심 설계 질문
> **메모리 및 데이터의 어떤 특성을 기반으로 배치·이동을 결정할 것인가?**

---

## 2. 문제 정의

1. AI 워크로드의 메모리 병목 심화에 따라 다양한 메모리 솔루션이 등장하고 있다.
   - CXL Memory
   - Custom HBM
   - HBF
   - PIM/PNM 계열 메모리 등

2. 메모리 병목 해소를 위해 단일 시스템 내 용량, 대역폭, 지연시간 등 특성이 상이한 이기종 메모리가 혼재할 수 있으며, 일부 메모리는 데이터 저장뿐 아니라 **연산 기능(Compute Capability)**까지 제공한다.

3. 또한 일부 메모리는 **Read/Write 비대칭성**과 **유한한 Write Endurance**를 갖는다. HBF, SSD-PIM 등은 Write 비용이 Read 대비 현저히 높고, 누적 Write 량이 소자 수명을 제한한다. 따라서 Capacity / BW / Latency만으로 배치 적합성을 판단하면, Write 집약적 데이터를 내구성이 낮은 메모리에 배치하여 성능 저하와 수명 소모를 동시에 유발할 수 있다.

4. 기존 HBM–DRAM–SSD 구조에서는 GPU 연산 대상 데이터가 최종적으로 HBM에 위치해야 하는 경우가 많아 **HBM 우선 할당**과 같은 단순한 배치 정책이 합리적이었다. 그러나 연산 기능을 포함해 역할이 서로 다른 메모리가 추가되면, 단순히 GPU에 가까운 메모리를 우선하는 방식만으로는 각 자원의 특성을 충분히 활용하기 어렵다.

### As-Is
**메모리 특성을 고려하지 않은 단순 정책 (HBM 우선 할당)**  
→ 신규 메모리 도입 시 시스템 성능 저하 및 비효율적 자원 사용 발생

### To-Be
**메모리·데이터 특성 및 연산 기능을 고려한 배치·이동 정책**  
→ 신규 메모리의 저장·연산 특성을 활용하여 시스템 성능 및 자원 활용도 향상

---

## 3. 설계 쟁점

- 메모리별 상이한 특성을 고려한 **데이터 배치·이동 의사결정 기준 설계 필요**

> **메모리 및 데이터의 어떤 특성을 기반으로 배치·이동을 결정할 것인가?**

본 DP의 핵심은 Allocation Request 자체의 차이가 아니라, 동일한 요청 정보 중 **어떤 정보를 Placement의 1차 기준으로 삼는가**에 있다.

공통 Allocation Request 예시:

```text
Allocation Request
(size, data info, op info, ...)
```

---

## 4. 후보 구조

## Candidate 1. Memory-centric Placement

### 한 줄 정의
> **메모리 특성(Capacity / BW / Compute Capability / Load / Write Endurance)을 기준으로 배치**

### 구조

```text
Allocation Request
(size, data info, op info, ...)
        |
        v
Memory State / Capability
- Available Capacity
- Bandwidth / Latency
- Compute Capability
- Current Load
- Write Cost / Endurance Headroom
        |
        v
Tier Scoring / Selection
        |
        v
Placement / Migration
        |
        v
HBM / DRAM / CXL Memory / Custom HBM / HBF / SSD-PIM
```

### 특징
- 메모리의 현재 상태 및 Capability가 Placement의 1차 의사결정 기준이다.
- Capacity, BW, Load 등의 변화에 따라 배치 정책을 동적으로 변경하기 쉽다.
- 데이터의 세부 특성을 별도로 분류하지 않아 구조가 상대적으로 단순하다.
- Operation 정보는 실행 가능성 확인 등에 사용할 수 있으나, 데이터 특성이 Placement의 주 기준은 아니다.
- Write Endurance Headroom은 관측 가능한 Memory State이므로 직접 반영할 수 있다. 다만 데이터별 Write 집약도를 분류하지 않으므로, 어떤 데이터가 내구성을 소모할지는 사전에 판단하기 어렵다.

---

## Candidate 2. Data-centric Placement

### 한 줄 정의
> **데이터 특성(Access Pattern / Hotness / Lifetime / Operation / Write Intensity)을 기준으로 배치**

### 구조

```text
Allocation Request
(size, data info, op info, ...)
        |
        v
Data Profiling / Classification
- Access Pattern
- Hotness
- Lifetime
- Operation
- Write Intensity
        |
        v
Candidate Tier / Preferred Tier
        |
        v
Memory State Check
- Available Capacity
- Load
- BW / Latency
- Capability
- Write Cost / Endurance Headroom
        |
        v
Final Placement / Migration
        |
        v
HBM / DRAM / CXL Memory / Custom HBM / HBF / SSD-PIM
```

### 특징
- Data 특성을 기준으로 적합한 메모리 후보를 먼저 결정한다.
- 이후 실제 배치 시 Available Capacity, Load 등의 Memory State를 확인하여 feasibility를 보정한다. 단 이는 1차 후보가 정해진 뒤의 필터이므로, 자원 상태가 후보 형성 자체에 미치는 영향은 C1보다 간접적이다.
- Operation과 Memory Compute Capability 간 매칭이 가능해 연산 기능을 가진 메모리 활용에 유리하다.
- Hotness/Lifetime 등의 정보는 관측 또는 예측이 필요하므로 Profiling/Classification 비용과 오분류 가능성이 존재한다.
- Write Intensity를 분류에 포함하면 Write 집약 데이터를 저내구성 메모리에서 회피할 수 있다. 다만 Write 집약도 역시 추정 대상이므로, 오분류는 성능 저하뿐 아니라 수명 소모로 직결된다.

---

## 5. C1 vs C2 핵심 차이

```text
                Same Allocation Request
             (size, data info, op info, ...)
                        |
              +---------+---------+
              |                   |
              v                   v
       C1 Memory-centric     C2 Data-centric
              |                   |
       Memory 특성이          Data 특성이
       1차 배치 기준          1차 배치 기준
              |                   |
              |             Memory State로
              |              최종 feasibility
              |                / 보정 확인
              +---------+---------+
                        |
                        v
                 Placement / Migration
```

즉, 두 후보 모두 Memory State를 확인할 수 있다. 차이는 **실시간 상태를 볼지 여부가 아니라 어떤 특성을 우선하여 Placement 후보를 형성하느냐**이다.

---

## 6. 장단점

| 구분 | C1. Memory-centric | C2. Data-centric |
|---|---|---|
| 주요 기준 | Capacity / BW / Compute Capability / Load / Write Endurance Headroom | Access Pattern / Hotness / Lifetime / Operation / Write Intensity |
| 장점 1 | 자원 혼잡·포화가 후보 형성 단계에서 직접 반영되므로 과부하 회피가 즉각적 | 데이터 특성에 적합한 맞춤형 Placement 가능 |
| 장점 2 | 데이터 Profiling/Classification이 불필요하여 구조 및 의사결정 단순 | Operation–Compute Capability 매칭을 통해 연산형 메모리 활용에 유리 |
| 장점 3 | 정책 구현/분석/검증이 상대적으로 단순 | 장기적인 Access/Lifetime 특성을 고려한 Placement 최적화 가능 |
| 단점 1 | Data 요구 특성을 직접 반영하지 않아 Placement Quality 한계 | Data 특성 수집·분석 및 Classification Overhead 발생 |
| 단점 2 | 미래 Access/Lifetime을 반영하기 어려움 | Hotness/Lifetime 등의 예측·분류 오류 가능 |
| 단점 3 | 어떤 Data/Operation이 Compute-capable Memory에 적합한지 판단에 한계 | 잘못된 분류 시 부적절한 Tier 선택 및 불필요한 Migration 가능 |

### 핵심 Trade-off

**C1**  
> 단순성·자원 상태 반영의 즉시성 ↑ / 데이터별 Placement 최적화 수준 ↓

**C2**  
> 데이터·연산 특성 기반 Placement 최적화 및 연산형 메모리 활용도 ↑ / 분석 복잡도·오분류 Risk ↑

### 직교 축: Reactivity (본 DP의 쟁점이 아님)

**정적 배치(1회 결정 후 유지) vs 반응적 재배치(상태 변화에 따라 Migration)** 는 본 DP의 쟁점과 **직교하는 별개 설계 축**이다.

```text
              static            reactive
memory-first  C1-static         C1-reactive
data-first    C2-static         C2-reactive
```

두 후보 모두 static/reactive 어느 쪽으로도 구현할 수 있다. 따라서 "동적 자원 변화에 대응 가능한가"를 C1 또는 C2의 고유 장점으로 기술하면 두 변수가 교란되어 후보 비교가 성립하지 않는다.

> **본 DP의 쟁점은 오직 "1차 배치 기준을 Memory 특성으로 둘지 Data 특성으로 둘지"이며, 후보 비교는 동일한 Reactivity 수준 내에서만 수행한다.**

---

## 7. SW Quality Attribute 관점 비교

DP 후보 구조의 차이를 설명하는 데 직접적인 QA만 선별한다.

> **아래 등급은 정성적 가설이며 정량 검증 대상이다.** §8의 방법으로 측정한 결과가 등급과 다를 수 있으며, 그 경우 측정 결과를 따른다.

| QA | 평가 관점 | C1 (가설) | C2 (가설) |
|---|---|:---:|:---:|
| **Functional Correctness** | 입력 정보 및 예측 오차가 존재할 때 적절한 Placement를 결정할 수 있는가 | ★★★ | ★★☆ |
| **Performance Efficiency** | Data/Operation 특성에 적합한 메모리 배치로 성능 및 자원 활용을 높일 수 있는가 | ★★☆ | ★★★ |
| **Maintainability** | Placement 정책의 구현·분석·검증·변경이 용이한가 | ★★★ | ★★☆ |
| **Flexibility** | 새로운 Memory/Data/Operation 특성에 대응 가능한가 | ★★☆ | ★★★ |

### Functional Correctness
- C1은 Capacity/Load 등 현재 관측 가능한 Memory State 중심으로 결정하므로 예측 정보 의존도가 낮다.
- C2는 Hotness/Lifetime 등 일부 Data 특성이 추정값일 수 있어 오분류가 Placement 오류로 연결될 가능성이 있다.
- 이는 Fault Tolerance 관점의 Reliability보다 **의도한 Placement 판단을 얼마나 정확히 수행하는지**에 해당하므로 Functional Correctness로 평가한다.

### Performance Efficiency
- C2는 Data Access 특성과 Operation을 Memory Capability와 직접 매칭할 수 있어 적합한 Placement 및 Compute-capable Memory 활용에 유리하다.

### Maintainability
- C1은 Memory State → Scoring → Placement 구조로 비교적 단순하다.
- C2는 Profiling → Classification → Tier Mapping → Memory State Check가 추가되어 정책 및 테스트 복잡도가 높다.

### Flexibility
- C2는 저장 특성뿐 아니라 Data 및 Operation 특성을 정책에 반영할 수 있어, Compute Capability까지 다변화되는 차세대 메모리 환경에 유리하다.

---

## 8. 정량 Trade-off 평가 방법

실제 구현 전 단계에서는 실측 성능값이 아니라 **동일한 가정과 Cost Model을 기반으로 후보를 비교**한다.

### 평가 시나리오 예시

```text
1,000 Data Objects

Memory Pool
- HBM
- DRAM
- CXL Memory
- Custom HBM / PIM
- HBF
- SSD-PIM

Workload
- Hot / Warm / Cold 혼재
- Lifetime 상이
- GPU / PIM 적합 Operation 혼재
- Read-only / Write 집약 데이터 혼재
```

### 비교 항목

측정할 Metric은 아래와 같다. **수치는 Prototype 실측으로 채우며 본 문서에 가정값을 기재하지 않는다.**

| Metric | C1 | C2 |
|---|---:|---:|
| Placement Decision Cost | 측정 | 측정 |
| Data–Memory Matching Rate | 측정 | 측정 |
| Compute-capable Memory 활용률 | 측정 | 측정 |
| Mis-placement 대비 불필요 Migration 비율 | 측정 | 측정 |
| Endurance Pressure | 측정 | 측정 |
| Prediction Dependency | 측정 | 측정 |

### 보고 원칙

단일 수치 비교는 파라미터 선택에 취약하므로, **조건에 따른 곡선과 유효 범위**로 보고한다.

- **정규화 지표 사용** — As-Is(HBM 우선 할당)를 기준선으로, 이상적 하한(미래 접근을 모두 아는 배치)까지의 구간에서 각 후보의 위치를 정규화해 표현한다. 절대 시간값의 스케일 의존성을 제거한다.
- **Sweep 필수** — Classification 오차율, 자원 상태 변동 주기, Write 집약도 등 후보의 우열이 바뀔 수 있는 파라미터를 범위로 훑고, **교차 지점의 위치**를 결과로 보고한다.
- **통계적 판정 규칙을 사전 고정** — 동일 seed 쌍으로 반복하고 신뢰구간이 겹치면 "차이 없음"으로 판정한다. 사후에 규칙을 바꾸지 않는다.
- **Cost Model 민감도 명시** — 대역폭 혼잡 계수, Latency 가중치 등을 함께 훑어 **결론의 부호가 안정한 구간에서만** 주장한다.
- **개수 편중 보정** — 구성 요소별 객체 수가 수 자릿수 차이 나므로(예: Weight Tensor 대 KV Block) 모든 비율 지표를 **개수 기준과 바이트 기준 양쪽으로** 보고한다.

### Metric 정의

#### Placement Decision Cost
Placement 요청 1건을 처리하기 위한 정책 실행 비용을 C1 = 1.0으로 normalize한다.

- C1: Memory State Read → Tier Scoring → Placement
- C2: Data Profiling/Classification → Candidate Tier → Memory State Check → Placement

#### Data–Memory Matching Rate
데이터의 BW/Latency/Operation 요구 특성과 실제 배치된 Memory Capability가 일치한 비율.

```text
Matching Rate = # Requirement-compatible placements / # Total placements
```

#### Compute-capable Memory 활용률
PIM/PNM 등 Memory-side Compute에서 처리 가능한 Operation 중 실제 해당 자원으로 배치되어 처리된 비율.

```text
Compute Memory Utilization
= # Operations assigned to compatible compute-memory
  / # Operations eligible for compute-memory
```

#### 불필요 Migration 비율
Mis-placement 대비, 결과적으로 교정에 기여하지 못한 Migration의 비율.

```text
불필요 Migration 비율 = # 이득이 없던 Migration / # Mis-placement
```

> **주의:** 분모를 Migration 건수로 두면 재배치를 아예 수행하지 않는 정적 정책이 "0건 중 0%"로 최고점을 받는 왜곡이 발생한다. 분모는 Mis-placement 건수여야 한다.

#### Prediction Dependency
Placement 결정이 Hotness/Lifetime/Future Access와 같은 예측 또는 분류 결과에 얼마나 의존하는지를 나타낸다.

#### Write Amplification / Endurance Pressure
Write 비용이 높고 내구성이 유한한 메모리(HBF, SSD-PIM 등)에 Write 집약 데이터가 배치된 정도를 나타낸다. Read 중심 지표만으로는 드러나지 않는 배치 오류를 포착한다.

```text
Endurance Pressure
= Σ (배치된 데이터의 Write Bytes × 해당 메모리의 Write Amplification)
  / 해당 메모리의 Endurance Budget
```

Write 집약 데이터를 저내구성 메모리에 배치하면 즉각적인 성능 저하와 장기적인 수명 소모가 동시에 발생하므로, Access Latency 계열 지표와 **별도로** 측정한다.

---

## 9. 후보 선정 (본 문서 범위 밖)

본 문서는 **Design Point의 정의와 후보 구조의 제시**까지를 범위로 한다. 후보 선정은 §8의 방법으로 산출한 정량 Trade-off 분석 결과를 근거로 **별도 문서에서 다룬다.**

이 시점에 어느 후보도 선정하지 않는 이유:

- §7의 QA 등급과 §8의 Metric은 모두 정량 검증 이전의 가설 수준이다.
- 두 후보의 우열은 Classification 오차율, 자원 상태 변동 주기, Workload의 Write 집약도 등 **운용 조건에 따라 역전될 수 있다.** 따라서 선정은 단일 결론이 아니라 적용 조건이 명시된 형태여야 한다.
- 선정 근거를 먼저 고정하면 이후 측정이 그 결론을 확인하는 방향으로 편향될 위험이 있다.

### 선정 문서가 갖춰야 할 형태

> **조건부 선정 + 유효 범위(Envelope).** "조건 X 범위에서는 C_i, 조건 Y 범위에서는 C_j" 형태로 기술한다. 단일 후보를 무조건 선정하는 서술은 §8의 Sweep 결과가 전 구간에서 일관된 경우에만 허용한다.

---

## 10. 향후 검증 항목

Prototype 구현 후 아래 Metric을 실제 workload에서 측정한다.

> **측정 결과:** [`dp1-prototype-results.md`](dp1-prototype-results.md).
> 아래 항목 중 Placement Decision Latency, Data–Memory Matching Rate,
> Compute-capable Memory Utilization, Data Migration Traffic / Count,
> HBM Pressure, Data Classification Accuracy, Mis-placement Rate는 측정 완료.
> End-to-End Throughput / Latency와 Endurance Pressure는 GPU 실측 또는
> Write 집약 시나리오 확장이 필요하다.
>
> 측정 과정에서 §8의 Metric 정의 두 개(Matching Rate, 불필요 Migration 비율)에
> 결함이 발견되어 수정했으며, 아래 항목에 **GPU Occupancy**를 추가해야 한다는
> 결론이 나왔다 — 본 Prototype의 Cost Model에는 이 항이 없어 Compute-capable
> Memory에 관한 모든 결과가 이득의 하한이다.

- Placement Decision Latency
- Data–Memory Matching Rate
- Memory Tier Utilization
- Compute-capable Memory Utilization
- Data Migration Traffic / Count
- HBM Pressure / Peak Usage
- End-to-End Throughput / Latency
- Data Classification Accuracy
- Mis-placement / Re-placement Rate
- Write Traffic per Memory Tier
- Endurance Pressure (저내구성 메모리의 Write 소모율)

