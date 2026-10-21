"""PPO-only regression tests. Synthetic unit evidence is NOT physical acceptance.

Torch-dependent tests train a tiny fixture in a temporary runtime, never in the
real model registry. No existing model, dataset or evidence file is touched.
"""
from datetime import datetime, timedelta
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from algorithms.objectives import ObjectiveWeights
from algorithms.ppo.environment import SharedPPOEnv
from algorithms.ppo.protocol import (MAX_ACTIONS, PPOParams,
                                      validate_request, validate_scene)
from eos_system.contracts import RunRequest
from schedulers.constraint_model import ConstraintModel, Schedule
from schedulers.scenario_loader import (SchedulingProblem, SchedulingSatellite,
                                         SchedulingTask, SensorSpec, TaskWindow)


class SharedEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 1, 1)
        self.problem = SchedulingProblem('PPO_SYNTHETIC_UNIT_ONLY', self.start,
            self.start + timedelta(seconds=120),
            {'S1': SchedulingSatellite('S1', maneuverability_type='non_agile',
                                      sensors={'cam': SensorSpec('cam', 819.2, 1)})}, {}, {}, [])
        self.cm = ConstraintModel(self.problem)

    def task(self, tid, second, priority=1, evidence=True):
        self.problem.tasks[tid] = SchedulingTask(tid, priority, 10, [TaskWindow(
            len(self.problem.tasks) + 1, 'S1', tid, 'cam', 1,
            self.start + timedelta(seconds=second), self.start + timedelta(seconds=second + 10),
            non_agile_data={'roll_angle': 0, 'pitch_angle': 0, 'yaw_angle': 0},
            planning_evidence={'trusted': True, 'version': 'visibility_exit_refined_v3',
                'step_s': 1, 'evidence_sha256': 'PPO_SYNTHETIC_UNIT_ONLY'} if evidence else None)])

    def test_cached_mapping_dynamic_conflicts_and_state(self):
        self.task('A', 10, 3)
        self.task('B', 10, 2)
        self.task('C', 50, 1)
        from algorithms.candidate_pool import enumerate_task_candidates
        with patch('algorithms.ppo.environment.enumerate_task_candidates', wraps=enumerate_task_candidates) as generate:
            env = SharedPPOEnv()
            obs = env.reset(self.problem, self.cm)
            self.assertIs(env.cm, self.cm)
            self.assertEqual(obs['action_mask'].sum(), 2)
            original = env._candidates[1].assignment
            env.observation()
            self.assertEqual(generate.call_count, 1)
            obs, _, done, info = env.step(1)
            self.assertEqual(info['status'], 'ok')
            self.assertIs(env.schedule.assignments[0], original)
            self.assertFalse(done)
            self.assertGreater(obs['state'][3], 0)
            self.assertEqual(obs['action_mask'].sum(), 1)  # B overlaps A
            obs, _, _, _ = env.step(0)
            self.assertEqual(obs['action_mask'].sum(), 2)
            _, _, done, _ = env.step(1)
            self.assertTrue(done)
        replay = Schedule()
        for assignment in env.schedule.assignments:
            self.assertTrue(self.cm.is_feasible_assignment(assignment, replay))
            replay.assignments.append(assignment)
        self.assertEqual(env.schedule.assigned_task_ids, replay.assigned_task_ids)

    def test_public_per_orbit_capacity_masks_second_task(self):
        self.problem.satellites['S1'].max_data_storage_GB = 1.5
        self.task('A', 10, 2)
        self.task('B', 50, 1)
        env = SharedPPOEnv()
        env.reset(self.problem, self.cm)
        obs, _, _, _ = env.step(1)
        self.assertEqual(obs['action_mask'].sum(), 1)
        self.assertEqual(len(env.schedule.assignments), 1)

    def test_missing_public_window_evidence_and_no_candidates_are_safe(self):
        self.task('A', 10, evidence=False)
        env = SharedPPOEnv()
        obs = env.reset(self.problem, self.cm)
        self.assertEqual(obs['action_mask'].sum(), 1)
        _, _, done, info = env.step(0)
        self.assertTrue(done)
        self.assertEqual(info['status'], 'skip')
        self.assertEqual(env.schedule.assignments, [])

    def test_invalid_index_does_not_clip_to_assignment(self):
        for action in (-1, MAX_ACTIONS, 99999):
            self.task('A', 10)
            env = SharedPPOEnv()
            env.reset(self.problem, self.cm)
            _, _, done, info = env.step(action)
            self.assertTrue(done)
            self.assertEqual(info['status'], 'invalid_action')
            self.assertEqual(env.schedule.assignments, [])

    def test_stale_candidate_recheck_advances_without_insertion(self):
        self.task('A', 10)
        env = SharedPPOEnv()
        env.reset(self.problem, self.cm)
        with patch.object(self.cm, 'is_feasible_assignment', return_value=False):
            _, _, done, info = env.step(1)
        self.assertTrue(done)
        self.assertEqual(info['status'], 'infeasible')
        self.assertFalse(env.schedule.assignments)

    def test_post_action_replay_is_transactional(self):
        self.task('A', 10)
        env = SharedPPOEnv()
        env.reset(self.problem, self.cm)
        with patch.object(self.cm, 'is_feasible_assignment', side_effect=[True, False]):
            env.step(1)
        self.assertFalse(env.schedule.assignments)

    def test_empty_problem_is_terminal_with_skip_mask(self):
        env = SharedPPOEnv()
        obs = env.reset(self.problem, self.cm)
        self.assertTrue(env.done)
        self.assertEqual(obs['action_mask'].sum(), 1)
        self.assertTrue(np.isfinite(obs['state']).all())


class ProtocolTests(unittest.TestCase):
    def test_request_mismatch_is_rejected_without_mutation(self):
        from copy import deepcopy
        snapshot = {'execution_mode': 'physical_validation'}
        request = RunRequest(scenario_id='test', algorithm_id='ppo', execution_mode='physical_validation')
        validate_request(request, snapshot)
        for change in ({'placement_mode': 'center'}, {'execution_mode': 'formal'},
                       {'constraints': {'agility_profile': 'Low-Agility'}},
                       {'objective_weights': {'w_profit': 0, 'w_completion': 1}}):
            raw = request.model_dump() | change
            before = deepcopy(raw)
            with self.assertRaisesRegex(ValueError, 'PPO_'):
                validate_request(RunRequest(**raw), snapshot)
            self.assertEqual(raw, before)

    def test_physics_domain_mismatch_is_rejected(self):
        from algorithms.ppo.protocol import scene_domain
        snapshot = {'scene_domain': scene_domain({}, {'scenario_physics_version': 'training'})}
        with self.assertRaisesRegex(ValueError, 'PPO_SCENARIO_PHYSICS'):
            validate_scene({}, {'scenario_physics_version': 'other'}, snapshot)

    def test_no_model_remains_unavailable_and_no_arbitrary_path(self):
        from eos_system.algorithm_registry import availability, get_algorithm
        missing = Path(__file__).resolve().parent / 'PPO_TEST_NO_MODEL_NONEXISTENT'
        self.assertFalse(missing.exists())
        with patch.dict(os.environ, EOS_RUNTIME_DIR=str(missing)):
            self.assertEqual(availability('ppo')[0], 'unavailable')
        self.assertEqual(get_algorithm('ppo').params_model, PPOParams)
        for params in ({'model_path': '/tmp/untrusted.pt'}, {'model_id': '../untrusted'}):
            with self.assertRaises(ValueError):
                PPOParams(**params)


@unittest.skipUnless(importlib.util.find_spec('torch'), 'PyTorch not installed')
class TrainedArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from algorithms.ppo.training import train
        from rabas_integration_fixture import write_scene
        cls.temp = tempfile.TemporaryDirectory(prefix='ppo-SYNTHETIC-UNIT-ONLY-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.envpatch = patch.dict(os.environ, EOS_RUNTIME_DIR=str(cls.root / 'runtime'))
        cls.envpatch.start()
        cls.addClassCleanup(cls.envpatch.stop)
        cls.scene = cls.root / 'SYNTHETIC_UNIT_ONLY.json'
        write_scene(cls.scene)
        cls.snapshot = train('unit-trained', [cls.scene], episodes=4, execution_mode='formal')

    def config(self):
        from eos_system.config import sha256_file
        from eos_system.contracts import RunConfig
        from eos_system.provenance import capture_execution_provenance
        sha = sha256_file(self.scene)
        return RunConfig(scenario_id=self.scene.stem, scenario_path=str(self.scene), scenario_sha256=sha,
            algorithm_id='ppo', algorithm_params={'model_id': 'unit-trained'}, run_id='PPO_UNIT_ONLY',
            algorithm_version='ppo-shared-v1', created_at='2026-01-01T00:00:00Z',
            model_provenance=self.snapshot, scenario_provenance=capture_execution_provenance(self.scene, sha, 'formal'))

    def test_trained_artifact_runner_and_independent_verifier_SYNTHETIC_ONLY(self):
        from eos_system.runner import calculate
        from eos_system.verification import verify_candidate
        from certification_fixtures import unit_certify
        config = self.config()
        candidate, runtime = calculate(config)
        with patch('eos_system.verification.certify_schedule', side_effect=unit_certify):
            official, metrics, _ = verify_candidate(config, candidate, runtime)
        self.assertEqual(len(official['assignments']), metrics['completed_tasks'])

    def test_sha_protocol_snapshot_and_untrained_rejection(self):
        from algorithms.ppo.model import model_root, freeze, verify_snapshot
        directory = model_root() / 'unit-trained'
        weights, manifest = directory / 'model.pt', directory / 'manifest.json'
        data = weights.read_bytes()
        raw = manifest.read_bytes()
        try:
            weights.write_bytes(data + b'tampered')
            with self.assertRaisesRegex(ValueError, 'PPO_MODEL_SHA_MISMATCH'):
                freeze('unit-trained')
            weights.write_bytes(data)
            for key, value in (('features', ['wrong']), ('max_actions', 12),
                               ('objective_weights', {'w_completion': 1}),
                               ('domain', {}), ('dependencies', {}),
                               ('model_version', 'legacy'), ('inference_code_sha256_lf', '0' * 64)):
                record = json.loads(raw)
                record[key] = value
                manifest.write_text(json.dumps(record), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'PPO_INCOMPATIBLE_MODEL'):
                    freeze('unit-trained')
            record = json.loads(raw)
            record['training']['updates'] = 0
            manifest.write_text(json.dumps(record), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'PPO_TRAINING_EVIDENCE_REQUIRED'):
                freeze('unit-trained')
            manifest.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, 'PPO_MODEL_CHANGED_AFTER_SUBMISSION'):
                verify_snapshot(self.snapshot | {'manifest_sha256': '0' * 64})
            import io
            import torch
            from algorithms.ppo.model import digest
            stream = io.BytesIO()
            torch.save({'legacy_untrained_state_dict': torch.zeros(1)}, stream)
            legacy = stream.getvalue()
            record = json.loads(raw)
            record['model_sha256'] = digest(legacy)
            weights.write_bytes(legacy)
            manifest.write_text(json.dumps(record), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'PPO_INCOMPATIBLE_CHECKPOINT'):
                freeze('unit-trained')
        finally:
            weights.write_bytes(data)
            manifest.write_bytes(raw)

    def test_no_overwrite_and_single_sample_update_is_finite(self):
        from algorithms.ppo.training import train
        with self.assertRaises(FileExistsError):
            train('unit-trained', [self.scene], 1, execution_mode='formal')
        from algorithms.ppo.agent import PPOAgent, PPOConfig
        from algorithms.ppo.policy import PPOPolicy
        agent = PPOAgent(PPOPolicy(5, MAX_ACTIONS), PPOConfig())
        state, mask = np.zeros(5, dtype=np.float32), np.ones(MAX_ACTIONS, dtype=np.float32)
        action, logp, _ = agent.act(state, mask)
        stats = agent.update(dict(state=state[None], mask=mask[None], action=np.array([action]),
                                  logp=np.array([logp]), adv=np.array([1.]), ret=np.array([1.])))
        self.assertTrue(all(np.isfinite(v) for v in stats.values()))


if __name__ == '__main__':
    unittest.main()
