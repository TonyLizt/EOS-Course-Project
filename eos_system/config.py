"""系统运行配置和只读场景登记。

配置集中在这一层，避免把某位组员的 Windows 盘符写死在业务代码里。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from functools import lru_cache
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
        configured_scenarios = os.environ.get("EOS_SCENARIO_DIR")
        if configured_scenarios:
            scenarios = Path(configured_scenarios).expanduser().resolve()
        else:
            runtime_scenarios = runtime / "scenarios"
            project_scenarios = Path(__file__).resolve().parent.parent / "experiments" / "scenarios"
            has_runtime_scenarios = (runtime_scenarios.is_dir()
                                     and any(runtime_scenarios.rglob("*.json")))
            scenarios = (runtime_scenarios
                         if has_runtime_scenarios or not project_scenarios.is_dir()
                         else project_scenarios)
        # 命令行环境变量优先；网页保存的并发设置位于运行目录，不进入仓库。
        saved = runtime / 'execution-settings.json'
        stored = json.loads(saved.read_text(encoding='utf-8')) if saved.is_file() else {}
        workers = int(os.environ.get('EOS_MAX_WORKERS', stored.get('max_workers', 2)))
        if not 1 <= workers <= 8:
            raise ValueError('EOS_MAX_WORKERS 必须为 1 到 8')
        return cls(runtime_dir=runtime, scenario_dir=scenarios, max_workers=workers)

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


@lru_cache(maxsize=64)
def _catalog_sha256(path: str, size: int, modified: int, changed: int) -> str:
    """仅目录列表复用未变化文件的 SHA；实验提交仍调用 sha256_file 重新校验。"""
    return sha256_file(Path(path))


def _listing_sha(path: Path) -> str:
    stat = path.stat()
    digest = _catalog_sha256(str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    after = path.stat()
    if (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) != (
        after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ):
        raise ValueError("列目录期间场景发生变化，请刷新后重试")
    return digest


def _released_epoch_scenario(path: Path, *, planning_preview: bool = False) -> bool:
    """Return whether an epoch-fixed file can actually be submitted.

    A candidate file without its matching release evidence must not hide the
    usable legacy sibling or appear in the experiment picker.  Submission
    repeats the same provenance check, so this is only a catalog filter rather
    than a weakened trust boundary.
    """
    if not path.is_file() or path.is_symlink() or not path.stem.endswith("_epoch_fixed_v1"):
        return False
    try:
        from .provenance import capture_provenance
        from utils.continuous_exposure import planning_evidence
        scenario_sha = _listing_sha(path)
        capture_provenance(path, scenario_sha)
        if planning_preview:
            return True  # Published lineage is retained; no continuous proof is asserted.
        # The earlier release sidecar proves lineage and sampled checks only.
        # It must not make a scenario selectable unless its window-generation
        # evidence also satisfies the current conservative planning contract.
        # Sidecar-backed candidates need no second full parse of the large JSON.
        return planning_evidence({"metadata": {}}, path, scenario_sha) is not None
    except (OSError, ValueError, TypeError):
        return False


def list_scenarios_in(root: Path, source_id: str, *, planning_preview: bool = False) -> list[dict]:
    """递归列出已登记目录中的 JSON；ID 是不含扩展名的安全相对路径。"""
    if not root.is_dir():
        return []
    result = []
    resolved_root = root.resolve()
    for path in sorted(root.rglob("*.json")):
        relative_path = path.relative_to(root)
        if (not path.is_file() or path.is_symlink()
                or not path.resolve().is_relative_to(resolved_root)
                or "provenance" in relative_path.parts):
            continue
        is_epoch_fixed = path.stem.endswith("_epoch_fixed_v1")
        if is_epoch_fixed and not _released_epoch_scenario(path, planning_preview=planning_preview):
            continue
        # Only a formally released corrected sibling may replace the legacy
        # picker entry.  Candidate-only or incomplete output stays invisible.
        if (not is_epoch_fixed
                and _released_epoch_scenario(
                    path.with_name(path.stem + "_epoch_fixed_v1.json"), planning_preview=planning_preview
                )):
            continue
        relative = relative_path.with_suffix("")
        scenario_id = relative.as_posix()
        result.append({"source_id": source_id, "scenario_id": scenario_id,
                       "name": scenario_id, "sha256": _listing_sha(path)})
    return result


def resolve_scenario_in(root: Path, scenario_id: str) -> tuple[Path, str]:
    """ID 允许安全相对路径，解析后仍检查登记根目录边界和符号链接。"""
    relative = Path(scenario_id)
    valid_parts = (not relative.is_absolute() and bool(relative.parts)
                   and all(part and part not in {".", ".."}
                           and part[0].isalnum()
                           and all(ch.isalnum() or ch in "_.-" for ch in part)
                           for part in relative.parts))
    if not valid_parts:
        raise ValueError("场景 ID 只能是由字母、数字、下划线、短横线和小数点组成的安全相对路径")
    path = root / f"{scenario_id}.json"
    if (path.is_symlink() or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve())):
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
    files.extend([project / "utils" / "continuous_exposure.py",
                  project / "utils" / "visibility.py", project / "utils" / "time_parsing.py",
                  project / "eos_system" / "algorithm_registry.py",
                  project / "eos_system" / "verification.py"])
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(project).as_posix()):
        digest.update(path.relative_to(project).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
