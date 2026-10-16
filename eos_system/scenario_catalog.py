"""内置六场景的可移植登记与身份检查；不复制数据或替代物理验收。"""
from __future__ import annotations

import json
from pathlib import Path

from replay.sampling import sampling_policy
from .config import list_scenarios_in


class ScenarioCatalog:
    def __init__(self, project: Path):
        self.project = project.resolve()
        self.root = self.project / "experiments/scenarios"
        path = self.project / "experiments/scenario_catalog.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.groups = data["groups"]
        self.entries = {}
        for row in data["scenarios"]:
            relative = Path(row["path"])
            target = (self.root / relative).resolve()
            if relative.is_absolute() or not target.is_relative_to(self.root.resolve()):
                raise ValueError("内置场景清单路径越界")
            if target in self.entries:
                raise ValueError("内置场景路径重复")
            self.entries[target] = row

    def register_sources(self, database) -> list[str]:
        """启动时幂等登记；已手工登记的同路径复用，不增加重复数据源。"""
        warnings = []
        for group in self.groups:
            root = (self.root / group["directory"]).resolve()
            if not root.is_relative_to(self.root.resolve()) or not root.is_dir():
                warnings.append("内置场景目录不可用：" + group["name"])
                continue
            overlaps = any(
                profile["root_path"] and (
                    root.is_relative_to(Path(profile["root_path"]).resolve())
                    or Path(profile["root_path"]).resolve().is_relative_to(root)
                ) for profile in database.list_output_profiles()
            )
            if overlaps:
                warnings.append("内置场景目录与输出目录重叠，未登记：" + group["name"])
                continue
            database.ensure_catalog_source(group["source_id"], group["name"], root)
        return warnings

    def list_scenarios(self, root: Path, source_id: str) -> list[dict]:
        """目录列表附带可信的规模信息；SHA 不符/未下载时仍可看见原因。"""
        result = list_scenarios_in(root, source_id)
        by_name = {row["scenario_id"]: row for row in result}
        for path, entry in self.entries.items():
            if path.parent != root.resolve():
                continue
            row = by_name.get(entry["scenario_id"])
            if row is None:
                row = {"source_id":source_id, "scenario_id":entry["scenario_id"],
                       "name":entry["scenario_id"], "sha256":None}
                result.append(row)
            status = "ready"
            if not path.is_file() or path.is_symlink():
                status = "missing"
            elif path.stat().st_size < 512 and path.read_bytes().startswith(b"version https://git-lfs"):
                status = "lfs_pointer"
            elif row["sha256"] != entry["sha256"]:
                status = "hash_mismatch"
            row.update(
                catalog_id="course-six-v1", availability=status,
                expected_sha256=entry["sha256"], size_bytes=entry["size_bytes"],
                satellite_count=entry["satellite_count"], mission_count=entry["mission_count"],
                duration_s=entry["duration_s"], internal_scenario_id=entry["internal_scenario_id"],
                scenario_physics_version=entry["scenario_physics_version"],
                provenance_status=entry["provenance_status"],
                replay_preview=sampling_policy(entry["duration_s"], entry["satellite_count"],
                                               entry["mission_count"]),
            )
        return sorted(result, key=lambda row: row["scenario_id"])

    def verify_identity(self, path: Path, actual_sha256: str) -> None:
        """提交仍用新算的字节 SHA，不能用列表缓存或文件名冒充清单数据。"""
        entry = self.entries.get(path.resolve())
        if entry and actual_sha256 != entry["sha256"]:
            raise ValueError("内置场景 SHA 与清单不符；请完成 Git LFS 下载，或另存为自定义数据源")
