"""Build a reproducible replay manifest beside, never inside, protected inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from .contracts import ReplayConfig
from .read_only import load_replay_inputs, require_isolated_output


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def code_sha(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=project_root, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def make_manifest(inputs, config: ReplayConfig, config_bytes: bytes, builder_code_sha: str) -> dict:
    cache_identity = {
        "scenario_sha256": inputs.scenario_sha256,
        "plan_sha256": inputs.plan_sha256,
        "replay_config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "builder_code_sha": builder_code_sha,
        "builder_version": "replay-contract-v2",
        "propagation_version": "existing-orekit-czml-v1",
        "attitude_version": "pending-commit-2",
        "geometry_version": "pending-commit-4",
    }
    return {
        "schema_version": 2,
        "replay_id": hashlib.sha256(canonical_bytes(cache_identity)).hexdigest()[:24],
        "scenario_id": inputs.scenario["scenario_id"],
        "replay_config_id": config.replay_config_id,
        **cache_identity,
        "cache_key": hashlib.sha256(canonical_bytes(cache_identity)).hexdigest(),
        "time_range": {"start_time": inputs.start_time, "end_time": inputs.end_time, "semantics": "scenario ISO-8601 offsets"},
        "coordinates": {
            "reference_frame": config.reference_frame,
            "position_unit": "m",
            "quaternion_order": config.quaternion_order,
            "rotation_direction": config.rotation_direction,
            "camera_axes": config.camera_axes,
            "mount_rotation_direction": "camera_to_body",
        },
        "attitude_source": config.attitude_source,
        "resources": [],
        "warnings": [
            "geometry_pointing_illustration is display-only and is not a dynamics validation",
            "single-value source FOV is shown as a square full-angle display assumption",
        ],
    }


def write_manifest(scenario: Path, plan: Path, config_path: Path, output: Path, protected: list[Path]) -> Path:
    inputs = load_replay_inputs(scenario, plan)
    config_bytes = config_path.read_bytes()
    config = ReplayConfig.from_bytes(config_bytes)
    target_dir = require_isolated_output(output, [scenario, plan, config_path, *protected])
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "manifest.json"
    data = json.dumps(make_manifest(inputs, config, config_bytes, code_sha(Path(__file__).parents[1])), ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target_dir, prefix=".manifest-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protected-root", action="append", type=Path, default=[])
    args = parser.parse_args()
    print(write_manifest(args.scenario, args.plan, args.config, args.output, args.protected_root))


if __name__ == "__main__":
    main()
