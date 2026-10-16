"""检查已成功实验的统一 READY 回放；构建须显式加 --build。"""
from __future__ import annotations
import argparse
import hashlib
import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

def read(url, *, payload=None):
    request = Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                      headers={"Content-Type":"application/json"} if payload is not None else {})
    try:
        with urlopen(request, timeout=660) as response:
            return response.read()
    except HTTPError as exc:
        raise RuntimeError(f"{exc.code}: {exc.read().decode(errors='replace')[:600]}") from exc

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--build", action="store_true", help="显式申请/重试独立回放")
    parser.add_argument("--check-legacy-orbit", action="store_true", help="额外验证旧 orbit GET；可能生成共享轨道缓存")
    args = parser.parse_args()
    root = f"{args.base.rstrip('/')}/api/runs/{args.run_id}"
    plan = json.loads(read(root+"/visualization/schedule"))
    assert plan["provenance"]["run_id"] == args.run_id
    configs = json.loads(read(args.base+"/api/replay-configs"))
    state = json.loads(read(root+"/replay", payload={"replay_config_id":configs["default_id"]}) if args.build
                       else read(root+"/replay"))
    deadline = time.monotonic()+660
    while state["replay_status"] == "BUILDING" and time.monotonic() < deadline:
        time.sleep(.5)
        state = json.loads(read(args.base+state["status_url"]))
    if state["replay_status"] != "READY":
        raise RuntimeError(f"回放未 READY：{state['replay_status']}；首次构建请加 --build；{state.get('error')}")
    manifest = state["manifest"]
    assert manifest["plan_sha256"] == plan["plan_sha256"]
    for key, item in manifest["resources"].items():
        content = read(args.base+item["url"])
        assert len(content) == item["size_bytes"]
        assert hashlib.sha256(content).hexdigest() == item["sha256"], key
    for page in ("gantt", "cesium"):
        read(f"{args.base}/visualization/{page}/{args.run_id}")
    if args.check_legacy_orbit:
        packets = json.loads(read(root+"/visualization/orbit.czml"))
        assert packets and packets[0]["id"] == "document"
    print(f"统一回放检查通过：{len(plan['assignments'])} 条正式 assignment，5 种哈希匹配资源；{state['replay_id']}")

if __name__ == "__main__":
    main()
