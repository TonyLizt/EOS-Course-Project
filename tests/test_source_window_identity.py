"""I2 public-interface regressions. Synthetic inputs; positive receipts are UNIT TEST ONLY."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from algorithms.candidate_pool import enumerate_task_candidates
from algorithms.conflict_beam import CAABSParams, ConflictBeamScheduler
from algorithms.objectives import ObjectiveWeights
from certification_fixtures import unit_certify
from eos_system.algorithm_registry import SolveContext, get_algorithm, make_context
from eos_system.config import sha256_file
from eos_system.contracts import RunConfig
from eos_system.exporting import render_json, render_csv
from eos_system.storage import Database
from eos_system.verification import verify_candidate
from schedulers.constraint_model import ConstraintModel, Schedule
from schedulers.scenario_loader import load_scheduling_problem_from_json
from schedulers.schedule_output import schedule_to_dict, save_schedule_to_json
from test_continuous_exposure import fixture, START
from utils.continuous_exposure import window_generation_record, ContinuousCertificationError, ExposureStatus
from verify_schedules import verify


class I2Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='i2-source-unit-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.serial = 0
        self.scene, _ = fixture(duration=10)
        self.scene['satellites'][0]['maneuverability_capability']['maneuverability_type'] = 'non_agile'
        wide = self.scene['observation_windows'][0]['time_windows'][0]
        wide.update(end_time=(START + timedelta(seconds=100)).isoformat(),
                    non_agile_data=dict(roll_angle=0, pitch_angle=0, yaw_angle=0))
        narrow = dict(wide, start_time=(START + timedelta(seconds=10)).isoformat(),
                      end_time=(START + timedelta(seconds=20)).isoformat())
        self.scene['observation_windows'][0]['time_windows'].append(narrow)
        self.load()

    def next_path(self, name):
        self.serial += 1
        return self.root / (str(self.serial) + '-' + name)

    def load(self, *, trust=True):
        self.path = self.next_path('scene.json')
        if trust:
            self.scene['metadata']['extra'] = {'window_generation': window_generation_record(1, 5, 60)}
        else:
            self.scene['metadata'].pop('extra', None)
        self.path.write_text(json.dumps(self.scene), encoding='utf-8')
        self.problem = load_scheduling_problem_from_json(self.path)
        self.config = RunConfig(run_id='i2-unit', scenario_id=self.path.stem, scenario_path=str(self.path),
            scenario_sha256=sha256_file(self.path), algorithm_id='completion_first',
            algorithm_version='baseline-1', created_at=START.isoformat())

    def candidate(self, window=1, comm=None):
        problem = self.problem if comm is None else replace(self.problem, comm_windows=[self.problem.comm_windows[comm]])
        cm = ConstraintModel(problem)
        task = self.problem.tasks['M']
        assignment = cm.build_feasible_assignment_for_task(replace(task, windows=[task.windows[window]]), Schedule())
        self.assertIsNotNone(assignment)
        return schedule_to_dict(Schedule([assignment]), self.problem), assignment

    def plan_path(self, plan):
        path = self.next_path('plan.json')
        path.write_text(json.dumps(plan), encoding='utf-8')
        return path

    def formal(self, plan):
        # Source/Loader/ConstraintModel are real. Only final physical certification
        # is injected, to test lifecycle without issuing a real certificate.
        with patch('eos_system.verification.certify_schedule', side_effect=unit_certify) as certify:
            result = verify_candidate(self.config, plan, .001)
            certify.assert_called_once()
            return result

    def reject_both(self, plan):
        with patch('eos_system.verification.certify_schedule', side_effect=unit_certify) as certify:
            with self.assertRaises(ValueError):
                verify_candidate(self.config, plan, .001)
            certify.assert_not_called()
        with self.assertRaises(ValueError):
            verify(self.path, self.plan_path(plan), emit=False)

    def add_ground(self, duplicate=False):
        self.scene['ground_stations'] = [dict(id='G'), dict(id='H')]
        cw = dict(satellite_id='S', ground_station_id='G', time_windows=[dict(
            start_time=(START + timedelta(seconds=30)).isoformat(),
            end_time=(START + timedelta(seconds=70)).isoformat())])
        self.scene['communication_windows'] = [cw]
        if duplicate:
            self.scene['communication_windows'].append(deepcopy(cw))
        self.load()


class ObservationIdentityTests(I2Fixture):
    def test_export_keeps_actual_narrow_window_and_formal_reconstruction(self):
        plan, assignment = self.candidate()
        self.assertEqual(assignment.sat_window_id, 2)
        self.assertEqual(plan['assignments'][0]['sat_window_id'], 2)
        official, _, receipt = self.formal(plan)
        self.assertEqual(official['assignments'][0]['sat_window_id'], 2)
        self.assertEqual(receipt.evidence()['evidence_kind'], 'UNIT_TEST_INJECTION_ONLY')
        self.assertEqual(verify(self.path, self.plan_path(plan), emit=False), 1)

    def test_unknown_explicit_id_rejected_by_both_public_verifiers(self):
        plan, _ = self.candidate()
        plan['assignments'][0]['sat_window_id'] = 999999
        self.reject_both(plan)

    def test_swapped_id_cannot_fall_back_to_time_match(self):
        plan, _ = self.candidate()
        plan['assignments'][0]['sat_window_id'] = 1
        self.reject_both(plan)

    def test_explicit_ids_have_strict_positive_integer_type(self):
        for value in (None, True, False, '2', 2.0, 0, -1):
            with self.subTest(value=value):
                plan, _ = self.candidate()
                plan['assignments'][0]['sat_window_id'] = value
                self.reject_both(plan)

    def test_same_time_different_id_requires_explicit_identity(self):
        windows = self.scene['observation_windows'][0]['time_windows']
        windows[0] = deepcopy(windows[1])
        self.load()
        plan, _ = self.candidate()
        self.formal(plan)
        del plan['assignments'][0]['sat_window_id']
        self.reject_both(plan)

    def test_same_time_id_swap_with_different_angles_is_rejected(self):
        windows = self.scene['observation_windows'][0]['time_windows']
        windows[0] = deepcopy(windows[1])
        windows[0]['non_agile_data'] = dict(roll_angle=20, pitch_angle=0, yaw_angle=0)
        self.load()
        plan, _ = self.candidate()
        plan['assignments'][0]['sat_window_id'] = 1
        self.reject_both(plan)

    def test_legacy_unique_full_semantics_select_narrow_source(self):
        plan, _ = self.candidate()
        plan['assignments'][0].pop('sat_window_id', None)
        official, _, _ = self.formal(plan)
        self.assertEqual(official['assignments'][0]['sat_window_id'], 2)

    def test_other_satellite_task_and_sensor_window_references_rejected(self):
        for field, other in (('satellite_id', 'OTHER_S'), ('mission_id', 'OTHER_M'), ('sensor_id', 'other-camera')):
            with self.subTest(field=field):
                scene = deepcopy(self.scene)
                ow = deepcopy(scene['observation_windows'][0])
                ow[field] = other
                if field == 'satellite_id':
                    sat = deepcopy(scene['satellites'][0]); sat['id'] = other
                    scene['satellites'].append(sat)
                elif field == 'mission_id':
                    mission = deepcopy(scene['missions'][0]); mission['id'] = other
                    scene['missions'].append(mission)
                else:
                    sensor = deepcopy(scene['satellites'][0]['observation_capability']['sensors'][0])
                    sensor['sensor_id'] = other
                    scene['satellites'][0]['observation_capability']['sensors'].append(sensor)
                scene['observation_windows'].append(ow)
                original = self.scene
                self.scene = scene; self.load()
                plan, _ = self.candidate()
                plan['assignments'][0]['sat_window_id'] = 4
                if field == 'mission_id':
                    plan['unassigned_tasks'] = [other]
                self.reject_both(plan)
                self.scene = original; self.load()

    def test_orbit_must_match_exact_source_without_numeric_coercion(self):
        for value in (2, 1.5, True, '1'):
            with self.subTest(value=value):
                plan, _ = self.candidate()
                plan['assignments'][0]['orbit_number'] = value
                self.reject_both(plan)

    def test_exposure_cannot_escape_source_by_one_microsecond(self):
        for shift in (-1, 1):
            with self.subTest(shift=shift):
                plan, _ = self.candidate()
                for field in ('sat_start_time', 'sat_end_time'):
                    value = datetime.fromisoformat(plan['assignments'][0][field])
                    plan['assignments'][0][field] = (value + timedelta(microseconds=shift)).isoformat()
                self.reject_both(plan)

    def test_source_grid_and_attitudes_are_checked(self):
        for key, value in (('sat_angles', {}), ('data_volume_GB', 100), ('power_cost_W', 10)):
            with self.subTest(key=key):
                plan, _ = self.candidate()
                plan['assignments'][0][key] = value
                self.reject_both(plan)
        # Inside the wide window, correct duration/angles but off its sample grid.
        plan, _ = self.candidate(window=0)
        for field in ('sat_start_time', 'sat_end_time'):
            # Preserve the existing 1e-6 sample-index tolerance; exceed it here.
            plan['assignments'][0][field] = (datetime.fromisoformat(plan['assignments'][0][field]) + timedelta(microseconds=2)).isoformat()
        self.reject_both(plan)

    def test_agile_angle_slice_can_uniquely_resolve_legacy_source(self):
        self.scene['satellites'][0]['maneuverability_capability']['maneuverability_type'] = 'agile'
        windows = self.scene['observation_windows'][0]['time_windows']
        windows[0]['agile_data'] = {axis + '_angles': [7] * 100 for axis in ('roll', 'pitch', 'yaw')}
        self.load()
        plan, _ = self.candidate()
        legacy = deepcopy(plan)
        legacy['assignments'][0].pop('sat_window_id', None)
        self.assertEqual(self.formal(legacy)[0]['assignments'][0]['sat_window_id'], 2)
        plan['assignments'][0]['sat_window_id'] = 1
        self.reject_both(plan)

    def test_utc_offset_equivalence_preserves_identity(self):
        plan, _ = self.candidate()
        for field, second in (('sat_start_time', 10), ('sat_end_time', 20)):
            plan['assignments'][0][field] = (START + timedelta(seconds=second)).astimezone(timezone(timedelta(hours=8))).isoformat()
        self.formal(plan)

    def test_missing_planning_provenance_remains_inconclusive(self):
        plan, _ = self.candidate()
        self.load(trust=False)
        with self.assertRaises(ContinuousCertificationError) as error:
            verify_candidate(self.config, plan, .001)
        self.assertIs(error.exception.status, ExposureStatus.INCONCLUSIVE)

    def test_same_ids_do_not_override_exported_scenario_sha(self):
        plan, _ = self.candidate()
        plan['provenance'] = dict(scenario_sha256='0' * 64)
        self.reject_both(plan)

    def test_duplicate_loaded_ids_are_invalid_not_first_match(self):
        from schedulers.source_windows import SourceWindowIndex
        self.problem.tasks['M'].windows[0].window_id = 2
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_SCENARIO_WINDOW_ID'):
            SourceWindowIndex(self.problem)

    def test_public_constraint_model_checks_source_center_and_orbit(self):
        _, a = self.candidate()
        cm = ConstraintModel(self.problem)
        self.assertFalse(cm.is_feasible_assignment(replace(a, sat_window_id=1), Schedule()))
        self.assertFalse(cm.is_feasible_assignment(replace(a, orbit_number=2), Schedule()))


class CommunicationIdentityTests(I2Fixture):
    def test_ground_source_is_retained_and_reconstructed(self):
        self.add_ground(duplicate=True)
        plan, a = self.candidate(comm=1)
        self.assertEqual(a.gs_window_id, 2)
        self.assertEqual(plan['assignments'][0]['gs_window_id'], 2)
        self.assertEqual(self.formal(plan)[0]['assignments'][0]['gs_window_id'], 2)

    def test_unknown_and_invalid_ground_ids_rejected(self):
        self.add_ground()
        for value in (999, None, True, '1', 1.0, 0):
            with self.subTest(value=value):
                plan, _ = self.candidate()
                plan['assignments'][0]['gs_window_id'] = value
                self.reject_both(plan)

    def test_ground_station_and_satellite_ownership_rejected(self):
        self.add_ground()
        for owner, value in (('ground_station_id', 'H'), ('satellite_id', 'OTHER')):
            with self.subTest(owner=owner):
                scene = deepcopy(self.scene)
                cw = deepcopy(scene['communication_windows'][0]); cw[owner] = value
                scene['communication_windows'].append(cw)
                if owner == 'satellite_id':
                    sat = deepcopy(scene['satellites'][0]); sat['id'] = value
                    scene['satellites'].append(sat)
                original = self.scene; self.scene = scene; self.load()
                plan, _ = self.candidate()
                plan['assignments'][0]['gs_window_id'] = 2
                self.reject_both(plan)
                self.scene = original; self.load()

    def test_downlink_must_be_contained_long_enough_and_strictly_after_exposure(self):
        self.add_ground()
        for start, end in ((29, 39), (65, 75), (30, 39), (20, 30)):
            with self.subTest(start=start, end=end):
                plan, _ = self.candidate()
                row = plan['assignments'][0]
                row['gs_start_time'] = (START + timedelta(seconds=start)).isoformat()
                row['gs_end_time'] = (START + timedelta(seconds=end)).isoformat()
                self.reject_both(plan)

    def test_legacy_ground_source_only_when_unique(self):
        self.add_ground()
        plan, _ = self.candidate()
        plan['assignments'][0].pop('gs_window_id', None)
        self.assertEqual(self.formal(plan)[0]['assignments'][0]['gs_window_id'], 1)
        self.add_ground(duplicate=True)
        plan, _ = self.candidate()
        plan['assignments'][0].pop('gs_window_id', None)
        self.reject_both(plan)

    def test_public_constraint_model_rejects_forged_ground_source(self):
        self.add_ground()
        _, a = self.candidate()
        self.assertFalse(ConstraintModel(self.problem).is_feasible_assignment(replace(a, gs_window_id=999), Schedule()))
        self.assertFalse(ConstraintModel(self.problem).is_feasible_assignment(replace(a, orbit_number=99), Schedule()))

    def test_no_ground_station_scene_rejects_injected_ground_identity(self):
        plan, _ = self.candidate()
        plan['assignments'][0]['gs_window_id'] = 1
        self.reject_both(plan)

    def test_duplicate_communication_ids_are_invalid(self):
        from schedulers.source_windows import SourceWindowIndex
        self.add_ground(duplicate=True)
        self.problem.comm_windows[1].window_id = 1
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_SCENARIO_WINDOW_ID'):
            SourceWindowIndex(self.problem)

    def test_formal_verifier_uses_trusted_configured_downlink_ratio(self):
        self.add_ground()
        plan, _ = self.candidate()
        row = plan['assignments'][0]
        row['gs_end_time'] = (START + timedelta(seconds=35)).isoformat()
        self.config = self.config.model_copy(update={'constraints': self.config.constraints.model_copy(
            update={'downlink_duration_ratio': .5})})
        self.formal(plan)
        self.config = self.config.model_copy(update={'constraints': self.config.constraints.model_copy(
            update={'downlink_duration_ratio': 1.0})})
        self.reject_both(plan)


class RoundTripAndAlgorithmTests(I2Fixture):
    def test_cli_json_export_import_round_trip_is_read_only(self):
        plan, a = self.candidate()
        path = self.next_path('export.json')
        save_schedule_to_json(Schedule([a]), self.problem, path)
        before = path.read_bytes(), self.path.read_bytes()
        imported = json.loads(path.read_bytes())
        self.assertEqual(verify(self.path, path, emit=False), 1)
        self.assertEqual(self.formal(imported)[0], plan)
        self.assertEqual((path.read_bytes(), self.path.read_bytes()), before)

    def test_formal_json_and_csv_exports_keep_both_source_ids(self):
        self.add_ground()
        plan, _ = self.candidate()
        official, metrics, receipt = self.formal(plan)
        db = Database(self.root / 'unit.sqlite3')
        db.enqueue(self.config, max_queued=1)
        attempt, _ = db.start_attempt(self.config.run_id)
        db.set_verifying(self.config.run_id, attempt)
        self.assertTrue(db.finish_success(self.config.run_id, attempt, official, metrics, .001, certification=receipt))
        record = db.get_run(self.config.run_id)
        exported = json.loads(render_json(record))
        reverified, _, _ = self.formal(exported)
        self.assertEqual(reverified, official)
        rows = list(csv.DictReader(io.StringIO(render_csv(record).decode('utf-8-sig'))))
        self.assertEqual((rows[0]['sat_window_id'], rows[0]['gs_window_id']), ('2', '1'))
        with db.connect() as connection:
            stored = json.loads(connection.execute('SELECT assignment_json FROM assignments').fetchone()[0])
        self.assertEqual((stored['sat_window_id'], stored['gs_window_id']), (2, 1))

    def test_multiple_actual_algorithms_emit_verifiable_source_identities(self):
        self.add_ground()
        weights = dict(w_profit=0, w_completion=1, w_timeliness=0, w_balance=0)
        cm = ConstraintModel(self.problem)
        for name in ('completion_first', 'adaptive_repair', 'caabs'):
            with self.subTest(algorithm=name):
                if name == 'caabs':
                    # I1 is intentionally not changed/required on this branch.
                    context = SolveContext(42, 2, ObjectiveWeights(**weights), CAABSParams(beam_width=2))
                    solver = ConflictBeamScheduler()
                else:
                    spec = get_algorithm(name)
                    context = make_context(42, 2, weights, spec, {'alns_iterations': 0} if name == 'adaptive_repair' else {})
                    solver = spec.build(context)
                schedule = solver.solve(self.problem, cm, context)
                self.assertTrue(schedule.assignments)
                plan = schedule_to_dict(schedule, self.problem)
                self.assertEqual(len(self.formal(plan)[0]['assignments']), len(schedule.assignments))
        self.assertTrue(enumerate_task_candidates(self.problem, self.problem.tasks['M'], seed=42))

    def test_loader_ids_are_snapshot_scoped_separate_ordinals(self):
        self.add_ground()
        self.scene['observation_windows'][0]['time_windows'][1]['window_id'] = 999
        self.load()
        self.assertEqual([w.window_id for w in self.problem.tasks['M'].windows], [1, 2])
        self.assertEqual(self.problem.comm_windows[0].window_id, 1)

    def test_new_source_validator_is_in_deployment_identity(self):
        from utils.certification_identity import SOURCE_NAMES
        self.assertIn('schedulers/source_windows.py', SOURCE_NAMES)


if __name__ == '__main__':
    unittest.main()
