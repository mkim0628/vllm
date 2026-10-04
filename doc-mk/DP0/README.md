# DP0 — 서버 간 요청 조율 계층 (Request Orchestration)

| 항목 | 내용 |
|---|---|
| 상태 | 초안 |
| 작성 일자 | 2026-10-02 |
| 분석 대상 버전 | llm-d Router `llm-d/llm-d-router@af01da5` / NVIDIA Dynamo `ai-dynamo/dynamo@938d89b` / vLLM upstream `vllm-project/vllm@9e6550b` |
| 근거 수준 범례 | **[A]** 실제 실행/빌드로 검증 · **[B]** 공식 문서·문헌 · **[C]** 코드 읽기·분석·논증 |

이 폴더는 **DP0**의 문서를 모은다. DP0은 여러 추론 서버(vLLM 인스턴스)를 묶어 요청을 조율하는 계층(Orchestration)을 **OSS(llm-d, NVIDIA Dynamo)를 확장해서 만들지(1안), 자체 구현할지(2안)** 를 정한다.

## DP0의 위치

DP0은 기존 DP1~DP4 **앞에 오는 최상위 Design Point**다. 기존 DP 번호(DP1~DP4)는 바꾸지 않았다. DP0이 정하는 서버 간(클러스터) 결정과 DP1~DP4의 서버 내부 결정은 약속된 인터페이스(vLLM의 KV 이벤트, 메트릭, `kv_transfer_params`, NIXL)로 만나므로 병렬로 진행할 수 있다.

| DP | 문서 |
|---|---|
| DP0 | 이 폴더 |
| DP1 | [`../DP1/dp1-ai-data-migration-decision-architecture.md`](../DP1/dp1-ai-data-migration-decision-architecture.md) |
| DP2 | [`../DP2/dp2-prefill-decode-execution-planning-decision-timing.md`](../DP2/dp2-prefill-decode-execution-planning-decision-timing.md) |
| DP3 | [`../vllm-dp3-memory-placement-abstraction-candidates.md`](../vllm-dp3-memory-placement-abstraction-candidates.md) |
| DP4 | [`../vllm-dp4-compute-placement-scheduling-candidates.md`](../vllm-dp4-compute-placement-scheduling-candidates.md) |

## 문서 목록과 읽는 순서

| 순서 | 문서 | 내용 |
|---|---|---|
| 1 | [`dp0-requirements.md`](dp0-requirements.md) | 기능 요구사항 F1~F6, 품질 속성 Q1~Q4(QA 시나리오 표), 제약 C1~C6, 정책 P1~P5, 추적성 매트릭스. 맨 위 "한눈에 보기"부터 읽는다 |
| 2 | [`dp0-request-orchestration-framework.md`](dp0-request-orchestration-framework.md) | 설계 문서. 맨 위 "임원용 요약" → 후보 구조(컴포넌트 뷰) → 평가 → 전환 조건·Evidence 계획 → 리스크 |
| 3 | `DP0-slides.pptx` | 발표자료. 위 두 문서와 같은 ID(F/Q/C/P)와 용어를 쓴다 (발표자료는 이 폴더에 별도로 복사해 둔다) |

## 발표자료와의 관계

발표자료는 청중(도메인을 모르는 일반 SW 개발 임원)에 맞춰 도식 중심으로 줄인 버전이고, 이 폴더의 문서는 그 근거다. 사실·평가·결론은 같다. 슬라이드와 문서의 ID·용어가 다르면 `dp0-requirements.md`가 맞다(요구사항 단일 출처).

## 분석 근거 문서 위치

llm-d와 Dynamo의 코드 분석 문서는 `mkim0628/llm-d` 저장소 브랜치 `claude/doc-mk-orchestration-analysis`의 `doc-mk/`에 있다: <https://github.com/mkim0628/llm-d/tree/claude/doc-mk-orchestration-analysis/doc-mk>

- llm-d 분석: [`llm-d-architecture-analysis.md`](https://github.com/mkim0628/llm-d/blob/claude/doc-mk-orchestration-analysis/doc-mk/llm-d/llm-d-architecture-analysis.md)
- Dynamo 분석: [`dynamo-architecture-analysis.md`](https://github.com/mkim0628/llm-d/blob/claude/doc-mk-orchestration-analysis/doc-mk/dynamo/dynamo-architecture-analysis.md)

## 근거 수준 범례

| 태그 | 의미 |
|---|---|
| **[A]** | 실제 실행·빌드로 검증 (llm-d 확장은 합성 백엔드로 EPP를 끝단까지 실행. 실제 vLLM end-to-end는 아님) |
| **[B]** | 공식 문서·문헌 |
| **[C]** | 코드 읽기·분석·논증 |

평가의 우열(●/◐/○, ▲/▼)은 모두 **가설**이며, 근거 수준은 결과의 좋고 나쁨과 독립이다 ([`../Evaluation/qa-evaluation-criteria.md`](../Evaluation/qa-evaluation-criteria.md)).
