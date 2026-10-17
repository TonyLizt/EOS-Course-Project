"""Exposure regressions. Historical roots are local fixtures, not universal constants.

Reference: s2-20s20m-grid-v2-lazy-20261016/independent-e3-20261016/
continuous_duration_probe_report.json, SHA
 a1629ddaf3ab7fb730ccf38fdc6c169f67089ebcdb4cb9d13bd15fe1158a7026.
Each historical exit bracket is one microsecond wide.
"""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from functools import partial
import json
import os
from pathlib import Path
import tempfile
import unittest

from utils.time_parsing import parse_orbit_epoch as utc
from utils.visibility import _scan_visibility_grid,_build_time_windows_from_visible_attitudes,_refine_visibility_exit
from utils.continuous_exposure import PlanExposureAuditor,audit_interval,exposure_times
from verify_schedules import verify,verify_continuous

START=utc("2025-11-18T12:00:00Z")
CASES=(("M001","SKYSAT-C2_41773","2025-11-18T15:06:44Z",11,"2025-11-18T15:06:54.513645Z"),
       ("M007","SCD_1_22490","2025-11-19T04:46:29Z",13,"2025-11-19T04:46:41.801176Z"))


def predicate(test):
    def evaluate(t):
        return dict(time=t,visible=test(t),elevation_deg=20,off_nadir_deg=0,
                    yaw_deg=0,pitch_deg=0,roll_deg=0)
    return evaluate


def fixture(mid="M",sid="S",start=START,duration=2):
    end=start+timedelta(seconds=duration)
    ad={a+"_angles":[0]*int(duration) for a in ("yaw","pitch","roll")}
    scene=dict(scenario_id="fixture",metadata=dict(creation_time=START.isoformat(),duration=86400,time_step=1),
        satellites=[dict(id=sid,orbital_params=dict(semi_major_axis_km=7000,eccentricity=.001,
            inclination_deg=60,right_ascension_of_ascending_node_deg=10,argument_of_perigee_deg=20,
            mean_anomaly_deg=30,epoch="18 Nov 2025 12:00:00.000"),
            maneuverability_capability=dict(maneuverability_type="agile",max_yaw_angle_deg=45,
                max_pitch_angle_deg=45,max_roll_angle_deg=45),
            observation_capability=dict(sensors=[dict(sensor_id="camera",data_rate_Mbps=0,power_consumption_W=0)]))],
        missions=[dict(id=mid,priority=1,target_location=dict(latitude=0,longitude=0,altitude_km=0),
                       observation_requirement=dict(duration_s=duration))],ground_stations=[],
        observation_windows=[dict(satellite_id=sid,mission_id=mid,sensor_id="camera",time_windows=[dict(
            start_time=start.isoformat(),end_time=end.isoformat(),orbit_number=1,agile_data=ad)])],communication_windows=[])
    assignment=dict(task_id=mid,satellite_id=sid,sensor_id="camera",orbit_number=1,
                    sat_start_time=start.isoformat(),sat_end_time=end.isoformat(),
                    data_volume_GB=0,power_cost_W=0,sat_angles=ad)
    plan=dict(scenario_id="fixture",start_time=START.isoformat(),end_time=(START+timedelta(days=1)).isoformat(),
              assignments=[assignment],unassigned_tasks=[])
    return scene,plan


class ExposureTests(unittest.TestCase):
    def public(self,scene,plan,factory):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/"scene.json";target=Path(d)/"plan.json"
            source.write_text(json.dumps(scene));target.write_text(json.dumps(plan))
            original=(source.read_bytes(),target.read_bytes())
            # Actually exercise the serialized public verifier, not just a helper.
            result=verify_continuous(source,target,min_elevation_deg=5,step_s=.05,
                auditor_factory=partial(PlanExposureAuditor,evaluator_factory=factory))
            self.assertEqual((source.read_bytes(),target.read_bytes()),original)
            return result

    def test_two_historical_overruns_rejected_by_public_gate(self):
        for mid,sid,time,duration,root in CASES:
            with self.subTest(task=mid):
                start,lower=utc(time),utc(root);scene,plan=fixture(mid,sid,start,duration)
                def factory(**params):return predicate(lambda t:t<lower+timedelta(microseconds=1))
                result=self.public(scene,plan,factory)
                self.assertEqual(result["discrete_status"],"PASS")
                self.assertEqual(result["status"],"FAIL")
                row=result["rows"][0];self.assertEqual(row["boundary_precision_us"],1)
                self.assertLessEqual(abs((utc(row["safe_exit_lower"])-lower).total_seconds()),.000001)
                self.assertGreater(row["overrun_lower_s"],.19)
                windows,_,_=_scan_visibility_grid(start,start+timedelta(seconds=duration+1),1,factory())
                self.assertLess(windows[0][1]-start,timedelta(seconds=duration))

    def test_legal_exposure_and_visible_safe_endpoint_public_pass(self):
        scene,plan=fixture()
        def factory(**params):
            result=predicate(lambda t:START<=t<=START+timedelta(seconds=2))
            # Trusted analytic fixture: the predicate above is TRUE throughout
            # each closed interval inside these bounds. Never read from JSON.
            result.certify_interval=lambda a,b:START<=a<=b<=START+timedelta(seconds=2)
            return result
        result=self.public(scene,plan,factory)
        self.assertEqual(result["status"],"PASS")
        self.assertEqual(result["rows"][0]["reason"],"CERTIFIED_INTERVAL")

    def test_all_visible_points_without_certificate_are_inconclusive(self):
        scene,plan=fixture();result=self.public(scene,plan,lambda **kw:predicate(lambda t:True))
        self.assertEqual(result["status"],"INCONCLUSIVE")
        self.assertEqual(result["rows"][0]["sampled_boundaries_status"],"PASS")

    def test_hidden_gap_is_not_falsely_certified(self):
        scene,plan=fixture();result=self.public(scene,plan,lambda **kw:predicate(
            lambda t:not START+timedelta(seconds=.011)<t<START+timedelta(seconds=.012)))
        self.assertEqual(result["status"],"INCONCLUSIVE")

    def test_horizon_is_evaluated_and_refined_without_extra_grid_samples(self):
        evaluate=predicate(lambda t:t<START+timedelta(seconds=2.125001));calls=[]
        def counted(t):calls.append(t);return evaluate(t)
        windows,samples,poses=_scan_visibility_grid(START,START+timedelta(seconds=2.5),1,counted)
        self.assertEqual(windows,[(START,START+timedelta(seconds=2.125))])
        self.assertIn(START+timedelta(seconds=2.5),calls)
        self.assertEqual([s["time"] for s in samples],[START+timedelta(seconds=i) for i in range(3)])
        self.assertEqual([s["time"] for s in poses],[s["time"] for s in samples])

    def test_steps_subsecond_exits_and_half_open_pose_slicing(self):
        for step in (.1,.5,1,2):
            with self.subTest(step=step):
                cutoff=START+timedelta(seconds=3.123457)
                windows,samples,poses=_scan_visibility_grid(START,START+timedelta(seconds=8),step,
                                                          predicate(lambda t:t<cutoff))
                self.assertEqual(windows[0][1],cutoff-timedelta(microseconds=1))
                model=_build_time_windows_from_visible_attitudes(windows,poses,scenario_start_dt=START,orbit_period_s=6000)
                self.assertEqual(len(model[0].agile_data.yaw_angles),sum(s["time"]<windows[0][1] for s in poses))
                self.assertTrue(all(s["time"]<START+timedelta(seconds=8) for s in samples))

    def test_refined_endpoint_grid_pose_is_not_exported(self):
        cutoff=START+timedelta(seconds=3,microseconds=1)
        windows,samples,poses=_scan_visibility_grid(START,START+timedelta(seconds=5),1,
                                                  predicate(lambda t:t<cutoff))
        self.assertEqual(windows,[(START,START+timedelta(seconds=3))])
        self.assertEqual(len(poses),4)  # original grid is preserved
        model=_build_time_windows_from_visible_attitudes(windows,poses,
                            scenario_start_dt=START,orbit_period_s=6000)
        self.assertEqual(len(model[0].agile_data.yaw_angles),3)  # endpoint excluded

    def test_json_cannot_claim_a_continuity_certificate(self):
        scene,plan=fixture();scene['continuous_verified']=True
        plan['continuity_certificate']=True
        self.assertEqual(self.public(scene,plan,lambda **kw:predicate(lambda t:True))['status'],'INCONCLUSIVE')

    def test_refinement_rejects_unbracketed_inputs_and_terminates_at_one_us(self):
        evaluate=predicate(lambda t:t==START)
        with self.assertRaises(ValueError):_refine_visibility_exit(START,START+timedelta(seconds=1),predicate(lambda t:True))
        for precision in (0,True,1.5):
            with self.assertRaises(ValueError):_refine_visibility_exit(START,START+timedelta(seconds=1),evaluate,precision_us=precision)
        self.assertEqual(_refine_visibility_exit(START,START+timedelta(microseconds=1),evaluate),
                         (START,START+timedelta(microseconds=1)))
        self.assertEqual(_scan_visibility_grid(START,START+timedelta(microseconds=1),.000001,evaluate)[0],[])

    def test_bad_duration_times_and_one_us_short_rejected_publicly(self):
        scene,plan=fixture()
        for start,end in ((START-timedelta(microseconds=1),START+timedelta(seconds=2)),
                          (START,START+timedelta(seconds=2,microseconds=1)),
                          (START,START+timedelta(seconds=2,microseconds=-1)),(START,START),
                          (START+timedelta(seconds=3),START),("bad",START),(None,START)):
            with self.subTest(start=start,end=end):
                altered=deepcopy(plan);a=altered["assignments"][0]
                a["sat_start_time"]=start.isoformat() if isinstance(start,datetime) else start
                a["sat_end_time"]=end.isoformat() if isinstance(end,datetime) else end
                self.assertEqual(self.public(scene,altered,lambda **kw:predicate(lambda t:True))["status"],"FAIL")

    def test_equivalent_utc_and_microseconds(self):
        start=START.replace(microsecond=123456)
        for value in (start,start.replace(tzinfo=None),start.astimezone(timezone(timedelta(hours=8))),
                      start.isoformat().replace('+00:00','Z')):
            one,two=exposure_times(value,start+timedelta(microseconds=1),.000001)
            self.assertEqual(one,start);self.assertEqual(two-one,timedelta(microseconds=1))
        with self.assertRaises(ValueError):exposure_times("2025-11-18T12:00:00+25:00",START,1)
        with self.assertRaises(ValueError):exposure_times(START,START+timedelta(microseconds=1),.0000001)
        scene,plan=fixture();plan['assignments'][0]['sat_start_time']='2025-11-18T20:00:00+08:00'
        self.assertEqual(self.public(scene,plan,lambda **kw:predicate(lambda t:True))['status'],'INCONCLUSIVE')

    def test_missing_physics_and_evaluator_budget_are_not_pass(self):
        scene,plan=fixture();del scene["satellites"][0]["orbital_params"]["epoch"]
        result=self.public(scene,plan,lambda **kw:predicate(lambda t:True))
        self.assertEqual(result["status"],"INCONCLUSIVE")
        scene,plan=fixture();auditor=PlanExposureAuditor(scene,min_elevation_deg=5,max_evaluations=1,
                                                   evaluator_factory=lambda **kw:predicate(lambda t:True))
        self.assertEqual(auditor.audit(plan)["status"],"INCONCLUSIVE")

    def test_cache_is_bounded_and_does_not_alias_nearby_orbits_or_targets(self):
        from utils.visibility import _orbit_cache_key
        self.assertNotEqual(_orbit_cache_key(7000000,.001,60,0,0,0,'epoch'),
                            _orbit_cache_key(7000000.00001,.001,60,0,0,0,'epoch'))
        scene,plan=fixture();seen=[]
        def factory(**kw):seen.append(kw);return predicate(lambda t:True)
        auditor=PlanExposureAuditor(scene,min_elevation_deg=5,evaluator_factory=factory,max_pairs=1)
        auditor.audit(plan);auditor.audit(plan);self.assertEqual(len(seen),1)
        altered=deepcopy(scene);altered['satellites'][0]['orbital_params']['mean_anomaly_deg']+=.0000001
        other=PlanExposureAuditor(altered,min_elevation_deg=5,evaluator_factory=factory,max_pairs=1)
        other.audit(plan);self.assertEqual(len(seen),2)
        self.assertNotEqual(seen[0]['m_deg'],seen[1]['m_deg']);self.assertLessEqual(len(other.pairs),1)

    def test_separate_windows_cannot_be_spanned(self):
        scene,plan=fixture(duration=4);tw=scene['observation_windows'][0]['time_windows'][0]
        second=deepcopy(tw);tw['end_time']=(START+timedelta(seconds=2)).isoformat()
        second['start_time']=(START+timedelta(seconds=3)).isoformat();second['end_time']=(START+timedelta(seconds=5)).isoformat()
        scene['observation_windows'][0]['time_windows'].append(second)
        self.assertEqual(self.public(scene,plan,lambda **kw:predicate(lambda t:True))['status'],'FAIL')


@unittest.skipUnless(os.environ.get('EOS_RUN_EXPOSURE_OREKIT_TESTS')=='1','opt-in real Orekit exposure cases')
class RealExposureTests(unittest.TestCase):
    def test_frozen_public_verifier_probes_against_rebuilt_orekit(self):
        base=Path('/home/meteor/eos-course-runtime/epoch-acceptance/s2-20s20m-grid-v2-lazy-20261016')
        folder=base/'independent-e3-20261016'
        config=json.loads((folder/'scheduling/config.json').read_bytes())
        for i,case in enumerate(CASES,1):
            with self.subTest(case=i):
                result=verify_continuous(config['scenario_path'],folder/f'continuous_duration_probes/{i}_public_verified_plan.json',
                    data_path=os.environ['EOS_OREKIT_DATA'],min_elevation_deg=5)
                self.assertEqual(result['status'],'FAIL');row=result['rows'][0]
                self.assertEqual(row['reason'],'NONVISIBLE_EXPOSURE_POINT')
                self.assertLessEqual(abs((utc(row['safe_exit_lower'])-utc(case[4])).total_seconds()),.000002)
                self.assertLessEqual((utc(row['exit_upper'])-utc(row['safe_exit_lower'])).total_seconds(),.000001)
