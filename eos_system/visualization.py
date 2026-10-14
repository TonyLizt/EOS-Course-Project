"""把旧 Cesium 页面需要的轨道文件按场景哈希生成并缓存。"""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import Settings, sha256_file


class OrbitUnavailable(RuntimeError):
    """Java/Orekit 缺失或轨道生成失败时的受控错误。"""


ORBIT_STEP_S = 300
ORBIT_CACHE_VERSION = 1


def orbit_cache_path(settings: Settings, scene_path: Path, expected_sha256: str) -> Path:
    """同一场景哈希只生成一次；进程锁避免并发请求看到半写文件。"""
    cache_dir = settings.runtime_dir / "visualizations" / "scenes"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key = f"{expected_sha256}-v{ORBIT_CACHE_VERSION}-s{ORBIT_STEP_S}"
    target = cache_dir / f"{cache_key}.czml"
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
