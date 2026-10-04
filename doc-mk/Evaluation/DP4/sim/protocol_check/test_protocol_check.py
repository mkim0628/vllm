"""unittest suite: memory semantics, checker determinism, normal pass, defect detection, replay.

  cd protocol_check && uv run --no-project python -m unittest test_protocol_check -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check  # noqa: E402
import protocols  # noqa: E402
from model import Prog, System  # noqa: E402

CAP = 1_500_000


def mini(prog_fn, ncells=2, nhosts=2, init=None, env=None, prefetch=False):
    """Tiny system: host0 runs the program, host1 idle."""
    names = ["X", "Y"][:ncells]
    p = Prog("t", 0, ["a", "b"], names)
    prog_fn(p)
    p.emit("end")
    return System("mini", names, nhosts, [p], init or [0] * ncells, prefetch=prefetch,
                  env_filter=env, writeback_events=True)


def run_all(sysm, state=None, steps=50):
    """Run only thread steps (deterministic) until blocked."""
    s = state or sysm.initial()
    for _ in range(steps):
        acts = [a for a in sysm.enabled(s) if a[0] == "T"]
        if not acts:
            break
        s = sysm.apply(s, acts[0])[0]
    return s


def env_actions(sysm, s, kind):
    return [a for a in sysm.enabled(s) if a[0] == kind]


class MemorySemantics(unittest.TestCase):
    def test_store_is_local_only(self):
        sm = mini(lambda p: p.emit("store", 0, 5))
        s = run_all(sm)
        self.assertEqual(s[0][0], 0)            # memory unchanged
        self.assertEqual(s[1][0][0], (5, 1))    # dirty in local cache

    def test_clflush_is_synchronous(self):
        def f(p):
            p.emit("store", 0, 5); p.emit("clflush", 0)
        s = run_all(mini(f))
        self.assertEqual(s[0][0], 5)
        self.assertIsNone(s[1][0][0])

    def test_clflushopt_is_asynchronous(self):
        def f(p):
            p.emit("store", 0, 5); p.emit("clflushopt", 0); p.emit("mfence")
        sm = mini(f)
        s = run_all(sm)
        self.assertEqual(s[0][0], 0)            # mfence did not complete the flush
        self.assertEqual(s[3][0], (0,))         # still queued
        fo = env_actions(sm, s, "fo")
        self.assertEqual(len(fo), 1)
        s2 = sm.apply(s, fo[0])[0]
        self.assertEqual(s2[0][0], 5)

    def test_ntstore_bypasses_cache_and_sfence_waits(self):
        def f(p):
            p.emit("ntstore", 0, 7); p.emit("sfence"); p.emit("set", 0, 1)
        sm = mini(f)
        s = run_all(sm)
        self.assertEqual(s[1][0][0], None)
        self.assertEqual(s[2][0], ((0, 7),))
        self.assertEqual(s[0][0], 0)            # not in memory yet; sfence blocked
        self.assertEqual([a for a in sm.enabled(s) if a[0] == "T"], [])
        s = sm.apply(s, env_actions(sm, s, "nt")[0])[0]
        self.assertEqual(s[0][0], 7)
        s = run_all(sm, s)
        self.assertEqual(s[5][0][1][0], 1)      # sfence passed

    def test_dma_async_and_wait(self):
        def f(p):
            p.emit("dma_write", 1, ((0, 3), (1, 3))); p.emit("dma_wait", 1)
        sm = mini(f)
        s = run_all(sm)
        self.assertEqual(s[0], (0, 0))
        self.assertEqual(len(s[4]), 2)
        self.assertEqual([a for a in sm.enabled(s) if a[0] == "T"], [])    # wait blocked
        s = sm.apply(s, env_actions(sm, s, "dma")[0])[0]
        self.assertEqual(sum(1 for x in s[0] if x == 3), 1)                 # partial visible
        s = sm.apply(s, env_actions(sm, s, "dma")[0])[0]
        self.assertEqual(s[0], (3, 3))
        self.assertTrue([a for a in sm.enabled(s) if a[0] == "T"])

    def test_dma_bypasses_cpu_cache(self):
        def f(p):
            p.emit("store", 0, 9); p.emit("dma_read", p.r("a"), 0)
        s = run_all(mini(f))
        self.assertEqual(s[5][0][1][0], 0)      # DMA read sees memory, not dirty cache

    def test_stale_hit_without_flush(self):
        def f(p):
            p.emit("load", p.r("a"), 0); p.emit("load", p.r("b"), 0)
        sm = mini(f)
        s = sm.initial()
        s = sm.apply(s, ("T", 0, 0))[0]
        s = (s[0][:0] + (4,) + s[0][1:],) + s[1:]       # other node updates memory
        s = sm.apply(s, ("T", 0, 0))[0]
        self.assertEqual(s[5][0][1], (0, 0))            # second load hits stale 0

    def test_cache_evict_nondeterministic(self):
        def f(p):
            p.emit("store", 0, 5); p.emit("load", p.r("a"), 1)
        sm = mini(f, env=[{0}, set()], prefetch=True)
        s = run_all(sm, steps=1)
        kinds = {a[0] for a in sm.enabled(s)}
        self.assertIn("evict", kinds)
        self.assertIn("wb", kinds)
        s2 = sm.apply(s, env_actions(sm, s, "evict")[0])[0]
        self.assertEqual(s2[0][0], 5)                   # dirty evict writes back
        self.assertIsNone(s2[1][0][0])


class CheckerBehaviour(unittest.TestCase):
    def test_deterministic_exploration(self):
        a = check.explore(protocols.build("C2_manager_double_grant", 2), 20000)
        b = check.explore(protocols.build("C2_manager_double_grant", 2), 20000)
        self.assertEqual(a["states"], b["states"])
        self.assertEqual(a["transitions"], b["transitions"])
        self.assertEqual({k: v[0] for k, v in a["cex"].items()}, {k: v[0] for k, v in b["cex"].items()})

    def test_replay_counterexample(self):
        sysm = protocols.build("publish_before_dma_complete", 2)
        r = check.explore(sysm, CAP)
        acts, _ = r["cex"]["I1"]
        trace, viols = check.replay(sysm, acts)
        self.assertEqual(len(trace), len(acts))
        self.assertIn("I1", [v[0] for v in viols])
        # prefix of the trace does not violate: counterexample is minimal under BFS
        for k in range(1, len(acts)):
            _, v = check.replay(sysm, acts[:k])
            self.assertNotIn("I1", [x[0] for x in v])

    def test_replay_rejects_disabled_action(self):
        sysm = protocols.build("C2", 2)
        with self.assertRaises(ValueError):
            check.replay(sysm, [("dma", 0)])


class NormalProtocols(unittest.TestCase):
    def _normal(self, name):
        r = check.explore(protocols.build(name, 2), CAP)
        self.assertFalse(r["capped"], "exploration must be complete")
        self.assertEqual(r["cex"], {}, "unexpected counterexample: %r" % r["cex"])
        self.assertGreater(r["states"], 1000)

    def test_C1_passes_all_invariants(self):
        self._normal("C1")

    def test_C2_passes_all_invariants(self):
        self._normal("C2")


class DefectVariants(unittest.TestCase):
    def _detect(self, name, must):
        r = check.explore(protocols.build(name, 2), CAP)
        for iv in must:
            self.assertIn(iv, r["cex"], "%s: %s not detected (found %s)" % (name, iv, sorted(r["cex"])))
        return r

    def test_clflushopt_stale_refcount(self):
        self._detect("C2_clflushopt", ["I2"])

    def test_no_invalidate_before_read(self):
        self._detect("C2_no_invalidate_before_read", ["I2"])

    def test_no_flush_before_unlock(self):
        self._detect("C2_no_flush_before_unlock", ["I2"])

    def test_manager_double_grant(self):
        r = self._detect("C2_manager_double_grant", ["I3"])
        self.assertEqual(r["cex"]["I3"][0][-1][0], "T")

    def test_publish_before_dma_complete(self):
        self._detect("publish_before_dma_complete", ["I1"])

    def test_c1_no_clflush_on_server(self):
        self._detect("C1_no_clflush_on_server", ["I1"])

    def test_payload_via_cpu_cache(self):
        self._detect("payload_via_cpu_cache", ["I1"])

    def test_every_variant_registered_with_expectation(self):
        for n, v in protocols.VARIANTS.items():
            self.assertEqual(v["kind"] == "defect", bool(v["expected"]), n)


if __name__ == "__main__":
    unittest.main()
