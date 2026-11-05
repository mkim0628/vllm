# DP4 protocol model check

Explicit-state (BFS + exact state dedupe, shortest counterexample) checker for the DP4 candidates
C1 (central metadata server, CXL-RPC slots) and C2 (shared metadata, 2-tier lock + clflush).
Evidence: [C]. Plan reference: `../../simulation-plan.md` §2(c), §8, §11. Python standard library only.

```bash
cd doc-mk/Evaluation/DP4/sim/protocol_check
uv run --no-project python check.py --nodes 2        # -> results/data/protocol_check.json
uv run --no-project python check.py --nodes 3        # -> results/data/protocol_check_n3.json
uv run --no-project python check.py --variants C1,C2 --no-write
uv run --no-project python -m unittest test_protocol_check -v
```
Options: `--max-states N` (default 1,500,000), `--no-prefetch`, `--variants a,b`, `--out file`.

## Files
`model.py` memory/cache semantics + thread interpreter; `protocols.py` C1, C2 and defect variants;
`invariants.py` I1..I4; `check.py` BFS, replay, CLI, JSON; `test_protocol_check.py` unittest.

## What this is NOT (limitations, also in the JSON `limitations`)
- A design-level abstract model. It is **not** a verification of real CPU / CXL hardware memory models.
- A pass means "no counterexample inside this model and the explored scope". `complete=false` (state cap reached) means
  "no counterexample found in the explored part", which is weaker.
- **Safety only** (I1-I4). Liveness (e.g. spinning forever on a stale line, lock never granted) is not checked.
- Scope: one block (K1) with one eviction + reallocation for K2, one global lock stripe, single-word cells,
  each client issues a bounded request sequence, 2 or 3 peer nodes plus one lock-manager host (C2) / server host (C1).
  Spontaneous cache events (evict / prefetch fill) are restricted to the metadata/slot-body lines that matter
  (C2: S, R; C1: server-side request flag/body lines); dirty write-back-and-keep-valid events are off
  (dirty eviction already writes back). DMA read is synchronous per word. Allocator state is folded into the entry
  cell (single region), so multi-writer allocator races are not modeled.

## Memory semantics
store: local cache only (dirty), write-back deferred. load: pending-ntstore forward / cache hit (maybe stale) / miss fills.
`clflush` synchronous. `clflushopt` only queues; completion is a separate nondeterministic event; `mfence` is a CPU-order
no-op that does not complete flushes. `ntstore` bypasses the cache and drains to memory later in any order;
`sfence` waits for the drain. DMA write bypasses caches, every word completes separately and later; `dma_wait` waits
for all words. Lines may be evicted nondeterministically (dirty ones written back) or filled (prefetch). No inter-node
invalidation, no atomics.

## Invariants
I1 payload visibility (reader's payload after READY is the complete (1,1)); I2 no use-after-free (no eviction /
pin-on-freed while a reader holds a pin); I3 mutual exclusion of the global-lock critical section;
I4 no stale index resurrect (READY observed by a read that started after the entry was freed, then used).
Ghost variables (freed, holders, cs mask) are verification-only.

## Paper basis vs author assumptions
| Item | Paper basis | Author assumption |
|---|---|---|
| Payload via GPU-CXL DMA (cache bypass), metadata READY publish after DMA completion is the visibility boundary | TraCT §3.4(2), §4.3 | DMA words complete independently; DMA read synchronous |
| clflush (not clflushopt) because clflushopt is async and mfence does not complete it | TraCT §3.4(4) example | Async completion acts on the line contents at completion time |
| Two-tier lock: local DRAM lock, then global slot WAITING, manager grants LOCKED, release IDLE | TraCT §3.3 | Manager runs on its own host (own cache); scan = per-slot clflush+load; grants only if no slot is LOCKED, picks any WAITING node; lock slot ops always clflush |
| Metadata flush before read / after write inside critical section | TraCT §3.4(1) | Flush after write happens before unlock (the C2_no_flush_before_unlock variant removes it) |
| Lookup does not modify metadata | TraCT §4.3 | Lookup is lock-free; pin re-validates READY under the lock; publish, pin, unpin, evict+realloc are critical sections |
| Eviction takes entry with refcount 0 | TraCT §4.3 | One entry cell holds FREE/ALLOC/READY(key); eviction + reallocation in one critical section |
| Single writer, many readers; ntstore writes, CLFLUSH before reads; REQ_READY / RESP_READY flags; server CLFLUSH before read | Beluga §5.1, §6.2 | Request/response slot = flag line + separate body line (64 B body leaves no room for the flag); flag carries a sequence number; body written before flag with sfence between; server state (index, refcount, allocator) is server-private; eviction happens inside ALLOC under pressure |
| Stale slot body | none | Slot bodies are reused, so the body line initially holds the previous request (UNPIN) and may already be cached by the server. Without this assumption a seq-numbered handshake makes a missing server CLFLUSH a liveness bug only; with a separate body line it is a safety bug (server executes the stale op) |
| Defect variants | TraCT §3.4 (clflushopt), Beluga (CLFLUSH rules) | Each variant removes exactly one mechanism |

## Results
See `../../results/data/protocol_check*.json` (per variant: per-invariant pass / violated, counterexample trace,
states, transitions, cap reached, parameters, limitations). Normal C1 and C2 are expected to be explored completely
with no counterexample; defect variants must produce counterexamples (`expected_violations`). If a normal
protocol ever produced a counterexample, that is a finding about missing assumptions and is to be reported, not
hidden by weakening invariants or removing nondeterminism.
