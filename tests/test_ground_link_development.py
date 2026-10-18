"""Real Orekit GS geometry/source/resource tests; no forged link or certificate."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('EOS_RUN_GEN02_PHYSICS')=='1','real Orekit opt-in')
class GroundLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utils.visibility import ensure_orekit
        from scripts.generate_caabs_development_scene import generate
        ensure_orekit(os.environ['EOS_OREKIT_DATA'])
        cls.temp=tempfile.TemporaryDirectory(prefix='caabs-ground-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root=Path(cls.temp.name)
        cls.generated=generate(cls.root/'scene',Path(__file__).resolve().parents[1]/'input/10_satellites.json',
            'ALOS-2_39766',os.environ['EOS_OREKIT_DATA'],with_ground_station=True)
        cls.path=Path(cls.generated['scenario'])

    def candidate(self):
        from scripts.validate_caabs_real_integration import make_config
        from eos_system.runner import calculate
        config=make_config(self.path)
        candidate,runtime=calculate(config)
        self.assertTrue(candidate['assignments'])
        return config,candidate,runtime

    def test_real_link_sources_and_independent_observation_and_downlink_replay(self):
        from eos_system.verification import verify_candidate
        from physical_reference_v2 import reference
        from utils.time_parsing import parse_orbit_epoch as utc
        config,plan,runtime=self.candidate()
        official,metrics,receipt=verify_candidate(config,plan,runtime)
        self.assertGreater(metrics['completed_tasks'],0)
        model=json.loads(self.path.read_bytes());sat=model['satellites'][0]
        station=model['ground_stations'][0]
        truth=reference(sat,station['location'])
        for a in official['assignments']:
            self.assertEqual(a['ground_station_id'],station['id'])
            self.assertIs(type(a['gs_window_id']),int)
            self.assertGreater(utc(a['gs_start_time']),utc(a['sat_end_time']))
            for i in range(201):
                self.assertGreater(truth(utc(a['gs_start_time'])+timedelta(seconds=i*.05))['elevation_deg'],5.)
        for row in receipt.evidence()['audit_summary']['rows']:
            self.assertEqual(row['downlink_audit']['sampled_boundaries_status'],'PASS')
            self.assertEqual(row['downlink_audit']['status'],'INCONCLUSIVE')
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.generated['scenario_sha256'])

    def test_downlink_owner_id_duration_and_strict_after_observation_negatives(self):
        from eos_system.verification import verify_candidate
        config,plan,runtime=self.candidate()
        for key,value in (('ground_station_id','not-owner'),('gs_window_id',99999),
                ('gs_start_time',plan['assignments'][0]['sat_end_time'])):
            changed=deepcopy(plan);changed['assignments'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):verify_candidate(config,changed,runtime)
        changed=deepcopy(plan);changed['assignments'][0]['gs_end_time']=changed['assignments'][0]['gs_start_time']
        with self.assertRaises(ValueError):verify_candidate(config,changed,runtime)

    def test_true_public_storage_and_power_limits_reject_real_assignment(self):
        from eos_system.runner import prepare
        from schedulers.source_windows import SourceWindowIndex
        from schedulers.constraint_model import Schedule
        config,plan,_=self.candidate()
        _,problem,cm,_=prepare(config)
        candidate=SourceWindowIndex(problem).restore(plan['assignments'][0],cm)
        self.assertTrue(cm.is_feasible_assignment(candidate,Schedule()))
        sat=problem.satellites[candidate.satellite_id]
        for field,cost in (('max_data_storage_GB',candidate.data_volume_GB),('max_power_W',candidate.power_cost_W)):
            old=getattr(sat,field)
            setattr(sat,field,cost/2)
            self.assertFalse(cm.is_feasible_assignment(candidate,Schedule()))
            setattr(sat,field,old)

    def test_communication_geometry_does_not_invent_camera_angles(self):
        from physical_reference_v2 import production_params
        from utils.visibility import create_communication_evaluator
        from utils.time_parsing import parse_orbit_epoch
        model=json.loads(self.path.read_bytes())
        params=production_params(model['satellites'][0],model['ground_stations'][0]['location'])
        for key in ('max_yaw_deg','max_pitch_deg','max_roll_deg','field_of_view_deg','maneuverability_type','max_tracking_rate_deg_s'):
            del params[key]
        evaluate=create_communication_evaluator(**params)
        point=evaluate(parse_orbit_epoch(model['metadata']['creation_time'])+timedelta(seconds=330))
        self.assertTrue(point['visible']);self.assertIsNone(point['yaw_deg'])
        self.assertNotIn('inertial_to_body_quaternion_xyzw',point)

    def test_real_downlink_physics_rejects_opposite_earth_station(self):
        from utils.continuous_exposure import PlanExposureAuditor
        config,plan,_=self.candidate()
        model=json.loads(self.path.read_bytes())  # Owned in-memory negative only.
        location=model['ground_stations'][0]['location']
        location['latitude']=-location['latitude']
        location['longitude']=(location['longitude']+360)%360-180
        auditor=PlanExposureAuditor(model,data_path=os.environ['EOS_OREKIT_DATA'],min_elevation_deg=5.)
        result=auditor.audit(plan)
        self.assertEqual(result['status'],'FAIL')
        self.assertTrue(all(r['reason'].startswith('DOWNLINK_NONVISIBLE') for r in result['rows']))
        self.assertTrue(all(r['sampled_boundaries_status']=='FAIL' for r in result['rows']))

    def test_two_individually_feasible_requests_cannot_share_ground_station(self):
        from dataclasses import replace
        from eos_system.runner import prepare
        from schedulers.constraint_model import Schedule
        config,_,_=self.candidate()
        _,problem,cm,_=prepare(config)
        tasks=sorted(problem.tasks.values(),key=lambda t:t.id)
        first=cm.build_feasible_assignment_for_task(tasks[0],Schedule())
        second=cm.build_feasible_assignment_for_task(tasks[1],Schedule())
        self.assertIsNotNone(first);self.assertIsNotNone(second)
        start=max(first.gs_start_time,second.gs_start_time)
        end=start+timedelta(seconds=10)
        first=replace(first,gs_start_time=start,gs_end_time=end)
        second=replace(second,gs_start_time=start,gs_end_time=end)
        self.assertTrue(cm.is_feasible_assignment(first,Schedule()))
        self.assertTrue(cm.is_feasible_assignment(second,Schedule()))
        self.assertLess(first.sat_end_time,second.sat_start_time)
        self.assertFalse(cm.is_feasible_assignment(second,Schedule([first])))

    def test_actual_formal_certificate_is_blocked_despite_positive_point_checks(self):
        from utils.continuous_exposure import certify_schedule,ContinuousCertificationError
        from scripts.audit_continuous_proof_readiness import audit
        config,plan,_=self.candidate()
        with self.assertRaisesRegex(ContinuousCertificationError,'NO_CONTINUITY_CERTIFICATE'):
            certify_schedule(self.path,plan,run_id=config.run_id,scenario_sha=config.scenario_sha256,
                             data_path=os.environ['EOS_OREKIT_DATA'])
        ready=audit(self.path,Path(os.environ['EOS_OREKIT_DATA']))
        self.assertEqual(ready['status'],'INCONCLUSIVE')
        self.assertFalse(ready['interval_provider_available'])
        self.assertIn('NO_COMMAND_SLEW_TRAJECTORY_AND_EXECUTION_ERROR_CONTRACT',ready['blockers'])

    def test_real_spawn_controller_ground_result_is_only_a_preview(self):
        with tempfile.TemporaryDirectory(prefix='caabs-ground-process-') as temp:
            result=subprocess.run([sys.executable,'-B','scripts/validate_ground_link_development.py',
                '--output',str(Path(temp)/'acceptance'),'--orekit-data',os.environ['EOS_OREKIT_DATA']],
                cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=180)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            evidence=json.loads((Path(temp)/'acceptance/acceptance.json').read_bytes())
            self.assertEqual(evidence['result_kind'],'planning_preview')
            self.assertGreater(evidence['runner_metrics']['completed_tasks'],0)
