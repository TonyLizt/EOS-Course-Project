"""证明 Controller 的核验会拒绝篡改资源消耗的候选计划。"""

from __future__ import annotations

from copy import deepcopy

from eos_system.config import Settings
from eos_system.contracts import RunConfig
from eos_system.storage import Database
from eos_system.verification import verify_candidate


def main() -> None:
    database = Database(Settings.from_env().database_path)
    with database.connect() as db:
        row = db.execute("SELECT run_id FROM runs WHERE status='SUCCEEDED' AND algorithm_id='completion_first' ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        raise RuntimeError("先运行 scripts/smoke_system.py 生成正式计划")
    record = database.get_run(row["run_id"])
    config = RunConfig.model_validate(record["config"])
    altered = deepcopy(record["plan"])
    altered["assignments"][0]["data_volume_GB"] = 0.0
    try:
        verify_candidate(config, altered, 0.1)
    except ValueError as exc:
        assert "资源消耗" in str(exc), str(exc)
        print("篡改资源量的候选计划已被拒绝。")
    else:
        raise AssertionError("核验器错误地接受了篡改计划")
    assert database.get_run(row["run_id"])["status"] == "SUCCEEDED", "拒绝候选不应改变历史正式记录"


if __name__ == "__main__":
    main()
