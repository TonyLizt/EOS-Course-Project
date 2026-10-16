"""In-memory replay resource derived from one committed successful result."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .assets import load_model_resources
from .contracts import ReplayConfig
from .manifest import canonical_bytes, code_sha
from .read_only import ReplayInputError
from .timeline import build_task_phases


def _scheduler_utc_text(value: str) -> str:
    """Expose scheduler timestamps as explicit UTC without mutating the plan.

    The existing scenario loader normalises all input offsets to UTC and removes
    tzinfo before scheduling.  Consequently the committed schedule uses naive
    ISO strings even though their established meaning is UTC.
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat()


def _display_plan(plan: dict) -> dict:
    display = {**plan}
    display["start_time"] = _scheduler_utc_text(plan["start_time"])
    display["end_time"] = _scheduler_utc_text(plan["end_time"])
    display["assignments"] = [
        {
            **item,
            "sat_start_time": _scheduler_utc_text(item["sat_start_time"]),
            "sat_end_time": _scheduler_utc_text(item["sat_end_time"]),
        }
        for item in plan["assignments"]
    ]
    return display


def build_replay_document(record: dict, config_path: Path | None = None, *, config_data: dict | None = None) -> dict:
    scenario_path = Path(record["config"]["scenario_path"])
    scenario_bytes = scenario_path.read_bytes()
    scenario_sha = hashlib.sha256(scenario_bytes).hexdigest()
    if scenario_sha != record["config"]["scenario_sha256"]:
        raise ReplayInputError("scenario bytes differ from the committed run hash")
    scenario = json.loads(scenario_bytes)
    plan = record["plan"]
    if not isinstance(plan, dict) or plan.get("scenario_id") != scenario.get("scenario_id"):
        raise ReplayInputError("committed plan and scenario identities differ")
    plan_bytes = canonical_bytes(plan)
    display_plan = _display_plan(plan)
    # 构建进程使用已冻结配置；离线调用仍可读取原配置文件。
    config_bytes = canonical_bytes(config_data) if config_data is not None else config_path.read_bytes()
    replay_config = ReplayConfig.from_bytes(config_bytes)
    project_root = Path(__file__).parents[1]
    resources, asset_manifest_sha = load_model_resources(replay_config, project_root)
    constraints = record["config"].get("constraints") or {}
    segments, diagnostics = build_task_phases(
        scenario, display_plan,
        agility_profile=constraints.get("agility_profile", "Standard-Agility"),
        non_agile_transition_s=float(constraints.get("non_agile_transition_s", 10.0)),
    )
    identity = {
        "run_id": record["run_id"], "scenario_sha256": scenario_sha,
        "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "replay_config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "builder_code_sha": code_sha(project_root),
        "builder_version": "replay-document-v3", "propagation_version": "existing-orekit-czml-v1",
        "attitude_version": "geometry-pointing-fixed-payload-v1", "geometry_version": "wgs84-ray-ellipsoid-v1",
        "asset_manifest_sha256": asset_manifest_sha,
        "model_resources_sha256": hashlib.sha256(canonical_bytes(resources)).hexdigest(),
    }
    cache_key = hashlib.sha256(canonical_bytes(identity)).hexdigest()
    sensors_by_satellite = {}
    for sensor in replay_config.sensors:
        sensors_by_satellite.setdefault(sensor.satellite_id, []).append(sensor.as_dict())
    models_by_satellite = {model.satellite_id: model.as_dict() for model in replay_config.models}
    satellites = []
    for satellite in scenario["satellites"]:
        satellites.append({
            "id": satellite["id"],
            "maneuverability_type": (satellite.get("maneuverability_capability") or {}).get("maneuverability_type"),
            "sensors": sensors_by_satellite.get(satellite["id"], []),
            "model": models_by_satellite.get(satellite["id"], models_by_satellite.get("*")),
        })
    return {
        "schema_version": 2,
        "manifest": {
            **identity, "replay_id": cache_key[:24], "cache_key": cache_key,
            "scenario_id": scenario["scenario_id"], "replay_config_id": replay_config.replay_config_id,
            "start_time": display_plan["start_time"], "end_time": display_plan["end_time"],
            "reference_frame": "ECEF", "position_unit": "m", "quaternion_order": "xyzw",
            "rotation_direction": "body_to_ecef", "camera_axes": replay_config.camera_axes,
            "attitude_source": replay_config.attitude_source,
            "resources": resources,
        },
        "replay_config": replay_config.as_dict(),
        "satellites": satellites,
        "missions": [{"id": mission["id"], "target_location": mission["target_location"]} for mission in scenario["missions"]],
        "assignments": [{
            "assignment_ordinal": ordinal, "task_id": item["task_id"], "satellite_id": item["satellite_id"],
            "sensor_id": item["sensor_id"], "sat_start_time": item["sat_start_time"], "sat_end_time": item["sat_end_time"],
        } for ordinal, item in enumerate(display_plan["assignments"])],
        "segments": segments,
        "diagnostics": diagnostics,
        "warnings": [
            "Attitude is a deterministic target-pointing illustration, not an Orekit attitude export or dynamics validation.",
            "Legacy scheduler timestamps are exposed with an explicit UTC offset; committed plan bytes remain unchanged.",
            "This checkout parses plural *_angles fields in the legacy transition path; each actual result is recorded in diagnostics.",
        ],
    }
