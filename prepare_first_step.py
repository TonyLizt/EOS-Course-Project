"""Create two small, reproducible scenarios from the read-only EOS-Bench dataset."""

from __future__ import annotations

import argparse
from pathlib import Path

from input.scenario_splitter import split_scenario_file


CASES = (
    ("output_s1", "Sats1_M100_T7d_dist0.json", "Scenario_S2_Sats1_M100_T7d_dist0", 30),
    ("output_s3", "Sats3_M200_T7d_dist0.json", "Scenario_S3_Sats3_M200_T7d_dist0", 60),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260927)
    args = parser.parse_args()

    output_dir = Path(__file__).resolve().parent / "output"
    for subdir, filename, name, count in CASES:
        source = args.data_root / subdir / filename
        if not source.is_file():
            parser.error(f"Missing source scenario: {source}")
        result = split_scenario_file(
            source,
            num_missions=count,
            start_offset="0h",
            duration="24h",
            search_root=source.parent,
            out_dir=output_dir,
            out_name=name,
            seed=args.seed,
        )
        print(f"Prepared: {result}")


if __name__ == "__main__":
    main()
