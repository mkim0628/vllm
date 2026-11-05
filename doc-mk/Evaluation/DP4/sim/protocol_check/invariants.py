"""Safety invariants I1..I4 of the DP4 protocol model check.

Only safety is checked (liveness / progress is out of scope).  Each helper
returns a list of (invariant_id, message); an empty list means no violation.
"""
I1, I2, I3, I4 = "I1", "I2", "I3", "I4"
ALL = (I1, I2, I3, I4)

DESCRIPTION = {
    I1: "payload visibility: after seeing READY the payload read is the complete value the writer wrote",
    I2: "no use-after-free: a block with refcount>0 (a reader holds a pin) is never evicted/reallocated",
    I3: "mutual exclusion: at most one node inside the critical section of the global lock (C2)",
    I4: "no stale index resurrect: a READY entry observed after the block was freed is never used",
}

EXPECTED_PAYLOAD = (1, 1)


def check_use(p0, p1, stale):
    out = []
    if (p0, p1) != EXPECTED_PAYLOAD:
        out.append((I1, "reader used payload (%d,%d) after seeing READY; expected complete value %s"
                    % (p0, p1, EXPECTED_PAYLOAD)))
    if stale:
        out.append((I4, "reader saw READY for an entry that had already been freed and then used its payload"))
    return out


def check_evict(holders):
    if holders > 0:
        return [(I2, "block evicted/reallocated while %d reader(s) hold a pin" % holders)]
    return []


def check_pin(freed):
    if freed:
        return [(I2, "reader obtained a pin on a block that was already freed")]
    return []


def check_cs(mask):
    if mask & (mask - 1):
        return [(I3, "two nodes inside the global critical section (host mask=%s)" % bin(mask))]
    return []
