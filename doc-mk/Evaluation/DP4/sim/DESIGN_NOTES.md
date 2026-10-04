# DP4 simulator: decisions, simplifications, approximations

Everything the plan (`../simulation-plan.md`) does not fix is listed here. "Conservative" marks a choice that does not
favour a candidate. Nothing below was tuned after seeing results (H16). Simulation output is Evidence [B+C].

## A. Plan ambiguities and how they were resolved

1. **Move path is one overlapped flow.** The plan says T_move is write (P to pool) plus read (pool to D) with a layer-pipeline
   overlap ratio. The simulator reserves one flow on [P egress, pool aggregate, D ingress] that starts at
   `prefill_start + (1 - overlap) * prefill`, ends no earlier than prefill end. The pool aggregate carries the bytes twice
   (write + read). Publish and pin are charged after the flow ends; unpin right after pin (the D read is complete).
   Physically a block can only be read after it is published, so a real pooled path has a non-overlapped read. Not modelled
   (it would add roughly one extra D-ingress transfer time to candidate TTFT). Direction of bias: favours candidates slightly.
2. **Baseline path.** P to D point-to-point over RDMA, `eta_rdma` 0.85, no fragmentation penalty, same overlap rule. One central
   index lookup (100 us) per request at arrival. Index updates are async and cost nothing on the critical path.
3. **Background load** (CB-1/2/3) multiplies the bandwidth of every node egress/ingress link and of the pool aggregate by
   `1 - bg(t)` for both data planes (RDMA NIC and CXL adapters). The plan only says "node KV link"; applying it to the
   pool as well is a choice. `bg(t)` for the ramp is linear over the horizon. Duration uses bandwidth at the transfer start and midpoint.
4. **DP4-specific rows use background 0** (isolates the control plane). Only CB rows are link-pressured. Topology default for
   DP4 rows is P2+D2 (CB rows: P1+D1 as the plan says). `d4_lock_stripes_*` and `d4_server_threads_*` use `d4_hot_prefix_fanout`
   with P4+D4 (N=8); the plan does not say which workload carries the sweeps.
5. **Extra reference row `d4_node_scale_n2`** (P1+D1, background 0). Scaling Efficiency needs Goodput(2) under the same
   conditions as N=4/8/16; the plan lists only n4/n8/n16. The row is labelled `reference` and is not a benchmark.md scenario.
6. **Variant rows.** `d4_fail_lockholder[as_published|lease]` as required; `d4_fail_server[restart|node_loss]` added
   (`node_loss` = 30 s index rebuild, ASSUMED range value of the plan).
7. **Load grid** `x0.5/1.0/1.5/2.0`, all arms identical. If any arm's mean Max-goodput peak is at the grid end (and > 0)
   the grid is extended by x3, x4, ... up to x8 for all arms of that scenario. A peak at x8 stays flagged in `meta.loads_run`.
   Deviation in the spirit of common-benchmark 5.2 ("a missed peak is invalid"): a peak at the lowest point (x0.5) extends downward
   (x0.25, x0.125, x0.0625) because link-bound rows (B200 CB-3) peak below the grid. `qa1_n_cand_zero` counts scenarios where a candidate has zero goodput
   at every load (the QA1 geometric mean then collapses; `qa1_ratio_geomean_excl_zero` is stored next to it).
8. **Goodput** counts a request when its own TTFT <= 2 s and TPOT <= 50 ms (per-request SLO). Cohort = arrivals after the
   10 % warm-up; all requests are drained (so overload shows up as SLO violations, not as a vanishing denominator). Consequence:
   the goodput peak can sit at a load where the P99 TTFT already violates the SLO (the P99 star then drops). QA2 star follows
   the DP1 convention (worst case at each arm's own Max-goodput load); `qa2_common_*` (Baseline-peak load) and
   `qa2_load1_*` (x1.0) are reported next to it.
9. **QA3 load.** KV residency is compared at the offered load where the Baseline peaks (same request stream for all arms),
   as qa-criteria says "same number of requests"; own-peak and x1.0 values are also stored. Residency = P-side buffer
   (prefill start to flow end, all arms) + D HBM (flow start to completion, context + out/2 tokens) + pool copy
   (candidates, flow start to unpin; shared hot prefix stored once; agent sessions keep the pool copy until the next turn).
   Baseline agent sessions keep History KV on D between turns. Host DRAM is 0 for all arms. Non-KV objects (CB-3) are not counted.
   The accounting makes candidates carry one extra transient copy (the pool) unless sharing/reuse removes a copy.
10. **CB-3 mixed traffic.** KV is 50 % of pool traffic and of object count, so every request moves and pins one additional
    block-equivalent of non-KV objects per KV block (same treatment in the Baseline: the same extra bytes cross RDMA and the same
    extra objects appear in metadata ops for the pool arms). LoRA/MoE/Agent/Tool differences in access pattern are not modelled.
11. **Agent multi-turn.** 8 turns, turn k adds 256 output + 1024 new input tokens, fixed open-loop gap 8 s between turns (so the
    trace does not depend on the arm), sessions Poisson with request-level base rate = 0.6 x P saturation using the mean
    incremental prefill. Baseline: session-affine D holds History KV; per turn argmin between D-local incremental prefill
    (D decode frozen for the prefill duration, FCFS on D) and D to P history transfer + P prefill + P to D new-KV transfer.
    Candidates: any P; P reads History KV from the pool (stage 1, not overlapped), then the normal flow; D reads the whole context.
    Pins protect History KV only through the normal pin (no extra eviction race modelled).
12. **Hot prefix.** 90 % of requests share a 6144-token prefix (ASSUMED length). Effects: lookup walks the hit chain, pin/unpin
    of the shared blocks go to lock stripe 0 (C2), publish only covers private blocks, pool residency dedups the prefix.
    Prefill compute and transfer bytes are NOT reduced (control-plane isolation; conservative for candidates).
13. **Pool-full eviction.** At `pool_occ >= 0.9` every publish is preceded by an `evict` critical section/RPC sequence of the same size
    (before the flow starts). No data movement. Reader contention beyond refcount pins is not modelled.
14. **C2 critical sections.** `cs_per_request` 3 = publish, pin, unpin (each with its own lock id: uniform stripe, or stripe 0 for
    hot pin/unpin). Hold = ceil(blocks / 4 entries per cacheline) x (read + write+flush). 2 drops unpin; 5 adds alloc (before the
    flow) and lru (after unpin). Node-local lock = constant 0.1 us (no node-local queueing). Sequence per section: local lock,
    WAITING slot write+flush, grant at the next scan probe of (stripe, node) after the lock is free (FIFO per stripe), grant write +
    client poll read, hold, release write+flush. Scan phase of slot (s, n) is `(s*N+n)*t_probe` mod `S*N*t_probe`.
    Lookup is lock-free: (hit blocks + 1) x 1.3 probes x cacheline read, sequential (no memory-level parallelism; conservative).
15. **C1 server.** FIFO shared queue over T threads, service = 1/12.13 Mops per RPC, RTT floor 2.11 us split into transport (RTT minus
    service) around the queue, ceil(blocks / 8) RPCs per op issued back-to-back. Process restart / node loss = no service in the
    window; requests wait (index preserved in CXL). Server CPU = T cores busy-polling at all times.
16. **Failures.** `d4_fail_server`: C1 down window starting at 30 % of the measurement window; no effect on Baseline/C2 (no such component).
    `d4_fail_lockholder`: node P0 crashes at the same time in every arm, loses its in-flight requests, and returns after
    `node_recovery_s` = 30 s (ASSUMED). In C2 the crash is aligned to P0's next critical section after that time (it dies holding a lock).
    As-published: that stripe is never released (stuck); with lease the stripe is freed `lease_s` after the crash. The lock holder's
    in-flight requests count as failed, stuck requests as incomplete (SLO violations). `failure` table compares against a no-failure rerun.
17. **Tail latency of requests that never finish** is recorded as 1e9 ms (SLO violation, makes P99 "never" when > 1 % are stuck).
18. **First token / TPOT.** First token = decode admission + one step at the admitted batch; TPOT = (done - first)/(out - 1).
    Decode is processor sharing with batch cap 32; step time from DP1 `decode_step_s(mean context, batch)`; recomputed when the
    active set changes (context growth inside a step interval is approximated by the mean).
19. **DP2 rule** for the prefill node: argmin(queue + prefill + exposed move) with identical formula in all arms; D choice = least loaded
    (Baseline reuse: session affinity).
20. **Control-plane saturation** (`cp_capacity`): open-loop requests that only execute lookup/publish/pin/unpin; saturation = lowest
    rate in a x2 geometric sweep (100 req/s upward) where P99 chain latency > 10 x the P99 at 100 req/s. Unloaded scan wait is not saturation.
    Null = not reached within the sweep (about 1e8 req/s).
21. **Ablation arms** (SKILL 9): `C2-no-scan` grants at the lock free time (direct hand-off, scan wait 0), `C1-no-batch` sends one block hash per RPC.
    Control = full arms of the same run; `ablation.py` compares them with the main result file.
22. **Scaling Efficiency** can exceed 1 because per-node load is fixed at 0.6 x P saturation: more P nodes pool queueing (M/D/n) and the P99-SLO goodput
    of N=2 (single P node) is queueing-limited. Reported as computed (no stars, proposal metric).
23. **Seeds / reproducibility**: seeds 11 23 37 53 71, `random.Random`, no global state. Same command + same git revision gives identical numbers
    (test `test_same_seed_same_result`). Results record `git rev-parse --short HEAD` and dirty flag of `doc-mk/Evaluation/DP4`.

## B. Not modelled
CXL device/bank contention, switch congestion beyond aggregate BW, CPU scheduling of the server/lock manager, DMA scatter-gather details, pool device
failure, node-local lock queueing, host DRAM tier, DP3 compression, per-class behaviour of LoRA/MoE/Agent/Tool objects, stale-read correctness
(owned by `protocol_check/`).

## C. Provenance hygiene
Only the plan's table values carry PAPER. Simulator-only parameters (`in_spec_table=false` in `configs/cluster_dp4.json`) are SPEC (from the
common benchmark / brief) or ASSUMED. `lease_s` is ASSUMED (not found in the paper). The write latency 9.14 us is used once per candidate flow; 11.06 us,
`client_ntstore_us`, `cxl_latency_ns` are recorded but unused (`used_in_model=false`).
