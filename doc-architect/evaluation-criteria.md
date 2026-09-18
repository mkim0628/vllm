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
| `b200_x16_2node` **(기준)** | 8× B200 | 1.50 TiB | 64 TB/s | 8.0 kW | 2 |
| `gb200_nvl72` | 72× Blackwell | 13.50 TiB | 576 TB/s | 86.4 kW | 1 |
| `rubin_x16_2node` | 8× Rubin | 2.79 TiB | 224 TB/s | 18.4 kW | 2 |

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
        │  768 GB, 내부 56 TB/s         │     재활성 경로는 Mode C 뿐
        │  1,665 TFLOPS(FP16), 767 W   │
        └──────────────────────────────┘
```

| 메모리 | 용량 | 외부 BW | 내부 BW | 연산 | TDP | provenance |
|---|---:|---:|---:|---:|---:|---|
| `hbm` | 1.50 TiB | 64 TB/s | 64 TB/s | — | GPU 포함 | SPEC |
| `custom_hbm` | 768 GB | **63.0 GB/s** | **56 TB/s** | 1,665 TF | 767 W | 사용자 제공 (Rubin 환산) |
| `cxl_pnm` | 512 GiB | 63.0 GB/s | 1.1 TB/s | **3.28 TF** | 150 W | 사용자 제공 (FP32 1.64 TF ×2) |
| `dram` | 1.00 TiB | 63.0 GB/s | 400 GB/s | — | 50 W | ASSUMED |
| `hbf` | 2.00 TiB | 1.0 TB/s | 1.0 TB/s | — | 100 W | ASSUMED |
| `ssd_pim` | 16.00 TiB | 16.0 GB/s | 200 GB/s | 2.0 TF | 75 W | ASSUMED |

> **링크 스펙 유도** — PCIe 5.0 x16 = 32 GT/s × 16 × (128/130) ÷ 8 = **63.0 GB/s** 단방향. PCIe 6.0 x16 = 64 GT/s × 16 × (242/256) ÷ 8 = **121.0 GB/s** (`configs/memories_pcie6.json`).
>
> **Custom HBM은 GPU가 직접 읽지 못한다.** CPU를 2홉 경유하므로 Mode A(GPU 직접 읽기)가 성립하지 않고, 재활성 경로는 Mode C(Attention 오프로드)뿐이며 오프로드가 불가하면 Mode B(전량 복원)로 떨어진다.
>
> **cHBM은 도메인당 1대다.** HBM은 GPU 수만큼 합산되지만(64 TB/s) cHBM은 1대(56 TB/s)다. 따라서 **오프로드의 이득은 대역폭이 아니라 (a) 용량 확장과 (b) GPU를 Attention에서 놓아주는 자원 병렬화에서 나온다.**

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

**부하 = 배치 크기 × context 길이.** LLM 서빙 벤치마크의 통상 축이다 (vLLM `benchmark_serving`의 `--max-concurrency` + 입력/출력 길이, MLPerf Inference의 고정 시퀀스 길이 + 동시성 시나리오).

```
BATCH   = [1, 16, 64, 256]
CONTEXT = [16K, 32K, 128K, 512K]
```

도착률은 배치를 채우는 수단이며 부하의 좌표가 아니다.

### 1.5 SLO

| 항목 | 값 | 근거 |
|---|---|---|
| TTFT | ≤ 2,000 ms | 대화형 에이전트의 체감 한계 |
| TPOT | ≤ 50 ms | 20 tok/s ≈ 사람의 읽기 속도 |

---

## 2. Reference Performance — 절대 수치의 기준점

**큐잉 없는 물리 하한**이다. 워크로드가 아니라 Configuration에서 유도되므로 기준점으로 쓸 수 있다.

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

### 3.1 Performance — 처리량 (TPS)

| 별점 | 배수 | 절대 (기준 셀) | 근거 |
|---|---|---|---|
| ★☆☆ | < 0.50× | < 557 tok/s | 물리 하한의 절반도 못 내면 구조가 자원을 낭비하고 있다 |
| ★★☆ | 0.50 ~ 0.85× | 557 ~ 946 | 통상적인 실측/이론 비율 구간 |
| ★★★ | ≥ 0.85× | ≥ 946 tok/s | 물리 하한의 85% 이상. 스케줄링·배치 오버헤드를 감안한 실질 상한 |

### 3.2 Performance — TTFT p99

| 별점 | 배수 | 절대 | 근거 |
|---|---|---|---|
| ★☆☆ | > 2.0× SLO | > 4,000 ms | 사용자가 이탈하는 구간 |
| ★★☆ | 1.0 ~ 2.0× SLO | 2,000 ~ 4,000 ms | SLO 초과이나 사용 가능 |
| ★★★ | ≤ SLO | ≤ 2,000 ms | §1.5의 SLO 달성 |

### 3.3 Performance — TPOT p99

| 별점 | 배수 | 절대 | 근거 |
|---|---|---|---|
| ★☆☆ | > 1.0× SLO | > 50 ms | step 예산 초과. 그 토큰은 Goodput 분자에서 빠진다 |
| ★★☆ | 0.5 ~ 1.0× SLO | 25 ~ 50 ms | 여유 없음 |
| ★★★ | ≤ 0.5× SLO | ≤ 25 ms | 부하가 두 배가 되어도 SLO를 지킨다 |

### 3.4 Performance — Latency 최종 별점

Performance Latency의 최종 별점은 TTFT와 TPOT 중 **더 낮은 별점**을 사용한다.

```
Latency Star = min(TTFT Star, TPOT Star)
```

이 규칙은 DP1~DP4에 동일하게 적용한다. E2E Latency는 원인 분석용 보조 지표로 함께 보고하되 최종 별점의 별도 축을 만들지 않는다.

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

1. **워크로드를 정책과 무관하게 먼저 생성한다.** 정책마다 난수 소비 순서가 달라지면 같은 seed라도 다른 입력을 보게 되어 짝지은 비교가 무효가 된다.
2. **동일 seed에서 짝지어(paired) 비교하고, 95% 신뢰구간이 0을 지나면 "차이 없음"으로 판정한다.** 점 추정의 부호로 판정하지 않는다.
3. **Goodput의 분모는 horizon으로 고정한다.**
4. **최초 턴은 SLO 판정과 Goodput 분자에서 제외한다** — 배치 결정 이전이므로 대조군으로만 쓴다.
5. **"정책 없음" 대조군(As-Is)을 반드시 함께 잰다.** 후보 간 격차보다 "정책이 있는가 없는가"의 격차가 더 클 수 있다.
6. **TTFT·TPOT의 p99는 전체 요청에 대해 하나만 낸다.** 정상/급변 구간을 나누지 않고, 부하 변동을 워크로드 안에 포함시킨다.
7. **정책 결정 시간과 데이터 이동 시간을 모든 시간 지표에 포함한다.** 결정점 A의 비용은 Decode를 막고, 결정점 B의 비용은 유휴에 숨되 초과분이 다음 턴의 TTFT로 이월된다.

---

## 5. 재현

```bash
# CPython 3.11.15. 의존성 없음 (표준 라이브러리만).
python3 -m dp1_sim.run_grid --seeds 8 --horizon 200   # 클러스터 x 모델 x 배치 x context
python3 -m dp1_sim.static_metrics                      # 정적 지표
python3 -m dp1_sim.modifiability                       # Man-month / 토큰
```

> Python 버전이 다르면 수치가 달라질 수 있다 — CPython은 `random.random()`의 시퀀스만 보장하고 그 위의 분포 함수(`gauss`/`expovariate`/`choices`)는 보장하지 않는다. 판정이 paired CI라 결론은 유지될 것으로 본다.

---

## 6. 미확정 항목

| 항목 | 영향 |
|---|---|
| **GLM-5 활성 파라미터 수** | 가중치 읽기 항이 0 → TPS 과대평가. **GLM-5 절대 수치 인용 불가** |
| `dram` · `hbf` · `ssd_pim` 의 TDP | 에너지 지표의 절대값 (상대 비교는 영향 적음) |
| Host 2홉 지연 2.0 µs | ASSUMED. Mode C에서는 예산의 0.3% 미만이라 영향이 작다 |
| Rubin 노드 형태 (8-GPU 가정) | 도메인 집계 |
