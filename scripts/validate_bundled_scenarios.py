"""六份真实场景的隔离系统验收；临时库/轨道/回放退出后清理，只保留指定报告。

不重算/改写原始场景，不把 Legacy 标成物理修复版本。
两个基线各跑六场景；默认只为第一基线构建六次真实 Orekit 回放。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from eos_system.config import sha256_file
from replay.runtime import source_bundle_sha


def request(base, path, *, data=None, method=None, raw=False):
    body = json.dumps(data).encode() if data is not None else None
    req = Request(base+path, data=body, method=method,
                  headers={"Content-Type":"application/json"} if body else {})
    try:
        with urlopen(req, timeout=180) as response:
            content = response.read()
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:1000]}") from exc
    return content if raw else json.loads(content) if content else None


def await_state(base, path, field, active, timeout):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        result = request(base, path)
        if result[field] not in active:
            return result
        time.sleep(.2)
    raise TimeoutError("验收轮询超过上限："+path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--budget-s", type=float, default=60)
    parser.add_argument("--no-replay", action="store_true", help="只验证调度，不宣称回放验收")
    args = parser.parse_args()
    report_path = args.report.resolve()
    if report_path.exists():
        raise ValueError("报告文件已存在，禁止覆盖")
    for protected in (PROJECT/"input", PROJECT/"experiments/scenarios"):
        if report_path.is_relative_to(protected.resolve()):
            raise ValueError("报告不能写入输入目录")
    catalog = json.loads((PROJECT/"experiments/scenario_catalog.json").read_text())
    report = {"status":"RUNNING", "scope":"Legacy integration only; E3/E4 physics NOT accepted",
              "budget_s":args.budget_s,"seed":42,"builder_code_sha":source_bundle_sha(PROJECT),
              "scenarios":[]}
    success = False
    try:
        with tempfile.TemporaryDirectory(prefix="eos-six-scenario-validation-") as directory:
            root = Path(directory)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1",0))
                port = probe.getsockname()[1]
            base = f"http://127.0.0.1:{port}"
            env = os.environ.copy()
            env.update(EOS_RUNTIME_DIR=str(root/"runtime"), EOS_SCENARIO_DIR=str(root/"empty"),
                       PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0", MPLCONFIGDIR=str(root/"mpl"))
            with (root/"server.log").open("w") as log:
                server = subprocess.Popen([
                    sys.executable,"-B","-m","uvicorn","eos_system.api:create_app","--factory",
                    "--host","127.0.0.1","--port",str(port),"--no-access-log"
                ],cwd=PROJECT,env=env,stdout=log,stderr=subprocess.STDOUT)
                try:
                    for _ in range(200):
                        try:
                            request(base,"/api/health")
                            break
                        except (OSError,RuntimeError):
                            if server.poll() is not None:
                                raise RuntimeError((root/"server.log").read_text())
                            time.sleep(.1)
                    else:
                        raise TimeoutError("隔离服务未就绪")
                    available = {}
                    for group in catalog["groups"]:
                        rows = request(base,"/api/scenarios?source_id="+group["source_id"])["items"]
                        available.update((row["scenario_id"], row) for row in rows)
                    assert len(available)==6
                    config_id=request(base,"/api/replay-configs")["default_id"]
                    for entry in catalog["scenarios"]:
                        path=PROJECT/"experiments/scenarios"/entry["path"]
                        before=sha256_file(path)
                        assert before==entry["sha256"]
                        selected=available[entry["scenario_id"]]
                        assert selected["availability"]=="ready"
                        evidence={"path":entry["path"],"sha256":before,"runs":[]}
                        report["scenarios"].append(evidence)
                        for index, algorithm in enumerate(("completion_first","adaptive_repair")):
                            started=time.monotonic()
                            created=request(base,"/api/runs",data={
                                "source_id":selected["source_id"],"scenario_id":entry["scenario_id"],
                                "algorithm_id":algorithm,"seed":42,"time_budget_s":args.budget_s,
                                "objective_weights":{"w_profit":0,"w_completion":1,"w_timeliness":0,"w_balance":0}
                            })
                            run_id=created["run_id"]
                            run=await_state(base,"/api/runs/"+run_id,"status",
                                            {"QUEUED","RUNNING","VERIFYING"},180)
                            row={"algorithm_id":algorithm,"status":run["status"],
                                 "elapsed_s":round(time.monotonic()-started,3)}
                            evidence["runs"].append(row)
                            assert run["status"]=="SUCCEEDED",run.get("error")
                            assert run["config"]["scenario_sha256"]==before
                            assert run["config"]["scenario_provenance"]["scenario_physics_version"]=="legacy_unknown"
                            row["metrics"]=run["metrics"]
                            row["algorithm_code_sha"]=run["config"]["algorithm_code_sha"]
                            formal_before=json.dumps(run["plan"],sort_keys=True)
                            exported=json.loads(request(base,"/api/runs/"+run_id+"/export?format=json",raw=True))
                            assert len(exported["assignments"])==run["metrics"]["completed_tasks"]
                            csv=request(base,"/api/runs/"+run_id+"/export?format=csv",raw=True)
                            assert csv.startswith(bytes([239,187,191]))
                            assert b"scenario_sha256" in csv
                            if index==0 and not args.no_replay:
                                started=time.monotonic()
                                state=request(base,"/api/runs/"+run_id+"/replay",data={"replay_config_id":config_id})
                                state=await_state(base,state["status_url"],"replay_status",{"BUILDING"},650)
                                assert state["replay_status"]=="READY",state.get("error")
                                manifest=state["manifest"]
                                sizes={}
                                document=None
                                for key,item in manifest["resources"].items():
                                    content=request(base,item["url"],raw=True)
                                    assert len(content)==item["size_bytes"]
                                    assert hashlib.sha256(content).hexdigest()==item["sha256"]
                                    sizes[key]=len(content)
                                    if key=="attitude_samples":
                                        document=json.loads(content)
                                assert len(document["samples"])<=100000
                                assert len(document["satellites"])==entry["satellite_count"]
                                assert manifest["scenario_sha256"]==before
                                after=request(base,"/api/runs/"+run_id)
                                assert json.dumps(after["plan"],sort_keys=True)==formal_before
                                assert after["metrics"]==run["metrics"]
                                row["replay"]={"status":"READY","elapsed_s":round(time.monotonic()-started,3),
                                    "sampling_policy":manifest["sampling_policy"],
                                    "sample_count":len(document["samples"]),"resource_bytes":sizes}
                                del content,document
                            request(base,"/api/runs/"+run_id,method="DELETE")
                            print(json.dumps({"scene":entry["scenario_id"],**row},ensure_ascii=False),flush=True)
                        assert sha256_file(path)==before
                        evidence["input_unchanged"]=True
                    success=True
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        server.kill();server.wait(timeout=5)
                    if not success:
                        report["server_log_tail"]=(root/"server.log").read_text()[-2400:]
        report["temporary_runtime_cleaned"]=True
    except Exception as exc:
        report["error"]=f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["status"]="PASS" if success else "FAIL"
        report_path.parent.mkdir(parents=True,exist_ok=True)
        with report_path.open("x",encoding="utf-8") as stream:
            json.dump(report,stream,ensure_ascii=False,indent=2)
            stream.write("\n")
        print("REPORT="+str(report_path),flush=True)


if __name__=="__main__":
    main()
