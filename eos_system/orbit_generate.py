"""独立子进程中的 Orekit 入口；不启动旧版第二个 HTTP 服务。"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from replay.scene import file_sha256
from .visualization import ORBIT_STEP_S

from draw.orekit_to_czml import demo


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--orekit-data", required=True)
    parser.add_argument("--orbit-step-s", type=float, default=ORBIT_STEP_S)
    args = parser.parse_args()
    source = Path(args.orekit_data)
    if source.is_file():
        # Orekit 对 ZIP 有大量细碎读取；复制到 Linux 临时盘以避开 DrvFS 开销。
        # 每次只有这一份临时副本；校验后使用，正常/异常退出都会自动清理。
        with tempfile.TemporaryDirectory(prefix="eos-orbit-data-") as directory:
            local = Path(directory) / source.name
            shutil.copyfile(source, local)
            if file_sha256(source) != file_sha256(local):
                raise ValueError("Orekit 临时数据包与原包 SHA 不符")
            demo(scenario_path=args.scenario, output_czml=args.output,
                 orekit_data_path=str(local), orbit_step_s=args.orbit_step_s)
    else:
        # 保留原 CLI 对已展开数据目录的支持。
        demo(scenario_path=args.scenario, output_czml=args.output,
             orekit_data_path=args.orekit_data, orbit_step_s=args.orbit_step_s)


if __name__ == "__main__":
    main()
