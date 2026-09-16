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
                 arrival_multiplier: float = 1.0, context_override: int = 0):
        self.context_override = context_override
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
        if self.context_override:
            # 부하 격자에서 context를 고정한 경우 — 분산 없이 그 값을 쓴다.
            return self.context_override
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
                burst: bool = False, context_tokens: int = 0) -> list[SessionSpec]:
    """도착 시각과 모든 턴의 내용을 미리 확정한다."""
    rng = random.Random(seed)
    gen = WorkloadGenerator(scenario, rng, tool_latency_scale, arrival_multiplier,
                            context_override=context_tokens)
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


# ─────────────────────────────────────────────────────────── 부하 정의
#
# 부하는 **배치 크기 x context 길이** 로 준다.
# LLM 서빙 벤치마크의 통상적인 축이다 (vLLM benchmark_serving 의
# --max-concurrency 와 입력/출력 길이, MLPerf Inference 의 고정 시퀀스 길이
# + 동시성 시나리오). 두 값이 곧 KV 총량과 step당 읽는 바이트를 정하므로
# DP1이 다루는 압력을 직접적으로 가른다.
#
#   KV 총량      = 배치 x context x KV/token (+ 세션당 상수 상태)
#   step 읽기    = 배치 x attended_tokens(context) x KV/token
#
# 과부하는 이 둘을 키워서 만든다. 도착률은 배치를 채우는 수단일 뿐
# 부하의 좌표가 아니다.

#: 부하 격자. 배치 크기 x context 길이.
BATCH_LEVELS = [1, 16, 64, 256]
CONTEXT_LEVELS = [16384, 32768, 131072, 524288]
