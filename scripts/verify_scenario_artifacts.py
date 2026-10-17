#!/usr/bin/env python3
"""Print a read-only R1-02 artifact verification report to stdout."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from eos_system.scenario_artifacts import load_index, verify_index


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog="Exit 0: PASS/WARN; 1: FAIL; 2: usage/index IO. Does not register or publish.")
    parser.add_argument("--index", type=Path, default=ROOT / "data/registry/scenario_artifacts.v1.json")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--evidence-root", action="append", default=[], metavar="NAME=ABSOLUTE_PATH")
    args = parser.parse_args(argv)
    roots = {}
    for value in args.evidence_root:
        name, sep, path = value.partition("=")
        if not sep or not name or name in roots or not Path(path).is_absolute():
            parser.error("each evidence root needs a unique NAME=ABSOLUTE_PATH")
        roots[name] = Path(path)
    try:
        result = verify_index(load_index(args.index), repo_root=args.repo_root, evidence_roots=roots)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
