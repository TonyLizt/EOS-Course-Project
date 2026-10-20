"""RABAS: centralized resource-aware bundle auction, using shared feasibility.

One greedy local bundle chain per satellite, NOT a cross-round beam or CBBA.
Only validated current-version awards become the returned incumbent. No I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import time
from typing import Callable, Literal

from pydantic import ConfigDict, Field

from algorithms.objectives import ObjectiveModel
from algorithms.solver_contracts import AlgorithmParams, SolveContext
from schedulers.constraint_model import Assignment, ConstraintModel, Schedule
from schedulers.scenario_loader import SchedulingProblem, SchedulingTask

VERSION = '1.0.0'


class RABASParams(AlgorithmParams):
    model_config = ConfigDict(extra='forbid', frozen=True)
    max_bundle_size: int = Field(2, ge=1, le=3, strict=True, description='任务包最大任务数；1 为消融模式')
    bid_candidates_per_satellite: int = Field(8, ge=1, le=32, strict=True, description='每步最多比较的可行任务数')
    max_rounds: int = Field(0, ge=0, le=1000, strict=True, description='0 自动使用任务数，上限 1000')
    max_windows_per_task: int = Field(4, ge=1, le=32, strict=True, description='每任务每颗卫星的窗口上限')
    max_positions_per_window: int = Field(2, ge=1, le=2, strict=True, description='公共构造器 earliest/center；1 仅使用所选放置模式')
    max_checks_per_round: int = Field(20000, ge=16, le=100000, strict=True, description='每轮搜索约束检查上限；中标全量核验另计且最多为任务数')
    transition_cost_weight: float = Field(.1, ge=0, le=10, strict=True, allow_inf_nan=False)
    resource_cost_weight: float = Field(.1, ge=0, le=10, strict=True, allow_inf_nan=False)
    opportunity_cost_weight: float = Field(.5, ge=0, le=10, strict=True, allow_inf_nan=False)
    reauction_mode: Literal['all_affected'] = Field('all_affected', description='当前实现：所有卫星全量重新报价')


class RABASCancelled(RuntimeError):
    """Cooperative cancellation is not a successful anytime return."""


class _BudgetExpired(Exception):
    pass


class _RoundLimit(Exception):
    pass


def assignment_key(a: Assignment) -> tuple:
    return (a.satellite_id, a.task_id, a.sat_window_id, a.sat_start_time,
            a.sat_end_time, a.sensor_id, a.orbit_number,
            a.gs_window_id or 0, a.ground_station_id or '',
            a.gs_start_time.isoformat() if a.gs_start_time else '',
            a.gs_end_time.isoformat() if a.gs_end_time else '')


@dataclass(frozen=True)
class OrbitResources:
    orbit: int
    storage_used_GB: float
    storage_remaining_GB: float | None
    power_used_W: float
    power_remaining_W: float | None


@dataclass(frozen=True)
class BundleBid:
    satellite_id: str
    plan_version: int
    additions: tuple[Assignment, ...]
    local_plan: tuple[Assignment, ...]
    candidate_plan: Schedule
    utility_gain: float
    transition_seconds: float
    transition_cost: float
    resource_cost: float
    opportunity_cost: float
    resources: tuple[OrbitResources, ...]
    score: float

    @property
    def rank(self) -> tuple:
        return (-len(self.additions), -self.score, self.satellite_id,
                tuple(sorted(assignment_key(a) for a in self.additions)))


class _Control:
    def __init__(self, context: SolveContext, clock):
        if not math.isfinite(context.time_budget_s) or context.time_budget_s <= 0:
            raise ValueError('time_budget_s must be finite and positive')
        self.context, self.clock = context, clock
        self.reserve = min(.05, context.time_budget_s * .05)
        self.hard_deadline = clock() + context.time_budget_s
        self.deadline = self.hard_deadline - self.reserve
        self.stats = dict(rounds=0, candidate_bundles=0, max_bundle_built=0,
                          public_constraint_checks=0, constructor_calls=0,
                          reauctions=0, stale_bids_rejected=0, awards=0,
                          full_plan_copies=0, objective_full_calls=0, objective_delta_calls=0,
                          option_cache_hits=0)
        self.round_checks = 0
        self.check_limit = 0

    def checkpoint(self):
        if self.context.is_cancelled():
            raise RABASCancelled('RABAS cancelled by SolveContext')
        if self.clock() >= self.deadline:
            raise _BudgetExpired()

    def check(self, constraints, assignment, plan, *, award=False):
        self.checkpoint()
        if not award and self.round_checks >= self.check_limit:
            raise _RoundLimit()
        self.round_checks += 1
        self.stats['public_constraint_checks'] += 1
        result = constraints.is_feasible_assignment(assignment, plan)
        self.checkpoint()
        return result


class _Constructor(ConstraintModel):
    """Reuse the public builder, delegate every decision to ORIGINAL constraints.

    Bound downlink enumeration as well; its source IDs remain those of the full
    original problem. Never replace/reimplement the public physical predicate.
    """
    def __init__(self, original, mode, sid, control):
        comm = sorted((w for w in original.problem.comm_windows if w.satellite_id == sid),
                      key=lambda w: (w.start_time, w.end_time, w.window_id))
        super().__init__(replace(original.problem, comm_windows=_spread(comm, 4)),
                         placement_mode=mode, downlink_duration_ratio=original.downlink_duration_ratio,
                         unassigned_penalty=original.unassigned_penalty,
                         agility_profile=original.agility_profile,
                         non_agile_transition_s=original.non_agile_transition_s)
        self.original, self.control = original, control

    def is_feasible_assignment(self, assignment, plan):
        return self.control.check(self.original, assignment, plan)


def _spread(items, limit):
    if len(items) <= limit:
        return items
    if limit == 1:
        return items[:1]
    return [items[round(i * (len(items)-1)/(limit-1))] for i in range(limit)]


class _Auction:
    def __init__(self, problem, constraints, context, params, control):
        self.problem, self.constraints, self.params, self.control = problem, constraints, params, control
        self.objective = ObjectiveModel(problem, context.objective_weights)
        self.horizon = max(1., (problem.end_time-problem.start_time).total_seconds())
        self.windows, self.exclusive = {}, {}
        for tid, task in sorted(problem.tasks.items()):
            control.checkpoint()
            owners = set()
            for w in task.windows:
                control.checkpoint()
                owners.add(w.satellite_id)
                self.windows.setdefault((w.satellite_id, tid), []).append(w)
            if len(owners) == 1:
                self.exclusive.setdefault(next(iter(owners)), []).append(tid)
        self.selected_windows = {key: _spread(sorted(rows, key=lambda w: (w.start_time, w.end_time, w.window_id)),
                                              params.max_windows_per_task) for key, rows in self.windows.items()}
        self.single_tasks = {w.window_id: replace(problem.tasks[tid], windows=[w])
                             for (sid, tid), rows in self.selected_windows.items() for w in rows}
        self.option_cache = {}
        self.constructors = {}
        modes = [constraints.placement_mode]
        if params.max_positions_per_window == 2:
            modes.append('center' if constraints.placement_mode == 'earliest' else 'earliest')
        for sid in sorted(problem.satellites):
            control.checkpoint()
            self.constructors[sid] = [_Constructor(constraints, mode, sid, control) for mode in (modes[:1] if problem.satellites[sid].maneuverability_type == 'non_agile' else modes)]

    def options(self, sid: str, tid: str, plan: Schedule):
        self.control.checkpoint()
        # Exact plan identity, retained for one auction round only.
        key = (sid, tid, tuple(id(a) for a in plan.assignments))
        if key in self.option_cache:
            self.control.stats['option_cache_hits'] += 1
            yield from self.option_cache[key]
            return
        windows = self.selected_windows.get((sid, tid), [])
        cached = []
        seen = set()
        # Fixed input windows; no time/angle/source rewriting to create placements.
        for window in _spread(windows, self.params.max_windows_per_task):
            for model in self.constructors[sid]:
                self.control.checkpoint()
                self.control.stats['constructor_calls'] += 1
                candidate = model.build_feasible_assignment_for_task(
                    self.single_tasks[window.window_id], plan)
                self.control.checkpoint()
                if candidate is not None and assignment_key(candidate) not in seen:
                    seen.add(assignment_key(candidate))
                    cached.append(candidate)
                    yield candidate
        # Only complete enumerations are cached; early generator close is safe.
        self.option_cache[key] = tuple(cached)

    def has_option(self, sid, tid, plan):
        return next(self.options(sid, tid, plan), None) is not None

    def resources(self, sid, plan):
        satellite = self.problem.satellites[sid]
        totals = {}
        for a in plan.get_assignments_for_satellite(sid):
            self.control.checkpoint()
            storage, power = totals.get(a.orbit_number, (0., 0.))
            totals[a.orbit_number] = storage+a.data_volume_GB, power+a.power_cost_W
        return tuple(OrbitResources(orbit, storage,
            satellite.max_data_storage_GB-storage if satellite.max_data_storage_GB > 0 else None,
            power, satellite.max_power_W-power if satellite.max_power_W > 0 else None)
            for orbit, (storage, power) in sorted(totals.items()))

    def resource_pressure(self, sid, before, after, snapshots):
        satellite = self.problem.satellites[sid]
        old = {r.orbit: r for r in self.resources(sid, before)}
        costs = []
        for row in snapshots:
            self.control.checkpoint()
            previous = old.get(row.orbit)
            for value, former, capacity in (
                (row.storage_used_GB, previous.storage_used_GB if previous else 0., satellite.max_data_storage_GB),
                (row.power_used_W, previous.power_used_W if previous else 0., satellite.max_power_W)):
                if capacity > 0 and value != former:
                    costs.append((value/capacity)**2 - (former/capacity)**2)
        def occupancy(plan, ground=None):
            seconds = 0.
            for a in plan.assignments:
                self.control.checkpoint()
                if ground is None and a.satellite_id == sid:
                    seconds += (a.sat_end_time-a.sat_start_time).total_seconds()
                    if a.gs_start_time is not None:
                        seconds += (a.gs_end_time-a.gs_start_time).total_seconds()
                elif ground is not None and a.ground_station_id == ground:
                    seconds += (a.gs_end_time-a.gs_start_time).total_seconds()
            return seconds/self.horizon
        costs.append(occupancy(after)**2 - occupancy(before)**2)
        changed_stations = {a.ground_station_id for a in after.assignments[len(before.assignments):]
                            if a.ground_station_id is not None}
        for ground in sorted(changed_stations):
            costs.append(occupancy(after, ground)**2 - occupancy(before, ground)**2)
        return max(0., sum(costs)/len(costs))

    def transition_total(self, sid, plan):
        ordered = sorted(plan.get_assignments_for_satellite(sid), key=lambda a: (a.sat_start_time, a.task_id))
        total = 0.
        for previous, following in zip(ordered, ordered[1:]):
            self.control.checkpoint()
            total += self.constraints._transition_time_s(sid, previous, following)
        return total

    def bid(self, sid, version, base, candidate, additions, remaining, baseline):
        c, p = self.control, self.params
        c.checkpoint()
        # Exact shared-objective delta for additive terms. BD keeps its public helper.
        w = self.objective.weights
        delta = sum(w.w_profit*self.problem.tasks[a.task_id].priority/self.objective.total_priority
                    + w.w_completion/self.objective.total_tasks
                    + w.w_timeliness*(1-(a.sat_start_time-self.problem.start_time).total_seconds()/self.horizon)/self.objective.total_tasks
                    for a in additions)
        if w.w_balance:
            c.stats['objective_full_calls'] += 1
            delta += w.w_balance*(self.objective.balance_score(candidate)-baseline['balance'])
        c.stats['objective_delta_calls'] += 1
        transition = max(0., self.transition_total(sid, candidate)-baseline['transition'][sid])
        snapshots = self.resources(sid, candidate)
        resource = self.resource_pressure(sid, base, candidate, snapshots)
        lost = 0
        if p.opportunity_cost_weight:
            protected = sorted((set(self.exclusive.get(sid, [])) & remaining) - {a.task_id for a in additions},
                               key=lambda tid: (-self.problem.tasks[tid].priority, tid))[:p.bid_candidates_per_satellite]
            for tid in protected:
                c.checkpoint()
                key = sid, tid
                if key not in baseline['feasible']:
                    baseline['feasible'][key] = self.has_option(sid, tid, base)
                if baseline['feasible'][key] and not self.has_option(sid, tid, candidate):
                    lost += 1
        opportunity = lost / max(1, len(remaining))
        transition_cost = transition/self.horizon
        score = delta - p.transition_cost_weight*transition_cost - p.resource_cost_weight*resource - p.opportunity_cost_weight*opportunity
        if not math.isfinite(score):
            raise ValueError('non-finite RABAS bid')
        c.checkpoint()
        c.stats['candidate_bundles'] += 1
        c.stats['max_bundle_built'] = max(c.stats['max_bundle_built'], len(additions))
        return BundleBid(sid, version, additions, tuple(candidate.get_assignments_for_satellite(sid)),
                         candidate, delta, transition, transition_cost, resource, opportunity, snapshots, score)


class ResourceAwareBundleAuctionScheduler:
    """Direct shared Solver; deterministic, no new processes or lifecycle writes."""
    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self.clock = clock

    def _observe_bid(self, bid: BundleBid):
        """Optional read-only diagnostic hook (no production storage)."""

    def _observe_award(self, bid: BundleBid):
        """Optional read-only diagnostic hook after atomic validated award."""

    def solve(self, problem: SchedulingProblem, constraints: ConstraintModel, context: SolveContext) -> Schedule:
        control = _Control(context, self.clock)
        params = RABASParams.model_validate(context.params.model_dump())
        plan, version, trace, reason = Schedule(), 0, [], 'completed'
        try:
            control.checkpoint()
            auction = _Auction(problem, constraints, context, params, control)
            remaining = set(problem.tasks)
            rounds = params.max_rounds or min(1000, len(remaining))
            for _ in range(rounds):
                control.checkpoint()
                if not remaining:
                    break
                control.stats['rounds'] += 1
                control.stats['reauctions'] += int(version > 0)
                control.round_checks, control.check_limit = 0, params.max_checks_per_round
                # Per-round caches ONLY. Never reuse an old plan's quotations.
                auction.option_cache.clear()
                baseline = {'balance': auction.objective.balance_score(plan) if auction.objective.weights.w_balance else 0., 'feasible': {},
                            'transition': {sid: auction.transition_total(sid, plan) for sid in sorted(problem.satellites)}}
                bids = []
                truncated = None
                try:
                    for sid in sorted(problem.satellites):
                        control.checkpoint()
                        prefix, additions = plan, ()
                        for _depth in range(params.max_bundle_size):
                            best, feasible_tasks = None, 0
                            for tid in sorted(remaining - {a.task_id for a in additions},
                                              key=lambda tid: (-problem.tasks[tid].priority, tid)):
                                control.checkpoint()
                                if (sid, tid) not in auction.windows:
                                    continue
                                found = False
                                for assignment in auction.options(sid, tid, prefix):
                                    found = True
                                    candidate = Schedule(prefix.assignments + [assignment])
                                    control.checkpoint()
                                    bid = auction.bid(sid, version, plan, candidate,
                                        additions+(assignment,), remaining, baseline)
                                    self._observe_bid(bid)
                                    control.checkpoint()
                                    if best is None or bid.rank < best.rank:
                                        best = bid
                                        bids.append(bid)  # retain every completed best, even if next check stops
                                feasible_tasks += int(found)
                                if feasible_tasks >= params.bid_candidates_per_satellite:
                                    break
                            if best is None:
                                break
                            bids.append(best)  # one validated prefix per depth / satellite
                            prefix, additions = best.candidate_plan, best.additions
                except (_RoundLimit, _BudgetExpired) as stopped:
                    truncated = 'round_check_limit' if isinstance(stopped, _RoundLimit) else 'budget'
                    control.deadline = control.hard_deadline
                if not bids:
                    reason = truncated or 'no_feasible_bid'
                    break
                control.checkpoint()
                winner = min(bids, key=lambda bid: bid.rank)
                if winner.plan_version != version:
                    control.stats['stale_bids_rejected'] += 1
                    raise RuntimeError('stale RABAS bid cannot be awarded')
                # Independent full global replay before committing the bundle.
                replay = Schedule()
                for assignment in sorted(winner.candidate_plan.assignments, key=lambda a: (a.sat_start_time, assignment_key(a))):
                    if not control.check(constraints, assignment, replay, award=True):
                        raise RuntimeError('public constraints rejected RABAS global award')
                    replay.assignments.append(assignment)
                control.checkpoint()
                plan = replay
                remaining.difference_update(a.task_id for a in winner.additions)
                trace.append({'version': version, 'satellite_id': winner.satellite_id,
                              'tasks': sorted(a.task_id for a in winner.additions),
                              'bid': winner.score, 'opportunity_cost': winner.opportunity_cost})
                control.stats['awards'] += 1
                version += 1
                self._observe_award(winner)
                if truncated:
                    reason = truncated
                    break
                bids.clear()  # all old quotes invalidated; next round rebuilds all
            else:
                if remaining:
                    reason = 'round_limit'
        except _BudgetExpired:
            reason = 'budget'
        except _RoundLimit:
            reason = 'round_check_limit'
        # No unbounded copy/evaluation after stopping; plan is an owned award.
        if context.is_cancelled():
            raise RABASCancelled('RABAS cancelled before return')
        plan.metadata['rabas'] = {'version': VERSION, 'stop_reason': reason,
                                  'return_reserve_s': control.reserve,
                                  'stats': control.stats, 'awards': trace}
        return plan
