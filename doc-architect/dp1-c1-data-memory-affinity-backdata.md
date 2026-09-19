# DP1 C1 보완 설계 Back Data — Data-Memory Affinity Registry

> 목적: **Memory-centric Placement(C1)** 을 최종 후보로 선택한 뒤, 기존 C1의 성능 약점을 **Data-Memory Affinity Registry**로 보완하는 설계 논리를 정성적으로 설명한다.
>
> 이 문서는 정량 benchmark 결과가 아니라 **Architecture rationale / review back-data** 용도다.

---

# 1. 왜 C1을 선택하는가

기본 C1은 Memory Resource State를 중심으로 배치한다.

```text
Capacity / BW / Pressure
        ↓
Resource State Monitor
        ↓
Resource-aware Placement
```

장점은 명확하다.

- Memory Tier별 Resource 상태를 직접 보고 빠르게 대응 가능
- Resource balancing / capacity pressure 대응이 직관적
- Object별 Runtime behavior state를 유지하지 않아 구조와 decision overhead가 낮음
- 운영 및 확장 관점에서 C2보다 단순함

반면 단점도 있다.

> **Resource가 비어 있다는 이유만으로 배치하면, 그 Memory가 해당 AI Data / Operation에 실제로 적합한지는 충분히 반영하지 못한다.**

즉 기존 C1의 성능 약점은 “Resource monitoring이 틀렸다”기보다는, **Resource 상태만으로는 Data와 Memory 사이의 정적인 적합성을 충분히 표현하지 못한다**는 데 있다.

---

# 2. 보완 방향

C1의 Resource-centric 철학은 유지하되, 다음 deterministic knowledge를 추가한다.

```text
Resource State
        +
Data-Memory Affinity Registry
        ↓
Resource-aware Placement
```

Data-Memory Affinity Registry는 Runtime Profiler가 아니다.

다음과 같이 **미리 알 수 있는 정적인 Data↔Memory 적합 관계**를 관리한다.

- Data Type
- Data Size / Mutability
- Read-mostly / Append-heavy
- Required Operation
- Memory Tier의 BW / Latency / Compute Capability
- Operation 수행 시 static execution / transfer cost

따라서 C2의 Hotness / Reuse / Lifetime monitoring을 가져오지 않고도 C1의 명백한 성능 손실을 줄일 수 있다.

---

# 3. 대표적인 Affinity Rule

| AI Data | Deterministic 특성 | Preferred Memory / Path | 기대 효과 |
|---|---|---|---|
| **RAG Vector Index** | Large, read-mostly, Vector Similarity | **SSD-PIM GEMV** | Vector 전체를 GPU로 이동하지 않고 local similarity 수행 |
| **KV Cache** | Decode-critical, appendable | **HBM / Attention-capable Memory** | Decode path의 static cost가 낮은 Tier 선택 |
| **Large / Sealed KV** | Large, read-mostly | HBF / staging tier 후보 | HBM capacity 절감 |
| **MoE Expert** | Large, immutable, read-mostly weight | **HBM → HBF spill** | HBM pressure 완화 + high read BW 활용 |
| **LoRA Adapter** | Read-mostly weight | HBM / HBF / DRAM | Capacity pressure에 따라 적절한 tier 선택 |
| **Agent Memory** | Long-lived, capacity-oriented | DRAM / CXL / HBF | HBM 장기 점유 완화 |
| **Tool Result** | Short/medium lived, read-mostly after creation | DRAM / HBF | HBM 우선순위를 낮춤 |

중요한 점은 이 Rule이 **강제 배치 규칙이 아니라 Affinity Hint**라는 것이다.

```text
Static Affinity
    +
Current / Predicted Resource State
    +
Migration / Execution Cost
        ↓
Final Placement
```

즉 SSD-PIM이 RAG에 적합하더라도 현재 해당 path의 cost가 더 크면 다른 Tier를 선택할 수 있다.

---

# 4. 기존 C1 대비 왜 Performance가 좋아지는가

## 4.1 RAG — 불필요한 Data Movement 제거

기존 Resource-only C1에서는 SSD에 충분한 capacity가 있다는 사실은 알 수 있어도,
**RAG Vector Similarity가 SSD-PIM의 GEMV와 잘 맞는다는 의미**는 직접 표현되지 않는다.

보완 후:

```text
RAG_DATA
+ Vector Similarity
+ SSD-PIM GEMV capability
        ↓
SSD-PIM affinity 증가
        ↓
Vector는 SSD에 유지
        ↓
Local GEMV
        ↓
Similarity score만 Host/GPU로 전송
```

따라서 대규모 Vector 이동을 줄이고 TTFT / Throughput 측면의 손실 가능성을 낮춘다.

---

## 4.2 KV Cache — Resource가 아니라 Execution Path까지 고려

KV Cache는 단순히 “공간이 많은 Memory”로 보내면 안 된다.

보완된 C1은 deterministic하게 다음 path를 비교할 수 있다.

```text
HBM
→ HBM Direct Attention

Custom HBM / CXL-PNM
→ Near-memory Attention

DRAM / HBF
→ Restore to HBM
→ Attention
```

즉 “어디에 공간이 있는가?”만 보지 않고,

> **이 Memory에 KV를 둘 경우 실제 Decode path가 어떻게 되는가?**

를 Static Affinity / Cost로 반영한다.

따라서 Resource pressure 해소를 위해 지나치게 느린 Tier로 KV를 내리는 문제를 줄일 수 있다.

---

## 4.3 MoE Expert — HBF를 의미 있게 사용

MoE Expert는 큰 immutable/read-mostly weight이므로 HBF와 affinity가 높다.

```text
HBM pressure 증가
        ↓
MOE_EXPERT 확인
        ↓
Data-Memory Affinity Registry
        ↓
HBF preferred spill
```

기존 C1처럼 단순히 “빈 Tier”로 보내는 것이 아니라, **Read-intensive Data를 Read BW가 높은 Tier로 내리는 방향**으로 바뀐다.

결과적으로 HBM capacity를 확보하면서도 remote access penalty를 상대적으로 줄일 수 있다.

---

# 5. 보완 전 / 후 Architecture 차이

## Before — Resource-only C1

```text
Telemetry
   ↓
Resource State Monitor
   ↓
Candidate Builder
   ↓
Resource Utility Evaluator
   ↓
Memory Tier Selector
```

주요 판단:

> “어느 Memory가 덜 차 있고 BW 여유가 있는가?”

---

## After — C1 + Data-Memory Affinity

```text
                   Telemetry
                      ↓
             Resource State Monitor
                      ↓
Data Descriptor → Data-Memory Affinity Registry
                      ↓
               Candidate Builder
                      ↓
        Resource Utility + Affinity
                      ↓
              Performance Guard
                      ↓
             Memory Tier Selector
```

주요 판단:

> “어느 Memory Resource가 여유 있는가?”  
> **+ “이 Data / Operation에 어느 Memory가 원래 잘 맞는가?”**

---

# 6. 왜 C2까지 가지 않고 C1을 보완하는가

C2는 object별로 다음 Runtime State를 관리한다.

- Access Rate
- Reuse Interval
- Idle Time
- Lifetime
- Hotness

이 정보는 더 fine-grained한 placement에 유리하지만, object 수에 비례한 state와 monitoring / prediction logic이 필요하다.

반면 C1 + Data-Memory Affinity는:

```text
Memory Resource Runtime State
        +
Static AI Domain Knowledge
```

까지만 사용한다.

따라서:

- C1의 낮은 complexity 유지
- Resource-centric architecture 유지
- 대표적인 AI-specific optimization 확보
- 명백한 wrong-tier placement 감소
- C2 수준의 per-object Runtime characterization은 피함

이라는 절충점이 생긴다.

---

# 7. Review 설명용 핵심 문장

### Q. 왜 기존 C1의 Performance가 낮았나?

> 기존 C1은 Resource Capacity/BW 중심으로 배치했기 때문에, 해당 Memory가 실제 AI Data와 Operation에 적합한지에 대한 정보가 부족했다. 따라서 Resource 관점에서는 합리적이어도 Execution/Transfer cost가 큰 placement가 발생할 수 있었다.

### Q. 무엇을 보완했나?

> Data-Memory Affinity Registry를 추가해 RAG→SSD-PIM, KV→Attention-capable Memory, MoE→HBF와 같이 deterministic하게 알 수 있는 Data↔Memory 적합성을 Placement에 반영했다.

### Q. 왜 Performance가 좋아질 것으로 보는가?

> 기존 C1의 Resource-aware decision은 유지하면서, 명백하게 불리한 Data-Memory 조합을 줄이고 Data-near Compute나 Read-optimized Tier 같은 적합한 path를 선택할 수 있기 때문이다.

### Q. 그러면 C2와 같은 것 아닌가?

> 아니다. C1은 Data Type과 Operation에 대한 **Static Affinity**만 사용하고 object별 Hotness / Reuse / Lifetime은 monitoring하지 않는다. C1의 Runtime intelligence는 여전히 Resource State Monitoring에 있고, C2의 Runtime intelligence는 Data Object Monitoring에 있다.

---

# 8. 결론

C1 선택 후 보완 설계의 핵심은 다음 한 줄로 정리할 수 있다.

> **Resource-centric Placement의 단순성과 Resource 대응 능력은 유지하면서, Data-Memory Affinity Registry를 통해 AI Data/Operation에 명백히 적합한 Memory Path를 반영하여 Performance 약점을 보완한다.**

즉 Architecture Evolution은:

```text
C1
Resource-aware Placement
        ↓
C1+
Resource-aware Placement
+ Deterministic Data-Memory Affinity
```

이며, **C2처럼 Runtime Data Characterization까지 확장하지 않고도 C1의 주요 Performance 약점을 보완하는 설계**다.

---

# 9. 현재 단계의 Evidence Level

현재 문서는 **정성적 Architecture Back-data**다.

따라서 Review 시에는 다음처럼 표현하는 것이 안전하다.

> “Data-Memory Affinity Registry를 통해 성능 저하를 유발할 수 있는 대표적인 wrong-tier placement를 제거하도록 설계했다.”

현재 단계에서 다음 표현은 정량 실험 없이 사용하지 않는다.

- “Throughput이 X% 향상된다.”
- “TTFT가 X% 감소한다.”
- “TPOT이 X% 감소한다.”

정량 근거가 필요하면 이후 최소 대표 Scenario만 별도로 구성해 Before/After C1을 비교하면 된다.
