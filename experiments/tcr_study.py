"""Paired TCR study on 3-satellite, 200-task, 24-hour agile scenarios.

Inputs are the read-only released seven-day masters. All derived instances and
results live under output/experiments/tcr_study. These temporal crops are not
claimed to be the paper's ten independently generated instances.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from algorithms.objectives import ObjectiveWeights
from input.scenario_splitter import split_scenario_file
from main_scheduler import run_single_scheduling
from schedulers.scenario_loader import load_scheduling_problem_from_json
from verify_schedules import verify


ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "output" / "experiments" / "tcr_study"
SOURCES = {
    0: Path("output_s3/Sats3_M200_T7d_dist0.json"),
    1: Path("output_s3/Sats3_M200_T7d_dist1.json"),
}
ALGORITHMS = {
    "mip": 1,
    "completion_first": 2,
    "pressure_repair": 2,
    "adaptive_repair": 2,
    "sa": 3,
    "ga": 3,
    "aco": 3,
}
FIELDS = (
    "scenario", "distribution", "offset_h", "algorithm", "completed", "TP",
    "TCR", "BD", "TM", "RT_s", "plan",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scenario_path(distribution: int, offset_h: int, seed: int) -> Path:
    name = f"Scenario_Study_Sats3_M200_T1d_dist{distribution}_h{offset_h:03}_seed{seed}.json"
    return STUDY / "scenarios" / name


def prepare(data_root: Path, distributions: list[int], offsets: list[int], seed: int) -> None:
    scenarios = STUDY / "scenarios"
    scenarios.mkdir(parents=True, exist_ok=True)
    manifest = {
        "description": "Derived temporal crops; not the paper's original ten instances",
        "settings": {
            "satellites": 3, "tasks": 200, "horizon_h": 24,
            "platform": "agile", "agility_profile": "Standard-Agility",
            "placement_mode": "earliest", "objective": "TCR",
            "seed": seed,
        },
        "scenarios": [],
    }
    manifest_path = STUDY / "manifest.json"
    previous = {}
    if manifest_path.is_file():
        old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if old_manifest.get("settings") != manifest["settings"]:
            raise ValueError("Existing study manifest uses different fixed settings")
        previous = {item["file"]: item for item in old_manifest.get("scenarios", [])}
    for distribution in distributions:
        source = data_root / SOURCES[distribution]
        if not source.is_file():
            raise FileNotFoundError(source)
        source_hash = sha256(source)
        for offset_h in offsets:
            target = scenario_path(distribution, offset_h, seed)
            if not target.is_file():
                produced = split_scenario_file(
                    source, num_missions=200, start_offset=f"{offset_h}h",
                    duration="24h", search_root=source.parent,
                    out_dir=scenarios,
                    out_name=f"Scenario_Study_Sats3_M200_T7d_dist{distribution}_h{offset_h:03}",
                    seed=seed,
                )
                if Path(produced) != target:
                    raise RuntimeError(f"Unexpected splitter output: {produced}")
            relative = str(target.relative_to(STUDY))
            target_hash = sha256(target)
            if relative in previous:
                old = previous[relative]
                if old["sha256"] != target_hash or old["source_sha256"] != source_hash:
                    raise ValueError(f"Existing scenario or source has changed: {target}")
            problem = load_scheduling_problem_from_json(target)
            if (len(problem.satellites) != 3 or len(problem.tasks) != 200
                    or (problem.end_time - problem.start_time).total_seconds() != 86400
                    or any(s.maneuverability_type != "agile" for s in problem.satellites.values())):
                raise ValueError(f"Scenario does not match paper-aligned configuration: {target}")
            previous[relative] = {
                "file": relative,
                "sha256": target_hash,
                "source": str(source),
                "source_sha256": source_hash,
                "distribution": distribution,
                "offset_h": offset_h,
            }
            print(f"Prepared dist={distribution} offset={offset_h}h: {target.name}")
    manifest["scenarios"] = [previous[key] for key in sorted(previous)]
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


def run(distributions: list[int], offsets: list[int], seed: int,
        algorithms: list[str], mip_limit_s: int, rerun: bool = False) -> None:
    result_path = STUDY / "results.csv"
    manifest_path = STUDY / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Run prepare first: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["settings"]["seed"] != seed:
        raise ValueError("Study seed does not match the prepared manifest")
    prepared = {item["file"]: item for item in manifest["scenarios"]}
    rows: dict[tuple[str, str], dict] = {}
    if result_path.is_file():
        with result_path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                rows[(row["scenario"], row["algorithm"])] = row

    for distribution in distributions:
        for offset_h in offsets:
            scenario = scenario_path(distribution, offset_h, seed)
            if not scenario.is_file():
                raise FileNotFoundError(f"Run prepare first: {scenario}")
            relative = str(scenario.relative_to(STUDY))
            if relative not in prepared or sha256(scenario) != prepared[relative]["sha256"]:
                raise ValueError(f"Scenario is missing from manifest or has changed: {scenario}")
            for algorithm in algorithms:
                key = (scenario.stem, algorithm)
                if key in rows and not rerun:
                    print(f"Already recorded: {scenario.stem} {algorithm}")
                    continue
                class_id = ALGORITHMS[algorithm]
                overrides = {"seed": seed + 100 * offset_h + distribution}
                if algorithm == "mip":
                    overrides["time_limit_sec"] = mip_limit_s
                metrics, plan, _ = run_single_scheduling(
                    problem_json=scenario,
                    class_id=class_id,
                    algo_name=algorithm,
                    placement_mode="earliest",
                    agility_profile="Standard-Agility",
                    objective_weights=ObjectiveWeights(0, 1, 0, 0),
                    cfg_overrides=overrides,
                    schedule_dir=STUDY / "schedules",
                )
                completed = verify(scenario, plan)
                rows[key] = {
                    "scenario": scenario.stem,
                    "distribution": distribution,
                    "offset_h": offset_h,
                    "algorithm": algorithm,
                    "completed": completed,
                    "TP": metrics.task_profit,
                    "TCR": metrics.task_completion_rate,
                    "BD": metrics.balance_degree,
                    "TM": metrics.timeliness_metric,
                    "RT_s": metrics.runtime_efficiency,
                    "plan": str(plan.relative_to(STUDY)),
                }
                result_path.parent.mkdir(parents=True, exist_ok=True)
                with result_path.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=FIELDS)
                    writer.writeheader()
                    writer.writerows(rows.values())
                print(f"Recorded {algorithm}: {completed}/200 on dist={distribution} offset={offset_h}h")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--distributions", type=int, nargs="+", choices=(0, 1), default=[0, 1])
    parser.add_argument("--offsets", type=int, nargs="+", default=[0])
    parser.add_argument("--seed", type=int, default=20260927)
    parser.add_argument("--algos", nargs="+", choices=tuple(ALGORITHMS),
                        default=["completion_first", "sa", "ga", "aco", "adaptive_repair"])
    parser.add_argument("--mip-limit-s", type=int, default=3600)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--run-only", action="store_true")
    parser.add_argument("--rerun", action="store_true",
                        help="Replace selected algorithms' earlier study results")
    args = parser.parse_args()
    if args.prepare_only and args.run_only:
        parser.error("Choose only one of --prepare-only and --run-only")
    if any(offset < 0 or offset > 144 for offset in args.offsets):
        parser.error("Each 24-hour offset must fit inside the 7-day master (0..144h)")
    if not args.run_only:
        prepare(args.data_root, args.distributions, args.offsets, args.seed)
    if not args.prepare_only:
        run(args.distributions, args.offsets, args.seed, args.algos,
            args.mip_limit_s, rerun=args.rerun)


if __name__ == "__main__":
    main()
