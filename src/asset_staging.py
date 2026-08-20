"""Validate and stage uploaded assets before Blender opens them."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_SUFFIXES = {".blend", ".fbx", ".obj"}
TEXTURE_KEYS = {
    "map_kd", "map_ks", "map_ns", "map_d", "map_bump", "bump", "disp",
    "decal", "refl", "norm", "map_pr", "map_pm", "map_ke",
}


@dataclass(frozen=True)
class StagedAsset:
    source_path: Path
    staged_path: Path
    source_size_bytes: int
    source_sha256: str
    sidecar_files: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "source_file": self.source_path.name,
            "staged_file": self.staged_path.name,
            "source_size_bytes": self.source_size_bytes,
            "source_sha256": self.source_sha256,
            "sidecar_files": list(self.sidecar_files),
            "warnings": list(self.warnings),
        }


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(path: Path, root: Path) -> Path | None:
    """Return a safe relative path only for resources under the source folder."""
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    if relative.is_absolute() or ".." in relative.parts:
        return None
    return relative


def _copy_resource(source: Path, source_root: Path, stage_root: Path, copied: set[str], warnings: list[str]) -> None:
    if not source.exists() or not source.is_file():
        warnings.append(f"Missing referenced resource: {source}")
        return
    relative = _safe_relative_path(source, source_root)
    if relative is None:
        warnings.append(f"Skipped resource outside asset directory: {source}")
        return
    target = stage_root / relative
    key = str(relative).replace("\\", "/")
    if key in copied:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    copied.add(key)


def _parse_mtl_resources(mtl_path: Path) -> list[Path]:
    resources: list[Path] = []
    try:
        lines = mtl_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return resources
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(None, 1)
        if len(parts) != 2 or parts[0].lower() not in TEXTURE_KEYS:
            continue
        try:
            tokens = shlex.split(parts[1], posix=True)
        except ValueError:
            tokens = parts[1].split()
        if tokens:
            resources.append((mtl_path.parent / tokens[-1]).resolve())
    return resources


def _obj_sidecars(source: Path, stage_root: Path, copied: set[str], warnings: list[str]) -> None:
    source_root = source.parent.resolve()
    try:
        lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        warnings.append(f"OBJ sidecar scan failed: {exc}")
        return
    for line in lines:
        if not re.match(r"^\s*mtllib\s+", line, re.IGNORECASE):
            continue
        raw_reference = re.sub(r"^\s*mtllib\s+", "", line, flags=re.IGNORECASE).strip()
        if not raw_reference:
            continue
        mtl_path = (source_root / raw_reference).resolve()
        _copy_resource(mtl_path, source_root, stage_root, copied, warnings)
        for texture in _parse_mtl_resources(mtl_path):
            _copy_resource(texture, source_root, stage_root, copied, warnings)


def _fbx_sidecars(source: Path, stage_root: Path, copied: set[str], warnings: list[str]) -> None:
    """Preserve the common FBX texture sidecar folder without copying its parent."""
    sidecar_dir = source.with_suffix(".fbm")
    if not sidecar_dir.is_dir():
        return
    source_root = source.parent.resolve()
    for resource in sidecar_dir.rglob("*"):
        if resource.is_file():
            _copy_resource(resource, source_root, stage_root, copied, warnings)


def stage_asset(source: Path, job_dir: Path, max_size_bytes: int = 2_147_483_648) -> StagedAsset:
    """Validate and copy an asset plus safe, locally referenced sidecars."""
    source = source.expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise ValueError(f"Asset file not found: {source}")
    if source.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("Supported formats are .blend, .fbx, and .obj.")
    size_bytes = source.stat().st_size
    if size_bytes > max_size_bytes:
        limit_mb = max_size_bytes / (1024 * 1024)
        raise ValueError(f"Asset is too large ({size_bytes / (1024 * 1024):.1f} MB). The configured limit is {limit_mb:.1f} MB.")
    job_dir.mkdir(parents=True, exist_ok=True)
    staged = job_dir / source.name
    shutil.copy2(source, staged)
    copied: set[str] = {source.name}
    warnings: list[str] = []
    if source.suffix.lower() == ".obj":
        _obj_sidecars(source, job_dir, copied, warnings)
    elif source.suffix.lower() == ".fbx":
        _fbx_sidecars(source, job_dir, copied, warnings)
    result = StagedAsset(source, staged, size_bytes, _sha256(source), tuple(sorted(copied - {source.name})), tuple(warnings))
    (job_dir / "staging.json").write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return result
