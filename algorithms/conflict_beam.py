"""CAABS v0.1 foundations; planning feasibility is not certification.

Candidate construction delegates all physical rules to ConstraintModel. Nothing
in this module registers an algorithm or writes system lifecycle state.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, fields, replace
from datetime import datetime, timezone
import math
from typing import Callable

from pydantic import ConfigDict, Field

from eos_system.algorithm_registry import AlgorithmParams
from schedulers.constraint_model import Assignment, ConstraintModel, Schedule
from schedulers.scenario_loader import SchedulingProblem, SchedulingTask, TaskWindow
from utils.continuous_exposure import ExposureStatus, planning_window

VERSION = "0.1.0"
Checkpoint = Callable[[], None]


def _noop() -> None:
    pass


class CAABSParams(AlgorithmParams):
    """Experimental defaults, independent of the system registry."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    beam_width: int = Field(default=8, ge=1, le=256, strict=True)
    branch_limit: int = Field(default=8, ge=1, le=64, strict=True)
    max_candidates_per_task: int = Field(default=16, ge=1, le=128, strict=True)
    max_windows_per_task: int = Field(default=32, ge=1, le=256, strict=True)
    conflict_prefilter: bool = Field(default=True, strict=True)


def _freeze(value, checkpoint: Checkpoint) -> tuple:
    checkpoint()
    if value is None:
        return ("none",)
    if isinstance(value, datetime):
        # Loader-naive datetimes mean UTC, never the host's local timezone.
        moment = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return ("datetime", moment.isoformat(timespec="microseconds"))
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int):
        return ("int", value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite assignment value")
        return ("float", value.hex())
    if isinstance(value, str):
        return ("str", value)
    if isinstance(value, dict):
        pairs = [(_freeze(k, checkpoint), _freeze(v, checkpoint)) for k, v in value.items()]
        return ("dict", tuple(sorted(pairs)))
    if isinstance(value, (list, tuple)):
        return ("sequence", tuple(_freeze(item, checkpoint) for item in value))
    raise TypeError(f"unsupported assignment payload: {type(value).__name__}")


def canonical_assignment_key(assignment: Assignment, checkpoint: Checkpoint = _noop) -> tuple:
    """All actual Assignment fields, including downlink, attitude and resources."""
    return tuple((f.name, _freeze(getattr(assignment, f.name), checkpoint)) for f in fields(Assignment))


def canonical_state_key(schedule: Schedule, checkpoint: Checkpoint = _noop) -> tuple:
    """Order-independent schedule semantics; metadata has no scheduling meaning."""
    keys = [canonical_assignment_key(a, checkpoint) for a in schedule.assignments]
    checkpoint()
    result = tuple(sorted(keys))
    checkpoint()
    return result


def clone_schedule(schedule: Schedule, checkpoint: Checkpoint = _noop) -> Schedule:
    """Own every mutable assignment, attitude payload and metadata dictionary."""
    assignments = []
    for assignment in schedule.assignments:
        checkpoint()
        assignments.append(deepcopy(assignment))
    checkpoint()
    result = Schedule(assignments=assignments, metadata=deepcopy(schedule.metadata))
    checkpoint()
    return result


def branch_schedule(parent: Schedule, candidate: Assignment, checkpoint: Checkpoint = _noop) -> Schedule:
    """Copy only; caller MUST check candidate against parent before calling."""
    result = clone_schedule(parent, checkpoint)
    result.assignments.append(deepcopy(candidate))
    checkpoint()
    return result


@dataclass(frozen=True)
class BeamState:
    schedule: Schedule
    task_index: int
    completed: int
    objective_score: float
    canonical_key: tuple

    @property
    def search_key(self) -> tuple:
        # Skipped tasks are represented by the fixed-order cursor.
        return self.task_index, self.canonical_key

    @property
    def rank_key(self) -> tuple:
        return -self.completed, -self.objective_score, self.canonical_key


def _spread(items: list, limit: int) -> list:
    if len(items) <= limit:
        return items
    if limit == 1:
        return items[:1]
    return [items[round(i * (len(items) - 1) / (limit - 1))] for i in range(limit)]


class _CandidateConstructor(ConstraintModel):
    """Count delegated checks without reproducing any shared feasibility rule."""

    def __init__(self, original: ConstraintModel, mode: str, checkpoint: Checkpoint, stats: dict):
        super().__init__(
            original.problem, placement_mode=mode,
            unassigned_penalty=original.unassigned_penalty,
            downlink_duration_ratio=original.downlink_duration_ratio,
            agility_profile=original.agility_profile,
            non_agile_transition_s=original.non_agile_transition_s,
        )
        self.checkpoint = checkpoint
        self.stats = stats

    def is_feasible_assignment(self, assignment: Assignment, schedule: Schedule) -> bool:
        self.checkpoint()
        self.stats["candidate_constraint_calls"] = self.stats.get("candidate_constraint_calls", 0) + 1
        result = super().is_feasible_assignment(assignment, schedule)
        self.checkpoint()
        return result


class BoundedCandidateAdapter:
    """At most two public constructor calls per selected observation window.

    Selection balances satellites, then spreads each satellite's window quota
    over the horizon. One placement per selected window precedes extra centers.
    Public constructors choose only their first feasible downlink combination.
    """

    def __init__(self, constraints: ConstraintModel, params: CAABSParams,
                 checkpoint: Checkpoint = _noop, stats: dict | None = None):
        self.constraints = constraints
        self.params = params
        self.checkpoint = checkpoint
        self.stats = stats if stats is not None else {}
        self.models = {mode: _CandidateConstructor(constraints, mode, checkpoint, self.stats)
                       for mode in ("earliest", "center")}

    def _windows(self, task: SchedulingTask) -> list[TaskWindow]:
        groups: dict[str, list[TaskWindow]] = {}
        for window in task.windows:
            self.checkpoint()
            decision = planning_window(window)
            if decision.status is not ExposureStatus.PLANNING_FEASIBLE:
                continue
            if (decision.safe_end - decision.safe_start).total_seconds() < task.required_duration:
                continue
            groups.setdefault(window.satellite_id, []).append(window)
        cap = min(self.params.max_windows_per_task, self.params.max_candidates_per_task)
        satellite_ids = _spread(sorted(groups), cap)
        if not satellite_ids:
            return []
        buckets = []
        for index, sid in enumerate(satellite_ids):
            self.checkpoint()
            windows = sorted(groups[sid], key=self._window_key)
            quota = cap // len(satellite_ids) + (index < cap % len(satellite_ids))
            buckets.append(_spread(windows, quota))
        selected = []
        for offset in range(max(map(len, buckets))):
            for bucket in buckets:
                self.checkpoint()
                if offset < len(bucket):
                    selected.append(bucket[offset])
        return selected

    def _window_key(self, window: TaskWindow) -> tuple:
        self.checkpoint()
        return window.start_time, window.end_time, window.window_id, window.sensor_id

    def build(self, task: SchedulingTask) -> list[Assignment]:
        self.checkpoint()
        if task.required_duration <= 0:
            return []
        windows = self._windows(task)
        candidates = []
        seen = set()
        for mode in ("earliest", "center"):
            for window in windows:
                self.checkpoint()
                if len(candidates) >= self.params.max_candidates_per_task:
                    return candidates
                self.stats["candidate_builder_calls"] = self.stats.get("candidate_builder_calls", 0) + 1
                candidate = self.models[mode].build_feasible_assignment_for_task(
                    replace(task, windows=[window]), Schedule(), randomized=False,
                )
                self.checkpoint()
                if candidate is None:
                    continue
                key = canonical_assignment_key(candidate, self.checkpoint)
                if key not in seen:
                    seen.add(key)
                    candidates.append(candidate)
        # The list order is deterministic and intentionally preserves coverage
        # before extra positions; solve applies a separate deterministic ranking.
        return candidates
