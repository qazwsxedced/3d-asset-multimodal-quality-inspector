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
import sys
from pathlib import Path

import bpy

# Blender's background runner does not always put the script directory on
# sys.path. Add it explicitly so the shared generator utilities work both from
# the repository root and from a direct ``blender -P`` invocation.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from generate_scene_dataset import (
    configure_render,
    diagnostic_material,
    geometry_stats,
    look_at,
    mat,
    render,
    render_diagnostic,
)
from inspection_config import (
    choose_geometry_adaptive_settings as _choose_geometry_adaptive_settings,
    load_thresholds as _load_thresholds,
)

DEFAULT_THRESHOLDS = SCRIPT_DIR.parent / "config" / "inspection_thresholds.json"


# Compatibility names keep the Blender entry point stable while the policy
# implementation lives in a separately testable module.
load_thresholds = _load_thresholds
choose_geometry_adaptive_settings = _choose_geometry_adaptive_settings

from asset_geometry import (
    ensure_uv,
    import_input_asset,
    join_meshes,
    normalize_asset,
    remove_cameras_and_lights,
)
from scene_inventory import scene_inventory
from geometry_diagnostics import component_diagnostics, extended_geometry_stats
from uv_diagnostics import uv_diagnostics
from material_diagnostics import texture_diagnostics
from performance_diagnostics import performance_diagnostics
from animation_diagnostics import animation_diagnostics
from src.issue_locator_script import write_blender_selection_script








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








from issue_localization import (
    issue_breakdown_by_object as _issue_breakdown_by_object,
    issue_face_indices as _issue_face_indices,
)

issue_face_indices = _issue_face_indices
issue_breakdown_by_object = _issue_breakdown_by_object


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


def write_issue_locator(out: Path, stats: dict) -> dict[str, str]:
    """Write locator JSON plus a self-contained Blender face-selection script."""
    payload = {
        "schema_version": "1.3",
        "asset_id": "uploaded_asset",
        "issue_related_face_counts": stats.get("issue_related_face_counts", {}),
        "issue_related_face_indices": stats.get("issue_related_face_indices", {}),
        "issue_face_index_truncated": stats.get("issue_face_index_truncated", {}),
        "source_issue_breakdown": stats.get("source_issue_breakdown", []),
    }
    path = out / "issue_locator.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    selection_script = write_blender_selection_script(payload, out / "apply_issue_locator.py")
    return {"issue_locator": path.name, "issue_selection_script": selection_script.name}


def write_runtime_manifest(out: Path, asset: bpy.types.Object, views: list[str], uv: str, uv_heatmap: str, normal: str, model: str, model_overlay: str | None, stats: dict, artifacts: dict[str, str] | None = None) -> None:
    row = {
        "id": "uploaded_asset_000000",
        "scene_id": "uploaded_asset",
        "split": "test",
        "generalization": "external_asset",
        "question_type": "quality_summary",
        "question": "请判断这个 3D 资产是否通过质量检查，并列出主要问题。",
        "answer": None,
        "images": {"views": views, "uv": uv, "uv_heatmap": uv_heatmap, "normal": normal, "model": model, "model_overlay": model_overlay},
        "artifacts": artifacts or {},
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
    face_index_limit = min(int(thresholds.get("max_diagnostic_triangles", 50_000)), 10_000)
    stats["issue_related_face_indices"] = {
        key: sorted(values)[:face_index_limit]
        for key, values in face_issues.items()
        if values
    }
    stats["issue_face_index_truncated"] = {
        key: len(values) > face_index_limit
        for key, values in face_issues.items()
        if values
    }
    stats["issue_overlay_available"] = bool(any(face_issues.values()))
    locator_artifacts = write_issue_locator(args.out, stats)
    stats["issue_locator_file"] = locator_artifacts["issue_locator"]
    stats["issue_selection_script_file"] = locator_artifacts["issue_selection_script"]
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
    write_runtime_manifest(args.out, asset, view_paths, uv_relative, uv_heatmap_relative, normal_relative, model_relative, model_overlay_relative, stats, locator_artifacts)
    print(json.dumps({"manifest": str(args.out / "manifest.jsonl"), "stats": stats}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
