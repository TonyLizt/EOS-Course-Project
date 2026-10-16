"""回放所需的静态场景投影，不在内存中复制百万级窗口/角度数组。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# 保留静态对象原值；不借此重算窗口、修复坐标或修改来源身份。
DISPLAY_FIELDS = frozenset({
    "scenario_id", "scenario_type", "metadata", "satellites", "missions", "ground_stations"
})
FALLBACK_LIMIT = 16 * 1024 * 1024


def file_sha256(path: Path) -> str:
    """按原始字节分块哈希，供独立回放和只读投影共用。"""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_display_scene(path: str | Path) -> dict:
    """完整扫描 JSON，只保留展示字段；缺少 ijson 时只允许小文件回退。"""
    path = Path(path)
    before = path.stat()
    try:
        import ijson
        from ijson.common import ObjectBuilder
    except ImportError:
        if before.st_size > FALLBACK_LIMIT:
            raise ValueError("大型场景投影需要 ijson，请安装 requirements-system.txt")
        with path.open(encoding="utf-8") as stream:
            raw = json.load(stream)
        if not isinstance(raw, dict):
            raise ValueError("场景 JSON 根节点必须是对象")
        result = {key: value for key, value in raw.items() if key in DISPLAY_FIELDS}
    else:
        result, keys = {}, set()
        current, builder = None, None
        first = True
        with path.open("rb") as stream:
            for prefix, event, value in ijson.parse(stream, use_float=True):
                if first:
                    first = False
                    if prefix != "" or event != "start_map":
                        raise ValueError("场景 JSON 根节点必须是对象")
                if prefix == "" and event == "map_key":
                    if value in keys:
                        raise ValueError("场景顶层字段重复：" + value)
                    keys.add(value)
                    current = value
                    builder = ObjectBuilder() if current in DISPLAY_FIELDS else None
                elif current in DISPLAY_FIELDS and prefix != "":
                    builder.event(event, value)
                    # 根字段闭合时保存；未选择的大窗口不会构造成 Python 对象。
                    if prefix == current and event in {
                        "end_map", "end_array", "string", "number", "boolean", "null"
                    }:
                        result[current] = builder.value
                elif prefix == "" and event == "start_array":
                    raise ValueError("场景 JSON 根节点必须是对象")
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ):
        raise ValueError("读取期间场景文件发生变化")
    return result
