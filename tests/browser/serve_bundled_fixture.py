"""临时运行一个真实 50 星场景供浏览器验收；全部派生数据退出清理。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT))
from scripts.validate_bundled_scenarios import request, await_state
from eos_system.config import sha256_file


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coord",type=Path,required=True)
    parser.add_argument("--port",type=int,default=18766)
    args=parser.parse_args()
    if args.coord.exists():
        raise ValueError("协调文件已存在，不能覆盖")
    scene_id="Scenario_S2_Sats50_M100_T3.0d_dist0"
    source=PROJECT/"experiments/scenarios/medium"/(scene_id+".json")
    before=sha256_file(source)
    owns_coord=False
    try:
        with tempfile.TemporaryDirectory(prefix="eos-six-browser-") as directory:
            root=Path(directory)
            env=os.environ.copy()
            env.update(EOS_RUNTIME_DIR=str(root/"runtime"),EOS_SCENARIO_DIR=str(root/"empty"),
                       PYTHONDONTWRITEBYTECODE="1",PYTHONHASHSEED="0",MPLCONFIGDIR=str(root/"mpl"))
            base=f"http://127.0.0.1:{args.port}"
            with (root/"server.log").open("w") as log:
                server=subprocess.Popen([
                    sys.executable,"-B","-m","uvicorn","eos_system.api:create_app","--factory",
                    "--host","127.0.0.1","--port",str(args.port),"--no-access-log"
                ],cwd=PROJECT,env=env,stdout=log,stderr=subprocess.STDOUT)
                try:
                    for _ in range(100):
                        try:
                            request(base,"/api/health")
                            break
                        except (OSError,RuntimeError):
                            if server.poll() is not None:raise RuntimeError((root/"server.log").read_text())
                            time.sleep(.1)
                    created=request(base,"/api/runs",data={
                        "source_id":"bundled-medium","scenario_id":scene_id,"algorithm_id":"completion_first",
                        "time_budget_s":60,"seed":42,
                        "objective_weights":{"w_profit":0,"w_completion":1,"w_timeliness":0,"w_balance":0}
                    })
                    run_id=created["run_id"]
                    run=await_state(base,"/api/runs/"+run_id,"status",{"QUEUED","RUNNING","VERIFYING"},180)
                    assert run["status"]=="SUCCEEDED",run.get("error")
                    cfg=request(base,"/api/replay-configs")["default_id"]
                    state=request(base,"/api/runs/"+run_id+"/replay",data={"replay_config_id":cfg})
                    state=await_state(base,state["status_url"],"replay_status",{"BUILDING"},650)
                    assert state["replay_status"]=="READY",state.get("error")
                    info={"url":base,"run_id":run_id,"scenario_id":scene_id,"source_id":"bundled-medium",
                          "scenario_sha256":before,"stop":False}
                    with args.coord.open("x",encoding="utf-8") as stream:json.dump(info,stream)
                    owns_coord=True
                    print("BUNDLED_BROWSER_READY "+json.dumps(info),flush=True)
                    deadline=time.monotonic()+300
                    while time.monotonic()<deadline:
                        if not args.coord.exists() or json.loads(args.coord.read_text(encoding="utf-8-sig")).get("stop"):
                            break
                        time.sleep(.5)
                finally:
                    server.terminate()
                    try:server.wait(timeout=15)
                    except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
                    print("SERVER_STOPPED "+(root/"server.log").read_text()[-1000:],flush=True)
            assert sha256_file(source)==before
        print("BUNDLED_BROWSER_TEMPORARIES_CLEANED_INPUT_UNCHANGED",flush=True)
    finally:
        if owns_coord:args.coord.unlink(missing_ok=True)

if __name__=="__main__":
    main()
