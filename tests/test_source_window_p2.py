"""P2 public-interface regressions; synthetic inputs, never physical approval."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta, timezone
import json
from unittest.mock import patch

from eos_system.config import sha256_file
from eos_system.verification import verify_candidate
from schedulers.constraint_model import ConstraintModel, Schedule
from schedulers.scenario_loader import load_scheduling_problem_from_json
from schedulers.source_windows import SourceWindowIndex
from test_source_window_identity import I2Fixture
from utils.continuous_exposure import window_generation_record
from verify_schedules import verify


ZONES = (None, timezone.utc, timezone(timedelta(hours=8)), timezone(timedelta(hours=-5)))
TIME_FIELDS = ('sat_start_time', 'sat_end_time', 'gs_start_time', 'gs_end_time')


def in_zone(assignment, zone):
    return replace(assignment, **{
        key: value.replace(tzinfo=timezone.utc).astimezone(zone) if zone is not None else value
        for key in TIME_FIELDS if (value := getattr(assignment, key)) is not None})


class AssignmentUTCTests(I2Fixture):
    def test_direct_naive_utc_aware_utc_and_equivalent_offsets(self):
        _, original = self.candidate()
        cm = ConstraintModel(self.problem)
        for zone in ZONES:
            with self.subTest(zone=zone):
                a = in_zone(original, zone)
                before = deepcopy(a)
                self.assertTrue(cm.is_feasible_assignment(a, Schedule()))
                self.assertTrue(cm.check_discrete_assignment(a, Schedule()))
                self.assertEqual(vars(a), vars(before))
        mixed = replace(in_zone(original, timezone.utc), sat_end_time=original.sat_end_time)
        self.assertTrue(cm.is_feasible_assignment(mixed, Schedule()))
        self.assertTrue(cm.check_discrete_assignment(mixed, Schedule()))

    def test_nonzero_offset_is_converted_not_discarded(self):
        _, original = self.candidate()
        wrong_instant = replace(original,
            sat_start_time=original.sat_start_time.replace(tzinfo=ZONES[2]),
            sat_end_time=original.sat_end_time.replace(tzinfo=ZONES[2]))
        self.assertFalse(ConstraintModel(self.problem).is_feasible_assignment(wrong_instant, Schedule()))

    def test_source_endpoints_and_microsecond_outside_duration(self):
        _, original = self.candidate()
        cm = ConstraintModel(self.problem)
        for zone in ZONES:
            self.assertTrue(cm.is_feasible_assignment(in_zone(original, zone), Schedule()))
            for shift in (-1, 1):
                a = replace(original, sat_start_time=original.sat_start_time + timedelta(microseconds=shift),
                            sat_end_time=original.sat_end_time + timedelta(microseconds=shift))
                self.assertFalse(cm.is_feasible_assignment(in_zone(a, zone), Schedule()))
            for end in (original.sat_start_time, original.sat_start_time - timedelta(microseconds=1),
                        original.sat_end_time - timedelta(microseconds=1)):
                self.assertFalse(cm.is_feasible_assignment(in_zone(replace(original, sat_end_time=end), zone), Schedule()))

    def test_scenario_horizon_is_not_relaxed(self):
        _, a = self.candidate()
        for zone in ZONES:
            for start_shift, end_shift, expected in ((0, 0, True), (1, 0, False), (0, -1, False)):
                problem = replace(self.problem,
                    start_time=a.sat_start_time + timedelta(microseconds=start_shift),
                    end_time=a.sat_end_time + timedelta(microseconds=end_shift))
                self.assertEqual(ConstraintModel(problem).is_feasible_assignment(in_zone(a, zone), Schedule()), expected)

    def test_existing_grid_index_tolerance_is_preserved(self):
        _, a = self.candidate(window=0)
        for zone in ZONES:
            for shift, expected in ((0, True), (1, True), (2, False)):
                shifted = replace(a, sat_start_time=a.sat_start_time + timedelta(microseconds=shift),
                                  sat_end_time=a.sat_end_time + timedelta(microseconds=shift))
                self.assertEqual(ConstraintModel(self.problem).is_feasible_assignment(in_zone(shifted, zone), Schedule()), expected)

    def test_mixed_schedule_times_preserve_half_open_touch_and_overlap(self):
        _, a = self.candidate()
        task = self.problem.tasks[a.task_id]
        window = replace(task.windows[1], window_id=3, mission_id='N',
                         start_time=a.sat_end_time, end_time=a.sat_end_time + timedelta(seconds=10))
        problem = replace(self.problem, tasks={**self.problem.tasks, 'N': replace(task, id='N', windows=[window])})
        b = replace(a, task_id='N', sat_window_id=3, sat_start_time=window.start_time, sat_end_time=window.end_time)
        cm = ConstraintModel(problem, non_agile_transition_s=0)
        for incoming_zone, existing_zone in ((None, ZONES[2]), (ZONES[3], None), (timezone.utc, ZONES[2])):
            schedule = Schedule([in_zone(a, existing_zone)], metadata={'test': 'keep'})
            original_schedule = deepcopy(schedule)
            self.assertTrue(cm.is_feasible_assignment(in_zone(b, incoming_zone), schedule))
            self.assertTrue(cm.check_discrete_assignment(in_zone(b, incoming_zone), schedule))
            overlap = replace(b, sat_start_time=b.sat_start_time - timedelta(microseconds=1),
                              sat_end_time=b.sat_end_time - timedelta(microseconds=1))
            self.assertFalse(cm.is_feasible_assignment(in_zone(overlap, incoming_zone), schedule))
            self.assertFalse(cm.check_discrete_assignment(in_zone(overlap, incoming_zone), schedule))
            self.assertEqual(schedule, original_schedule)

    def test_downlink_offsets_boundaries_and_strictly_after(self):
        self.add_ground()
        _, a = self.candidate()
        cw = replace(self.problem.comm_windows[0], start_time=a.sat_end_time)
        problem = replace(self.problem, comm_windows=[cw])
        for zone in ZONES:
            self.assertTrue(ConstraintModel(problem).is_feasible_assignment(in_zone(a, zone), Schedule()))
            for shift, expected in ((0, False), (1, True)):
                start = a.sat_end_time + timedelta(microseconds=shift)
                trial = replace(a, gs_start_time=start, gs_end_time=start + timedelta(seconds=10))
                cm = ConstraintModel(problem)
                self.assertEqual(cm.is_feasible_assignment(in_zone(trial, zone), Schedule()), expected)
                self.assertEqual(cm.check_discrete_assignment(in_zone(trial, zone), Schedule()), expected)
            trial = replace(a, gs_start_time=cw.end_time - timedelta(seconds=10), gs_end_time=cw.end_time)
            self.assertTrue(ConstraintModel(problem).is_feasible_assignment(in_zone(trial, zone), Schedule()))
            self.assertFalse(ConstraintModel(problem).is_feasible_assignment(
                in_zone(replace(trial, gs_end_time=cw.end_time + timedelta(microseconds=1)), zone), Schedule()))

    def test_ground_station_conflict_with_other_satellite_and_mixed_zones(self):
        self.add_ground()
        _, a = self.candidate()
        task = self.problem.tasks[a.task_id]
        window = replace(task.windows[1], window_id=3, mission_id='N', satellite_id='OTHER')
        cw = replace(self.problem.comm_windows[0], window_id=2, satellite_id='OTHER')
        problem = replace(self.problem,
            satellites={**self.problem.satellites, 'OTHER': replace(self.problem.satellites[a.satellite_id], id='OTHER')},
            tasks={**self.problem.tasks, 'N': replace(task, id='N', windows=[window])},
            comm_windows=[*self.problem.comm_windows, cw])
        b = replace(a, task_id='N', satellite_id='OTHER', sat_window_id=3, gs_window_id=2)
        for zone in ZONES:
            schedule = Schedule([in_zone(a, ZONES[2])])
            cm = ConstraintModel(problem)
            self.assertFalse(cm.is_feasible_assignment(in_zone(b, zone), schedule))
            self.assertFalse(cm.check_discrete_assignment(in_zone(b, zone), schedule))
            touching = replace(b, gs_start_time=a.gs_end_time, gs_end_time=a.gs_end_time + timedelta(seconds=10))
            self.assertTrue(cm.is_feasible_assignment(in_zone(touching, zone), schedule))
            self.assertTrue(cm.check_discrete_assignment(in_zone(touching, zone), schedule))


class SourceStepTests(I2Fixture):
    def write_input(self, scene):
        self.path = self.next_path('step-scene.json')
        self.path.write_text(json.dumps(scene), encoding='utf-8')
        self.config = self.config.model_copy(update={'scenario_path': str(self.path),
            'scenario_id': self.path.stem, 'scenario_sha256': sha256_file(self.path)})

    @staticmethod
    def set_step(scene, scope, value):
        if scope == 'global':
            scene['metadata']['time_step'] = value
        elif scope == 'group':
            scene['observation_windows'][0]['time_step'] = value
        else:
            for window in scene['observation_windows'][0]['time_windows']:
                window['time_step'] = value

    def test_explicit_zero_rejected_at_each_configuration_level(self):
        plan, _ = self.candidate()
        for scope in ('global', 'group', 'window'):
            with self.subTest(scope=scope):
                scene = deepcopy(self.scene)
                self.set_step(scene, scope, 0)
                self.write_input(scene)
                self.reject_both(plan)

    def test_invalid_numeric_steps_rejected_by_both(self):
        plan, _ = self.candidate()
        for scope in ('global', 'group', 'window'):
            for step in (-1, float('nan'), float('inf'), -float('inf'), .0000001, .0000015, True, False):
                with self.subTest(scope=scope, step=step):
                    scene = deepcopy(self.scene)
                    self.set_step(scene, scope, step)
                    self.write_input(scene)
                    self.reject_both(plan)

    def test_invalid_step_cannot_be_recovered_by_legacy_matching(self):
        plan, _ = self.candidate()
        del plan['assignments'][0]['sat_window_id']
        scene = deepcopy(self.scene)
        self.set_step(scene, 'window', 0)
        self.write_input(scene)
        self.reject_both(plan)

    def test_missing_or_none_global_step_keeps_existing_default(self):
        plan, _ = self.candidate()
        for missing in (True, False):
            scene = deepcopy(self.scene)
            if missing:
                del scene['metadata']['time_step']
            else:
                scene['metadata']['time_step'] = None
            self.write_input(scene)
            self.assertEqual(load_scheduling_problem_from_json(self.path).tasks['M'].windows[1].time_step, 1)
            self.assertEqual(verify(self.path, self.plan_path(plan), emit=False), 1)
            self.formal(plan)

    def test_resolved_none_step_is_not_an_implicit_one_second(self):
        plan, a = self.candidate()
        self.problem.tasks['M'].windows[1].time_step = None
        cm = ConstraintModel(self.problem)
        self.assertFalse(cm.is_feasible_assignment(a, Schedule()))
        with self.assertRaises(ValueError):
            SourceWindowIndex(self.problem).restore(plan['assignments'][0], cm)

    def test_valid_fractional_and_integer_steps_still_pass_both(self):
        plan, _ = self.candidate()
        for step in (.5, 1, 2):
            scene = deepcopy(self.scene)
            scene['metadata']['time_step'] = step
            scene['metadata']['extra']['window_generation'] = window_generation_record(step, 5, 60)
            self.write_input(scene)
            self.assertEqual(verify(self.path, self.plan_path(plan), emit=False), 1)
            self.formal(plan)

    def test_malformed_resolved_step_rejected_without_certifier(self):
        plan, _ = self.candidate()
        for value in ('invalid', None):
            scene = deepcopy(self.scene)
            self.set_step(scene, 'window', value)
            self.write_input(scene)
            with patch('eos_system.verification.certify_schedule') as certifier:
                for fn in (lambda: verify_candidate(self.config, plan, .001),
                           lambda: verify(self.path, self.plan_path(plan), emit=False)):
                    with self.assertRaises((ValueError, TypeError)):
                        fn()
                certifier.assert_not_called()
