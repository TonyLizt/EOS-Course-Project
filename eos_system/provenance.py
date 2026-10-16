"""场景来源的最小接入：读取外部证据，不补写或改造原场景。"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

def sidecar_path(scene: Path) -> Path:
    return scene.parent / "provenance" / (scene.name + ".provenance.json")

def capture_provenance(scene: Path, scenario_sha: str) -> dict:
    """Legacy 允许流程演示；E2 candidate 不能通过目录登记自动变成正式数据。"""
    sidecar = sidecar_path(scene)
    if not sidecar.exists():
        if "epoch_fixed_v1" in scene.name:
            raise ValueError("修复场景缺少匹配的来源与正式验收记录")
        return {"scenario_physics_version":"legacy_unknown", "provenance_status":"unknown",
                "scenario_sha256":scenario_sha, "parent_scenario_sha256":None,
                "warning":"历史生成版本与物理验收未证实；不得混入修复模型的正式比较"}
    if sidecar.is_symlink() or sidecar.stat().st_size > 1024*1024:
        raise ValueError("来源记录必须是小于 1 MiB 的普通文件")
    raw = sidecar.read_bytes()
    evidence = json.loads(raw)
    if not isinstance(evidence,dict) or not isinstance(evidence.get("physical_validation", {}),dict):
        raise ValueError("场景来源记录结构无效")
    if evidence.get("scenario_sha256") != scenario_sha or evidence.get("completion_status") != "complete":
        raise ValueError("场景来源记录的哈希或完成标记不匹配")
    if (evidence.get("publication_status") == "candidate_only"
            or evidence.get("formal_release_eligible") is not True
            or evidence.get("physical_validation", {}).get("status") != "PASS"):
        raise ValueError("该场景仍是待验收候选，请先完成 E3/E4 正式发布")
    for key in ("scenario_physics_version","epoch_parser_version","propagation_version"):
        if not isinstance(evidence.get(key),str) or not evidence[key]:
            raise ValueError("正式修复场景缺少版本字段："+key)
    parent = evidence.get("parent_scenario_sha256")
    if not isinstance(parent,str) or not re.fullmatch("[0-9a-f]{64}",parent):
        raise ValueError("修复场景缺少可追溯的父场景 SHA-256")
    return {key:evidence.get(key) for key in (
        "scenario_physics_version","epoch_parser_version","propagation_version",
        "parent_scenario_sha256","scenario_sha256","registry_id","provenance_status")} | {
        "sidecar_sha256":hashlib.sha256(raw).hexdigest(), "physical_validation_status":"PASS"}

def verify_provenance(config) -> None:
    """运行与独立核验都复查提交时的 sidecar，不接受提交后替换来源文件。"""
    snapshot = config.scenario_provenance
    if snapshot.get("sidecar_sha256"):
        current = capture_provenance(Path(config.scenario_path), config.scenario_sha256)
        if current != snapshot:
            raise ValueError("场景来源记录与本次实验快照不一致")
