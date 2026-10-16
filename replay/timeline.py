"""Task phases derived from a committed plan and the current legacy transition model."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from schedulers.transition_utils import C_SMALL, compute_transition_time_agile, delta_g_between


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("replay phase times require an explicit timezone")
    return parsed


def _text(value: datetime) -> str:
    return value.isoformat()


def build_task_phases(
    scenario: dict[str, Any], plan: dict[str, Any], *, agility_profile: str, non_agile_transition_s: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return deterministic SLEWING/OBSERVING intervals without moving observations."""
    satellites = {item["id"]: item for item in scenario["satellites"]}
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {satellite_id: [] for satellite_id in satellites}
    for ordinal, assignment in enumerate(plan["assignments"]):
        grouped[assignment["satellite_id"]].append((ordinal, assignment))

    segments: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for satellite_id, assignments in grouped.items():
        assignments.sort(key=lambda pair: (_time(pair[1]["sat_start_time"]), pair[0]))
        agile = (satellites[satellite_id].get("maneuverability_capability") or {}).get("maneuverability_type") == "agile"
        previous: tuple[int, dict[str, Any]] | None = None
        for ordinal, assignment in assignments:
            start, end = _time(assignment["sat_start_time"]), _time(assignment["sat_end_time"])
            activation = start
            if previous is not None:
                previous_ordinal, previous_assignment = previous
                previous_end = _time(previous_assignment["sat_end_time"])
                delta = delta_g_between(previous_assignment.get("sat_angles"), assignment.get("sat_angles")) if agile else None
                used_fallback = agile and delta is None
                legacy_s = (
                    compute_transition_time_agile(delta, agility_profile)
                    if agile and delta is not None
                    else C_SMALL if agile
                    else float(non_agile_transition_s)
                )
                intended_start = start - timedelta(seconds=legacy_s)
                display_start = max(intended_start, previous_end)
                degraded = intended_start < previous_end
                activation = display_start if display_start < start else start
                diagnostic = {
                    "satellite_id": satellite_id,
                    "previous_assignment_ordinal": previous_ordinal,
                    "assignment_ordinal": ordinal,
                    "legacy_transition_time_s": legacy_s,
                    "transition_source": "schedulers.transition_utils.current_checkout" if agile else "RunConfig.constraints.non_agile_transition_s",
                    "delta_g_deg": delta,
                    "used_fallback": used_fallback,
                    "available_gap_s": (start - previous_end).total_seconds(),
                    "intended_start_time": _text(intended_start),
                    "display_degraded": degraded,
                    "reason_code": "ATTITUDE_PARSE_FALLBACK" if used_fallback else "TRANSITION_GAP_INSUFFICIENT" if degraded else None,
                }
                diagnostics.append(diagnostic)
                if display_start < start:
                    segments.append({
                        "satellite_id": satellite_id, "task_id": assignment["task_id"],
                        "sensor_id": assignment["sensor_id"], "phase": "SLEWING",
                        "start_time": _text(display_start), "end_time": _text(start),
                        "activation_time": _text(display_start), "assignment_ordinal": ordinal,
                        "from_assignment_ordinal": previous_ordinal, "display_degraded": degraded,
                    })
            segments.append({
                "satellite_id": satellite_id, "task_id": assignment["task_id"],
                "sensor_id": assignment["sensor_id"], "phase": "OBSERVING",
                "start_time": _text(start), "end_time": _text(end),
                "activation_time": _text(activation), "assignment_ordinal": ordinal,
                "display_degraded": False,
            })
            previous = ordinal, assignment
    segments.sort(key=lambda item: (item["start_time"], item["satellite_id"], item["phase"]))
    return segments, diagnostics


def phase_at(segments: list[dict[str, Any]], satellite_id: str, when: str) -> dict[str, Any] | None:
    """Evaluate half-open phases from absolute time; call order has no effect."""
    instant = _time(when)
    for segment in segments:
        if segment["satellite_id"] == satellite_id and _time(segment["start_time"]) <= instant < _time(segment["end_time"]):
            return segment
    return None
