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

    def test_gpm_boundaries_all_samples_and_recompute_serialization(self):
        from org.orekit.frames import TopocentricFrame
        from org.orekit.bodies import GeodeticPoint
        from org.hipparchus.geometry.euclidean.threed import RotationOrder,RotationConvention
        from orekit_jpype.pyhelpers import datetime_to_absolutedate
        from scripts.recompute_scenario_windows import recompute_data,static_data,calculator_inputs
        results=[]
        for mid,creation,expected_first,expected_end,n in (
            ("M009","2025-11-18T13:11:00Z","2025-11-18T13:13:33Z","2025-11-18T13:14:32Z",59),
            ("M020","2025-11-19T09:21:00Z","2025-11-19T09:23:10Z","2025-11-19T09:24:16Z",66)):
            fixture=deepcopy(self.scene)
            fixture["satellites"]=[self.sats["GPM-CORE_39574"]]
            fixture["missions"]=[next(m for m in fixture["missions"] if m["id"]==mid)]
            fixture["observation_windows"]=[];fixture["communication_windows"]=[];fixture["ground_stations"]=[]
            fixture["metadata"].update(creation_time=creation,duration=600,time_step=1)
            original=deepcopy(fixture);start=utc(creation)
            target=fixture["missions"][0]["target_location"]
            geo=GeodeticPoint(math.radians(target["latitude"]),math.radians(target["longitude"]),float(target.get("altitude_km",0))*1000)
            topo=TopocentricFrame(self.earth,geo,"INDEPENDENT")
            prop=self.reference("GPM-CORE_39574",geo)
            def reference(moment):
                date=datetime_to_absolutedate(moment);state=prop.propagate(date)
                elevation=float(topo.getElevation(state.getPVCoordinates(self.inertial).getPosition(),self.inertial,date))
                angles=[math.degrees(float(a)) for a in state.getAttitude().getRotation().getAngles(RotationOrder.ZYX,RotationConvention.FRAME_TRANSFORM)]
                return elevation>math.radians(5) and all(abs(a)<=45 for a in angles),angles
            inputs=calculator_inputs(fixture);op=inputs["satellites"][0].orbital_params
            windows,samples,attitudes=self.v.compute_visibility_and_attitude(a_m=op.semi_major_axis*1000,e=op.eccentricity,
                i_deg=op.inclination,raan_deg=op.right_ascension_of_ascending_node,argp_deg=op.argument_of_perigee,
                m_deg=op.mean_anomaly,epoch_dt=utc(op.epoch),start_dt=start,end_dt=start+timedelta(seconds=600),step_s=1,
                target_lat_deg=target["latitude"],target_lon_deg=target["longitude"],target_alt_m=0,
                max_yaw_deg=45,max_pitch_deg=45,max_roll_deg=45,min_elevation_deg=5,coarse_step_min=60)
            self.assertEqual(windows,[(utc(expected_first),utc(expected_end))]);self.assertEqual(len(samples),600);self.assertEqual(len(attitudes),n)
            for sample in samples:self.assertEqual(sample["visible"],reference(sample["time"])[0])
            for sample in attitudes:
                truth=reference(sample["time"])[1]
                self.assertLessEqual(max(abs(sample[k]-a) for k,a in zip(("yaw_deg","pitch_deg","roll_deg"),truth)),1e-8)
            errors=[]
            for boundary,entering in ((utc(expected_first),True),(utc(expected_end),False)):
                lo,hi=boundary-timedelta(seconds=1),boundary
                self.assertEqual(reference(lo)[0],not entering);self.assertEqual(reference(hi)[0],entering)
                while (hi-lo).total_seconds()>1e-6:
                    middle=lo+(hi-lo)/2
                    if reference(middle)[0]==entering:hi=middle
                    else:lo=middle
                upper=(boundary-lo).total_seconds()
                self.assertLess(upper,1)
                errors.append(dict(kind="entry" if entering else "exit",lower=lo.isoformat(),upper=hi.isoformat(),error_upper_s=upper))
            candidate,_=recompute_data(fixture,data_path=str(self.data))
            self.assertEqual(fixture,original);self.assertEqual(static_data(candidate),static_data(original))
            item=candidate["observation_windows"][0]["time_windows"][0]
            self.assertEqual(utc(item["start_time"]),utc(expected_first));self.assertEqual(utc(item["end_time"]),utc(expected_end))
            for axis in ("pitch","yaw","roll"):self.assertEqual(item["agile_data"][axis+"_angles"],[s[axis+"_deg"] for s in attitudes])
            results.append(dict(mission=mid,start=expected_first,end=expected_end,attitude_samples=n,boundaries=errors,static_equal=True))
        self.evidence("boundaries.json",results)


if __name__=="__main__":
    unittest.main()
