#!/usr/bin/env python3
"""离线学习同状态候选的相对优势；不改变在线候选、特征和物理约束。"""
from __future__ import annotations

import argparse
from collections import defaultdict
import io
import json
import os
from pathlib import Path
import sys
import time

for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(name, "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from algorithms.lavis import training
from algorithms.lavis.model import (
    FrozenPredictor, dependencies, digest, freeze, inference_code_sha, model_root,
)
from algorithms.lavis.protocol import (
    CANDIDATE_VERSION, DOMAIN, FEATURE_NAMES, FEATURE_VERSION, LABEL_VERSION, POOL_CONFIG,
)


def relative_targets(rows, mode):
    """只在同一个真实状态内比较；平标签没有排序信号，不拿它们监督绝对分数。"""
    if mode not in ("task_advantage", "ordinal_rank"):
        raise ValueError("UNKNOWN_RANKING_TARGET")
    groups = defaultdict(list)
    for row in rows:
        groups[row["lineage_group_id"], row["state_hash"]].append(row)
    selected = []
    for values in groups.values():
        labels = [float(row["y"]) for row in values]
        if max(labels) - min(labels) <= 1e-12:
            continue
        mean = sum(labels) / len(labels)
        for row in values:
            if mode == "task_advantage":
                # 原y按剩余任务数归一化；还原为相对于同状态均值的额外任务数。
                target = (row["y"] - mean) * row["r"]
            else:
                # 同分取平均秩，映射到[-0.5, 0.5]；不把并列候选强行排出先后。
                lower = sum(value < row["y"] - 1e-12 for value in labels)
                tied = sum(abs(value - row["y"]) <= 1e-12 for value in labels)
                target = (lower + (tied - 1) / 2) / (len(labels) - 1) - .5
            selected.append(dict(row, raw_rollout_y=row["y"], y=target))
    if not selected:
        raise ValueError("NO_INFORMATIVE_RANKING_STATES")
    return selected


def passes_reference(candidate, reference):
    """原验证和高冲突总完成数均不退步，高冲突家族宏TCR还须严格改善。"""
    old = candidate["cohorts"]["eos-course-v1"]
    hard = candidate["cohorts"]["lavis-conflict-v1"]
    ref_old = reference["cohorts"]["eos-course-v1"]
    ref_hard = reference["cohorts"]["lavis-conflict-v1"]
    return (old["completed"] >= ref_old["completed"]
            and hard["completed"] >= ref_hard["completed"]
            and hard["family_macro_TCR"] > ref_hard["family_macro_TCR"] + 1e-12)


def refine(dataset, extra_dataset, output, model_id, budget):
    import joblib
    from sklearn.ensemble import HistGradientBoostingRegressor
    from threadpoolctl import threadpool_limits

    output = training.safe_output(output, dataset)
    training.safe_output(output, extra_dataset)
    target = model_root() / model_id
    if target.exists():
        raise ValueError("LAVIS_MODEL_ID_ALREADY_EXISTS_USE_NEW_ID")
    report_path = output / (model_id + "-ranking-report.json")
    if report_path.exists():
        raise ValueError("RANKING_REPORT_ALREADY_EXISTS_USE_NEW_ID")
    rows, sources, protocol = training.training_rows(output, extra_dataset=extra_dataset)
    _, _, _, rows = training.weighted_arrays(rows)
    started = time.perf_counter()
    reference_snapshot = freeze("lavis-v1")
    reference = training.evaluate(dataset, FrozenPredictor(reference_snapshot), budget, extra_dataset)
    print(json.dumps({"stage": "reference", "cohorts": reference["cohorts"]}), flush=True)
    trials = []
    best = None
    with threadpool_limits(limits=1):
        # 两种训练目标、两种树复杂度；不用验证数据构造特征、标签或改变场景划分。
        for mode in ("task_advantage", "ordinal_rank"):
            X, y, w, selected = training.weighted_arrays(relative_targets(rows, mode))
            for leaves in (15, 31):
                params = dict(max_iter=180, max_leaf_nodes=leaves, learning_rate=.05,
                              min_samples_leaf=5, l2_regularization=1.,
                              early_stopping=False, random_state=42)
                model = HistGradientBoostingRegressor(**params).fit(X, y, sample_weight=w)
                result = training.evaluate(dataset, training.Predictor(model), budget, extra_dataset)
                eligible = passes_reference(result, reference)
                trials.append({"target": mode, "params": params, "validation": result,
                               "passes_reference": eligible})
                rank = (-result["cohorts"]["lavis-conflict-v1"]["family_macro_TCR"],
                        -result["cohorts"]["eos-course-v1"]["completed"], mode, leaves)
                if eligible and (best is None or rank < best[0]):
                    best = (rank, model, params, mode, result, selected)
                print(json.dumps({"stage": "relative_trial", "target": mode, "leaves": leaves,
                                  "passes_reference": eligible, "cohorts": result["cohorts"]}), flush=True)
        if best is None:
            training.write_new(report_path, {"status": "REJECTED_KEEP_V1", "reference": reference,
                "trials": trials, "final_test_used": False})
            print(json.dumps({"stage": "rejected", "report": str(report_path)}), flush=True)
            return
        _, model, params, mode, result, selected = best
        original = [r for r in rows if r.get("data_origin", "eos-course-v1") == "eos-course-v1"]
        X0, y0, w0, _ = training.weighted_arrays(relative_targets(original, mode))
        control = HistGradientBoostingRegressor(**params).fit(X0, y0, sample_weight=w0)
        without_extra = training.evaluate(dataset, training.Predictor(control), budget, extra_dataset)
        control_result = {"same_target": mode, "same_params": params,
                          "without_conflict": without_extra, "with_conflict": result}
    physics_versions = {r["scenario_physics_version"] for r in selected}
    if len(physics_versions) != 1:
        raise ValueError("LAVIS_MIXED_PHYSICS_TRAINING_DOMAIN")
    buffer = io.BytesIO()
    joblib.dump(model, buffer, compress=3)
    data = buffer.getvalue()
    manifest = dict(model_id=model_id, model_version="0.3.0", format="team-joblib-v1",
        model_sha256=digest(data), feature_version=FEATURE_VERSION, features=list(FEATURE_NAMES),
        candidate_version=CANDIDATE_VERSION, label_version=LABEL_VERSION, pool_config=POOL_CONFIG,
        domain=DOMAIN, dependencies=dependencies(), inference_code_sha256_lf=inference_code_sha(),
        training_code_sha256=digest(Path(__file__).read_bytes()),
        shared_training_code_sha256=digest((ROOT / "algorithms/lavis/training.py").read_bytes()),
        split_sha256=training.split_sha(extra_dataset),
        training_sources_sha256=digest(training.encode(training.splits(extra_dataset)["train_development"])),
        validation_sources_sha256=digest(training.encode(training.splits(extra_dataset)["validation"])),
        label_protocol=protocol, target_transform=mode + "-informative-state-v1",
        training_rows=len(selected), training_params=params, training_seed=42,
        selected_training="base_informative_states", scenario_physics_version=next(iter(physics_versions)),
        training_source_whitelist_count=len(training.splits(extra_dataset)["train_development"]),
        effective_training_families=len({r["lineage_group_id"] for r in selected}),
        training_label_sources_sha256=digest(training.encode(sources)),
        extra_dataset_identity={"dataset_id": "lavis-conflict-v1",
            "spec_sha256": digest((Path(extra_dataset) / "dataset_spec.json").read_bytes()),
            "isolation_report_sha256": digest((Path(extra_dataset) / "isolation_report.json").read_bytes())})
    report = dict(status="PROMOTED", model=manifest, reference_model=reference_snapshot,
        reference_model_validation=reference, trials=trials, validation=result,
        data_only_comparison=control_result, training_seconds=time.perf_counter() - started,
        base_label_rows=len(rows), effective_rows=len(selected), sources=sources,
        final_test_used=False, note="Development validation selected target/hyperparameters; not final-test evidence")
    # 先保存完整诊断；登记成功的标志仍是最后写出的manifest。
    training.write_new(report_path, report)
    target.mkdir(parents=True)
    try:
        (target / "model.joblib").write_bytes(data)
        training.write_new(target / "training_report.json", report)
        training.write_new(target / "manifest.json", manifest)
    except BaseException:
        for name in ("model.joblib", "training_report.json", "manifest.json"):
            (target / name).unlink(missing_ok=True)
        target.rmdir()
        raise
    print(json.dumps({"stage": "registered", "model_id": model_id,
                      "model_sha256": manifest["model_sha256"], "cohorts": result["cohorts"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--extra-dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-id", default="lavis-v3-ranking")
    parser.add_argument("--budget", type=float, default=15.)
    args = parser.parse_args()
    import re
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", args.model_id):
        parser.error("模型ID不能是路径")
    if not .2 < args.budget <= 600:
        parser.error("budget需要大于0.2且不超过600")
    refine(args.dataset, args.extra_dataset, args.output, args.model_id, args.budget)


if __name__ == "__main__":
    main()
