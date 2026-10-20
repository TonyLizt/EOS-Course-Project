"""PPO protocol for the existing actor/critic and shared scheduling rules."""
from dataclasses import asdict
from math import isfinite
from pydantic import Field

from algorithms.solver_contracts import AlgorithmParams

VERSION = 'ppo-shared-v1'
FEATURES = ['task_priority_norm', 'task_duration_norm', 'remaining_ratio',
            'sat_load_mean', 'sat_load_std']
ACTION_VERSION = 'shared-candidates-seeded-compact-skip-v1'
MAX_ACTIONS = 256
HIDDEN = 128
WEIGHTS = dict(w_profit=1.0, w_completion=0.0, w_timeliness=0.0, w_balance=0.0)
DOMAIN = dict(placement_mode='earliest', unassigned_penalty=1000.0,
              downlink_duration_ratio=1.0, agility_profile='Standard-Agility',
              non_agile_transition_s=10.0, has_ground_stations=False)
REWARD = dict(scale=10.0, skip_penalty=1.0)


class PPOParams(AlgorithmParams):
    model_id: str = Field('ppo-v1', pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$',
                          description='已训练并登记的PPO模型ID。仅earliest、默认约束、无地面站、收益目标；执行模式须与训练一致。')


def validate_weights(weights):
    values = asdict(weights) if hasattr(weights, '__dataclass_fields__') else weights.model_dump()
    if (not all(isfinite(v) and v >= 0 for v in values.values())
            or values['w_profit'] <= 0 or any(values[k] != 0 for k in values if k != 'w_profit')):
        raise ValueError('PPO_OBJECTIVE_MISMATCH: requires profit > 0, other weights = 0')


def validate_request(request, snapshot):
    validate_weights(request.objective_weights)
    actual = request.constraints.model_dump() | {'placement_mode': request.placement_mode}
    if (any(actual[k] != DOMAIN[k] for k in actual)
            or request.execution_mode != snapshot['execution_mode']):
        raise ValueError('PPO_MODEL_DOMAIN_MISMATCH: placement/constraints/execution_mode')


def scene_domain(scene, provenance):
    from utils.course_compatibility import engineering_attitude
    return dict(scenario_physics_version=provenance.get('scenario_physics_version'),
                attitude_model_version=engineering_attitude(scene, provenance),
                development_contract=scene.get('metadata', {}).get('extra', {}).get('development_generation_contract'))


def validate_scene(scene, provenance, snapshot):
    if scene_domain(scene, provenance) != snapshot['scene_domain']:
        raise ValueError('PPO_SCENARIO_PHYSICS_DOMAIN_MISMATCH')


def validate_constraints(problem, constraints, execution_mode):
    actual = {k: getattr(constraints, k) for k in DOMAIN if k != 'has_ground_stations'}
    actual['has_ground_stations'] = bool(problem.ground_stations)
    if (constraints.problem is not problem or actual != DOMAIN
            or getattr(problem, 'execution_mode', 'formal') != execution_mode):
        raise ValueError('PPO_MODEL_DOMAIN_MISMATCH: Runner constraint instance required')
