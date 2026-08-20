"""Small valid binary artifacts used by runtime validation tests."""

from __future__ import annotations

import json
import struct
import zlib

from src.runtime_artifacts import PNG_SIGNATURE


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def png_bytes(varied: bool = True, width: int = 2, height: int = 2, sparse: bool = False) -> bytes:
    """Return a small RGB PNG with deterministic dark/light content."""
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            light = varied and ((x == 0 and y == 0) if sparse else (x + y) % 2 == 1)
            rows.extend((255, 255, 255) if light else (0, 0, 0))
    return PNG_SIGNATURE + _png_chunk(b"IHDR", header) + _png_chunk(b"IDAT", zlib.compress(rows)) + _png_chunk(b"IEND", b"")


def glb_bytes(marker: bool = False) -> bytes:
    """Return a minimal glTF 2.0 scene containing one non-indexed triangle."""
    positions = struct.pack("<9f", 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "buffers": [{"byteLength": len(positions)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(positions)}],
        "accessors": [{
            "bufferView": 0,
            "componentType": 5126,
            "count": 3,
            "type": "VEC3",
            "min": [0, 0, 0],
            "max": [1, 1, 0],
        }],
    }
    if marker:
        document["materials"] = [{
            "name": "issue_overlay_marker",
            "pbrMetallicRoughness": {"baseColorFactor": [1.0, 0.05, 0.02, 1.0]},
        }]
    json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    binary_chunk = positions + b"\x00" * ((4 - len(positions) % 4) % 4)
    chunks = (
        struct.pack("<II", len(json_chunk), 0x4E4F534A) + json_chunk
        + struct.pack("<II", len(binary_chunk), 0x004E4942) + binary_chunk
    )
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks
