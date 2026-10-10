"""Single source of the DP4 benchmark scenarios (Common CB-1..3 realization + DP4-specific rows).

knobs (all optional, defaults in DEFAULT_KNOBS):
  n_p, n_d          prefill / decode node counts
  in_tokens, out_tokens
  bg0, bg1          background load on node KV links and pool: bg(t) = bg0 + (bg1-bg0)*t/horizon
  kv_share          KV share of pool traffic and object count (1.0 = KV only)
  turns, reuse      agent multi-turn sessions with History KV (reuse on)
  hot               shared hot prefix (shared_prefix_frac of requests share shared_prefix_tokens)
  pool_occ          pool occupancy before the run (>= evict_threshold -> every publish needs an evict section)
  block_tokens, lock_stripes, server_threads    parameter overrides (sweep rows)
  fail              None | "server" | "lockholder"
  fail_rebuild      server loss with index rebuild (server_rebuild_s) instead of process restart
  lease             None (as-published, lock never freed) | seconds (lease supplement)
  reference         True for rows that are only a reference for a derived metric (Scaling Efficiency)
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_KNOBS = dict(
    n_p=1, n_d=1, in_tokens=8192, out_tokens=256, bg0=0.0, bg1=0.0, kv_share=1.0, turns=1, reuse=False,
    hot=False, pool_occ=0.0, block_tokens=None, lock_stripes=None, server_threads=None,
    fail=None, fail_rebuild=False, lease=1.0, reference=False,
)


@dataclass(frozen=True)
class Scenario:
    name: str
    brief: str  # one line, <= 60 chars
    knobs: dict = field(default_factory=dict)
    exposes: str = ""
    cb_id: str = ""
    variants: tuple = ()  # ((suffix, knob overrides), ...)

    def __post_init__(self):
        assert len(self.brief) <= 60, (self.name, len(self.brief))

    def resolved(self, extra=None):
        k = dict(DEFAULT_KNOBS)
        k.update(self.knobs)
        if extra:
            k.update(extra)
        return k

    def rows(self):
        """-> [(row_name, resolved knobs)]; a scenario with variants yields one row per variant."""
        if not self.variants:
            return [(self.name, self.resolved())]
        return [(f"{self.name}[{suf}]", self.resolved(kn)) for suf, kn in self.variants]


def common_benchmark():
    return [
        Scenario("cb_kv_8k_b32", "KV만, 8K/256, batch 32, 링크 background 0.85",
                 dict(n_p=1, n_d=1, bg0=0.85, bg1=0.85),
                 "KV 이동 경로(링크/풀) 경합", "CB-1"),
        Scenario("cb_kv_8k_b32_ramp", "KV만, 8K/256, 링크 background 0.2→0.9 증가",
                 dict(n_p=1, n_d=1, bg0=0.2, bg1=0.9),
                 "시간에 따라 이동 경로 여유가 줄어드는 경우", "CB-2"),
        Scenario("cb_mixed_8k_b32", "KV50/LoRA15/MoE15/Agent10/Tool10 혼합, background 0.85",
                 dict(n_p=1, n_d=1, bg0=0.85, bg1=0.85, kv_share=0.5),
                 "객체 종류가 섞여 풀 트래픽·메타데이터 연산이 늘어나는 경우", "CB-3"),
    ]


def _n(name, n, brief_n):
    return Scenario(name, f"노드당 부하 고정, 노드 {brief_n}개 (P {n // 2} + D {n // 2})",
                    dict(n_p=n // 2, n_d=n // 2),
                    "Scalability: C1 서버 포화, C2 scan 비용 S×N")


def dp4_benchmark():
    two = dict(n_p=2, n_d=2)
    hot8 = dict(n_p=4, n_d=4, hot=True)
    return [
        Scenario("d4_agent_multiturn", "8턴 에이전트, History KV 누적 (reuse 켬, 별도 행)",
                 dict(two, turns=8, reuse=True),
                 "Baseline의 D→P 왕복 전송 vs 풀 공유"),
        Scenario("d4_hot_prefix_fanout", "긴 공통 prefix를 request의 90%가 공유",
                 dict(two, hot=True), "C1 서버 대기열, C2 hot 락 경합·refcount 갱신"),
        Scenario("d4_small_prompt_highqps", "512 in/64 out, 높은 request rate",
                 dict(two, in_tokens=512, out_tokens=64), "control plane 연산률 지배 영역"),
        Scenario("d4_node_scale_n2", "Scaling 기준 행: 노드 2개 (P1 + D1)",
                 dict(n_p=1, n_d=1, reference=True), "Scaling Efficiency 분모 (공식 시나리오 아님)"),
        _n("d4_node_scale_n4", 4, 4), _n("d4_node_scale_n8", 8, 8), _n("d4_node_scale_n16", 16, 16),
        Scenario("d4_block16", "block 16 tokens (블록당 연산 수 4배)", dict(two, block_tokens=16),
                 "블록당 control plane 연산 수 ∝ 1/block"),
        Scenario("d4_block256", "block 256 tokens (블록당 연산 수 1/4)", dict(two, block_tokens=256),
                 "블록당 control plane 연산 수 ∝ 1/block"),
        Scenario("d4_pool_full_eviction", "풀 점유 95%, publish마다 퇴출 연산", dict(two, pool_occ=0.95),
                 "refcount 경합, 퇴출 지연"),
        Scenario("d4_lock_stripes_1", "C2 락 stripe 1개 (hot prefix, 노드 8)", dict(hot8, lock_stripes=1),
                 "stripe 수의 contention vs scan 비용"),
        Scenario("d4_lock_stripes_8", "C2 락 stripe 8개 (hot prefix, 노드 8)", dict(hot8, lock_stripes=8),
                 "stripe 수의 contention vs scan 비용"),
        Scenario("d4_lock_stripes_512", "C2 락 stripe 512개 (hot prefix, 노드 8)", dict(hot8, lock_stripes=512),
                 "stripe 수의 contention vs scan 비용"),
        Scenario("d4_server_threads_2", "C1 서버 스레드 2개 (hot prefix, 노드 8)", dict(hot8, server_threads=2),
                 "중앙 직렬화의 확장 여지"),
        Scenario("d4_server_threads_4", "C1 서버 스레드 4개 (hot prefix, 노드 8)", dict(hot8, server_threads=4),
                 "중앙 직렬화의 확장 여지"),
        Scenario("d4_fail_server", "C1 메타데이터 서버 crash 후 복구", dict(two, fail="server"),
                 "가용성 창, SLO 위반 (C1 SPOF)",
                 variants=(("restart", dict(fail_rebuild=False)), ("node_loss", dict(fail_rebuild=True)))),
        Scenario("d4_fail_lockholder", "C2 락 보유 노드 crash (as-published / lease)", dict(two, fail="lockholder"),
                 "락 고착, 영향 범위",
                 variants=(("as_published", dict(lease=None)), ("lease", dict(lease=1.0)))),
    ]


def all_sets():
    return {"common_benchmark": common_benchmark, "dp4_benchmark": dp4_benchmark}
