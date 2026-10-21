"""Collect immutable CAABS job evidence and produce flat CSV/mean tables."""
import argparse
import csv
import json
from pathlib import Path
import statistics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stem", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = {}
    rows = []
    for directory in args.inputs:
        manifest = json.loads((directory/"manifest.json").read_text(encoding="utf-8"))
        results = json.loads((directory/"results.json").read_text(encoding="utf-8"))
        evidence[directory.name] = dict(manifest=manifest,results=results)
        rows.extend(results)
    targets = [args.output/(args.stem+suffix) for suffix in (".json", ".csv", ".md")]
    if any(path.exists() for path in targets):
        parser.error("evidence already exists; choose a new stem")
    targets[0].write_text(json.dumps(evidence,indent=2),encoding="utf-8")
    flat=[]
    for row in rows:
        stats=row.get("diagnostics",{}).get("caabs",{}).get("stats",{})
        diagnostic=row.get("diagnostics",{}).get("caabs",{})
        flat.append({k:row.get(k) for k in ("id","name","suite","family","total","repeat","scenario_sha256","scenario_file_sha256","implementation_sha256","budget","runtime","completed","unassigned","status","controller_status","controller_error","peak_python_bytes")}
            | row.get("metrics",{}) | row.get("derived",{}) | stats
            | {k:diagnostic.get(k) for k in ("stop_reason","stop_phase")}
            | (row.get("process_memory") or {}))
    fields=list(dict.fromkeys(key for row in flat for key in row))
    with targets[1].open("w",newline="",encoding="utf-8-sig") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(flat)
    lines=["# CAABS measured means", "", "Only uninstrumented PUBLIC_PASS rows are summarized. Public replay is not physical certification.", "",
        "| Tasks | Variant | Runs | Completed | TP | TCR | BD | TM | RT(s) |", "|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    keys=sorted({(r.get("total",0),r["name"]) for r in rows if r.get("status")=="PUBLIC_PASS" and r["instrument"]=="none"})
    for n,name in keys:
        selected=[r for r in rows if r.get("total")==n and r["name"]==name and r.get("status")=="PUBLIC_PASS" and r["instrument"]=="none"]
        mean=lambda key:statistics.mean(r["metrics"][key] for r in selected)
        values=[statistics.mean(r["completed"] for r in selected),mean("task_profit"),mean("task_completion_rate"),mean("balance_degree"),mean("timeliness_metric"),statistics.mean(r["runtime"] for r in selected)]
        lines.append(f"| {n} | {name} | {len(selected)} | "+" | ".join(f"{v:.4f}" for v in values)+" |")
    targets[2].write_text("\n".join(lines)+"\n",encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
