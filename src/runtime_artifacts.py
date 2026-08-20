"""Validate files emitted by a Blender inspection job."""

from __future__ import annotations

import json
import struct
import zlib
from collections import Counter
from pathlib import Path
from typing import Any


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
GLB_SIGNATURE = b"glTF"
REQUIRED_IMAGE_KEYS = ("uv", "uv_heatmap", "normal", "model")
REQUIRED_ARTIFACT_KEYS = ("issue_locator", "issue_selection_script")
OPTIONAL_GLTF_KEYS = ("model_overlay",)


def _file_failure(label: str, path: Any) -> dict[str, str] | None:
    if not path:
        return {"artifact": label, "reason": "not listed in resolved runtime paths"}
    file_path = Path(str(path))
    if not file_path.is_file():
        return {"artifact": label, "reason": f"file does not exist: {file_path}"}
    if file_path.stat().st_size == 0:
        return {"artifact": label, "reason": "file is empty"}
    return None


def _paeth_predictor(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    distance_left = abs(estimate - left)
    distance_above = abs(estimate - above)
    distance_upper_left = abs(estimate - upper_left)
    if distance_left <= distance_above and distance_left <= distance_upper_left:
        return left
    if distance_above <= distance_upper_left:
        return above
    return upper_left


def _parse_png(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Parse PNG structure and decode common 8-bit scanlines for blank checks."""
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        return None, "file is not a PNG"
    position = len(PNG_SIGNATURE)
    header: tuple[int, int, int, int, int] | None = None
    compressed: list[bytes] = []
    saw_iend = False
    while position + 12 <= len(data):
        length = struct.unpack(">I", data[position:position + 4])[0]
        chunk_type = data[position + 4:position + 8]
        end = position + 12 + length
        if end > len(data):
            return None, "truncated PNG chunk"
        chunk = data[position + 8:position + 8 + length]
        expected_crc = struct.unpack(">I", data[end - 4:end])[0]
        actual_crc = zlib.crc32(chunk_type + chunk) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            return None, f"PNG chunk CRC mismatch for {chunk_type.decode('ascii', errors='replace')}"
        if chunk_type == b"IHDR":
            if length != 13:
                return None, "PNG IHDR has an invalid length"
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
            header = (width, height, bit_depth, color_type, interlace)
            if compression != 0 or filter_method != 0:
                return None, "PNG uses an unsupported compression or filter method"
        elif chunk_type == b"IDAT":
            compressed.append(chunk)
        elif chunk_type == b"IEND":
            saw_iend = True
            break
        position = end
    if header is None:
        return None, "PNG has no IHDR chunk"
    if not saw_iend:
        return None, "PNG has no IEND chunk"
    width, height, bit_depth, color_type, interlace = header
    if width < 2 or height < 2:
        return None, f"PNG dimensions are too small: {width}x{height}"
    info: dict[str, Any] = {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "content_checkable": False,
        "pixel_variation": None,
    }
    if bit_depth != 8 or interlace != 0 or color_type not in {0, 2, 3, 4, 6} or not compressed:
        return info, None
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    row_bytes = width * channels
    try:
        raw = zlib.decompress(b"".join(compressed))
    except zlib.error as exc:
        return None, f"PNG pixel data cannot be decompressed: {exc}"
    expected_size = height * (row_bytes + 1)
    if len(raw) != expected_size:
        return None, f"PNG scanline data has invalid length: {len(raw)} != {expected_size}"
    rows: list[bytes] = []
    offset = 0
    previous = bytearray(row_bytes)
    for _ in range(height):
        filter_type = raw[offset]
        encoded = raw[offset + 1:offset + 1 + row_bytes]
        offset += row_bytes + 1
        current = bytearray(row_bytes)
        for index, value in enumerate(encoded):
            left = current[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                predictor = _paeth_predictor(left, above, upper_left)
            else:
                return None, f"PNG uses an invalid scanline filter: {filter_type}"
            current[index] = (value + predictor) & 0xFF
        rows.append(bytes(current))
        previous = current
    unique_pixels: set[bytes] = set()
    decoded_rows: list[bytes] = rows
    for row in rows:
        for offset in range(0, len(row), channels):
            unique_pixels.add(row[offset:offset + channels])
            if len(unique_pixels) > 1:
                break
        if len(unique_pixels) > 1:
            break
    info["content_checkable"] = True
    info["pixel_variation"] = len(unique_pixels) > 1
    if width >= 16 and height >= 16:
        pixels: list[tuple[int, ...]] = []
        for row in decoded_rows:
            pixels.extend(tuple(row[index:index + channels]) for index in range(0, len(row), channels))
        quantized = Counter(tuple(min(channel // 32, 7) for channel in pixel[:3]) for pixel in pixels)
        luminance = [sum(pixel[:3]) / 3 for pixel in pixels]
        edge_count = 0
        for y in range(height):
            row_start = y * width
            for x in range(width):
                current = pixels[row_start + x]
                current_luma = luminance[row_start + x]
                if x + 1 < width and abs(current_luma - luminance[row_start + x + 1]) >= 24:
                    edge_count += 1
                if y + 1 < height and abs(current_luma - luminance[row_start + width + x]) >= 24:
                    edge_count += 1
        info["quantized_color_count"] = len(quantized)
        info["dominant_color_fraction"] = max(quantized.values()) / len(pixels) if pixels else 1.0
        info["edge_density"] = edge_count / max(1, 2 * width * height - width - height)
        info["bright_fraction"] = sum(value >= 150 for value in luminance) / max(1, len(luminance))
        info["dark_fraction"] = sum(value <= 45 for value in luminance) / max(1, len(luminance))
    return info, None


def _read_glb_document(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read a GLB JSON chunk after validating its container boundaries."""
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != GLB_SIGNATURE:
        return None, "file is not a GLB container"
    version, declared_length = struct.unpack("<II", data[4:12])
    if version != 2:
        return None, f"unsupported GLB version: {version}"
    if declared_length != len(data):
        return None, f"GLB length mismatch: header={declared_length}, file={len(data)}"
    position = 12
    document: dict[str, Any] | None = None
    while position + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack("<II", data[position:position + 8])
        start = position + 8
        end = start + chunk_length
        if end > len(data):
            return None, "GLB chunk exceeds file length"
        chunk = data[start:end]
        if chunk_type == 0x4E4F534A:
            try:
                document = json.loads(chunk.rstrip(b" \t\r\n\x00").decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                return None, f"GLB JSON chunk is invalid: {exc}"
        position = end
    if position != len(data):
        return None, "GLB has trailing incomplete chunk data"
    return document, None


def _parse_glb(path: Path) -> str | None:
    """Validate the GLB container and require at least one renderable mesh."""
    document, error = _read_glb_document(path)
    if error:
        return error
    if not isinstance(document, dict) or document.get("asset", {}).get("version") != "2.0":
        return "GLB JSON has no glTF 2.0 asset declaration"
    meshes = document.get("meshes")
    if not isinstance(meshes, list) or not meshes:
        return "GLB contains no mesh"
    if not any(isinstance(mesh, dict) and mesh.get("primitives") for mesh in meshes):
        return "GLB meshes contain no primitives"
    scenes = document.get("scenes")
    if scenes is not None and (not isinstance(scenes, list) or not scenes):
        return "GLB contains no scene"
    return None


def _overlay_has_marker_content(path: Path) -> bool:
    """Require an overlay to contain a plausible issue marker signal."""
    document, error = _read_glb_document(path)
    if error or not isinstance(document, dict):
        return False
    marker_words = ("issue", "overlay", "degenerate", "hole", "uv", "normal", "manifold", "stretch")
    for collection_key in ("nodes", "meshes", "materials"):
        for item in document.get(collection_key, []) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).casefold()
            if any(word in name for word in marker_words):
                return True
            if collection_key == "materials":
                factor = (item.get("pbrMetallicRoughness", {}) or {}).get("baseColorFactor")
                if isinstance(factor, list) and len(factor) >= 3:
                    try:
                        color_range = max(float(value) for value in factor[:3]) - min(float(value) for value in factor[:3])
                    except (TypeError, ValueError):
                        color_range = 0.0
                    if color_range >= 0.35:
                        return True
    return False


def _validate_png_artifact(
    label: str,
    path: Path,
    *,
    require_variation: bool = True,
    semantic: str | None = None,
) -> dict[str, str] | None:
    info, error = _parse_png(path)
    if error:
        return {"artifact": label, "reason": error}
    if require_variation and info and info.get("content_checkable") and not info.get("pixel_variation"):
        return {"artifact": label, "reason": "PNG evidence is uniform and may be blank"}
    if info and info.get("content_checkable") and info.get("width", 0) >= 16 and info.get("height", 0) >= 16:
        if semantic == "uv_lines" and info.get("edge_density", 0.0) < 0.001:
            return {"artifact": label, "reason": "UV evidence has no detectable line structure"}
        if semantic == "heatmap" and (
            info.get("quantized_color_count", 0) < 2
            or info.get("dominant_color_fraction", 1.0) >= 0.995
        ):
            return {"artifact": label, "reason": "UV heatmap has no meaningful color distribution"}
    return None


def _uv_is_available(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata", {}) or {}
    if not isinstance(metadata, dict):
        return False
    try:
        uv_layer_count = int(metadata.get("uv_layer_count", metadata.get("source_uv_layer_count", 0)) or 0)
    except (TypeError, ValueError):
        uv_layer_count = 0
    return uv_layer_count > 0 and metadata.get("uv_status", "present") != "not_present"


def validate_runtime_artifacts(row: dict[str, Any], paths: dict[str, Any]) -> list[dict[str, str]]:
    """Return actionable failures for required inspection outputs.

    ``paths`` must come from the safe manifest resolver. This function checks
    content signatures as well, because a zero-byte or wrong-format file can
    still exist after a partially failed Blender render.
    """
    failures: list[dict[str, str]] = []
    views = paths.get("views", []) or []
    if not views:
        failures.append({"artifact": "views", "reason": "no multi-view preview was produced"})
    for index, view in enumerate(views):
        failure = _file_failure(f"views[{index}]", view)
        if failure:
            failures.append(failure)
        else:
            failure = _validate_png_artifact(f"views[{index}]", Path(str(view)))
            if failure:
                failures.append(failure)

    uv_available = _uv_is_available(row)
    for key in REQUIRED_IMAGE_KEYS:
        failure = _file_failure(key, paths.get(key))
        if failure:
            failures.append(failure)
            continue
        file_path = Path(str(paths[key]))
        if key == "model":
            error = _parse_glb(file_path)
            if error:
                failures.append({"artifact": key, "reason": error})
        else:
            # A no-UV asset may legitimately produce a uniform placeholder UV
            # diagnostic. That is a valid "not applicable" evidence state,
            # not a broken render; other raster evidence still needs variation.
            require_variation = not (key in {"uv", "uv_heatmap"} and not uv_available)
            semantic = "uv_lines" if key == "uv" and uv_available else "heatmap" if key == "uv_heatmap" and uv_available else None
            failure = _validate_png_artifact(
                key,
                file_path,
                require_variation=require_variation,
                semantic=semantic,
            )
            if failure:
                failures.append(failure)

    for key in OPTIONAL_GLTF_KEYS:
        if not paths.get(key):
            continue
        failure = _file_failure(key, paths.get(key))
        if failure:
            failures.append(failure)
            continue
        error = _parse_glb(Path(str(paths[key])))
        if error:
            failures.append({"artifact": key, "reason": error})
        elif key == "model_overlay":
            metadata = row.get("metadata", {}) or {}
            related_counts = metadata.get("issue_related_face_counts", {}) if isinstance(metadata, dict) else {}
            marker_expected = bool(metadata.get("issue_overlay_available")) and any(
                int(value or 0) > 0 for value in (related_counts or {}).values()
            )
            if marker_expected and not _overlay_has_marker_content(Path(str(paths[key]))):
                failures.append({"artifact": key, "reason": "issue overlay contains no recognizable marker material or issue mesh"})

    for key in REQUIRED_ARTIFACT_KEYS:
        failure = _file_failure(key, paths.get(key))
        if failure:
            failures.append(failure)
            continue
        file_path = Path(str(paths[key]))
        try:
            if key == "issue_locator":
                payload = json.loads(file_path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict) or not payload.get("schema_version"):
                    failures.append({"artifact": key, "reason": "locator JSON has no schema_version"})
                if not isinstance(payload.get("source_issue_breakdown"), list):
                    failures.append({"artifact": key, "reason": "locator JSON has no source_issue_breakdown list"})
            else:
                compile(file_path.read_text(encoding="utf-8"), str(file_path), "exec")
        except (OSError, UnicodeError, json.JSONDecodeError, SyntaxError) as exc:
            failures.append({"artifact": key, "reason": f"invalid content: {exc}"})
    return failures
