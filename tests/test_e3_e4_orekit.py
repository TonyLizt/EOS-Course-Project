"""Opt-in local Orekit regressions: no full scenario generation."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from utils.time_parsing import parse_orbit_epoch as utc

START=datetime(2025,11,18,12,tzinfo=timezone.utc)
SOURCE=Path("/home/meteor/eos-course-runtime/epoch-acceptance/s1-20s20m-1d-20261016/candidate/Scenario_S1_Sats20_M20_T1.0d_dist1_epoch_fixed_v1.json")
DATA_SHA="1c104cba89468a817d4d32ca8a12df7cab56f8d06a978ee736c841af123b7985"


@unittest.skipUnless(os.environ.get("EOS_RUN_E3_E4_OREKIT_TESTS")=="1",
                     "opt-in: EOS_RUN_E3_E4_OREKIT_TESTS=1")
class E3E4OrekitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from utils import visibility as v
        cls.v=v
        cls.data=Path(os.environ["EOS_OREKIT_DATA"])
        assert hashlib.sha256(cls.data.read_bytes()).hexdigest()==DATA_SHA
        assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()=="5e7a7702d60d194f403c30b157089243135b4287bef48b4114af5c83899addda"
        cls.source_sha=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
        cls.scene=json.loads(SOURCE.read_bytes())
        cls.sats={s["id"]:s for s in cls.scene["satellites"]}
        v.ensure_orekit(str(cls.data))
        from draw import orekit_to_czml
        cls.draw=orekit_to_czml
        from org.orekit.frames import FramesFactory
        from org.orekit.utils import IERSConventions,Constants
        from org.orekit.bodies import OneAxisEllipsoid
        cls.inertial=FramesFactory.getEME2000()
        cls.itrf=FramesFactory.getITRF(IERSConventions.IERS_2010,True)
        cls.earth=OneAxisEllipsoid(Constants.WGS84_EARTH_EQUATORIAL_RADIUS,Constants.WGS84_EARTH_FLATTENING,cls.itrf)

    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix="eos-e3-e4-orekit-")
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)

    @classmethod
    def tearDownClass(cls):
        assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==cls.source_sha
        assert hashlib.sha256(cls.data.read_bytes()).hexdigest()==DATA_SHA

    def reference(self,sid,geo=None):
        from org.orekit.orbits import KeplerianOrbit,PositionAngleType
        from org.orekit.utils import Constants
        from org.orekit.propagation.analytical import KeplerianPropagator
        from org.orekit.attitudes import TargetPointing
        from orekit_jpype.pyhelpers import datetime_to_absolutedate
        op=self.sats[sid]["orbital_params"]
        self.assertEqual(op["epoch"],"18 Nov 2025 12:00:00.000")
        orbit=KeplerianOrbit(op["semi_major_axis_km"]*1000,op["eccentricity"],
            math.radians(op["inclination_deg"]),math.radians(op["argument_of_perigee_deg"]),
            math.radians(op["right_ascension_of_ascending_node_deg"]),math.radians(op["mean_anomaly_deg"]),
            PositionAngleType.MEAN,self.inertial,datetime_to_absolutedate(START),Constants.WGS84_EARTH_MU)
        return KeplerianPropagator(orbit,TargetPointing(self.inertial,geo,self.earth)) if geo else KeplerianPropagator(orbit)

    @staticmethod
    def xyz(v):
        return [float(v.getX()),float(v.getY()),float(v.getZ())]

    def evidence(self,name,value):
        if os.environ.get("EOS_E3_E4_EVIDENCE_DIR"):
            path=Path(os.environ["EOS_E3_E4_EVIDENCE_DIR"])
            path.mkdir(parents=True,exist_ok=True)
            with (path/name).open("x",encoding="utf-8") as f:json.dump(value,f,ensure_ascii=False,indent=2)

    def test_fixed_eme2000_itrf_pv_and_aware_utc(self):
        from org.orekit.propagation.analytical import KeplerianPropagator
        from orekit_jpype.pyhelpers import datetime_to_absolutedate
        rows=[]
        for sid in ("ALOS-2_39766","GPM-CORE_39574","SCD_1_22490"):
            op=self.sats[sid]["orbital_params"]
            main=KeplerianPropagator(self.v._build_keplerian_orbit(self.v._CONTEXT,
                op["semi_major_axis_km"]*1000,op["eccentricity"],op["inclination_deg"],
                op["right_ascension_of_ascending_node_deg"],op["argument_of_perigee_deg"],
                op["mean_anomaly_deg"],utc(op["epoch"])))
            ref=self.reference(sid)
            for seconds in (0,43200,86400):
                moment=START+timedelta(seconds=seconds,microseconds=123456)
                date=datetime_to_absolutedate(moment)
                self.assertEqual(float(date.durationFrom(datetime_to_absolutedate(moment.astimezone(timezone(timedelta(hours=8)))))),0)
                for label,frame in (("EME2000",self.inertial),("ITRF",self.itrf)):
                    one,two=main.propagate(date).getPVCoordinates(frame),ref.propagate(date).getPVCoordinates(frame)
                    pe=math.dist(self.xyz(one.getPosition()),self.xyz(two.getPosition()))
                    ve=math.dist(self.xyz(one.getVelocity()),self.xyz(two.getVelocity()))
                    self.assertLessEqual(pe,1e-6);self.assertLessEqual(ve,1e-9)
                    rows.append(dict(satellite=sid,utc=moment.isoformat(),frame=label,position_error_m=pe,velocity_error_m_s=ve))
        self.evidence("pv.json",rows)

    def test_all_fractional_czml_knots_and_duration_endpoints(self):
        from org.orekit.bodies import GeodeticPoint
        from orekit_jpype.pyhelpers import datetime_to_absolutedate
        rows=[]
        for micros in (0,123456,500000,999999):
            for duration in (0,100,300,600,650,900):
                first=START.replace(microsecond=micros)
                fixture=deepcopy(self.scene)
                fixture["satellites"]=[self.sats[s] for s in ("ALOS-2_39766","GPM-CORE_39574","SCD_1_22490")]
                fixture["observation_windows"]=[];fixture["communication_windows"]=[]
                fixture["metadata"].update(creation_time=first.astimezone(timezone(timedelta(hours=8))).isoformat(),duration=duration,time_step=1)
                path=self.root/"fixture.json";target=self.root/"fixture.czml"
                path.write_text(json.dumps(fixture));original=path.read_bytes()
                with patch("builtins.print"):self.draw.demo(str(path),str(target),str(self.data),orbit_step_s=300)
                self.assertEqual(path.read_bytes(),original)
                doc=json.loads(target.read_bytes())
                self.assertEqual(list(map(utc,doc[0]["clock"]["interval"].split("/"))),[first,first+timedelta(seconds=duration)])
                self.assertEqual(utc(doc[0]["clock"]["currentTime"]),first)
                offsets=list(range(0,duration,300))+[duration]
                maximum=0
                for packet in doc:
                    if packet.get("id") not in self.sats:continue
                    position=packet["position"]
                    self.assertEqual(utc(position["epoch"]),first)
                    self.assertEqual(packet["availability"],doc[0]["clock"]["interval"])
                    self.assertEqual(position["cartographicDegrees"][::4],offsets)
                    prop=self.reference(packet["id"])
                    points=position["cartographicDegrees"]
                    for i in range(0,len(points),4):
                        offset,lon,lat,alt=points[i:i+4]
                        date=datetime_to_absolutedate(utc(position["epoch"])+timedelta(seconds=offset))
                        actual=self.earth.transform(GeodeticPoint(math.radians(lat),math.radians(lon),alt))
                        truth=prop.propagate(date).getPVCoordinates(self.itrf).getPosition()
                        error=math.dist(self.xyz(actual),self.xyz(truth))
                        self.assertLessEqual(error,1e-6)
                        maximum=max(maximum,error)
                rows.append(dict(microseconds=micros,duration_s=duration,offsets_s=offsets,max_position_error_m=maximum))
                if micros==123456 and duration==650:
                    self.evidence("browser-scene.json",fixture);self.evidence("browser-orbit.czml",doc)
        self.evidence("czml.json",rows)

    def test_gpm_relative_v2_boundaries_all_samples_and_recompute_serialization(self):
        from physical_reference_v2 import frozen, reference, production_params, exit_bracket
        from scripts.recompute_scenario_windows import recompute_data, static_data
        case=next(c for c in frozen()['cases'] if c['satellite']['id']=='GPM-CORE_39574')
        sat,loc=case['satellite'],case['location']
        start=utc(case['start']);oracle=reference(sat,loc)
        windows,samples,attitudes=self.v.compute_visibility_and_attitude(
            **production_params(sat,loc),start_dt=start,end_dt=start+timedelta(seconds=600),step_s=1)
        expected=[(utc(w['start']),utc(w['safe_exit'])) for w in case['windows']]
        self.assertEqual(windows,expected)
        self.assertEqual(len(samples),600)
        self.assertGreater(len(attitudes),10)  # no vacuous zero-window migration
        for sample in samples:
            truth=oracle(sample['time'])
            self.assertEqual(sample['visible'],truth['visible'])
            if sample['yaw_deg'] is not None:
                for axis in ('yaw_deg','pitch_deg','roll_deg'):
                    self.assertAlmostEqual(sample[axis],truth[axis],places=8)
        for w in case['windows']:
            lo,hi=utc(w['safe_exit']),utc(w['exit_upper'])
            self.assertEqual(exit_bracket(oracle,lo-timedelta(seconds=1),hi+timedelta(seconds=1)),(lo,hi))
            self.assertTrue(oracle(lo)['visible']);self.assertFalse(oracle(hi)['visible'])
        fixture=deepcopy(self.scene)
        fixture['satellites']=[sat]
        mission=deepcopy(fixture['missions'][0]);mission.update(id='GPM_RELATIVE_V2',target_location=loc)
        fixture['missions']=[mission];fixture['ground_stations']=[]
        fixture['observation_windows']=[];fixture['communication_windows']=[]
        fixture['metadata'].update(creation_time=start.isoformat(),duration=600,time_step=1)
        before=deepcopy(fixture)
        computed,_=recompute_data(fixture,data_path=str(self.data))
        self.assertEqual(fixture,before);self.assertEqual(static_data(computed),static_data(before))
        item=computed['observation_windows'][0]['time_windows'][0]
        self.assertEqual((utc(item['start_time']),utc(item['end_time'])),expected[0])
        self.assertEqual(len(item['agile_data']['boundary_quaternions_xyzw']),len(attitudes)+1)
        self.evidence('relative-v2-boundaries.json',case)

    def test_historical_absolute_gpm_roots_remain_versioned_negative_evidence(self):
        from physical_reference_v2 import frozen, reference, production_params, assert_point_close
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(),frozen()['original_scene_sha256'])
        for row in frozen()['historical']:
            with self.subTest(task=row['task_id']):
                oracle=reference(row['satellite'],row['location'])
                actual=oracle(row['time'])
                self.assertTrue(row['absolute']['visible'])
                self.assertFalse(actual['visible'])
                assert_point_close(self,actual,row['relative'])
                production=self.v.create_visibility_evaluator(**production_params(row['satellite'],row['location']))
                self.assertEqual(production(utc(row['time']))['visible'],actual['visible'])


if __name__=="__main__":
    unittest.main()
