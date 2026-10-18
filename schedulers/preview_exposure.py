"""Explicit planning-preview window policy; never a continuous certificate."""
from datetime import timedelta
from utils.continuous_exposure import (planning_exposure, exposure_times, ExposureDecision,
                                       ExposureStatus)
from utils.time_parsing import parse_orbit_epoch


def candidate_exposure(problem, window, start, end, duration):
    if getattr(problem, 'execution_mode', 'formal') not in ('planning_preview', 'physical_validation'):
        return planning_exposure(window, start, end, duration)
    try:
        first, last = exposure_times(start, end, duration)
        ws, we = parse_orbit_epoch(window.start_time), parse_orbit_epoch(window.end_time)
        # Legacy exports store the first invisible point; reserve one actual step.
        evidence = getattr(window, 'planning_evidence', None) or {}
        if evidence.get('version') != 'visibility_exit_refined_v3':
            we -= timedelta(seconds=float(window.time_step))
        if not ws <= first < last <= we:
            return ExposureDecision(ExposureStatus.REJECTED, 'OUTSIDE_PREVIEW_WINDOW')
        return ExposureDecision(ExposureStatus.PLANNING_FEASIBLE,
                                'PREVIEW_WINDOW_ONLY_NOT_CONTINUOUSLY_CERTIFIED', ws, we)
    except (ValueError, TypeError, OverflowError):
        return ExposureDecision(ExposureStatus.ERROR, 'INVALID_PREVIEW_EXPOSURE')
