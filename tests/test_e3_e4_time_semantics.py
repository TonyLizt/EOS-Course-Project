"""Root-cause regressions; pure tests never start a JVM."""
import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

from utils.time_parsing import parse_orbit_epoch
from replay.scene import load_display_scene

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2025, 11, 18, 12, tzinfo=timezone.utc)


def exporter_without_jvm():
    source = ast.parse((ROOT/"draw/orekit_to_czml.py").read_text(encoding="utf-8"))
    module = ModuleType("_czml_functions")
    module.__dict__.update(datetime=datetime, timedelta=timedelta, timezone=timezone,
                           math=math, json=json, os=os, parse_orbit_epoch=parse_orbit_epoch,
                           load_display_scene=load_display_scene)
    functions = [node for node in source.body if isinstance(node, ast.FunctionDef)]
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(ROOT/"draw/orekit_to_czml.py"), "exec"),
         module.__dict__)
    return module


class CzmlPrecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exporter = exporter_without_jvm()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="eos-e3-e4-time-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def export(self, times):
        source = {"sat": [dict(time=t, lon_deg=i, lat_deg=2, alt_m=600000)
                          for i,t in enumerate(times)]}
        before = deepcopy(source)
        target = self.root/"orbit.czml"
        with patch("builtins.print"):
            self.exporter.build_czml(source, [], {}, str(target))
        self.assertEqual(source, before)
        return json.loads(target.read_bytes())

    def test_fractional_clock_availability_epoch_and_offsets(self):
        for micros in (0, 123456, 500000, 999999):
            with self.subTest(micros=micros):
                first = START.replace(microsecond=micros)
                last = first+timedelta(seconds=650, microseconds=123)
                doc = self.export([first, first+timedelta(seconds=300), last])
                self.assertEqual(parse_orbit_epoch(doc[0]["clock"]["currentTime"]), first)
                self.assertEqual(list(map(parse_orbit_epoch,doc[0]["clock"]["interval"].split("/"))),
                                 [first,last])
                position=doc[1]["position"]
                epoch=parse_orbit_epoch(position["epoch"])
                self.assertEqual(epoch,first)
                self.assertEqual(doc[1]["availability"],doc[0]["clock"]["interval"])
                self.assertEqual([epoch+timedelta(seconds=s) for s in position["cartographicDegrees"][::4]],
                                 [first,first+timedelta(seconds=300),last])

    def test_equivalent_utc_forms_preserve_absolute_time(self):
        forms=("2025-11-18T12:00:00Z","2025-11-18T12:00:00+00:00",
               "2025-11-18T20:00:00+08:00","2025-11-18T12:00:00")
        docs=[self.export([parse_orbit_epoch(t),START+timedelta(seconds=60)]) for t in forms]
        self.assertTrue(all(d==docs[0] for d in docs))

    def test_mixed_aware_naive_normalized_at_boundary(self):
        first=START.replace(microsecond=123456)
        doc=self.export([first.replace(tzinfo=None),
                         (first+timedelta(seconds=60)).astimezone(timezone(timedelta(hours=8)))])
        self.assertEqual(parse_orbit_epoch(doc[1]["position"]["epoch"]),first)
        self.assertEqual(doc[1]["position"]["cartographicDegrees"][::4],[0,60])

    def test_negative_offset_not_relabelled(self):
        first=START.astimezone(timezone(timedelta(hours=-5)))
        self.assertEqual(parse_orbit_epoch(self.export([first])[0]["clock"]["currentTime"]),START)

    def test_invalid_sample_time_rejected_before_writing(self):
        for value in ("broken","2025-11-18T12:00:00+25:00",None,True):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,"sat.*sample.time"):
                self.export([value])
            self.assertFalse((self.root/"orbit.czml").exists())

    def test_empty_samples_rejected(self):
        with self.assertRaises(ValueError):
            self.export([])

    def test_demo_keeps_fractional_scene_and_orbit_epoch(self):
        first=START.replace(microsecond=999999)
        scene={"scenario_id":"fixture","metadata":{"creation_time":first.isoformat(),"duration":650,"time_step":1},
               "satellites":[{"id":"sat","orbital_params":{"semi_major_axis_km":7000,"eccentricity":0.001,
                "inclination_deg":28,"right_ascension_of_ascending_node_deg":0,
                "argument_of_perigee_deg":0,"mean_anomaly_deg":0,"epoch":first.isoformat()}}],
               "missions":[]}
        path=self.root/"scene.json";path.write_text(json.dumps(scene))
        before=path.read_bytes()
        def propagate(**kw):
            self.assertEqual(kw["start_dt"],first)
            self.assertEqual(kw["end_dt"],first+timedelta(seconds=650))
            self.assertEqual(kw["epoch_dt"],first)
            return [dict(time=t,lon_deg=0,lat_deg=0,alt_m=600000)
                    for t in self.exporter._sample_times(kw["start_dt"],kw["end_dt"],kw["step_s"])]
        constants=ModuleType("org.orekit.utils")
        constants.Constants=type("Constants",(),{"WGS84_EARTH_MU":3.986004418e14})
        with patch.object(self.exporter,"init_orekit"),patch.object(self.exporter,"propagate_satellite_groundtrack",side_effect=propagate),patch.dict("sys.modules",{"org.orekit.utils":constants}),patch("builtins.print"):
            self.exporter.demo(str(path),str(self.root/"demo.czml"),"unused",orbit_step_s=300)
        doc=json.loads((self.root/"demo.czml").read_bytes())
        self.assertEqual(doc[1]["position"]["cartographicDegrees"][::4],[0,300,600,650])
        self.assertEqual(parse_orbit_epoch(doc[0]["clock"]["interval"].split("/")[1]),first+timedelta(seconds=650))
        self.assertEqual(path.read_bytes(),before)

    def test_cache_identity_changes_without_version_or_contract_change(self):
        from eos_system.visualization import orbit_cache_file, ORBIT_CACHE_VERSION, _propagation_signature
        from eos_system.config import Settings
        self.assertEqual(ORBIT_CACHE_VERSION,2)
        settings=Settings(runtime_dir=self.root,scenario_dir=self.root/"scenes")
        with patch("eos_system.visualization.propagation_identity",return_value="a"*64):
            one=orbit_cache_file(settings,"b"*64)
        with patch("eos_system.visualization.propagation_identity",return_value="c"*64):
            two=orbit_cache_file(settings,"b"*64)
        self.assertNotEqual(one,two)


class ClosedOrbitSamplingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exporter=exporter_without_jvm()

    def test_all_requested_durations(self):
        for duration,expected in ((0,[0]),(100,[0,100]),(300,[0,300]),
                                  (600,[0,300,600]),(650,[0,300,600,650]),
                                  (900,[0,300,600,900])):
            with self.subTest(duration=duration):
                times=list(self.exporter._sample_times(START,START+timedelta(seconds=duration),300))
                self.assertEqual([(t-START).total_seconds() for t in times],expected)
                self.assertEqual(len(times),len(set(times)))

    def test_fractional_start_and_step_include_exact_end_once(self):
        first=START.replace(microsecond=123456)
        last=first+timedelta(seconds=0.65)
        times=list(self.exporter._sample_times(first,last,0.3))
        self.assertEqual(times,[first,first+timedelta(seconds=.3),first+timedelta(seconds=.6),last])

    def test_invalid_steps_and_reversed_interval_fail(self):
        for step in (0,-1,float("nan"),float("inf"),1e-9):
            with self.subTest(step=step),self.assertRaises(ValueError):
                list(self.exporter._sample_times(START,START+timedelta(seconds=1),step))
        with self.assertRaises(ValueError):
            list(self.exporter._sample_times(START,START-timedelta(seconds=1),300))


class VisibilityGridTests(unittest.TestCase):
    def scan(self, visible, duration=120, step=1):
        from utils.visibility import _scan_visibility_grid
        def evaluate(t):
            second=(t-START).total_seconds()
            return dict(time=t,visible=visible(second),elevation_deg=second,
                        off_nadir_deg=1,yaw_deg=second,pitch_deg=2,roll_deg=3)
        return _scan_visibility_grid(START,START+timedelta(seconds=duration),step,evaluate)

    def test_short_pass_between_invisible_coarse_points_is_found(self):
        windows,samples,attitudes=self.scan(lambda s:26<=s<29)
        self.assertEqual(windows,[(START+timedelta(seconds=26),START+timedelta(seconds=29))])
        self.assertEqual(len(samples),120);self.assertEqual(len(attitudes),3)

    def test_inner_fragments_and_attitudes_match_half_open_windows(self):
        from utils.visibility import _build_time_windows_from_visible_attitudes
        windows,_,attitudes=self.scan(lambda s:26<=s<29 or 49<=s<55)
        model=_build_time_windows_from_visible_attitudes(windows,attitudes,scenario_start_dt=START,orbit_period_s=6000)
        self.assertEqual(len(model),2)
        self.assertEqual(model[0].agile_data.yaw_angles,[26,27,28])
        self.assertEqual(model[1].agile_data.yaw_angles,[49,50,51,52,53,54])
        self.assertEqual([(m.start_time,m.end_time) for m in model],windows)

    def test_zero_window_and_horizon_clip(self):
        self.assertEqual(self.scan(lambda s:False)[0],[])
        windows,samples,attitudes=self.scan(lambda s:s>=118)
        self.assertEqual(windows,[(START+timedelta(seconds=118),START+timedelta(seconds=120))])
        self.assertEqual(len(attitudes),2)
        self.assertTrue(all(a["time"]<START+timedelta(seconds=120) for a in samples))

    def test_endpoint_attitude_cannot_leak_into_half_open_window(self):
        from utils.visibility import _build_time_windows_from_visible_attitudes
        _,_,attitudes=self.scan(lambda s:True,duration=3)
        windows=[(START,START+timedelta(seconds=2))]
        model=_build_time_windows_from_visible_attitudes(windows,attitudes,scenario_start_dt=START,orbit_period_s=6000)
        self.assertEqual(model[0].agile_data.yaw_angles,[0,1])

    def test_substep_hidden_window_limitation_is_explicit(self):
        self.assertEqual(self.scan(lambda s:26.1<s<26.9)[0],[])

    def test_offset_and_naive_grid_inputs_mean_utc(self):
        from utils.visibility import _scan_visibility_grid
        def evaluate(t):
            return dict(time=t,visible=True,elevation_deg=1,off_nadir_deg=2,yaw_deg=3,pitch_deg=4,roll_deg=5)
        for start in (START.replace(tzinfo=None),START.astimezone(timezone(timedelta(hours=8)))):
            windows,_,_=_scan_visibility_grid(start,start+timedelta(seconds=2),1,evaluate)
            self.assertEqual(windows,[(START,START+timedelta(seconds=2))])


if __name__=="__main__":
    unittest.main()
