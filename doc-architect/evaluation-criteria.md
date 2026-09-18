# 평가 기준 (DP1 · DP2 · DP3 · DP4 공통)

> **DP1~DP4가 같은 QA를 같은 기준으로 매기기 위한 문서다.** 후보 비교 문서(`dp*-…-results.md`)는 여기서 정의한 Reference Configuration과 별점 기준만 인용하고, 자체 기준을 만들지 않는다.
>
> 최종 별점 QA는 네 가지로 고정한다: **Performance Throughput / Performance Latency / Resource Utilization / Modifiability**. 아래의 이동 바이트·에너지·Flexibility 등은 원인 분석을 위한 보조 metric이며 별도의 최종 QA 별점을 만들지 않는다.

---

## 1. Reference Configuration

모든 절대 수치의 기준점이다. 이 값을 바꾸면 §3의 별점 임계값을 다시 계산해야 한다.

### 1.1 하드웨어

**단위는 scale-up 도메인 하나다.** 도메인을 넘는 배치는 DP2의 범위이므로 여기서는 도메인 수만 기록하고 모델링하지 않는다.

| 클러스터 | 도메인 구성 | 도메인 HBM | 도메인 대역폭 | 도메인 TDP | 도메인 수 |
|---|---|---:|---:|---:|---:|
| `b200_8gpu` **(기준)** | 8× B200 | 1.50 TiB | 64 TB/s | 8.0 kW | 1 |
| `vera_rubin_8gpu` | 8× Vera Rubin | 3.072 TB (≈2.79 TiB) | 224 TB/s | 18.4 kW | 1 |

> 클러스터 이름과 값은 `configs/clusters.json`을 source of truth로 사용한다. 문서에만 존재하고 Config에 없는 가상 cluster 이름을 QA 기준으로 사용하지 않는다.

### 1.2 메모리 계층과 토폴로지

```
        ┌──────────────────────────────┐
        │  GPU 도메인 (8× B200)         │
        │  HBM 1.50 TiB @ 64 TB/s      │  ← GPU 직접 읽기
        └───────────┬──────────────────┘
                    │ PCIe5
        ┌───────────┴──────────────────┐
        │  CPU / Host                  │
        └───────────┬──────────────────┘
                    │ PCIe5 x16 = 63.0 GB/s   ← 도메인 전체가 공유
        ┌───────────┴──────────────────┐
        │  Custom HBM 노드 × 1          │  ← GPU 직접 읽기 불가
        │  384 GiB, 내부 16 TB/s        │
        │  450 TFLOPS(FP16), 333 W     │
        └──────────────────────────────┘
```

| 메모리 | 용량 | 외부 BW | 내부 BW | 연산 | TDP | provenance |
|---|---:|---:|---:|---:|---:|---|
| `hbm` | 1.50 TiB/domain | 64 TB/s/domain | 64 TB/s/domain | GPU | GPU 포함 | `clusters.json`의 8×B200 집계 |
| `custom_hbm` | 384 GiB | **63.0 GB/s** | **16 TB/s** | 450 TF FP16 | 333 W | `memories_default.json` B200-paired default |
| `cxl_pnm` | 512 GiB | 63.0 GB/s | **400 GB/s** | 3.28 TF FP16 | 150 W | `memories_default.json` |
| `dram` | 1.00 TiB | 64.0 GB/s | 400 GB/s | — | 50 W | `memories_default.json` |
| `hbf` | 2.00 TiB | 1.0 TB/s | 1.0 TB/s | — | 100 W | `memories_default.json` |
| `ssd_pim` | 16.00 TiB | 16.0 GB/s | 200 GB/s | 2.0 TF FP16 | 75 W | `memories_default.json` |

> DP1~DP4 실험의 Memory source of truth는 `configs/memories_default.json`이다. Rubin 환경을 평가할 때만 cluster pairing rule에 따라 별도 sweep으로 값을 바꾼다.

> **링크 스펙 유도** — PCIe 5.0 x16 = 32 GT/s × 16 × (128/130) ÷ 8 = **63.0 GB/s** 단방향. PCIe 6.0 x16 = 64 GT/s × 16 × (242/256) ÷ 8 = **121.0 GB/s** (`configs/memories_pcie6.json`).
>
> **Custom HBM은 GPU가 직접 읽지 못한다.** CPU를 2홉 경유하므로 Mode A(GPU 직접 읽기)가 성립하지 않고, 재활성 경로는 Mode C(Attention 오프로드)뿐이며 오프로드가 불가하면 Mode B(전량 복원)로 떨어진다.
>
> **cHBM은 도메인당 1대다.** HBM은 GPU 수만큼 합산되지만(64 TB/s) 기본 B200-paired cHBM은 1대(16 TB/s)다. 따라서 **오프로드의 이득은 대역폭이 아니라 (a) 용량 확장과 (b) GPU를 Attention에서 놓아주는 자원 병렬화에서 나온다.**

### 1.3 모델

| 모델 | attention | 층 | KV/token | 활성 파라미터 | 연산 강도 | decode 읽기 @128K |
|---|---|---:|---:|---:|---:|---:|
| `llama_3_1_70b` **(기준)** | GQA 64:8 | 80 | 320.00 KB | 70.6 B | 8.0 | 40,960 MiB |
| `llama_4_maverick` | GQA 40:8 | 48 | 192.00 KB | 17.0 B | 5.0 | 24,576 MiB |
| `glm_5` | MLA+DSA | 78 | 107.25 KB | **TODO** | 93.1 | **214 MiB** (topk 2048) |

KV 공식:
- **GQA** — `2 × 층 × kv_heads × head_dim × dtype`
- **MLA+DSA** — `층 × (kv_lora_rank + qk_rope) × dtype + 층 × index_head_dim × dtype`, decode는 top-k만 읽는다

> ⚠️ **GLM-5의 활성 파라미터 수가 미확정**이다. 가중치 읽기 항이 0이 되어 **GPU가 실제보다 한가해 보이고 TPS가 과대평가**된다. 확정 전까지 GLM-5의 절대 수치를 인용하면 안 된다.

### 1.4 부하 정의

**부하 = 명시적 Batch/Concurrency × Context Length**를 기본 좌표로 한다. 도착률만 올려 large-batch를 대체하지 않는다.

```
BATCH / CONCURRENCY = [1, 16, 64, 256]
CONTEXT             = [16K, 32K, 128K, 512K]
```

일반 sweep은 전체 grid를 사용하고, 최종 heavy-load throughput score는 **batch 64/256 × context 128K/512K**를 사용한다. RAG처럼 LLM decode batch와 의미가 다른 workload는 동일한 숫자를 **concurrent queries**로 해석하고 index size를 별도 축으로 기록한다.

### 1.5 SLO

| 항목 | 값 | 근거 |
|---|---|---|
| TTFT | ≤ 2,000 ms | 대화형 에이전트의 체감 한계 |
| TPOT | ≤ 50 ms | 20 tok/s ≈ 사람의 읽기 속도 |

---

## 2. Analytical GPU-only Reference — sanity check only

아래 수치는 **GPU-only / HBM-resident 경로를 단순화한 분석값**이다. 실측 peak도 아니고, DP1~DP4 후보의 성능 상한도 아니다.

특히 Custom HBM / CXL-PNM / SSD-PIM처럼 별도 연산 자원이 병렬로 동작하면 GPU-only reference를 넘는 system goodput도 가능하므로, **이 값을 QA 별점의 분모나 ceiling으로 사용하지 않는다.** 용도는 모델식 sanity check와 단위 검증뿐이다.

```
TTFT = Attention prefill + FFN prefill                       (GPU 고정)
TPOT = 가중치 읽기(배치 공유) + Attention(세션별, 배치만큼 직렬)
TPS  = 배치 ÷ TPOT
```

**128K context 기준:**

| 클러스터 | 모델 | batch | TTFT | TPOT | TPS | KV 총량 |
|---|---|---:|---:|---:|---:|---:|
| **B200 ×8** | **Llama 3.1 70B** | **16** | **7,060 ms** | **14.38 ms** | **1,113** | 640 GiB |
| B200 ×8 | Llama 3.1 70B | 64 | 7,060 | 50.17 | 1,276 | 2,560 GiB |
| B200 ×8 | Llama 4 Maverick | 16 | 2,372 | 7.75 | 2,065 | 384 GiB |
| B200 ×8 | GLM-5 ⚠️ | 16 | 305 | 4.00 | 4,001 | 214 GiB |
| NVL72 | Llama 3.1 70B | 16 | 784 | 1.60 | 10,013 | 640 GiB |
| Rubin ×8 | Llama 3.1 70B | 16 | 1,908 | 4.11 | 3,894 | 640 GiB |

**기준 셀(굵게)**: `B200 ×8 / Llama 3.1 70B / batch 16 / 128K` → **TPS 1,113 · TTFT 7,060 ms · TPOT 14.38 ms**

> TTFT 7,060 ms는 §1.5의 SLO(2,000 ms)를 이미 3.5배 넘긴다. **128K를 한 번에 prefill하는 것이 물리적으로 SLO 안에 안 들어간다**는 뜻이며, Chunked Prefill이나 Prefix Caching 없이는 이 셀이 성립하지 않는다. 별점 기준은 이 사실 위에서 세운다.

---

## 3. QA별 별점 기준

배수와 절대 수치를 함께 적는다. 배수는 §2의 Reference Performance 대비다.

### 3.1 Performance — Throughput / SLO-constrained Goodput

Throughput QA는 analytical physical reference 대비 비율로 매기지 않는다. **같은 HW / 같은 trace / 같은 workload에서의 As-Is baseline**과 비교한다.

주 지표는 다음 두 개를 함께 기록한다.

- Raw Token Throughput [tok/s]
- **Max Sustainable SLO Goodput [tok/s]** — 동일 workload cell에서 offered load를 sweep하고, First-response와 TPOT SLO를 만족하면서 얻은 최대 Goodput

각 `(batch, context, workload)` cell에서 다음 load sweep을 수행한다.

```
OFFERED_LOAD_SCALE = [0.25, 0.50, 0.75, 1.00, 1.25]
Sustainable(load) =
  (TTFT_p99(load) <= 2,000 ms)
  AND
  (TPOT_p99(load) <= 50 ms)

Max Sustainable SLO Goodput =
  max(SLO goodput at load)
  over Sustainable(load) == true
```

공통 score는 **SLO-feasible heavy cell**에서 As-Is 대비 ratio를 사용한다.

```
Goodput Ratio =
  Candidate Max Sustainable SLO Goodput
  / As-Is Max Sustainable SLO Goodput
```

**Request 일부가 SLO를 만족했다는 이유만으로 그 load point를 sustainable로 인정하지 않는다.** 해당 load point의 전체 요청 기준 p99 TTFT와 p99 TPOT이 둘 다 SLO를 만족해야 한다.

기본 heavy/stress 축은 large batch와 long context를 모두 포함하지만, As-Is와 모든 후보에서 위 p99 조건을 만족하는 load point가 하나도 없는 cell은 **SLO-infeasible stress cell**로 표시하고 Throughput 별점 분모에서는 제외한다. 예를 들어 512K context가 물리적으로 TPOT SLO를 넘는다면 그 cell은 Latency/Stress 분석에는 남기되 throughput ratio를 0/0으로 만들지 않는다.

| 별점 | 공통 정량 기준 | 의미 |
|---|---|---|
| ★☆☆ | feasible-cell geometric-mean ratio < 0.90 **and** paired 95% CI upper < 1.0 | baseline보다 유의하게 악화 |
| ★★☆ | 0.90 ~ 1.10 또는 paired CI가 1.0을 포함 | baseline과 유사 / trade-off 구간 |
| ★★★ | ratio ≥ 1.10 **and** paired 95% CI lower ≥ 1.0 | heavy load에서 10% 이상 유의한 goodput 개선 |

> 1.10/0.90은 “이론 peak의 몇 %”가 아니라 **같은 시스템의 As-Is 대비 최소 의미 있는 개선/회귀 폭 10%**다. Large-batch/Long-context stress 결과는 ratio 별점과 별개로 raw throughput, TTFT, TPOT을 반드시 같이 보고한다.

### 3.2 Performance — First-response Latency p99 (TTFB / TTFT)

First-response latency와 TPOT은 원인이 다르므로 **절대 하나의 숫자나 min/max 연산으로 합치지 않는다.**

- Serving interface까지 network / HTTP framing을 모델링하면 **TTFB**
- Model/runtime ready-to-first-token까지만 모델링하면 **TTFT**

현재 simulator가 network transport를 모델링하지 않으면 결과 표에는 **TTFT**라고 써야 하며, TTFB라고 부르지 않는다.

| 별점 | 절대 | 근거 |
|---|---|---|
| ★☆☆ | > 4,000 ms | first response가 매우 늦음 |
| ★★☆ | 2,000 ~ 4,000 ms | target SLO 초과 |
| ★★★ | ≤ 2,000 ms | first-response SLO 달성 |

### 3.3 Performance — TPOT p99

| 별점 | 절대 | 근거 |
|---|---|---|
| ★☆☆ | > 50 ms | decode step 예산 초과 |
| ★★☆ | 25 ~ 50 ms | SLO 안이지만 headroom이 작음 |
| ★★★ | ≤ 25 ms | 부하 증가에 대한 headroom 확보 |

### 3.4 Performance — Latency QA 표기 규칙

Latency는 하나의 QA이지만 결과는 항상 두 sub-metric을 **각각 별점으로 표기**한다. 별점 산정은 offered-load sweep에서 **p99 TTFT ≤ 2,000 ms AND p99 TPOT ≤ 50 ms를 동시에 만족하는 load point 중 SLO Goodput이 최대인 operating point**를 사용한다.

모든 후보가 first-response/TPOT SLO를 만족하는 요청을 하나도 만들지 못하는 cell은 `SLO-infeasible stress`로 분리한다. 이런 cell은 large-batch/long-context failure boundary를 보여주는 데는 중요하지만, 하드웨어 자체의 불가능 영역으로 인해 모든 후보의 Latency 별점을 일괄적으로 떨어뜨리지 않도록 **최종 Latency 별점 집계에서는 제외하고 raw TTFT/TPOT을 별도 보고**한다.

```
Performance Latency
  First-response (TTFB/TTFT): ★★★
  TPOT:                       ★★☆
```

즉 **Latency = First-response + TPOT 두 결과의 묶음**이며, 둘을 하나의 별점으로 축약하지 않는다. E2E Latency는 보조 지표로 함께 보고한다.

### 3.5 Resource Utilization

DP마다 자원 종류는 다르므로(HBM/Memory Tier, GPU/CPU, Link 등) raw metric은 각 DP 문서에서 정의하되, 최종 별점은 공통의 **Resource Utilization Index (RUI, 0~1)** 로 정규화한다.

- 각 DP는 문서에 정의된 resource metric을 0~1 utility로 변환하고 가중치를 명시한다.
- 1.0은 목표 활용 상태, 0은 심한 saturation / capacity pressure / 자원 낭비를 뜻한다.
- 원시 수치(HBM Capacity, BW, Tier, CPU/GPU/Link utilization)는 반드시 함께 보고한다.
- 후보에 유리하도록 사후에 utility 함수나 가중치를 바꾸지 않는다.

| 별점 | RUI | 근거 |
|---|---:|---|
| ★☆☆ | < 0.65 | saturation/pressure 또는 심한 자원 낭비가 반복됨 |
| ★★☆ | 0.65 ~ 0.85 | 실용 가능하나 headroom/균형에 제약이 있음 |
| ★★★ | ≥ 0.85 | 목표 utilization/headroom을 대부분의 평가 구간에서 유지 |

### 3.6 Efficiency — 토큰당 이동 바이트 (M-R1)

```
(결정 A/B 재배치 + Mode B 복원 바이트) ÷ SLO 만족 출력 토큰
```
최초 배치는 분자에서 뺀다 — Prefill이 어차피 그곳에 쓰므로 링크를 건너는 이동이 아니다.

| 별점 | 절대 | 근거 |
|---|---|---|
| ★☆☆ | > 1 GB/tok | 토큰 하나에 세션 KV 하나 이상을 옮긴다 |
| ★★☆ | 10 MB ~ 1 GB/tok | — |
| ★★★ | ≤ 10 MB/tok | 기준 셀의 세션 KV(40 GiB)의 1/4000 이하 |

### 3.7 Efficiency — 토큰당 에너지 (M-R2)

```
정적 = Σ(컴포넌트 TDP × 점유 시간)    동적 = Σ(링크 바이트 × 5.0 pJ/bit)
```

| 별점 | 배수 | 근거 |
|---|---|---|
| ★☆☆ | > 1.5× | 같은 토큰에 1.5배의 전력 |
| ★★☆ | 1.1 ~ 1.5× | — |
| ★★★ | ≤ 1.1× | 대조군과 차이 없음 |

> **절대값은 신뢰하지 말 것.** TDP는 첨두값이고 Attention 외 연산의 점유가 완전히 모델링되지 않았다. **정책 간 상대 비교로만 쓴다.** 측정에서 이동 에너지는 전체의 0.02% 미만이었다 — 에너지 차이는 거의 전부 **점유 시간** 차이에서 온다.

### 3.8 Flexibility (M-F1)

**"지원했는가"가 아니라 "옳게 판단했는가".** 신규 메모리를 투입하고 오라클(실제로 Goodput이 늘었는가)과 정책의 판단(배치했는가)을 대조한다.

```
적중 TP  이득O·배치O      놓침 FN  이득O·배치X
오용 FP  이득X·배치O      회피 TN  이득X·배치X

M-F1 정확도 = (TP+TN)/N    M-F1b 오용률 = FP/(FP+TN)    M-F1c 기회손실 = FN/(TP+FN)
```

| 별점 | 정확도 | 근거 |
|---|---|---|
| ★☆☆ | < 0.50 | 동전 던지기보다 못하다 |
| ★★☆ | 0.50 ~ 0.83 | 6종 중 5종 이하를 맞춘다 |
| ★★★ | ≥ 0.83 | 6종 중 5종 이상 |

> **정확도만 보면 안 된다.** 아무것도 안 쓰는 정책은 오용률 0이지만 기회손실 1이다. 셋을 함께 읽는다. 오라클에 유익한 투입이 하나도 없으면(`oracle_has_positive: false`) 이 실험은 "회피 능력"만 재므로 Flexibility 측정으로 인용할 수 없다.

### 3.9 Modifiability (ISO/IEC 25010)

DP1~DP4에서 동일한 변경 archetype 4종을 고정하고 두 단위로 잰다.

1. **New Resource Type** — 신규 Memory/Compute/Link 등 resource type 추가
2. **New Workload/Data/Operation Type** — DP가 해석해야 하는 신규 data/workload/operation 추가
3. **New Constraint/SLO** — latency, capacity, movement budget 등 새 제약 추가
4. **New Execution/Decision Mode** — 새 placement/eviction/migration/execution mode 추가

- **Man-month** — COCOMO II **Reuse/Reengineering** 모델. 변경 비율(DM/CM/IM)을 입력으로 받으므로 LoC→노력 환산의 순환 논리를 피한다. SU(Software Understanding)는 측정된 순환복잡도에서 유도한다 (McCabe/NIST 구간: ≤10 → 20, 11~20 → 30, >20 → 40).
- **토큰** — 읽어야 하는 코드 + 써야 하는 코드. 3.6 char/token 근사 (후보 간 비교에서 약분).

| 별점 | Man-month (4과제 합) | 토큰 | 근거 |
|---|---|---|---|
| ★☆☆ | > 1.0 PM (19일 초과) | > 50K | 한 사람이 한 달 가까이 붙어야 한다 |
| ★★☆ | 0.25 ~ 1.0 PM | 20K ~ 50K | — |
| ★★★ | ≤ 0.25 PM (5일 이하) | ≤ 20K | 한 사람이 한 주 안에 끝낸다 |

> **두 단위가 다른 답을 낼 수 있다.** 최종 별점은 DP1~DP4 공통으로 **Man-month 별점과 Token 별점 중 더 낮은 값**을 사용한다. 사람 비용은 복잡도에 초선형이고 AI 비용은 코드 크기에 거의 선형이므로 두 수치는 함께 보고한다.
>
> 현재 토큰 모델은 **시행 횟수를 반영하지 못한다** — 복잡한 코드는 한 번에 못 맞춰 재시도가 곱으로 붙는다.

---

## 4. 측정 절차 (DP1~DP4 공통)

1. **워크로드/trace를 후보와 무관하게 먼저 생성한다.** 같은 `(scenario, seed)`에서 후보들이 동일 입력을 보게 하여 paired 비교가 성립하도록 한다.
2. **동일 seed에서 짝지어(paired) 비교하고, 95% 신뢰구간이 0을 지나면 "차이 없음"으로 판정한다.** 점 추정의 부호만으로 우열을 정하지 않는다.
3. **Throughput/Goodput의 시간 분모는 후보와 무관한 고정 horizon으로 둔다.**
4. **Warm-up 또는 정책 적용 이전 구간을 제외해야 하는 DP는 제외 규칙을 실행 전에 고정하고 모든 후보에 동일하게 적용한다.** DP마다 "최초 턴"의 의미가 다르므로 특정 턴 번호를 공통 규칙으로 강제하지 않는다.
5. **의미 있는 As-Is/정책 없음 대조군을 정의할 수 있는 DP에서는 함께 측정한다.** 다만 C1/C2 등 후보의 최종 별점은 대조군 상대값이 아니라 §3의 공통 절대/정규화 기준으로 매긴다.
6. **TTFT·TPOT p99는 각 평가 시나리오의 전체 요청을 기준으로 계산한다.** 급변/정상 구간을 사후 분리해 유리한 구간만 인용하지 않는다. 또한 Max Sustainable operating point는 **TTFT p99와 TPOT p99가 둘 다 SLO를 만족하는 load point만** 후보로 인정한다.
7. **정책 결정 비용과 DP가 유발하는 실행 비용을 critical path에 노출되는 만큼 Latency/Throughput에 포함한다.** DP1의 tier 변경은 DP4 migration mechanism 자체를 구현하지 않더라도 이동 비용 proxy를 명시해야 하며, DP4에서는 실제 migration 비용을 직접 측정한다.
8. **Fault injection / infeasible stress / coverage-only scenario는 정상 운용 QA 별점과 분리한다.** Trade-off와 failure mode 분석에는 포함하되, 별점에 넣을 경우 공통 문서에 사전 명시한다.

---

## 5. 재현

각 DP 결과 문서는 이 공통 문서를 인용하고, 자기 evaluator의 정확한 실행 명령·seed·scenario manifest·원자료 경로를 기록한다.

DP1 현재 evaluator 예:

```bash
cd doc-architect/dp1_eval
python3 run_eval.py
python3 -m unittest -v test_eval.py
```

DP2~DP4도 동일한 네 QA와 §3의 별점 기준을 사용하되, DP별 raw resource metric과 scenario만 각 결과 문서에서 추가 정의한다.

> Python 버전/난수 구현이 결과에 영향을 줄 수 있으므로 실행 환경과 seed를 함께 기록한다. 최종 후보 비교는 paired trace와 95% 신뢰구간을 우선한다.

---

## 6. 미확정 항목

| 항목 | 영향 |
|---|---|
| **GLM-5 활성 파라미터 수** | 가중치 읽기 항이 0 → TPS 과대평가. **GLM-5 절대 수치 인용 불가** |
| `dram` · `hbf` · `ssd_pim` 의 TDP | 에너지 지표의 절대값 (상대 비교는 영향 적음) |
| Host 2홉 지연 2.0 µs | ASSUMED. Mode C에서는 예산의 0.3% 미만이라 영향이 작다 |
| Rubin 노드 형태 (8-GPU 가정) | 도메인 집계 |
