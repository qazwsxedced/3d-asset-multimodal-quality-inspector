"""Animation, skinning, and sampled deformation diagnostics."""

from __future__ import annotations

import math

import bpy
from mathutils.bvhtree import BVHTree

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
        if rigged_meshes and not actions:
            inspection_status = "binding_only"
            playback_status = "not_tested_no_actions"
            self_intersection_status = "not_tested_no_actions"
        else:
            inspection_status = "not_checked"
            playback_status = "not_tested_no_rigged_mesh"
            self_intersection_status = "not_applicable"
        return {
            "rigged_mesh_count": len(rigged_meshes),
            "unbound_vertex_count": unbound_vertices,
            "weight_sum_error_count": weight_sum_errors,
            "over_influenced_vertex_count": over_influenced,
            "weighted_vertex_count": weighted_vertices,
            "unbound_vertex_ratio": round(unbound_vertices / max(1, sum(int(item.get("vertex_count", 0) or 0) for item in rigged_meshes)), 6),
            "weight_sum_error_ratio": round(weight_sum_errors / max(1, weighted_vertices), 6),
            "missing_armature_modifier": missing_armature_modifier,
            "animation_inspection_status": inspection_status,
            "animation_binding_status": "checked" if rigged_meshes else "not_checked",
            "animation_playback_status": playback_status,
            "animation_playability": playback_status,
            "animation_probe_frame_count": 0,
            "deformation_nonfinite_vertex_count": 0,
            "deformation_self_intersection_check": self_intersection_status,
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
        "animation_inspection_status": "sampled_pose",
        "animation_binding_status": "checked",
        "animation_playback_status": "sampled",
        "animation_playability": "passed_finite_pose_probe" if nonfinite == 0 else "failed_nonfinite_pose_probe",
        "animation_probe_frame_count": sampled,
        "deformation_nonfinite_vertex_count": nonfinite,
        "deformation_self_intersection_check": "detected_sampled_overlap" if self_intersection_pairs else "passed_sampled_no_non_adjacent_overlap",
        "deformation_self_intersection_sample_count": self_intersection_samples,
        "deformation_self_intersection_pair_count": self_intersection_pairs,
        "deformation_self_intersection_frames": self_intersection_frames[:60],
        "deformation_frame_stats": deformation_frame_stats[:60],
    }
