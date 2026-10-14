"""Strict, byte-preserving adapters for scenario and committed-plan JSON."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class ReplayInputError(ValueError):
    """The source data is missing or inconsistent; replay never repairs it."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json_bytes(path: Path) -> tuple[bytes, dict[str, Any]]:
    data = path.read_bytes()
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReplayInputError(f"invalid UTF-8 JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise ReplayInputError(f"JSON root must be an object: {path.name}")
    return data, value


def _iso(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ReplayInputError(f"{field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReplayInputError(f"invalid {field}: {value}") from exc
    if parsed.tzinfo is None:
        raise ReplayInputError(f"{field} has no verified timezone")
    return parsed


@dataclass(frozen=True)
class ReplayInputs:
    scenario_path: Path
    plan_path: Path
    scenario_bytes: bytes
    plan_bytes: bytes
    scenario: dict[str, Any]
    plan: dict[str, Any]
    scenario_sha256: str
    plan_sha256: str
    start_time: str
    end_time: str
    satellites: dict[str, dict[str, Any]]
    missions: dict[str, dict[str, Any]]


def load_replay_inputs(scenario_path: Path, plan_path: Path) -> ReplayInputs:
    """Load and cross-check sources without opening either file for writing."""
    scenario_path = scenario_path.resolve(strict=True)
    plan_path = plan_path.resolve(strict=True)
    scenario_bytes, scenario = _read_json_bytes(scenario_path)
    plan_bytes, plan = _read_json_bytes(plan_path)
    scenario_id = scenario.get("scenario_id")
    if not scenario_id or plan.get("scenario_id") != scenario_id:
        raise ReplayInputError("scenario_id differs between scenario and plan")

    satellites = {item.get("id"): item for item in scenario.get("satellites", []) if isinstance(item, dict)}
    missions = {item.get("id"): item for item in scenario.get("missions", []) if isinstance(item, dict)}
    if None in satellites or len(satellites) != len(scenario.get("satellites", [])):
        raise ReplayInputError("satellites must have unique non-empty ids")
    if None in missions or len(missions) != len(scenario.get("missions", [])):
        raise ReplayInputError("missions must have unique non-empty ids")

    meta = scenario.get("metadata") or {}
    scene_start = _iso(meta.get("creation_time"), "metadata.creation_time")
    try:
        scene_end = scene_start + timedelta(seconds=float(meta["duration"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayInputError("metadata.duration must be numeric") from exc
    start = _iso(plan.get("start_time"), "plan.start_time")
    end = _iso(plan.get("end_time"), "plan.end_time")
    if start != scene_start or end != scene_end:
        raise ReplayInputError("plan time range differs from scenario metadata")

    assignments = plan.get("assignments")
    if not isinstance(assignments, list):
        raise ReplayInputError("plan.assignments must be a list")
    seen_tasks: set[str] = set()
    for ordinal, item in enumerate(assignments):
        if not isinstance(item, dict):
            raise ReplayInputError(f"assignment {ordinal} must be an object")
        task_id, satellite_id, sensor_id = (item.get("task_id"), item.get("satellite_id"), item.get("sensor_id"))
        if task_id not in missions or task_id in seen_tasks:
            raise ReplayInputError(f"assignment {ordinal} has unknown or duplicate task_id")
        if satellite_id not in satellites:
            raise ReplayInputError(f"assignment {ordinal} has unknown satellite_id")
        sensors = (satellites[satellite_id].get("observation_capability") or {}).get("sensors", [])
        if sensor_id not in {sensor.get("sensor_id") for sensor in sensors}:
            raise ReplayInputError(f"assignment {ordinal} has unknown sensor_id")
        sat_start = _iso(item.get("sat_start_time"), f"assignment {ordinal} sat_start_time")
        sat_end = _iso(item.get("sat_end_time"), f"assignment {ordinal} sat_end_time")
        if not (scene_start <= sat_start < sat_end <= scene_end):
            raise ReplayInputError(f"assignment {ordinal} is outside the scenario time range")
        seen_tasks.add(task_id)

    return ReplayInputs(
        scenario_path=scenario_path,
        plan_path=plan_path,
        scenario_bytes=scenario_bytes,
        plan_bytes=plan_bytes,
        scenario=scenario,
        plan=plan,
        scenario_sha256=_sha256(scenario_bytes),
        plan_sha256=_sha256(plan_bytes),
        start_time=start.isoformat(),
        end_time=end.isoformat(),
        satellites=satellites,
        missions=missions,
    )


def require_isolated_output(output: Path, protected: list[Path]) -> Path:
    """Reject output that contains, equals, or is contained by a protected source."""
    target = output.expanduser().resolve()
    for item in protected:
        source = item.expanduser().resolve(strict=True)
        overlaps = target == source or source.is_relative_to(target)
        if source.is_dir():
            overlaps = overlaps or target.is_relative_to(source)
        if overlaps:
            raise ReplayInputError(f"replay output overlaps protected input: {source}")
    return target
