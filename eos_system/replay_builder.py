"""独立回放构建进程：只读正式输入，只向指定临时目录写可再生产物。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from schedulers.transition_utils import compute_transition_time_agile, delta_g_between

from .config import Settings
from .visualization import orbit_cache_path

WGS84_A = 6378137.0
WGS84_E2 = 6.69437999014e-3


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # 第一阶段场景存在无时区时间；按原项目的 UTC 解释并在 manifest 披露。
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8")


def _ecef(lon: float, lat: float, alt_m: float) -> tuple[float, float, float]:
    longitude, latitude = math.radians(lon), math.radians(lat)
    sin_lat, cos_lat = math.sin(latitude), math.cos(latitude)
    n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    return ((n + alt_m) * cos_lat * math.cos(longitude),
            (n + alt_m) * cos_lat * math.sin(longitude),
            (n * (1.0 - WGS84_E2) + alt_m) * sin_lat)


def _unit(vector: tuple[float, ...]) -> tuple[float, ...]:
    length = math.sqrt(sum(item * item for item in vector))
    if length < 1e-9:
        raise ValueError("无法从重合位置计算相机方向")
    return tuple(item / length for item in vector)


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _look_quaternion(position: tuple[float, float, float],
                     target: tuple[float, float, float]) -> list[float]:
    """C 的 -Z 指向目标、+Y 尽量朝 ECEF 北；结果是 camera_to_ecef 的 xyzw。"""
    forward = _unit(tuple(target[i] - position[i] for i in range(3)))
    north = (0.0, 0.0, 1.0)
    right_raw = _cross(forward, north)
    if sum(value * value for value in right_raw) < 1e-8:
        right_raw = _cross(forward, (0.0, 1.0, 0.0))
    right = _unit(right_raw)
    up = _unit(_cross(right, forward))
    back = tuple(-value for value in forward)
    m00, m10, m20 = right
    m01, m11, m21 = up
    m02, m12, m22 = back
    trace = m00 + m11 + m22
    if trace > 0:
        scale = math.sqrt(trace + 1.0) * 2.0
        q = [(m21 - m12) / scale, (m02 - m20) / scale,
             (m10 - m01) / scale, scale / 4.0]
    elif m00 > m11 and m00 > m22:
        scale = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        q = [scale / 4.0, (m01 + m10) / scale,
             (m02 + m20) / scale, (m21 - m12) / scale]
    elif m11 > m22:
        scale = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        q = [(m01 + m10) / scale, scale / 4.0,
             (m12 + m21) / scale, (m02 - m20) / scale]
    else:
        scale = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        q = [(m02 + m20) / scale, (m12 + m21) / scale,
             scale / 4.0, (m10 - m01) / scale]
    normalized = _unit(tuple(q))
    return list(normalized)


def _orbit_samples(packet: dict) -> list[tuple[datetime, tuple[float, float, float]]]:
    epoch = _time(packet["position"]["epoch"])
    values = packet["position"]["cartographicDegrees"]
    if not values or len(values) % 4:
        raise ValueError("轨道 CZML 位置样本格式无效")
    return [(epoch + timedelta(seconds=float(values[i])),
             _ecef(float(values[i + 1]), float(values[i + 2]), float(values[i + 3])))
            for i in range(0, len(values), 4)]


def _position_at(samples: list[tuple[datetime, tuple[float, float, float]]],
                 when: datetime) -> tuple[float, float, float]:
    if when <= samples[0][0]:
        return samples[0][1]
    if when >= samples[-1][0]:
        return samples[-1][1]
    lo, hi = 0, len(samples) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if samples[mid][0] <= when:
            lo = mid
        else:
            hi = mid
    fraction = (when - samples[lo][0]).total_seconds() / (
        samples[hi][0] - samples[lo][0]).total_seconds()
    return tuple(samples[lo][1][i] * (1 - fraction) + samples[hi][1][i] * fraction
                 for i in range(3))


def _segments(sat_id: str, assignments: list[tuple[int, dict]], agile: bool,
              constraints: dict, start: datetime, end: datetime) -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    warnings: list[dict] = []
    cursor = start
    previous: dict | None = None
    for ordinal, item in assignments:
        obs_start, obs_end = _time(item["sat_start_time"]), _time(item["sat_end_time"])
        if obs_end <= obs_start or obs_start < start or obs_end > end:
            raise ValueError("正式 assignment 超出场景时间范围")
        slew_start = obs_start
        if previous is not None:
            if agile:
                delta = delta_g_between(previous.get("sat_angles"), item.get("sat_angles"))
                if delta is None:
                    duration = 11.66
                    warnings.append({"code": "ATTITUDE_PARSE_FALLBACK", "satellite_id": sat_id,
                                     "assignment_ordinal": ordinal})
                else:
                    duration = compute_transition_time_agile(
                        delta, constraints.get("agility_profile", "Standard-Agility"))
            else:
                duration = float(constraints.get("non_agile_transition_s", 10.0))
            proposed = obs_start - timedelta(seconds=duration)
            if proposed < cursor:
                warnings.append({"code": "TRANSITION_GAP_INSUFFICIENT", "satellite_id": sat_id,
                                 "assignment_ordinal": ordinal, "legacy_transition_time_s": duration})
            slew_start = max(cursor, proposed)
        if cursor < slew_start:
            rows.append({"satellite_id": sat_id, "phase": "IDLE", "task_id": None,
                         "sensor_id": None, "assignment_ordinal": None,
                         "start_time": _iso(cursor), "end_time": _iso(slew_start),
                         "activation_time": None})
        if previous is not None and slew_start < obs_start:
            rows.append({"satellite_id": sat_id, "phase": "SLEWING",
                         "task_id": item["task_id"], "sensor_id": item["sensor_id"],
                         "assignment_ordinal": ordinal, "start_time": _iso(slew_start),
                         "end_time": _iso(obs_start), "activation_time": _iso(slew_start)})
        rows.append({"satellite_id": sat_id, "phase": "OBSERVING",
                     "task_id": item["task_id"], "sensor_id": item["sensor_id"],
                     "assignment_ordinal": ordinal, "start_time": _iso(obs_start),
                     "end_time": _iso(obs_end), "activation_time": _iso(slew_start)})
        cursor, previous = obs_end, item
    if cursor < end:
        rows.append({"satellite_id": sat_id, "phase": "IDLE", "task_id": None,
                     "sensor_id": None, "assignment_ordinal": None,
                     "start_time": _iso(cursor), "end_time": _iso(end),
                     "activation_time": None})
    return rows, warnings


def _target_for(when: datetime, segments: list[dict],
                assignments: list[tuple[int, dict]], targets: dict[str, tuple[float, float, float]],
                position: tuple[float, float, float]) -> tuple[float, float, float]:
    if not assignments:
        return tuple(-value for value in position)
    selected = assignments[0][1]["task_id"]
    for segment in segments:
        if _time(segment["start_time"]) <= when < _time(segment["end_time"]):
            if segment["task_id"] is not None:
                selected = segment["task_id"]
            break
        if segment["task_id"] is not None:
            selected = segment["task_id"]
    if selected not in targets:
        raise ValueError("正式计划引用了场景中不存在的任务")
    return targets[selected]


def build(job_path: Path) -> None:
    job = json.loads(job_path.read_text(encoding="utf-8"))
    directory = job_path.parent
    scene_path = Path(job["scenario_path"])
    if _sha(scene_path) != job["scenario_sha256"]:
        raise ValueError("场景 SHA-256 与正式运行记录不一致")
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    plan = job["plan"]
    config = job["replay_config"]
    start, end = _time(plan["start_time"]), _time(plan["end_time"])
    if not start < end:
        raise ValueError("正式计划时间范围无效")
    orbit_path = directory / "orbit_display.czml"
    orekit_data = Path(job["orekit_data"])
    if not orekit_data.is_file():
        raise FileNotFoundError("缺少 Orekit 数据文件")
    # 复用旧页面按场景哈希锁定的轨道缓存；未命中时它在本进程组中调用 Orekit。
    # 每次回放复制一份不可变资源，单次实验删除不清理其他实验共用的轨道缓存。
    cached = orbit_cache_path(
        Settings(runtime_dir=Path(job["runtime_dir"]), scenario_dir=scene_path.parent),
        scene_path, job["scenario_sha256"])
    shutil.copyfile(cached, orbit_path)
    packets = json.loads(orbit_path.read_text(encoding="utf-8"))
    orbit_by_sat = {item["id"]: _orbit_samples(item) for item in packets
                    if "position" in item and "epoch" in item["position"]}
    targets = {item["id"]: _ecef(float(item["target_location"]["longitude"]),
                                float(item["target_location"]["latitude"]),
                                float(item["target_location"].get("altitude_km", 0)) * 1000.0)
               for item in scene.get("missions", [])}
    satellites = {item["id"]: item for item in scene.get("satellites", [])}
    grouped: dict[str, list[tuple[int, dict]]] = {sat_id: [] for sat_id in satellites}
    for ordinal, item in enumerate(plan.get("assignments", [])):
        if item["satellite_id"] not in grouped:
            raise ValueError("正式计划引用了场景中不存在的卫星")
        grouped[item["satellite_id"]].append((ordinal, item))
    for rows in grouped.values():
        rows.sort(key=lambda pair: _time(pair[1]["sat_start_time"]))
    all_segments: list[dict] = []
    all_samples: list[dict] = []
    warnings: list[dict] = [{"code": "GEOMETRY_POINTING_ILLUSTRATION",
                             "message": "固定镜头姿态为目标指向示意，不是 Orekit 权威姿态"}]
    for sat_id, satellite in satellites.items():
        orbit = orbit_by_sat.get(sat_id)
        if not orbit:
            raise ValueError("ORBIT_DATA_MISSING: " + sat_id)
        agile = satellite.get("maneuverability_capability", {}).get(
            "maneuverability_type") == "agile"
        segments, diagnostics = _segments(
            sat_id, grouped[sat_id], agile, job["run_config"].get("constraints", {}), start, end)
        all_segments.extend(segments)
        warnings.extend(diagnostics)
        if not agile:
            warnings.append({"code": "NON_AGILE_ILLUSTRATION", "satellite_id": sat_id})
        moments = {time for time, _ in orbit if start <= time <= end}
        moments.update((_time(segment["start_time"]) for segment in segments))
        moments.update((_time(segment["end_time"]) for segment in segments))
        for moment in sorted(moments):
            position = _position_at(orbit, moment)
            target = (tuple(-value for value in position) if not agile else
                      _target_for(moment, segments, grouped[sat_id], targets, position))
            all_samples.append({
                "satellite_id": sat_id, "time": _iso(moment),
                "position_ecef_m": list(position),
                "body_to_ecef_quaternion_xyzw": _look_quaternion(position, target),
                "source": "geometry_pointing_illustration",
                "quality": "illustration_only" if agile else "non_agile_nadir_illustration",
            })
    _write_json(directory / "attitude_samples.json",
                {"schema_version": 2, "samples": all_samples})
    _write_json(directory / "segments.json", {"schema_version": 2, "segments": all_segments})
    _write_json(directory / "diagnostics.json", {"schema_version": 2, "warnings": warnings})
    _write_json(directory / "replay_config.json", config)
    keys = {"orbit_display": ("orbit_display.czml", "application/json"),
            "attitude_samples": ("attitude_samples.json", "application/json"),
            "segments": ("segments.json", "application/json"),
            "diagnostics": ("diagnostics.json", "application/json"),
            "replay_config": ("replay_config.json", "application/json")}
    resources = {key: {"filename": filename, "mime": mime,
                       "size_bytes": (directory / filename).stat().st_size,
                       "sha256": _sha(directory / filename)}
                 for key, (filename, mime) in keys.items()}
    manifest = {
        "schema_version": 2, "replay_id": job["replay_id"], "run_id": job["run_id"],
        "build_attempt": job["build_attempt"], "scenario_id": job["scenario_id"],
        "replay_config_id": config["replay_config_id"],
        "scenario_sha256": job["scenario_sha256"], "plan_sha256": job["plan_sha256"],
        "replay_config_sha256": job["replay_config_sha256"], "cache_key": job["cache_key"],
        "algorithm_code_sha": job["algorithm_code_sha"],
        "provenance_warning": job["provenance_warning"],
        "builder_code_sha": job["builder_code_sha"],
        "builder_version": job["builder_version"],
        "propagation_version": job["propagation_version"],
        "attitude_version": job["attitude_version"],
        "geometry_version": job["geometry_version"],
        "start_time": _iso(start), "end_time": _iso(end),
        "time_semantics": "naive_utc_assumption_when_timezone_missing",
        "reference_frame": "ECEF", "position_unit": "m",
        "quaternion_order": "xyzw", "rotation_direction": "body_to_ecef",
        "camera_axes": {"forward": "-Z", "right": "+X", "up": "+Y"},
        "mount_rotation_direction": "camera_to_body",
        "attitude_source": "geometry_pointing_illustration",
        "sensors": config["sensors"], "resources": resources,
        "diagnostics_summary": {"warning_count": len(warnings),
                                "sample_count": len(all_samples),
                                "segment_count": len(all_segments)},
        "warnings": warnings[:100],
    }
    _write_json(directory / "manifest.json", manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    args = parser.parse_args()
    build(args.job)


if __name__ == "__main__":
    main()
