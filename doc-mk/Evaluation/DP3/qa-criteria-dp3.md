# DP3 QA 기준

DP3에는 DP 전용 별 기준이 없다. **`../qa-star-criteria-unified.md`(공통 별 기준 v2)를 그대로 쓴다.**

| QA | DP3에서의 지표 | 기준 |
|---|---|---|
| QA2 지연 | 시나리오 쌍별 TTFT P99·TPOT P99의 기하평균과 Baseline 대비 r | unified §3.2 (절대 SLO 등급 A와 개선 등급 R의 평균) |
| QA3 자원 | HBM에 올라간 Context KV의 시간 평균 GiB의 Baseline ÷ 후보 | unified §3.3 (1.25 / 0.95) |
| QA5 기능 정확성 | F1 상대 하락 (소형 모델 eviction micro-benchmark + 매핑) | unified §3.5 (1% / 3%, 3%는 제안) |

선정 QA와 우선순위 제안: `qa_priority.json` (QA2 > QA5 > QA3, 소유자 확정 전).
