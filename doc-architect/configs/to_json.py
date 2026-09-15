#!/usr/bin/env python3
"""memories_default.yaml -> memories_default.json

YAML is the source of truth because strict JSON has no comment syntax and
these values need their units and provenance visible where they are edited.
This exports a machine-readable copy for consumers that want JSON; the
provenance and note fields survive as data, and a `units` block is added so
the magnitudes stay readable there too.

    python3 to_json.py            # regenerate memories_default.json
    python3 to_json.py --check    # fail if the json is stale (for CI)
"""

import argparse
import json
import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).parent
SRC = HERE / "memories_default.yaml"
DST = HERE / "memories_default.json"

TIB = 1024**4
GIB = 1024**3


def humanize(mem: dict) -> dict:
    """Attach a units block so the JSON is readable without a calculator."""
    cap = mem["capacity_bytes"]
    units = {
        "capacity": f"{cap / TIB:.2f} TiB" if cap >= TIB else f"{cap / GIB:.0f} GiB",
        "ext_bw": f"{mem['ext_bw_bytes_per_s'] / 1e12:.3f} TB/s",
        "int_bw": f"{mem['int_bw_bytes_per_s'] / 1e12:.3f} TB/s",
        "latency": f"{mem['latency_s'] * 1e9:.0f} ns"
        if mem["latency_s"] < 1e-6
        else f"{mem['latency_s'] * 1e6:.0f} us",
        "int_ext_asymmetry": f"{mem['int_bw_bytes_per_s'] / mem['ext_bw_bytes_per_s']:.1f}x",
    }
    if mem.get("write_bw_bytes_per_s"):
        units["write_bw"] = f"{mem['write_bw_bytes_per_s'] / 1e12:.3f} TB/s"
    if mem.get("endurance_budget_bytes"):
        units["endurance_budget"] = f"{mem['endurance_budget_bytes'] / 1e15:.0f} PB"
    return {**mem, "units": units}


def build() -> dict:
    doc = yaml.safe_load(SRC.read_text(encoding="utf-8"))
    doc["_generated_from"] = SRC.name
    doc["_note"] = (
        "Generated file - edit memories_default.yaml and rerun to_json.py. "
        "See the yaml for per-field src: SPEC / PUBLIC / ASSUMED tags."
    )
    doc["memories"] = [humanize(m) for m in doc["memories"]]
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if json is stale")
    args = ap.parse_args()

    text = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not DST.exists() or DST.read_text(encoding="utf-8") != text:
            print(f"{DST.name} is stale; run: python3 {pathlib.Path(__file__).name}")
            return 1
        print(f"{DST.name} is up to date")
        return 0

    DST.write_text(text, encoding="utf-8")
    print(f"wrote {DST.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
