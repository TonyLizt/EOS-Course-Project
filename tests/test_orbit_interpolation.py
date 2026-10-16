"""Independent orbit interpolation regressions; no formal scene generation."""
from datetime import datetime, timedelta, timezone
import json
import os
import subprocess
from copy import deepcopy
import math
from pathlib import Path
import tempfile
import unittest

from replay.runtime import _position_at
from test_e3_e4_time_semantics import exporter_without_jvm

START = datetime(2025,11,18,12,tzinfo=timezone.utc).replace(microsecond=123456)


def circular(seconds):
    return (7000000*math.cos(0.0012*seconds),7000000*math.sin(0.0012*seconds),
            300000*math.sin(0.0012*seconds))


class OrbitInterpolationTests(unittest.TestCase):
    def test_curved_midpoints_and_off_grid_queries(self):
        nodes=[(START+timedelta(seconds=s),circular(s)) for s in range(0,601,60)]
        for seconds in (0,1,30,37.5,147.3,150,225,300,375,449.3,450,599,600):
            with self.subTest(seconds=seconds):
                error=math.dist(_position_at(nodes,START+timedelta(seconds=seconds)),circular(seconds))
                self.assertLess(error,0.1)

    def test_exact_knots_and_fractional_endpoint_are_preserved(self):
        nodes=[(START+timedelta(seconds=s),circular(s)) for s in (*range(0,601,60),650.125)]
        for time,position in nodes:self.assertEqual(_position_at(nodes,time),position)

    def test_single_and_two_point_legacy_inputs(self):
        first=(START,(1,2,3));last=(START+timedelta(seconds=60),(61,122,183))
        self.assertEqual(_position_at([first],START),first[1])
        self.assertEqual(_position_at([first,last],START+timedelta(seconds=30)),(31,62,93))
        self.assertEqual(_position_at([first,last],START-timedelta(seconds=1)),first[1])
        self.assertEqual(_position_at([first,last],last[0]+timedelta(seconds=1)),last[1])

    def test_czml_declares_position_interpolation_without_changing_time(self):
        draw=exporter_without_jvm()
        samples={"sat":[dict(time=START+timedelta(seconds=s),lon_deg=s,lat_deg=0,alt_m=600000) for s in (0,300,600)]}
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/"orbit.czml"
            draw.build_czml(samples,[],{},str(target))
            doc=json.loads(target.read_bytes())
        position=doc[1]["position"]
        self.assertEqual(position["interpolationAlgorithm"],"LAGRANGE")
        self.assertEqual(position["interpolationDegree"],5)
        self.assertEqual(position["cartographicDegrees"][::4],[0,300,600])
        self.assertIn(".123456Z",position["epoch"])

    def test_existing_budgets_not_relaxed(self):
        from eos_system.visualization import ORBIT_STEP_S,ORBIT_CACHE_VERSION
        from replay.sampling import sampling_policy,MAX_SAMPLES
        self.assertLessEqual(ORBIT_STEP_S,60)
        self.assertEqual(ORBIT_CACHE_VERSION,2)
        self.assertEqual(MAX_SAMPLES,200000)
        profile=sampling_policy(3*86400,50,100)
        self.assertLessEqual(profile["estimated_sample_upper_bound"],100000)
        orbit_count=50*(math.ceil(3*86400/ORBIT_STEP_S)+1)
        # Four conservative 32-byte JSON scalar slots plus packet overhead;
        # no real 50-star generation is performed by this resource check.
        self.assertLess(orbit_count*4*32+1024*1024,64*1024*1024)


@unittest.skipUnless(os.environ.get("EOS_RUN_ORBIT_INTERPOLATION_TESTS")=="1",
                     "opt-in: EOS_RUN_ORBIT_INTERPOLATION_TESTS=1")
class OrekitInterpolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_e3_e4_orekit as fixtures
        fixtures.E3E4OrekitTests.setUpClass()
        cls.reference=fixtures.E3E4OrekitTests()
        cls.temporary=tempfile.TemporaryDirectory(prefix="orbit-interpolation-")
        cls.root=Path(cls.temporary.name)
        cls.selected=("ALOS-2_39766","GPM-CORE_39574","SCD_1_22490")
        scene=deepcopy(cls.reference.scene)
        scene["satellites"]=[cls.reference.sats[s] for s in cls.selected]
        scene["missions"]=[];scene["observation_windows"]=[];scene["communication_windows"]=[]
        scene["metadata"].update(creation_time=START.isoformat(),duration=650,time_step=1)
        source=cls.root/"fixture.json";source.write_text(json.dumps(scene))
        cls.reference.draw.demo(str(source),str(cls.root/"orbit.czml"),str(cls.reference.data),orbit_step_s=60)
        cls.packets=json.loads((cls.root/"orbit.czml").read_bytes())
        from orekit_jpype.pyhelpers import datetime_to_absolutedate
        cls.truth={}
        cls.queries=tuple(range(651))+(37.5,112.5,147.3,449.3,649.9)
        for sid in cls.selected:
            prop=cls.reference.reference(sid)
            cls.truth[sid]={seconds:cls.reference.xyz(prop.propagate(
                datetime_to_absolutedate(START+timedelta(seconds=seconds))).getPVCoordinates(cls.reference.itrf).getPosition())
                for seconds in cls.queries}

    @classmethod
    def tearDownClass(cls):
        import test_e3_e4_orekit as fixtures
        fixtures.E3E4OrekitTests.tearDownClass()
        cls.temporary.cleanup()

    def save_evidence(self,name,value):
        if os.environ.get("EOS_ORBIT_INTERPOLATION_EVIDENCE"):
            directory=Path(os.environ["EOS_ORBIT_INTERPOLATION_EVIDENCE"])
            directory.mkdir(parents=True,exist_ok=True)
            with (directory/name).open("x") as f:json.dump(value,f,indent=2)

    def test_300s_nodes_and_dense_off_grid_vs_direct_orekit(self):
        from replay.runtime import _orbit_samples
        report=[]
        for packet in self.packets:
            sid=packet.get("id")
            if sid not in self.selected:continue
            self.assertEqual(packet["position"]["interpolationAlgorithm"],"LAGRANGE")
            samples=_orbit_samples(packet)
            old=[(START+timedelta(seconds=s),self.truth[sid][s]) for s in (0,300,600,650)]
            def linear(when):
                for (a,p),(b,q) in zip(old,old[1:]):
                    if a<=when<=b:
                        u=(when-a).total_seconds()/(b-a).total_seconds()
                        return [p[i]*(1-u)+q[i]*u for i in range(3)]
                raise AssertionError("query outside reference")
            rows=[]
            for seconds in self.queries:
                when=START+timedelta(seconds=seconds)
                before=math.dist(linear(when),self.truth[sid][seconds])
                after=math.dist(_position_at(samples,when),self.truth[sid][seconds])
                self.assertLess(after,1.0)
                if seconds in (0,300,600,650):self.assertLess(after,1e-6)
                rows.append(dict(offset_s=seconds,before_m=before,after_m=after))
            self.assertGreater(max(row["before_m"] for row in rows),50000)
            self.assertLess(max(row["after_m"] for row in rows),max(row["before_m"] for row in rows)*1e-5)
            report.append(dict(satellite=sid,max_before_m=max(x["before_m"] for x in rows),
                               max_after_m=max(x["after_m"] for x in rows),rows=rows))
        self.save_evidence("orekit-comparison.json",report)
        self.save_evidence("orbit.czml",self.packets)

    def test_ready_backend_and_node_consumer_at_5_20_135_seconds(self):
        from replay.runtime import attitude_samples
        root=Path(__file__).resolve().parents[1]
        results=[]
        for step in (5,20,135):
            document=dict(manifest=dict(start_time=START.isoformat(),end_time=(START+timedelta(seconds=650)).isoformat()),
                replay_config=dict(display_sampling_policy=dict(attitude_step_s=step,preferred_attitude_step_s=5)),
                satellites=[dict(id=sid,maneuverability_type="agile",sensors=[
                    dict(sensor_id=sid+"_sensor",sensor_mount_quaternion_xyzw=[0,0,0,1])]) for sid in self.selected],
                missions=[],segments=[],warnings=[])
            samples,warnings=attitude_samples(document,self.packets)
            document["samples"]=samples
            tolerance=5 if step==135 else 1
            queries=[dict(satellite=sid,time=(START+timedelta(seconds=s)).isoformat(),offset_s=s,
                          truth_m=self.truth[sid][s]) for sid in self.selected for s in self.queries]
            fixture=dict(replay=document,queries=queries,max_error_m=tolerance)
            path=self.root/("ready-"+str(step)+".json");path.write_text(json.dumps(fixture))
            result=subprocess.run(["node","tests/orbit_interpolation.test.cjs","--fixture",str(path)],
                                  cwd=root,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            results.append(dict(step_s=step,node_output=result.stdout.strip(),sample_count=len(samples)))
            self.save_evidence("ready-"+str(step)+".json",fixture)
        self.save_evidence("ready-consumer.json",results)


if __name__=="__main__":
    unittest.main()
