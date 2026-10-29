"""冲突感知束搜索：增加来源网格覆盖、边界补点与任务子集多样性，保留公共可行性检查。

参考 2026-10-28 交付快照选择性移植；不引入 Score/v2 协议，不修改物理与指标口径。
"""
from __future__ import annotations

from bisect import bisect_left
from copy import deepcopy
from dataclasses import dataclass, fields, replace
from datetime import datetime, timedelta, timezone
import math
import time
from typing import Callable, Literal

from pydantic import ConfigDict, Field

from algorithms.objectives import ObjectiveModel
from algorithms.solver_contracts import AlgorithmParams, SolveContext
from schedulers.constraint_model import Assignment, ConstraintModel, Schedule
from schedulers.assignment_building import observation_at_index
from schedulers.scenario_loader import SchedulingProblem, SchedulingTask, TaskWindow
from utils.continuous_exposure import ExposureStatus
from schedulers.preview_exposure import candidate_exposure

VERSION = "0.5.0-course.1"
Checkpoint = Callable[[], None]


def _noop() -> None:
    pass


class CAABSParams(AlgorithmParams):
    """Experimental defaults, independent of the system registry."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    beam_width: int = Field(default=8, ge=1, le=256, strict=True)
    branch_limit: int = Field(default=8, ge=1, le=64, strict=True)
    candidate_check_limit: int = Field(default=16, ge=1, le=128, strict=True)
    max_candidates_per_task: int = Field(default=16, ge=1, le=128, strict=True)
    max_windows_per_task: int = Field(default=32, ge=1, le=256, strict=True)
    conflict_prefilter: bool = Field(default=True, strict=True)
    candidate_diversity: bool = Field(default=True, strict=True)
    task_order: Literal["id", "scarcity"] = "scarcity"
    greedy_incumbent: bool = Field(default=True, strict=True)
    incremental_keys: bool = Field(default=True, strict=True)
    incremental_objective: bool = Field(default=False, strict=True)
    dynamic_repair_limit: int = Field(default=12, ge=0, le=32, strict=True,
        description="静态候选在当前 Beam 状态均不可行时，任务边界附近最多补查的来源网格起点数。")
    grid_coverage: bool = Field(default=True, strict=True,
        description="在公共首中末锚点之后，用真实来源网格补足有界候选池。")
    diversity_slots: int = Field(default=2, ge=0, le=32, strict=True,
        description="Beam 内为不同已选任务集合保留的最多替换槽数；0 关闭。")


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
    if isinstance(value, list):
        return ("list", tuple(_freeze(item, checkpoint) for item in value))
    if isinstance(value, tuple):
        return ("tuple", tuple(_freeze(item, checkpoint) for item in value))
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
class ObjectiveTotals:
    profit: float
    wait_s: float
    workloads: tuple[float, ...]


class _IncrementalObjective:
    """Exact arithmetic domain; fall back to the full public objective otherwise.

    Integral nonnegative priorities and integral seconds whose sums stay below
    2**52 are exactly representable regardless of set/dict summation order.
    Fractional priorities, negative priorities, subsecond horizons/placements
    and oversized sums use ObjectiveModel.score, preserving its rounding and
    clipping behavior. Workloads use the public balance helper.
    """

    def __init__(self, objective: ObjectiveModel, checkpoint: Checkpoint):
        self.objective = objective
        self.horizon = (objective.problem.end_time-objective.problem.start_time).total_seconds()
        self.sat_index = {sid: i for i, sid in enumerate(objective.sat_ids)}
        priorities = []
        for task in objective.problem.tasks.values():
            checkpoint()
            priorities.append(float(task.priority))
        self.safe = (bool(priorities) and self.horizon > 0 and self.horizon.is_integer()
            and self.horizon * len(priorities) < 2**52
            and all(math.isfinite(p) and p >= 0 and p.is_integer() for p in priorities)
            and sum(priorities) < 2**52)

    def initial(self) -> ObjectiveTotals | None:
        return ObjectiveTotals(0., 0., (0.,)*len(self.sat_index)) if self.safe else None

    def extend(self, parent: ObjectiveTotals | None, candidate: Assignment) -> ObjectiveTotals | None:
        if parent is None:
            return None
        offset = max(0., (candidate.sat_start_time-self.objective.problem.start_time).total_seconds())
        duration = (candidate.sat_end_time-candidate.sat_start_time).total_seconds()
        if (not offset.is_integer() or not duration.is_integer() or offset > self.horizon
                or sum(parent.workloads)+duration >= 2**52):
            return None
        loads = list(parent.workloads)
        loads[self.sat_index[candidate.satellite_id]] += duration
        return ObjectiveTotals(parent.profit+float(self.objective.problem.tasks[candidate.task_id].priority),
            parent.wait_s+offset, tuple(loads))

    def score(self, totals: ObjectiveTotals, completed: int) -> float:
        model = self.objective
        w = model.weights
        profit = max(0., min(1., totals.profit/model.total_priority))
        tm = (totals.wait_s+(len(model.problem.tasks)-completed)*self.horizon)/(self.horizon*len(model.problem.tasks))
        timeliness = max(0., min(1., 1.-tm))
        balance = model.balance_score_from_workloads(dict(zip(model.sat_ids, totals.workloads))) if w.w_balance else 0.
        return (w.w_profit*profit + w.w_completion*(completed/float(model.total_tasks))
                + w.w_timeliness*timeliness + w.w_balance*balance)


def extend_canonical_key(parent_key: tuple, candidate_key: tuple, checkpoint: Checkpoint = _noop) -> tuple:
    """Insert an exact complete Assignment key; no hash-only identity."""
    checkpoint()
    index = bisect_left(parent_key, candidate_key)
    result = parent_key[:index] + (candidate_key,) + parent_key[index:]
    checkpoint()
    return result


@dataclass(frozen=True)
class BeamState:
    schedule: Schedule
    task_index: int
    completed: int
    objective_score: float
    canonical_key: tuple
    objective_totals: ObjectiveTotals | None = None

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
    """Public anchors followed by bounded, evenly spread source-grid coverage.

    Selection balances satellites, then spreads each satellite's window quota
    over the horizon. Diversity rotates public placement anchors across windows.
    Public constructors choose only their first feasible downlink combination.
    """

    def __init__(self, constraints: ConstraintModel, params: CAABSParams,
                 checkpoint: Checkpoint = _noop, stats: dict | None = None):
        self.constraints = constraints
        self.params = params
        self.checkpoint = checkpoint
        self.stats = stats if stats is not None else {}
        self.models = {mode: _CandidateConstructor(constraints, mode, checkpoint, self.stats)
                       for mode in ("earliest", "center", "latest")}

    def _windows(self, task: SchedulingTask) -> list[TaskWindow]:
        groups: dict[str, list[TaskWindow]] = {}
        for window in task.windows:
            self.checkpoint()
            # 复用公共曝光准入，避免 CAABS 在工程模式额外要求正式窗口来源。
            # 这里只判断窗口能否容纳一次曝光；公共构造器和 Controller 仍完整核验。
            decision = candidate_exposure(self.constraints.problem, window, window.start_time,
                window.start_time + timedelta(seconds=task.required_duration), task.required_duration)
            if decision.status is not ExposureStatus.PLANNING_FEASIBLE:
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
        modes = ("earliest", "center", "latest")
        for round_index in range(len(modes)):
            for window_index, window in enumerate(windows):
                # Rotate anchors across the selected windows instead of letting
                # an earliest-only round fill every candidate slot. Non-agile
                # placement remains controlled by the public constructor.
                mode = modes[(round_index + (window_index if self.params.candidate_diversity else 0)) % len(modes)]
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
        if len(candidates) >= self.params.max_candidates_per_task:
            return candidates
        # 只补充来源网格上的真实采样点；每个候选仍经当前公共约束检查。
        if self.params.grid_coverage and not self.constraints.has_ground_stations:
            remaining = self.params.max_candidates_per_task - len(candidates)
            per_window = max(1, math.ceil(remaining / max(1, len(windows))))
            buckets = []
            for window in windows:
                self.checkpoint()
                if self.constraints.problem.satellites[window.satellite_id].maneuverability_type != "agile":
                    continue
                step = float(window.time_step)
                last = math.floor(((window.end_time-window.start_time).total_seconds()
                                   - task.required_duration + 1e-9)/step)
                if last < 0 or last > 1024:
                    continue
                count = min(last + 1, per_window + 6)
                buckets.append((window, _spread(list(range(last + 1)), count)))
            for depth in range(max((len(indices) for _, indices in buckets), default=0)):
                for window, indices in buckets:
                    self.checkpoint()
                    if depth >= len(indices):
                        continue
                    candidate = observation_at_index(self.constraints.problem, task, window, indices[depth])
                    if candidate is None:
                        continue
                    key = canonical_assignment_key(candidate, self.checkpoint)
                    if key in seen:
                        continue
                    self.stats["grid_candidates_checked"] = self.stats.get("grid_candidates_checked", 0) + 1
                    if not self.constraints.is_feasible_assignment(candidate, Schedule()):
                        continue
                    seen.add(key)
                    candidates.append(candidate)
                    if len(candidates) >= self.params.max_candidates_per_task:
                        return candidates
        # Deterministic coverage order; solve has separate check/child budgets.
        return candidates

    def repair(self, task: SchedulingTask, schedule: Schedule,
               static: list[Assignment]) -> list[Assignment]:
        """Bounded source-grid placements near occupied task boundaries.

        Public feasibility remains in the caller. Downlink cases retain the
        existing public constructor path until a shared indexed builder exists.
        """
        limit = self.params.dynamic_repair_limit
        if not limit or self.constraints.has_ground_stations:
            return []
        seen = {(a.satellite_id, a.sat_window_id, a.sat_start_time) for a in static}
        result = []
        for window in self._windows(task):
            self.checkpoint()
            sat = self.constraints.problem.satellites[window.satellite_id]
            if sat.maneuverability_type == "non_agile":
                continue
            occupied = sorted(schedule.get_assignments_for_satellite(window.satellite_id),
                              key=lambda a: a.sat_start_time)
            if not occupied:
                continue
            step = float(window.time_step)
            last = math.floor(((window.end_time-window.start_time).total_seconds()
                               - task.required_duration + 1e-9)/step)
            indices = []
            for prior in occupied:
                # A successor may need several extra grid steps for attitude
                # slew; a predecessor may need to end earlier for the same.
                after = math.ceil((prior.sat_end_time-window.start_time).total_seconds()/step-1e-9)
                before = math.floor(((prior.sat_start_time-window.start_time).total_seconds()
                                     - task.required_duration)/step+1e-9)
                # Alternate grid steps first to cover a useful slew span
                # before the small per-state budget is exhausted.
                offsets = list(range(0, 25, 2)) + list(range(1, 24, 2))
                indices.extend(after + delta for delta in offsets)
                indices.extend(before - delta for delta in offsets)
            for k in dict.fromkeys(indices):
                self.checkpoint()
                if k < 0 or k > last:
                    continue
                candidate = observation_at_index(self.constraints.problem, task, window, k)
                if candidate is None:
                    continue
                key = (candidate.satellite_id, candidate.sat_window_id, candidate.sat_start_time)
                if key in seen:
                    continue
                seen.add(key)
                result.append(candidate)
                if len(result) >= limit:
                    self.stats["dynamic_candidates_generated"] = self.stats.get("dynamic_candidates_generated", 0) + len(result)
                    return result
        self.stats["dynamic_candidates_generated"] = self.stats.get("dynamic_candidates_generated", 0) + len(result)
        return result


def static_opportunity_key(task: SchedulingTask, candidates: list[Assignment]) -> tuple:
    """Sampled public-feasible opportunities, NOT all-window feasibility.

    The caller constructs candidates with the authoritative model on an empty
    plan. Ground station, resource, attitude and source rules are included in
    those checks. No-candidate tasks go last; IDs resolve every tie.
    """
    opportunities = {(a.satellite_id, a.sat_window_id) for a in candidates}
    satellites = {a.satellite_id for a in candidates}
    latest = max((a.sat_start_time for a in candidates), default=datetime.max)
    density = float(task.priority) / max(float(task.required_duration), 1e-9)
    return not bool(candidates), len(opportunities), len(satellites), latest, -density, task.id


@dataclass(frozen=True)
class SafeConflictIndex:
    """Per-state sparse observations, NOT an all-candidate pair graph.

    Only task identity and strict half-open observation overlap are indexed.
    Prefix maximum ends also make overlap lookup correct on arbitrary fixtures.
    Slew, downlinks, ground stations and cumulative resources are delegated.
    """

    task_ids: frozenset[str]
    observations: dict[str, tuple[tuple, tuple]]

    @classmethod
    def from_schedule(cls, schedule: Schedule, checkpoint: Checkpoint = _noop) -> SafeConflictIndex:
        tasks = set()
        by_satellite: dict[str, list] = {}
        for assignment in schedule.assignments:
            checkpoint()
            tasks.add(assignment.task_id)
            by_satellite.setdefault(assignment.satellite_id, []).append(
                (assignment.sat_start_time, assignment.sat_end_time))
        observations = {}
        for sid, intervals in by_satellite.items():
            checkpoint()
            intervals.sort()
            starts, prefix_ends = [], []
            for start, end in intervals:
                checkpoint()
                starts.append(start)
                prefix_ends.append(max(prefix_ends[-1], end) if prefix_ends else end)
            observations[sid] = (tuple(starts), tuple(prefix_ends))
        checkpoint()
        return cls(frozenset(tasks), observations)

    def rejects(self, candidate: Assignment) -> bool:
        if candidate.task_id in self.task_ids:
            return True
        intervals = self.observations.get(candidate.satellite_id)
        if intervals is None:
            return False
        starts, prefix_ends = intervals
        before_end = bisect_left(starts, candidate.sat_end_time)
        return before_end > 0 and prefix_ends[before_end - 1] > candidate.sat_start_time


class _SearchStopped(Exception):
    def __init__(self, reason: str):
        self.reason = reason


class _SolveControl:
    def __init__(self, context: SolveContext, clock: Callable[[], float]):
        self.clock = clock
        self.context = context
        self.started = clock()
        budget = context.time_budget_s
        if not math.isfinite(budget) or budget <= 0:
            raise ValueError("time_budget_s must be finite and positive")
        # A best effort reserve, not a hard real-time guarantee for native calls.
        self.reserve_s = min(0.05, budget * 0.05)
        self.deadline = self.started + budget - self.reserve_s
        self.reason = "completed"

    def checkpoint(self) -> None:
        if self.context.is_cancelled():
            self.reason = "cancelled"
            raise _SearchStopped(self.reason)
        if self.clock() >= self.deadline:
            self.reason = "budget"
            raise _SearchStopped(self.reason)


class ConflictBeamScheduler:
    """Direct Solver implementation; all per-run state lives inside solve().

    clock is a synchronous test injection. The scheduler never captures a
    pre-Worker SolveContext, writes files, or manufactures lifecycle statuses.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self.clock = clock

    def _observe_beam(self, states: tuple[BeamState, ...]) -> None:
        """Read-only diagnostic hook for small deterministic tests; no storage."""

    def solve(self, problem: SchedulingProblem, constraints: ConstraintModel,
              context: SolveContext) -> Schedule:
        control = _SolveControl(context, self.clock)
        checkpoint = control.checkpoint
        stats = {
            "candidate_builder_calls": 0, "candidate_constraint_calls": 0,
            "generated_candidates": 0, "prefilter_rejections": 0,
            "public_constraint_calls": 0, "accepted_insertions": 0,
            "scored_states": 0, "duplicate_states": 0, "pruned_states": 0,
            "max_beam_size": 0, "max_children": 0, "levels_completed": 0,
            "candidate_checks": 0, "feasible_children": 0,
            "prepared_tasks": 0, "candidate_cache_hits": 0,
            "greedy_tasks_completed": 0,
            "incremental_key_calls": 0, "full_key_calls": 0,
            "incremental_objective_calls": 0, "full_objective_calls": 0,
            "skip_states": 0,
            "dedup_input_states": 0,
            "dynamic_candidates_generated": 0, "dynamic_repair_states": 0,
            "dynamic_repair_successes": 0,
            "grid_candidates_checked": 0,
            "diversity_replacements": 0,
        }
        best_feasible = Schedule()
        best_rank = None
        phase = "initialization"
        try:
            checkpoint()
            params = CAABSParams.model_validate(context.params.model_dump())
            objective = ObjectiveModel(problem, context.objective_weights)
            incremental = _IncrementalObjective(objective, checkpoint) if params.incremental_objective else None
            checkpoint()
            # ID order is deliberately fixed: no order changes after a skip.
            task_ids = sorted(problem.tasks, key=lambda tid: (checkpoint(), tid)[1])
            checkpoint()
            adapter = BoundedCandidateAdapter(constraints, params, checkpoint, stats)
            # Cache lifetime is exactly this solve: problem, model configuration,
            # modes, evidence and budgets are captured here, never reused by a
            # different scene/constraint domain or a later invocation.
            candidate_cache: dict[str, list[Assignment]] = {}

            def prepare_candidates(tid: str) -> list[Assignment]:
                nonlocal phase
                phase = "candidate_preparation"
                checkpoint()
                if tid in candidate_cache:
                    stats["candidate_cache_hits"] += 1
                    return candidate_cache[tid]
                result = adapter.build(problem.tasks[tid])
                stats["generated_candidates"] += len(result)
                stats["prepared_tasks"] += 1
                # Only ordering/greedy needs reuse. Keep default streaming
                # preparation's memory footprint bounded by the current task.
                if params.task_order != "id" or params.greedy_incumbent:
                    candidate_cache[tid] = result
                return result

            def state(schedule: Schedule, task_index: int, parent: BeamState | None = None,
                      candidate: Assignment | None = None, candidate_key: tuple | None = None) -> BeamState:
                nonlocal phase
                phase = "scoring"
                checkpoint()
                totals = (incremental.extend(parent.objective_totals, candidate) if parent is not None
                          else incremental.initial()) if incremental else None
                if totals is None:
                    score = objective.score(schedule)
                    stats["full_objective_calls"] += 1
                else:
                    score = incremental.score(totals, len(schedule.assignments))
                    stats["incremental_objective_calls"] += 1
                stats["scored_states"] += 1
                checkpoint()
                phase = "canonicalization"
                if params.incremental_keys and parent is not None:
                    key = extend_canonical_key(parent.canonical_key, candidate_key, checkpoint)
                    stats["incremental_key_calls"] += 1
                else:
                    key = canonical_state_key(schedule, checkpoint)
                    stats["full_key_calls"] += 1
                return BeamState(schedule, task_index, len(schedule.assignments), score, key, totals)

            def remember(candidate_state: BeamState) -> None:
                nonlocal best_feasible, best_rank, phase
                checkpoint()
                incumbent_rank = candidate_state.rank_key
                if best_rank is None or incumbent_rank < best_rank:
                    # Only replace the incumbent after the isolated copy finishes.
                    phase = "incumbent_copy"
                    snapshot = clone_schedule(candidate_state.schedule, checkpoint)
                    best_feasible = snapshot
                    best_rank = incumbent_rank

            initial = state(Schedule(), 0)
            remember(initial)
            if params.task_order == "scarcity" or params.greedy_incumbent:
                for tid in task_ids:
                    prepare_candidates(tid)
                if params.task_order == "scarcity":
                    phase = "task_ordering"
                    def opportunity(tid: str) -> tuple:
                        checkpoint()
                        return static_opportunity_key(problem.tasks[tid], candidate_cache[tid])
                    task_ids.sort(key=opportunity)
                    checkpoint()
            if params.greedy_incumbent:
                greedy = initial
                for tid in task_ids:
                    phase = "greedy_initialization"
                    checkpoint()
                    choices = sorted(candidate_cache[tid], key=lambda a: (a.sat_start_time, a.satellite_id, a.sat_window_id))
                    for candidate in choices[:params.candidate_check_limit]:
                        checkpoint()
                        stats["candidate_checks"] += 1
                        stats["public_constraint_calls"] += 1
                        accepted = constraints.is_feasible_assignment(candidate, greedy.schedule)
                        checkpoint()
                        if not accepted:
                            continue
                        stats["accepted_insertions"] += 1
                        phase = "state_copy"
                        key = canonical_assignment_key(candidate, checkpoint) if params.incremental_keys else None
                        greedy = state(branch_schedule(greedy.schedule, candidate, checkpoint), 0, greedy, candidate, key)
                        remember(greedy)
                        stats["greedy_tasks_completed"] += 1
                        break
            beam = [initial]
            stats["max_beam_size"] = 1
            for task_index, tid in enumerate(task_ids, 1):
                phase = "candidate_preparation"
                checkpoint()
                # Prepare one task at a time, preserving an incumbent if later
                # preparation is interrupted. Candidate order preserves coverage.
                candidates = prepare_candidates(tid)
                phase = "candidate_keys"
                candidate_keys = {id(a): canonical_assignment_key(a, checkpoint) for a in candidates} if params.incremental_keys else {}
                children: list[BeamState] = []
                for parent in beam:
                    phase = "expansion"
                    checkpoint()
                    # A skip is a real, independent branch at the next cursor.
                    phase = "state_copy"
                    skipped = BeamState(clone_schedule(parent.schedule, checkpoint), task_index,
                                        parent.completed, parent.objective_score, parent.canonical_key, parent.objective_totals)
                    children.append(skipped)
                    stats["skip_states"] += 1
                    index = None
                    if params.conflict_prefilter:
                        phase = "conflict_index"
                        index = SafeConflictIndex.from_schedule(parent.schedule, checkpoint)
                    admitted = 0
                    for candidate in candidates[:params.candidate_check_limit]:
                        phase = "expansion"
                        checkpoint()
                        if admitted >= params.branch_limit:
                            break
                        stats["candidate_checks"] += 1
                        if index is not None and index.rejects(candidate):
                            stats["prefilter_rejections"] += 1
                            continue
                        stats["public_constraint_calls"] += 1
                        # Always check against the untouched PARENT, before append.
                        accepted = constraints.is_feasible_assignment(candidate, parent.schedule)
                        checkpoint()
                        if not accepted:
                            continue
                        stats["accepted_insertions"] += 1
                        phase = "state_copy"
                        child = state(branch_schedule(parent.schedule, candidate, checkpoint), task_index,
                                      parent, candidate, candidate_keys.get(id(candidate)))
                        remember(child)  # Save before deduplication or Top-B pruning.
                        children.append(child)
                        admitted += 1
                        stats["feasible_children"] += 1
                    if not admitted and params.dynamic_repair_limit:
                        phase = "dynamic_repair"
                        repair = adapter.repair(problem.tasks[tid], parent.schedule, candidates)
                        if repair:
                            stats["dynamic_repair_states"] += 1
                        for candidate in repair:
                            checkpoint()
                            stats["candidate_checks"] += 1
                            if index is not None and index.rejects(candidate):
                                stats["prefilter_rejections"] += 1
                                continue
                            stats["public_constraint_calls"] += 1
                            if not constraints.is_feasible_assignment(candidate, parent.schedule):
                                continue
                            checkpoint()
                            stats["accepted_insertions"] += 1
                            stats["dynamic_repair_successes"] += 1
                            key = canonical_assignment_key(candidate, checkpoint) if params.incremental_keys else None
                            child = state(branch_schedule(parent.schedule, candidate, checkpoint), task_index,
                                          parent, candidate, key)
                            remember(child)
                            children.append(child)
                            admitted += 1
                            stats["feasible_children"] += 1
                            if admitted >= params.branch_limit:
                                break
                stats["max_children"] = max(stats["max_children"], len(children))
                phase = "deduplication"
                unique = {}
                for child in children:
                    checkpoint()
                    stats["dedup_input_states"] += 1
                    if child.search_key in unique:
                        stats["duplicate_states"] += 1
                    else:
                        unique[child.search_key] = child
                phase = "pruning"
                checkpoint()

                def rank(child: BeamState) -> tuple:
                    checkpoint()
                    return child.rank_key

                ranked = sorted(unique.values(), key=rank)
                checkpoint()
                beam = ranked[:params.beam_width]
                # 为不同任务子集保留有界名额，避免同一组任务的多个时间放置挤掉跳过分支。
                # A top-B filled by many time placements of the same task set
                # can erase the skip path needed for a later conflicting task.
                # Reserve a small number of slots for distinct task subsets;
                # never bypass public feasibility or the global width bound.
                if params.diversity_slots and len(ranked) > len(beam):
                    def signature(item: BeamState) -> frozenset[str]:
                        return frozenset(a.task_id for a in item.schedule.assignments)
                    slots = min(params.diversity_slots, len(beam))
                    replacements = 0
                    signatures = {signature(item) for item in beam}
                    for alternative in ranked[len(beam):]:
                        checkpoint()
                        if replacements >= slots:
                            break
                        new_signature = signature(alternative)
                        if new_signature in signatures:
                            continue
                        counts = {}
                        for item in beam:
                            key = signature(item)
                            counts[key] = counts.get(key, 0) + 1
                        victim = next((i for i in range(len(beam)-1, -1, -1)
                            if counts[signature(beam[i])] > 1), None)
                        if victim is None:
                            break
                        beam[victim] = alternative
                        signatures.add(new_signature)
                        replacements += 1
                    beam.sort(key=rank)
                    stats["diversity_replacements"] += replacements
                stats["pruned_states"] += max(0, len(ranked) - len(beam))
                stats["max_beam_size"] = max(stats["max_beam_size"], len(beam))
                stats["levels_completed"] += 1
                self._observe_beam(tuple(beam))
                checkpoint()
        except _SearchStopped:
            pass
        else:
            phase = "completed"
        # No further search, score or full-plan copying after a stop. The
        # incumbent already owns its mutable data; attach only small diagnostics.
        best_feasible.metadata["caabs"] = {
            "version": VERSION, "stop_reason": control.reason,
            "stop_phase": phase, "return_reserve_s": control.reserve_s,
            "feasibility": "public_model_checked" if best_feasible.assignments else "structural_fallback",
            "stats": stats,
        }
        return best_feasible
