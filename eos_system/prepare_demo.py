"""从只读母场景生成一个固定小实例，放入 WSL 专用运行目录。"""

from __future__ import annotations

import argparse
from pathlib import Path

from input.scenario_splitter import split_scenario_file

from .config import Settings, sha256_file


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("/mnt/c/EOS-Bench"),
                        help="未指定 --source 时使用的数据根目录")
    parser.add_argument("--source", type=Path, help="任意现有的母场景 JSON（WSL 路径）")
    parser.add_argument("--output-dir", type=Path, help="派生场景输出目录，默认 WSL 运行目录的 scenarios")
    parser.add_argument("--name", default="demo-s1-30", help="派生文件名前缀")
    parser.add_argument("--tasks", type=int, default=30, help="抽取的任务数")
    parser.add_argument("--start-offset", default="0h")
    parser.add_argument("--duration", default="24h")
    parser.add_argument("--seed", type=int, default=20260927)
    args = parser.parse_args()
    source = args.source or args.data_root / "output_s1" / "Sats1_M100_T7d_dist0.json"
    if not source.is_file():
        parser.error(f"只读母场景不存在：{source}")
    settings = Settings.from_env()
    output_dir = args.output_dir or settings.scenario_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    result = split_scenario_file(
        source, num_missions=args.tasks, start_offset=args.start_offset, duration=args.duration,
        search_root=source.parent, out_dir=output_dir,
        out_name=args.name, seed=args.seed,
    )
    print(f"母场景 SHA-256: {sha256_file(source)}")
    print(f"固定小实例：{result}")
    print(f"小实例 SHA-256: {sha256_file(Path(result))}")


if __name__ == "__main__":
    main()
