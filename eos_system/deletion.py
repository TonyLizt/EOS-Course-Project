"""按实验清理可选导出文件；输入场景和共享轨道缓存不属于单次实验。"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from .config import sha256_file


def remove_exported_files(deleted: dict) -> tuple[int, list[str]]:
    """仅删除路径、文件名和哈希都与本实验记录一致的正式导出。"""
    run_id = deleted["run_id"]
    try:
        if str(UUID(run_id)) != run_id:
            raise ValueError("运行 ID 不是标准 UUID")
    except ValueError:
        return 0, ["运行 ID 不是标准 UUID，未清理目录文件"]
    root_value = deleted["config"].get("output_root")
    if not root_value:
        return 0, []
    root = Path(root_value)
    folder = root / run_id
    removed = 0
    warnings: list[str] = []
    if root.is_symlink() or not root.is_dir() or folder.is_symlink() or not folder.is_dir():
        return 0, ["原输出目录已不存在或不是普通目录，未删除导出文件"]
    for item in deleted["exports"]:
        if item["status"] != "SUCCEEDED" or not item["artifact_path"]:
            continue
        name = f"eos-{run_id}.{item['format']}"
        target = folder / name
        # 数据库里的旧路径不能指向任意位置；符号链接和被改写的文件也不删除。
        if Path(item["artifact_path"]) != target or target.is_symlink() or not target.is_file():
            warnings.append(f"{name} 路径已变化或文件不存在，已跳过")
            continue
        try:
            digest = sha256_file(target)
            if digest != item["artifact_sha256"]:
                warnings.append(f"{name} 内容已变化，已跳过")
                continue
            target.unlink()
            removed += 1
        except OSError as exc:
            warnings.append(f"{name} 删除失败：{exc}")
    try:
        folder.rmdir()  # 仅移除已空的本实验目录，不递归删除用户其他文件。
    except OSError:
        pass
    return removed, warnings
