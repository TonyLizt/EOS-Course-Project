"""对正在运行的系统做一次真实跨进程闭环检查。

用法：先启动 `python -m eos_system`，再执行本脚本；结果保存在数据库，不产生临时文件。
"""

from __future__ import annotations

import json
import time
from urllib.request import Request, urlopen


BASE = "http://127.0.0.1:8765"


def request(path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    with urlopen(Request(BASE + path, data=body, headers=headers), timeout=10) as response:
        return json.loads(response.read())


def main() -> None:
    scenes = request("/api/scenarios")["items"]
    assert scenes, "请先运行 python -m eos_system.prepare_demo"
    scene_id = scenes[0]["scenario_id"]
    created = request("/api/runs", {
        "scenario_id": scene_id, "algorithm_id": "completion_first", "seed": 20260927,
        "placement_mode": "earliest", "time_budget_s": 30,
        "objective_weights": {"w_profit": 0, "w_completion": 1, "w_timeliness": 0, "w_balance": 0},
    })
    run_id = created["run_id"]
    print(f"已提交：{run_id}")
    for _ in range(60):
        detail = request(f"/api/runs/{run_id}")
        if detail["status"] in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"}:
            break
        time.sleep(0.5)
    else:
        raise AssertionError("30 秒内未进入终态")
    if detail["status"] != "SUCCEEDED":
        raise AssertionError(f"实验失败：{detail['status']} {detail['error']}")
    assert detail["metrics"]["completed_tasks"] == len(detail["plan"]["assignments"])
    assert detail["metrics"]["TCR"] > 0
    with urlopen(BASE + f"/api/runs/{run_id}/export?format=json", timeout=10) as response:
        exported = json.loads(response.read())
    assert exported["scenario_id"] == detail["plan"]["scenario_id"]
    assert exported["metrics"]["TCR"] == detail["metrics"]["TCR"]
    with urlopen(BASE + f"/api/runs/{run_id}/export?format=csv", timeout=10) as response:
        csv_data = response.read().decode("utf-8-sig")
    assert "task_id" in csv_data and scene_id in csv_data
    print(f"通过：{detail['metrics']['completed_tasks']}/{detail['metrics']['total_tasks']}，TCR={detail['metrics']['TCR']:.3f}")
    print("JSON、CSV 导出均通过。")


if __name__ == "__main__":
    main()
