"""系统运行配置和只读场景登记。

配置集中在这一层，避免把某位组员的 Windows 盘符写死在业务代码里。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    runtime_dir: Path
    scenario_dir: Path
    max_queued: int = 8
    max_workers: int = 1
    startup_timeout_s: float = 30.0
    transfer_timeout_s: float = 30.0
    stop_grace_s: float = 2.0

    @classmethod
    def from_env(cls) -> "Settings":
        runtime = Path(os.environ.get("EOS_RUNTIME_DIR", "~/eos-course-runtime")).expanduser().resolve()
        scenarios = Path(os.environ.get("EOS_SCENARIO_DIR", str(runtime / "scenarios"))).expanduser().resolve()
        return cls(runtime_dir=runtime, scenario_dir=scenarios)

    @property
    def database_path(self) -> Path:
        return self.runtime_dir / "results.sqlite3"

    @property
    def lock_path(self) -> Path:
        return self.runtime_dir / "controller.lock"


def sha256_file(path: Path) -> str:
    """分块计算哈希，避免一次把较大的母场景读入内存。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def list_scenarios(settings: Settings) -> list[dict]:
    """只登记专用场景目录中的 JSON；浏览器不能传入任意磁盘路径。"""
    if not settings.scenario_dir.is_dir():
        return []
    result = []
    for path in sorted(settings.scenario_dir.glob("*.json")):
        if not path.is_file() or path.is_symlink():
            continue
        result.append({"scenario_id": path.stem, "name": path.stem, "sha256": sha256_file(path)})
    return result


def resolve_scenario(settings: Settings, scenario_id: str) -> tuple[Path, str]:
    """ID 只允许简单文件名，解析后仍检查目录边界和符号链接。"""
    if not scenario_id or not all(ch.isalnum() or ch in "_-" for ch in scenario_id):
        raise ValueError("场景 ID 只能包含字母、数字、下划线和短横线")
    path = settings.scenario_dir / f"{scenario_id}.json"
    if path.is_symlink() or not path.is_file() or path.resolve().parent != settings.scenario_dir:
        raise FileNotFoundError(f"未登记场景：{scenario_id}")
    return path, sha256_file(path)
