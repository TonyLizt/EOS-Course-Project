"""Validated public model resources that participate in replay identity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contracts import ReplayConfig


def load_model_resources(config: ReplayConfig, project_root: Path) -> tuple[list[dict], str]:
    manifest_path = project_root / "assets" / "satellites" / "asset-manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    by_id = {item["asset_id"]: item for item in manifest.get("assets", [])}
    resources = []
    for asset_id in sorted({model.model_asset_id for model in config.models}):
        if asset_id not in by_id:
            raise ValueError(f"model asset is absent from asset manifest: {asset_id}")
        item = by_id[asset_id]
        target = (project_root / item["local_path"]).resolve()
        if not target.is_relative_to(project_root.resolve()) or not target.is_file():
            raise ValueError(f"model asset path is unavailable: {asset_id}")
        actual_sha = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual_sha != item.get("sha256"):
            raise ValueError(f"model asset hash differs from asset manifest: {asset_id}")
        uris = sorted({model.uri for model in config.models if model.model_asset_id == asset_id})
        resources.append({
            "asset_id": asset_id,
            "uris": uris,
            "sha256": actual_sha,
            "size_bytes": target.stat().st_size,
            "source_page": item.get("source_page"),
            "credit": item.get("credit"),
            "role": item.get("role"),
        })
    return resources, hashlib.sha256(manifest_bytes).hexdigest()
