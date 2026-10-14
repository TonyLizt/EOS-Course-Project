"""独立子进程中的 Orekit 入口；不启动旧版第二个 HTTP 服务。"""

from __future__ import annotations

import argparse

from draw.orekit_to_czml import demo


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--orekit-data", required=True)
    parser.add_argument("--orbit-step-s", type=float, default=300.0)
    args = parser.parse_args()
    demo(scenario_path=args.scenario, output_czml=args.output,
         orekit_data_path=args.orekit_data, orbit_step_s=args.orbit_step_s)


if __name__ == "__main__":
    main()
