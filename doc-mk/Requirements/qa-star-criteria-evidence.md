# QA-01~05 별 기준(★ 하한 / ★★ 등분 / ★★★ 상한)과 문헌 근거

> 상태: **proposal** (소유자 확정 전). 작성: 2026-10-19. 슬라이드: `qa-star-evidence-slides.pptx`(1장 표 + 2~6장 QA별), 생성 스크립트: `build_qa_star_deck.py`.
> 번호는 사용자 표(QA-01 Performance, 02 Resource Efficiency, 03 Modifiability, 04 Scalability, 05 Functional Correctness)를 따른다. `Evaluation/qa-star-criteria-unified.md`(v3)의 QA1~QA6 번호와 다르다(v3의 QA2 지연은 표에서 QA-01의 SLO 조건으로 합쳐졌다).

## 1. 별 규칙

| 별 | 의미 |
|---|---|
| ☆ | 미충족: 시나리오 목표(★ 값)에 못 미침 |
| ★ | 시나리오 충족(하한). 표의 [측정] 값 |
| ★★★ | 상한. 문헌·환산으로 찾은 현실적 상한 |
| ★★ | ★과 ★★★의 산술 등분 중점(정수 지표는 내림) |

v3와 다른 점: v3는 ★이 "열세", ★★이 "동등", ★★★이 "눈에 띄는 개선"이었다. 이 안은 ★이 이미 "충족"이라 현재 내부 시뮬레이션 결과 상당수가 ☆(미충족)이 된다(QA-01은 DP3 C1 1.514만 ★, QA-02는 DP3 C1·C2만 ★ 이상, QA-05는 DP3 C1 16.98%로 ☆). 소유자 확정 전에는 기존 v3 별을 바꾸지 않는다.

## 2. QA별 기준과 근거

| QA | ★ | ★★ | ★★★ | 근거 수준 |
|---|---|---|---|---|
| QA-01 Goodput 배수 R | ≥ 1.5x | ≥ 2.25x | ≥ 3.0x | 문헌 인용(지표·baseline 상이). 3.0x = Pensieve 상한, 6~14x는 시뮬·조건부 최대로 제외 |
| QA-02 HBM 감소율 | ≥ 20% | ≥ 47.5% | ≥ 75% | ★ 정책+측정 잡음 대비, ★★★ = KV 3~4x 축소(KVzip) |
| QA-03 변경 비용(AND) | $2(≈0.7M tok), 1.0 MM, ≤5 module | $1.25, 0.75 MM, ≤3 | $0.5(≈0.17M tok), 0.5 MM, ≤2 | 환산·측정. 경계값은 v3 사전 등록 가정 재사용 |
| QA-04 SE(N=16) | > 80% | > 85% | > 90% | ★ 문헌 유추, ★★★ 정책+USL 환산 |
| QA-05 F1 상대 하락 | < 3% | < 2% | < 1% | ★★★ 소유자 확정 한도, ★ 정책. 문헌은 정성 표현 |

## 3. 문헌 검증 상태

"확인"은 이번 세션에서 논문 abstract 또는 본문에서 직접 확인한 것이다.

| 문헌 | 사용한 값 | 상태 |
|---|---|---|
| InferCept, arXiv 2402.01869 | 처리량 1.6~2x, 재계산이 forward 시간의 37~40% | 확인(abstract). 비교 대상 시스템명은 abstract에 없음 |
| Mooncake, arXiv 2407.00079 (FAST'25) | 실트래픽 +75% 요청, 시뮬 최대 +525% | 확인(abstract) |
| KVFlow, arXiv 2507.07400 | SGLang(HiCache) 대비 최대 1.83x / 2.19x | 확인(abstract), "up to" 값 |
| Pensieve, arXiv 2312.05516 | vLLM·TensorRT-LLM 대비 1.14~3.0x | 확인(abstract), 어느 baseline이 어느 끝인지 abstract에 없음 |
| DistServe, arXiv 2401.09670 (OSDI'24) | 7.4x 요청 수, 12.6x 엄격한 SLO | 확인(abstract) |
| LMCache, arXiv 2510.09665 | 동일 TTFT에서 2.3~14x 처리율 | **검색 요약 기준, 원문 미확인** |
| KVzip, arXiv 2505.23416 | KV 3~4x 축소, 디코딩 지연 약 2x 감소, negligible 성능 저하 | 확인(abstract) |
| KVQuant, arXiv 2401.18079 | 3-bit KV, perplexity 저하 < 0.1 | 확인(abstract). F1 아님 |
| KIVI, arXiv 2402.02750 | 2.6x peak memory(가중치 포함), batch 4x, "거의 동일" 품질 | 확인(abstract). 정확도 수치 없음 |
| vLLM PagedAttention, arXiv 2309.06180 | 기존 시스템의 KV 메모리 실사용 20.4~38.2% | 확인(본문 Fig. 2 설명) |
| SWE-bench, arXiv 2310.06770 | gold patch 평균 1.7 file, 32.8 line | 확인(본문 Table) |
| Claude Code 비용 문서 | 평균 약 $13/개발자·활동일, 90%가 $30/일 미만 | 확인(code.claude.com/docs/en/costs) |
| arXiv 2409.16053 | 65,536 GPU(Frontier)에서 병렬 효율 80% | 확인(abstract). 학습 workload |
| vLLM 저장소 connector LOC | 최상위 파일 192~1,190(중앙값 356), backend 패키지 1,436~3,764 | 이 저장소에서 직접 계수 |

## 4. 알려진 한계와 정정

1. **v3 문서의 arXiv 1704.03329 인용은 부적합하다.** `qa-star-criteria-unified.md` §3.6이 SE 90% 근거로 인용했지만 이 논문은 분자동역학 코드 생성 시스템 논문이며 병렬 효율 수치가 abstract에 없다. Cornell CVW "Scaling" 페이지도 90% 기준을 확인하지 못했다. QA-04의 90%는 **정책 선택**으로 표기했다. (v3 문서는 소유자 확정 전이라 이 변경에서 수정하지 않았다.)
2. QA-04 문헌 80%는 학습(weak scaling) 병렬 효율이라 서빙 SE와 지표 의미가 다르다. USL 환산(σ ≤ 1.67% / 1.18% / 0.74%)은 모델 가정이다.
3. QA-05는 F1 하락의 일반 임계 문헌이 없다. 3%는 소유자 한도 1%의 3배인 정책 값이며 task별 run-to-run F1 변동으로 확인해야 한다.
4. QA-01 문헌 값은 지표(처리량·요청 수·goodput), baseline, workload가 서로 달라 직접 비교가 아니다.
5. 표의 TPOT 2 ms는 원문 그대로 유지했다. v3 문서는 50 ms 오타로 해석했고 소유자 확인이 필요하다(D2).
6. 표(원문 이미지)의 QA-08 측정값("원인 파악 시간 < 1시간")은 QA-10과 같은 문구라 복사 오류로 보고 "성능 회복 시간 < 5분"(요구사항 덱 QA-11 값)으로 바꿨다. QA-09의 "> 3 개"는 대상이 3종이라 "≥ 3개"로 바꿨다.
7. QA-06~10의 근거는 이번 작업에서 조사하지 않았다(임시, 가정 표기).
8. 토큰 환산은 입력 단가 $3/MTok(v3 문서 가정, 2차 자료)로 한 값이다.
9. 확장성은 `qa-star-criteria-unified.md` §3.6(2026-10-17 확장)에서 5개 증가 축(S1~S5)으로 정의되었고 별 경계는 S2(노드 수) 축 SE에만 있다. QA-04의 ★/★★/★★★은 그 S2 축 SE에만 적용되며 나머지 4개 축은 값 보고(D9)다.
