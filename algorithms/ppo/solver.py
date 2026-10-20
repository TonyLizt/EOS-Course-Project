"""Registered PPO Solver. No initial plan or random-policy fallback."""
import time

from algorithms.ppo.protocol import validate_constraints, validate_weights


class BudgetExpired(Exception):
    pass


class PPOSolver:
    def __init__(self, context):
        from algorithms.ppo.model import FrozenPolicy
        if context.model_provenance.get('model_id') != context.params.model_id:
            raise ValueError('PPO_MODEL_ID_MISMATCH')
        validate_weights(context.objective_weights)
        self.policy = FrozenPolicy(context.model_provenance)

    def solve(self, problem, constraints, context):
        from algorithms.ppo.environment import SharedPPOEnv
        from schedulers.constraint_model import Schedule
        validate_constraints(problem, constraints, context.model_provenance['execution_mode'])
        deadline = time.monotonic() + context.time_budget_s

        def checkpoint():
            if context.is_cancelled():
                raise RuntimeError('PPO_CANCELLED')
            if time.monotonic() >= deadline:
                raise BudgetExpired()

        env = SharedPPOEnv(checkpoint)
        try:
            obs = env.reset(problem, constraints)
            while not env.done:
                checkpoint()
                action = self.policy.greedy(obs['state'], obs['action_mask'])
                obs, _, _, _ = env.step(action)
        except BudgetExpired:
            pass
        return env.schedule if env.problem is not None else Schedule()


def build(context):
    return PPOSolver(context)
