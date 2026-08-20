"""Source-scene inventory and rig/material complexity statistics."""

from __future__ import annotations

import re
import math
from pathlib import Path

import bpy

from inspection_config import load_thresholds

DEFAULT_THRESHOLDS = Path(__file__).resolve().parents[1] / "config" / "inspection_thresholds.json"

def scene_inventory(input_path: Path | None = None, thresholds: dict | None = None) -> dict:
    """Capture source-scene complexity before mesh objects are joined."""
    thresholds = thresholds or load_thresholds(DEFAULT_THRESHOLDS)
    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    unique_materials = {slot.material for obj in mesh_objects for slot in obj.material_slots if slot.material}
    lod_levels = set()
    source_objects = []
    material_usage: dict[str, list[dict[str, int | str]]] = {}
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
        material_names = []
        for slot_index, slot in enumerate(obj.material_slots):
            if not slot.material:
                continue
            material_name = slot.material.name
            material_names.append(material_name)
            material_usage.setdefault(material_name, []).append({
                "object_name": obj.name,
                "face_count": sum(poly.material_index == slot_index for poly in obj.data.polygons),
                "material_slot_index": slot_index,
            })
        source_objects.append({
            "name": obj.name,
            "vertex_count": len(obj.data.vertices),
            "face_count": len(obj.data.polygons),
            "material_slot_count": len(obj.material_slots),
            "material_names": material_names[:32],
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
        "source_material_usage": {name: objects[:100] for name, objects in material_usage.items()},
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
