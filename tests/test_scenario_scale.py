"""六场景登记、流式静态投影与预算/端点的针对性回归。"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from eos_system.api import create_app
from eos_system.config import Settings, list_scenarios_in
from eos_system.scenario_catalog import ScenarioCatalog
from eos_system.storage import Database
from replay.runtime import attitude_samples
from replay.sampling import sampling_policy
from replay.scene import file_sha256, load_display_scene
try:
    from .test_replay_backend import _DirectClient
except ImportError:
    from test_replay_backend import _DirectClient


class SamplingScaleTests(unittest.TestCase):
    def test_real_scale_profiles_fit_budget(self):
        for stars, duration, tasks, step in (
            (10,86400,20,10),(20,86400,20,20),(50,259200,100,135)
        ):
            with self.subTest(stars=stars):
                policy=sampling_policy(duration,stars,tasks)
                self.assertEqual(policy["attitude_step_s"],step)
                self.assertLessEqual(policy["estimated_sample_upper_bound"],100000)
                self.assertTrue(policy["preserve_task_and_slew_endpoints"])

    def test_small_case_keeps_five_seconds_and_impossible_case_refuses(self):
        self.assertEqual(sampling_policy(60,2,2)["attitude_step_s"],5)
        for args in ((float("nan"),1,1),(60,1,30000),(10**9,50,1)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                sampling_policy(*args)

    def test_coarser_grid_still_keeps_short_task_and_slew_endpoints(self):
        with patch("replay.sampling.TARGET_SAMPLES",60):
            policy=sampling_policy(600,2,2)
        self.assertEqual(policy["attitude_step_s"],25)
        sensor={"sensor_id":"camera","sensor_mount_quaternion_xyzw":[0,0,0,1]}
        base={"satellite_id":"s1","sensor_id":"camera"}
        segments=[
            dict(base,phase="OBSERVING",task_id="t1",assignment_ordinal=0,
                 start_time="2026-01-01T00:00:10Z",end_time="2026-01-01T00:00:15Z"),
            dict(base,phase="SLEWING",task_id="t2",assignment_ordinal=1,from_assignment_ordinal=0,
                 start_time="2026-01-01T00:00:20Z",end_time="2026-01-01T00:00:40Z"),
            dict(base,phase="OBSERVING",task_id="t2",assignment_ordinal=1,
                 start_time="2026-01-01T00:00:40Z",end_time="2026-01-01T00:00:45Z"),
        ]
        document={
            "manifest":{"start_time":"2026-01-01T00:00:00Z","end_time":"2026-01-01T00:10:00Z"},
            "replay_config":{"display_sampling_policy":policy},
            "satellites":[{"id":sid,"maneuverability_type":"agile","sensors":[sensor]}
                          for sid in ("s1","s2")],
            "missions":[{"id":task,"target_location":{"longitude":lon,"latitude":1}}
                        for task,lon in (("t1",1),("t2",2))],
            "segments":segments,
        }
        packets=[{"id":sid,"position":{"epoch":"2026-01-01T00:00:00Z",
                   "cartographicDegrees":[0,0,0,600000,600,2,0,600000]}}
                 for sid in ("s1","s2")]
        samples,warnings=attitude_samples(document,packets)
        times={row["time"] for row in samples if row["satellite_id"]=="s1"}
        for seconds in (10,15,20,40,45):
            self.assertIn(f"2026-01-01T00:00:{seconds:02d}+00:00",times)
        self.assertLessEqual(len(samples),60)
        self.assertTrue(any(row["code"]=="ADAPTIVE_SAMPLING_COARSENED" for row in warnings))


class SceneProjectionTests(unittest.TestCase):
    def test_static_fields_are_exact_and_windows_not_materialized(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"scene.json"
            data={"observation_windows":[{"many_angles":[1,2,3]}],
                  "metadata":{"duration":60,"extra":{"same":True}},
                  "scenario_id":"original","satellites":[{"id":"custom","future":[1,2]}],
                  "missions":[],"communication_windows":[{"arbitrary":"unchanged"}],"unknown":[1]}
            path.write_text(json.dumps(data))
            before=file_sha256(path)
            # ijson 应实际处理，不允许偷偷回退到全量 json.load。
            with patch("replay.scene.json.load",side_effect=AssertionError("全量加载")):
                result=load_display_scene(path)
            self.assertEqual(result,{key:data[key] for key in ("metadata","scenario_id","satellites","missions")})
            self.assertEqual(file_sha256(path),before)

    def test_rejects_duplicate_root_fields_and_invalid_root(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"scene.json"
            for data in ('{"scenario_id":"a","scenario_id":"b"}',"[]","1","null"):
                path.write_text(data)
                with self.subTest(data=data), self.assertRaises(ValueError):
                    load_display_scene(path)

    def test_missing_ijson_only_allows_bounded_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"scene.json"
            path.write_text('{"scenario_id":"a","missions":[]}')
            with patch.dict(sys.modules,{"ijson":None}):
                self.assertEqual(load_display_scene(path)["scenario_id"],"a")
                with patch("replay.scene.FALLBACK_LIMIT",1), self.assertRaisesRegex(ValueError,"ijson"):
                    load_display_scene(path)


class CatalogTests(unittest.TestCase):
    def synthetic_catalog(self, root):
        folder=root/"experiments/scenarios/small"
        folder.mkdir(parents=True)
        scene=folder/"fixture.json"
        scene.write_text(json.dumps({"scenario_id":"fixture",
            "metadata":{"duration":60,"creation_time":"2026-01-01T00:00:00"},
            "satellites":[],"missions":[],"ground_stations":[]}))
        digest=file_sha256(scene)
        document={"groups":[{"source_id":"bundled-small","name":"小型","directory":"small"}],
            "scenarios":[{"path":"small/fixture.json","scenario_id":"fixture",
                         "internal_scenario_id":"fixture","sha256":digest,"size_bytes":scene.stat().st_size,
                         "satellite_count":0,"mission_count":0,"duration_s":60,
                         "scenario_physics_version":"legacy_unknown","provenance_status":"unknown"}]}
        (root/"experiments/scenario_catalog.json").write_text(json.dumps(document))
        return ScenarioCatalog(root),scene

    def test_registration_is_idempotent_and_reuses_manual_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            catalog,scene=self.synthetic_catalog(root)
            database=Database(root/"db.sqlite3")
            database.add_data_source("manual","已有目录",scene.parent)
            self.assertEqual(catalog.register_sources(database),[])
            catalog.register_sources(database)
            self.assertEqual([row["source_id"] for row in database.list_data_sources()],["manual"])

    def test_overlapping_output_is_never_registered_as_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            catalog,scene=self.synthetic_catalog(root)
            database=Database(root/"db.sqlite3")
            database.add_output_profile("conflict","冲突输出",scene.parent.parent)
            self.assertTrue(catalog.register_sources(database))
            self.assertEqual(database.list_data_sources(),[])

    def test_list_explains_missing_pointer_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            catalog,scene=self.synthetic_catalog(root)
            def row():return catalog.list_scenarios(scene.parent,"bundled-small")[0]
            self.assertEqual(row()["availability"],"ready")
            scene.write_text("version https://git-lfs.github.com/spec/v1\n")
            self.assertEqual(row()["availability"],"lfs_pointer")
            scene.write_text("{}")
            self.assertEqual(row()["availability"],"hash_mismatch")
            with self.assertRaisesRegex(ValueError,"SHA"):
                catalog.verify_identity(scene,file_sha256(scene))
            scene.unlink()
            self.assertEqual(row()["availability"],"missing")

    def test_http_submission_rechecks_sha_even_after_cached_listing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            catalog,scene=self.synthetic_catalog(root)
            settings=Settings(runtime_dir=root/"runtime",scenario_dir=root/"default")
            with patch("eos_system.api.ScenarioCatalog",return_value=catalog):
                app=create_app(settings)
            try:
                catalog.list_scenarios(scene.parent,"bundled-small")
                registry=_DirectClient(app).get("/api/replay-configs").json()["items"][0]
                self.assertEqual(registry["attitude_step_s"],5)
                self.assertTrue(registry["attitude_step_is_preferred"])
                self.assertEqual(registry["target_samples"],100000)
                scene.write_text("{}")
                response=_DirectClient(app).post("/api/runs",json={
                    "source_id":"bundled-small","scenario_id":"fixture","algorithm_id":"completion_first"})
                self.assertEqual(response.status_code,422)
                self.assertIn("SHA",response.json()["error"]["message"])
            finally:
                app.state.replay.close()

    def test_catalog_lists_all_six_real_files_without_reading_window_objects(self):
        project=Path(__file__).resolve().parents[1]
        catalog=ScenarioCatalog(project)
        rows=[]
        for group in catalog.groups:
            rows.extend(catalog.list_scenarios(catalog.root/group["directory"],group["source_id"]))
        self.assertEqual(len(rows),6)
        self.assertTrue(all(row["availability"]=="ready" for row in rows))
        self.assertEqual(sorted(row["satellite_count"] for row in rows),[10,10,20,20,50,50])
        self.assertTrue(all(row["scenario_physics_version"]=="legacy_unknown" for row in rows))

if __name__=="__main__":
    unittest.main()
