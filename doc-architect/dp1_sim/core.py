"""공통 타입 — 구현 UML §2.1.

메모리 스펙, 모델 형상, KV 요청, 결정점, 링크 비용.
물리식은 설계 문서 §4(Attention/FFN 분리 실행)를 그대로 옮긴 것이다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


# ─────────────────────────────────────────────────────────── enums


class DecisionPoint(Enum):
    """설계 문서 §1 — 배치 결정 시점은 두 곳이다."""

    PREFILL_COMPLETE = "prefill_complete"   # 결정점 A: 이번 턴 Decode를 어디서
    DEACTIVATION = "deactivation"           # 결정점 B: 유휴 중 어디에 보관


class TriggerKind(Enum):
    """결정점 B의 계기 (설계 문서 §1)."""

    TURN_END = "turn_end"
    PREFIX_RETAIN = "prefix_retain"
    PREEMPTION = "preemption"
    SESSION_DONE = "session_done"


class AttentionPrimitive(Enum):
    """원시 연산 단위. 'GEMV 지원'과 'Attention 처리 가능'은 다르다 (§4.5)."""

    QK_GEMM = "QK_GEMM"
    SOFTMAX = "SOFTMAX"
    AV_GEMM = "AV_GEMM"
    CAUSAL_MASK = "CAUSAL_MASK"


#: Attention을 한 메모리에서 끝내려면 이 넷을 모두 지원해야 한다.
ATTENTION_PRIMITIVE_SET = frozenset(
    {
        AttentionPrimitive.QK_GEMM,
        AttentionPrimitive.SOFTMAX,
        AttentionPrimitive.AV_GEMM,
        AttentionPrimitive.CAUSAL_MASK,
    }
)


class ReactivationMode(Enum):
    """설계 문서 §11.2.1 — 재활성 방식 세 가지."""

    RESIDENT = "A_resident"              # GPU가 직접 읽는다. 복원 0
    RESTORE = "B_restore"                # 재활성 시 전량 복원
    ATTENTION_OFFLOAD = "C_offload"      # KV 이동 없이 그 자리에서 Attention


class Medium(Enum):
    HBM = "HBM"
    CUSTOM_HBM = "CUSTOM_HBM"
    CXL_PNM = "CXL_PNM"
    DRAM = "DRAM"
    HBF = "HBF"
    SSD_PIM = "SSD_PIM"


# ─────────────────────────────────────────────────────────── model


@dataclass(frozen=True)
class ModelShape:
    """설계 문서 §4.2 — 연산 강도는 모델 형상에서 나온다."""

    name: str
    num_layers: int
    hidden: int
    num_heads: int
    dtype_bytes: int
    head_dim: int = 0
    #: GQA면 필수. MLA면 쓰지 않는다.
    num_kv_heads: int = 0
    #: "GQA" | "MLA" | "MLA+DSA" | "KDA+GATED_MLA" | "CSA2"
    attention_kind: str = "GQA"
    # ── MLA 계열
    kv_lora_rank: int = 0
    qk_rope_head_dim: int = 0
    # ── DSA / CSA2 의 sparse indexer
    index_head_dim: int = 0
    index_topk: int = 0
    sparse_attention: bool = False
    # ── KDA (선형/재귀 attention) 혼합
    kda_layers: int = 0
    mla_layers: int = 0
    kda_num_heads: int = 0
    kda_head_dim: int = 0
    short_conv_kernel_size: int = 0
    # ── CSA2 의 계층 간 KV 공유
    kv_source_layer_ids: tuple = ()
    index_source_layer_ids: tuple = ()
    sliding_window: int = 0
    #: 토큰 1개를 만드는 데 실제로 쓰이는 파라미터 수 (MoE면 활성분만).
    #: Decode의 가중치 읽기 시간을 정한다. None이면 그 항을 세지 않는다.
    active_params: int = 0
    total_params: int = 0

    def gqa_ratio(self) -> float:
        if self.attention_kind != "GQA":
            raise ValueError("gqa_ratio는 GQA에서만 정의된다. decode_intensity()를 쓸 것")
        return self.num_heads / self.num_kv_heads

    # ── KV 상태는 두 항으로 나뉜다: 토큰에 비례하는 항과 세션당 상수 항.
    #    KDA 같은 재귀 attention은 후자만 있고 context에 비례하지 않는다.

    def kv_bytes_per_token(self) -> int:
        """토큰 수에 **비례**하는 KV [bytes/token], 전 계층 합계."""
        d = self.dtype_bytes
        k = self.attention_kind
        if k == "GQA":
            return 2 * self.num_layers * self.num_kv_heads * self.head_dim * d
        if k in ("MLA", "MLA+DSA"):
            # MLA 잠재 + rope 성분을 계층마다, 헤드 간 공유
            per = self.num_layers * (self.kv_lora_rank + self.qk_rope_head_dim) * d
            if k == "MLA+DSA":
                # DSA의 lightning indexer도 토큰마다 키를 캐시한다
                per += self.num_layers * self.index_head_dim * d
            return per
        if k == "KDA+GATED_MLA":
            # MLA 계층만 토큰에 비례한다. KDA 계층은 재귀 상태라 상수항이다.
            return self.mla_layers * (self.kv_lora_rank + self.qk_rope_head_dim) * d
        if k == "CSA2":
            # KV를 **일부 계층에서만** 만들어 나머지 계층이 공유한다.
            n_kv = len(self.kv_source_layer_ids) or self.num_layers
            n_ix = len(self.index_source_layer_ids)
            return n_kv * (self.head_dim + self.qk_rope_head_dim) * d + n_ix * self.index_head_dim * d
        raise ValueError(f"모르는 attention_kind: {k}")

    def kv_bytes_constant(self) -> int:
        """세션당 **상수** 상태 [bytes] — context 길이와 무관하다.

        KDA 같은 선형/재귀 attention의 상태가 여기 들어간다.
        헤드당 (head_dim x head_dim) 재귀 상태 + short conv 상태.
        """
        if self.attention_kind != "KDA+GATED_MLA":
            return 0
        d = self.dtype_bytes
        recur = self.kda_layers * self.kda_num_heads * self.kda_head_dim * self.kda_head_dim * d
        conv = (self.kda_layers * self.kda_num_heads * self.kda_head_dim
                * max(0, self.short_conv_kernel_size - 1) * d)
        return recur + conv

    def kv_bytes_for(self, context_tokens: int) -> int:
        return context_tokens * self.kv_bytes_per_token() + self.kv_bytes_constant()

    def attended_tokens(self, context_tokens: int) -> int:
        """Decode 한 step이 **실제로 읽는** 토큰 수.

        sparse attention은 top-k만 읽으므로 context가 길어져도 상한이 있다.
        이것이 DP1의 대역폭 요구를 좌우한다.
        """
        if self.index_topk and self.sparse_attention:
            return min(context_tokens, self.index_topk)
        if self.attention_kind == "CSA2" and self.index_topk:
            return min(context_tokens, self.index_topk)
        return context_tokens

    def decode_read_bytes(self, context_tokens: int) -> int:
        """Decode 한 step이 읽는 KV 바이트. sparse면 top-k만."""
        return (self.attended_tokens(context_tokens) * self.kv_bytes_per_token()
                + self.kv_bytes_constant())

    def decode_intensity(self, context_tokens: int = 4096) -> float:
        """읽은 바이트당 FLOPs. GQA에 넣으면 H/KVH로 환원된다 (§4.2)."""
        rb = self.decode_read_bytes(context_tokens)
        return self.attention_flops(context_tokens, 1) / max(1, rb)

    def prefill_intensity(self, delta_tokens: int) -> float:
        """Incremental Prefill의 연산 강도 = Decode 강도 x query token 수 (§4.2)."""
        return self.decode_intensity() * delta_tokens

    def attention_flops(self, context_tokens: int, query_tokens: int) -> float:
        """QK^T + AV 의 FLOPs, 전 계층 합계 (§4.2의 4·H·HD·S·q).

        sparse attention은 top-k 토큰만 계산하므로 S를 그만큼 줄인다.
        """
        hd = self.head_dim or self.kv_lora_rank
        s_eff = self.attended_tokens(context_tokens)
        return 4.0 * self.num_heads * hd * s_eff * query_tokens * self.num_layers

    def weight_bytes(self) -> int:
        """Decode step마다 읽어야 하는 가중치 [bytes] (활성 파라미터분)."""
        return self.active_params * self.dtype_bytes

    def ffn_flops_per_token(self) -> float:
        """Attention 외 연산의 FLOPs — 대략 2 x 활성 파라미터."""
        return 2.0 * self.active_params

    def activation_bytes_per_token(self) -> int:
        """계층당 링크를 건너는 활성화 크기 (Q + attn_out). KV보다 세 자릿수 작다 (§4.1)."""
        return 2 * self.hidden * self.dtype_bytes


@dataclass(frozen=True)
class GpuSpec:
    name: str
    hbm_bw_bytes_per_s: float
    compute_tflops_fp16: float
    attention_bw_efficiency: float
    attention_flops_efficiency: float

    def prefill_seconds(self, model: ModelShape, context_tokens: int, query_tokens: int) -> float:
        """Prefill은 연산 한계 (§4.2(1)) — GPU에 고정된다."""
        flops = model.attention_flops(context_tokens, query_tokens)
        return flops / (self.compute_tflops_fp16 * self.attention_flops_efficiency)

    def decode_weight_seconds(self, model: ModelShape) -> float:
        """Decode step 1회의 가중치 읽기 시간.

        **배치 전체가 한 번만 읽으므로 배치로 나뉘지 않는다** — 세션마다
        자기 KV를 읽는 Attention과 여기서 성질이 갈린다. 이 항이 없으면
        GPU가 실제보다 한가해 보이고 오프로드의 이득이 과소평가된다.
        """
        if not model.active_params:
            return 0.0
        return model.weight_bytes() / (self.hbm_bw_bytes_per_s * self.attention_bw_efficiency)

    def ffn_prefill_seconds(self, model: ModelShape, tokens: int) -> float:
        """Prefill의 Attention 외 연산 시간 — 연산 한계."""
        if not model.active_params:
            return 0.0
        return model.ffn_flops_per_token() * tokens / (
            self.compute_tflops_fp16 * self.attention_flops_efficiency)

    def decode_attention_seconds(self, kv_bytes: int) -> float:
        """GPU가 HBM에서 KV 전체를 읽는 시간. Decode는 대역폭 한계 (§4.2)."""
        return kv_bytes / (self.hbm_bw_bytes_per_s * self.attention_bw_efficiency)


# ─────────────────────────────────────────────────────────── memory


@dataclass
class MemorySpec:
    """설계 문서 §3.4 Configuration의 한 항목."""

    name: str
    medium: Medium
    capacity_bytes: int
    ext_bw_bytes_per_s: float          # GPU에서 이 메모리에 도달하는 경로의 대역폭
    int_bw_bytes_per_s: float          # 내부 연산 유닛이 자기 매체에 접근하는 대역폭
    latency_s: float
    gpu_reachable: bool
    supported_primitives: frozenset
    compute_tflops_fp16: float | None
    attention_bw_efficiency: float | None
    write_amplification: float
    endurance_budget_bytes: float | None
    write_bw_bytes_per_s: float | None = None
    provenance: str = ""
    #: 이 메모리 장치의 TDP [W]. 에너지 지표(M-R2)에 쓴다.
    #: HBM은 GPU 패키지 안이므로 0으로 두고 GPU TDP에 포함시킨다.
    tdp_watts: float = 0.0

    # ── §3.3 외부/내부 비대칭

    def asymmetry_ratio(self) -> float:
        return self.int_bw_bytes_per_s / self.ext_bw_bytes_per_s

    def effective_write_bw(self) -> float:
        return self.write_bw_bytes_per_s or self.ext_bw_bytes_per_s

    # ── §4.2 균형점: 대역폭 한계를 유지하는 데 필요한 연산 성능

    def balanced_tflops(self, model: ModelShape) -> float:
        """`내부 대역폭 x 연산 강도`. 이를 넘는 연산 성능은 이득이 없다 (§4.2)."""
        eff = self.attention_bw_efficiency or 1.0
        return self.int_bw_bytes_per_s * eff * model.decode_intensity()

    # ── §4.4 Decode 오프로드 성립 조건 (네 가지 모두)

    def supports_attention(self) -> bool:
        return ATTENTION_PRIMITIVE_SET <= self.supported_primitives

    def can_serve_decode_attention(
        self,
        model: ModelShape,
        kv_bytes: int,
        capacity_headroom: int,
        step_budget_s: float,
        compute_margin: float = 0.25,
    ) -> bool:
        """§4.4의 네 조건. 하나라도 어기면 결정점 A의 후보가 아니다."""
        if not self.supports_attention():
            return False                                      # 원시 연산
        if self.compute_tflops_fp16 is None:
            return False
        if self.compute_tflops_fp16 < self.balanced_tflops(model) * compute_margin:
            return False                                      # 연산 성능
        if model.num_layers * self.latency_s > step_budget_s:
            return False                                      # 지연 예산
        if capacity_headroom < kv_bytes:
            return False                                      # 용량
        return True

    # ── 실행 시간 (§11.2.1의 Mode A/B/C)

    def resident_decode_seconds(self, kv_bytes: int) -> float:
        """Mode A — GPU가 이 메모리의 외부 대역폭으로 KV 전체를 읽는다."""
        return kv_bytes / self.ext_bw_bytes_per_s

    def offload_decode_seconds(self, model: ModelShape, kv_bytes: int, context_tokens: int) -> float:
        """Mode C — 내부 대역폭으로 읽고 근접 연산 유닛이 처리한다.

        대역폭 한계와 연산 한계 중 큰 쪽이 걸린다 (§4.2).
        링크 왕복 지연은 배치로 상쇄되므로 여기 포함하지 않고
        LinkCostModel이 배치 크기와 함께 별도로 계상한다 (§4.3).
        """
        eff = self.attention_bw_efficiency or 1.0
        bw_bound = kv_bytes / (self.int_bw_bytes_per_s * eff)
        flops = model.attention_flops(context_tokens, query_tokens=1)
        compute_bound = flops / self.compute_tflops_fp16 if self.compute_tflops_fp16 else float("inf")
        return max(bw_bound, compute_bound)

    def transfer_seconds(self, num_bytes: int) -> float:
        """KV를 이 메모리와 GPU 사이로 옮기는 시간 (외부 대역폭)."""
        return num_bytes / self.ext_bw_bytes_per_s

    def write_seconds(self, num_bytes: int) -> float:
        return num_bytes / self.effective_write_bw()

    def reactivation_mode_for(
        self, model: ModelShape, kv_bytes: int, headroom: int, step_budget_s: float
    ) -> ReactivationMode:
        """이 메모리에 둔 KV가 재활성 시 강제하는 방식 (§11.2.1).

        오프로드 가능 여부는 메모리가 정하지 정책이 정하지 않는다.
        """
        if self.can_serve_decode_attention(model, kv_bytes, headroom, step_budget_s):
            return ReactivationMode.ATTENTION_OFFLOAD
        if self.gpu_reachable:
            return ReactivationMode.RESIDENT
        return ReactivationMode.RESTORE


@dataclass
class MemoryState:
    used_bytes: int = 0
    endurance_consumed_bytes: float = 0.0
    busy_seconds: float = 0.0        # 이 메모리의 연산 유닛이 점유된 시간


class MemoryStateView:
    """정책이 메모리 상태를 읽는 유일한 창구 (구현 UML §0)."""

    def __init__(self, specs: list[MemorySpec]):
        self._specs = {s.name: s for s in specs}
        self._state = {s.name: MemoryState() for s in specs}

    def memories(self) -> list[MemorySpec]:
        return list(self._specs.values())

    def spec(self, name: str) -> MemorySpec:
        return self._specs[name]

    def state(self, name: str) -> MemoryState:
        return self._state[name]

    def capacity_headroom_of(self, name: str) -> int:
        return self._specs[name].capacity_bytes - self._state[name].used_bytes

    def load_of(self, name: str) -> float:
        """점유율 [0,1]. 완료된 Step까지만 반영한다."""
        spec = self._specs[name]
        return self._state[name].used_bytes / spec.capacity_bytes

    def endurance_headroom_of(self, name: str) -> float:
        spec = self._specs[name]
        if spec.endurance_budget_bytes is None:
            return 1.0
        used = self._state[name].endurance_consumed_bytes
        return max(0.0, 1.0 - used / spec.endurance_budget_bytes)

    # ── 실제 배치 반영

    def allocate(self, name: str, num_bytes: int) -> None:
        self._state[name].used_bytes += num_bytes

    def release(self, name: str, num_bytes: int) -> None:
        self._state[name].used_bytes = max(0, self._state[name].used_bytes - num_bytes)

    def charge_write(self, name: str, num_bytes: int) -> None:
        spec = self._specs[name]
        self._state[name].endurance_consumed_bytes += num_bytes * spec.write_amplification


class QueueStateView:
    """시스템 상태 — 데이터 특성이 아니다 (설계 문서 §5.4(2)).

    별도 모듈로 두어 두 후보가 동등하게 접근할 수 있게 한다.
    C1이 이것을 쓰지 않는 것은 설계 선택이지 접근 불가가 아니다.
    """

    def __init__(self) -> None:
        self.pending_requests = 0
        self._ewma_wait_s = 0.0

    def expected_wait_seconds(self) -> float:
        return self._ewma_wait_s

    def observe_wait(self, seconds: float, alpha: float = 0.2) -> None:
        self._ewma_wait_s = (1 - alpha) * self._ewma_wait_s + alpha * seconds


# ─────────────────────────────────────────────────────────── request


@dataclass
class AgentToolInfo:
    """다음 Tool 호출에 대해 Agent 런타임이 선언할 수 있는 것 (§5.1).

    tool_name은 선언값(관측 아님)이고, expected_exec_seconds는
    이름에서 유도한 추정값이다.
    """

    tool_name: str
    expected_exec_seconds: float
    expected_result_tokens: int
    is_terminal: bool


@dataclass
class SessionBlockSet:
    """배치 단위. 세션의 KV Block 전체 — §5.2(2)의 all-or-nothing 재접근 때문."""

    session_id: str
    context_tokens: int
    total_bytes: int
    observed_ref_cnt: int = 1
    placed_at: str | None = None          # 현재 어느 메모리에 있는가
    mode: ReactivationMode | None = None


@dataclass
class AllocationRequest:
    block_set: SessionBlockSet
    decision_point: DecisionPoint
    trigger: TriggerKind | None
    tool_info: AgentToolInfo | None
    next_op_primitives: frozenset
    turns_so_far: int
    step_index: int


# ─────────────────────────────────────────────────────────── link cost


#: 데이터 이동 에너지 [pJ/bit] — PUBLIC 실측/문헌값.
#:   PCIe/SerDes  : 112G-LR SerDes 4.5~6 pJ/bit, 224G-LR 5 pJ/bit 가정치
#:                  -> 5.0 pJ/bit 채택
#:   HBM3e        : 3.44 pJ/bit
#: 출처는 evaluation-criteria 문서에 적는다. 절대값이 아니라 **정책 간
#: 상대 비교**에 쓴다 — 두 정책이 같은 링크를 쓰므로 계수는 약분된다.
PJ_PER_BIT_LINK = 5.0
PJ_PER_BIT_HBM = 3.44


class LinkCostModel:
    """§4.3 — 오프로드 비용은 바이트(전송)와 왕복 횟수(지연)로 나뉜다.

    후자만 배치 크기에 반비례하므로 분리해서 계상한다.
    하나로 합치면 배치 크기 Sweep의 효과가 사라진다.
    """

    def __init__(self, model: ModelShape):
        self.model = model

    def transfer_seconds(self, spec: MemorySpec, batch_size: int) -> float:
        """계층당 활성화 왕복의 전송 시간, 전 계층 합계."""
        act_bytes = self.model.activation_bytes_per_token() * batch_size
        return self.model.num_layers * act_bytes / spec.ext_bw_bytes_per_s / max(1, batch_size)

    def roundtrip_latency_seconds(self, spec: MemorySpec, batch_size: int) -> float:
        """계층 수 x 경로 지연. 배치 안의 여러 요청이 상쇄하므로 배치 크기에 반비례."""
        return self.model.num_layers * spec.latency_s / max(1, batch_size)

    def total_seconds(self, spec: MemorySpec, batch_size: int) -> float:
        return self.transfer_seconds(spec, batch_size) + self.roundtrip_latency_seconds(spec, batch_size)


# ─────────────────────────────────────────────────────────── config load


def load_config(path: Path | str) -> tuple[GpuSpec, ModelShape, list[MemorySpec]]:
    """configs/memories_default.json 을 읽는다.

    설계 문서 §3.4 — Configuration 교체가 코드 수정 없이 되어야 M-F1 실험이 성립한다.
    신규 메모리는 이 파일에 항목을 추가하는 것만으로 투입된다.
    """
    raw = json.loads(Path(path).read_text())
    g = raw["gpu"]
    gpu = GpuSpec(
        name=g["name"],
        hbm_bw_bytes_per_s=float(g["hbm_bw_bytes_per_s"]),
        compute_tflops_fp16=float(g["compute_tflops_fp16"]),
        attention_bw_efficiency=float(g["attention_bw_efficiency"]),
        attention_flops_efficiency=float(g["attention_flops_efficiency"]),
    )
    m = raw["model"]
    model = ModelShape(
        name=m.get("name", "model"),
        num_layers=int(m["num_layers"]),
        hidden=int(m["hidden"]),
        num_heads=int(m["num_heads"]),
        num_kv_heads=int(m.get("num_kv_heads", 0)),
        head_dim=int(m["head_dim"]),
        dtype_bytes=int(m["dtype_bytes"]),
        attention_kind=m.get("attention_kind", "GQA"),
        kv_lora_rank=int(m.get("kv_lora_rank", 0)),
        qk_rope_head_dim=int(m.get("qk_rope_head_dim", 0)),
    )
    mems = []
    for e in raw["memories"]:
        prims = frozenset(AttentionPrimitive[p] for p in e.get("supported_primitives", []))
        mems.append(
            MemorySpec(
                name=e["name"],
                medium=Medium[e["medium"]],
                capacity_bytes=int(e["capacity_bytes"]),
                ext_bw_bytes_per_s=float(e["ext_bw_bytes_per_s"]),
                int_bw_bytes_per_s=float(e["int_bw_bytes_per_s"]),
                latency_s=float(e["latency_s"]),
                gpu_reachable=bool(e["gpu_reachable"]),
                tdp_watts=float(e.get("tdp_watts", 0.0)),
                supported_primitives=prims,
                compute_tflops_fp16=(
                    float(e["compute_tflops_fp16"]) if e.get("compute_tflops_fp16") else None
                ),
                attention_bw_efficiency=(
                    float(e["attention_bw_efficiency"]) if e.get("attention_bw_efficiency") else None
                ),
                write_amplification=float(e.get("write_amplification", 1.0)),
                endurance_budget_bytes=(
                    float(e["endurance_budget_bytes"]) if e.get("endurance_budget_bytes") else None
                ),
                write_bw_bytes_per_s=(
                    float(e["write_bw_bytes_per_s"]) if e.get("write_bw_bytes_per_s") else None
                ),
                provenance=e.get("provenance", ""),
            )
        )
    return gpu, model, mems


# ───────────────────────────────────── 클러스터 / 모델 Configuration 조립
#
# DP1의 단위는 **scale-up 도메인 하나**다 (도메인 간 배치는 DP2 범위).
# 도메인 안의 GPU는 TP로 묶여 하나의 연산·대역폭·용량 풀처럼 동작한다고 본다.


def load_model(path: Path | str, name: str | None = None) -> ModelShape:
    """configs/models.json 에서 모델 하나를 만든다."""
    raw = json.loads(Path(path).read_text())
    key = name or raw["default"]
    m = raw["models"][key]
    return ModelShape(
        name=key,
        num_layers=int(m["num_layers"]), hidden=int(m["hidden"]),
        num_heads=int(m["num_heads"]), dtype_bytes=int(m["dtype_bytes"]),
        head_dim=int(m.get("head_dim", 0)),
        num_kv_heads=int(m.get("num_kv_heads", 0)),
        attention_kind=m.get("attention_kind", "GQA"),
        kv_lora_rank=int(m.get("kv_lora_rank", 0)),
        qk_rope_head_dim=int(m.get("qk_rope_head_dim", 0)),
        index_head_dim=int(m.get("index_head_dim", 0)),
        index_topk=int(m.get("index_topk", 0)),
        sparse_attention=bool(m.get("sparse_attention", False)),
        kda_layers=int(m.get("kda_layers", 0)),
        mla_layers=int(m.get("mla_layers", 0)),
        kda_num_heads=int(m.get("kda_num_heads", 0)),
        kda_head_dim=int(m.get("kda_head_dim", 0)),
        short_conv_kernel_size=int(m.get("short_conv_kernel_size", 0)),
        active_params=int(m.get("active_params") or 0),
        total_params=int(m.get("total_params") or 0),
        kv_source_layer_ids=tuple(m.get("kv_source_layer_ids", ())),
        index_source_layer_ids=tuple(m.get("index_source_layer_ids", ())),
        sliding_window=int(m.get("sliding_window", 0)),
    )


def load_cluster(path: Path | str, name: str | None = None) -> tuple[GpuSpec, dict]:
    """configs/clusters.json 에서 **도메인 하나**의 GPU 집계 스펙을 만든다.

    반환값의 dict는 HBM 메모리 항목을 덮어쓸 값과 메타데이터를 담는다.
    """
    raw = json.loads(Path(path).read_text())
    key = name or raw["default"]
    cl = raw["clusters"][key]
    g = raw["gpus"][cl["gpu"]]
    n = int(cl["gpus_per_scaleup_domain"])
    # GPU-HBM 대역폭은 GPU 1장의 자기 HBM 링크 대역폭이다. GPU가 N장이어도
    # 각자 자기 HBM에 그 대역폭으로 붙을 뿐 도메인 전체로 합산되지 않는다
    # (세션 하나의 Decode는 한 GPU/TP샤드 몫만 읽는다). 용량·연산·TDP는
    # GPU가 병렬로 일하므로 N배가 맞다.
    gpu = GpuSpec(
        name=f"{key}(domain of {n}x {cl['gpu']})",
        hbm_bw_bytes_per_s=float(g["hbm_bw_bytes_per_s"]),
        compute_tflops_fp16=float(g["dense_fp16_flops"]) * n,
        attention_bw_efficiency=0.9,
        attention_flops_efficiency=0.5,
    )
    meta = {
        "cluster": key, "gpu_model": cl["gpu"], "gpus_per_domain": n,
        "num_domains": int(cl["num_domains"]),
        "hbm_capacity_bytes": int(g["hbm_capacity_bytes"]) * n,   # 도메인 합산
        "hbm_bw_bytes_per_s": float(g["hbm_bw_bytes_per_s"]),      # GPU 1장 링크 속도
        "tdp_watts": float(g["tdp_watts"]) * n,                    # 도메인 합산
        # ── custom_hbm을 상대 스펙으로 유도하기 위한 GPU 1장 기준값
        "gpu_hbm_capacity_bytes": int(g["hbm_capacity_bytes"]),
        "gpu_dense_fp16_flops": float(g["dense_fp16_flops"]),
        "gpu_tdp_watts_each": float(g["tdp_watts"]),
        "hbm_medium": g.get("hbm_medium", "HBM"),
    }
    return gpu, meta


def apply_cluster(memories: list[MemorySpec], meta: dict, *,
                  scale_attached: bool = False) -> list[MemorySpec]:
    """도메인 집계를 메모리 목록에 반영한다.

    HBM은 항상 도메인(= GPU N장) 합산이다.

    `scale_attached` — Host에 붙는 메모리(custom_hbm, cxl_pnm)를 어떻게 셀
    것인가. **이 선택이 결과를 지배하므로 기본값을 두지 않고 명시한다.**
      False : 장치 1대가 도메인 전체를 담당하고 PCIe 한 가닥을 공유한다
              (보수적. custom_hbm 56 TB/s vs 도메인 HBM 64 TB/s 라
               오프로드 이득이 사라진다)
      True  : GPU마다 장치 1대와 자기 PCIe x16을 가진다
              (용량·내부BW·연산·외부BW·TDP를 모두 N배)
    """
    from dataclasses import replace
    n = meta["gpus_per_domain"]
    out = []
    for m in memories:
        if m.name == "hbm":
            out.append(replace(m, capacity_bytes=meta["hbm_capacity_bytes"],
                               ext_bw_bytes_per_s=meta["hbm_bw_bytes_per_s"],
                               int_bw_bytes_per_s=meta["hbm_bw_bytes_per_s"]))
        elif scale_attached and not m.gpu_reachable:
            out.append(replace(
                m, capacity_bytes=m.capacity_bytes * n,
                ext_bw_bytes_per_s=m.ext_bw_bytes_per_s * n,
                int_bw_bytes_per_s=m.int_bw_bytes_per_s * n,
                compute_tflops_fp16=(m.compute_tflops_fp16 * n
                                     if m.compute_tflops_fp16 else None),
                tdp_watts=m.tdp_watts * n))
        else:
            out.append(m)
    # custom_hbm은 **페어링 GPU 상대 스펙**이다 (사용자 규칙).
    #   용량 = GPU HBM x2,  내부BW = GPU HBM BW x2,
    #   연산 = GPU dense FP16 x20%,  TDP = GPU TDP / 3
    # 클러스터가 바뀌면 그 GPU 기준으로 전부 다시 계산한다.
    return [replace(m,
                    capacity_bytes=int(2 * meta["gpu_hbm_capacity_bytes"]),
                    int_bw_bytes_per_s=2.0 * meta["hbm_bw_bytes_per_s"],
                    compute_tflops_fp16=0.20 * meta["gpu_dense_fp16_flops"],
                    tdp_watts=meta["gpu_tdp_watts_each"] / 3.0)
            if m.name == "custom_hbm" else m
            for m in out]
