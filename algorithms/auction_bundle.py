"""RABAS: centralized resource-aware bundle auction, using shared feasibility.

Bounded diverse local bundle chains per satellite, NOT a cross-round beam or CBBA.
Only validated current-version awards become the returned incumbent. No I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from collections import OrderedDict
import math
import time
from typing import Callable, Literal

from pydantic import ConfigDict, Field

from algorithms.objectives import ObjectiveModel
from algorithms.solver_contracts import AlgorithmParams, SolveContext
from schedulers.constraint_model import Assignment, ConstraintModel, Schedule
from schedulers.scenario_loader import SchedulingProblem

VERSION = '1.1.0'


class RABASParams(AlgorithmParams):
    model_config = ConfigDict(extra='forbid', frozen=True)
    max_bundle_size: int = Field(2, ge=1, le=3, strict=True, description='任务包最大任务数；1 为消融模式')
    bid_candidates_per_satellite: int = Field(8, ge=1, le=32, strict=True, description='每步最多比较的可行任务数')
    max_rounds: int = Field(0, ge=0, le=1000, strict=True, description='0 自动使用任务数，上限 1000')
    max_windows_per_task: int = Field(4, ge=1, le=32, strict=True, description='每任务每颗卫星的窗口上限')
    max_positions_per_window: int = Field(4, ge=1, le=8, strict=True, description='有界原始网格：所选模式、earliest/latest/center、冲突边界；非敏捷仅中心')
    max_checks_per_round: int = Field(20000, ge=16, le=100000, strict=True, description='每轮搜索约束检查上限；中标全量核验另计且最多为任务数')
    transition_cost_weight: float = Field(.1, ge=0, le=10, strict=True, allow_inf_nan=False)
    resource_cost_weight: float = Field(.1, ge=0, le=10, strict=True, allow_inf_nan=False)
    opportunity_cost_weight: float = Field(.5, ge=0, le=10, strict=True, allow_inf_nan=False)
    dynamic_scarcity: bool = Field(True, strict=True)
    diverse_candidates: bool = Field(True, strict=True)
    opportunity_probe_tasks: int = Field(4, ge=1, le=16, strict=True)
    multi_starts: int = Field(1, ge=1, le=4, strict=True)
    adaptive_search: bool = Field(True, strict=True)
    repair_attempts: int = Field(0, ge=0, le=64, strict=True)
    future_aware_rank: bool = Field(True, strict=True)
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
    future_gain: float = 0.

    @property
    def rank(self) -> tuple:
        return (-self.future_gain, -len(self.additions), -self.score, self.satellite_id,
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
                          option_cache_hits=0, template_cache_hits=0, opportunity_probes=0, opportunity_discrete_checks=0,
                          dynamic_scarce=0, multistart_paths=0, repair_attempts=0, repairs=0,
                          search_width_min=32, search_width_max=0)
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


    def probe(self, constraints, witness, plan):
        """Cheap opportunity ESTIMATE for an already source-validated witness.

        This never accepts a task or a bid. Candidate insertion and final award
        still use original.is_feasible_assignment, including custom predicates.
        """
        self.checkpoint()
        if self.round_checks >= self.check_limit:
            raise _RoundLimit()
        self.round_checks += 1
        self.stats['opportunity_discrete_checks'] += 1
        result = constraints.check_discrete_assignment(witness, plan)
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
        self.captured = []

    def is_feasible_assignment(self, assignment, plan):
        # Capture public constructor output only. This is NOT an acceptance decision:
        # options() checks every captured template against the original public model.
        self.control.checkpoint()
        self.captured.append(assignment)
        return False


class _Placement:
    """Deterministically ask the PUBLIC builder for one original-grid start."""
    def __init__(self, k): self.k = k
    def randrange(self, start, stop): return max(start, min(stop-1, self.k))
    def random(self): return 0.
    def shuffle(self, rows): pass


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
        self.template_cache = OrderedDict()
        self.witness_cache = {}
        self.effective_positions = params.max_positions_per_window
        self.effective_probes = params.opportunity_probe_tasks
        self.effective_windows = params.max_windows_per_task
        self.owners = {tid: sorted({w.satellite_id for w in task.windows}) for tid, task in problem.tasks.items()}
        self.deadlines = {tid: min((w.end_time for w in task.windows), default=problem.end_time) for tid, task in problem.tasks.items()}
        self.constructors = {}
        for sid in sorted(problem.satellites):
            control.checkpoint()
            self.constructors[sid] = _Constructor(constraints, constraints.placement_mode, sid, control)

    def _starts(self, sid, tid, window, plan):
        task = self.problem.tasks[tid]
        step = float(window.time_step or 1.)
        width = (window.end_time-window.start_time).total_seconds()-task.required_duration
        if width < 0 or step <= 0:
            return []
        last = max(0, math.floor((width+1e-9)/step))
        middle = max(0, min(last, round(width/2/step)))
        if self.problem.satellites[sid].maneuverability_type == 'non_agile':
            return [middle]
        mode = self.constraints.placement_mode
        preferred = middle if mode == 'center' else last if mode == 'latest' else 0
        proposed = [preferred, 0, last, middle]
        if self.effective_positions <= 3:
            return list(dict.fromkeys(proposed))[:self.effective_positions]
        # Align to the ORIGINAL grid; never shorten or rewrite source windows.
        # Public transition and source checks decide whether a proposed gap fits.
        templates = self.templates(sid, window, preferred)
        reference = templates[0] if templates else None
        for a in plan.get_assignments_for_satellite(sid):
            self.control.checkpoint()
            for point in (a.sat_end_time, a.gs_end_time):
                if point is not None:
                    offset = (point-window.start_time).total_seconds()
                    proposed.extend([math.ceil(offset/step), math.ceil((offset+self.constraints.non_agile_transition_s)/step)])
            if reference is not None:
                after = self.constraints._transition_time_s(sid, a, reference)
                before = self.constraints._transition_time_s(sid, reference, a)
                if math.isfinite(after):
                    proposed.append(math.ceil(((a.sat_end_time-window.start_time).total_seconds()+after)/step))
                if math.isfinite(before):
                    proposed.append(math.floor(((a.sat_start_time-window.start_time).total_seconds()-task.required_duration-before)/step))
        unique = list(dict.fromkeys(k for k in proposed if 0 <= k <= last))
        cap = self.effective_positions
        if cap >= 4 and len(unique) > cap:
            # Reserve half for gap boundaries instead of always truncating them away.
            unique = unique[:3] + _spread(unique[3:], cap-3)
        return unique[:cap]

    def templates(self, sid, window, k):
        c = self.control
        template_key = (window.window_id, k)
        if template_key not in self.template_cache:
            model = self.constructors[sid]
            model.captured = []
            c.stats['constructor_calls'] += 1
            model.build_feasible_assignment_for_task(self.single_tasks[window.window_id], Schedule(),
                                                     randomized=True, rng=_Placement(k))
            self.template_cache[template_key] = tuple(model.captured)
            if len(self.template_cache) > 4096:
                self.template_cache.popitem(last=False)
        else:
            c.stats['template_cache_hits'] += 1
        return self.template_cache[template_key]

    def options(self, sid: str, tid: str, plan: Schedule):
        c = self.control
        c.checkpoint()
        key = (sid, tid, tuple(id(a) for a in plan.assignments))
        if key in self.option_cache:
            c.stats['option_cache_hits'] += 1
            yield from self.option_cache[key]
            return
        seen, cached = set(), []
        for window in _spread(self.selected_windows.get((sid, tid), []), self.effective_windows):
            for k in self._starts(sid, tid, window, plan):
                c.checkpoint()
                for candidate in self.templates(sid, window, k):
                    akey = assignment_key(candidate)
                    if akey not in seen:
                        seen.add(akey)
                        if c.check(self.constraints, candidate, plan):
                            cached.append(candidate)
                            yield candidate
        self.option_cache[key] = tuple(cached)

    def has_option(self, sid, tid, plan):
        return next(self.options(sid, tid, plan), None) is not None

    def witnesses(self, tid, base):
        if tid not in self.witness_cache:
            found = []
            for sid in self.owners[tid]:
                from itertools import islice
                candidates = tuple(islice(self.options(sid, tid, base), 2))
                if candidates:
                    found.append(candidates)
                # A bounded estimate: two surviving satellites already establish alternatives.
                if len(found) == 2:
                    break
            self.witness_cache[tid] = tuple(found)
            if len(found) == 1 and len(self.owners[tid]) > 1:
                self.control.stats['dynamic_scarce'] += 1
        return self.witness_cache[tid]

    def order(self, sid, remaining, style=0):
        tids = [tid for tid in remaining if (sid, tid) in self.windows]
        if not self.params.diverse_candidates:
            return sorted(tids, key=lambda tid: (-self.problem.tasks[tid].priority, tid))
        def key(tid):
            task = self.problem.tasks[tid]
            scarcity = len(self.witness_cache.get(tid, self.owners[tid]))
            if style % 3 == 0:
                return (scarcity, self.deadlines[tid], task.required_duration, -task.priority, tid)
            if style % 3 == 1:
                return (-task.priority, task.required_duration, self.deadlines[tid], tid)
            return (task.required_duration, self.deadlines[tid], scarcity, -task.priority, tid)
        return sorted(tids, key=key)

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

    def bid(self, sid, version, base, candidate, additions, remaining, baseline, *, estimate=True):
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
        lost = 0.
        if estimate and p.opportunity_cost_weight:
            pool = ((set(tid for ss, tid in self.windows if ss == sid) & remaining)
                    if p.dynamic_scarcity else (set(self.exclusive.get(sid, [])) & remaining))
            protected = sorted(pool - {a.task_id for a in additions},
                key=lambda tid: (len(self.owners[tid]), self.deadlines[tid], -self.problem.tasks[tid].priority, tid))[:self.effective_probes]
            for tid in protected:
                witnesses = self.witnesses(tid, base)
                if not witnesses:
                    continue
                destroyed = 0
                for choices in witnesses:
                    witness = choices[0]
                    # Other satellites are independent only when no ground resource is shared.
                    if witness.satellite_id != sid and not self.problem.ground_stations:
                        continue
                    for witness in choices:
                        c.stats['opportunity_probes'] += 1
                        if c.probe(self.constraints, witness, candidate):
                            break
                    else:
                        destroyed += 1
                lost += destroyed / len(witnesses)
        opportunity = lost / max(1, len(remaining))
        transition_cost = transition/self.horizon
        score = delta - p.transition_cost_weight*transition_cost - p.resource_cost_weight*resource - p.opportunity_cost_weight*opportunity
        if not math.isfinite(score):
            raise ValueError('non-finite RABAS bid')
        c.checkpoint()
        c.stats['candidate_bundles'] += 1
        c.stats['max_bundle_built'] = max(c.stats['max_bundle_built'], len(additions))
        return BundleBid(sid, version, additions, tuple(candidate.get_assignments_for_satellite(sid)),
                         candidate, delta, transition, transition_cost, resource, opportunity, snapshots, score, len(additions)-p.opportunity_cost_weight*lost if p.future_aware_rank else float(len(additions)))


class ResourceAwareBundleAuctionScheduler:
    """Direct shared Solver; deterministic, no new processes or lifecycle writes."""
    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self.clock = clock

    def _observe_bid(self, bid: BundleBid):
        """Optional read-only diagnostic hook (no production storage)."""

    def _observe_award(self, bid: BundleBid):
        """Optional read-only diagnostic hook after atomic validated award."""

    def _repair(self, auction, plan, remaining, limit):
        c = auction.control
        # Try replacing one low-priority assignment by two currently unscheduled tasks.
        # Preserve the best full replay locally and publish each improvement atomically.
        for removed in sorted(plan.assignments, key=lambda a: auction.problem.tasks[a.task_id].priority):
            c.checkpoint()
            if c.stats['repair_attempts'] >= limit:
                break
            c.stats['repair_attempts'] += 1
            trial = Schedule([a for a in plan.assignments if a is not removed])
            inserted = []
            for tid in auction.order(removed.satellite_id, remaining)[:8]:
                a = next(auction.options(removed.satellite_id, tid, trial), None)
                if a is not None:
                    trial = Schedule(trial.assignments+[a])
                    inserted.append(a)
                if len(inserted) == 2:
                    replay = Schedule()
                    for assignment in sorted(trial.assignments, key=lambda a: (a.sat_start_time, assignment_key(a))):
                        if not c.check(auction.constraints, assignment, replay, award=True):
                            break
                        replay.assignments.append(assignment)
                    else:
                        c.stats['repairs'] += 1
                        return replay
                    break
        return plan

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
                auction.witness_cache.clear()
                baseline = {'balance': auction.objective.balance_score(plan) if auction.objective.weights.w_balance else 0.,
                            'transition': {sid: auction.transition_total(sid, plan) for sid in sorted(problem.satellites)}}
                bids = []
                truncated = None
                try:
                    workload = sum(len(rows) for rows in auction.selected_windows.values())
                    width, starts = params.bid_candidates_per_satellite, params.multi_starts
                    auction.effective_positions = params.max_positions_per_window
                    auction.effective_probes = params.opportunity_probe_tasks
                    auction.effective_windows = params.max_windows_per_task
                    if params.adaptive_search:
                        # Cost depends on search volume and time left, not instance identity.
                        pressure = workload / max(.1, control.deadline-control.clock())
                        if pressure > 200:
                            width, starts = 1, 1
                            auction.effective_windows = min(params.max_windows_per_task, 2)
                            auction.effective_probes = 1
                            auction.effective_positions = min(params.max_positions_per_window, 2)
                        elif pressure > 50:
                            width, starts = min(width, 4), 1
                    control.stats['search_width_min'] = min(control.stats['search_width_min'], width)
                    control.stats['search_width_max'] = max(control.stats['search_width_max'], width)
                    for sid in sorted(problem.satellites):
                        control.checkpoint()
                        used_seeds = set()
                        for start_index in range(starts):
                            control.stats['multistart_paths'] += 1
                            prefix, additions = plan, ()
                            for depth in range(params.max_bundle_size):
                                best, feasible_tasks, finalists = None, 0, {}
                                pool = remaining - {a.task_id for a in additions}
                                if depth == 0:
                                    pool = pool - used_seeds
                                for tid in auction.order(sid, pool, start_index):
                                    control.checkpoint()
                                    found = False
                                    for assignment in auction.options(sid, tid, prefix):
                                        found = True
                                        candidate = Schedule(prefix.assignments + [assignment])
                                        bid = auction.bid(sid, version, plan, candidate,
                                            additions+(assignment,), remaining, baseline, estimate=False)
                                        previous = finalists.get(tid)
                                        if previous is None or bid.rank < previous.rank:
                                            finalists[tid] = bid
                                        # Preserve one completed quotation before wider exploration.
                                        if not bids:
                                            ready = auction.bid(sid, version, plan, candidate,
                                                additions+(assignment,), remaining, baseline)
                                            self._observe_bid(ready)
                                            bids.append(ready)
                                    feasible_tasks += int(found)
                                    if feasible_tasks >= width:
                                        break
                                # Expensive future-opportunity estimation only on a bounded shortlist.
                                # Candidates are already public-feasible; only finalized bids enter arbitration.
                                for proposal in sorted(finalists.values(), key=lambda b: b.rank)[:2]:
                                    ready = auction.bid(sid, version, plan, proposal.candidate_plan,
                                                        proposal.additions, remaining, baseline)
                                    self._observe_bid(ready)
                                    bids.append(ready)
                                    if best is None or ready.rank < best.rank:
                                        best = ready
                                if best is None:
                                    break
                                if depth == 0:
                                    used_seeds.add(best.additions[0].task_id)
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
        # Optional bounded 1 -> 2 replacement, only after auction stagnation.
        # Auction remains the construction mechanism. No neutral moves or loops.
        if params.repair_attempts and reason == 'no_feasible_bid':
            try:
                control.round_checks, control.check_limit = 0, params.max_checks_per_round
                plan = self._repair(auction, plan, remaining, params.repair_attempts)
            except (_BudgetExpired, _RoundLimit):
                pass
        # No unbounded copy/evaluation after stopping; plan is an owned award.
        if context.is_cancelled():
            raise RABASCancelled('RABAS cancelled before return')
        plan.metadata['rabas'] = {'version': VERSION, 'stop_reason': reason,
                                  'return_reserve_s': control.reserve,
                                  'stats': control.stats, 'awards': trace}
        return plan
