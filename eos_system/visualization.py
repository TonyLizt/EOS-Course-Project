"""把旧 Cesium 页面需要的轨道文件按场景哈希生成并缓存。"""

from __future__ import annotations

import fcntl
import hashlib
import importlib.metadata
import json
from functools import lru_cache
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import Settings, sha256_file


class OrbitUnavailable(RuntimeError):
    """Java/Orekit 缺失或轨道生成失败时的受控错误。"""


ORBIT_STEP_S = 300
ORBIT_CACHE_VERSION = 2



@lru_cache(maxsize=8)
def _propagation_signature(identity: tuple) -> str:
    """以文件指纹作为缓存入参，数据包内容变化时重算实际 SHA。"""
    data_path = Path(identity[0])
    data_sha = sha256_file(data_path) if data_path.is_file() else "missing"
    return hashlib.sha256(json.dumps([identity, data_sha], sort_keys=True).encode()).hexdigest()

def propagation_identity() -> str:
    """解析/传播源码、wrapper 与数据包都进入轨道身份，不只依赖场景名。"""
    project = Path(__file__).resolve().parent.parent
    data = project / "utils/orekit-data.zip"
    stat = data.stat() if data.is_file() else None
    try:
        wrapper = importlib.metadata.version("orekit_jpype")
    except importlib.metadata.PackageNotFoundError:
        wrapper = "unavailable"
    identity = (str(data), stat.st_size if stat else 0, stat.st_mtime_ns if stat else 0,
                stat.st_ctime_ns if stat else 0, wrapper,
                *(sha256_file(project/name) for name in (
                    "utils/time_parsing.py", "draw/orekit_to_czml.py", "utils/visibility.py")))
    return "epoch-parser-v1-" + _propagation_signature(identity)

def orbit_cache_file(settings: Settings, scenario_sha: str) -> Path:
    """纯路径计算，供查询、构建和固定缓存测试共同使用；不创建文件。"""
    key = f"{scenario_sha}-v{ORBIT_CACHE_VERSION}-s{ORBIT_STEP_S}-{propagation_identity()[-16:]}"
    return settings.runtime_dir / "visualizations/scenes" / (key + ".czml")

def orbit_cache_path(settings: Settings, scene_path: Path, expected_sha256: str) -> Path:
    """同一场景哈希只生成一次；进程锁避免并发请求看到半写文件。"""
    cache_dir = settings.runtime_dir / "visualizations" / "scenes"
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = orbit_cache_file(settings, expected_sha256)
    cache_key = target.stem
    lock_path = cache_dir / f"{cache_key}.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.is_file() and target.stat().st_size > 0:
            # 已缓存的轨道属于提交时的场景哈希；原始目录以后移动也能回放。
            return target
        if sha256_file(scene_path) != expected_sha256:
            raise ValueError("可视化输入与实验场景哈希不一致")
        project_root = Path(__file__).resolve().parent.parent
        orekit_data = project_root / "utils" / "orekit-data.zip"
        if not orekit_data.is_file():
            raise OrbitUnavailable("缺少 Orekit 轨道数据文件 utils/orekit-data.zip")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix=f".{cache_key}-", suffix=".czml.tmp", dir=cache_dir, delete=False) as stream:
                temporary = Path(stream.name)
            result = subprocess.run(
                [sys.executable, "-m", "eos_system.orbit_generate", "--scenario", str(scene_path),
                 "--output", str(temporary), "--orekit-data", str(orekit_data), "--orbit-step-s", str(ORBIT_STEP_S)],
                cwd=project_root, capture_output=True, text=True, timeout=600, check=False,
            )
            if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
                detail = (result.stderr or result.stdout).strip().splitlines()
                raise OrbitUnavailable("CZML 生成失败：" + (detail[-1][:240] if detail else "无输出"))
            os.replace(temporary, target)
            temporary = None
            return target
        except FileNotFoundError as exc:
            raise OrbitUnavailable("缺少可视化所需的 Java/Orekit 运行依赖") from exc
        except subprocess.TimeoutExpired as exc:
            raise OrbitUnavailable("CZML 生成超过 600 秒") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
