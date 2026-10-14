"""Contracts owned by replay; none of these fields enter scheduler constraints."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ReplayConfigError(ValueError):
    pass


def _only(data: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ReplayConfigError(f"unknown {label} fields: {sorted(unknown)}")


@dataclass(frozen=True)
class SensorDisplayConfig:
    satellite_id: str
    sensor_id: str
    sensor_mount_quaternion_xyzw: tuple[float, float, float, float]
    sensor_offset_body_m: tuple[float, float, float]
    fov_interpretation: str
    horizontal_full_fov_deg: float
    vertical_full_fov_deg: float

    @classmethod
    def parse(cls, data: dict[str, Any]) -> "SensorDisplayConfig":
        _only(data, set(cls.__dataclass_fields__), "sensor")
        try:
            mount = tuple(float(value) for value in data["sensor_mount_quaternion_xyzw"])
            offset = tuple(float(value) for value in data.get("sensor_offset_body_m", [0, 0, 0]))
            horizontal = float(data["horizontal_full_fov_deg"])
            vertical = float(data["vertical_full_fov_deg"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ReplayConfigError("invalid numeric sensor configuration") from exc
        if len(mount) != 4 or not all(math.isfinite(value) for value in mount) or abs(sum(v * v for v in mount) - 1) > 1e-8:
            raise ReplayConfigError("sensor mount quaternion must be a finite unit xyzw quaternion")
        if len(offset) != 3 or not all(math.isfinite(value) for value in offset):
            raise ReplayConfigError("sensor offset must contain three finite metres")
        if not (0 < horizontal < 180 and 0 < vertical < 180):
            raise ReplayConfigError("full FOV angles must be between 0 and 180 degrees")
        if data.get("fov_interpretation") != "square_full_angle_display_assumption":
            raise ReplayConfigError("unsupported FOV interpretation")
        return cls(str(data["satellite_id"]), str(data["sensor_id"]), mount, offset,
                   data["fov_interpretation"], horizontal, vertical)

    def as_dict(self) -> dict[str, Any]:
        return {
            "satellite_id": self.satellite_id, "sensor_id": self.sensor_id,
            "sensor_mount_quaternion_xyzw": list(self.sensor_mount_quaternion_xyzw),
            "sensor_offset_body_m": list(self.sensor_offset_body_m),
            "fov_interpretation": self.fov_interpretation,
            "horizontal_full_fov_deg": self.horizontal_full_fov_deg,
            "vertical_full_fov_deg": self.vertical_full_fov_deg,
        }


@dataclass(frozen=True)
class ReplayConfig:
    schema_version: int
    replay_config_id: str
    config_version: str
    attitude_mode: str
    attitude_source: str
    idle_attitude_policy: str
    initial_display_policy: str
    earth_model: str
    reference_frame: str
    quaternion_order: str
    rotation_direction: str
    camera_axes: str
    display_sampling_policy: dict[str, Any]
    sensors: tuple[SensorDisplayConfig, ...]
    thruster_effect_mode: str

    @classmethod
    def parse(cls, data: dict[str, Any]) -> "ReplayConfig":
        if not isinstance(data, dict):
            raise ReplayConfigError("ReplayConfig root must be an object")
        _only(data, set(cls.__dataclass_fields__), "ReplayConfig")
        expected = {
            "schema_version": 2, "attitude_mode": "body_pointing_fixed_sensor",
            "idle_attitude_policy": "hold_ecef_v1", "initial_display_policy": "first_task_start_attitude",
            "earth_model": "WGS84_ellipsoid", "reference_frame": "ECEF", "quaternion_order": "xyzw",
            "rotation_direction": "body_to_ecef", "camera_axes": "forward=-Z,right=+X,up=+Y",
        }
        for key, value in expected.items():
            if data.get(key) != value:
                raise ReplayConfigError(f"{key} must be {value!r}")
        if data.get("attitude_source") not in {"orekit_target_pointing", "geometry_pointing_illustration"}:
            raise ReplayConfigError("unsupported attitude_source")
        if data.get("thruster_effect_mode", "disabled") not in {"disabled", "illustration_only"}:
            raise ReplayConfigError("unsupported thruster_effect_mode")
        sampling = data.get("display_sampling_policy")
        if not isinstance(sampling, dict) or sampling.get("preserve_task_and_slew_endpoints") is not True:
            raise ReplayConfigError("display sampling must preserve task and slew endpoints")
        step = sampling.get("attitude_step_s")
        if not isinstance(step, (int, float)) or not math.isfinite(step) or not (0 < step <= 300):
            raise ReplayConfigError("attitude_step_s must be in (0, 300]")
        raw_sensors = data.get("sensors")
        if not isinstance(raw_sensors, list):
            raise ReplayConfigError("sensors must be a list")
        sensors = tuple(SensorDisplayConfig.parse(item) for item in raw_sensors)
        keys = [(sensor.satellite_id, sensor.sensor_id) for sensor in sensors]
        if len(keys) != len(set(keys)):
            raise ReplayConfigError("duplicate (satellite_id, sensor_id) replay sensor")
        values = dict(data)
        values["sensors"] = sensors
        values["thruster_effect_mode"] = data.get("thruster_effect_mode", "disabled")
        return cls(**values)

    @classmethod
    def from_path(cls, path: Path) -> "ReplayConfig":
        return cls.parse(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_bytes(cls, data: bytes) -> "ReplayConfig":
        return cls.parse(json.loads(data))

    def as_dict(self) -> dict[str, Any]:
        result = dict(self.__dict__)
        result["sensors"] = [sensor.as_dict() for sensor in self.sensors]
        return result
