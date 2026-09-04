# DP1 배치 결정 프로토타입

`doc-mk/vllm-dp1-placement-decision-basis.md`의 두 후보 구조를 실제로 구현하고,
문서의 정량 주장을 **실행 가능한 단언**으로 바꾼 코드다.

```
prototype/
├── dp1/
│   ├── model.py            공통 모델 — Tier, 요청, 관측 가능성 분리, 결정 계측
│   ├── tier_indexed.py     Candidate 1 — 자원 축 인덱스
│   ├── object_indexed.py   Candidate 2 — 객체 축 인덱스 (계약 / 비용 모델)
│   ├── policies.py         정책 레지스트리 — 형태마다 이름, 최선 형태(★) 표시
│   ├── cases.py            케이스 카탈로그 — 무엇을 재현하고 무엇을 봐야 하나
│   ├── workload.py         시나리오 생성
│   ├── harness.py          시뮬레이션 + 정량 프록시 측정
│   └── run_experiment.py   후보 비교 실험 CLI
├── tests/test_dp1_claims.py  문서 주장 35건의 검증
├── TESTING.md              테스트 가이드 (읽는 법 · 실행법 · 실패 시 판단)
└── README.md               이 파일
```

## 무엇인가 / 무엇이 아닌가

| | |
|---|---|
| **맞다** | DP1의 **배치 결정 로직(코어 기술)** 구현. 두 후보의 정책·불변식·비용 구조를 그대로 옮겼다 |
| **맞다** | 문서의 수치가 예측이라면, 이 코드가 내는 수치는 **실측**이다 |
| **아니다** | vLLM 코어 패치가 아니다. `allocate_slots`나 `BlockPool`을 건드리지 않는다 |
| **아니다** | 성능 벤치마크가 아니다. 커널·전송·실제 지연을 모델링하지 않는다 |

## 빠른 시작

```bash
cd doc-mk/prototype
python3 -m unittest discover -s . -v     # 테스트 35건
python3 -m dp1.cases                     # 케이스 카탈로그
python3 -m dp1.run_experiment --list     # 케이스·정책 목록
python3 -m dp1.run_experiment --steelman # 두 후보의 최선 형태 비교
```

의존성 없음 (Python 3.10+ 표준 라이브러리만). 자세한 내용은 `TESTING.md`.
