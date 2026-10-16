"""恢复后框架的统一回放与数据来源集成验收，不修改正式运行库。"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from eos_system.api import create_app
from eos_system.config import Settings
from eos_system.contracts import RunConfig
from eos_system.provenance import capture_provenance, sidecar_path, verify_provenance
from eos_system.storage import Database, compact_json, now
from eos_system.visualization import orbit_cache_file, propagation_identity
from replay.runtime import CONFIG_ID, validate_document
try:
    from .test_replay_backend import _DirectClient
except ImportError:
    from test_replay_backend import _DirectClient

@contextmanager
def fixture():
    """种入隔离的正式记录；独立 builder 是真实子进程，轨道用确定样本避免 JVM 成本。"""
    with tempfile.TemporaryDirectory(prefix="eos-integrated-test-") as directory:
        root=Path(directory)
        scenes=root/"scenes"
        scenes.mkdir()
        scene={"scenario_id":"Scenario_internal",
               "metadata":{"creation_time":"2026-01-01T08:00:00+08:00","duration":60},
               "satellites":[{"id":sid,
                    "maneuverability_capability":{"maneuverability_type":kind},
                    "observation_capability":{"sensors":[{"sensor_id":sid+"_custom","field_of_view_deg":45}]}}
                    for sid,kind in (("sat-a","agile"),("sat-b","non-agile"))],
               "missions":[{"id":task,"target_location":{"longitude":lon,"latitude":1,"altitude_km":0}}
                           for task,lon in (("M1",1),("M2",2))]}
        path=scenes/"fixture.json"
        path.write_text(json.dumps(scene),encoding="utf-8")
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        settings=Settings(runtime_dir=root/"runtime",scenario_dir=scenes,replay_build_timeout_s=30)
        cache=orbit_cache_file(settings,sha)
        cache.parent.mkdir(parents=True)
        cache.write_text(json.dumps([{"id":"document","version":"1.0","clock":{
            "interval":"2026-01-01T00:00:00Z/2026-01-01T00:01:00Z"}},
            *[{"id":sid,"position":{"epoch":"2026-01-01T00:00:00Z",
              "cartographicDegrees":[0,0,0,600000,30,1,0,600000,60,2,0,600000]}}
              for sid in ("sat-a","sat-b")]]))
        db=Database(settings.database_path)
        rid="00000000-0000-4000-8000-000000000016"
        cfg=RunConfig(run_id=rid,scenario_id="fixture",scenario_sha256=sha,scenario_path=str(path),
                      algorithm_id="completion_first",algorithm_version="baseline-1",created_at=now())
        db.enqueue(cfg,8)
        attempt,_=db.start_attempt(rid)
        db.set_verifying(rid,attempt)
        plan={"scenario_id":"Scenario_internal","start_time":"2026-01-01T00:00:00",
              "end_time":"2026-01-01T00:01:00",
              "assignments":[{"task_id":task,"satellite_id":"sat-a","sensor_id":"sat-a_custom",
                    "sat_start_time":"2026-01-01T00:00:"+start,
                    "sat_end_time":"2026-01-01T00:00:"+end,
                    "sat_angles":{"roll_angles":[0],"pitch_angles":[0],"yaw_angles":[0]}}
                    for task,start,end in (("M1","10","15"),("M2","40","45"))],
              "unassigned_tasks":[]}
        metrics={"completed_tasks":2,"total_tasks":2,"task_profit":2,"task_completion_rate":1,
                 "balance_degree":1,"timeliness_metric":0.3,"runtime_efficiency":0.01,
                 "robustness_variance":None,"mip_gap":None}
        assert db.finish_success(rid,attempt,plan,metrics,0.001)
        app=create_app(settings)
        obj=SimpleNamespace(root=root,settings=settings,scene=path,sha=sha,db=db,run_id=rid,
                            app=app,client=_DirectClient(app),config=cfg)
        try:
            yield obj
        finally:
            app.state.replay.close()

def request(f):
    response=f.client.post("/api/runs/"+f.run_id+"/replay",json={"replay_config_id":CONFIG_ID})
    assert response.status_code in (200,202), response.text
    return response.json()

def terminal(f,state):
    for _ in range(200):
        if state["replay_status"]!="BUILDING":
            return state
        time.sleep(0.05)
        state=f.client.get(state["status_url"]).json()
    raise AssertionError("回放未在测试上限内结束")

class IntegratedReplayTests(unittest.TestCase):
    def test_committed_plan_to_published_samples_and_compatibility(self):
        with fixture() as f:
            before=compact_json(f.db.get_run(f.run_id))
            url="/api/runs/"+f.run_id
            self.assertEqual(f.client.get(url+"/visualization/replay").status_code,409)
            self.assertIsNone(f.db.latest_replay(f.run_id,CONFIG_ID))
            config=f.client.get("/api/replay-configs").json()
            self.assertEqual(config["default_id"],CONFIG_ID)
            state=request(f)
            self.assertEqual(request(f)["replay_id"],state["replay_id"])
            state=terminal(f,state)
            self.assertEqual(state["replay_status"],"READY",state)
            manifest=state["manifest"]
            self.assertEqual(manifest["scenario_id"],"fixture")
            self.assertEqual(manifest["internal_scenario_id"],"Scenario_internal")
            self.assertEqual(manifest["propagation_version"],propagation_identity())
            doc=f.client.get(manifest["resources"]["attitude_samples"]["url"]).json()
            self.assertEqual(set(s["id"] for s in doc["satellites"]),{"sat-a","sat-b"})
            self.assertTrue(all(s["sensors"] for s in doc["satellites"]))
            self.assertGreater(len(doc["samples"]),0)
            self.assertTrue(any(s["phase"]=="SLEWING" for s in doc["segments"]))
            self.assertTrue(any(s["quality"]=="non_agile_nadir_illustration" for s in doc["samples"]))
            self.assertIn("?sha=",doc["satellites"][0]["model"]["uri"])
            validate_document(doc,f.db.get_replay(f.run_id,state["replay_id"]))
            self.assertEqual(f.client.get(url+"/visualization/replay").json(),doc)
            self.assertEqual(request(f)["replay_id"],state["replay_id"])
            self.assertEqual(compact_json(f.db.get_run(f.run_id)),before)
            directory=f.settings.replay_dir/state["replay_id"]/"build-1"
            self.assertEqual(len(list(directory.iterdir())),6)
            self.assertFalse((directory/"job.json").exists())
            redirect=f.client.get("/visualization/cesium/"+f.run_id)
            self.assertIn("replay_status=",redirect.headers["location"])
            self.assertNotIn("orbit.czml",redirect.headers["location"])

    def test_timeout_failure_retry_and_resource_corruption_leave_run_intact(self):
        with fixture() as f:
            f.app.state.replay.settings=replace(f.settings,replay_build_timeout_s=0.001)
            failed=terminal(f,request(f))
            self.assertEqual(failed["replay_status"],"FAILED",failed)
            self.assertEqual(f.db.get_run(f.run_id)["status"],"SUCCEEDED")
            f.app.state.replay.settings=f.settings
            ready=terminal(f,request(f))
            self.assertEqual(ready["replay_status"],"READY",ready)
            self.assertEqual(ready["replay_id"],failed["replay_id"])
            self.assertEqual(ready["build_attempt"],2)
            descriptor=ready["manifest"]["resources"]["segments"]
            folder=f.settings.replay_dir/ready["replay_id"]/"build-2"
            (folder/descriptor["filename"]).write_text("{}")
            self.assertEqual(f.client.get(descriptor["url"]).status_code,503)
            state=f.client.get(ready["status_url"]).json()
            self.assertEqual(state["replay_status"],"FAILED")
            self.assertEqual(f.db.get_run(f.run_id)["status"],"SUCCEEDED")
            self.assertEqual(f.client.delete("/api/runs/"+f.run_id).status_code,200)
            self.assertFalse((f.settings.replay_dir/ready["replay_id"]).exists())
            self.assertTrue(f.scene.exists())

    def test_interrupted_build_blocks_deletion_until_recovery(self):
        with fixture() as f:
            ready=terminal(f,request(f))
            self.assertEqual(ready["replay_status"],"READY",ready)
            with f.db.write() as db:
                db.execute("UPDATE replay_artifacts SET status='BUILDING',builder_pid=NULL WHERE replay_id=?",
                           (ready["replay_id"],))
            self.assertEqual(f.client.delete("/api/runs/"+f.run_id).status_code,409)
            f.app.state.replay.recover()
            failed=f.client.get(ready["status_url"]).json()
            self.assertEqual(failed["error"]["code"],"REPLAY_BUILD_INTERRUPTED")
            self.assertEqual(f.client.delete("/api/runs/"+f.run_id).status_code,200)

    def test_manifest_samples_reject_nan_and_missing_coverage(self):
        with fixture() as f:
            state=terminal(f,request(f))
            self.assertEqual(state["replay_status"],"READY",state)
            doc=f.client.get(state["manifest"]["resources"]["attitude_samples"]["url"]).json()
            expected=f.db.get_replay(f.run_id,state["replay_id"])
            original=json.loads(json.dumps(doc))
            doc["samples"][0]["body_to_ecef_quaternion_xyzw"][0]=float("nan")
            with self.assertRaisesRegex(ValueError,"有限"):
                validate_document(doc,expected)
            original["samples"]=original["samples"][1:]
            with self.assertRaisesRegex(ValueError,"覆盖"):
                validate_document(original,expected)

class ProvenanceTests(unittest.TestCase):
    def test_candidate_not_promoted_by_directory_registration(self):
        with fixture() as f:
            sidecar=sidecar_path(f.scene)
            sidecar.parent.mkdir()
            sidecar.write_text(json.dumps({"scenario_sha256":f.sha,"completion_status":"complete",
                "publication_status":"candidate_only","formal_release_eligible":False}))
            response=f.client.post("/api/runs",json={"scenario_id":"fixture","algorithm_id":"completion_first"})
            self.assertEqual(response.status_code,422)
            self.assertIn("待验收候选",response.json()["error"]["message"])

    def test_source_snapshot_unknown_or_verified_never_fabricated(self):
        with fixture() as f:
            old=capture_provenance(f.scene,f.sha)
            self.assertEqual(old["provenance_status"],"unknown")
            sidecar=sidecar_path(f.scene)
            sidecar.parent.mkdir()
            evidence={"scenario_sha256":f.sha,"parent_scenario_sha256":"a"*64,
                      "completion_status":"complete","publication_status":"released",
                      "formal_release_eligible":True,"physical_validation":{"status":"PASS"},
                      "scenario_physics_version":"epoch_fixed_v1","provenance_status":"verified",
                      "epoch_parser_version":"epoch_parser_v1","propagation_version":"orekit-test-v1"}
            sidecar.write_text(json.dumps(evidence))
            snapshot=capture_provenance(f.scene,f.sha)
            config=f.config.model_copy(update={"scenario_provenance":snapshot})
            verify_provenance(config)
            sidecar.write_text(json.dumps(evidence)+" ")
            with self.assertRaisesRegex(ValueError,"快照"):
                verify_provenance(config)

if __name__=="__main__":
    unittest.main()
