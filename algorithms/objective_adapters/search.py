"""Bounded model-guided beam and native-proposal refinement using ObjectiveModel.

Original model loaders, features, action masks and physical rules stay frozen.
The model supplies the shortlist and breaks equal-objective ties. It is not a
newly trained cross-objective model. Ablation switches are constructor-only,
not accepted from HTTP algorithm parameters.
"""
from copy import copy
from dataclasses import replace
from math import isfinite
import time

from algorithms.objectives import ObjectiveModel
from schedulers.constraint_model import Schedule
from .protocol import VERSION, freeze_adapter, validate_weights

BEAM = 4
MODEL_SHORTLIST = 8
PPO_SHORTLIST = 3
REPAIR_SEEDS = 16
POOL_PER_TASK = 16
POOL_TOTAL = 1024


class BudgetExpired(Exception):
    pass


class ObjectiveCancelled(RuntimeError):
    pass


class Control:
    def __init__(self, context, *, fraction=1.):
        self.context = context
        self.started = time.monotonic()
        self.deadline = self.started + context.time_budget_s * fraction - min(.05, context.time_budget_s * .03)
        self.checks = 0
        self.stats = dict(objective_evaluations=0, model_calls=0, alternatives=0, budget_exit=False)

    def checkpoint(self):
        if self.context.is_cancelled():
            raise ObjectiveCancelled('OBJECTIVE_SEARCH_CANCELLED')
        if time.monotonic() >= self.deadline:
            raise BudgetExpired()

    def check(self, cm, assignment, plan):
        self.checkpoint()
        self.checks += 1
        return cm.is_feasible_assignment(assignment, plan)

    def score(self, objective, plan):
        self.checkpoint()
        score = float(objective.score(plan))
        if not isfinite(score):
            raise ValueError('OBJECTIVE_NONFINITE_SCORE')
        self.stats['objective_evaluations'] += 1
        return score


def key(a):
    return (a.task_id, a.satellite_id, a.sensor_id, a.sat_window_id,
            a.sat_start_time.isoformat(), a.sat_end_time.isoformat(),
            a.ground_station_id or '', a.gs_window_id or 0,
            a.gs_start_time.isoformat() if a.gs_start_time else '',
            a.gs_end_time.isoformat() if a.gs_end_time else '')


def plan_key(plan):
    return tuple(sorted(key(a) for a in plan.assignments))


def replay(assignments, cm, control):
    plan = Schedule()
    for a in sorted(assignments, key=lambda x: (x.sat_start_time, x.task_id)):
        if not control.check(cm, a, plan):
            return None
        plan.assignments.append(a)
    return plan


def rank(plan, score, guide=0.):
    # Requested score is primary. Native/model information never overrides it.
    return (-score, -len(plan.assignments), -guide, plan_key(plan))


def identity(context, aid, version):
    return getattr(context, 'objective_adapter', {}) or freeze_adapter(aid, version, context.objective_weights, context.model_provenance)


def annotate(plan, context, aid, version, control, **extra):
    plan.metadata = dict(plan.metadata)
    plan.metadata['objective_adapter'] = dict(identity=identity(context, aid, version),
        **control.stats, constraint_checks=control.checks,
        search_seconds=time.monotonic()-control.started, **extra)
    return plan


class PPOObjectiveSolver:
    def __init__(self, context, version, *, adapt=True):
        from algorithms.ppo.model import FrozenPolicy
        if context.params.model_id != context.model_provenance.get('model_id'):
            raise ValueError('PPO_MODEL_ID_MISMATCH')
        validate_weights(context.objective_weights)
        self.frozen = FrozenPolicy(context.model_provenance)
        self.version, self.adapt = version, adapt

    def action_scores(self, observation):
        import torch
        with torch.no_grad():
            state = torch.as_tensor(observation['state'], dtype=torch.float32).unsqueeze(0)
            mask = torch.as_tensor(observation['action_mask']).unsqueeze(0)
            logits, _ = self.frozen.policy(state)
            if not torch.isfinite(logits).all():
                raise ValueError('PPO_NONFINITE_PREDICTION')
            logits = self.frozen.policy.apply_action_mask(logits, mask)
            return torch.log_softmax(logits[0], dim=-1).cpu().numpy()

    def solve(self, problem, constraints, context):
        from algorithms.ppo.environment import SharedPPOEnv
        from algorithms.ppo.protocol import validate_constraints
        validate_constraints(problem, constraints, context.model_provenance['execution_mode'])
        validate_weights(context.objective_weights)
        objective = ObjectiveModel(problem, context.objective_weights)
        control = Control(context)
        best = Schedule(); best_rank = rank(best, objective.score(best))
        width = BEAM if self.adapt else 1
        try:
            env = SharedPPOEnv(control.checkpoint)
            observation = env.reset(problem, constraints)
            # Rewards are not used for training here. Every branch and its state
            # now evaluates the actual requested objective, never the PPO TP reward.
            env.obj_model = objective
            env._last_score = objective.score(env.schedule)
            beams = [(env, observation, 0.)]
            for _ in problem.tasks:
                children = {}
                for parent, obs, guide in beams:
                    control.checkpoint()
                    scores = self.action_scores(obs)
                    control.stats['model_calls'] += 1
                    available = [i for i, valid in enumerate(obs['action_mask']) if valid]
                    learned = sorted(available, key=lambda i: (-float(scores[i]), i))
                    actions = learned[:PPO_SHORTLIST] if self.adapt else learned[:1]
                    if self.adapt and 0 not in actions: actions.append(0)
                    for action in actions:
                        control.checkpoint()
                        child = copy(parent)
                        child.schedule = Schedule(list(parent.schedule.assignments))
                        following, _, _, info = child.step(action)
                        if info['status'] in ('invalid_action', 'infeasible'):
                            continue
                        score = control.score(objective, child.schedule)
                        next_guide = guide + float(scores[action])
                        quality = rank(child.schedule, score, next_guide)
                        control.stats['alternatives'] += 1
                        if quality < best_rank:
                            best, best_rank = Schedule(list(child.schedule.assignments)), quality
                        canonical = plan_key(child.schedule)
                        if canonical not in children or quality < children[canonical][0]:
                            children[canonical] = (quality, child, following, next_guide)
                beams = [(p, obs, guide) for _, p, obs, guide in sorted(children.values(), key=lambda v: v[0])[:width]]
                if not beams or all(p.done for p, _, _ in beams): break
        except BudgetExpired:
            control.stats['budget_exit'] = True
        control.context.is_cancelled() and control.checkpoint()
        return annotate(best, context, 'ppo', self.version, control, mode='objective_beam' if self.adapt else 'ablation_model_only',
                        beam_width=width, model_shortlist=PPO_SHORTLIST if self.adapt else 1)


class LavisObjectiveSolver:
    def __init__(self, context, version, *, adapt=True):
        from algorithms.lavis.model import FrozenPredictor
        validate_weights(context.objective_weights)
        self.predictor = FrozenPredictor(context.model_provenance)
        self.version, self.adapt = version, adapt

    def solve(self, problem, constraints, context):
        from algorithms.lavis.protocol import Control as ModelControl, BudgetExpired as ModelBudget
        from algorithms.lavis.candidates import build_pool, feasible, key as native_key
        from algorithms.lavis.features import extract
        validate_weights(context.objective_weights)
        objective = ObjectiveModel(problem, context.objective_weights)
        control = Control(context)
        model_control = ModelControl(deadline=control.deadline, cancelled=context.is_cancelled)
        best = Schedule(); best_rank = rank(best, objective.score(best)); pool_stats = {}
        width = (min(8, context.params.max_branches) if context.params.search_mode == 'multistart' else BEAM) if self.adapt else 1
        try:
            pool, pool_stats = build_pool(problem, constraints, model_control, strategy=context.params.candidate_strategy)
            beams = [(Schedule(), 0.)]
            for _ in problem.tasks:
                children = {}
                for parent, guide in beams:
                    control.checkpoint()
                    current = feasible(pool, parent, constraints, model_control)
                    if not current: continue
                    rows = extract(problem, parent, pool, current, model_control)
                    scores = []
                    for offset in range(0, len(rows), 256):
                        control.checkpoint()
                        scores.extend(map(float, self.predictor.predict(rows[offset:offset+256])))
                        control.stats['model_calls'] += 1
                    if len(scores) != len(current) or not all(isfinite(x) for x in scores):
                        raise ValueError('LAVIS_NONFINITE_OR_MISSING_PREDICTION')
                    learned = sorted(zip(current, scores), key=lambda pair: (-pair[1], native_key(pair[0])))
                    for assignment, model_score in learned[:MODEL_SHORTLIST if self.adapt else 1]:
                        candidate = replay(parent.assignments + [assignment], constraints, control)
                        if candidate is None: continue
                        score = control.score(objective, candidate)
                        next_guide = guide + model_score
                        quality = rank(candidate, score, next_guide)
                        control.stats['alternatives'] += 1
                        if quality < best_rank:
                            best, best_rank = candidate, quality
                        canonical = plan_key(candidate)
                        if canonical not in children or quality < children[canonical][0]:
                            children[canonical] = (quality, candidate, next_guide)
                beams = [(p, guide) for _, p, guide in sorted(children.values(), key=lambda v: v[0])[:width]]
                if not beams: break
        except (BudgetExpired, ModelBudget):
            control.stats['budget_exit'] = True
        if context.is_cancelled(): model_control.checkpoint()
        control.checks += model_control.checks
        return annotate(best, context, 'lavis', self.version, control, mode='objective_beam' if self.adapt else 'ablation_model_only',
                        beam_width=width, model_shortlist=MODEL_SHORTLIST if self.adapt else 1,
                        native_search_mode=context.params.search_mode, pool=pool_stats)


class ConstraintBudget:
    """Deadline/cancel guard delegating every rule to the Runner's authority."""
    def __init__(self, original, control):
        self.original, self.control = original, control
        self.last_plan = Schedule()

    def __getattr__(self, name): return getattr(self.original, name)

    def is_feasible_assignment(self, assignment, schedule):
        self.control.checkpoint()
        self.last_plan = schedule
        return self.original.is_feasible_assignment(assignment, schedule)

    def check_discrete_assignment(self, assignment, schedule):
        self.control.checkpoint()
        return self.original.check_discrete_assignment(assignment, schedule)

    def build_initial_schedule(self):
        self.control.checkpoint()
        plan = self.original.build_initial_schedule()
        self.last_plan = plan
        self.control.checkpoint()
        return plan

    def build_feasible_assignment_for_task(self, *args, **kwargs):
        self.control.checkpoint()
        result = self.original.build_feasible_assignment_for_task(*args, **kwargs)
        self.control.checkpoint()
        return result


def refine(problem, constraints, context, initial, control):
    from algorithms.candidate_pool import enumerate_task_candidates
    objective = ObjectiveModel(problem, context.objective_weights)
    validated = replay(initial.assignments, constraints, control)
    if validated is None: raise ValueError('NATIVE_PROPOSAL_FAILED_SHARED_CONSTRAINTS')
    validated.metadata = dict(initial.metadata)
    best = validated
    best_rank = rank(best, control.score(objective, best))
    control.stats['native_objective_score'] = -best_rank[0]
    pool = []; native_keys = {key(a) for a in validated.assignments}
    def remember(plan):
        nonlocal best, best_rank
        quality = rank(plan, control.score(objective, plan))
        if quality < best_rank:
            best, best_rank = Schedule(list(plan.assignments), metadata=dict(initial.metadata)), quality
    def complete(seed, forbidden_task=None, forbidden_key=None):
        plan = Schedule(list(seed.assignments))
        remember(plan)
        for _ in problem.tasks:
            winner = None
            for a in pool:
                control.checkpoint()
                if a.task_id == forbidden_task or key(a) == forbidden_key or a.task_id in plan.assigned_task_ids: continue
                if not control.check(constraints, a, plan): continue
                proposal = replay(plan.assignments + [a], constraints, control)
                if proposal is None: continue
                score = control.score(objective, proposal)
                quality = (-score, -len(proposal.assignments), int(key(a) not in native_keys), key(a))
                control.stats['alternatives'] += 1
                if winner is None or quality < winner[0]: winner = (quality, proposal)
            if winner is None: break
            plan = winner[1]
            remember(plan)
        return plan
    try:
        remember(Schedule())
        for tid, task in sorted(problem.tasks.items()):
            control.checkpoint()
            candidates = enumerate_task_candidates(problem, task, placement_mode=constraints.placement_mode,
                downlink_duration_ratio=constraints.downlink_duration_ratio, max_candidates=POOL_PER_TASK,
                random_samples_per_window=0, seed=context.seed)
            for a in candidates:
                if control.check(constraints, a, Schedule()): pool.append(a)
                if len(pool) >= POOL_TOTAL: break
            if len(pool) >= POOL_TOTAL: break
        complete(validated)
        complete(Schedule())
        for removed in validated.assignments[:REPAIR_SEEDS]:
            seed = replay([a for a in validated.assignments if a is not removed], constraints, control)
            if seed is None: continue
            complete(seed, forbidden_task=removed.task_id)
            complete(seed, forbidden_key=key(removed))
    except BudgetExpired:
        control.stats['budget_exit'] = True
    control.stats['effective_objective_score'] = -best_rank[0]
    control.stats['refinement_pool'] = len(pool)
    return best


class NativeObjectiveSolver:
    def __init__(self, aid, context, native_build, version):
        validate_weights(context.objective_weights)
        self.base = native_build(replace(context, time_budget_s=context.time_budget_s*.55))
        self.algorithm = getattr(self.base, 'algorithm', None)
        self.aid, self.version = aid, version

    def solve(self, problem, constraints, context):
        validate_weights(context.objective_weights)
        control = Control(context)
        native_control = Control(context, fraction=.55)
        guarded = ConstraintBudget(constraints, native_control)
        try:
            initial = self.base.solve(problem, guarded, replace(context, time_budget_s=context.time_budget_s*.55))
            native_interrupted = False
        except BudgetExpired:
            initial = Schedule(list(guarded.last_plan.assignments))
            native_interrupted = True
        try:
            result = refine(problem, constraints, context, initial, control)
        except BudgetExpired:
            # Validation may exhaust the remaining budget; no unchecked output.
            result = Schedule()
            control.stats['budget_exit'] = True
        if context.is_cancelled(): control.checkpoint()
        return annotate(result, context, self.aid, self.version, control,
                        mode='native_proposal_refinement', native_interrupted=native_interrupted)


def build(aid, context, native_build, native_version):
    version = native_version + '+' + VERSION
    if aid == 'ppo': return PPOObjectiveSolver(context, version)
    if aid == 'lavis': return LavisObjectiveSolver(context, version)
    return NativeObjectiveSolver(aid, context, native_build, version)
