#!/usr/bin/env python3
"""설계 문서 4장의 정량 비교를 memories_default.yaml에서 직접 계산한다.

손으로 적은 숫자가 config와 어긋나는 것을 막기 위해, 문서의 표는 이 스크립트의
출력을 옮겨 적는다. config를 고치면 이 스크립트를 다시 돌려 표를 갱신할 것.

    python3 calc_attention.py
"""

import pathlib

import yaml

CFG = yaml.safe_load((pathlib.Path(__file__).parent / "memories_default.yaml").read_text(encoding="utf-8"))
G, M = CFG["gpu"], CFG["model"]
MEM = {m["name"]: m for m in CFG["memories"]}

L, H, KVH, HD, B = M["num_layers"], M["num_heads"], M["num_kv_heads"], M["head_dim"], M["dtype_bytes"]
S, DT = M["context_tokens"], M["incremental_prefill_tokens"]

# KV cache
KV_BYTES = 2 * KVH * HD * B * S * L
# 링크를 건너는 활성화: Q + attn_out + K/V append
ACT_DECODE = (2 * H * HD * B + 2 * KVH * HD * B) * L
ACT_PREFILL = ACT_DECODE * DT


def attn_flops(q_tokens: int) -> float:
    """QK^T + AV. multiply-add를 2 FLOP로 센다."""
    return 4 * H * HD * S * q_tokens * L


def intensity(q_tokens: int) -> float:
    """연산 강도 [FLOP/byte] = GQA 비율 x query token 수."""
    return attn_flops(q_tokens) / KV_BYTES


def attn_time(mem: dict, q_tokens: int) -> tuple[float, float, float]:
    """(실제 시간, 대역폭 한계 시간, 연산 한계 시간) 초."""
    bw = mem["int_bw_bytes_per_s"] * (mem.get("attention_bw_efficiency") or 1.0)
    t_bw = KV_BYTES / bw
    tf = mem.get("compute_tflops_fp16")
    t_fl = attn_flops(q_tokens) / tf if tf else 0.0
    return max(t_bw, t_fl), t_bw, t_fl


def gpu_attn_time(q_tokens: int) -> tuple[float, float, float]:
    t_bw = KV_BYTES / (G["hbm_bw_bytes_per_s"] * G["attention_bw_efficiency"])
    t_fl = attn_flops(q_tokens) / (G["compute_tflops_fp16"] * G["attention_flops_efficiency"])
    return max(t_bw, t_fl), t_bw, t_fl


def link_time(mem: dict, act_bytes: float) -> float:
    return act_bytes / mem["ext_bw_bytes_per_s"] + L * mem["latency_s"]


def ms(x: float) -> str:
    return f"{x * 1e3:8.2f}"


print(f"모델 {M['name']}: L={L} H={H} KVH={KVH} HD={HD} S={S} dT={DT}")
print(f"세션 KV {KV_BYTES / 2**30:.2f} GiB | 활성화/token {ACT_DECODE / 2**20:.2f} MiB\n")

print("[연산 강도] = GQA 비율 x query token 수")
print(f"  Decode (q=1)            {intensity(1):10.1f} FLOP/B")
print(f"  Incremental prefill (q={DT}) {intensity(DT):9.1f} FLOP/B\n")

print("[대역폭 한계를 유지하려면 필요한 연산 성능]  = int_bw x 연산강도")
for n in ("custom_hbm", "cxl_pnm"):
    m = MEM[n]
    bw = m["int_bw_bytes_per_s"] * m["attention_bw_efficiency"]
    have = m["compute_tflops_fp16"] / 1e12
    print(f"  {n:12s} decode {bw * intensity(1) / 1e12:8.1f} TFLOPS 필요 / 가정 {have:6.1f} "
          f"-> {'대역폭 한계' if have >= bw * intensity(1) / 1e12 else '연산 한계'}")
    print(f"  {n:12s} prefill{bw * intensity(DT) / 1e12:8.0f} TFLOPS 필요 / 가정 {have:6.1f} -> 연산 한계 (달성 불가)")
print()

print("[Decode 1 step, 세션 1개]")
t, bw, fl = gpu_attn_time(1)
print(f"  {'GPU 로컬 HBM':38s} {ms(t)} ms   (bw {ms(bw)} / flops {ms(fl)})")
base = t
for n, mode in (("custom_hbm", "A"), ("custom_hbm", "C"), ("cxl_pnm", "C"), ("hbf", "A")):
    m = MEM[n]
    if mode == "A":
        t = KV_BYTES / m["ext_bw_bytes_per_s"]
        print(f"  {n + ' fabric/direct read (Mode A)':38s} {ms(t)} ms   {t / base:5.2f}x")
    else:
        a, bw, fl = attn_time(m, 1)
        lk = link_time(m, ACT_DECODE)
        bound = "연산 한계" if fl > bw else "대역폭 한계"
        print(f"  {n + ' Attention 오프로드 (Mode C)':38s} {ms(a + lk)} ms   {(a + lk) / base:5.2f}x  "
              f"[{bound}] 링크 {lk * 1e6:.0f} us")
print()

print(f"[Incremental prefill, dT={DT}]")
t, bw, fl = gpu_attn_time(DT)
print(f"  {'GPU 로컬 HBM':38s} {ms(t)} ms   (bw {ms(bw)} / flops {ms(fl)})  <- 연산 한계")
gpu_pf = t
for n in ("custom_hbm", "cxl_pnm"):
    m = MEM[n]
    a, bw, fl = attn_time(m, DT)
    lk = link_time(m, ACT_PREFILL)
    print(f"  {n + ' 오프로드':38s} {ms(a + lk)} ms   {(a + lk) / gpu_pf:5.1f}x  [연산 한계]")
    stream = KV_BYTES / m["ext_bw_bytes_per_s"]
    hidden = "GPU 연산에 가려짐" if stream < gpu_pf else "가려지지 않음 — 전송이 지배"
    print(f"  {n + ' KV 스트리밍 + GPU 연산':38s} {ms(max(stream, gpu_pf))} ms          "
          f"(전송 {ms(stream)} ms, {hidden})")


# ── 턴 단위 처리량 모델 (설계 문서 4.6) ────────────────────────────────
# Agent 한 턴 = Incremental Prefill 1회 + N회 Decode.
# Prefill은 연산 한계라 GPU가 해야 하고, Decode attention은 대역폭 한계라
# 연산형 메모리로 보낼 수 있다. 보내면 두 자원이 직렬이 아니라 병렬로 돈다.

WEIGHT_MS = 2.2  # src: ASSUMED TP8 기준 가중치 read. 배치 전체가 공유

print("\n" + "=" * 68)
print("[턴 단위 처리량] Agent 한 턴 = prefill 1 + decode N")
print("  가정: prefill은 GPU 고정(연산 한계), decode attention만 오프로드 대상")
print(f"  가중치 read {WEIGHT_MS} ms/step (ASSUMED, TP8)\n")

gpu_pf_ms = gpu_attn_time(DT)[0] * 1e3
gpu_dec_ms = gpu_attn_time(1)[0] * 1e3

print(f"{'N (턴당 생성 토큰)':>18s} {'GPU만':>10s} {'오프로드':>10s} {'변화':>9s}  병목")
for n_tok in (8, 20, 50, 143, 400):
    for name in ("custom_hbm",):
        m = MEM[name]
        node_dec_ms = (attn_time(m, 1)[0] + link_time(m, ACT_DECODE)) * 1e3
        # GPU만: prefill + decode 전부 GPU에서 직렬
        t_gpu_only = gpu_pf_ms + n_tok * (gpu_dec_ms + WEIGHT_MS)
        # 오프로드: GPU는 prefill + 가중치, 노드는 decode attention. 두 자원 병렬
        t_gpu = gpu_pf_ms + n_tok * WEIGHT_MS
        t_node = n_tok * node_dec_ms
        t_off = max(t_gpu, t_node)
        who = "GPU" if t_gpu >= t_node else "노드"
        print(f"{n_tok:>18d} {t_gpu_only:9.1f}ms {t_off:9.1f}ms {t_gpu_only / t_off - 1:+8.1%}  {who}")

print("\n[노드 연산 성능 민감도] N=20 기준, custom_hbm의 TFLOPS만 바꿔가며")
m = dict(MEM["custom_hbm"])
n_tok = 20
t_gpu_only = gpu_pf_ms + n_tok * (gpu_dec_ms + WEIGHT_MS)
print(f"{'노드 TFLOPS':>14s} {'decode step':>13s} {'턴 시간':>10s} {'처리량 변화':>12s}  한계")
for tf in (16e12, 32e12, 44.8e12, 64e12, 128e12):
    m["compute_tflops_fp16"] = tf
    a, bw, fl = attn_time(m, 1)
    node_dec_ms = (a + link_time(m, ACT_DECODE)) * 1e3
    t_off = max(gpu_pf_ms + n_tok * WEIGHT_MS, n_tok * node_dec_ms)
    print(f"{tf / 1e12:13.1f} {node_dec_ms:12.2f}ms {t_off:9.1f}ms {t_gpu_only / t_off - 1:+11.1%}  "
          f"{'연산' if fl > bw else '대역폭'}")
