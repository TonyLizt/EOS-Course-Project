"""隔离网页验收服务：正式库不受影响，结束后清理所有临时输入和派生文件。

先运行本脚本，再将 --coord 指定的文件交给 integrated-system-smoke.cjs。
两任务记录由测试种入，仅验收回放；网页另提交空场景验收真实 Worker 链路。
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "tests"))
from test_integrated_replay import fixture
from eos_system.visualization import orbit_cache_file

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coord", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--max-duration-s", type=float, default=300)
    parser.add_argument("--satellites", type=int, default=2, choices=(2, 10, 50))
    parser.add_argument("--duration-s", type=int, default=60)
    args = parser.parse_args()
    if args.coord.exists():
        raise ValueError("协调文件已存在，请选新的路径，不能覆盖已有文件")
    base = f"http://127.0.0.1:{args.port}"
    owns_coord = False
    try:
        with fixture(args.satellites, args.duration_s) as f:
            # 合成轨道专门验收浏览器；真实 Orekit 导出由独立测试覆盖。
            empty = f.scene.parent / "empty.json"
            empty.write_text(json.dumps({
                "scenario_id": "empty",
                "metadata": {"creation_time": "2026-01-01T00:00:00", "duration": 60},
                "satellites": [], "ground_stations": [], "missions": []
            }), encoding="utf-8")
            output = f.root / "exports"
            output.mkdir()
            cache = orbit_cache_file(f.settings, f.sha)
            packets = json.loads(cache.read_text())
            clock = packets[0]["clock"]
            clock.update(currentTime="2026-01-01T00:00:00Z", multiplier=1,
                         range="LOOP_STOP", step="SYSTEM_CLOCK_MULTIPLIER")
            for row in packets[1:]:
                row.update(name=row["id"], availability=clock["interval"],
                           point={"pixelSize": 8, "color": {"rgba": [0,255,255,255]}},
                           path={"show": True, "width": 2,
                                 "material": {"solidColor": {"color": {"rgba": [0,255,255,255]}}}})
            for task, lon in (("M1",1), ("M2",2)):
                packets.append({"id": task, "name": task,
                    "position": {"cartographicDegrees": [lon,1,0]},
                    "point": {"pixelSize": 6, "color": {"rgba": [255,0,0,255]}}})
            cache.write_text(json.dumps(packets), encoding="utf-8")
            env = os.environ.copy()
            env.update(EOS_RUNTIME_DIR=str(f.settings.runtime_dir),
                       EOS_SCENARIO_DIR=str(f.scene.parent), PYTHONDONTWRITEBYTECODE="1")
            with (f.root/"server.log").open("w") as log:
                server = subprocess.Popen([
                    sys.executable, "-B", "-m", "uvicorn", "eos_system.api:create_app",
                    "--factory", "--host", "127.0.0.1", "--port", str(args.port), "--no-access-log"
                ], cwd=PROJECT, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    for _ in range(100):
                        if server.poll() is not None:
                            raise RuntimeError((f.root/"server.log").read_text())
                        try:
                            with urlopen(base+"/api/health", timeout=1):
                                break
                        except OSError:
                            time.sleep(.1)
                    else:
                        raise TimeoutError("隔离服务未按时就绪")
                    info = {"url": base, "run_id": f.run_id, "output": str(output),
                            "satellite_count": args.satellites, "stop": False}
                    with args.coord.open("x", encoding="utf-8") as stream:
                        json.dump(info, stream)
                    owns_coord = True
                    print("BROWSER_QA_READY "+json.dumps(info), flush=True)
                    deadline = time.monotonic()+args.max_duration_s
                    while time.monotonic() < deadline:
                        if not args.coord.exists() or json.loads(args.coord.read_text(encoding="utf-8-sig")).get("stop"):
                            break
                        time.sleep(.5)
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait(timeout=5)
                    print("BROWSER_QA_SERVER_LOG "+(f.root/"server.log").read_text()[-1800:], flush=True)
        print("BROWSER_QA_TEMPORARIES_CLEANED", flush=True)
    finally:
        if owns_coord:
            args.coord.unlink(missing_ok=True)

if __name__ == "__main__":
    main()
