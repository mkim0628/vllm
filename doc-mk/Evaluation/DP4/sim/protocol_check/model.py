"""Abstract non-coherent shared-memory machine (design-level model, not a hardware model).

State = (mem, caches, nt, fq, dma, thr, locks, ghost)
  mem     tuple of cell values in shared memory
  caches  per host: tuple per cell of None | (value, dirty)
  nt      per host: ordered tuple of pending ntstores (cell, value)
  fq      per host: sorted tuple of cells with a queued (not yet completed) clflushopt
  dma     sorted tuple of pending DMA word writes (job, cell, value)
  thr     per thread: (pc, regs)
  locks   per host: node-local DRAM mutex holder (-1 free)
  ghost   (freed, holders, cs_mask)  -- verification-only variables

Memory semantics
  store      -> local cache only (dirty); write-back is deferred and nondeterministic
  load       -> pending-ntstore forward, else cache hit (maybe stale), else miss fills from memory
  clflush    -> synchronous: write back if dirty, invalidate
  clflushopt -> only queued; completion is a separate nondeterministic event. mfence is a
                CPU-ordering no-op in this model (it does not complete queued flushes)
  ntstore    -> bypasses cache (drops local line), drains to memory later in any order
                (different cells), sfence waits for the drain
  dma_write  -> bypasses caches, each word completes later (any order); dma_wait waits all words
  dma_read   -> reads memory directly (synchronous per word)
  environment: any valid line may be evicted (dirty ones written back), a dirty line may be
  written back and kept clean, an invalid line may be filled from memory (prefetch).
  There is no inter-node invalidation and no atomic operation.
"""
from invariants import check_use, check_evict, check_pin, check_cs

VISIBLE = {"load", "store", "clflush", "clflushopt", "ntstore", "sfence", "dma_write",
           "dma_wait", "dma_read", "lock", "pick"}


class Prog:
    """A thread program with symbolic registers and labels."""

    def __init__(self, name, host, regs, cells):
        self.name, self.host, self.cells = name, host, cells
        self.regs = {r: i for i, r in enumerate(regs)}
        self.nregs = len(regs)
        self.ins, self.txt, self.labels, self._n = [], [], {}, 0

    def r(self, name):
        return self.regs[name]

    def R(self, name, delta=0):
        return ("r", self.regs[name], delta)

    def new_label(self, base="L"):
        self._n += 1
        return "%s%d" % (base, self._n)

    def label(self, name):
        self.labels[name] = len(self.ins)

    def emit(self, *ins, text=None):
        self.ins.append(tuple(ins))
        self.txt.append(text or self._fmt(ins))

    def _c(self, c):
        return self.cells[c]

    def _v(self, x):
        if isinstance(x, tuple):
            names = {i: n for n, i in self.regs.items()}
            d = "" if x[2] == 0 else "%+d" % x[2]
            return "%s%s" % (names[x[1]], d)
        return str(x)

    def _fmt(self, i):
        op = i[0]
        names = {k: n for n, k in self.regs.items()}
        if op == "load":
            return "load %s -> %s" % (self._c(i[2]), names[i[1]])
        if op in ("store", "ntstore"):
            return "%s %s = %s" % (op, self._c(i[1]), self._v(i[2]))
        if op in ("clflush", "clflushopt"):
            return "%s %s" % (op, self._c(i[1]))
        if op == "dma_write":
            return "dma_write job%d %s" % (i[1], ",".join("%s=%d" % (self._c(c), v) for c, v in i[2]))
        if op == "dma_wait":
            return "dma_wait job%d" % i[1]
        if op == "dma_read":
            return "dma_read %s -> %s" % (self._c(i[2]), names[i[1]])
        if op == "br":
            return "br %s %s %s -> %s" % (i[1], self._v(i[2]), self._v(i[3]), i[4])
        if op == "set":
            return "set %s = %s" % (names[i[1]], self._v(i[2]))
        return " ".join(str(x) for x in i)

    def finish(self):
        out = []
        for i in self.ins:
            if i[0] == "br":
                i = ("br", i[1], i[2], i[3], self.labels[i[4]])
            elif i[0] == "jmp":
                i = ("jmp", self.labels[i[1]])
            elif i[0] == "pick":
                i = ("pick", i[1], i[2], i[3], self.labels[i[4]])
            out.append(i)
        self.ins = out
        return self


def _ev(regs, x):
    return x if type(x) is int else regs[x[1]] + x[2]


def _tset(t, i, v):
    return t[:i] + (v,) + t[i + 1:]


_CMP = {"eq": lambda a, b: a == b, "ne": lambda a, b: a != b,
        "le": lambda a, b: a <= b, "gt": lambda a, b: a > b}


class System:
    def __init__(self, name, cell_names, nhosts, progs, init_mem, host_names=None, prefetch=True, env_filter=None, writeback_events=False):
        self.name, self.cells, self.nc, self.nh = name, list(cell_names), len(cell_names), nhosts
        self.progs = [p.finish() for p in progs]
        self.init_mem = tuple(init_mem)
        self.prefetch = prefetch
        self.host_names = host_names or ["h%d" % i for i in range(nhosts)]
        acc = [set() for _ in range(nhosts)]
        for p in self.progs:
            for i in p.ins:
                if i[0] in ("load",):
                    acc[p.host].add(i[2])
                elif i[0] in ("store", "clflush", "clflushopt"):
                    acc[p.host].add(i[1])
        if env_filter is not None:
            acc = [{c for c in a if c in env_filter[h]} for h, a in enumerate(acc)]
        self.env_cells = [sorted(a) for a in acc]
        self.writeback_events = writeback_events

    # ---------------------------------------------------------------- init
    def initial(self):
        thr = []
        gh = (0, 0, 0)
        locks = (-1,) * self.nh
        for t, p in enumerate(self.progs):
            pc, regs, gh, locks, _ = self._advance(t, 0, (0,) * p.nregs, gh, locks)
            thr.append((pc, regs))
        return (self.init_mem,
                tuple(tuple(None for _ in range(self.nc)) for _ in range(self.nh)),
                ((),) * self.nh, ((),) * self.nh, (), tuple(thr), locks, gh)

    # ------------------------------------------------- eager local part
    def _advance(self, t, pc, regs, gh, locks, notes=None):
        p = self.progs[t]
        ins_l = p.ins
        h = p.host
        viols = []
        while True:
            ins = ins_l[pc]
            op = ins[0]
            if op in VISIBLE or op == "end":
                return pc, regs, gh, locks, viols
            if op == "set":
                regs = _tset(regs, ins[1], _ev(regs, ins[2]))
                pc += 1
            elif op == "br":
                pc = ins[4] if _CMP[ins[1]](_ev(regs, ins[2]), _ev(regs, ins[3])) else pc + 1
            elif op == "jmp":
                pc = ins[1]
            elif op == "mfence":
                pc += 1  # CPU ordering only: does NOT complete queued flushes
            elif op == "unlock":
                locks = _tset(locks, h, -1)
                pc += 1
            elif op == "g_enter":
                gh = (gh[0], gh[1], gh[2] | (1 << h))
                pc += 1
            elif op == "g_exit":
                gh = (gh[0], gh[1], gh[2] & ~(1 << h))
                pc += 1
            elif op == "g_snap":
                regs = _tset(regs, ins[1], gh[0])
                pc += 1
            elif op == "g_stale":
                if regs[ins[1]]:
                    regs = _tset(regs, ins[2], 1)
                pc += 1
            elif op == "g_hold_inc":
                viols += check_pin(gh[0])
                gh = (gh[0], gh[1] + 1, gh[2])
                pc += 1
            elif op == "g_hold_dec":
                gh = (gh[0], max(0, gh[1] - 1), gh[2])
                pc += 1
            elif op == "g_evict":
                viols += check_evict(gh[1])
                pc += 1
            elif op == "g_freed":
                gh = (1, gh[1], gh[2])
                pc += 1
            elif op == "g_use":
                viols += check_use(regs[ins[1]], regs[ins[2]], regs[ins[3]])
                pc += 1
            else:
                raise ValueError("unknown op %r" % (op,))

    # ----------------------------------------------------------- enabled
    def enabled(self, st):
        mem, caches, nt, fq, dma, thr, locks, gh = st
        acts = []
        for t, p in enumerate(self.progs):
            pc, regs = thr[t]
            ins = p.ins[pc]
            op = ins[0]
            if op == "end":
                continue
            h = p.host
            if op == "sfence" and nt[h]:
                continue
            if op == "lock" and locks[h] != -1:
                continue
            if op == "dma_wait":
                job = t * 10 + ins[1]
                if any(d[0] == job for d in dma):
                    continue
            if op == "pick":
                cands = [i for i, r in enumerate(ins[1]) if regs[r] == ins[2]]
                if cands:
                    for k in range(len(cands)):
                        acts.append(("T", t, k))
                    continue
            acts.append(("T", t, 0))
        for h in range(self.nh):
            seen = set()
            for i, (c, _v) in enumerate(nt[h]):
                if c not in seen:
                    acts.append(("nt", h, i))
                    seen.add(c)
            for c in fq[h]:
                acts.append(("fo", h, c))
        for i in range(len(dma)):
            acts.append(("dma", i))
        for h in range(self.nh):
            for c in self.env_cells[h]:
                e = caches[h][c]
                if e is None:
                    if self.prefetch:
                        acts.append(("fill", h, c))
                else:
                    acts.append(("evict", h, c))
                    if e[1] and self.writeback_events:
                        acts.append(("wb", h, c))
        return acts

    # --------------------------------------------------------------- apply
    def apply(self, st, a, verbose=False):
        """Return (new_state, violations, detail)."""
        mem, caches, nt, fq, dma, thr, locks, gh = st
        k = a[0]
        det = ""
        viols = []
        if k == "T":
            return self._exec(st, a[1], a[2], verbose)
        if k == "nt":
            h, i = a[1], a[2]
            c, v = nt[h][i]
            mem = _tset(mem, c, v)
            nt = _tset(nt, h, nt[h][:i] + nt[h][i + 1:])
            det = "ntstore drains: %s=%d reaches memory" % (self.cells[c], v)
        elif k == "fo":
            h, c = a[1], a[2]
            fq = _tset(fq, h, tuple(x for x in fq[h] if x != c))
            mem, caches, det = self._clflush(mem, caches, h, c)
            det = "queued clflushopt completes on %s: %s" % (self.cells[c], det)
        elif k == "dma":
            job, c, v = dma[a[1]]
            mem = _tset(mem, c, v)
            dma = dma[:a[1]] + dma[a[1] + 1:]
            det = "DMA word completes: %s=%d reaches memory" % (self.cells[c], v)
        elif k == "fill":
            h, c = a[1], a[2]
            caches = _tset(caches, h, _tset(caches[h], c, (mem[c], 0)))
            det = "prefetch fills %s=%d into cache" % (self.cells[c], mem[c])
        elif k == "evict":
            h, c = a[1], a[2]
            e = caches[h][c]
            if e[1]:
                mem = _tset(mem, c, e[0])
            caches = _tset(caches, h, _tset(caches[h], c, None))
            det = "cache evicts %s (%s)" % (self.cells[c], "dirty write-back %d" % e[0] if e[1] else "clean")
        elif k == "wb":
            h, c = a[1], a[2]
            e = caches[h][c]
            mem = _tset(mem, c, e[0])
            caches = _tset(caches, h, _tset(caches[h], c, (e[0], 0)))
            det = "cache writes back %s=%d (line stays valid)" % (self.cells[c], e[0])
        else:
            raise ValueError(a)
        return (mem, caches, nt, fq, dma, thr, locks, gh), viols, ("h%d: %s" % (a[1], det) if k in ("nt", "fo", "fill", "evict", "wb") else det)

    def _clflush(self, mem, caches, h, c):
        e = caches[h][c]
        if e is None:
            return mem, caches, "line not cached"
        d = "write-back %d + invalidate" % e[0] if e[1] else "invalidate clean"
        if e[1]:
            mem = _tset(mem, c, e[0])
        return mem, _tset(caches, h, _tset(caches[h], c, None)), d

    def _exec(self, st, t, choice, verbose):
        mem, caches, nt, fq, dma, thr, locks, gh = st
        p = self.progs[t]
        h = p.host
        pc, regs = thr[t]
        ins = p.ins[pc]
        op = ins[0]
        npc = pc + 1
        det = ""
        if op == "load":
            reg, c = ins[1], ins[2]
            v = None
            for cc, vv in reversed(nt[h]):
                if cc == c:
                    v = vv
                    det = "forwarded from pending ntstore"
                    break
            if v is None:
                e = caches[h][c]
                if e is not None:
                    v = e[0]
                    det = "cache HIT (may be stale; memory=%d)" % mem[c]
                else:
                    v = mem[c]
                    caches = _tset(caches, h, _tset(caches[h], c, (v, 0)))
                    det = "cache miss, read memory"
            regs = _tset(regs, reg, v)
            det = "%s = %d (%s)" % (p.txt[pc].split("->")[-1].strip(), v, det)
        elif op == "store":
            c, v = ins[1], _ev(regs, ins[2])
            caches = _tset(caches, h, _tset(caches[h], c, (v, 1)))
            det = "%s=%d in local cache only (dirty)" % (self.cells[c], v)
        elif op == "clflush":
            mem, caches, det = self._clflush(mem, caches, h, ins[1])
        elif op == "clflushopt":
            c = ins[1]
            if c not in fq[h]:
                fq = _tset(fq, h, tuple(sorted(fq[h] + (c,))))
            det = "queued only; completion is asynchronous"
        elif op == "ntstore":
            c, v = ins[1], _ev(regs, ins[2])
            caches = _tset(caches, h, _tset(caches[h], c, None))
            nt = _tset(nt, h, nt[h] + ((c, v),))
            det = "%s=%d queued in NT buffer (cache bypass)" % (self.cells[c], v)
        elif op == "sfence":
            det = "NT buffer drained"
        elif op == "dma_write":
            job = t * 10 + ins[1]
            dma = tuple(sorted(dma + tuple((job, c, v) for c, v in ins[2])))
            det = "DMA issued, completion asynchronous"
        elif op == "dma_wait":
            det = "DMA complete"
        elif op == "dma_read":
            v = mem[ins[2]]
            regs = _tset(regs, ins[1], v)
            det = "read memory directly = %d" % v
        elif op == "lock":
            locks = _tset(locks, h, t)
            det = "node-local mutex acquired"
        elif op == "pick":
            cands = [i for i, r in enumerate(ins[1]) if regs[r] == ins[2]]
            if cands:
                regs = _tset(regs, ins[3], cands[choice])
                det = "manager grants slot index %d" % cands[choice]
            else:
                npc = ins[4]
                det = "no WAITING slot"
        else:
            raise ValueError(op)
        pc2, regs, gh, locks, viols = self._advance(t, npc, regs, gh, locks)
        thr = _tset(thr, t, (pc2, regs))
        return (mem, caches, nt, fq, dma, thr, locks, gh), viols, ("%s: %s" % (p.txt[pc], det) if verbose else "")

    def successors(self, st):
        out = []
        for a in self.enabled(st):
            s2, v, _ = self.apply(st, a)
            out.append((a, s2, v))
        return out

    def check_state(self, st):
        return check_cs(st[7][2])

    def describe(self, st, a):
        s2, v, det = self.apply(st, a, verbose=True)
        if a[0] == "T":
            det = "%s.%s | %s" % (self.host_names[self.progs[a[1]].host], self.progs[a[1]].name, det)
        else:
            det = "env | " + det
        return det, s2, v
