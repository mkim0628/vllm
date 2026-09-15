# ADR — Architecture Decision Record

`doc-architect/`의 설계 문서가 **이미 전제로 깔고 있으나 그 자체로는 기록되지 않은 결정**을 고정한다. 설계 문서는 "무엇을 설계했는가"를 쓰고, ADR은 **"왜 그 선택이었고 무엇을 기각했으며 언제 다시 볼 것인가"** 를 쓴다.

## 목록

| ADR | 결정 | 상태 | 되돌리기 |
|---|---|---|---|
| [001](adr-001-prefill-gpu-pinning.md) | **Prefill 연산을 GPU에 고정한다** | Accepted | 어려움 — 모듈 경계와 시퀀스 전반이 이 위에 서 있다 |
| [002](adr-002-custom-hbm-separate-node.md) | **Custom HBM을 GPU 패키지가 아닌 별도 노드로 모델링한다** | Accepted | 중간 — Configuration 교체로 가능하나 §4의 결론이 함께 바뀐다 |
| [003](adr-003-two-decision-points.md) | **DP1의 배치 결정 시점을 두 곳(Prefill 종료 / 비활성 전환)으로 둔다** | Accepted (001을 대체) | 중간 |
| [004](adr-004-demote-vs-drop.md) | **회수를 Demote와 Drop으로 가르고 Drop만 DP3에 귀속시킨다** | Accepted | 어려움 — DP3의 성립 근거 자체 |
| [005](adr-005-dp1-before-dp3.md) | **DP1을 먼저 실행하고 DP3는 그 실패 처리 경로로 둔다** | Accepted | 어려움 — 되돌리면 되돌릴 수 없는 손실이 발생한다 |
| [006](adr-006-shared-block-drop-exclusion.md) | **Prefix Cache 공유 Block을 Drop 대상에서 제외한다** | Accepted | 쉬움 — 범위 제한이므로 근거가 생기면 넓힐 수 있다 |
| [007](adr-007-selection-out-of-scope.md) | **후보 선정을 설계 문서 범위 밖에 둔다** | Accepted | 쉬움 |

## 의존 관계

```text
   001. Prefill GPU 고정
        │
        ├──► 003. 결정 시점 두 곳      (Decode 구간에만 선택지가 있으므로)
        │
        └──► 002. Custom HBM 별도 노드  (외부/내부 비대칭이 오프로드 판단의 기준)

   004. Demote / Drop 분리
        │
        ├──► 005. DP1 → DP3 순서       (Drop이 되돌릴 수 없으므로 순서가 중요)
        │
        └──► 006. 공유 Block 제외      (Drop의 손실이 세션 경계를 넘으므로)

   007. 선정 범위 밖  ── 세 DP 공통
```

## 템플릿에 대하여

일반적인 ADR 템플릿의 다음 절은 **본 도메인에 해당하지 않으므로 의도적으로 비운다.**

| 생략한 절 | 이유 |
|---|---|
| AuthN/AuthZ, Secret 관리, 데이터 residency | 단일 추론 노드 내부의 메모리 배치 결정이며 외부 경계나 자격 증명을 만들지 않는다 |
| 규제/컴플라이언스 제약 | 해당 없음 |
| 배포 전략, Feature Flag, 단계적 롤아웃 | 현 단계의 산출물은 **설계와 시뮬레이션**이며 서비스에 배포되지 않는다 |

대신 본 도메인에 필요한 절을 넣는다 — **가정과 그 출처 등급**(공개값 / 가정값), **재검토 트리거**, **이 결정이 무엇을 측정 불가능하게 만드는가**.

## 규칙

- **결정을 바꿀 때 ADR을 수정하지 않는다.** 새 ADR을 쓰고 이전 것의 상태를 `Superseded`로 바꾼다. 003이 그 예다.
- **가정값에 의존하는 결정은 그 사실을 Assumptions에 명시한다.** DP1 설계 문서 §3.5의 출처 등급을 그대로 따른다.
- **재검토 트리거를 반드시 채운다.** "언제 이 결정을 다시 볼 것인가"가 없는 ADR은 기록이 아니라 선언이다.
