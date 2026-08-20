"""Face- and object-level issue localization for Blender assets."""

from __future__ import annotations

import hashlib
import struct
from typing import Any

import bpy


def topology_fingerprint(obj: bpy.types.Object) -> str:
    """Return a stable local-mesh fingerprint for safe face-index reuse."""
    digest = hashlib.sha256()
    mesh = obj.data
    digest.update(struct.pack("<II", len(mesh.vertices), len(mesh.polygons)))
    for vertex in mesh.vertices:
        for coordinate in vertex.co:
            digest.update(struct.pack("<d", round(float(coordinate), 6)))
    for polygon in mesh.polygons:
        digest.update(struct.pack("<I", len(polygon.vertices)))
        for vertex_index in polygon.vertices:
            digest.update(struct.pack("<I", int(vertex_index)))
    return digest.hexdigest()


def _rounded_vector(value: Any) -> list[float]:
    return [round(float(component), 6) for component in value]


def object_selector(obj: bpy.types.Object, source_index: int) -> dict[str, Any]:
    """Capture identity evidence that survives ordinary FBX/OBJ renaming."""
    return {
        "object_name": obj.name,
        "data_name": getattr(obj.data, "name", ""),
        "source_object_index": int(source_index),
        "vertex_count": len(obj.data.vertices),
        "face_count": len(obj.data.polygons),
        "topology_fingerprint": topology_fingerprint(obj),
        "world_location": _rounded_vector(obj.matrix_world.translation),
        "dimensions": _rounded_vector(obj.dimensions),
        "has_modifiers": bool(obj.modifiers),
        "modifier_types": [str(modifier.type) for modifier in obj.modifiers],
        "face_index_space": "source_mesh_base",
    }


def issue_face_indices(asset: bpy.types.Object, thresholds: dict | None = None) -> dict[str, set[int]]:
    """Locate faces that can be visualized in the issue-overlay GLB."""
    thresholds = thresholds or {}
    mesh = asset.data
    edge_faces: dict[tuple[int, int], list[int]] = {}
    directed_edges: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for poly in mesh.polygons:
        verts = list(poly.vertices)
        for left, right in zip(verts, verts[1:] + verts[:1]):
            key = tuple(sorted((left, right)))
            edge_faces.setdefault(key, []).append(poly.index)
            direction = 1 if (left, right) == key else -1
            directed_edges.setdefault(key, []).append((poly.index, direction))

    result = {
        "degenerate_faces": set(), "hole": set(), "non_manifold": set(),
        "flipped_normals": set(), "stretched_triangles": set(), "uv_overlap": set(),
    }
    for faces in edge_faces.values():
        if len(faces) == 1:
            result["hole"].add(faces[0])
        if len(faces) > 2:
            result["non_manifold"].update(faces)
    for uses in directed_edges.values():
        if len(uses) == 2 and uses[0][1] == uses[1][1]:
            result["flipped_normals"].update(item[0] for item in uses)

    uv_layer = mesh.uv_layers.active
    uv_faces: dict[tuple[tuple[float, float], ...], list[int]] = {}
    aspect_limit = float(thresholds.get("max_triangle_aspect_p95", 8.0))
    for poly in mesh.polygons:
        if poly.area < 1e-8:
            result["degenerate_faces"].add(poly.index)
        vertices = [mesh.vertices[index].co.copy() for index in poly.vertices]
        for index in range(1, max(1, len(vertices) - 1)):
            if len(vertices) < 3:
                break
            a, b, c = vertices[0], vertices[index], vertices[index + 1]
            lengths = [(a - b).length, (b - c).length, (c - a).length]
            shortest = min(lengths)
            if shortest > 1e-8 and max(lengths) / shortest > aspect_limit:
                result["stretched_triangles"].add(poly.index)
        if uv_layer and len(poly.loop_indices) >= 3:
            points = tuple(sorted(
                (round(float(uv_layer.data[loop].uv.x), 6), round(float(uv_layer.data[loop].uv.y), 6))
                for loop in list(poly.loop_indices)[:3]
            ))
            uv_faces.setdefault(points, []).append(poly.index)
    for faces in uv_faces.values():
        if len(faces) > 1:
            result["uv_overlap"].update(faces)
    return result


def issue_breakdown_by_object(mesh_objects: list[bpy.types.Object], thresholds: dict | None = None) -> list[dict[str, Any]]:
    """Keep issue evidence tied to source objects before they are joined."""
    thresholds = thresholds or {}
    uv_owners: dict[tuple[tuple[float, float], ...], list[tuple[str, int]]] = {}
    for source_index, obj in enumerate(mesh_objects):
        uv_layer = obj.data.uv_layers.active
        if not uv_layer:
            continue
        for poly in obj.data.polygons:
            if len(poly.loop_indices) < 3:
                continue
            points = tuple(sorted(
                (round(float(uv_layer.data[loop].uv.x), 6), round(float(uv_layer.data[loop].uv.y), 6))
                for loop in list(poly.loop_indices)[:3]
            ))
            uv_owners.setdefault(points, []).append((obj.name, poly.index))
    cross_object_uv_faces: dict[str, set[int]] = {}
    for owners in uv_owners.values():
        owner_objects = {name for name, _ in owners}
        if len(owner_objects) < 2:
            continue
        for name, face_index in owners:
            cross_object_uv_faces.setdefault(name, set()).add(face_index)

    limit = min(int(thresholds.get("max_diagnostic_triangles", 50_000)), 2_000)
    breakdown = []
    for obj in mesh_objects:
        face_issues = issue_face_indices(obj, thresholds)
        counts = {key: len(value) for key, value in face_issues.items() if value}
        uv_faces = set(face_issues.get("uv_overlap", set())) | cross_object_uv_faces.get(obj.name, set())
        if uv_faces:
            counts["uv_overlap"] = len(uv_faces)
        if not counts:
            continue
        related_indices = {key: sorted(values)[:limit] for key, values in face_issues.items() if values}
        if uv_faces:
            related_indices["uv_overlap"] = sorted(uv_faces)[:limit]
        selector = object_selector(obj, source_index)
        breakdown.append({
            "object_name": obj.name,
            "source_object_index": source_index,
            "face_count": len(obj.data.polygons),
            "topology_fingerprint": selector["topology_fingerprint"],
            "object_selector": selector,
            "face_index_space": "source_mesh_base",
            "related_face_counts": counts,
            "related_face_indices": related_indices,
        })
    return breakdown
