"""Deterministic observation line-of-sight diagnostics for stale scenarios.

The scenario files contain precomputed observation windows.  Older files were
generated before orbit-epoch handling was corrected, so a window is not by
itself proof that the target is above the local horizon at execution time.
This module provides a small, dependency-free Kepler/WGS84 cross-check.  It is
diagnostic only: finite samples are not a continuity certificate and formal
planning/storage remains governed by ``utils.continuous_exposure``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import math
from typing import Mapping, Optional

from utils.time_parsing import parse_orbit_epoch


EARTH_MU_M3_S2 = 3.986004418e14
WGS84_A_M = 6378137.0
WGS84_F = 1.0 / 298.257223563
# Valid generated windows use a non-negative (normally 5 degree) elevation.
# A small negative tolerance prevents an approximate ECI/ECEF transform from
# rejecting a genuine horizon-boundary sample.
OCCLUSION_REJECT_ELEVATION_DEG = -0.05


@dataclass(frozen=True)
class ObservationGeometryResult:
    checked: bool
    feasible: bool
    min_elevation_deg: Optional[float] = None
    reason: str = ""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _julian_date(value: datetime) -> float:
    return value.timestamp() / 86400.0 + 2440587.5


def _gmst_rad(value: datetime) -> float:
    """IAU-compatible low-order GMST, sufficient for a horizon guardrail."""
    jd = _julian_date(value)
    t = (jd - 2451545.0) / 36525.0
    degrees = (
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * t * t
        - t * t * t / 38710000.0
    )
    return math.radians(degrees % 360.0)


def _solve_eccentric_anomaly(mean_anomaly: float, eccentricity: float) -> float:
    estimate = mean_anomaly
    for _ in range(12):
        delta = (estimate - eccentricity * math.sin(estimate) - mean_anomaly) / (
            1.0 - eccentricity * math.cos(estimate)
        )
        estimate -= delta
        if abs(delta) < 1e-13:
            break
    return estimate


def _satellite_ecef(orbit: Mapping[str, object], when: datetime) -> tuple[float, float, float]:
    a = float(orbit["semi_major_axis_km"]) * 1000.0
    e = float(orbit["eccentricity"])
    inc = math.radians(float(orbit["inclination_deg"]))
    argp = math.radians(float(orbit["argument_of_perigee_deg"]))
    raan = math.radians(float(orbit["right_ascension_of_ascending_node_deg"]))
    mean0 = math.radians(float(orbit["mean_anomaly_deg"]))
    epoch = parse_orbit_epoch(orbit["epoch"])
    elapsed = (_utc(when) - epoch).total_seconds()
    mean = (mean0 + math.sqrt(EARTH_MU_M3_S2 / (a ** 3)) * elapsed) % (2.0 * math.pi)
    eccentric = _solve_eccentric_anomaly(mean, e)
    xp = a * (math.cos(eccentric) - e)
    yp = a * math.sqrt(1.0 - e * e) * math.sin(eccentric)

    cos_o, sin_o = math.cos(raan), math.sin(raan)
    cos_w, sin_w = math.cos(argp), math.sin(argp)
    cos_i, sin_i = math.cos(inc), math.sin(inc)
    x_eci = (cos_o * cos_w - sin_o * sin_w * cos_i) * xp + (-cos_o * sin_w - sin_o * cos_w * cos_i) * yp
    y_eci = (sin_o * cos_w + cos_o * sin_w * cos_i) * xp + (-sin_o * sin_w + cos_o * cos_w * cos_i) * yp
    z_eci = sin_w * sin_i * xp + cos_w * sin_i * yp

    theta = _gmst_rad(_utc(when))
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    return (cos_t * x_eci + sin_t * y_eci, -sin_t * x_eci + cos_t * y_eci, z_eci)


def _target_ecef(latitude_deg: float, longitude_deg: float, altitude_m: float) -> tuple[float, float, float]:
    lat, lon = math.radians(latitude_deg), math.radians(longitude_deg)
    e2 = WGS84_F * (2.0 - WGS84_F)
    n = WGS84_A_M / math.sqrt(1.0 - e2 * math.sin(lat) ** 2)
    return (
        (n + altitude_m) * math.cos(lat) * math.cos(lon),
        (n + altitude_m) * math.cos(lat) * math.sin(lon),
        (n * (1.0 - e2) + altitude_m) * math.sin(lat),
    )


def _elevation_deg(satellite: tuple[float, float, float], target: tuple[float, float, float], lat_deg: float, lon_deg: float) -> float:
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    up = (math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat))
    los = tuple(satellite[index] - target[index] for index in range(3))
    norm = math.sqrt(sum(value * value for value in los))
    if norm == 0.0:
        return -90.0
    return math.degrees(math.asin(max(-1.0, min(1.0, sum(los[index] * up[index] for index in range(3)) / norm))))


@lru_cache(maxsize=250_000)
def _sample_elevation(
    orbit_items: tuple[tuple[str, object], ...], latitude_deg: float, longitude_deg: float,
    altitude_km: float, timestamp_us: int,
) -> float:
    orbit = dict(orbit_items)
    when = datetime.fromtimestamp(timestamp_us / 1_000_000.0, tz=timezone.utc)
    target = _target_ecef(latitude_deg, longitude_deg, altitude_km * 1000.0)
    return _elevation_deg(_satellite_ecef(orbit, when), target, latitude_deg, longitude_deg)


def validate_observation_interval(problem, satellite_id: str, task_id: str, start: datetime, end: datetime, *, step_s: float = 1.0) -> ObservationGeometryResult:
    """Check the complete exposure interval, including both exact boundaries.

    Missing geometry remains backward-compatible and is reported as unchecked.
    A caller can distinguish that state for diagnostics without rejecting old
    synthetic/unit-test scenarios that never carried orbital elements.
    """
    satellite = problem.satellites.get(satellite_id)
    task = problem.tasks.get(task_id)
    orbit = getattr(satellite, "orbital_params", None) if satellite else None
    lat = getattr(task, "target_latitude_deg", None) if task else None
    lon = getattr(task, "target_longitude_deg", None) if task else None
    alt = getattr(task, "target_altitude_km", 0.0) if task else 0.0
    required = {
        "semi_major_axis_km", "eccentricity", "inclination_deg",
        "argument_of_perigee_deg", "right_ascension_of_ascending_node_deg",
        "mean_anomaly_deg", "epoch",
    }
    if not isinstance(orbit, Mapping) or not required.issubset(orbit) or lat is None or lon is None:
        return ObservationGeometryResult(False, True, reason="geometry metadata unavailable")
    if end <= start or step_s <= 0:
        return ObservationGeometryResult(True, False, reason="invalid exposure interval")

    orbit_items = tuple(sorted((key, orbit[key]) for key in required))
    current = _utc(start)
    finish = _utc(end)
    elevations: list[float] = []
    while current < finish:
        elevations.append(_sample_elevation(orbit_items, float(lat), float(lon), float(alt or 0.0), round(current.timestamp() * 1_000_000)))
        current = min(finish, current + timedelta(seconds=step_s))
    elevations.append(_sample_elevation(orbit_items, float(lat), float(lon), float(alt or 0.0), round(finish.timestamp() * 1_000_000)))
    minimum = min(elevations)
    if minimum < OCCLUSION_REJECT_ELEVATION_DEG:
        return ObservationGeometryResult(True, False, minimum, "earth occluded during exposure")
    return ObservationGeometryResult(True, True, minimum)
