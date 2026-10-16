"""统一独立构建入口：只读正式输入，临时资源由服务端校验后发布。"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from replay.document import build_replay_document
from replay.runtime import CONFIG_ID, attitude_samples, source_bundle_sha
from .config import Settings, sha256_file
from .storage import compact_json
from .visualization import orbit_cache_path

MAX_RESOURCE_BYTES = 64 * 1024 * 1024

def _write(path, value):
    payload = compact_json(value).encode("utf-8")
    if len(payload) > MAX_RESOURCE_BYTES:
        raise ValueError("REPLAY_RESOURCE_TOO_LARGE: 回放资源超过 64 MiB")
    path.write_bytes(payload)

def build(job_path: Path) -> None:
    job = json.loads(job_path.read_text(encoding="utf-8"))
    if job["replay_config"]["replay_config_id"] != CONFIG_ID:
        # 旧配置只维持原语义，不再作为新页面的数据源；身份仍记录实际构建版本。
        from .replay_legacy import build as build_legacy
        build_legacy(job_path)
        return
    project = Path(__file__).resolve().parent.parent
    if source_bundle_sha(project) != job["builder_code_sha"]:
        raise ValueError("回放构建源码已变化，请重新申请")
    scene = Path(job["scenario_path"])
    if sha256_file(scene) != job["scenario_sha256"]:
        raise ValueError("场景 SHA-256 不匹配")
    if hashlib.sha256(compact_json(job["plan"]).encode()).hexdigest() != job["plan_sha256"]:
        raise ValueError("正式计划快照 SHA-256 不匹配")
    record = {"run_id":job["run_id"], "config":job["run_config"], "plan":job["plan"]}
    document = build_replay_document(record, config_data=job["replay_config"])
    directory = job_path.parent
    cached = orbit_cache_path(Settings(runtime_dir=Path(job["runtime_dir"]), scenario_dir=scene.parent),
                              scene, job["scenario_sha256"])
    if cached.stat().st_size > MAX_RESOURCE_BYTES:
        raise ValueError("轨道显示资源超过 64 MiB，请登记较小场景或更疏采样")
    orbit = directory / "orbit_display.czml"
    shutil.copyfile(cached, orbit)
    samples, warnings = attitude_samples(document, json.loads(orbit.read_text(encoding="utf-8")))
    document["samples"] = samples
    document["diagnostics"].extend(warnings)
    document["manifest"].update({key:job[key] for key in (
        "replay_id","run_id","build_attempt","cache_key","builder_code_sha",
        "builder_version","propagation_version","attitude_version","geometry_version")})
    # API 的场景文件 ID 与 JSON 内部 ID 允许不同，分别保留，避免跨批次重名混淆。
    document["manifest"]["internal_scenario_id"] = document["manifest"]["scenario_id"]
    document["manifest"]["scenario_id"] = job["scenario_id"]
    document["manifest"]["plan_sha256"] = job["plan_sha256"]
    document["manifest"]["mount_rotation_direction"] = "camera_to_body"
    _write(directory/"attitude_samples.json", document)
    _write(directory/"segments.json", {"schema_version":2,"segments":document["segments"]})
    _write(directory/"diagnostics.json", {"schema_version":2,"warnings":document["warnings"],
                                          "diagnostics":document["diagnostics"]})
    _write(directory/"replay_config.json", job["replay_config"])
    resources = {}
    for key, filename in (("orbit_display","orbit_display.czml"),
                           ("attitude_samples","attitude_samples.json"),
                           ("segments","segments.json"),("diagnostics","diagnostics.json"),
                           ("replay_config","replay_config.json")):
        path = directory/filename
        resources[key] = {"filename":filename,"mime":"application/json",
                          "size_bytes":path.stat().st_size,"sha256":sha256_file(path)}
    manifest = {**document["manifest"], "resources":resources,
                "scenario_sha256":job["scenario_sha256"],
                "replay_config_sha256":job["replay_config_sha256"],
                "algorithm_code_sha":job["algorithm_code_sha"],
                "provenance_warning":job["provenance_warning"],
                "scenario_provenance":job["run_config"].get("scenario_provenance",{}),
                "diagnostics_summary":{"warning_count":len(document["warnings"])+len(document["diagnostics"]),
                                       "sample_count":len(samples),"segment_count":len(document["segments"])}}
    _write(directory/"manifest.json", manifest)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job",type=Path,required=True)
    build(parser.parse_args().job)

if __name__ == "__main__":
    main()
