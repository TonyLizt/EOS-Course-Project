"""用旧 CLI 函数重跑最近一次成功实验，检查新系统没有改变调度含义。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from algorithms.objectives import ObjectiveWeights
from eos_system.config import Settings
from eos_system.storage import Database
from main_scheduler import run_single_scheduling


def main() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise RuntimeError("请用 PYTHONHASHSEED=0 启动旧 CLI 对照脚本")
    database = Database(Settings.from_env().database_path)
    with database.connect() as db:
        row = db.execute("SELECT run_id FROM runs WHERE status='SUCCEEDED' AND algorithm_id='completion_first' ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        raise RuntimeError("先运行 scripts/smoke_system.py 生成成功实验")
    record = database.get_run(row["run_id"])
    config = record["config"]
    weights = ObjectiveWeights(**config["objective_weights"])
    with tempfile.TemporaryDirectory(prefix="eos-cli-parity-") as directory:
        metrics, plan_path, _ = run_single_scheduling(
            problem_json=Path(config["scenario_path"]), class_id=2,
            algo_name=config["algorithm_id"], placement_mode=config["placement_mode"],
            unassigned_penalty=config["constraints"]["unassigned_penalty"],
            downlink_duration_ratio=config["constraints"]["downlink_duration_ratio"],
            agility_profile=config["constraints"]["agility_profile"],
            non_agile_transition_s=config["constraints"]["non_agile_transition_s"],
            objective_weights=weights, cfg_overrides={"seed": config["seed"]},
            schedule_dir=Path(directory),
        )
        old_plan = json.loads(plan_path.read_text(encoding="utf-8"))
        old_assignments = sorted((item["task_id"], item["satellite_id"], item["sat_start_time"]) for item in old_plan["assignments"])
        new_assignments = sorted((item["task_id"], item["satellite_id"], item["sat_start_time"]) for item in record["plan"]["assignments"])
        if old_assignments != new_assignments:
            only_old = sorted(set(old_assignments) - set(new_assignments))[:5]
            only_new = sorted(set(new_assignments) - set(old_assignments))[:5]
            raise AssertionError(f"旧 CLI 与新 Worker 的 assignment 不一致；旧独有={only_old}，新独有={only_new}")
        assert abs(metrics.task_completion_rate - record["metrics"]["TCR"]) < 1e-12
        print(f"旧 CLI 对照通过：{len(new_assignments)} 个 assignment，TCR={metrics.task_completion_rate:.3f}")
    # TemporaryDirectory 在这里清理 JSON 和甘特图，不在仓库留下对照产物。


if __name__ == "__main__":
    main()
