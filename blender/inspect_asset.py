"""Render one arbitrary .blend, .fbx, or .obj file for the local quality-inspection demo.

Run from Blender:
  blender -b -P blender/inspect_asset.py -- --input asset.fbx --out runtime_dir

The source .blend is never saved or modified. The output directory contains
rendered evidence and a runtime manifest consumed by ``demo/app.py``.
"""

from __future__ import annotations

import argparse
import bmesh
import json
import math
import re
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

# Blender's background runner does not always put the script directory on
# sys.path. Add it explicitly so the shared generator utilities work both from
# the repository root and from a direct ``blender -P`` invocation.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from generate_scene_dataset import (
    configure_render,
    diagnostic_material,
    geometry_stats,
    look_at,
    mat,
    render,
    render_diagnostic,
)

DEFAULT_THRESHOLDS = SCRIPT_DIR.parent / "config" / "inspection_thresholds.json"


def load_thresholds(path: Path) -> dict:
    defaults = {
        "max_faces": 50_000,
        "max_uv_overlap_ratio": 0.001,
        "max_triangle_aspect_p95": 8.0,
        "max_texture_size": 4096,
        "min_texture_size": 512,
        "max_material_slots": 8,
        "max_draw_calls": 100,
        "max_texture_memory_bytes": 1_073_741_824,
        "max_estimated_load_time_seconds": 8.0,
        "max_influences_per_vertex": 4,
        "weight_sum_tolerance": 0.05,
        "max_unbound_vertex_ratio": 0.01,
        "max_weight_error_ratio": 0.01,
        "max_material_slots_per_object": 8,
        "max_diagnostic_triangles": 50_000,
        "max_component_gap_pairs": 200_000,
    }
    try:
        loaded = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        defaults.update({key: value for key, value in loaded.items() if key in defaults})
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return defaults


def choose_geometry_adaptive_settings(args: argparse.Namespace, thresholds: dict, geometry: dict) -> dict:
    """Reduce expensive evidence rendering when imported geometry is genuinely large."""
    triangle_count = int(geometry.get("triangle_count", 0) or 0)
    vertex_count = int(geometry.get("vertex_count", 0) or 0)
    requested_views = int(args.views)
    requested_resolution = int(args.resolution)
    requested_limit = int(thresholds.get("max_diagnostic_triangles", 50_000))
    if triangle_count >= 1_000_000:
        strategy = "geometry_ultra_conservative"
        views, resolution, diagnostic_limit = 1, min(requested_resolution, 96), min(requested_limit, 10_000)
        reason = "triangle_count >= 1,000,000"
    elif triangle_count >= 250_000:
        strategy = "geometry_large_conservative"
        views, resolution, diagnostic_limit = min(requested_views, 2), min(requested_resolution, 128), min(requested_limit, 20_000)
        reason = "triangle_count >= 250,000"
    elif triangle_count >= 100_000:
        strategy = "geometry_large_balanced"
        views, resolution, diagnostic_limit = min(requested_views, 3), min(requested_resolution, 160), min(requested_limit, 30_000)
        reason = "triangle_count >= 100,000"
    else:
        strategy = "geometry_default"
        views, resolution, diagnostic_limit = requested_views, requested_resolution, requested_limit
        reason = "triangle_count below adaptive geometry thresholds"
    return {
        "strategy": strategy,
        "reason": reason,
        "vertex_count": vertex_count,
        "triangle_count": triangle_count,
        "requested_views": requested_views,
        "requested_resolution": requested_resolution,
        "requested_max_diagnostic_triangles": requested_limit,
        "effective_views": max(1, min(8, views)),
        "effective_resolution": max(64, resolution),
        "effective_max_diagnostic_triangles": max(1, diagnostic_limit),
    }


def remove_cameras_and_lights() -> None:
    for obj in list(bpy.context.scene.objects):
        if obj.type in {"CAMERA", "LIGHT"}:
            bpy.data.objects.remove(obj, do_unlink=True)


def join_meshes() -> bpy.types.Object:
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("The .blend file contains no mesh objects.")
    active = max(meshes, key=lambda obj: len(obj.data.polygons))
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active
    if len(meshes) > 1:
        bpy.ops.object.join()
    asset = bpy.context.object
    asset.name = "uploaded_asset"
    return asset


def ensure_uv(asset: bpy.types.Object) -> None:
    if asset.data.uv_layers.active:
        return
    bpy.context.view_layer.objects.active = asset
    asset.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.03)
    bpy.ops.object.mode_set(mode="OBJECT")


def normalize_asset(asset: bpy.types.Object) -> None:
    bpy.context.view_layer.update()
    corners = [asset.matrix_world @ Vector(corner) for corner in asset.bound_box]
    center = sum(corners, Vector()) / len(corners)
    asset.location -= center
    dimensions = asset.dimensions
    largest = max(float(dimensions.x), float(dimensions.y), float(dimensions.z), 1e-6)
    factor = 2.6 / largest
    asset.scale = asset.scale * factor
    bpy.context.view_layer.update()


def import_input_asset(input_path: Path) -> None:
    """Open a Blender file or import a supported interchange format."""
    suffix = input_path.suffix.lower()
    if suffix == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(input_path.resolve()))
        return
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if suffix == ".fbx":
        if not hasattr(bpy.ops.import_scene, "fbx"):
            raise RuntimeError("This Blender build does not provide the FBX importer.")
        bpy.ops.import_scene.fbx(filepath=str(input_path.resolve()))
        return
    if suffix == ".obj":
        # Blender 4+ exposes the OBJ importer under wm; retain the legacy
        # operator as a fallback for older Blender installations.
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=str(input_path.resolve()))
        elif hasattr(bpy.ops.import_scene, "obj"):
            bpy.ops.import_scene.obj(filepath=str(input_path.resolve()))
        else:
            raise RuntimeError("This Blender build does not provide the OBJ importer.")
        return
    raise RuntimeError("Supported input formats are .blend, .fbx, and .obj.")


def scene_inventory(input_path: Path | None = None, thresholds: dict | None = None) -> dict:
    """Capture source-scene complexity before mesh objects are joined."""
    thresholds = thresholds or load_thresholds(DEFAULT_THRESHOLDS)
    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    unique_materials = {slot.material for obj in mesh_objects for slot in obj.material_slots if slot.material}
    lod_levels = set()
    source_objects = []
    for obj in mesh_objects:
        lod_match = re.search(r"(?:^|[_. -])lod[_. -]?(\d+)", obj.name.lower())
        if lod_match:
            lod_levels.add(int(lod_match.group(1)))
        weighted_vertices = 0
        unbound_vertices = 0
        weight_sum_error_count = 0
        max_influence_count = 0
        over_influenced_vertices = 0
        for vertex in obj.data.vertices:
            weights = [float(group.weight) for group in vertex.groups if group.weight > 0.0]
            if weights:
                weighted_vertices += 1
                max_influence_count = max(max_influence_count, len(weights))
                if len(weights) > int(thresholds["max_influences_per_vertex"]):
                    over_influenced_vertices += 1
                if abs(sum(weights) - 1.0) > float(thresholds["weight_sum_tolerance"]):
                    weight_sum_error_count += 1
            else:
                unbound_vertices += 1
        armature_modifiers = [modifier for modifier in obj.modifiers if modifier.type == "ARMATURE"]
        scale = obj.matrix_world.to_scale()
        shape_keys = getattr(obj.data, "shape_keys", None)
        color_layer_count = sum(
            1 for attribute in getattr(obj.data, "attributes", [])
            if getattr(attribute, "data_type", "") in {"BYTE_COLOR", "FLOAT_COLOR"}
        )
        unassigned_material_slots = sum(slot.material is None for slot in obj.material_slots)
        source_objects.append({
            "name": obj.name,
            "vertex_count": len(obj.data.vertices),
            "face_count": len(obj.data.polygons),
            "material_slot_count": len(obj.material_slots),
            "unassigned_material_slot_count": unassigned_material_slots,
            "uv_layer_count": len(obj.data.uv_layers),
            "uv_layer_names": [layer.name for layer in obj.data.uv_layers[:8]],
            "vertex_color_layer_count": color_layer_count,
            "morph_target_count": len(shape_keys.key_blocks) - 1 if shape_keys else 0,
            "has_modifiers": bool(obj.modifiers),
            "vertex_group_count": len(obj.vertex_groups),
            "armature_modifier_count": len(armature_modifiers),
            "bound_armature_names": [modifier.object.name for modifier in armature_modifiers if modifier.object],
            "weighted_vertex_count": weighted_vertices,
            "unbound_vertex_count": unbound_vertices,
            "weight_sum_error_count": weight_sum_error_count,
            "max_influence_count": max_influence_count,
            "over_influenced_vertex_count": over_influenced_vertices,
            "negative_scale": any(float(value) < -1e-6 for value in scale),
            "non_unit_scale": any(abs(float(value) - 1.0) > 1e-4 for value in scale),
            "zero_scale": any(abs(float(value)) < 1e-8 for value in scale),
        })
    actions = []

    def action_fcurve_count(action):
        legacy = getattr(action, "fcurves", None)
        if legacy is not None:
            return len(legacy)
        count = 0
        for layer in getattr(action, "layers", []):
            for strip in getattr(layer, "strips", []):
                count += sum(len(channelbag.fcurves) for channelbag in getattr(strip, "channelbags", []))
        return count

    for action in bpy.data.actions:
        fcurve_count = action_fcurve_count(action)
        if not fcurve_count:
            continue
        start, end = action.frame_range
        actions.append({
            "name": action.name,
            "frame_start": round(float(start), 3),
            "frame_end": round(float(end), 3),
            "frame_count": max(0, int(math.ceil(end - start + 1))),
            "fcurve_count": fcurve_count,
        })
    source_file_size = int(input_path.stat().st_size) if input_path and input_path.exists() else 0
    lod_levels_sorted = sorted(lod_levels)
    expected_lod_levels = list(range(lod_levels_sorted[0], lod_levels_sorted[-1] + 1)) if lod_levels_sorted else []
    return {
        "source_scene_object_count": len(list(bpy.context.scene.objects)),
        "source_mesh_object_count": len(mesh_objects),
        "source_object_names": [obj.name for obj in mesh_objects[:50]],
        "source_mesh_objects": source_objects[:100],
        "source_has_armature": any(obj.type == "ARMATURE" for obj in bpy.context.scene.objects),
        "source_has_animation": bool(actions) or any(bool(getattr(obj, "animation_data", None)) for obj in bpy.context.scene.objects),
        "source_armature_count": len(armatures),
        "source_bone_count": sum(len(obj.data.bones) for obj in armatures),
        "source_deform_bone_count": sum(sum(bool(bone.use_deform) for bone in obj.data.bones) for obj in armatures),
        "animation_action_count": len(actions),
        "animation_actions": actions[:100],
        "source_lod_count": len(lod_levels),
        "source_lod_levels": sorted(lod_levels),
        "source_material_slot_count": sum(len(obj.material_slots) for obj in mesh_objects),
        "source_material_slot_overflow_object_count": sum(
            item["material_slot_count"] > int(thresholds["max_material_slots_per_object"])
            for item in source_objects
        ),
        "source_unassigned_material_slot_count": sum(item["unassigned_material_slot_count"] for item in source_objects),
        "source_unique_material_count": len(unique_materials),
        "source_missing_uv_object_count": sum(not bool(obj.data.uv_layers) for obj in mesh_objects),
        "source_uv_layer_count": sum(len(obj.data.uv_layers) for obj in mesh_objects),
        "source_vertex_color_layer_count": sum(item["vertex_color_layer_count"] for item in source_objects),
        "source_morph_target_object_count": sum(item["morph_target_count"] > 0 for item in source_objects),
        "source_morph_target_count": sum(item["morph_target_count"] for item in source_objects),
        "source_negative_scale_object_count": sum(item["negative_scale"] for item in source_objects),
        "source_non_unit_scale_object_count": sum(item["non_unit_scale"] for item in source_objects),
        "source_zero_scale_object_count": sum(item["zero_scale"] for item in source_objects),
        "source_lod_missing_levels": [level for level in expected_lod_levels if level not in lod_levels_sorted],
        "source_unit_system": getattr(bpy.context.scene.unit_settings, "system", "NONE"),
        "source_unit_scale_length": float(getattr(bpy.context.scene.unit_settings, "scale_length", 1.0) or 1.0),
        "source_file_size_bytes": source_file_size,
    }


def extended_geometry_stats(asset: bpy.types.Object) -> dict:
    """Add topology diagnostics that are useful on imported production assets."""
    mesh = asset.data
    referenced_vertices = set()
    zero_length_edges = 0
    for edge in mesh.edges:
        referenced_vertices.update(edge.vertices)
        if (mesh.vertices[edge.vertices[0]].co - mesh.vertices[edge.vertices[1]].co).length < 1e-8:
            zero_length_edges += 1
    ngon_faces = sum(len(poly.vertices) > 4 for poly in mesh.polygons)
    triangle_count = sum(max(0, len(poly.vertices) - 2) for poly in mesh.polygons)
    corners = [asset.matrix_world @ Vector(corner) for corner in asset.bound_box]
    min_corner = Vector((min(point.x for point in corners), min(point.y for point in corners), min(point.z for point in corners)))
    max_corner = Vector((max(point.x for point in corners), max(point.y for point in corners), max(point.z for point in corners)))

    # Connected components are a useful warning for imported assets that have
    # detached shells, floating triangles, or accidentally duplicated parts.
    adjacency = {vertex.index: set() for vertex in mesh.vertices}
    for edge in mesh.edges:
        a, b = edge.vertices
        adjacency[a].add(b)
        adjacency[b].add(a)
    components = 0
    unseen = set(adjacency)
    while unseen:
        components += 1
        stack = [unseen.pop()]
        while stack:
            current = stack.pop()
            for neighbour in adjacency[current]:
                if neighbour in unseen:
                    unseen.remove(neighbour)
                    stack.append(neighbour)

    return {
        "vertex_count": len(mesh.vertices),
        "triangle_count": triangle_count,
        "ngon_face_count": ngon_faces,
        "loose_vertex_count": len(set(range(len(mesh.vertices))) - referenced_vertices),
        "zero_length_edge_count": zero_length_edges,
        "connected_component_count": components,
        "uv_layer_count": len(mesh.uv_layers),
        "material_slot_count": len(asset.material_slots),
        "bounding_box_dimensions": [round(float(value), 6) for value in (max_corner - min_corner)],
    }


def component_diagnostics(asset: bpy.types.Object) -> list[dict]:
    """Return per-connected-component counts after imported objects are joined."""
    mesh = asset.data
    adjacency = {vertex.index: set() for vertex in mesh.vertices}
    for edge in mesh.edges:
        a, b = edge.vertices
        adjacency[a].add(b)
        adjacency[b].add(a)
    unseen = set(adjacency)
    vertex_component = {}
    component_sizes = []
    while unseen:
        root = unseen.pop()
        current = {root}
        stack = [root]
        while stack:
            vertex = stack.pop()
            for neighbour in adjacency[vertex]:
                if neighbour in unseen:
                    unseen.remove(neighbour)
                    current.add(neighbour)
                    stack.append(neighbour)
        component_id = len(component_sizes)
        for vertex in current:
            vertex_component[vertex] = component_id
        component_sizes.append({"component_id": component_id, "vertex_count": len(current), "face_count": 0, "edge_count": 0})
    for edge in mesh.edges:
        component_id = vertex_component.get(edge.vertices[0])
        if component_id is not None and component_id == vertex_component.get(edge.vertices[1]):
            component_sizes[component_id]["edge_count"] += 1
    for poly in mesh.polygons:
        component_ids = {vertex_component.get(vertex) for vertex in poly.vertices}
        component_ids.discard(None)
        for component_id in component_ids:
            component_sizes[component_id]["face_count"] += 1
    components = component_sizes
    return sorted(components, key=lambda item: item["face_count"], reverse=True)[:100]


def uv_diagnostics(asset: bpy.types.Object, thresholds: dict | None = None) -> dict:
    """Measure UV completeness, density, stretch, islands and spacing."""
    thresholds = thresholds or load_thresholds(DEFAULT_THRESHOLDS)
    mesh = asset.data
    layer = mesh.uv_layers.active
    if layer is None:
        return {
            "uv_status": "not_present",
            "uv_loop_count": 0,
            "uv_out_of_bounds_loop_count": 0,
            "uv_zero_area_triangle_count": 0,
            "uv_valid_triangle_count": 0,
            "uv_island_count": 0,
            "uv_density_stats": {},
            "uv_stretch_stats": {},
            "uv_min_island_gap": None,
            "uv_analysis_sampled": False,
            "uv_analysis_total_triangle_count": sum(max(0, len(poly.vertices) - 2) for poly in mesh.polygons),
            "uv_analysis_analyzed_triangle_count": 0,
            "uv_analysis_coverage_ratio": 0.0,
        }

    coords = [tuple(float(value) for value in layer.data[index].uv) for index in range(len(layer.data))]
    out_of_bounds = sum(x < 0.0 or x > 1.0 or y < 0.0 or y > 1.0 for x, y in coords)
    zero_area = 0
    analyzed_triangles = 0
    triangles = []
    polygon_uv_edges = {}
    max_triangles = max(1, int(thresholds["max_diagnostic_triangles"]))
    polygon_step = max(1, math.ceil(len(mesh.polygons) / max_triangles))
    for poly_index, poly in enumerate(mesh.polygons):
        if poly_index % polygon_step:
            continue
        loops = list(poly.loop_indices)
        if len(loops) < 3:
            continue
        anchor = coords[loops[0]]
        for index in range(1, len(loops) - 1):
            analyzed_triangles += 1
            b = coords[loops[index]]
            c = coords[loops[index + 1]]
            area = abs((b[0] - anchor[0]) * (c[1] - anchor[1]) - (b[1] - anchor[1]) * (c[0] - anchor[0]))
            if area < 1e-10:
                zero_area += 1
            a3 = asset.matrix_world @ mesh.vertices[poly.vertices[0]].co
            b3 = asset.matrix_world @ mesh.vertices[poly.vertices[index]].co
            c3 = asset.matrix_world @ mesh.vertices[poly.vertices[index + 1]].co
            area3d = ((b3 - a3).cross(c3 - a3)).length * 0.5
            uv_area = area * 0.5
            if area3d > 1e-10 and uv_area > 1e-10:
                triangles.append({"poly_index": poly.index, "uv": (anchor, b, c), "uv_area": uv_area, "area3d": area3d})
        for index, vertex in enumerate(poly.vertices):
            next_index = (index + 1) % len(poly.vertices)
            key = tuple(sorted((vertex, poly.vertices[next_index])))
            polygon_uv_edges.setdefault(key, []).append((poly.index, coords[loops[index]], coords[loops[next_index]]))

    densities = [triangle["uv_area"] / triangle["area3d"] for triangle in triangles]
    density_median = sorted(densities)[len(densities) // 2] if densities else 0.0
    stretches = [max(density / density_median, density_median / density) if density and density_median else 0.0 for density in densities]

    parent = {poly.index: poly.index for poly in mesh.polygons}

    def find(value):
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    def uv_pair_matches(left, right):
        return (max(abs(left[0][0] - right[0][0]), abs(left[0][1] - right[0][1])) < 1e-5 and
                max(abs(left[1][0] - right[1][0]), abs(left[1][1] - right[1][1])) < 1e-5) or (
                max(abs(left[0][0] - right[1][0]), abs(left[0][1] - right[1][1])) < 1e-5 and
                max(abs(left[1][0] - right[0][0]), abs(left[1][1] - right[0][1])) < 1e-5)

    for uses in polygon_uv_edges.values():
        if len(uses) == 2 and uv_pair_matches(uses[0][1:], uses[1][1:]):
            union(uses[0][0], uses[1][0])
    islands = {}
    for triangle, stretch in zip(triangles, stretches):
        island_id = find(triangle["poly_index"])
        island = islands.setdefault(island_id, {"uv_area": 0.0, "area3d": 0.0, "triangles": 0, "points": []})
        island["uv_area"] += triangle["uv_area"]
        island["area3d"] += triangle["area3d"]
        island["triangles"] += 1
        island["points"].extend(triangle["uv"])
    island_records = []
    for island_id, island in islands.items():
        xs = [point[0] for point in island["points"]]
        ys = [point[1] for point in island["points"]]
        island_records.append({
            "island_id": island_id,
            "uv_area": round(island["uv_area"], 8),
            "surface_area": round(island["area3d"], 8),
            "triangle_count": island["triangles"],
            "bounds": [round(min(xs), 6), round(min(ys), 6), round(max(xs), 6), round(max(ys), 6)],
        })
    min_gap = None
    gap_pair_limit = max(1, int(thresholds["max_component_gap_pairs"]))
    gap_pair_count = 0
    gap_complete = True
    for index, left in enumerate(island_records):
        for right in island_records[index + 1:]:
            if gap_pair_count >= gap_pair_limit:
                gap_complete = False
                break
            gap_pair_count += 1
            horizontal = max(0.0, max(left["bounds"][0], right["bounds"][0]) - min(left["bounds"][2], right["bounds"][2]))
            vertical = max(0.0, max(left["bounds"][1], right["bounds"][1]) - min(left["bounds"][3], right["bounds"][3]))
            gap = math.sqrt(horizontal * horizontal + vertical * vertical)
            min_gap = gap if min_gap is None else min(min_gap, gap)
        if not gap_complete:
            break
    xs = [point[0] for point in coords]
    ys = [point[1] for point in coords]

    def stats(values):
        ordered = sorted(values)
        if not ordered:
            return {"min": 0.0, "p05": 0.0, "median": 0.0, "p95": 0.0, "max": 0.0}
        return {
            "min": round(ordered[0], 8),
            "p05": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.05))], 8),
            "median": round(ordered[len(ordered) // 2], 8),
            "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 8),
            "max": round(ordered[-1], 8),
        }
    return {
        "uv_status": "present",
        "uv_loop_count": len(coords),
        "uv_out_of_bounds_loop_count": out_of_bounds,
        "uv_zero_area_triangle_count": zero_area,
        "uv_valid_triangle_count": len(triangles),
        "uv_island_count": len(island_records),
        "uv_islands": sorted(island_records, key=lambda item: item["uv_area"], reverse=True)[:100],
        "uv_density_stats": stats(densities),
        "uv_stretch_stats": stats(stretches),
        "uv_min_island_gap": round(min_gap, 8) if min_gap is not None else None,
        "uv_analysis_sampled": polygon_step > 1,
        "uv_analysis_triangle_limit": max_triangles,
        "uv_analysis_total_triangle_count": sum(max(0, len(poly.vertices) - 2) for poly in mesh.polygons),
        "uv_analysis_analyzed_triangle_count": analyzed_triangles,
        "uv_analysis_coverage_ratio": round(
            analyzed_triangles / max(1, sum(max(0, len(poly.vertices) - 2) for poly in mesh.polygons)), 6
        ),
        "uv_island_gap_analysis_complete": gap_complete,
        "uv_bounds": {
            "min": [round(min(xs), 6), round(min(ys), 6)] if xs else [0.0, 0.0],
            "max": [round(max(xs), 6), round(max(ys), 6)] if xs else [0.0, 0.0],
        },
    }


def render_uv_heatmap(asset: bpy.types.Object, path: Path, resolution: int = 512, max_triangles: int = 50000) -> None:
    """Write a UV stretch/density heatmap without changing the scene material."""
    mesh = asset.data
    layer = mesh.uv_layers.active
    path.parent.mkdir(parents=True, exist_ok=True)
    if layer is None:
        image = bpy.data.images.new("uv_stretch_heatmap_empty", width=resolution, height=resolution, alpha=True)
        image.generated_color = (0.05, 0.05, 0.05, 1.0)
        image.save_render(filepath=str(path))
        return
    coords = [tuple(float(value) for value in layer.data[index].uv) for index in range(len(layer.data))]
    triangles = []
    polygon_step = max(1, math.ceil(len(mesh.polygons) / max(1, int(max_triangles))))
    for poly_index, poly in enumerate(mesh.polygons):
        if poly_index % polygon_step:
            continue
        loops = list(poly.loop_indices)
        if len(loops) < 3:
            continue
        for index in range(1, len(loops) - 1):
            uv_points = (coords[loops[0]], coords[loops[index]], coords[loops[index + 1]])
            a3 = asset.matrix_world @ mesh.vertices[poly.vertices[0]].co
            b3 = asset.matrix_world @ mesh.vertices[poly.vertices[index]].co
            c3 = asset.matrix_world @ mesh.vertices[poly.vertices[index + 1]].co
            uv_area = abs((uv_points[1][0] - uv_points[0][0]) * (uv_points[2][1] - uv_points[0][1]) - (uv_points[1][1] - uv_points[0][1]) * (uv_points[2][0] - uv_points[0][0])) * 0.5
            area3d = ((b3 - a3).cross(c3 - a3)).length * 0.5
            if uv_area > 1e-10 and area3d > 1e-10:
                triangles.append((uv_points, uv_area / area3d))
    if not triangles:
        # A black image is ambiguous: it can mean either "everything is
        # healthy" or "there was no valid UV data to draw".  The caller adds
        # the same reason to the report metadata; this visible placeholder
        # makes the diagnostic artifact honest when opened by itself.
        image = bpy.data.images.new("uv_stretch_heatmap_unavailable", width=resolution, height=resolution, alpha=True)
        image.generated_color = (0.16, 0.08, 0.08, 1.0)
        image.save_render(filepath=str(path))
        return
    densities = [item[1] for item in triangles]
    median = sorted(densities)[len(densities) // 2] if densities else 1.0
    values = []
    for points, density in triangles:
        values.append((points, max(density / median, median / density) if density and median else 0.0))
    # A single very distorted triangle can otherwise become the global
    # maximum and compress every other triangle into the same blue color.
    # Clip the display range to P05-P95 so the image remains useful as a
    # comparative diagnostic while exact statistics stay in the manifest.
    heat_values = sorted(value for _, value in values)
    low_index = max(0, int(len(heat_values) * 0.05))
    high_index = min(len(heat_values) - 1, int(len(heat_values) * 0.95))
    lower = heat_values[low_index] if heat_values else 0.0
    upper = heat_values[high_index] if heat_values else 1.0
    if upper <= lower:
        upper = max(lower + 1e-6, max(heat_values, default=1.0))
    pixels = [0.06, 0.06, 0.08, 1.0] * (resolution * resolution)
    occupancy = [-1.0] * (resolution * resolution)

    def edge(a, b, c):
        return (c[0] - a[0]) * (b[1] - a[1]) - (c[1] - a[1]) * (b[0] - a[0])

    for points, value in values:
        min_x = max(0, int(math.floor(min(point[0] for point in points) * resolution)))
        max_x = min(resolution - 1, int(math.ceil(max(point[0] for point in points) * resolution)))
        min_y = max(0, int(math.floor(min(point[1] for point in points) * resolution)))
        max_y = min(resolution - 1, int(math.ceil(max(point[1] for point in points) * resolution)))
        intensity = min(1.0, max(0.0, (value - lower) / max(upper - lower, 1e-6)))
        red, green, blue = intensity, max(0.0, 1.0 - abs(intensity - 0.5) * 2.0), 1.0 - intensity
        for py in range(min_y, max_y + 1):
            for px in range(min_x, max_x + 1):
                sample = ((px + 0.5) / resolution, (py + 0.5) / resolution)
                signs = [edge(points[0], points[1], sample), edge(points[1], points[2], sample), edge(points[2], points[0], sample)]
                if all(sign >= 0 for sign in signs) or all(sign <= 0 for sign in signs):
                    offset = (py * resolution + px) * 4
                    if intensity >= occupancy[py * resolution + px]:
                        occupancy[py * resolution + px] = intensity
                        pixels[offset:offset + 4] = [red, green, blue, 1.0]
    image = bpy.data.images.new("uv_stretch_heatmap", width=resolution, height=resolution, alpha=True)
    image.pixels.foreach_set(pixels)
    image.save_render(filepath=str(path))


def render_diagnostic_notice(scene: bpy.types.Scene, path: Path, title: str, detail: str, resolution: int = 512) -> None:
    """Render a readable placeholder when a diagnostic has no valid data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    original_camera = scene.camera
    original_world_color = tuple(scene.world.color) if scene.world else None
    original_resolution = (scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage)
    hidden = {obj: obj.hide_render for obj in scene.objects}
    temporary_objects = []

    def text_material(name: str, color: tuple[float, float, float, float]):
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        nodes.clear()
        output = nodes.new("ShaderNodeOutputMaterial")
        emission = nodes.new("ShaderNodeEmission")
        emission.inputs["Color"].default_value = color
        emission.inputs["Strength"].default_value = 1.0
        links.new(emission.outputs[0], output.inputs[0])
        return material

    try:
        for obj in scene.objects:
            obj.hide_render = True
        bpy.ops.object.camera_add(location=(0.0, 0.0, 5.0), rotation=(0.0, 0.0, 0.0))
        camera = bpy.context.object
        temporary_objects.append(camera)
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = 2.4
        scene.camera = camera
        scene.world.color = (0.055, 0.06, 0.08)

        for index, (body, size, color) in enumerate(
            ((title, 0.16, (1.0, 0.45, 0.18, 1.0)), (detail, 0.085, (0.82, 0.84, 0.88, 1.0)))
        ):
            curve = bpy.data.curves.new(f"diagnostic_notice_text_{index}", type="FONT")
            curve.body = body
            curve.align_x = "CENTER"
            curve.align_y = "CENTER"
            curve.size = size
            obj = bpy.data.objects.new(f"diagnostic_notice_text_{index}", curve)
            obj.location = (0.0, 0.14 if index == 0 else -0.14, 0.0)
            curve.materials.append(text_material(f"diagnostic_notice_material_{index}", color))
            scene.collection.objects.link(obj)
            temporary_objects.append(obj)

        scene.render.resolution_x = resolution
        scene.render.resolution_y = resolution
        scene.render.resolution_percentage = 100
        render(scene, path)
    finally:
        for obj in temporary_objects:
            if obj and obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        for obj, value in hidden.items():
            if obj.name in bpy.data.objects:
                obj.hide_render = value
        scene.camera = original_camera
        if scene.world and original_world_color is not None:
            scene.world.color = original_world_color
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = original_resolution


def texture_diagnostics(asset: bpy.types.Object, thresholds: dict | None = None) -> dict:
    """Inspect PBR channel wiring, color spaces, images and material slots."""
    thresholds = thresholds or load_thresholds(DEFAULT_THRESHOLDS)
    materials = []
    seen_materials = set()
    for slot in asset.material_slots:
        if slot.material and slot.material.name not in seen_materials:
            materials.append(slot.material)
            seen_materials.add(slot.material.name)
    images = []
    seen = set()
    material_reports = []
    pbr_issue_count = 0
    pbr_channels = ("Base Color", "Normal", "Roughness", "Metallic", "Ambient Occlusion", "Alpha", "Emission Color")
    data_channels = {"Normal", "Roughness", "Metallic", "Ambient Occlusion", "Alpha"}

    def trace_image_source(node, visited=None):
        """Follow simple shader chains so a Normal Map node is not mistaken for a direct image link."""
        visited = visited or set()
        if node is None or node.name in visited:
            return None, []
        visited.add(node.name)
        if node.type == "TEX_IMAGE" and node.image:
            return node, [node.type]
        for input_socket in node.inputs:
            for link in input_socket.links:
                image_node, chain = trace_image_source(link.from_node, visited)
                if image_node:
                    return image_node, [node.type, *chain]
        return None, [node.type]

    channel_hint_tokens = {
        "Base Color": ("rough", "metal", "normal", "ao", "ambient", "opacity", "alpha", "emiss"),
        "Normal": ("rough", "metal", "basecolor", "albedo", "diffuse"),
        "Roughness": ("normal", "metal", "basecolor", "albedo", "diffuse"),
        "Metallic": ("normal", "rough", "basecolor", "albedo", "diffuse"),
        "Ambient Occlusion": ("normal", "rough", "metal", "basecolor", "albedo", "diffuse"),
        "Alpha": ("normal", "rough", "metal", "basecolor", "albedo", "diffuse"),
        "Emission Color": ("normal", "rough", "metal", "basecolor", "albedo", "diffuse"),
    }

    def image_info(image):
        try:
            resolved = bpy.path.abspath(image.filepath)
            exists = image.source == "GENERATED" or bool(image.packed_file) or (bool(image.filepath) and Path(resolved).exists())
        except (RuntimeError, ValueError):
            resolved = ""
            exists = image.source == "GENERATED" or bool(image.packed_file)
        width, height = [int(value) for value in image.size]
        if image.packed_file:
            byte_size = int(getattr(image.packed_file, "size", 0) or 0)
        elif resolved and Path(resolved).exists():
            byte_size = int(Path(resolved).stat().st_size)
        else:
            byte_size = 0
        return {
            "name": image.name,
            "filepath": resolved or str(getattr(image, "filepath", "") or ""),
            "width": width,
            "height": height,
            "packed": bool(image.packed_file),
            "exists": exists,
            "source": image.source,
            "resource_status": "embedded" if image.packed_file or image.source == "GENERATED" else "external" if exists else "missing",
            "colorspace": image.colorspace_settings.name,
            "byte_size": byte_size,
        }

    for material in materials:
        report = {"name": material.name, "node_based": bool(material.use_nodes), "channels": {}, "issues": []}
        if not material.use_nodes or not material.node_tree:
            report["issues"].append("material_without_nodes")
            material_reports.append(report)
            continue
        principled_nodes = [node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"]
        bsdf = principled_nodes[0] if principled_nodes else None
        if bsdf is None:
            report["issues"].append("missing_principled_bsdf")
        for node in material.node_tree.nodes:
            if node.type != "TEX_IMAGE" or not node.image or node.image.name in seen:
                continue
            image = node.image
            seen.add(image.name)
            images.append(image_info(image))
        if bsdf:
            for channel in pbr_channels:
                socket = bsdf.inputs.get(channel)
                links = list(socket.links) if socket else []
                info = {"connected": bool(links), "source_node": links[0].from_node.name if links else None, "source_chain": [], "image": None}
                if links:
                    source_node = links[0].from_node
                    image_node, source_chain = trace_image_source(source_node)
                    info["source_chain"] = source_chain
                    if image_node and image_node.image:
                        info["image"] = image_info(image_node.image)
                        image_name = image_node.image.name.lower()
                        expected_non_color = channel in data_channels
                        if expected_non_color and image_node.image.colorspace_settings.name != "Non-Color":
                            report["issues"].append(f"{channel}:expected_non_color")
                        if any(token in image_name for token in channel_hint_tokens.get(channel, ())):
                            report["issues"].append(f"{channel}:possible_wrong_channel")
                        if channel == "Normal" and source_node.type == "TEX_IMAGE":
                            report["issues"].append("Normal:missing_normal_map_node")
                info["status"] = "connected" if links else "not_connected"
                report["channels"][channel] = info
        # A material that deliberately uses a constant color or procedural
        # nodes is valid without an image texture.  Only actual channel
        # wiring, color-space, missing-node, or non-node problems count as
        # PBR issues.  Keep the textureless state as an informational fact.
        material_image_names = {
            node.image.name
            for node in material.node_tree.nodes
            if node.type == "TEX_IMAGE" and node.image
        }
        report["material_mode"] = "textured" if material_image_names else "constant_or_procedural"
        report["uses_image_texture"] = bool(material_image_names)
        pbr_issue_count += len(report["issues"])
        material_reports.append(report)
    missing = [image for image in images if not image["exists"]]
    low_resolution = [image for image in images if max(image["width"], image["height"]) < int(thresholds["min_texture_size"])]
    oversized = [image for image in images if max(image["width"], image["height"]) > int(thresholds["max_texture_size"])]
    texture_total_bytes = sum(image["byte_size"] for image in images if image["exists"])
    texture_memory_bytes = sum(image["width"] * image["height"] * 4 * 4 // 3 for image in images if image["exists"])
    unassigned_slots = sum(slot.material is None for slot in asset.material_slots)
    udim_images = sum(image.get("source") == "TILED" for image in images)
    external_images = sum(image.get("source") == "FILE" and not image.get("packed") for image in images)
    textureless_materials = [
        report["name"]
        for report in material_reports
        if report.get("material_mode") == "constant_or_procedural"
    ]
    return {
        "material_count": len(materials),
        "material_slot_count": len(asset.material_slots),
        "unique_material_count": len(materials),
        "material_slot_overflow": len(asset.material_slots) > int(thresholds["max_material_slots"]),
        "unassigned_material_slot_count": unassigned_slots,
        "node_based_material_count": sum(bool(material.use_nodes) for material in materials),
        "texture_image_count": len(images),
        "missing_texture_count": len(missing),
        "low_resolution_texture_count": len(low_resolution),
        "oversized_texture_count": len(oversized),
        "max_texture_size": int(thresholds["max_texture_size"]),
        "texture_total_bytes": texture_total_bytes,
        "texture_memory_bytes_estimated": texture_memory_bytes,
        "udim_image_count": udim_images,
        "external_image_count": external_images,
        "pbr_channel_issue_count": pbr_issue_count,
        "textureless_material_count": len(textureless_materials),
        "textureless_materials": textureless_materials[:100],
        "pbr_material_reports": material_reports[:100],
        "texture_images": images[:100],
    }


def performance_diagnostics(input_path: Path, inventory: dict, texture: dict, geometry: dict, thresholds: dict | None = None) -> dict:
    """Estimate delivery and loading risk using explicit, inspectable heuristics."""
    thresholds = thresholds or load_thresholds(DEFAULT_THRESHOLDS)
    file_size = int(input_path.stat().st_size) if input_path.exists() else 0
    texture_bytes = int(texture.get("texture_total_bytes", 0) or 0)
    texture_memory = int(texture.get("texture_memory_bytes_estimated", 0) or 0)
    mesh_objects = int(inventory.get("source_mesh_object_count", 0) or 0)
    material_count = int(texture.get("unique_material_count", 0) or 0)
    source_meshes = inventory.get("source_mesh_objects", []) or []
    # A more useful draw-call estimate is per-object material usage, rather
    # than object_count multiplied by the scene-wide unique material count.
    draw_call_estimate = sum(max(1, int(item.get("material_slot_count", 0) or 0)) for item in source_meshes)
    draw_call_estimate = max(1, draw_call_estimate or mesh_objects or material_count)
    memory_bytes = texture_memory + int(geometry.get("vertex_count", 0) * 32) + int(geometry.get("triangle_count", 0) * 16)
    estimated_seconds = file_size / (50 * 1024 * 1024) + texture_memory / (250 * 1024 * 1024) + draw_call_estimate * 0.015
    if texture_memory > int(thresholds["max_texture_memory_bytes"]) or draw_call_estimate > int(thresholds["max_draw_calls"]) or estimated_seconds > float(thresholds["max_estimated_load_time_seconds"]):
        risk = "high"
    elif texture_memory > int(thresholds["max_texture_memory_bytes"]) * 0.5 or draw_call_estimate > int(thresholds["max_draw_calls"]) * 0.4 or estimated_seconds > float(thresholds["max_estimated_load_time_seconds"]) * 0.375:
        risk = "medium"
    else:
        risk = "low"
    return {
        "asset_file_size_bytes": file_size,
        "texture_total_bytes": texture_bytes,
        "estimated_texture_memory_bytes": texture_memory,
        "estimated_runtime_memory_bytes": memory_bytes,
        "estimated_draw_calls": draw_call_estimate,
        "draw_call_risk": "high" if draw_call_estimate > 100 else "medium" if draw_call_estimate > 40 else "low",
        "estimated_load_time_seconds": round(estimated_seconds, 2),
        "loading_risk": risk,
        "lod_count": inventory.get("source_lod_count", 0),
        "lod_levels": inventory.get("source_lod_levels", []),
        "lod_missing_levels": inventory.get("source_lod_missing_levels", []),
        "vertex_count_for_performance": geometry.get("vertex_count", 0),
        "source_bone_count": inventory.get("source_bone_count", 0),
        "source_morph_target_count": inventory.get("source_morph_target_count", 0),
        "animation_present": inventory.get("source_has_animation", False),
        "armature_present": inventory.get("source_has_armature", False),
    }


def animation_diagnostics(inventory: dict) -> dict:
    """Check binding, finite poses, and sampled non-adjacent mesh overlaps."""
    mesh_reports = inventory.get("source_mesh_objects", [])
    rigged_meshes = [item for item in mesh_reports if item.get("armature_modifier_count", 0) or item.get("vertex_group_count", 0)]
    unbound_vertices = sum(int(item.get("unbound_vertex_count", 0) or 0) for item in rigged_meshes)
    weight_sum_errors = sum(int(item.get("weight_sum_error_count", 0) or 0) for item in rigged_meshes)
    over_influenced = sum(int(item.get("over_influenced_vertex_count", 0) or 0) for item in rigged_meshes)
    weighted_vertices = sum(int(item.get("weighted_vertex_count", 0) or 0) for item in rigged_meshes)
    missing_armature_modifier = bool(inventory.get("source_has_armature")) and any(
        item.get("vertex_group_count", 0) > 0 and item.get("armature_modifier_count", 0) == 0
        for item in mesh_reports
    )
    actions = inventory.get("animation_actions", [])
    if not actions or not rigged_meshes:
        return {
            "rigged_mesh_count": len(rigged_meshes),
            "unbound_vertex_count": unbound_vertices,
            "weight_sum_error_count": weight_sum_errors,
            "over_influenced_vertex_count": over_influenced,
            "weighted_vertex_count": weighted_vertices,
            "unbound_vertex_ratio": round(unbound_vertices / max(1, sum(int(item.get("vertex_count", 0) or 0) for item in rigged_meshes)), 6),
            "weight_sum_error_ratio": round(weight_sum_errors / max(1, weighted_vertices), 6),
            "missing_armature_modifier": missing_armature_modifier,
            "animation_playability": "not_applicable",
            "animation_probe_frame_count": 0,
            "deformation_nonfinite_vertex_count": 0,
            "deformation_self_intersection_check": "not_applicable",
            "deformation_self_intersection_sample_count": 0,
            "deformation_self_intersection_pair_count": 0,
            "deformation_self_intersection_frames": [],
            "deformation_frame_stats": [],
        }
    original_frame = bpy.context.scene.frame_current
    probe_frames = set()
    for action in actions[:20]:
        start, end = float(action["frame_start"]), float(action["frame_end"])
        probe_frames.update({int(round(start)), int(round((start + end) * 0.5)), int(round(end))})
    nonfinite = 0
    sampled = 0
    self_intersection_samples = 0
    self_intersection_pairs = 0
    self_intersection_frames = []
    deformation_frame_stats = []
    try:
        for frame in sorted(probe_frames)[:60]:
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            sampled += 1
            frame_max_displacement = 0.0
            frame_mean_displacements = []
            frame_overlap_pairs = 0
            frame_nonfinite = 0
            depsgraph = bpy.context.evaluated_depsgraph_get()
            for obj in bpy.context.scene.objects:
                if obj.type != "MESH" or not any(modifier.type == "ARMATURE" for modifier in obj.modifiers):
                    continue
                evaluated = obj.evaluated_get(depsgraph)
                mesh = evaluated.to_mesh()
                try:
                    mesh_nonfinite = sum(
                        not all(math.isfinite(float(value)) for value in vertex.co)
                        for vertex in mesh.vertices
                    )
                    nonfinite += mesh_nonfinite
                    frame_nonfinite += mesh_nonfinite
                    if len(mesh.vertices) == len(obj.data.vertices):
                        displacements = [
                            (mesh.vertices[index].co - obj.data.vertices[index].co).length
                            for index in range(len(mesh.vertices))
                        ]
                        if displacements:
                            frame_max_displacement = max(frame_max_displacement, max(displacements))
                            frame_mean_displacements.extend(displacements)
                    # BVH overlap is intentionally limited to meshes under
                    # 50k faces and only counts non-adjacent face pairs. It is
                    # evidence from sampled poses, not a proof of no collision.
                    if len(mesh.polygons) <= 50_000 and mesh_nonfinite == 0 and len(mesh.polygons) > 1:
                        bvh = BVHTree.FromPolygons(
                            [vertex.co[:] for vertex in mesh.vertices],
                            [poly.vertices[:] for poly in mesh.polygons],
                            epsilon=1e-6,
                        )
                        face_vertices = [set(poly.vertices) for poly in mesh.polygons]
                        for left, right in bvh.overlap(bvh):
                            if left == right or face_vertices[left].intersection(face_vertices[right]):
                                continue
                            frame_overlap_pairs += 1
                finally:
                    evaluated.to_mesh_clear()
            self_intersection_samples += 1
            self_intersection_pairs += frame_overlap_pairs
            if frame_overlap_pairs:
                self_intersection_frames.append({"frame": frame, "pair_count": frame_overlap_pairs})
            deformation_frame_stats.append({
                "frame": frame,
                "max_vertex_displacement": round(frame_max_displacement, 6),
                "mean_vertex_displacement": round(sum(frame_mean_displacements) / len(frame_mean_displacements), 6) if frame_mean_displacements else 0.0,
                "nonfinite_vertex_count": frame_nonfinite,
                "non_adjacent_overlap_pairs": frame_overlap_pairs,
            })
    finally:
        bpy.context.scene.frame_set(original_frame)
    return {
        "rigged_mesh_count": len(rigged_meshes),
        "unbound_vertex_count": unbound_vertices,
        "weight_sum_error_count": weight_sum_errors,
        "over_influenced_vertex_count": over_influenced,
        "weighted_vertex_count": weighted_vertices,
        "unbound_vertex_ratio": round(unbound_vertices / max(1, sum(int(item.get("vertex_count", 0) or 0) for item in rigged_meshes)), 6),
        "weight_sum_error_ratio": round(weight_sum_errors / max(1, weighted_vertices), 6),
        "missing_armature_modifier": missing_armature_modifier,
        "animation_playability": "passed_finite_pose_probe" if nonfinite == 0 else "failed_nonfinite_pose_probe",
        "animation_probe_frame_count": sampled,
        "deformation_nonfinite_vertex_count": nonfinite,
        "deformation_self_intersection_check": "detected_sampled_overlap" if self_intersection_pairs else "passed_sampled_no_non_adjacent_overlap",
        "deformation_self_intersection_sample_count": self_intersection_samples,
        "deformation_self_intersection_pair_count": self_intersection_pairs,
        "deformation_self_intersection_frames": self_intersection_frames[:60],
        "deformation_frame_stats": deformation_frame_stats[:60],
    }


def issue_face_indices(asset: bpy.types.Object, thresholds: dict | None = None) -> dict[str, set[int]]:
    """Locate faces that can be visualized in the issue-overlay GLB."""
    thresholds = thresholds or load_thresholds(DEFAULT_THRESHOLDS)
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

    result = {"degenerate_faces": set(), "hole": set(), "non_manifold": set(), "flipped_normals": set(), "stretched_triangles": set(), "uv_overlap": set()}
    for edge, faces in edge_faces.items():
        if len(faces) == 1:
            result["hole"].add(faces[0])
        if len(faces) > 2:
            result["non_manifold"].update(faces)
    for uses in directed_edges.values():
        if len(uses) == 2 and uses[0][1] == uses[1][1]:
            result["flipped_normals"].update(item[0] for item in uses)

    uv_layer = mesh.uv_layers.active
    uv_faces: dict[tuple[tuple[float, float], ...], list[int]] = {}
    aspect_limit = float(thresholds["max_triangle_aspect_p95"])
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
            points = tuple(sorted((round(float(uv_layer.data[loop].uv.x), 6), round(float(uv_layer.data[loop].uv.y), 6)) for loop in list(poly.loop_indices)[:3]))
            uv_faces.setdefault(points, []).append(poly.index)
    for faces in uv_faces.values():
        if len(faces) > 1:
            result["uv_overlap"].update(faces)
    return result


def issue_breakdown_by_object(mesh_objects: list[bpy.types.Object], thresholds: dict | None = None) -> list[dict]:
    """Keep issue evidence tied to source objects before they are joined."""
    thresholds = thresholds or load_thresholds(DEFAULT_THRESHOLDS)
    # UV overlap can be introduced by two different source objects that share
    # the same UV space. Build the same rounded first-triangle keys used by
    # issue_face_indices so those cross-object overlaps are not lost when the
    # objects are inspected independently.
    uv_owners: dict[tuple[tuple[float, float], ...], list[tuple[str, int]]] = {}
    for obj in mesh_objects:
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
    breakdown = []
    for obj in mesh_objects:
        face_issues = issue_face_indices(obj, thresholds)
        counts = {key: len(value) for key, value in face_issues.items() if value}
        uv_faces = set(face_issues.get("uv_overlap", set())) | cross_object_uv_faces.get(obj.name, set())
        if uv_faces:
            counts["uv_overlap"] = len(uv_faces)
        if not counts:
            continue
        breakdown.append({
            "object_name": obj.name,
            "face_count": len(obj.data.polygons),
            "related_face_counts": counts,
        })
    return breakdown


def export_preview(out: Path, asset: bpy.types.Object) -> str:
    """Export a lightweight GLB preview for the browser's interactive viewer."""
    preview = out / "preview.glb"
    bpy.ops.object.select_all(action="DESELECT")
    asset.select_set(True)
    bpy.context.view_layer.objects.active = asset
    bpy.ops.export_scene.gltf(
        filepath=str(preview),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_cameras=False,
        export_lights=False,
        export_animations=False,
    )
    if not preview.exists():
        raise RuntimeError("Blender finished without producing a GLB preview.")
    return "preview.glb"


def export_issue_overlay(out: Path, asset: bpy.types.Object, face_issues: dict[str, set[int]]) -> str | None:
    """Export a duplicate GLB with detected faces assigned diagnostic colors."""
    selected_faces = {face for faces in face_issues.values() for face in faces}
    if not selected_faces:
        return None
    overlay = asset.copy()
    overlay.data = asset.data.copy()
    overlay.name = "issue_overlay"
    bpy.context.collection.objects.link(overlay)
    colors = {
        "degenerate_faces": (0.95, 0.03, 0.03),
        "hole": (0.95, 0.12, 0.02),
        "stretched_triangles": (1.0, 0.45, 0.02),
        "uv_overlap": (0.05, 0.32, 1.0),
        "flipped_normals": (0.62, 0.12, 0.95),
        "non_manifold": (1.0, 0.82, 0.02),
    }
    priority = ["degenerate_faces", "non_manifold", "hole", "flipped_normals", "stretched_triangles", "uv_overlap"]
    base_slot_count = len(overlay.data.materials)
    material_indices = {}
    for issue in priority:
        material_indices[issue] = base_slot_count + len(material_indices)
        overlay.data.materials.append(mat(f"issue_overlay_{issue}", colors[issue]))
    for poly in overlay.data.polygons:
        for issue in priority:
            if poly.index in face_issues.get(issue, set()):
                poly.material_index = material_indices[issue]
                break
    overlay_path = out / "issue_overlay.glb"
    bpy.ops.object.select_all(action="DESELECT")
    overlay.select_set(True)
    bpy.context.view_layer.objects.active = overlay
    bpy.ops.export_scene.gltf(
        filepath=str(overlay_path), export_format="GLB", use_selection=True,
        export_apply=True, export_cameras=False, export_lights=False, export_animations=False,
    )
    bpy.data.objects.remove(overlay, do_unlink=True)
    return "issue_overlay.glb" if overlay_path.exists() else None


def create_camera_and_lights(scene: bpy.types.Scene, view: int, views: int) -> None:
    angle = 2.0 * math.pi * view / views
    bpy.ops.object.camera_add(location=(4.3 * math.cos(angle), 4.3 * math.sin(angle), 2.6))
    camera = bpy.context.object
    look_at(camera, (0, 0, 0))
    camera.data.lens = 52
    scene.camera = camera
    bpy.ops.object.light_add(type="AREA", location=(2, -2, 5))
    key = bpy.context.object
    key.data.energy = 900
    key.data.shape = "DISK"
    key.data.size = 5
    bpy.ops.object.light_add(type="AREA", location=(-3, 2, 2))
    fill = bpy.context.object
    fill.data.energy = 400
    fill.data.size = 3


def write_runtime_manifest(out: Path, asset: bpy.types.Object, views: list[str], uv: str, uv_heatmap: str, normal: str, model: str, model_overlay: str | None, stats: dict) -> None:
    row = {
        "id": "uploaded_asset_000000",
        "scene_id": "uploaded_asset",
        "split": "test",
        "generalization": "external_asset",
        "question_type": "quality_summary",
        "question": "请判断这个 3D 资产是否通过质量检查，并列出主要问题。",
        "answer": None,
        "images": {"views": views, "uv": uv, "uv_heatmap": uv_heatmap, "normal": normal, "model": model, "model_overlay": model_overlay},
        "metadata": {"asset_id": "uploaded_asset", "asset_family": "uploaded", **stats,
                     "camera_views": [{"id": i, "azimuth": i * 90.0, "elevation": 20} for i in range(len(views))]},
    }
    (out / "manifest.jsonl").write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--views", type=int, default=4)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--config", type=Path, default=DEFAULT_THRESHOLDS, help="JSON inspection threshold configuration.")
    parser.add_argument("--repair", action="store_true", help="Apply safe mesh cleanup before rendering and export.")
    parser.add_argument("--repaired-output", type=Path, default=None, help="Optional repaired .blend output path.")
    args = parser.parse_args(argv)
    if not args.input.exists():
        raise SystemExit(f"Input asset not found: {args.input}")
    if args.views < 1 or args.views > 8:
        raise SystemExit("--views must be between 1 and 8")

    args.out.mkdir(parents=True, exist_ok=True)
    thresholds = load_thresholds(args.config)
    import_input_asset(args.input)
    scene = configure_render()
    scene.render.resolution_x = args.resolution
    scene.render.resolution_y = args.resolution
    if scene.world is None:
        scene.world = bpy.data.worlds.new("InspectionWorld")
    scene.world.color = (0.025, 0.025, 0.025)
    remove_cameras_and_lights()
    inventory = scene_inventory(args.input, thresholds)
    animation_stats = animation_diagnostics(inventory)
    source_mesh_objects_before_join = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    source_issue_breakdown = issue_breakdown_by_object(source_mesh_objects_before_join, thresholds)
    asset = join_meshes()
    repair_actions = []
    if args.repair:
        bpy.context.view_layer.objects.active = asset
        asset.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(asset.data)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
        loose_vertices = [vert for vert in bm.verts if not vert.link_edges]
        if loose_vertices:
            bmesh.ops.delete(bm, geom=loose_vertices, context="VERTS")
        boundary_edges = [edge for edge in bm.edges if edge.is_boundary]
        if boundary_edges:
            bmesh.ops.holes_fill(bm, edges=boundary_edges, sides=0)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bmesh.update_edit_mesh(asset.data)
        bpy.ops.object.mode_set(mode="OBJECT")
        repair_actions = ["merge_duplicate_vertices", "delete_loose_geometry", "fill_holes", "recalculate_normals"]
    # Do not auto-unwrap before inspection: doing so would turn a source asset
    # with no UVs into an apparently valid UV asset and hide the defect. The
    # UV renderer and heatmap already handle a missing active layer explicitly.
    normalize_asset(asset)
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            obj.hide_render = obj != asset
    if not asset.data.materials:
        asset.data.materials.append(mat("uploaded_default_material", (0.42, 0.50, 0.66)))
    texture_stats = texture_diagnostics(asset, thresholds)
    # Use the full topology counter for the complexity decision. The UV-aware
    # geometry routine intentionally limits some analysis and is not suitable
    # for estimating the real triangle count from a tiny probe.
    geometry_probe = extended_geometry_stats(asset)
    geometry_adaptive = choose_geometry_adaptive_settings(args, thresholds, geometry_probe)
    args.views = geometry_adaptive["effective_views"]
    args.resolution = geometry_adaptive["effective_resolution"]
    diagnostic_triangle_limit = geometry_adaptive["effective_max_diagnostic_triangles"]
    thresholds["max_diagnostic_triangles"] = diagnostic_triangle_limit
    geometry_stats_after = {**geometry_stats(asset, max_uv_triangles=diagnostic_triangle_limit), **extended_geometry_stats(asset)}
    scene.render.resolution_x = args.resolution
    scene.render.resolution_y = args.resolution
    scene.render.resolution_percentage = 100
    stats = {
        **inventory,
        **geometry_stats_after,
        "component_details": component_diagnostics(asset),
        **uv_diagnostics(asset, thresholds),
        **texture_stats,
        **performance_diagnostics(args.input, inventory, texture_stats, geometry_stats_after, thresholds),
        **animation_stats,
        "source_format": args.input.suffix.lower().lstrip("."),
        "source_issue_breakdown": source_issue_breakdown[:200],
        "runtime_geometry_adaptive": geometry_adaptive,
        "repair_applied": bool(args.repair),
        "repair_actions": repair_actions,
        "threshold_config": str(args.config.resolve()),
        "thresholds": thresholds,
    }
    model_relative = export_preview(args.out, asset)
    face_issues = issue_face_indices(asset, thresholds)
    stats["issue_related_face_counts"] = {key: len(value) for key, value in face_issues.items()}
    stats["issue_overlay_available"] = bool(any(face_issues.values()))
    model_overlay_relative = export_issue_overlay(args.out, asset, face_issues)
    if args.repaired_output:
        args.repaired_output.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.repaired_output.resolve()))

    view_paths: list[str] = []
    for view in range(args.views):
        remove_cameras_and_lights()
        create_camera_and_lights(scene, view, args.views)
        relative = f"images/uploaded_asset/view_{view}.png"
        render(scene, args.out / relative)
        view_paths.append(relative)

    remove_cameras_and_lights()
    create_camera_and_lights(scene, 0, args.views)
    uv_relative = "images/uploaded_asset/uv.png"
    uv_heatmap_relative = "images/uploaded_asset/uv_heatmap.png"
    normal_relative = "images/uploaded_asset/normal.png"
    if stats.get("uv_status") == "not_present":
        render_diagnostic_notice(scene, args.out / uv_relative, "UV diagnostic unavailable", "No UV layer is present")
    elif stats.get("uv_analysis_analyzed_triangle_count", 0) and stats.get("uv_valid_triangle_count", 0) == 0:
        render_diagnostic_notice(scene, args.out / uv_relative, "UV diagnostic unavailable", "No valid UV triangles (zero area)")
    else:
        render_diagnostic(scene, asset, args.out / uv_relative, "uv")
    if stats.get("uv_status") == "not_present":
        render_diagnostic_notice(scene, args.out / uv_heatmap_relative, "UV heatmap unavailable", "No UV layer is present")
    elif stats.get("uv_analysis_analyzed_triangle_count", 0) and stats.get("uv_valid_triangle_count", 0) == 0:
        render_diagnostic_notice(scene, args.out / uv_heatmap_relative, "UV heatmap unavailable", "No valid UV triangles (zero area)")
    else:
        render_uv_heatmap(asset, args.out / uv_heatmap_relative, max_triangles=diagnostic_triangle_limit)
    render_diagnostic(scene, asset, args.out / normal_relative, "normal")
    write_runtime_manifest(args.out, asset, view_paths, uv_relative, uv_heatmap_relative, normal_relative, model_relative, model_overlay_relative, stats)
    print(json.dumps({"manifest": str(args.out / "manifest.jsonl"), "stats": stats}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
