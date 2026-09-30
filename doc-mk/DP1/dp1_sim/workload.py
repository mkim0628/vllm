"""DP1 serving workloads, serialised as JSONL.

The *same* JSONL file drives
  * the real vLLM server through measure/dp1_client.py   -> A evidence
  * serving_sim.py (C1/C2/baselines)                      -> C projection
so C1/C2 and the real run share workload, initial state and runtime trace
(Evaluation §1, "same workload / same trace").

Turn k>0 of a session is released ``think_s`` seconds after turn k-1
completes (closed loop per session), as in agentic / multi-turn serving.
The ``behavior`` field is ground truth for analysis only; no policy sees it.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Turn:
    session: int
    turn: int
    new_tokens: int
    output_tokens: int
    arrival_s: float | None  # turn 0 only
    think_s: float  # turn>0: delay after previous turn completion
    last: bool
    behavior: str  # ground truth label ("hot"/"cold"/"single"), analysis only


@dataclass(frozen=True)
class WorkloadSpec:
    kind: str  # common | multiturn | hotness_flip | long_cold
    rate: float  # session (or request, for common) arrivals per second
    horizon_s: float = 300.0
    seed: int = 0
    # common benchmark (qa-evaluation-criteria.md §8)
    input_len: int = 8192
    output_len: int = 256
    # multi-turn knobs
    turns_min: int = 4
    turns_max: int = 12
    first_mean_tokens: int = 3000
    first_max_tokens: int = 12000
    turn_tokens_min: int = 100
    turn_tokens_max: int = 600
    out_min: int = 100
    out_max: int = 300
    hot_frac: float = 0.6
    hot_think_s: float = 3.0
    cold_think_s: float = 45.0


def _lognormal_mean(rng: random.Random, mean: float, sigma: float = 0.8) -> float:
    mu = math.log(mean) - sigma * sigma / 2
    return rng.lognormvariate(mu, sigma)


def generate(spec: WorkloadSpec) -> list[Turn]:
    # deterministic across processes (str hash() is salted per process)
    rng = random.Random(
        spec.seed * 1_000_003 + int(spec.rate * 1e6) + sum(map(ord, spec.kind))
    )
    out: list[Turn] = []
    t = 0.0
    sid = 0
    while True:
        t += rng.expovariate(spec.rate)
        if t > spec.horizon_s:
            break
        if spec.kind == "common":
            out.append(
                Turn(sid, 0, spec.input_len, spec.output_len, t, 0.0, True, "single")
            )
            sid += 1
            continue

        if spec.kind == "long_cold" and rng.random() < 0.7:
            # large document + 1-2 turns, then never reused (long-lived cold object)
            n = rng.randint(1, 2)
            behavior = "cold"
            think_mean = spec.cold_think_s
        else:
            n = rng.randint(spec.turns_min, spec.turns_max)
            behavior = "hot" if rng.random() < spec.hot_frac else "cold"
            think_mean = spec.hot_think_s if behavior == "hot" else spec.cold_think_s

        for k in range(n):
            if k == 0:
                new = int(
                    min(
                        spec.first_max_tokens,
                        max(256, _lognormal_mean(rng, spec.first_mean_tokens)),
                    )
                )
            else:
                new = rng.randint(spec.turn_tokens_min, spec.turn_tokens_max)
            b = behavior
            tm = think_mean
            if spec.kind == "hotness_flip" and k >= n // 2:
                # behaviour inversion half-way through each session
                b = "cold" if behavior == "hot" else "hot"
                tm = spec.cold_think_s if b == "cold" else spec.hot_think_s
            think = 0.0 if k == 0 else rng.expovariate(1.0 / tm)
            out.append(
                Turn(
                    sid,
                    k,
                    new,
                    rng.randint(spec.out_min, spec.out_max),
                    t if k == 0 else None,
                    think,
                    k == n - 1,
                    b,
                )
            )
        sid += 1
    return out


def save(turns: list[Turn], path: Path, spec: WorkloadSpec | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        if spec is not None:
            f.write(json.dumps({"_spec": asdict(spec)}) + "\n")
        for tr in turns:
            f.write(json.dumps(asdict(tr)) + "\n")


def load(path: Path) -> tuple[list[Turn], dict | None]:
    turns, spec = [], None
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if "_spec" in d:
            spec = d["_spec"]
            continue
        turns.append(Turn(**d))
    return turns, spec
