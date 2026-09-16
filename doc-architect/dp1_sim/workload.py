"""워크로드 — opencode의 8종 툴과 시나리오 생성기.

설계 문서 §11의 평가 가정은 쓰지 않는다. 툴 타입과 분포를 여기서
독립적으로 정의한다.

[툴 선정] opencode의 permission 대상 툴은 bash·read·edit·glob·grep·
webfetch·task·todowrite·websearch·lsp·skill 이다. 이 중 **실행 시간
특성이 서로 구분되는 8종**을 고른다. 제외한 것과 이유:
  todowrite  메모리 내 상태 갱신 — 실질 0초라 유휴가 생기지 않는다
  websearch  webfetch와 같은 네트워크 왕복 등급
  lsp        read와 같은 로컬 I/O 등급
  skill      task와 같은 서브에이전트 등급
  write      edit에 포함시키지 않고 별도로 둔다 (쓰기 경로가 다르다)
남는 8종: read write edit glob grep bash webfetch task

[분포] 실행 시간은 lognormal을 쓴다 — 소프트웨어 실행 시간은 하한이
0이고 오른쪽 꼬리가 긴 것이 일반적이다. median과 sigma는 공개 실측이
없으므로 ASSUMED이지만, **상대적 크기 순서**는 근거가 있다:
  로컬 파일 I/O < ripgrep 스캔 < 네트워크 왕복 < 서브프로세스/서브에이전트
이 순서가 뒤집히지 않는 한 결론은 유지된다. 절대값이 결론을 바꾸는지는
run_eval.py 의 tool_latency_scale Sweep이 확인한다.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .core import AgentToolInfo, AttentionPrimitive, ATTENTION_PRIMITIVE_SET


@dataclass(frozen=True)
class ToolProfile:
    name: str
    median_s: float          # lognormal의 중앙값
    sigma: float             # lognormal의 log-스케일 표준편차 (분산의 크기)
    result_tokens_median: int
    result_tokens_sigma: float
    terminal_prob: float     # 이 툴 뒤에 세션이 끝날 확률
    rationale: str


#: opencode 8종. median_s 오름차순 = 로컬 I/O -> 검색 -> 네트워크 -> 서브프로세스.
TOOLS: dict[str, ToolProfile] = {
    "read": ToolProfile(
        "read", 0.02, 0.5, 2000, 0.8, 0.02,
        "로컬 파일 읽기 한 번. 페이지 캐시에 있으면 수 ms, 없으면 수십 ms"),
    "write": ToolProfile(
        "write", 0.04, 0.5, 50, 0.4, 0.06,
        "파일 쓰기 + fsync. 읽기보다 비싸지만 여전히 로컬 I/O 등급"),
    "edit": ToolProfile(
        "edit", 0.06, 0.6, 200, 0.6, 0.05,
        "문자열 매칭 후 부분 치환 — 읽기와 쓰기를 모두 포함한다"),
    "glob": ToolProfile(
        "glob", 0.15, 0.8, 400, 0.9, 0.02,
        "ripgrep의 파일 순회. 레포 크기에 비례하고 .gitignore를 탄다"),
    "grep": ToolProfile(
        "grep", 0.40, 1.0, 800, 1.1, 0.02,
        "ripgrep의 내용 스캔. 파일 순회보다 무겁고 패턴/레포 크기에 민감"),
    "webfetch": ToolProfile(
        "webfetch", 1.20, 0.9, 3000, 0.7, 0.03,
        "네트워크 왕복 + 본문 변환. 로컬 I/O보다 두 자릿수 느리다"),
    "bash": ToolProfile(
        "bash", 1.50, 1.6, 600, 1.4, 0.08,
        "서브프로세스 실행. ls 수 ms부터 테스트 수십 초까지 — 분산이 가장 크다"),
    "task": ToolProfile(
        "task", 25.0, 1.2, 1000, 0.8, 0.25,
        "서브에이전트 실행. 내부에서 LLM 호출이 여러 번 일어난다"),
}

#: 오프로드 가능한 재활성 연산을 받는 툴 — 결과가 곧바로 Attention 대상이 된다.
_FULL_ATTN = frozenset(ATTENTION_PRIMITIVE_SET)
_PARTIAL_ATTN = frozenset({AttentionPrimitive.QK_GEMM, AttentionPrimitive.AV_GEMM})


@dataclass(frozen=True)
class Scenario:
    name: str
    tool_mix: dict[str, float]
    arrival_rate_per_s: float
    turns_median: int
    context_tokens_median: int
    context_tokens_sigma: float
    description: str


SCENARIOS: list[Scenario] = [
    Scenario(
        "interactive_coding",
        {"read": 0.30, "edit": 0.25, "grep": 0.15, "glob": 0.10,
         "write": 0.10, "bash": 0.08, "webfetch": 0.01, "task": 0.01},
        arrival_rate_per_s=0.09, turns_median=12,
        context_tokens_median=16000, context_tokens_sigma=0.5,
        description="짧은 툴 위주. 유휴가 짧아 하위 계층 왕복을 회수할 시간이 없다"),
    Scenario(
        "deep_research",
        {"webfetch": 0.40, "task": 0.20, "read": 0.15, "grep": 0.10,
         "glob": 0.05, "edit": 0.05, "write": 0.03, "bash": 0.02},
        arrival_rate_per_s=0.035, turns_median=8,
        context_tokens_median=48000, context_tokens_sigma=0.4,
        description="네트워크·서브에이전트 위주. 유휴가 길어 깊은 계층이 값을 한다"),
    Scenario(
        "build_test_loop",
        {"bash": 0.55, "read": 0.15, "edit": 0.15, "grep": 0.06,
         "write": 0.05, "glob": 0.02, "task": 0.01, "webfetch": 0.01},
        arrival_rate_per_s=0.05, turns_median=15,
        context_tokens_median=24000, context_tokens_sigma=0.6,
        description="bash 지배. 같은 툴 이름 아래 실행 시간 분산이 가장 크다"),
    Scenario(
        "multi_agent",
        {"task": 0.45, "bash": 0.20, "read": 0.12, "webfetch": 0.10,
         "edit": 0.06, "grep": 0.04, "glob": 0.02, "write": 0.01},
        arrival_rate_per_s=0.04, turns_median=6,
        context_tokens_median=64000, context_tokens_sigma=0.5,
        description="멀티 에이전트. 서브에이전트 위주라 유휴가 수십 초 — 가장 깊은 계층까지 성립"),
    Scenario(
        "mixed_uniform",
        {k: 0.125 for k in TOOLS},
        arrival_rate_per_s=0.06, turns_median=10,
        context_tokens_median=32000, context_tokens_sigma=0.7,
        description="8종 균등. 한 세션 안에서 유휴 시간이 자릿수로 널뛴다"),
    Scenario(
        "long_context",
        {"read": 0.25, "grep": 0.20, "webfetch": 0.20, "task": 0.15,
         "edit": 0.10, "bash": 0.05, "glob": 0.03, "write": 0.02},
        arrival_rate_per_s=0.018, turns_median=9,
        context_tokens_median=96000, context_tokens_sigma=0.35,
        description="세션당 KV가 커 HBM 용량 압력이 지배적"),
]


class WorkloadGenerator:
    """세션과 턴을 만든다. 실제 실행 시간은 여기서 샘플링되며,
    C2의 추정 모델은 이 값을 사후 관측으로만 볼 수 있다."""

    def __init__(self, scenario: Scenario, rng: random.Random, tool_latency_scale: float = 1.0,
                 arrival_multiplier: float = 1.0):
        self.sc = scenario
        self.rng = rng
        self.tool_latency_scale = tool_latency_scale
        self.arrival_multiplier = arrival_multiplier
        names = list(scenario.tool_mix)
        weights = [scenario.tool_mix[n] for n in names]
        self._names, self._weights = names, weights

    def _lognormal(self, median: float, sigma: float) -> float:
        return median * math.exp(self.rng.gauss(0.0, sigma))

    def pick_tool(self) -> ToolProfile:
        return TOOLS[self.rng.choices(self._names, self._weights)[0]]

    def sample_tool_exec_s(self, tp: ToolProfile) -> float:
        return self._lognormal(tp.median_s, tp.sigma) * self.tool_latency_scale

    def sample_result_tokens(self, tp: ToolProfile) -> int:
        return max(16, int(self._lognormal(tp.result_tokens_median, tp.result_tokens_sigma)))

    def sample_decode_len(self, tp: ToolProfile) -> int:
        """이번 턴에 생성할 토큰 수. 무거운 툴을 부를수록 앞선 사고가 길다."""
        base = 60.0 + 40.0 * math.log10(1.0 + tp.median_s * 10)
        return max(8, int(self._lognormal(base, 0.7)))

    def sample_context_tokens(self) -> int:
        return max(2048, int(self._lognormal(
            self.sc.context_tokens_median, self.sc.context_tokens_sigma)))

    def sample_turns(self) -> int:
        return max(1, int(self._lognormal(self.sc.turns_median, 0.6)))

    def sample_interarrival_s(self, rate_multiplier: float = 1.0) -> float:
        rate = self.sc.arrival_rate_per_s * rate_multiplier * self.arrival_multiplier
        return self.rng.expovariate(max(1e-6, rate))

    def tool_info_for(self, tp: ToolProfile, is_terminal: bool) -> AgentToolInfo:
        """Agent 런타임이 **선언**하는 정보. 실제 실행 시간이 아니라
        툴 이름과 그에 대한 사전 기대값이다 (§5.1의 '선언 가능')."""
        return AgentToolInfo(
            tool_name=tp.name,
            expected_exec_seconds=tp.median_s * self.tool_latency_scale,
            expected_result_tokens=tp.result_tokens_median,
            is_terminal=is_terminal,
        )

    @staticmethod
    def next_op_primitives(tp: ToolProfile) -> frozenset:
        """재활성 시 이 KV가 받을 원시 연산 집합.

        Tool Result가 큰 툴일수록 Incremental Prefill이 커지지만,
        재활성 Attention 자체는 어느 툴이든 같은 원시 연산을 요구한다.
        """
        return _FULL_ATTN


# ─────────────────────────────────────────────── 사전 생성 trace
#
# 정책마다 rng 소비 순서가 달라지면 같은 seed라도 서로 다른 워크로드를
# 보게 되어 짝지은 비교가 무효가 된다. 그래서 워크로드를 **정책과 무관하게
# 먼저 생성**하고 모든 정책에 동일한 trace를 먹인다.

@dataclass
class TurnSpec:
    tool: ToolProfile
    result_tokens: int
    decode_len: int
    idle_s: float
    terminal: bool


@dataclass
class SessionSpec:
    sid: str
    arrival_s: float
    context_tokens: int
    turns: list["TurnSpec"]


def build_trace(scenario: Scenario, seed: int, horizon_s: float,
                tool_latency_scale: float = 1.0, arrival_multiplier: float = 1.0,
                burst: bool = False) -> list[SessionSpec]:
    """도착 시각과 모든 턴의 내용을 미리 확정한다."""
    rng = random.Random(seed)
    gen = WorkloadGenerator(scenario, rng, tool_latency_scale, arrival_multiplier)
    out: list[SessionSpec] = []
    now = 0.0
    idx = 0
    while now < horizon_s:
        mult = 1.0
        if burst:
            phase = (now / max(horizon_s, 1e-9)) * 4.0
            mult = 0.4 + 2.6 * (0.5 + 0.5 * math.sin(phase * math.pi))
        now += gen.sample_interarrival_s(mult)
        if now >= horizon_s:
            break
        idx += 1
        n_turns = gen.sample_turns()
        turns: list[TurnSpec] = []
        for i in range(n_turns):
            tp = gen.pick_tool()
            last = (i + 1) >= n_turns
            terminal = last or (rng.random() < tp.terminal_prob)
            turns.append(TurnSpec(
                tool=tp,
                result_tokens=gen.sample_result_tokens(tp),
                decode_len=gen.sample_decode_len(tp),
                idle_s=0.0 if terminal else gen.sample_tool_exec_s(tp),
                terminal=terminal,
            ))
            if terminal:
                break
        out.append(SessionSpec(
            sid=f"s{idx}", arrival_s=now,
            context_tokens=gen.sample_context_tokens(), turns=turns))
    return out


# ─────────────────────────────────────── 부하의 물리량 정의 (offered load)
#
# 도착률 배수는 시나리오마다 기준이 달라 시나리오 간 비교가 성립하지 않는다.
# 대신 **KV 수요량**을 부하의 축으로 쓴다 — DP1이 존재하는 이유가 곧
# "HBM이 살아 있는 KV를 다 담지 못한다"이므로, 그 비율이 이 DP의 부하다.
#
#   KV 압력 = (살아 있는 세션 KV의 시간평균) / (HBM 용량)
#
# 정책이 개입하기 전의 **제공 부하(offered load)** 로 정의해야 정책 간
# 비교가 성립한다. 에이전트 워크로드에서는 세션 수명이 유휴 시간에
# 지배되고 유휴는 trace에 확정되어 있으므로, trace만으로 계산할 수 있다.


def trace_kv_demand_bytes(trace: list["SessionSpec"], kv_bytes_per_token: int,
                          horizon_s: float) -> float:
    """trace에서 계산한 KV 수요의 시간평균 [bytes]. 정책과 무관하다.

    세션이 살아 있는 동안 점유하는 KV를 시간으로 적분하고 horizon으로 나눈다.
    턴 처리 시간은 유휴에 비해 작으므로 유휴 구간만으로 근사한다 — 따라서
    이 값은 **하한**이고, 실측 `kv_pressure`는 이보다 조금 크게 나온다.
    """
    total = 0.0
    for s in trace:
        ctx = s.context_tokens
        for t in s.turns:
            total += ctx * kv_bytes_per_token * t.idle_s
            ctx += t.result_tokens + t.decode_len
    return total / max(horizon_s, 1e-9)


def calibrate_arrival_by_gpu(scenario: Scenario, target_gpu_pressure: float,
                             measure, seeds: list[int],
                             lo: float = 0.05, hi: float = 64.0,
                             tol: float = 0.03, max_iter: int = 18) -> float:
    """목표 **GPU 압력**을 만드는 도착률 배수를 이분 탐색으로 찾는다.

    GPU 압력을 축으로 쓰는 이유 (측정으로 확인):
      - 모든 시나리오에서 **GPU가 KV보다 먼저 포화한다.** GPU 압력이 1에
        닿을 때 KV 압력은 1.7~3.5이고, 그 전까지는 KV가 HBM에 거의 다 들어간다.
        즉 배치 결정이 실재하는 구간은 GPU 포화 이후에 온다.
      - 도착률에 단조증가하고 1차원이라 안정적으로 풀린다.
      - 서빙 운영에서 실제로 보는 축이다.

    `measure(scenario, mult, seed) -> gpu_pressure` 를 주입받는다. 순환
    import을 피하려는 것이고, 대조군(as-is)으로 재는 것이 규약이다 —
    정책이 GPU를 비우면 압력이 내려가므로 정책별로 재면 좌표가 흔들린다.
    """
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        got = sum(measure(scenario, mid, sd) for sd in seeds) / len(seeds)
        if abs(got - target_gpu_pressure) / max(target_gpu_pressure, 1e-9) < tol:
            return mid
        if got < target_gpu_pressure:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def calibrate_arrival(scenario: Scenario, target_kv_pressure: float,
                      hbm_capacity_bytes: int, kv_bytes_per_token: int,
                      seeds: list[int], horizon_s: float,
                      tool_latency_scale: float = 1.0, burst: bool = False,
                      lo: float = 0.01, hi: float = 200.0, tol: float = 0.02,
                      max_iter: int = 40) -> float:
    """목표 KV 압력을 만드는 도착률 배수를 이분 탐색으로 찾는다.

    KV 수요는 도착률에 단조증가하므로 이분 탐색이 성립한다.
    """
    target_bytes = target_kv_pressure * hbm_capacity_bytes

    def demand(mult: float) -> float:
        vals = [trace_kv_demand_bytes(
            build_trace(scenario, sd, horizon_s, tool_latency_scale, mult, burst),
            kv_bytes_per_token, horizon_s) for sd in seeds]
        return sum(vals) / len(vals)

    for _ in range(max_iter):
        mid = (lo + hi) / 2
        d = demand(mid)
        if abs(d - target_bytes) / max(target_bytes, 1e-9) < tol:
            return mid
        if d < target_bytes:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2
