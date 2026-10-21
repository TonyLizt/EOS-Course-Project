"""R1 runtime contract; never edits or extends an original model manifest."""
from dataclasses import asdict
import hashlib
from math import isfinite
from pathlib import Path

from algorithms.objectives import ObjectiveWeights

VERSION = 'objective-v1'
FIELDS = tuple(ObjectiveWeights.__dataclass_fields__)
TP = dict(w_profit=1., w_completion=0., w_timeliness=0., w_balance=0.)
TCR = dict(w_profit=0., w_completion=1., w_timeliness=0., w_balance=0.)
MECHANISMS = {'ppo': 'frozen-policy-shortlist-objective-beam-v1',
              'lavis': 'frozen-value-shortlist-objective-beam-v1'}


def validate_weights(weights):
    raw = asdict(weights) if hasattr(weights, '__dataclass_fields__') else weights.model_dump() if hasattr(weights, 'model_dump') else dict(weights)
    if (set(raw) != set(FIELDS) or any(not isinstance(v, (int, float)) or not isfinite(v) or v < 0 for v in raw.values())
            or not isfinite(sum(raw.values())) or sum(raw.values()) <= 0):
        raise ValueError('OBJECTIVE_WEIGHTS_INVALID: finite nonnegative weights with finite positive sum required')
    return {key: float(raw[key]) for key in FIELDS}


def training_objective(aid):
    return TP.copy() if aid == 'ppo' else TCR.copy() if aid == 'lavis' else None


def adapter_code_sha():
    h = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob('*.py')):
        h.update(path.name.encode() + b'\0' + path.read_bytes().replace(b'\r\n', b'\n') + b'\0')
    return h.hexdigest()


def freeze_adapter(aid, solver_version, weights, model):
    requested = validate_weights(weights)
    normalized = asdict(ObjectiveWeights(**requested).normalized())
    training = training_objective(aid)
    return dict(schema=VERSION, algorithm_id=aid, solver_version=solver_version,
                mechanism=MECHANISMS.get(aid, 'native-proposal-objective-refinement-v1'),
                adapter_code_sha256_lf=adapter_code_sha(), training_objective=training,
                requested_objective=requested, effective_objective=requested.copy(),
                normalized_effective_objective=normalized,
                model_id=model.get('model_id'), model_sha256=model.get('model_sha256'),
                trained_for_requested_objective=(normalized == training) if training else None)


def validate_model_request(aid, request, snapshot):
    """Check original training domain separately from the requested search goal.

    The validation-only copy carries the *declared training objective* so that
    the unchanged native model protocol can check placement/physics settings.
    The original request/RunConfig is never rewritten; the R1 search scores it.
    """
    validate_weights(request.objective_weights)
    from eos_system.contracts import ObjectiveOptions
    training_request = request.model_copy(update={'objective_weights': ObjectiveOptions(**training_objective(aid))})
    if aid == 'ppo':
        from algorithms.ppo.protocol import validate_request
        validate_request(training_request, snapshot)
    elif aid == 'lavis':
        from algorithms.lavis.protocol import DOMAIN, validate_weights as native_weights
        native_weights(training_request.objective_weights)
        actual = request.constraints.model_dump() | dict(placement_mode=request.placement_mode, execution_mode=request.execution_mode)
        if any(actual[k] != DOMAIN[k] for k in actual):
            raise ValueError('LAVIS_MODEL_DOMAIN_MISMATCH: non-objective training domain')
    else:
        raise ValueError('UNKNOWN_LEARNED_OBJECTIVE_ADAPTER')


def verify_adapter(config):
    snapshot = config.objective_adapter
    if not snapshot:
        if config.algorithm_version.endswith('+' + VERSION):
            raise ValueError('OBJECTIVE_ADAPTER_SNAPSHOT_REQUIRED')
        return
    if not config.algorithm_version.endswith('+' + VERSION):
        raise ValueError('OBJECTIVE_ADAPTER_VERSION_MISMATCH')
    expected = freeze_adapter(config.algorithm_id, config.algorithm_version, config.objective_weights, config.model_provenance)
    if snapshot != expected:
        raise ValueError('OBJECTIVE_ADAPTER_IDENTITY_OR_OBJECTIVE_CHANGED')
