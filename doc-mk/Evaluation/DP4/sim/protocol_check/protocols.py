"""C1 / C2 protocols and defect variants as programs over the abstract machine.

Block lifetime (one physical region, one entry cell S, refcount R, payload P0,P1):
  allocate(K1) -> payload DMA write (1,1) -> publish READY(K1) -> reader lookup/pin ->
  payload read -> unpin -> eviction (only if R==0) + reallocation for K2 -> payload (2,2) -> publish READY(K2)
Entry cell values: FREE=0, A1/A2 = allocated for K1/K2, R1/R2 = READY for K1/K2.
Allocator state is folded into S (single region); multi-writer allocator races are not modeled.
"""
from model import Prog, System

FREE, A1, A2, R1, R2 = 0, 1, 2, 3, 4
G_IDLE, G_WAIT, G_LOCK = 0, 1, 2
OP_UNPIN, OP_ALLOC1, OP_PUB1, OP_PIN, OP_ALLOC2, OP_PUB2 = 1, 2, 3, 4, 5, 6
RES_OK, RES_NF, RES_NOSPACE = 1, 2, 3

C2_BASE = dict(flush="clflush", inval_read=True, flush_write=True, double_grant=False,
               pub_before_dma=False, payload_cpu=False)


# ------------------------------------------------------------------ C2
def build_c2(nodes=2, prefetch=True, **over):
    fl = dict(C2_BASE, **over)
    S, R, P0, P1 = 0, 1, 2, 3
    G = lambda i: 4 + i
    names = ["S", "R", "P0", "P1"] + ["G%d" % i for i in range(nodes)]
    M = nodes
    hn = ["node%d" % i for i in range(nodes)] + ["lockmgr"]

    def flush(p, c):
        p.emit(fl["flush"], c)
        if fl["flush"] == "clflushopt":
            p.emit("mfence")

    def rd(p, c, reg):
        if fl["inval_read"]:
            flush(p, c)
        p.emit("load", p.r(reg), c)

    def wflush(p, c):
        if fl["flush_write"]:
            flush(p, c)

    def acquire(p, h):
        p.emit("lock")
        p.emit("store", G(h), G_WAIT)
        p.emit("clflush", G(h))
        lp = p.new_label("poll")
        p.label(lp)
        p.emit("clflush", G(h))
        p.emit("load", p.r("g"), G(h))
        p.emit("br", "ne", p.R("g"), G_LOCK, lp)
        p.emit("g_enter")

    def release(p, h):
        p.emit("g_exit")
        p.emit("store", G(h), G_IDLE)
        p.emit("clflush", G(h))
        p.emit("unlock")

    def abort_block(p, h, ab, cont):
        p.emit("jmp", cont)
        p.label(ab)
        release(p, h)
        p.emit("jmp", "end")
        p.label(cont)

    progs = []
    # producer / evictor on node0
    p = Prog("producer", 0, ["s", "r", "g"], names)
    ab, ct = p.new_label("ab"), p.new_label("ct")
    acquire(p, 0)                                   # CS1: allocate K1
    rd(p, S, "s"); p.emit("br", "ne", p.R("s"), FREE, ab)
    p.emit("store", S, A1); wflush(p, S)
    release(p, 0); abort_block(p, 0, ab, ct)

    def payload(val, job):
        if fl["payload_cpu"]:
            p.emit("store", P0, val); p.emit("store", P1, val)
        else:
            p.emit("dma_write", job, ((P0, val), (P1, val)))

    def dwait(job):
        if not fl["payload_cpu"]:
            p.emit("dma_wait", job)

    def publish(pre, key_a, key_r):
        ab, ct = p.new_label("ab"), p.new_label("ct")
        acquire(p, 0)
        rd(p, S, "s"); p.emit("br", "ne", p.R("s"), key_a, ab)
        p.emit("store", S, key_r); wflush(p, S)
        release(p, 0); abort_block(p, 0, ab, ct)

    payload(1, 1)
    if fl["pub_before_dma"]:
        publish(0, A1, R1)
        dwait(1)
    else:
        dwait(1)
        publish(0, A1, R1)
    ab, ct = p.new_label("ab"), p.new_label("ct")
    acquire(p, 0)                                   # CS3: evict K1 (R==0) + allocate K2
    rd(p, S, "s"); p.emit("br", "ne", p.R("s"), R1, ab)
    rd(p, R, "r"); p.emit("br", "gt", p.R("r"), 0, ab)
    p.emit("g_evict")
    p.emit("store", S, A2); wflush(p, S)
    release(p, 0)
    p.emit("g_freed")
    p.emit("jmp", ct)
    p.label(ab); release(p, 0); p.emit("jmp", "end")
    p.label(ct)
    payload(2, 2)
    dwait(2)
    publish(0, A2, R2)
    p.label("end"); p.emit("end")
    progs.append(p)

    for h in range(1, nodes):                       # readers
        p = Prog("reader", h, ["s", "r", "g", "sn", "stl", "p0", "p1"], names)
        p.emit("g_snap", p.r("sn"))
        rd(p, S, "s"); p.emit("br", "ne", p.R("s"), R1, "end")
        p.emit("g_stale", p.r("sn"), p.r("stl"))
        ab, ct = p.new_label("ab"), p.new_label("ct")
        acquire(p, h)                               # pin
        p.emit("g_snap", p.r("sn"))
        rd(p, S, "s"); p.emit("br", "ne", p.R("s"), R1, ab)
        p.emit("g_stale", p.r("sn"), p.r("stl"))
        rd(p, R, "r")
        p.emit("store", R, p.R("r", 1)); wflush(p, R)
        p.emit("g_hold_inc")
        release(p, h)
        p.emit("jmp", ct)
        p.label(ab); release(p, h); p.emit("jmp", "end")
        p.label(ct)
        p.emit("dma_read", p.r("p0"), P0)
        p.emit("dma_read", p.r("p1"), P1)
        p.emit("g_use", p.r("p0"), p.r("p1"), p.r("stl"))
        acquire(p, h)                               # unpin
        rd(p, R, "r")
        p.emit("store", R, p.R("r", -1)); wflush(p, R)
        p.emit("g_hold_dec")
        release(p, h)
        p.label("end"); p.emit("end")
        progs.append(p)

    p = Prog("manager", M, ["g%d" % i for i in range(nodes)] + ["sel"], names)
    p.label("loop")
    for i in range(nodes):
        p.emit("clflush", G(i)); p.emit("load", p.r("g%d" % i), G(i))
    for i in range(nodes):
        p.emit("br", "eq", p.R("g%d" % i), G_LOCK, "loop")
    if fl["double_grant"]:
        for i in range(nodes):
            nx = p.new_label("nx")
            p.emit("br", "ne", p.R("g%d" % i), G_WAIT, nx)
            p.emit("store", G(i), G_LOCK); p.emit("clflush", G(i))
            p.label(nx)
        p.emit("jmp", "loop")
    else:
        p.emit("pick", tuple(p.r("g%d" % i) for i in range(nodes)), G_WAIT, p.r("sel"), "loop")
        for i in range(nodes):
            nx = p.new_label("nx")
            p.emit("br", "ne", p.R("sel"), i, nx)
            p.emit("store", G(i), G_LOCK); p.emit("clflush", G(i)); p.emit("jmp", "loop")
            p.label(nx)
        p.emit("jmp", "loop")
    p.label("end"); p.emit("end")
    progs.append(p)
    cpu = {S, R} | ({P0, P1} if fl["payload_cpu"] else set())
    return System("C2", names, nodes + 1, progs, [0] * len(names), hn, prefetch,
                  env_filter=[cpu for _ in range(nodes + 1)])


# ------------------------------------------------------------------ C1
C1_BASE = dict(server_flush=True, pub_before_dma=False)


def build_c1(nodes=2, prefetch=True, **over):
    """node0 = metadata server host; hosts 1..nodes = clients (client1 = writer, others readers)."""
    fl = dict(C1_BASE, **over)
    nc = nodes
    cn = []
    for c in range(1, nc + 1):
        cn += ["RF%d" % c, "RB%d" % c, "PF%d" % c, "PB%d" % c]
    P0, P1 = 4 * nc, 4 * nc + 1
    names = cn + ["P0", "P1"]
    RF = lambda c: 4 * (c - 1)
    RB = lambda c: 4 * (c - 1) + 1
    PF = lambda c: 4 * (c - 1) + 2
    PB = lambda c: 4 * (c - 1) + 3
    hn = ["server"] + ["client%d" % c for c in range(1, nc + 1)]
    init = [0] * len(names)
    for c in range(1, nc + 1):
        init[RB(c)] = OP_UNPIN     # slot reuse: body still holds the previous request (assumption)
    progs = []

    p = Prog("metadata_server", 0,
             ["S", "R", "res", "f", "op"] + ["last%d" % c for c in range(1, nc + 1)], names)
    p.label("loop")
    for c in range(1, nc + 1):
        nx, rp = p.new_label("nx"), p.new_label("rp")
        if fl["server_flush"]:
            p.emit("clflush", RF(c))
        p.emit("load", p.r("f"), RF(c))
        p.emit("br", "ne", p.R("f"), p.R("last%d" % c, 1), nx)
        if fl["server_flush"]:
            p.emit("clflush", RB(c))
        p.emit("load", p.r("op"), RB(c))
        lab = {k: p.new_label(k) for k in ("un", "pn", "a1", "p1", "a2", "p2")}
        for opc, k in ((OP_UNPIN, "un"), (OP_PIN, "pn"), (OP_ALLOC1, "a1"), (OP_PUB1, "p1"),
                       (OP_ALLOC2, "a2"), (OP_PUB2, "p2")):
            p.emit("br", "eq", p.R("op"), opc, lab[k])
        p.emit("set", p.r("res"), RES_OK); p.emit("jmp", rp)
        p.label(lab["un"])
        z = p.new_label("z")
        p.emit("br", "le", p.R("R"), 0, z); p.emit("set", p.r("R"), p.R("R", -1))
        p.label(z); p.emit("set", p.r("res"), RES_OK); p.emit("jmp", rp)
        p.label(lab["pn"])
        nf = p.new_label("nf")
        p.emit("br", "ne", p.R("S"), R1, nf)
        p.emit("set", p.r("R"), p.R("R", 1)); p.emit("set", p.r("res"), RES_OK); p.emit("jmp", rp)
        p.label(nf); p.emit("set", p.r("res"), RES_NF); p.emit("jmp", rp)
        p.label(lab["a1"])
        ns = p.new_label("ns")
        p.emit("br", "ne", p.R("S"), FREE, ns)
        p.emit("set", p.r("S"), A1); p.emit("set", p.r("res"), RES_OK); p.emit("jmp", rp)
        p.label(ns); p.emit("set", p.r("res"), RES_NOSPACE); p.emit("jmp", rp)
        p.label(lab["p1"])
        nf2 = p.new_label("nf")
        p.emit("br", "ne", p.R("S"), A1, nf2)
        p.emit("set", p.r("S"), R1); p.emit("set", p.r("res"), RES_OK); p.emit("jmp", rp)
        p.label(nf2); p.emit("set", p.r("res"), RES_NF); p.emit("jmp", rp)
        p.label(lab["a2"])
        ns2, al = p.new_label("ns"), p.new_label("al")
        p.emit("br", "eq", p.R("S"), FREE, al)
        p.emit("br", "ne", p.R("S"), R1, ns2)
        p.emit("br", "gt", p.R("R"), 0, ns2)
        p.emit("g_evict"); p.emit("g_freed")
        p.label(al)
        p.emit("set", p.r("S"), A2); p.emit("set", p.r("res"), RES_OK); p.emit("jmp", rp)
        p.label(ns2); p.emit("set", p.r("res"), RES_NOSPACE); p.emit("jmp", rp)
        p.label(lab["p2"])
        nf3 = p.new_label("nf")
        p.emit("br", "ne", p.R("S"), A2, nf3)
        p.emit("set", p.r("S"), R2); p.emit("set", p.r("res"), RES_OK); p.emit("jmp", rp)
        p.label(nf3); p.emit("set", p.r("res"), RES_NF)
        p.label(rp)
        p.emit("ntstore", PB(c), p.R("res")); p.emit("sfence")
        p.emit("ntstore", PF(c), p.R("f")); p.emit("sfence")
        p.emit("set", p.r("last%d" % c), p.R("f"))
        p.label(nx)
    p.emit("jmp", "loop")
    p.label("end"); p.emit("end")
    progs.append(p)

    def send(p, c, op):
        p.emit("set", p.r("k"), p.R("k", 1))
        p.emit("ntstore", RB(c), op); p.emit("sfence")
        p.emit("ntstore", RF(c), p.R("k")); p.emit("sfence")

    def wait(p, c):
        lp = p.new_label("poll")
        p.label(lp)
        p.emit("clflush", PF(c)); p.emit("load", p.r("pf"), PF(c))
        p.emit("br", "ne", p.R("pf"), p.R("k"), lp)
        p.emit("clflush", PB(c)); p.emit("load", p.r("res"), PB(c))

    p = Prog("writer", 1, ["k", "pf", "res"], names)
    send(p, 1, OP_ALLOC1); wait(p, 1)
    p.emit("br", "ne", p.R("res"), RES_OK, "end")
    p.emit("dma_write", 1, ((P0, 1), (P1, 1)))
    if fl["pub_before_dma"]:
        send(p, 1, OP_PUB1); wait(p, 1); p.emit("dma_wait", 1)
    else:
        p.emit("dma_wait", 1); send(p, 1, OP_PUB1); wait(p, 1)
    send(p, 1, OP_ALLOC2); wait(p, 1)
    p.emit("br", "ne", p.R("res"), RES_OK, "end")
    p.emit("dma_write", 2, ((P0, 2), (P1, 2)))
    p.emit("dma_wait", 2); send(p, 1, OP_PUB2); wait(p, 1)
    p.label("end"); p.emit("end")
    progs.append(p)

    for c in range(2, nc + 1):
        p = Prog("reader", c, ["k", "pf", "res", "sn", "stl", "p0", "p1"], names)
        p.emit("g_snap", p.r("sn"))
        send(p, c, OP_PIN); wait(p, c)
        p.emit("br", "ne", p.R("res"), RES_OK, "end")
        p.emit("g_stale", p.r("sn"), p.r("stl"))
        p.emit("g_hold_inc")
        p.emit("dma_read", p.r("p0"), P0); p.emit("dma_read", p.r("p1"), P1)
        p.emit("g_use", p.r("p0"), p.r("p1"), p.r("stl"))
        p.emit("g_hold_dec")
        send(p, c, OP_UNPIN); wait(p, c)
        p.label("end"); p.emit("end")
        progs.append(p)
    return System("C1", names, nc + 1, progs, init, hn, prefetch,
                  env_filter=[{RF(c) for c in range(1, nc + 1)} | {RB(c) for c in range(1, nc + 1)}]
                  + [set() for _ in range(nc)])


# ------------------------------------------------------------- registry
VARIANTS = {
    "C1": dict(build=build_c1, over={}, kind="normal", expected=[],
               desc="central metadata server, CXL-RPC slots (ntstore + REQ_READY, CLFLUSH before read)"),
    "C2": dict(build=build_c2, over={}, kind="normal", expected=[],
               desc="shared metadata, 2-tier lock + lock manager, clflush before read / after write"),
    "C2_clflushopt": dict(build=build_c2, over=dict(flush="clflushopt"), kind="defect", expected=["I2"],
               desc="C2 with asynchronous clflushopt (+mfence) instead of clflush for metadata"),
    "C2_no_invalidate_before_read": dict(build=build_c2, over=dict(inval_read=False), kind="defect",
               expected=["I2"], desc="C2 without invalidate (flush) before reading metadata"),
    "C2_no_flush_before_unlock": dict(build=build_c2, over=dict(flush_write=False), kind="defect",
               expected=["I2"], desc="C2 without flushing modified metadata before unlock"),
    "C2_manager_double_grant": dict(build=build_c2, over=dict(double_grant=True), kind="defect",
               expected=["I3"], desc="lock manager grants LOCKED to every WAITING node"),
    "publish_before_dma_complete": dict(build=build_c2, over=dict(pub_before_dma=True), kind="defect",
               expected=["I1"], desc="C2 publish READY before DMA completion"),
    "C1_no_clflush_on_server": dict(build=build_c1, over=dict(server_flush=False), kind="defect",
               expected=["I1"], desc="C1 server does not CLFLUSH slot lines before reading"),
    "payload_via_cpu_cache": dict(build=build_c2, over=dict(payload_cpu=True), kind="defect",
               expected=["I1"], desc="C2 payload written with cached CPU stores, never flushed"),
}


def build(name, nodes=2, prefetch=True):
    v = VARIANTS[name]
    s = v["build"](nodes=nodes, prefetch=prefetch, **v["over"])
    s.name = name
    return s
