"""Train and register a NEW PPO ID: python -m algorithms.ppo.training --help.

No legacy weight import, automatic resume, overwrite or certification claim.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import random
import re

import numpy as np

from algorithms.ppo.model import (ID_PATTERN, dependencies, digest, freeze, model_root,
                                  protocol_record, state_digest)
from algorithms.ppo.protocol import (FEATURES, HIDDEN, MAX_ACTIONS,
                                     scene_domain, validate_constraints)


def train(model_id, scenarios, episodes=1000, seed=42, execution_mode='physical_validation'):
    import torch
    from algorithms.ppo.agent import PPOAgent, PPOConfig
    from algorithms.ppo.environment import SharedPPOEnv
    from algorithms.ppo.policy import PPOPolicy
    from eos_system.contracts import RunRequest
    from eos_system.provenance import capture_execution_provenance
    from eos_system.runner import build_constraint_model
    from schedulers.scenario_loader import load_scheduling_problem_from_json

    if (not re.fullmatch(ID_PATTERN, model_id) or type(episodes) is not int or episodes <= 0
            or not scenarios or execution_mode not in ('formal', 'planning_preview', 'physical_validation')):
        raise ValueError('PPO_INVALID_TRAINING_CONFIG')
    directory = model_root() / model_id
    if directory.exists() or directory.is_symlink():
        raise FileExistsError('PPO_MODEL_ID_ALREADY_EXISTS: choose a NEW ID')
    protocol, dependency_versions = protocol_record(), dependencies()
    root = Path(__file__).resolve().parents[2]

    def training_code_sha():
        return digest(b''.join((root / name).read_bytes().replace(b'\r\n', b'\n')
                               for name in ('algorithms/ppo/training.py', 'algorithms/ppo/agent.py')))

    training_identity = training_code_sha()
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    problems, sources, domains = [], [], []
    for path in sorted({Path(p).resolve() for p in scenarios}):
        payload = path.read_bytes()
        sha = digest(payload)
        provenance = capture_execution_provenance(path, sha, execution_mode)
        problem = load_scheduling_problem_from_json(path)
        request = RunRequest(scenario_id=path.stem, algorithm_id='ppo', execution_mode=execution_mode)
        constraints = build_constraint_model(problem, request)
        validate_constraints(problem, constraints, execution_mode)
        domains.append(scene_domain(json.loads(payload), provenance))
        sources.append(dict(path=str(path), sha256=sha, provenance=provenance))
        problems.append((problem, constraints))
    if any(domain != domains[0] for domain in domains):
        raise ValueError('PPO_MIXED_TRAINING_PHYSICS_DOMAINS')

    policy = PPOPolicy(len(FEATURES), MAX_ACTIONS, HIDDEN)
    initial = state_digest(policy.state_dict())
    cfg = PPOConfig()
    agent = PPOAgent(policy, cfg, device='cpu')
    updates = steps = accepted = 0
    returns = []
    for episode in range(episodes):
        problem, constraints = problems[episode % len(problems)]
        env = SharedPPOEnv()
        obs = env.reset(problem, constraints)
        rollout = {k: [] for k in ('state', 'mask', 'action', 'logp', 'value', 'reward', 'done')}
        total_reward = 0.0
        while not env.done:
            action, logp, value = agent.act(obs['state'], obs['action_mask'])
            following, reward, done, info = env.step(action)
            for key, val in dict(state=obs['state'], mask=obs['action_mask'], action=action,
                                 logp=logp, value=value, reward=reward, done=float(done)).items():
                rollout[key].append(val)
            steps += 1
            accepted += int(info['status'] == 'ok')
            total_reward += reward
            obs = following
        if rollout['action']:
            batch = {k: np.asarray(v, dtype=np.int64 if k == 'action' else np.float32)
                     for k, v in rollout.items()}
            batch['adv'], batch['ret'] = agent.compute_gae(batch['reward'], batch['value'], batch['done'], 0.0)
            stats = agent.update(batch)
            if not all(np.isfinite(v) for v in stats.values()):
                raise ValueError('PPO_NONFINITE_TRAINING: artifact not registered')
            updates += 1
        returns.append(total_reward)
        if (episode + 1) % 10 == 0 or episode + 1 == episodes:
            print(f'PPO episode={episode + 1}/{episodes} return={total_reward:.6f} updates={updates}', flush=True)

    final = state_digest(policy.state_dict())
    if (not updates or not accepted or initial == final
            or not all(torch.isfinite(p).all().item() for p in policy.parameters())):
        raise ValueError('PPO_NO_TRAINED_POLICY: no usable updates/assignments; artifact not registered')
    # Training inputs and provenance must still be the same bytes at publication.
    for source in sources:
        path = Path(source['path'])
        if (digest(path.read_bytes()) != source['sha256']
                or capture_execution_provenance(path, source['sha256'], execution_mode) != source['provenance']):
            raise ValueError('PPO_TRAINING_SOURCE_CHANGED')
    if (protocol_record() != protocol or dependencies() != dependency_versions
            or training_code_sha() != training_identity):
        raise ValueError('PPO_TRAINING_CODE_OR_DEPENDENCIES_CHANGED')
    training = dict(episodes=episodes, steps=steps, updates=updates, accepted_assignments=accepted,
                    seed=seed, scenarios=sources, initial_policy_sha256=initial,
                    final_policy_sha256=final, training_code_sha256_lf=training_identity,
                    ppo_config=asdict(cfg), return_summary=dict(first=returns[0], last=returns[-1],
                                                               mean=float(np.mean(returns))))
    checkpoint = dict(policy_state=policy.state_dict(), protocol=protocol, training=training,
                      execution_mode=execution_mode, scene_domain=domains[0])
    import io
    stream = io.BytesIO()
    torch.save(checkpoint, stream)
    data = stream.getvalue()
    record = protocol | dict(model_id=model_id, model_sha256=digest(data), dependencies=dependency_versions,
                              execution_mode=execution_mode, scene_domain=domains[0], training=training,
                              acceptance_status='trained_not_validated')
    # Exclusive creation; manifest is published last. Existing artifacts are never overwritten.
    directory.mkdir(parents=True, exist_ok=False)
    with (directory / 'model.pt').open('xb') as output:
        output.write(data)
    with (directory / 'manifest.json').open('x', encoding='utf-8') as output:
        json.dump(record, output, ensure_ascii=False, indent=2, allow_nan=False)
    snapshot = freeze(model_id)
    print(json.dumps(dict(model_id=model_id, model_sha256=snapshot['model_sha256'],
                          manifest_sha256=snapshot['manifest_sha256'], directory=str(directory),
                          acceptance_status='trained_not_validated'), ensure_ascii=False), flush=True)
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-id', required=True, help='New immutable model ID, e.g. ppo-v1')
    parser.add_argument('--scenarios', type=Path, nargs='+', required=True, help='Explicit TRAIN split JSON files only')
    parser.add_argument('--episodes', type=int, default=1000)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--execution-mode', choices=['formal', 'planning_preview', 'physical_validation'],
                        default='physical_validation')
    args = parser.parse_args()
    train(args.model_id, args.scenarios, args.episodes, args.seed, args.execution_mode)


if __name__ == '__main__':
    main()
