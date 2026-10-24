"""qa-criteria-v4.md 생성 (값은 criteria_data / theory_model에서 읽는다). python3 gen_md.py"""
import criteria_data as cd
import theory_model as tm

R = tm.all_results()
S = R["single"]
b0, b1 = S["B0"], S["B1"]
n0 = lambda x: format(round(x), ",")
out = []
w = out.append
w("""# QA 평가 기준 v4 (B1 기준 5구간), Baseline, 이론 예상값, 평가 시나리오

> 상태: **설명용 장표의 기준안** (2026-10-24). 기존 문서(`Evaluation/`, `Requirements/`)는 수정하지 않았다. 이 폴더가 단일 출처다.
> 덱: `DP-QA-criteria-v4.pptx` (첨부 덱을 베이스로 `build_deck.py`가 생성) · 값: `criteria_data.py`, `theory_model.py` · 이 문서: `gen_md.py`가 생성.

## 0. 범위와 별 규칙

- 범위: **KV 캐시 관리만** (RAG·LoRA·MoE 제외). 압축은 범위 밖, DP3는 선택 재계산만. 정확도 QA는 제외.
- **판정 Baseline = B1(정적 offload)**: HBM이 차면 LRU로 DRAM, DRAM이 차면 SSD로 옮김. 전체 write-back, 요청 시 동기 복원, prefetch·예측 없음. B0(GPU-only: vLLM 기본, 부족하면 recompute)는 참고로 병기한다.
- 별: ☆(미충족) / ★1 / ★1.5 / ★2 / ★2.5 / ★3. ★1 = 시나리오 요구값, ★1 초과는 0.5씩, 앵커 사이는 중점.
- 문헌 수치는 모두 "up to" 보고값이며 지표·baseline·workload·논문 버전이 달라 직접 비교가 아니다.

## 1. 기준 (B1 대비)

| QA | 지표 | ★1 | ★1.5 | ★2 | ★2.5 | ★3 |
|---|---|---|---|---|---|---|
| Q1 처리량 | R = Max SLO goodput ÷ B1 | ≥ 1.2 | ≥ 1.35 | ≥ 1.5 | ≥ 1.65 | ≥ 1.8 |
| Q2 HBM | HBM 사용량 감소율 (B1 대비) | ≥ 20% | ≥ 30% | ≥ 40% | ≥ 50% | ≥ 60% |
| Q3 고부하 지연 | r = √(TTFT 개선 × TPOT 개선, P99), B1 Max SLO goodput의 90% 부하 | ≥ 1.2 | ≥ 1.35 | ≥ 1.5 | ≥ 1.65 | ≥ 1.8 |
| Q4 확장성 | SE(N=16) | ≥ 80% | ≥ 85% | ≥ 90% | ≥ 92.5% | ≥ 95% |
| Q5 변경 용이성 | module 수 AND M/M (시나리오 평균, 낮은 별) | ≤5 · ≤1.0 | ≤4 · ≤0.875 | ≤3 · ≤0.75 | ≤2.5 · ≤0.625 | ≤2 · ≤0.5 |

### 근거와 확인 상태

| QA | 앵커 | 근거 | 확인 상태 |
|---|---|---|---|
| Q1·Q3 | ★1 = 1.2x | DirectKV(OSDI'26): 기존 offload 방식 대비 end-to-end 최대 1.2x. 기존 '처리량 2배'(B0 대비)는 B1이 이미 B0의 @A@x라 B1 대비 @B@x에 해당 | 검색 요약 기준(원문 미확인) |
| Q1·Q3 | ★3 = 1.8x | KVFlow: SGLang(HiCache) 대비 최대 1.83x(단일)·2.19x(동시 다수). 시나리오 이론 상한(GPU 한계) @C@x의 약 80% | 기존 문서에서 abstract 확인 |
| Q1·Q3 | ★2 = 1.5x | ★1과 ★3의 중점 | 정책 |
| Q2 | ★1 = 20% | 시나리오 요구. 20% 감소 = 같은 HBM에 KV 1.25배 수용(계산) | 요구는 사용자 확정 |
| Q2 | ★2 = 40%, ★3 = 60% | DirectKV: 기존 offload 대비 GPU 메모리 43% 감소(B1과 같은 종류의 baseline). 이론 상한 ≈ 88%, HeadInfer 92%(1M ctx 극단)·ShadowKV(압축 포함)는 제외 | DirectKV·HeadInfer 검색 요약. "40~80%" 범위는 사용자 인용 |
| Q4 | 80 / 90 / 95% | Stakeholder 80%, AthenaK 65,536 GPU 80%(학습). 90·95%는 손실 10·5% 이내 정책(USL: σ 0.74%·0.35%) | 정책 선택. 90% 관례의 인용 논문(arXiv 1704.03329)은 부적합해 뺐다 |
| Q5 | ★1 = 5 module·1.0 MM, ★3 = 2·0.5 | module: 설계 component 12~14개 중 5개(36~42%). M/M: vLLM 최상위 connector 중앙값 356 LOC 신규 구현 ≈ 0.99 MM(공식), SWE-bench 평균 패치 ≈ 0.32 MM | LOC는 저장소에서 직접 계수, 공식·상수는 DP1 사전 등록(ASSUMED) |

Q5 공식: `M/M = [n × 3일 + L ÷ 40 LOC/일 × 2.0] ÷ 21`. 변경 시나리오 3종: S1 새 tier, S2 정책 교체, S3 vLLM upstream 갱신. 토큰 비용은 제외.
""".replace("@A@", "%.2f" % (b1["tps"] / b0["tps"])).replace("@B@", "%.2f" % (2 * b0["tps"] / b1["tps"])).replace("@C@", "%.1f" % ((1 / tm.G0) / b1["lam"])))

w("## 2. Baseline 절대값 (이론 계산, Agent KV Fleet)\n")
c2, c4 = R["dp2"], R["dp4"]
w("| QA | 범위 | B0 GPU-only | B1 정적 offload | ★1 / ★2 / ★3 (B1 환산) |")
w("|---|---|---|---|---|")
e1 = cd.EDGES["Q1"]
w("| Q1 goodput (tok/s) | 1 노드 | %s | %s | ≥ %s / %s / %s |" % (n0(b0["tps"]), n0(b1["tps"]), n0(b1["tps"] * e1[0]), n0(b1["tps"] * e1[2]), n0(b1["tps"] * e1[4])))
w("| | DP2 4노드(P2+D2 고정) | %s | %s | ≥ %s / %s / %s |" % (n0(c2["B0"]["tps"]), n0(c2["B1"]["tps"]), n0(c2["B1"]["tps"] * e1[0]), n0(c2["B1"]["tps"] * e1[2]), n0(c2["B1"]["tps"] * e1[4])))
w("| | DP4 4노드(노드 독립) | %s | %s | ≥ %s / %s / %s |" % (n0(c4["B0"]["tps"]), n0(c4["B1"]["tps"]), n0(c4["B1"]["tps"] * e1[0]), n0(c4["B1"]["tps"] * e1[2]), n0(c4["B1"]["tps"] * e1[4])))
w("| Q2 HBM (GiB) | 1 노드 / DP2 4노드 | %s / %s | %s / %s | ≤ %s / %s / %s (1 노드) |" % (n0(b1["hbm"]), n0(c2["B1"]["hbm"]), n0(b1["hbm"]), n0(c2["B1"]["hbm"]), n0(b1["hbm"] * .8), n0(b1["hbm"] * .6), n0(b1["hbm"] * .4)))
w("| Q3 TTFT/TPOT P99 | B1 90%% 부하 | %.1f s / %.1f ms (과부하) | %.2f s / %.1f ms | TTFT ≤ %.2f / %.2f / %.2f s (TPOT 동일 시) |" % (
    b0["ttft"], b0["tpot"], b1["ttft"], b1["tpot"], b1["ttft"] / 1.2 ** 2, b1["ttft"] / 1.5 ** 2, b1["ttft"] / 1.8 ** 2))
w("| Q4 SE(16) | N=16 | 98%% | 98%% | ≥ 80 / 90 / 95%% |")
w("\nB1은 B0의 %.2f배, 이론 상한(GPU 한계 %.2f turn/s)은 B1(%.2f turn/s)의 %.1f배다.\n" % (b1["tps"] / b0["tps"], 1 / tm.G0, b1["lam"], (1 / tm.G0) / b1["lam"]))

w("""## 3. 평가 시나리오: Agent KV Fleet

KV가 HBM·DRAM을 넘고 재사용할 history가 있는 구간을 겨냥한 통합 시나리오. 값은 설계값이고 시뮬레이션 전이다.

| 항목 | 값 | 계산·근거 |
|---|---|---|
| 모델·HW | Llama-3.1-70B BF16, 8-GPU 노드(SYS-H100): HBM 640 GiB, DRAM 1 TiB(호스트 링크 64 GB/s), NVMe 16 GB/s. DP2·DP4는 4~16 노드 | system-specs |
| 요청 모델 | open-loop, idle 지수분포 평균 60 s, 컨텍스트 평균 16K, 턴당 +1K·출력 256 | 16K KV = 5.0 GiB. 동시 세션 ≈ 250~330 |
| 메모리 압박 | HBM KV 풀 ≈ 425 GiB(≈85 세션분) + DRAM 922 GiB(≈184 세션분) | 동시 세션 KV 1.3~1.6 TiB는 HBM+DRAM도 초과 → SSD 사용 |
| 재사용 | 공유 문서 30%, 그중 50% non-prefix, 선택 재계산 15% 토큰 [가정] | DP3 조건 |
| 부하·SLO | Q1 Max SLO goodput(이용률 0.8), Q3 B1 Max SLO goodput의 90% 부하, TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms | |

Phase: P1 정상 multi-turn(DP1) · P2 burst(DP2) · P3 공유 문서 wave(DP3) · P4 노드 확장 2→16(DP4) · 변경 시나리오(Q5). 별은 이 regime에서의 조건부 별이다.

## 4. 이론 예상값 산출 방식과 후보 파라미터

계산 구조(`theory_model.py`): ① 반환 세션 hit = LRU stack distance(idle ~ Exp(60 s)) ② 처리 한계 λ = min(GPU 1/0.113 s, DRAM 링크 51 GB/s ÷ 이동 바이트, SSD 링크 12.8 GB/s ÷ 이동 바이트), goodput = 0.8 × 256 × λ ③ TTFT P99 = prefill 41 ms + 결정 지연 + 99% 복원 경로 ÷ (1 − 링크 이용률), TPOT P99 = 18.1 ms × (1 + 0.5 × 이용률) ④ SE = min(1, 결정 용량 ÷ 요구 결정률).

| 후보 | 파라미터(가정) | 근거 |
|---|---|---|
| DP1 1안 | θ 1.1, w 0.5, π 0, 결정 3 ms, watermark 0.80 | 임계 trigger로 HBM 압박 구간 단축, 접근 특성 구분 한계 |
| DP1 2안 | θ 1.3, w 0.3, π 0.6, ω 0.3, watermark 0.95 | 접근 특성 기반 prefetch(요구 70%에서 낭비 차감), snapshot stale로 HBM 확보 지연 |
| DP2 1안 / 2안 | 유휴 P 노드 활용 u_P 0.2 / 0.5, 결정 8 ms / 0 + Re-plan P99 40 ms, watermark 0.85 / 0.92 | 실시간 결정(지연 있음) / 사전 계획(Re-plan 31%) |
| DP3 1안 / 2안 | 공유 문서 dedup 0.70, GPU +27 ms·체인 tail 25 ms / GPU +3 ms, watermark 0.60 / 0.75 | 관련 KV만 보유·요청마다 체인 / 분석 1회+조회·사전 보유 |
| DP4 1안 / 2안 | CXL 풀이 SSD 대체(노드 유효 63 GB/s), 교차 라우팅 25% 재계산 제거, 제어 평면 RPC 7 µs / 락 P99 804 µs | 제어 평면은 요청당 ms 이하 |

한계: 후보 파라미터는 가정이라 값이 바뀌면 별이 바뀐다. 큐잉은 1/(1−ρ)로 근사했고 연속 배칭·chunked prefill 세부는 반영하지 않았다. 이용률 상한 0.8, idle 평균 60 s, 공유 문서 30%는 설계값이다.

## 5. DP별 결과 (B0 · B1 · 후보, 이론 예상값)
""")
names = {"DP1": ("상태 관측+이동 결정 통합", "관측·결정 분리"), "DP2": ("스케줄링 시점 결정", "사전 계획 결정"),
         "DP3": ("Pipe-and-Filter", "Shared Repository"), "DP4": ("중앙 서버 중재", "락 기반 직접 접근")}
qs = {"DP1": ["Q1", "Q2", "Q3", "Q5"], "DP2": ["Q1", "Q2", "Q3", "Q4"], "DP3": ["Q1", "Q2", "Q3"], "DP4": ["Q1", "Q3", "Q4"]}
for dp in ("DP1", "DP2", "DP3", "DP4"):
    w("### %s (1안 %s / 2안 %s)\n" % (dp, names[dp][0], names[dp][1]))
    w("| QA | B0 | B1 | 1안 (이론 → 별, 소유자) | 2안 (이론 → 별, 소유자) |")
    w("|---|---|---|---|---|")
    for q in qs[dp]:
        t1, t2 = cd.THEORY[(dp, 1)][q], cd.THEORY[(dp, 2)][q]
        if q == "Q1":
            b0c, b1c = n0(t1["b0"]) + " tok/s", n0(t1["b1"]) + " tok/s"
        elif q == "Q2":
            b0c = b1c = n0(t1["b1"]) + " GiB"
        elif q == "Q3":
            b0c, b1c = "과부하", "TTFT %.2f s · TPOT %.1f ms" % (t1["b1_ttft"], t1["b1_tpot"])
        elif q == "Q4":
            b0c = b1c = "SE %.0f%%" % t1["b1"]
        else:
            b0c = b1c = "—"
        cells = []
        for k in (1, 2):
            t = cd.THEORY[(dp, k)][q]
            extra = ""
            if q == "Q3":
                extra = " · r %.2f" % t["r"]
            cells.append("%s%s → %s (소유자 %s)" % (cd.cell_text(dp, k, q), extra, cd.fmt_star(cd.theory_star(dp, k, q)), cd.fmt_star(cd.OWNER[(dp, k)][q])))
        w("| %s | %s | %s | %s | %s |" % (q, b0c, b1c, cells[0], cells[1]))
    w("")
w("""## 6. 참고: 기존 중립 벤치마크 시뮬레이션 값 (새 시나리오 아님)

8K 입력·batch 32·압박 없는 조건의 H100+B200 시뮬레이션이다. 새 기준·새 Baseline과 직접 비교하지 않는다.

| 후보 | 기존 시뮬 |
|---|---|""")
for k, v in cd.OLD_SIM.items():
    w("| %s %d안 | %s |" % (k[0], k[1], v))
w("""
## 7. 알려진 문제

1. DP2·DP4 페이지의 일부 장단점 문구가 확장성을 `(Q5)`로 적고 있다(표의 번호는 Q4). 수정하지 않았다.
2. 슬라이드의 소유자 코멘트 박스(파란 글씨)는 그대로 두었다. LibreOffice 렌더링에서는 표가 PowerPoint보다 커서 위치가 어긋나 보일 수 있다.
3. 이론 예상값은 소유자 별과 일부 어긋난다(덱 마지막 정합표 참조): DP2 Q3(순위 반대), DP3 Q1·Q3와 DP4 Q1·Q3·Q4(두 안 동일).
4. DP1 Q5의 module·M/M은 기존 구현 측정(시나리오 4종 기준)이라 새 시나리오 3종으로 다시 재야 한다.
""")
open("qa-criteria-v4.md", "w", encoding="utf8").write("\n".join(out))
print("written", len(out), "lines")
