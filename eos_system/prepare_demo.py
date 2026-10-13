"""从只读母场景生成一个固定小实例，放入 WSL 专用运行目录。"""

from __future__ import annotations

import argparse
from pathlib import Path

from input.scenario_splitter import split_scenario_file

from .config import Settings, sha256_file


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("/mnt/c/EOS-Bench"))
    args = parser.parse_args()
    source = args.data_root / "output_s1" / "Sats1_M100_T7d_dist0.json"
    if not source.is_file():
        parser.error(f"只读母场景不存在：{source}")
    settings = Settings.from_env()
    settings.scenario_dir.mkdir(parents=True, exist_ok=True)
    result = split_scenario_file(
        source, num_missions=30, start_offset="0h", duration="24h",
        search_root=source.parent, out_dir=settings.scenario_dir,
        out_name="demo-s1-30", seed=20260927,
    )
    print(f"母场景 SHA-256: {sha256_file(source)}")
    print(f"固定小实例：{result}")
    print(f"小实例 SHA-256: {sha256_file(Path(result))}")


if __name__ == "__main__":
    main()
