"""Real point-model negatives discovered during continuous-proof audit."""
from copy import deepcopy
from datetime import timedelta
import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.environ.get('EOS_RUN_GEN02_PHYSICS')=='1','real Orekit opt-in')
class DeclaredPhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utils.visibility import ensure_orekit
        ensure_orekit(os.environ['EOS_OREKIT_DATA'])
        from physical_reference_v2 import frozen
        cls.case=frozen()['cases'][0]

    def scene(self):
        from utils.time_parsing import parse_orbit_epoch
        case=deepcopy(self.case)
        sat=case['satellite']
        sat['observation_capability']['sensors'][0]['min_elevation_angle_deg']=85.
        return dict(scenario_id='declared-physical-negative',
            metadata=dict(creation_time=case['start'],duration=600,time_step=1),satellites=[sat],
            missions=[dict(id='TARGET',priority=1,target_location=case['location'],
                observation_requirement=dict(duration_s=10,min_elevation_angle_deg=80.))],
            ground_stations=[],observation_windows=[],communication_windows=[])

    def test_underground_target_cannot_be_optically_visible(self):
        from physical_reference_v2 import production_params,reference
        from utils.visibility import create_visibility_evaluator
        from utils.time_parsing import parse_orbit_epoch
        case=self.case;loc=case['location']|dict(altitude_km=-1.)
        self.assertFalse(reference(case['satellite'],loc)(case['nadir_time'])['unoccluded'])
        point=create_visibility_evaluator(**production_params(case['satellite'],loc))(parse_orbit_epoch(case['nadir_time']))
        self.assertFalse(point['visible'])

    def test_generation_respects_sensor_and_task_minimum_not_only_global(self):
        from scripts.recompute_scenario_windows import recompute_data
        from physical_reference_v2 import reference
        from utils.time_parsing import parse_orbit_epoch
        scene=self.scene();before=deepcopy(scene)
        computed,_=recompute_data(scene,data_path=os.environ['EOS_OREKIT_DATA'])
        self.assertEqual(scene,before)
        oracle=reference(scene['satellites'][0],scene['missions'][0]['target_location'],minimum=85.)
        windows=computed['observation_windows']
        self.assertTrue(windows)
        for window in windows:
            for row in window['time_windows']:
                self.assertGreater(oracle(row['start_time'])['elevation_deg'],85.)
                self.assertGreater(oracle(row['end_time'])['elevation_deg'],85.)

    def test_independent_auditor_respects_same_declared_minimum(self):
        from utils.continuous_exposure import PlanExposureAuditor
        from utils.time_parsing import parse_orbit_epoch
        from physical_reference_v2 import reference
        scene=self.scene();sat,mission=scene['satellites'][0],scene['missions'][0]
        time=parse_orbit_epoch(self.case['nadir_time'])+timedelta(seconds=10)
        truth=reference(sat,mission['target_location'],minimum=85.)(time)
        self.assertFalse(truth['visible'])
        auditor=PlanExposureAuditor(scene,data_path=os.environ['EOS_OREKIT_DATA'],min_elevation_deg=5.)
        evaluate,_=auditor.evaluator(sat,mission)
        self.assertFalse(evaluate(time)['visible'])
