"""统一展示状态：只读取正式计划，生成可版本化的 ECEF 姿态样本。

新网页消费这些样本；离线原型保留原有几何求值接口。显示采样与 SLERP
不参与算法可行性，非敏捷星只给对地示意，不能被升级为自由指向卫星。
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

from utils.time_parsing import parse_orbit_epoch
from .contracts import ReplayConfig
from .manifest import canonical_bytes
from .timeline import phase_at

CONFIG_ID = "fixed-payload-illustration-v1"
MAX_SAMPLES = 200_000
WGS84_A = 6378137.0
WGS84_E2 = 6.69437999014e-3

def _time(value):
    return parse_orbit_epoch(value)

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




def source_bundle_sha(project: Path) -> str:
    """按真实源码字节计算身份，未提交修改也会改变缓存键，不能用 HEAD 冒充。"""
    files = list((project / "replay").glob("*.py"))
    files += list((project / "draw").glob("fixed-payload-*.js"))
    files += [project / name for name in (
        "eos_system/replay_builder.py", "eos_system/replay_legacy.py", "eos_system/replay_service.py",
        "eos_system/visualization.py", "eos_system/orbit_generate.py",
        "draw/orekit_to_czml.py", "utils/time_parsing.py")]
    files += list((project / "replay_configs").glob("*.json"))
    files += list((project / "assets/satellites").glob("*"))
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(project).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def display_config(scene: dict, project: Path) -> dict:
    """版本化模板只提供展示规则；载荷 ID/FOV 由本场景逐星展开，不写回场景。"""
    config = json.loads((project / "replay_configs/fixed-payload-illustration-v1.json").read_text(encoding="utf-8"))
    sensors = []
    for satellite in scene.get("satellites", []):
        for sensor in satellite.get("observation_capability", {}).get("sensors", []):
            sensors.append({
                "satellite_id": satellite["id"], "sensor_id": sensor["sensor_id"],
                "sensor_mount_quaternion_xyzw": [0.0, 0.0, 0.0, 1.0],
                "sensor_offset_body_m": [0.0, 0.0, 0.0],
                "fov_interpretation": "square_full_angle_display_assumption",
                "horizontal_full_fov_deg": float(sensor["field_of_view_deg"]),
                "vertical_full_fov_deg": float(sensor["field_of_view_deg"]),
            })
    for model in config["models"]:
        path = project / "assets/satellites/landsat8.glb"
        model["uri"] += "?sha=" + hashlib.sha256(path.read_bytes()).hexdigest()
    config["sensors"] = sorted(sensors, key=lambda s: (s["satellite_id"], s["sensor_id"]))
    return ReplayConfig.parse(config).as_dict()


def _multiply(a, b):
    x,y,z,w = a
    p,q,r,s = b
    return list(_unit((w*p+x*s+y*r-z*q, w*q-x*r+y*s+z*p,
                       w*r+x*q-y*p+z*s, w*s-x*p-y*q-z*r)))


def _slerp(a, b, t):
    cosine = sum(x*y for x,y in zip(a,b))
    if cosine < 0:
        b = [-x for x in b]
        cosine = -cosine
    if cosine > 0.9995:
        return list(_unit(tuple(x*(1-t)+y*t for x,y in zip(a,b))))
    angle = math.acos(max(-1.0, min(1.0, cosine)))
    return [((math.sin((1-t)*angle)*x+math.sin(t*angle)*y)/math.sin(angle))
            for x,y in zip(a,b)]


def attitude_samples(document: dict, packets: list[dict]) -> tuple[list[dict], list[dict]]:
    """采样保留每个任务/转向端点；任务身份由半开阶段决定，而非采样点数量。"""
    start = _time(document["manifest"]["start_time"])
    end = _time(document["manifest"]["end_time"])
    step = float(document["replay_config"]["display_sampling_policy"]["attitude_step_s"])
    count = int(math.ceil((end-start).total_seconds()/step)) + 1
    if count * len(document["satellites"]) + 2*len(document["segments"]) > MAX_SAMPLES:
        raise ValueError("REPLAY_SAMPLE_LIMIT: 展示样本超过 200000；请使用更小场景或登记较疏采样配置")
    orbits = {item["id"]: _orbit_samples(item) for item in packets
              if "epoch" in item.get("position", {})}
    targets = {m["id"]: _ecef(float(m["target_location"]["longitude"]),
                              float(m["target_location"]["latitude"]),
                              float(m["target_location"].get("altitude_km", 0))*1000)
               for m in document["missions"]}
    samples, warnings = [], []
    for satellite in document["satellites"]:
        sid = satellite["id"]
        orbit = orbits.get(sid)
        if not orbit or orbit[0][0] > start or orbit[-1][0] < end:
            raise ValueError("ORBIT_DATA_MISSING: 轨道采样必须覆盖正式计划的整个时间范围："+sid)
        segments = sorted((s for s in document["segments"] if s["satellite_id"] == sid),
                          key=lambda s: _time(s["start_time"]))
        observations = [s for s in segments if s["phase"] == "OBSERVING"]
        by_ordinal = {s["assignment_ordinal"]: s for s in observations}
        sensors = {s["sensor_id"]: s for s in satellite["sensors"]}
        agile = satellite["maneuverability_type"] == "agile"
        if not agile:
            warnings.append({"code":"NON_AGILE_NADIR_ILLUSTRATION", "satellite_id":sid})
        moments = {min(start+timedelta(seconds=i*step), end) for i in range(count)}
        moments.add(end)
        for segment in segments:
            moments.update((_time(segment["start_time"]), _time(segment["end_time"])))
        for moment in sorted(moments):
            if moment < start or moment > end:
                raise ValueError("回放阶段超出正式计划时域")
            position = _position_at(orbit, moment)
            active = phase_at(segments, sid, moment.isoformat())
            sensor_id = active["sensor_id"] if active else None
            sensor = sensors.get(sensor_id) or next(iter(sensors.values()), None)
            mount = sensor["sensor_mount_quaternion_xyzw"] if sensor else [0,0,0,1]
            def pointing(when, task):
                return _look_quaternion(_position_at(orbit, when), targets[task])
            if not agile:
                body = _look_quaternion(position, (0,0,0))
            else:
                if active and active["phase"] == "OBSERVING":
                    camera = pointing(moment, active["task_id"])
                elif active and active["phase"] == "SLEWING":
                    previous = by_ordinal[active["from_assignment_ordinal"]]
                    following = by_ordinal[active["assignment_ordinal"]]
                    a,b = _time(active["start_time"]), _time(active["end_time"])
                    camera = _slerp(pointing(_time(previous["end_time"]), previous["task_id"]),
                                    pointing(_time(following["start_time"]), following["task_id"]),
                                    (moment-a).total_seconds()/(b-a).total_seconds())
                else:
                    previous = [s for s in observations if _time(s["end_time"]) <= moment]
                    anchor = previous[-1] if previous else observations[0] if observations else None
                    camera = (pointing(_time(anchor["end_time"] if previous else anchor["start_time"]), anchor["task_id"])
                              if anchor else _look_quaternion(position, (0,0,0)))
                    # hold_ecef 固定的是本体姿态，沿用上次观测的固定安装方向。
                    sensor = sensors.get(anchor["sensor_id"]) if anchor else sensor
                    mount = sensor["sensor_mount_quaternion_xyzw"] if sensor else [0,0,0,1]
                body = _multiply(camera, [-mount[0],-mount[1],-mount[2],mount[3]])
            samples.append({
                "satellite_id":sid, "time":moment.isoformat(),
                "position_ecef_m":list(position),
                "body_to_ecef_quaternion_xyzw":body,
                "source":"geometry_pointing_illustration",
                "quality":"illustration_only" if agile else "non_agile_nadir_illustration",
            })
    return samples, warnings


def validate_document(document: dict, expected: dict) -> None:
    """发布方独立检查时间、有限单位四元数与覆盖，不只相信文件哈希正确。"""
    manifest = document["manifest"]
    for key in ("replay_id","run_id","cache_key","plan_sha256","scenario_sha256",
                "builder_code_sha","builder_version","propagation_version"):
        if manifest.get(key) != expected[key]:
            raise ValueError("姿态资源身份不匹配："+key)
    start,end = _time(manifest["start_time"]),_time(manifest["end_time"])
    if start >= end:
        raise ValueError("姿态资源时域无效")
    known = {sat["id"] for sat in document["satellites"]}
    if len(known) != len(document["satellites"]):
        raise ValueError("回放卫星 ID 重复")
    samples = document["samples"]
    if len(samples) > MAX_SAMPLES:
        raise ValueError("姿态资源样本数超限")
    coverage = {}
    for sample in samples:
        sid = sample["satellite_id"]
        instant = _time(sample["time"])
        position,q = sample["position_ecef_m"],sample["body_to_ecef_quaternion_xyzw"]
        if sid not in known or not start <= instant <= end:
            raise ValueError("姿态样本的卫星或时间无效")
        if len(position)!=3 or len(q)!=4 or not all(
                isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in position+q):
            raise ValueError("姿态样本必须包含有限位置与 xyzw 四元数")
        if abs(sum(x*x for x in q)-1)>1e-6:
            raise ValueError("姿态四元数未归一化")
        if sid in coverage and instant<=coverage[sid][1]:
            raise ValueError("姿态样本时间没有严格递增")
        coverage[sid]=(coverage.get(sid,(instant,instant))[0],instant)
    if any(coverage.get(sid)!=(start,end) for sid in known):
        raise ValueError("姿态样本没有覆盖全部卫星与正式时间端点")
    for segment in document["segments"]:
        if (segment["satellite_id"] not in known or segment["phase"] not in {"SLEWING","OBSERVING"}
                or not start<=_time(segment["start_time"])<_time(segment["end_time"])<=end):
            raise ValueError("回放阶段的时间或归属无效")
