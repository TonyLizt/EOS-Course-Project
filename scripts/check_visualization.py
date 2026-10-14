"""对一个已成功实验检查正式计划、旧页面入口与 CZML 回放。"""

from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError
from urllib.request import urlopen


def get(url: str):
    try:
        return urlopen(url, timeout=660)
    except HTTPError as exc:
        print(f"请求失败 {exc.code}：{exc.read().decode('utf-8', errors='replace')[:600]}")
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    root = f"{args.base}/api/runs/{args.run_id}/visualization"
    with get(root + "/schedule") as response:
        plan = json.load(response)
    assert plan["provenance"]["run_id"] == args.run_id
    with get(f"{args.base}/visualization/gantt/{args.run_id}") as response:
        assert "Satellite Observation Gantt Chart" in response.read().decode("utf-8")
    with get(f"{args.base}/visualization/cesium/{args.run_id}") as response:
        assert "Cesium" in response.read().decode("utf-8")
    with get(root + "/orbit.czml") as response:
        packets = json.load(response)
    assert packets and packets[0]["id"] == "document"
    print(f"回放接口通过：{len(plan['assignments'])} 条计划，{len(packets)} 个 CZML 包")


if __name__ == "__main__":
    main()
