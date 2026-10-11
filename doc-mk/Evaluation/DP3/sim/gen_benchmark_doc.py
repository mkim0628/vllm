#!/usr/bin/env python3
"""Regenerate DP3/benchmark.md scenario tables from dp3_scenarios.py.   python sim/gen_benchmark_doc.py"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dp3_scenarios as S  # noqa: E402


def row(sc):
    tiers = " ".join(f"{t} {int(f*100)}%" for t, f in sc.tier_frac)
    knobs = [f"ctx {sc.ctx_tokens//1024}K", f"query {sc.query_tokens}", f"풀 {sc.n_ctx}개", tiers]
    if sc.kv_frac != 1.0:
        knobs.append(f"HBM KV 몫 x{sc.kv_frac}")
    if sc.zipf != 0.8:
        knobs.append(f"zipf {sc.zipf}")
    if sc.ramp:
        knobs.append("압박 ramp")
    if sc.burst:
        knobs.append("burst x2.5")
    if sc.shift_frac:
        knobs.append("T/2에 hot 문맥 HBM 이탈")
    if sc.mismatch != 0.3:
        knobs.append(f"mismatch {sc.mismatch}")
    return f"| `{sc.sid}` | {sc.brief} | {', '.join(knobs)} |"


def table(items):
    return "\n".join(["| ID | 무엇인가 | 핵심 파라미터 |", "|---|---|---|"] + [row(s) for s in items])


def main():
    txt = f"""# DP3 Benchmark (DP3 맞춤형)

> 상태: **registered** (평가 실행 전에 고정, 결과를 본 뒤 바꾸지 않는다). 최종 결과 = **Common Benchmark + 이 문서의 DP3 전용 benchmark**.
> 시나리오 단일 소스는 `sim/dp3_scenarios.py`이며 이 표는 `sim/gen_benchmark_doc.py`가 만든다(수동 편집 금지).
> 평가 방법과 가정은 [`simulation-plan.md`](simulation-plan.md), 별 기준은 `../qa-star-criteria-unified.md`.

# 1. 구성

| Set | 수 | 목적 |
|---|---:|---|
| Common (CB-1~3) | {len(S.COMMON)} | 공통 입구. 8K 문맥 재사용에서 압축·재사용이 Baseline보다 나빠지지 않는지 |
| DP3 Stress | {len(S.STRESS)} | 문맥 길이, tier, 재사용 양상, 질의 길이, 용량 압박에 따른 trade-off |
| DP3 Dynamic | {len(S.DYNAMIC)} | Baseline이 처음엔 SLO를 만족하다 hot 문맥 이동·burst·압박 증가로 나빠지는 패턴 |

# 2. 고정 조건 (모든 시나리오 공통)

Llama-3.1-70B BF16(KV 320 KiB/token), 8-GPU 노드 1개(SYS-H100, SYS-B200 통합), 출력 256 token, SLO TTFT P99 ≤ 2 s / TPOT P99 ≤ 50 ms.
문맥 KV는 노드의 외부 배치(tier별 비율)에 놓여 있고 **배치는 모든 정책에 같다**(배치는 DP1 소관). 질의 길이 기본 256.
도착률은 Baseline만 돌려 얻은 용량(SLO를 지키는 최대 도착률)의 70%(`lam0`)로 고정한다. 부하 sweep은 lam0의 0.5/0.75/1.0/1.25배.

# 3. 정책

| 정책 | 설명 | 파라미터 |
|---|---|---|
| Baseline-As-Is | 전체 Context KV를 그대로 재사용(압축 없음). 다른 tier에 있으면 전량 적재 후 전체에 attention | — |
| C1-Offline | 사전에 만든 Comp.KV(요청 간 공유)를 적재·재사용, 선택 재계산 | 유지 비율 r = 0.30, 재계산 rho = 0.15 (유지 토큰 기준) |
| C2-Online | 요청 시점에 전체 KV를 적재하고 Query x KV attention으로 선정·압축, 선택 재계산 | r = 0.30, rho = 0.15 |

r과 rho는 문헌의 대표값(KVzip 3~4배 KV 축소, CacheBlend 15% 재계산)을 쓰며 결과를 본 뒤 바꾸지 않는다. 민감도(r 0.15/0.5)는 별도 보고한다.

# 4. Common Benchmark 실현 (CB-1~3)

{table(S.COMMON)}

# 5. DP3 Stress ({len(S.STRESS)})

{table(S.STRESS)}

# 6. DP3 Dynamic ({len(S.DYNAMIC)})

{table(S.DYNAMIC)}

# 7. 아직 모델링하지 못하는 것

- 정확도(F1)는 이 simulator의 출력이 아니다(`accuracy/`의 소형 모델 측정과 `sim/accuracy.py` 모델).
- 여러 문맥을 이어 붙일 때의 blending 품질, chunked prefill 세부, attention kernel 효율의 문맥 길이 의존, KV 전송 중 HBM 겹침.
- 압축·재사용이 DP1 배치·DP2 실행 자원 결정과 상호작용하는 효과(여기서는 배치를 고정하고 GPU에서 실행).
"""
    (HERE.parent / "benchmark.md").write_text(txt, encoding="utf-8")
    print("wrote benchmark.md")


if __name__ == "__main__":
    main()
