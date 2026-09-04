"""DP1 문서에서 산정한 케이스들을 워크로드로 만든다.

각 시나리오는 DP1 문서의 특정 주장에 대응한다. 시나리오 이름 옆의 참조를
보면 어느 절을 검증하는지 알 수 있다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .model import BLOCK_TOKENS, ObservableRequest, Oracle, Request


@dataclass
class Scenario:
    name: str
    ref: str                       # DP1 문서의 어느 주장을 재현하는가
    arrivals: dict[int, list[Request]] = field(default_factory=dict)
    horizon: int = 0

    def add(self, step: int, req: Request) -> None:
        self.arrivals.setdefault(step, []).append(req)
        end = step + max(1, req.oracle.actual_output_len)
        self.horizon = max(self.horizon, end + 1)


def make_request(
    req_id: str,
    prompt_len: int,
    actual_output_len: int,
    *,
    max_tokens: int | None = None,
    endpoint: str = "chat",
    model: str = "m",
    prefix_hit_blocks: int = 0,
    prefix_group: str | None = None,
    attention: str = "full",
) -> Request:
    return Request(
        obs=ObservableRequest(
            req_id=req_id,
            prompt_len=prompt_len,
            max_tokens=max_tokens if max_tokens is not None else 4096,
            endpoint=endpoint,
            model=model,
            prefix_hit_blocks=prefix_hit_blocks,
            attention=attention,
        ),
        oracle=Oracle(actual_output_len=actual_output_len, prefix_group=prefix_group),
    )


# --------------------------------------------------------------------------
# 시나리오
# --------------------------------------------------------------------------
def homogeneous(n: int = 40, steps: int = 8) -> Scenario:
    """균질 워크로드 — 요청 간 편차가 작다. 구분의 이득이 작은 경우(9장 선택 조건)."""
    s = Scenario("homogeneous", "9장 선택 조건 — C1을 선택할 근거")
    for i in range(n):
        s.add(i % steps, make_request(f"h{i}", 1024, 256, max_tokens=512))
    return s


def heterogeneous(n_long: int = 6, n_short: int = 48, steps: int = 8) -> Scenario:
    """이질 워크로드 — long-context 소수 + 짧은 다수. C2의 QA1 이득이 나오는 경우."""
    s = Scenario("heterogeneous", "QA1 배치 품질")
    for i in range(n_long):
        s.add(i % steps, make_request(f"L{i}", 32768, 200, max_tokens=4096))
    for i in range(n_short):
        s.add(i % steps, make_request(f"S{i}", 512, 64, max_tokens=128))
    return s


def burst(n: int = 200) -> Scenario:
    """한 스텝에 대량 도착 — herding과 자기 불변식 위반 (QA3 감점 근거).

    기본 128(max_num_seqs)보다 크게 잡아 예약 카운터가 없을 때
    tier 용량을 넘겨 커밋하는 것까지 드러나게 한다."""
    s = Scenario("burst", "QA3 — 스텝 내 herding")
    for i in range(n):
        s.add(0, make_request(f"b{i}", 1024, 32, max_tokens=256))
    return s


def misclassification() -> Scenario:
    """max_tokens는 크게 잡았지만 실제로는 금방 끝나는 요청과 그 반대.

    부록 D.4 — max_tokens는 상한일 뿐이다. C2는 이 오차를 수명 내내 안고 간다.
    """
    s = Scenario("misclassification", "QA3 — 오분류 고착 / 부록 D.4")
    # 예측: long_lived(=max_tokens 4096) / 실제: 100토큰에서 EOS
    for i in range(8):
        s.add(0, make_request(f"false_long{i}", 2048, 100, max_tokens=4096))
    # 예측: short / 실제: 3000토큰까지 생성
    for i in range(8):
        s.add(0, make_request(f"false_short{i}", 2048, 3000, max_tokens=512))
    return s


def shared_prefix(n: int = 100, hot: int = 30) -> Scenario:
    """같은 system prompt를 공유하는 요청들. 최초 소유자가 cold일 때 계약이
    조용히 깨진다 (QA3 — 예측 대상 오류)."""
    s = Scenario("shared_prefix", "QA3 — 공유 블록의 계약 위반")
    # 최초 요청은 cold 성격 (짧은 단발)
    s.add(0, make_request("owner", 2048, 64, max_tokens=128,
                          prefix_group="sys", endpoint="batch"))
    # 이후 hot 요청들이 같은 prefix를 hit 한다
    for i in range(hot):
        s.add(1, make_request(f"hot{i}", 2048, 2000, max_tokens=4096,
                              prefix_hit_blocks=128, prefix_group="sys"))
    for i in range(n - hot - 1):
        s.add(1, make_request(f"cold{i}", 2048, 64, max_tokens=128,
                              prefix_hit_blocks=128, prefix_group="sys",
                              endpoint="batch"))
    return s


def invariant_conflict() -> tuple[Scenario, str]:
    """상위 tier가 가득 찬 상태에서 더 높은 등급의 객체가 도착하는 상황.

    DP1 3.3-① 불변식 충돌을 재현하는 최소 시나리오다.
      - C1의 불변식(자원 제약 우선) → 새 객체를 하위 tier로 흘린다
      - C2의 불변식(객체 계약 우선) → 기존 점유자를 밀어내고 자리를 만든다
    두 결정이 정반대가 되는지 확인한다.

    HBM 계약을 받는 등급은 (bandwidth_heavy, *, long_lived) 두 가지다.
    reuse=False 등급으로 HBM을 정확히 채운 뒤 reuse=True 등급을 보낸다.
    """
    s = Scenario("invariant_conflict", "3.3-① 불변식 충돌")
    # 8192 토큰 = 512 블록. 16개 × 512 = 8192 블록 = HBM 정확히 만원.
    for i in range(16):
        s.add(0, make_request(f"filler{i}", 8192, 4000, max_tokens=4096))
    # 같은 대역폭·수명 등급이지만 prefix 재사용이 있어 등급이 한 단계 높다.
    s.add(1, make_request("hot_arrival", 8192, 3000, max_tokens=4096,
                          prefix_hit_blocks=128))
    return s, "hot_arrival"


ALL_SCENARIOS = {
    "homogeneous": homogeneous,
    "heterogeneous": heterogeneous,
    "burst": burst,
    "misclassification": misclassification,
    "shared_prefix": shared_prefix,
}
