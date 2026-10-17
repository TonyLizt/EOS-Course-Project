"""Reconstruct source identity from a trusted, unchanged Scenario snapshot.

IDs are Loader ordinals, scoped to that snapshot and to observation/communication
namespaces. A match is structural evidence, never a continuous exposure proof.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
import math

from utils.time_parsing import parse_orbit_epoch


def _time(value):
    return parse_orbit_epoch(value).replace(tzinfo=None) if value is not None else None


def _integer(value):
    return type(value) is int


def _slice_angles(payload, offset, count):
    if isinstance(payload, list):
        return payload[offset:offset + count]
    if isinstance(payload, dict):
        return {key: _slice_angles(value, offset, count) for key, value in payload.items()}
    return payload


def observation_source_matches(problem, task, window, item, start, end, *, check_angles=True):
    """Full observable source semantics; deliberately independent of planning trust."""
    if (window.mission_id != task.id or window.satellite_id != item['satellite_id']
            or window.sensor_id != item['sensor_id'] or window.orbit_number != item['orbit_number']
            or not window.start_time <= start < end <= window.end_time):
        return False
    # Loader has already resolved missing configuration. Never turn an explicit
    # zero (or an unresolved None) into a one-second source grid. Match the
    # existing planning contract's positive, integer-microsecond resolution.
    try:
        step = float(window.time_step)
        step_us = Decimal(str(window.time_step)) * 1000000
    except (TypeError, ValueError, OverflowError, InvalidOperation):
        return False
    if not math.isfinite(step) or step <= 0 or step_us != step_us.to_integral_value():
        return False
    offset = (start - window.start_time).total_seconds() / step
    k = round(offset)
    if abs(offset - k) > 1e-6:
        return False
    satellite = problem.satellites[item['satellite_id']]
    if satellite.maneuverability_type == 'non_agile':
        slack = (window.end_time - window.start_time).total_seconds() - task.required_duration
        max_k = math.floor((slack + 1e-9) / step)
        center_k = max(0, min(max_k, round(slack / (2 * step))))
        if k != center_k:
            return False
        expected = window.non_agile_data
    else:
        if not check_angles:
            return True
        count = max(1, math.ceil(task.required_duration / step - 1e-9))
        expected = _slice_angles(window.agile_data, k, count)
    return not check_angles or item['sat_angles'] == expected


def communication_source_matches(window, satellite_id, ground_station_id, start, end):
    return (window.satellite_id == satellite_id and window.ground_station_id == ground_station_id
            and window.start_time <= start < end <= window.end_time)


def validate_plan_source(plan, problem, scenario_sha):
    """A plan is interpreted only against the supplied, hash-checked snapshot."""
    if (plan.get('scenario_id') != problem.scenario_id
            or _time(plan.get('start_time')) != problem.start_time
            or _time(plan.get('end_time')) != problem.end_time):
        raise ValueError('PLAN_SCENARIO_MISMATCH')
    provenance = plan.get('provenance', {})
    if not isinstance(provenance, dict):
        raise ValueError('INVALID_PLAN_PROVENANCE')
    for declared in (plan.get('scenario_sha256'), provenance.get('scenario_sha256')):
        if declared is not None and declared != scenario_sha:
            raise ValueError('PLAN_SCENARIO_SHA_MISMATCH')


class SourceWindowIndex:
    """One immutable-input verification invocation; no process-global lookup cache."""

    def __init__(self, problem):
        self.problem = problem
        self.observations = defaultdict(list)
        self.communications = defaultdict(list)
        for task in problem.tasks.values():
            for window in task.windows:
                self._add(self.observations, window, (task.id, window))
        for window in problem.comm_windows:
            self._add(self.communications, window, window)

    @staticmethod
    def _add(index, window, value):
        if not _integer(window.window_id) or window.window_id <= 0:
            raise ValueError('INVALID_SCENARIO_WINDOW_ID')
        index[window.window_id].append(value)
        if len(index[window.window_id]) != 1:
            raise ValueError('DUPLICATE_SCENARIO_WINDOW_ID')

    @staticmethod
    def _explicit(index, item, key):
        value = item[key]
        if not _integer(value) or value <= 0:
            raise ValueError('INVALID_' + key.upper())
        if value not in index:
            raise ValueError('UNKNOWN_' + key.upper())
        return index[value][0]

    def observation(self, item, start, end):
        problem = self.problem
        task = problem.tasks.get(item['task_id'])
        satellite = problem.satellites.get(item['satellite_id'])
        if task is None or satellite is None or item['sensor_id'] not in satellite.sensors:
            raise ValueError('UNKNOWN_SOURCE_OWNER')
        if not _integer(item['orbit_number']):
            raise ValueError('INVALID_ORBIT_NUMBER')
        if not problem.start_time <= start < end <= problem.end_time:
            raise ValueError('EXPOSURE_OUTSIDE_SCENARIO')
        from utils.continuous_exposure import exposure_times
        exposure_times(start, end, task.required_duration)
        if 'sat_window_id' in item:
            owner, window = self._explicit(self.observations, item, 'sat_window_id')
            if owner != task.id or not observation_source_matches(problem, task, window, item, start, end):
                raise ValueError('SAT_WINDOW_SOURCE_MISMATCH')
            return window
        matches = [window for window in task.windows
                   if observation_source_matches(problem, task, window, item, start, end)]
        if len(matches) != 1:
            raise ValueError('AMBIGUOUS_LEGACY_SAT_SOURCE' if matches else 'NO_LEGACY_SAT_SOURCE')
        return matches[0]

    def communication(self, item, sat_end, ratio):
        problem = self.problem
        gs_fields = ('ground_station_id', 'gs_start_time', 'gs_end_time', 'gs_window_id')
        if not problem.ground_stations:
            if any(item.get(key) is not None for key in gs_fields):
                raise ValueError('UNEXPECTED_DOWNLINK_SOURCE')
            return None, None, None
        station = item.get('ground_station_id')
        start, end = _time(item.get('gs_start_time')), _time(item.get('gs_end_time'))
        if (station not in problem.ground_stations or start is None or end is None
                or not problem.start_time <= start < end <= problem.end_time
                or start <= sat_end):
            raise ValueError('INVALID_DOWNLINK_INTERVAL_OR_OWNER')
        required = problem.tasks[item['task_id']].required_duration * ratio
        if (end - start).total_seconds() + 1e-6 < required:
            raise ValueError('DOWNLINK_TOO_SHORT')
        if 'gs_window_id' in item:
            window = self._explicit(self.communications, item, 'gs_window_id')
            if not communication_source_matches(window, item['satellite_id'], station, start, end):
                raise ValueError('GS_WINDOW_SOURCE_MISMATCH')
        else:
            matches = [window for window in problem.comm_windows
                       if communication_source_matches(window, item['satellite_id'], station, start, end)]
            if len(matches) != 1:
                raise ValueError('AMBIGUOUS_LEGACY_GS_SOURCE' if matches else 'NO_LEGACY_GS_SOURCE')
            window = matches[0]
        return window, start, end

    def restore(self, item, constraint_model):
        """Import JSON assignment using source data, without trusting reported IDs alone."""
        from .constraint_model import Assignment
        if not isinstance(item, dict):
            raise ValueError('INVALID_ASSIGNMENT_OBJECT')
        start, end = _time(item['sat_start_time']), _time(item['sat_end_time'])
        if start is None or end is None:
            raise ValueError('MISSING_EXPOSURE_TIME')
        window = self.observation(item, start, end)
        cw, gs_start, gs_end = self.communication(item, end, constraint_model.downlink_duration_ratio)
        expected_data = constraint_model._estimate_data_volume_GB(item['satellite_id'], item['sensor_id'], start, end)
        expected_power = constraint_model._estimate_power_cost_W(item['satellite_id'], item['sensor_id'])
        data, power = float(item['data_volume_GB']), float(item['power_cost_W'])
        if (not math.isfinite(data) or not math.isfinite(power)
                or abs(data - expected_data) > 1e-7 or abs(power - expected_power) > 1e-7):
            raise ValueError('SOURCE_RESOURCE_MISMATCH')
        return Assignment(task_id=item['task_id'], satellite_id=item['satellite_id'],
            sat_start_time=start, sat_end_time=end, sat_window_id=window.window_id,
            sensor_id=item['sensor_id'], orbit_number=window.orbit_number,
            data_volume_GB=data, power_cost_W=power, sat_angles=item['sat_angles'],
            ground_station_id=item.get('ground_station_id'), gs_start_time=gs_start,
            gs_end_time=gs_end, gs_window_id=cw.window_id if cw else None)
