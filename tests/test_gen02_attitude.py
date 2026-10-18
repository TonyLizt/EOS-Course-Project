"""Rigid fixed-camera model; pure tests and explicit real Orekit regressions."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
import os
from pathlib import Path
import unittest

from utils.attitude_frames import fixed_camera_in_fov, quaternion_distance_deg, relative_body_rotation


class FrameMathTests(unittest.TestCase):
    def test_agile_only_window_export_preserves_exact_quaternion_boundaries(self):
        from core.models import AgileData, TimeWindow
        from core.scenario import Scenario
        start = datetime(2025, 11, 18, 12)
        quaternions = [[0., 0., 0., 1.], [0., 0., .01, math.sqrt(1-.01**2)]]
        window = TimeWindow(start, start + timedelta(seconds=1),
                            AgileData([0.], [0.], [0.], quaternions), orbit_number=1)
        # The serializer does not need a populated Scenario for an explicit orbit.
        result = Scenario._time_window_to_dict(None, window)
        self.assertEqual(result["agile_data"]["boundary_quaternions_xyzw"], quaternions)
        self.assertNotIn("non_agile_data", result)

    def test_fixed_square_fov_front_boundary_and_back(self):
        edge = math.tan(math.radians(22.5))
        self.assertTrue(fixed_camera_in_fov((edge, edge, 1), 45))
        self.assertFalse(fixed_camera_in_fov((edge + 1e-6, 0, 1), 45))
        self.assertFalse(fixed_camera_in_fov((0, 0, -1), 45))
        self.assertFalse(fixed_camera_in_fov((math.nan, 0, 1), 45))

    def test_invalid_fov_not_silently_accepted(self):
        for value in (0, -1, 180, math.inf, math.nan, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                fixed_camera_in_fov((0, 0, 1), value)

    def test_quaternion_sign_and_shortest_arc(self):
        self.assertEqual(quaternion_distance_deg([0, 0, 0, 1], [0, 0, 0, -1]), 0)
        self.assertAlmostEqual(quaternion_distance_deg([0, 0, 0, 1], [1, 0, 0, 0]), 180)
        with self.assertRaises(ValueError):
            quaternion_distance_deg([0, 0, 0, 2], [0, 0, 0, 1])

    def test_real_public_model_requires_initial_attitude_and_slew_settle(self):
        # UNIT_TEST_ONLY in-memory source evidence; this is a real public-model
        # constraint test, not a physical provenance or certificate fixture.
        from schedulers.scenario_loader import SchedulingProblem, SchedulingSatellite, SchedulingTask, SensorSpec, TaskWindow
        from schedulers.constraint_model import ConstraintModel, Schedule
        start = datetime(2025, 11, 18, 12)
        q = [0, 0, 0, 1]
        window = TaskWindow(1, "S", "T", "camera", 1, start + timedelta(seconds=5),
            start + timedelta(seconds=30), agile_data={
                "pitch_angles": [0.] * 25, "yaw_angles": [0.] * 25, "roll_angles": [0.] * 25,
                "boundary_quaternions_xyzw": [q[:] for _ in range(26)]},
            planning_evidence={"trusted": True, "version": "visibility_exit_refined_v3",
                               "step_s": 1, "evidence_sha256": "UNIT_TEST_ONLY"})
        task = SchedulingTask("T", 1, 5, [window])
        sat = SchedulingSatellite("S", stabilization_time_s=10, sensors={"camera": SensorSpec("camera", 0, 0)})
        problem = SchedulingProblem("unit-only", start, start + timedelta(seconds=60), {"S": sat}, {}, {"T": task}, [])
        cm = ConstraintModel(problem)
        self.assertIsNone(cm.build_feasible_assignment_for_task(task, Schedule()))
        problem.initial_attitudes = {"S": {"time": start.isoformat(), "inertial_to_body_quaternion_xyzw": q}}
        self.assertIsNone(cm.build_feasible_assignment_for_task(task, Schedule()))  # earliest5 < settle10
        cm.placement_mode = "center"
        candidate = cm.build_feasible_assignment_for_task(task, Schedule())
        self.assertIsNotNone(candidate)
        self.assertEqual(len(candidate.sat_angles["boundary_quaternions_xyzw"]), 6)
        self.assertTrue(cm.is_feasible_assignment(candidate, Schedule()))
        bad = deepcopy(candidate)
        bad.sat_angles["boundary_quaternions_xyzw"][0] = [1, 0, 0, 0]
        self.assertFalse(cm.is_feasible_assignment(bad, Schedule()))


@unittest.skipUnless(os.environ.get("EOS_RUN_GEN02_PHYSICS") == "1", "real Orekit opt-in")
class RealFixedCameraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utils import visibility as v
        v.ensure_orekit(os.environ["EOS_OREKIT_DATA"])
        from org.orekit.attitudes import NadirPointing, TargetPointing
        from org.orekit.bodies import GeodeticPoint
        from org.orekit.propagation.analytical import KeplerianPropagator
        from org.hipparchus.geometry.euclidean.threed import RotationOrder, RotationConvention, Vector3D
        from orekit_jpype.pyhelpers import datetime_to_absolutedate
        cls.v, cls.ctx = v, v._CONTEXT
        cls.start = datetime(2025, 11, 18, 12, tzinfo=timezone.utc)
        cls.date = datetime_to_absolutedate(cls.start)
        cls.params = dict(a_m=7000000., e=.001, i_deg=98., raan_deg=20., argp_deg=0., m_deg=0.,
                          epoch_dt=cls.start, max_yaw_deg=45., max_pitch_deg=45., max_roll_deg=45.,
                          min_elevation_deg=5., field_of_view_deg=45., max_tracking_rate_deg_s=1.)
        cls.prop = KeplerianPropagator(v._build_keplerian_orbit(cls.ctx, 7000000., .001, 98., 20., 0., 0., cls.start))
        cls.pos = cls.prop.propagateOrbit(cls.date).getPVCoordinates(cls.ctx.inertial).getPosition()
        geo = cls.ctx.earth.transform(cls.pos, cls.ctx.inertial, cls.date)
        cls.lat, cls.lon = math.degrees(geo.getLatitude()), math.degrees(geo.getLongitude())
        cls.Nadir, cls.Target, cls.Geo = NadirPointing, TargetPointing, GeodeticPoint
        cls.Order, cls.Convention, cls.Vector = RotationOrder, RotationConvention, Vector3D

    def evaluator(self, offset=0, **changes):
        return self.v.create_visibility_evaluator(**(self.params | dict(target_lat_deg=self.lat,
             target_lon_deg=self.lon + offset, target_alt_m=0.) | changes))

    def test_nadir_absolute_angle_counterexample_now_visible(self):
        point = self.evaluator()(self.start)
        self.assertTrue(point["visible"])
        self.assertLess(max(abs(point[k]) for k in ("yaw_deg", "pitch_deg", "roll_deg")), 1e-8)
        rotation = self.Nadir(self.ctx.inertial, self.ctx.earth).getAttitude(self.prop, self.date, self.ctx.inertial).getRotation()
        absolute = rotation.getAngles(self.Order.ZYX, self.Convention.FRAME_TRANSFORM)
        self.assertGreater(max(abs(math.degrees(x)) for x in absolute), 45)

    def test_rotation_composition_matrix_and_independent_los(self):
        target = self.Geo(math.radians(self.lat), math.radians(self.lon + 1), 0.)
        rn = self.Nadir(self.ctx.inertial, self.ctx.earth).getAttitude(self.prop, self.date, self.ctx.inertial).getRotation()
        rt = self.Target(self.ctx.inertial, target, self.ctx.earth).getAttitude(self.prop, self.date, self.ctx.inertial).getRotation()
        actual = relative_body_rotation(rt, rn).getMatrix()
        a, b = rt.getMatrix(), rn.getMatrix()
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(actual[i][j], sum(a[i][k] * b[j][k] for k in range(3)), places=13)
        los = self.ctx.itrf.getTransformTo(self.ctx.inertial, self.date).transformPosition(self.ctx.earth.transform(target)).subtract(self.pos)
        self.assertLess(self.Vector.angle(rt.applyTo(los), self.Vector.PLUS_K), 1e-12)

    def test_agile_tracks_with_body_not_independent_camera(self):
        self.assertTrue(self.evaluator(4)(self.start)["visible"])
        fixed = self.evaluator(4, maneuverability_type="non_agile")(self.start)
        self.assertFalse(fixed["visible"])
        self.assertFalse(fixed["camera_visible"])

    def test_off_axis_limits_and_earth_occultation_still_reject(self):
        self.assertFalse(self.evaluator(10)(self.start)["visible"])
        opposite = self.evaluator(180)(self.start)
        self.assertFalse(opposite["visible"])
        self.assertLess(opposite["elevation_deg"], 0)

    def test_tracking_hardware_rate_not_ignored(self):
        self.assertFalse(self.evaluator(max_tracking_rate_deg_s=.00001)(self.start)["visible"])

    def test_utc_offset_equal_but_orbit_time_shift_not_equal(self):
        evaluate = self.evaluator()
        point = evaluate(self.start)
        offset = self.start.astimezone(timezone(timedelta(hours=8)))
        self.assertEqual(point["inertial_to_body_quaternion_xyzw"], evaluate(offset)["inertial_to_body_quaternion_xyzw"])
        self.assertNotEqual(point["inertial_to_body_quaternion_xyzw"], evaluate(self.start + timedelta(seconds=30))["inertial_to_body_quaternion_xyzw"])

    def test_actual_exposure_remains_uncertified_without_interval_proof(self):
        from utils.continuous_exposure import audit_interval
        result = audit_interval(self.evaluator(), self.start, self.start + timedelta(seconds=5), 5)
        self.assertEqual((result["status"], result["reason"]), ("INCONCLUSIVE", "NO_CONTINUITY_CERTIFICATE"))
        self.assertEqual(result["evaluations"], 101)

    def test_real_visible_start_does_not_hide_later_pointing_exit(self):
        from utils.continuous_exposure import audit_interval
        evaluate = self.evaluator()
        self.assertTrue(evaluate(self.start)["visible"])
        self.assertFalse(evaluate(self.start + timedelta(seconds=200))["visible"])
        result = audit_interval(evaluate, self.start, self.start + timedelta(seconds=200), 200)
        self.assertEqual((result["status"], result["reason"]), ("FAIL", "NONVISIBLE_EXPOSURE_POINT"))
        from utils.time_parsing import parse_orbit_epoch
        lower = parse_orbit_epoch(result["safe_exit_lower"])
        upper = parse_orbit_epoch(result["exit_upper"])
        self.assertLessEqual((upper - lower).total_seconds(), .000001)
        self.assertTrue(evaluate(lower)["visible"])
        self.assertFalse(evaluate(upper)["visible"])


if __name__ == "__main__":
    unittest.main()
