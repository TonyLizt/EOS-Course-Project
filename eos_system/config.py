"""系统运行配置和只读场景登记。

配置集中在这一层，避免把某位组员的 Windows 盘符写死在业务代码里。
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
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
    replay_build_timeout_s: float = 600.0
    max_replay_queued: int = 4

    @classmethod
    def from_env(cls) -> "Settings":
        runtime = Path(os.environ.get("EOS_RUNTIME_DIR", "~/eos-course-runtime")).expanduser().resolve()
        scenarios = Path(os.environ.get("EOS_SCENARIO_DIR", str(runtime / "scenarios"))).expanduser().resolve()
        return cls(runtime_dir=runtime, scenario_dir=scenarios)

    @property
    def replay_dir(self) -> Path:
        """回放派生缓存与 SQLite 一样放在 WSL 本地运行目录。"""
        return self.runtime_dir / "replays"

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


def normalise_user_path(value: str) -> Path:
    """把本机 Windows 路径转成 WSL 挂载路径，并解析为真实目录。"""
    raw = value.strip()
    matched = re.fullmatch(r"([A-Za-z]):[\\/](.*)", raw)
    if matched:
        raw = f"/mnt/{matched.group(1).lower()}/{matched.group(2).replace(chr(92), '/')}"
    if not raw or not Path(raw).expanduser().is_absolute():
        raise ValueError("请输入绝对的 WSL 或 Windows 目录路径")
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"目录不存在：{value}")
    return path


def require_writable_directory(path: Path) -> None:
    """登记输出位置时短暂创建并自动删除测试文件，及时报告权限问题。"""
    try:
        with tempfile.TemporaryFile(dir=path):
            pass
    except OSError as exc:
        raise ValueError(f"输出目录不可写：{path}") from exc


def list_scenarios_in(root: Path, source_id: str) -> list[dict]:
    """只列出已登记目录中的直接子文件，防止页面指定任意磁盘路径。"""
    if not root.is_dir():
        return []
    result = []
    for path in sorted(root.glob("*.json")):
        if not path.is_file() or path.is_symlink():
            continue
        result.append({"source_id": source_id, "scenario_id": path.stem, "name": path.stem, "sha256": sha256_file(path)})
    return result


def resolve_scenario_in(root: Path, scenario_id: str) -> tuple[Path, str]:
    """ID 只允许简单文件名，解析后仍检查目录边界和符号链接。"""
    if not scenario_id or not scenario_id[0].isalnum() or not all(ch.isalnum() or ch in "_.-" for ch in scenario_id):
        raise ValueError("场景 ID 只能包含字母、数字、下划线、短横线和小数点")
    path = root / f"{scenario_id}.json"
    if path.is_symlink() or not path.is_file() or path.resolve().parent != root.resolve():
        raise FileNotFoundError(f"未登记场景：{scenario_id}")
    return path, sha256_file(path)


def list_scenarios(settings: Settings) -> list[dict]:
    """兼容早期脚本使用的默认场景目录。"""
    return list_scenarios_in(settings.scenario_dir, "runtime")


def resolve_scenario(settings: Settings, scenario_id: str) -> tuple[Path, str]:
    return resolve_scenario_in(settings.scenario_dir, scenario_id)


def algorithm_source_sha256() -> str:
    """对当前算法及共享约束源码做稳定摘要；未把 Git HEAD 冒充实际运行字节。"""
    project = Path(__file__).resolve().parent.parent
    files = []
    for folder in ("algorithms", "schedulers", "core"):
        files.extend((project / folder).rglob("*.py"))
    files.extend([project / "eos_system" / "algorithm_registry.py",
                  project / "eos_system" / "verification.py"])
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(project).as_posix()):
        digest.update(path.relative_to(project).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
