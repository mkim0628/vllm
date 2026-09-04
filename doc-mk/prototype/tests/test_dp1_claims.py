"""DP1 문서의 주장을 실행 가능한 단언으로 바꾼 테스트.

각 테스트는 doc-mk/vllm-dp1-placement-decision-basis.md 의 특정 절에 대응한다.
**테스트가 깨지면 코드가 틀렸거나 문서가 틀린 것이다.** 어느 쪽인지 판단해야
하며, 문서 쪽이면 문서를 고친다 — 별점을 맞추려고 테스트를 고치지 않는다.

의존성 없음. 다음 중 아무 방법으로나 실행된다.
    python -m unittest discover -s doc-mk/prototype -v
    .venv/bin/python -m pytest doc-mk/prototype/tests -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dp1 import workload  # noqa: E402
from dp1.harness import check_anonymity, run  # noqa: E402
from dp1.model import (  # noqa: E402
    AnonymityViolation,
    ObservableRequest,
    Placement,
    TierTable,
    TripwireView,
)
from dp1.object_indexed import (  # noqa: E402
    CostModel,
    HeuristicClassifier,
    ObjectIndexedPlacer,
)
from dp1.tier_indexed import TierIndexedPlacer  # noqa: E402


def c1(table, **kw):
    return TierIndexedPlacer(table, **kw)


def c2(table, **kw):
    return ObjectIndexedPlacer(table, **kw)


def run_both(scenario, **c1kw):
    t1 = TierTable()
    m1 = run(c1(t1, **c1kw), t1, scenario)
    t2 = TierTable()
    m2 = run(c2(t2), t2, scenario)
    return (m1, t1), (m2, t2)


def bw(table, tier):
    return table.specs[tier].bandwidth_gbps


# ==========================================================================
# 3.3 양립 불가 논증
# ==========================================================================
class TestExclusivity(unittest.TestCase):
    """DP1 3.3 — 두 후보가 대등한 대안인 이유."""

    def test_invariant_conflict_gives_opposite_decisions(self):
        """3.3-① 상위 tier full + 더 높은 등급 도착 → 결정이 정반대여야 한다."""
        scenario, target = workload.invariant_conflict()
        (m1, t1), (m2, t2) = run_both(scenario)

        self.assertEqual(
            m1.placement_log[target], "CUSTOM_HBM",
            "C1은 자원 제약이 불변식이므로 새 객체를 하위 tier로 흘려야 한다",
        )
        self.assertEqual(
            m2.placement_log[target], "HBM",
            "C2는 객체 계약이 불변식이므로 자리를 만들어서라도 목표 tier에 넣어야 한다",
        )
        self.assertNotEqual(m1.placement_log[target], m2.placement_log[target])
        self.assertEqual(m1.evictions, 0, "C1은 기존 점유자를 밀어내지 않는다")
        self.assertGreater(m2.evictions, 0, "C2는 계약을 지키려 점유자를 밀어낸다")

    def test_c1_never_reads_the_request(self):
        """3.3-② C1의 결정 단위에는 소유자 개념이 없다 — 요청을 읽지 않는다."""
        placer = c1(TierTable())
        self.assertTrue(
            check_anonymity(placer),
            "C1이 요청 속성을 읽었다면 더 이상 익명 요청 구조가 아니다",
        )

    def test_c2_must_read_the_request(self):
        """C2는 반드시 요청을 읽는다 — 읽지 않으면 등급을 만들 수 없다."""
        placer = c2(TierTable())
        with self.assertRaises(AnonymityViolation):
            placer.place(1, TripwireView())

    def test_c2_can_only_mimic_c1_by_paying_its_own_cost(self):
        """3.3-③ 반박 ② — 동작은 같아져도 비용은 남는다. 상위호환이 아니다."""
        scenario = workload.heterogeneous()
        t1 = TierTable()
        base = run(c1(t1), t1, scenario)
        t2 = TierTable()
        mimic = run(
            c2(t2, classifier=HeuristicClassifier(single_class=True), mimic_c1=True),
            t2, scenario,
        )

        self.assertEqual(
            base.placement_log, mimic.placement_log,
            "C1의 정책을 그대로 쓰면 배치 결과는 같아진다",
        )
        self.assertEqual(base.object_reads, 0)
        self.assertGreater(
            mimic.object_reads, 0,
            "흉내를 내도 분류 파이프라인 비용은 그대로 지불한다",
        )
        self.assertGreater(
            mimic.messages_per_decision, base.messages_per_decision,
            "같은 결과를 내면서 더 비싸다 = C1보다 비싼 C1",
        )

    def test_c1_cannot_mimic_c2_because_the_information_does_not_exist(self):
        """3.3-③ 역방향 — 미래 정보는 관측 표면에 존재하지 않는다."""
        obs_fields = set(ObservableRequest.__dataclass_fields__)
        for future in ("actual_output_len", "reuse_count", "session_continues"):
            self.assertNotIn(
                future, obs_fields,
                f"'{future}'는 할당 시점에 관측 불가능하므로 관측 표면에 있으면 안 된다",
            )


# ==========================================================================
# QA1 — 배치 품질
# ==========================================================================
class TestQA1PlacementQuality(unittest.TestCase):
    def test_c2_separates_hot_and_cold_on_heterogeneous_workload(self):
        """이질 워크로드에서 C2의 구분 능력이 드러난다."""
        (m1, _), (m2, _) = run_both(workload.heterogeneous())
        self.assertGreater(m2.separation_ratio, m1.separation_ratio)
        self.assertGreater(
            m2.separation_ratio, 5.0,
            "대역폭 요구 상위 20%가 하위 80%보다 훨씬 빠른 tier를 받아야 한다",
        )

    def test_grade_counts(self):
        """C1은 등급 개념이 없고(1종), C2는 2^3 = 8종을 구분할 수 있다."""
        self.assertEqual(c2(TierTable()).distinct_grades, 8)
        t = TierTable()
        m1 = run(c1(t), t, workload.heterogeneous())
        self.assertEqual(m1.distinct_grades, 1, "C1의 결정에는 등급이 붙지 않는다")

    def test_separation_gain_vanishes_on_homogeneous_workload(self):
        """9장 선택 조건 — 균질 워크로드에서는 구분의 이득이 사라진다."""
        (m1, _), (m2, _) = run_both(workload.homogeneous())
        self.assertAlmostEqual(m2.separation_ratio, 1.0, places=2)
        self.assertAlmostEqual(m1.separation_ratio, 1.0, places=2)

    def test_pure_c2_reads_tier_state_only_downward(self):
        """실측으로 정정된 발견 — C2도 tier 상태를 본다. 다만 아래로만 본다.

        계약이 지시한 tier가 차면 하위로 내려가지만, 상위가 비어 있어도
        올라가지 않는다. 그래서 한 등급이 워크로드를 지배하면 빠른 tier가
        비어 있는데도 쓰지 않는다.
        """
        (m1, _), (m2, _) = run_both(workload.homogeneous())
        self.assertGreater(
            m1.bandwidth_match, m2.bandwidth_match,
            "순수 C2는 계약이 지시한 tier 아래로만 움직이므로 빈 상위 tier를 놓친다",
        )

    def test_upgrade_knob_trades_utilization_against_separation(self):
        """"적당히 보게" 만들 수 있다 — 그러나 공짜가 아니다.

        계약을 하한으로 보고 위쪽 여유를 쓰게 하면(upgrade_if_free) 총량 활용은
        올라가지만 구분 능력은 무너진다. 빈 자리를 먼저 온 요청이 가져가므로
        **도착 순서가 등급을 이기기** 때문이다.
        """
        scenario = workload.heterogeneous()
        results = {}
        for label, kw in [
            ("pure", {}),
            ("headroom25", {"upgrade_if_free": True, "upgrade_headroom": 0.25}),
            ("open", {"upgrade_if_free": True}),
        ]:
            table = TierTable()
            results[label] = run(c2(table, **kw), table, scenario)

        self.assertLess(results["pure"].bandwidth_match, results["open"].bandwidth_match)
        self.assertGreater(results["pure"].separation_ratio,
                           results["open"].separation_ratio)
        # headroom은 두 값 사이를 잇는 손잡이다
        self.assertLess(results["headroom25"].separation_ratio,
                        results["pure"].separation_ratio)
        self.assertGreater(results["headroom25"].separation_ratio,
                           results["open"].separation_ratio)

    def test_proper_cost_model_has_no_size_bias(self):
        """steelman한 C2에는 크기 편향이 없다 — 크기는 가치와 가격에서 상쇄된다.

        (초기 구현의 "빈자리 있으면 위로" 규칙은 등급도 크기도 보지 않는 약한
        형태였고, 거기서 나온 크기 편향은 구조가 아니라 구현 아티팩트였다.)
        """
        scenario = workload.heterogeneous()
        t_naive = TierTable()
        naive = run(c2(t_naive, upgrade_if_free=True), t_naive, scenario)
        t_cost = TierTable()
        cost = run(c2(t_cost, cost_model=CostModel(reserve_for_future=True)),
                   t_cost, scenario)

        def avg_bw(metrics, table, ids):
            vals = [table.specs[metrics.placement_log[i]].bandwidth_gbps for i in ids]
            return sum(vals) / len(vals)

        shorts = [f"S{i}" for i in range(48)]
        longs = [f"L{i}" for i in range(6)]

        # 약한 구현: 작은 요청이 상위 tier를 잠식해 큰 요청과 평균이 비슷해진다
        self.assertLess(
            avg_bw(naive, t_naive, longs) / avg_bw(naive, t_naive, shorts), 1.5
        )
        # 제대로 된 비용 모델: 강도가 높은 큰 요청이 경쟁에서 이긴다
        self.assertGreater(
            avg_bw(cost, t_cost, longs) / avg_bw(cost, t_cost, shorts), 3.0
        )

    def test_discrimination_requires_holding_fast_tiers_back(self):
        """steelman 후 남는 구조적 제약 — 구분은 유보를 요구한다.

        유보하지 않으면 먼저 온 저강도 요청이 상위 tier를 채워 구분이 C1 수준으로
        떨어진다. 유보하면 구분이 오르지만 저부하 구간에서 빠른 tier를 비워 둔다.
        적정 유보량은 아직 오지 않은 요청의 분포에 달려 있어 관측으로 정할 수 없다.
        """
        het = workload.heterogeneous()
        t1 = TierTable(); base = run(c1(t1), t1, het)
        t2 = TierTable()
        no_hold = run(c2(t2, cost_model=CostModel()), t2, het)
        t3 = TierTable()
        hold = run(c2(t3, cost_model=CostModel(reserve_for_future=True)), t3, het)

        # 유보 없이는 객체 축의 이득이 사라진다 (C1과 같은 수준)
        self.assertLess(abs(no_hold.separation_ratio - base.separation_ratio), 0.5)
        # 유보하면 구분이 크게 오른다
        self.assertGreater(hold.separation_ratio, 3 * base.separation_ratio)

        # 그 대가: 균질(저부하) 워크로드에서 빠른 tier를 비워 둔다
        hom = workload.homogeneous()
        t4 = TierTable()
        hold_hom = run(c2(t4, cost_model=CostModel(reserve_for_future=True)), t4, hom)
        t5 = TierTable()
        free_hom = run(c2(t5, cost_model=CostModel()), t5, hom)
        self.assertLess(hold_hom.bandwidth_match, free_hom.bandwidth_match)

    def test_naive_upgrade_rule_has_a_small_object_bias(self):
        """상향 규칙의 이진 판정은 작은 객체에 유리한 편향을 내장한다.

        short(32블록)는 long(2048블록)이 못 들어가는 틈에도 들어간다.
        C1의 점유율 페널티는 그 편향을 완화하므로 short가 여러 tier로 흩어진다.
        """
        scenario = workload.heterogeneous()
        t1 = TierTable(); base = run(c1(t1), t1, scenario)
        t2 = TierTable(); openv = run(c2(t2, upgrade_if_free=True), t2, scenario)

        def short_tiers(metrics):
            return {metrics.placement_log[f"S{i}"] for i in range(48)}

        def avg_bw(metrics, table, ids):
            vals = [table.specs[metrics.placement_log[i]].bandwidth_gbps for i in ids]
            return sum(vals) / len(vals)

        shorts = [f"S{i}" for i in range(48)]
        longs = [f"L{i}" for i in range(6)]

        self.assertGreater(
            avg_bw(openv, t2, shorts), avg_bw(base, t1, shorts),
            "상향 규칙에서는 작은 요청이 더 빠른 tier를 차지한다",
        )
        self.assertGreaterEqual(
            len(short_tiers(base)), 3,
            "C1은 점유율 페널티로 작은 요청을 여러 tier에 흩뿌린다",
        )
        self.assertLessEqual(
            len(short_tiers(openv)), 2,
            "상향 규칙은 작은 요청을 상위 tier에 몰아넣는다",
        )
        # 큰 요청만 보면 오히려 C2가 낫다 — C1의 페널티가 상위 tier를 덜 채운다
        self.assertGreater(avg_bw(openv, t2, longs), avg_bw(base, t1, longs))

    def test_naive_upgrade_rule_separates_worse_than_c1(self):
        """약한 상향 규칙은 C1보다도 구분을 못 한다 (구현 아티팩트의 사례).

        "빈 자리가 있으면 무조건 위로"는 초반 도착자가 상위 tier를 독식하게
        만든다. C1은 최소한 점유율 페널티로 분산이라도 한다.
        """
        scenario = workload.heterogeneous()
        t1 = TierTable(); base = run(c1(t1), t1, scenario)
        t2 = TierTable(); openv = run(c2(t2, upgrade_if_free=True), t2, scenario)
        self.assertLess(openv.separation_ratio, base.separation_ratio)


# ==========================================================================
# QA2 — 결정 정보 비용
# ==========================================================================
class TestQA2InformationCost(unittest.TestCase):
    def test_message_counts_match_the_sequence_diagram(self):
        """4.3 시퀀스 — C1은 5개, C2는 7개(경합 시 9개)."""
        t = TierTable()
        d1 = c1(t).place(4)
        self.assertEqual(d1.messages, 5)
        self.assertEqual(d1.state_reads, 1)
        self.assertEqual(d1.object_reads, 0)
        self.assertEqual(d1.branches, 0)

        t2 = TierTable()
        obs = ObservableRequest("r", 16384, 4096, "chat", "m", 0)
        d2 = c2(t2).place(4, obs)
        self.assertEqual(d2.messages, 7)
        self.assertEqual(d2.object_reads, 1)
        self.assertGreaterEqual(d2.branches, 1)

    def test_c1_information_cost_is_independent_of_request_count(self):
        """C1의 갱신 비용은 O(T)로 요청 수와 무관하다."""
        small = workload.homogeneous(n=40, steps=8)
        large = workload.homogeneous(n=400, steps=8)
        t1 = TierTable(); a = run(c1(t1), t1, small)
        t2 = TierTable(); b = run(c1(t2), t2, large)
        self.assertEqual(a.refresh_items, b.refresh_items)
        self.assertEqual(a.object_reads, 0)
        self.assertEqual(b.object_reads, 0)

    def test_c2_information_cost_scales_with_request_count(self):
        """C2의 분류 비용은 요청 수에 비례한다."""
        small = workload.homogeneous(n=40, steps=8)
        large = workload.homogeneous(n=400, steps=8)
        t1 = TierTable(); a = run(c2(t1), t1, small)
        t2 = TierTable(); b = run(c2(t2), t2, large)
        self.assertGreater(b.object_reads, a.object_reads * 5)

    def test_observability_ratio_of_the_feature_set(self):
        """부록 D — 특성 집합 선택이 관측 불가 비율을 결정한다.

        여기서 쓴 휴리스틱은 3개 중 2개가 확정 관측값이고, 구분력의 핵심인
        long_lived만 추정이다.
        """
        clf = HeuristicClassifier()
        self.assertAlmostEqual(clf.observable_ratio, 2 / 3, places=6)
        unobservable = [f.name for f in clf.features if not f.observable]
        self.assertEqual(unobservable, ["long_lived"])

    def test_classifier_cannot_see_the_oracle(self):
        """분류기는 미래 정보에 접근할 수 없다 — 타입으로 막혀 있다."""
        req = workload.make_request("x", 1024, 3000, max_tokens=128)
        self.assertFalse(hasattr(req.obs, "actual_output_len"))
        grade = HeuristicClassifier().classify(req.obs)
        # max_tokens(128)만 보고 short으로 판정한다. 실제로는 3000토큰짜리다.
        self.assertFalse(grade[2], "관측 표면만 보면 long_lived를 알 수 없다")
        self.assertEqual(req.oracle.actual_output_len, 3000)


# ==========================================================================
# QA3 — 적응성 / 자기 교정
# ==========================================================================
class TestQA3Adaptivity(unittest.TestCase):
    def test_reservation_counter_is_required_to_hold_c1_invariant(self):
        """스텝 내 예약이 없으면 C1이 자기 불변식(자원 제약)을 위반한다."""
        scenario = workload.burst()
        t_off = TierTable()
        off = run(c1(t_off, reserve_within_step=False), t_off, scenario)
        t_on = TierTable()
        on = run(c1(t_on), t_on, scenario)

        self.assertGreater(
            off.overcommits, 0,
            "예약 없이 스텝 내 결정을 내리면 tier 용량을 넘겨 커밋한다",
        )
        self.assertEqual(on.overcommits, 0)
        self.assertEqual(off.herding_first_step, 1.0, "전부 한 tier로 몰린다")
        self.assertLess(on.herding_first_step, off.herding_first_step)

    def test_c2_grade_is_sticky_and_can_invert_the_right_answer(self):
        """오분류가 수명 내내 고착된다 — 부록 D.4.

        max_tokens만 보면 실제로 오래 사는 요청을 짧다고 판정하고,
        그 판정이 교정되지 않는다.
        """
        scenario = workload.misclassification()
        (m1, t1), (m2, t2) = run_both(scenario)

        long_lived = m2.placement_log["false_short0"]   # 실제 3000 토큰
        short_lived = m2.placement_log["false_long0"]   # 실제 100 토큰
        self.assertLess(
            bw(t2, long_lived), bw(t2, short_lived),
            "C2는 실제로 오래 사는 요청에 더 느린 tier를 준다 (오분류가 뒤집힌 채 고착)",
        )
        self.assertEqual(
            m1.placement_log["false_short0"], m1.placement_log["false_long0"],
            "C1은 둘을 구분하지 못하므로 같은 tier에 둔다 — 대신 뒤집히지도 않는다",
        )

    def test_shared_prefix_breaks_the_c2_contract_silently(self):
        """QA3 예측 대상 오류 — 공유 블록은 최초 소유자 등급으로 굳는다."""
        scenario = workload.shared_prefix()
        (m1, _), (m2, _) = run_both(scenario)

        self.assertGreater(
            m2.shared_contract_violations, 0,
            "cold 소유자가 놓은 공유 블록을 hot 요청들이 읽으면 계약이 깨진다",
        )
        self.assertEqual(
            m1.shared_contract_violations, 0,
            "C1에는 계약이 없으므로 위반이 성립하지 않는다",
        )

    def test_c1_corrects_itself_once_the_state_is_refreshed(self):
        """C1은 상태가 바뀌면 다음 결정부터 자동으로 교정된다.

        동시에 그 교정이 **스텝 경계 갱신에 묶여 있다**는 것도 함께 보인다.
        갱신 전에는 포화를 보지 못한다 — 이것이 herding의 뿌리다.
        """
        table = TierTable()
        placer = c1(table)
        table.begin_step()
        first = placer.place(1)
        table.end_step()

        # 다른 주체가 그 tier를 가득 채운 상황을 만든다
        table.commit(
            Placement("bulk", first.tier, table.specs[first.tier].capacity_blocks)
        )

        stale = placer.place(1)
        self.assertEqual(
            stale.tier, first.tier,
            "스텝 경계 갱신 전에는 포화가 보이지 않는다 (staleness)",
        )

        table.begin_step()  # 상태 갱신
        after = placer.place(1)
        self.assertNotEqual(
            after.tier, first.tier,
            "갱신 후에는 포화된 tier를 더 이상 고르지 않아야 한다 — 자기 교정",
        )


# ==========================================================================
# QA4 — 설명 가능성 / 재현성
# ==========================================================================
class TestQA4Reproducibility(unittest.TestCase):
    def _placements(self, make, key):
        scenario = workload.heterogeneous()
        table = TierTable()
        return run(make(table), table, scenario, order_key=key).placement_log

    def test_c2_is_deterministic_across_arrival_orders(self):
        fwd = self._placements(c2, lambda r: r.req_id)
        rev = self._placements(c2, lambda r: r.req_id[::-1])
        self.assertEqual(fwd, rev, "등급이 같으면 순서가 달라도 같은 tier여야 한다")

    def test_c1_placement_depends_on_arrival_order(self):
        fwd = self._placements(c1, lambda r: r.req_id)
        rev = self._placements(c1, lambda r: r.req_id[::-1])
        same = sum(1 for k in fwd if fwd[k] == rev.get(k)) / len(fwd)
        self.assertLess(same, 1.0, "C1의 결정은 동시 상태에 의존하므로 재현되지 않는다")

    def test_decision_reason_is_one_label_for_c2(self):
        """C2는 근거가 등급 라벨 하나, C1은 상태 스냅샷이 필요하다."""
        t = TierTable()
        d1 = c1(t).place(4)
        self.assertNotIn("grade", d1.reason)
        t2 = TierTable()
        obs = ObservableRequest("r", 16384, 4096, "chat", "m", 0)
        d2 = c2(t2).place(4, obs)
        self.assertIn("grade", d2.reason)


# ==========================================================================
# 부록 D — 특성 집합과 hotness의 분해
# ==========================================================================
class TestAppendixD(unittest.TestCase):
    def test_read_volume_math_from_appendix_d6(self):
        """부록 D.6 — 총 읽기량과 스텝당 대역폭은 서로 다른 축이다."""
        a = workload.make_request("A", 32768, 200)     # 긴 프롬프트 + 짧은 출력
        b = workload.make_request("B", 1024, 4096)     # 짧은 프롬프트 + 긴 출력

        self.assertEqual(a.read_tokens(), 6_573_700)
        self.assertEqual(b.read_tokens(), 12_584_960)
        self.assertGreater(
            b.read_tokens(), a.read_tokens(),
            "총 읽기량은 B가 더 크다 — A를 cold라 부를 근거가 아니다",
        )
        self.assertGreater(
            a.peak_step_read_tokens(), b.peak_step_read_tokens(),
            "스텝당 대역폭 요구는 A가 압도적이다",
        )

    def test_hint_api_must_not_carry_observable_values(self):
        """부록 D.5 — 런타임이 이미 아는 값을 힌트로 받으면 API만 오염된다."""
        obs_fields = set(ObservableRequest.__dataclass_fields__)
        for already_known in ("prompt_len", "prefix_hit_blocks", "model", "attention"):
            self.assertIn(
                already_known, obs_fields,
                f"'{already_known}'는 관측 가능하므로 힌트로 받을 대상이 아니다",
            )


# ==========================================================================
# 11장 — 최종 선택 구조 (C1 + 보강)
# ==========================================================================
class TestSelectedStructure(unittest.TestCase):
    def test_reinforcement_improves_separation(self):
        """관측 가능한 컨텍스트 길이를 score에 넣으면 구분 능력이 회복된다."""
        scenario = workload.heterogeneous()
        t1 = TierTable(); base = run(c1(t1), t1, scenario)
        t2 = TierTable(); reinf = run(c1(t2, context_length_term=True), t2, scenario)
        self.assertGreater(reinf.separation_ratio, base.separation_ratio)

    def test_reinforced_c1_is_not_a_hybrid(self):
        """11장 혼합 판정 — 단일 진실 원천이 여전히 하나인가?

        보강을 켜도 불변식은 '자원 제약 우선' 그대로여야 한다. 상위 tier가
        가득 차면 아무리 대역폭 요구가 큰 요청이라도 하위 tier로 흘러야 한다.
        """
        scenario, target = workload.invariant_conflict()
        table = TierTable()
        m = run(c1(table, context_length_term=True), table, scenario)
        self.assertEqual(
            m.placement_log[target], "CUSTOM_HBM",
            "보강이 불변식을 바꾸면 그것은 보강이 아니라 혼합이다",
        )
        self.assertEqual(m.evictions, 0, "보강된 C1도 점유자를 밀어내지 않는다")

    def test_reinforcement_reads_only_one_observable_field(self):
        """보강은 등급을 만들지 않는다 — 관측값 하나를 가중치로 쓸 뿐이다."""
        table = TierTable()
        obs = ObservableRequest("r", 32768, 4096, "chat", "m", 0)
        d = c1(table, context_length_term=True).place(4, obs)
        self.assertEqual(d.object_reads, 1)
        self.assertEqual(d.grade, (), "보강된 C1의 결정에도 등급은 붙지 않는다")


if __name__ == "__main__":
    unittest.main(verbosity=2)
