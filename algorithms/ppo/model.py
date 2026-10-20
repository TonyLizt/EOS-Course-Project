"""Local, administrator-produced PPO artifacts; same ID/snapshot pattern as LAVIS.

Hashes bind identity and compatibility, not performance or physical certification.
Only the training entry point publishes artifacts; legacy/raw state_dicts are rejected.
"""
import hashlib
import io
import json
import os
import pickle
import re
from importlib import metadata
from pathlib import Path

from algorithms.ppo.protocol import VERSION, FEATURES, ACTION_VERSION, MAX_ACTIONS, HIDDEN, DOMAIN, WEIGHTS, REWARD

MODEL_LIMIT = 50 * 1024 * 1024
ID_PATTERN = r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def inference_code_sha():
    root = Path(__file__).resolve().parents[2]
    names = ['algorithms/ppo/' + n + '.py' for n in ('protocol', 'environment', 'model', 'solver', 'policy')]
    names += ['algorithms/candidate_pool.py', 'algorithms/random_utils.py', 'algorithms/objectives.py', 'schedulers/rl_env.py',
              'schedulers/constraint_model.py', 'schedulers/source_windows.py',
              'schedulers/observation_geometry.py', 'schedulers/transition_utils.py',
              'schedulers/preview_exposure.py', 'schedulers/scenario_loader.py',
              'schedulers/balance_utils.py', 'schedulers/timeliness_utils.py',
              'core/models.py', 'utils/continuous_exposure.py', 'utils/visibility.py',
              'utils/attitude_frames.py', 'utils/time_parsing.py', 'utils/course_compatibility.py',
              'utils/certification_identity.py']
    h = hashlib.sha256()
    for name in sorted(names):
        h.update(name.encode() + b'\0')
        h.update((root / name).read_bytes().replace(b'\r\n', b'\n') + b'\0')
    return h.hexdigest()


def protocol_record():
    return dict(model_version=VERSION, format='team-torch-ppo-v1', features=FEATURES,
                state_dim=len(FEATURES), action_version=ACTION_VERSION,
                max_actions=MAX_ACTIONS, hidden=HIDDEN, domain=DOMAIN,
                objective_weights=WEIGHTS, reward=REWARD,
                inference_code_sha256_lf=inference_code_sha())


def dependencies():
    return {name: metadata.version(name) for name in ('torch', 'numpy')}


def model_root():
    return Path(os.environ.get('EOS_RUNTIME_DIR', '~/eos-course-runtime')).expanduser().resolve() / 'models' / 'ppo'


def state_digest(state):
    h = hashlib.sha256()
    for name, tensor in sorted(state.items()):
        h.update(name.encode() + b'\0')
        h.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def _decode(data, record):
    import torch
    from algorithms.ppo.policy import PPOPolicy
    try:
        checkpoint = torch.load(io.BytesIO(data), map_location='cpu', weights_only=True)
        for key in ('protocol', 'training', 'execution_mode', 'scene_domain'):
            expected = protocol_record() if key == 'protocol' else record[key]
            if checkpoint[key] != expected:
                raise ValueError('PPO_CHECKPOINT_METADATA_MISMATCH')
        # Construction must not perturb other algorithms' random streams.
        with torch.random.fork_rng(devices=[]):
            policy = PPOPolicy(len(FEATURES), MAX_ACTIONS, HIDDEN)
        policy.load_state_dict(checkpoint['policy_state'], strict=True)
        if (not all(torch.isfinite(p).all().item() for p in policy.parameters())
                or state_digest(policy.state_dict()) != record['training']['final_policy_sha256']):
            raise ValueError('PPO_INVALID_WEIGHTS')
        return policy.eval()
    except (KeyError, TypeError, RuntimeError, EOFError, pickle.UnpicklingError) as exc:
        raise ValueError('PPO_INCOMPATIBLE_CHECKPOINT') from exc


def read_artifact(model_id):
    if not isinstance(model_id, str) or not re.fullmatch(ID_PATTERN, model_id):
        raise ValueError('PPO_INVALID_MODEL_ID')
    root = model_root()
    directory = root / model_id
    if directory.is_symlink() or not directory.resolve().is_relative_to(root):
        raise ValueError('PPO_MODEL_PATH')
    manifest, weights = directory / 'manifest.json', directory / 'model.pt'
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 128 * 1024:
        raise ValueError('PPO_MODEL_NOT_REGISTERED')
    raw = manifest.read_bytes()
    record = json.loads(raw)
    expected = protocol_record()
    if (not isinstance(record, dict) or record.get('model_id') != model_id
            or any(record.get(k) != v for k, v in expected.items())
            or record.get('dependencies') != dependencies()
            or record.get('execution_mode') not in ('formal', 'planning_preview', 'physical_validation')
            or not isinstance(record.get('scene_domain'), dict)
            or set(record['scene_domain']) != {'scenario_physics_version', 'attitude_model_version', 'development_contract'}):
        raise ValueError('PPO_INCOMPATIBLE_MODEL')
    training = record.get('training', {})
    if (not isinstance(training, dict)
            or any(type(training.get(k)) is not int or training[k] <= 0 for k in ('episodes', 'steps', 'updates', 'accepted_assignments'))
            or not isinstance(training.get('scenarios'), list) or not training['scenarios']
            or any(not isinstance(s, dict) or not isinstance(s.get('sha256'), str)
                   or not re.fullmatch('[0-9a-f]{64}', s['sha256'])
                   for s in training['scenarios'])
            or any(not isinstance(training.get(k), str) or not re.fullmatch('[0-9a-f]{64}', training[k])
                   for k in ('initial_policy_sha256', 'final_policy_sha256', 'training_code_sha256_lf'))
            or training['initial_policy_sha256'] == training['final_policy_sha256']):
        raise ValueError('PPO_TRAINING_EVIDENCE_REQUIRED')
    if weights.is_symlink() or not weights.is_file() or not 0 < weights.stat().st_size <= MODEL_LIMIT:
        raise ValueError('PPO_MODEL_SIZE_OR_PATH')
    data = weights.read_bytes()
    if digest(data) != record.get('model_sha256'):
        raise ValueError('PPO_MODEL_SHA_MISMATCH')
    _decode(data, record)
    return record | {'manifest_sha256': digest(raw)}, data


def freeze(model_id):
    return read_artifact(model_id)[0]


def verify_snapshot(snapshot):
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('model_id'), str):
        raise ValueError('PPO_MODEL_SNAPSHOT_REQUIRED')
    current, data = read_artifact(snapshot['model_id'])
    if current != snapshot:
        raise ValueError('PPO_MODEL_CHANGED_AFTER_SUBMISSION')
    return data


def list_models():
    root = model_root()
    if not root.exists():
        return []
    items = []
    for directory in sorted(root.iterdir())[:100]:
        if directory.is_dir():
            try:
                record = freeze(directory.name)
                items.append({k: record[k] for k in ('model_id', 'model_version', 'model_sha256')})
            except (ValueError, OSError, KeyError, TypeError, metadata.PackageNotFoundError):
                continue
    return items


class FrozenPolicy:
    def __init__(self, snapshot):
        self.policy = _decode(verify_snapshot(snapshot), snapshot)

    def greedy(self, state, mask):
        import torch
        if len(state) != len(FEATURES) or len(mask) != MAX_ACTIONS or not mask.any():
            raise ValueError('PPO_OBSERVATION_MISMATCH')
        with torch.no_grad():
            logits, _ = self.policy(torch.as_tensor(state, dtype=torch.float32).unsqueeze(0))
            if not torch.isfinite(logits).all():
                raise ValueError('PPO_NONFINITE_PREDICTION')
            logits = self.policy.apply_action_mask(logits, torch.as_tensor(mask).unsqueeze(0))
            return int(logits.argmax(-1).item())
