"""Blender generator for single-asset quality diagnosis data.

Run:
  blender -b -P blender/generate_scene_dataset.py -- --out data/blender --n 30 --seed 7

The six defect injectors are intentionally simple and auditable. Their labels
are written only to the answer; metadata contains measurements, never defect
booleans or diagnosis names.
"""

import argparse
import json
import math
import random
import sys
from pathlib import Path

import bpy
from mathutils import Vector

DEFECTS = ["non_manifold", "uv_overlap", "flipped_normals", "hole", "stretched_triangles", "degenerate_faces"]
REPAIR = {"non_manifold": "merge or separate non-manifold components", "uv_overlap": "repack overlapping UV islands", "flipped_normals": "recalculate and validate face normals", "hole": "fill boundary loops and inspect watertightness", "stretched_triangles": "rebuild stretched regions with better topology", "degenerate_faces": "remove zero-area faces and re-triangulate"}


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def mat(name, color):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1)
    return material


def look_at(obj, target=(0, 0, 0)):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def make_asset(rng):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=1.35, location=(0, 0, 1.35))
    asset = bpy.context.object
    asset.name = "asset"
    asset.data.materials.append(mat("asset_material", (0.35, 0.48, 0.68)))
    # The primitive does not always carry a usable UV layout in headless
    # Blender runs. Create one explicitly so the UV diagnostic image is
    # informative for both clean and defective assets.
    bpy.context.view_layer.objects.active = asset
    asset.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.03)
    bpy.ops.object.mode_set(mode="OBJECT")
    return asset


def inject_hole(asset):
    mesh = asset.data
    # Delete one face through bmesh so the boundary is measurable.
    import bmesh
    bm = bmesh.new(); bm.from_mesh(mesh)
    target = max(bm.faces, key=lambda f: f.calc_center_median().z)
    bmesh.ops.delete(bm, geom=[target], context="FACES")
    bm.to_mesh(mesh); bm.free(); mesh.update()


def inject_degenerate(asset):
    mesh = asset.data
    import bmesh
    bm = bmesh.new(); bm.from_mesh(mesh)
    # Blender 5.2 no longer exposes bmesh.ops.create_face. Add an isolated
    # triangle through the BMesh API, then collapse two vertices to create a
    # measurable zero-area face.
    v1 = bm.verts.new((0.0, 0.0, 1.35))
    v2 = bm.verts.new((0.25, 0.0, 1.35))
    v3 = bm.verts.new((0.0, 0.25, 1.35))
    bm.verts.ensure_lookup_table()
    bm.faces.new((v1, v2, v3))
    v3.co = v2.co
    bm.to_mesh(mesh); bm.free(); mesh.update()


def inject_flipped_normals(asset):
    import bmesh
    bm = bmesh.new(); bm.from_mesh(asset.data)
    for face in list(bm.faces)[: max(1, len(bm.faces) // 20)]: face.normal_flip()
    bm.to_mesh(asset.data); bm.free(); asset.data.update()


def inject_non_manifold(asset):
    # Add a triangle sharing one existing mesh edge. That edge is then used by
    # three faces and is genuinely non-manifold; a loose triangle alone only
    # creates boundary edges.
    mesh = asset.data
    import bmesh
    bm = bmesh.new(); bm.from_mesh(mesh)
    bm.edges.ensure_lookup_table()
    edge = bm.edges[0]
    v1, v2 = edge.verts
    midpoint = (v1.co + v2.co) * 0.5
    v3 = bm.verts.new(midpoint + Vector((0.0, 0.0, 0.35)))
    bm.faces.new((v1, v2, v3))
    bm.to_mesh(mesh); bm.free(); mesh.update()


def inject_stretched(asset):
    import bmesh
    bm = bmesh.new(); bm.from_mesh(asset.data)
    for v in list(bm.verts)[: max(1, len(bm.verts) // 12)]: v.co.x *= 3.5
    bm.to_mesh(asset.data); bm.free(); asset.data.update()


def inject_uv_overlap(asset):
    uv = asset.data.uv_layers.active or asset.data.uv_layers.new(name="UVMap")
    polygons = [p for p in asset.data.polygons if len(p.loop_indices) >= 3]
    if len(polygons) >= 2:
        source = polygons[0].loop_indices[:3]
        target = polygons[1].loop_indices[:3]
        coords = [uv.data[li].uv.copy() for li in source]
        for li, coord in zip(target, coords):
            uv.data[li].uv = coord


INJECTORS = {"hole": inject_hole, "degenerate_faces": inject_degenerate, "flipped_normals": inject_flipped_normals, "non_manifold": inject_non_manifold, "stretched_triangles": inject_stretched, "uv_overlap": inject_uv_overlap}
INJECTION_ORDER = ["hole", "non_manifold", "uv_overlap", "flipped_normals", "stretched_triangles", "degenerate_faces"]


def apply_defects(asset, defects):
    """Apply defects in a stable order so later BMesh edits preserve earlier ones."""
    for defect in sorted(defects, key=INJECTION_ORDER.index):
        INJECTORS[defect](asset)


def geometry_stats(asset):
    mesh = asset.data
    edge_use = {}
    edge_faces = {}
    for poly in mesh.polygons:
        for a, b in zip(poly.vertices, poly.vertices[1:] + poly.vertices[:1]): edge_use[tuple(sorted((a, b)))] = edge_use.get(tuple(sorted((a, b))), 0) + 1
        for a, b in zip(poly.vertices, poly.vertices[1:] + poly.vertices[:1]):
            key = tuple(sorted((a, b)))
            edge_faces.setdefault(key, set()).add(poly.index)
    areas = [float(p.area) for p in mesh.polygons]
    degenerate_faces = {p.index for p in mesh.polygons if p.area < 1e-8}
    non_manifold = sum(v > 2 for v in edge_use.values())
    non_manifold_faces = {
        face_index
        for edge, count in edge_use.items()
        if count > 2
        for face_index in edge_faces.get(edge, set())
    }
    # Count only genuine open boundaries. Degenerate faces and the two side
    # edges of the injected non-manifold triangle must not masquerade as holes.
    boundary = sum(
        count == 1
        and not (edge_faces.get(edge, set()) & degenerate_faces)
        and not (edge_faces.get(edge, set()) & non_manifold_faces)
        for edge, count in edge_use.items()
    )
    uv_overlap_ratio = 0.0
    if mesh.uv_layers.active:
        # Estimate UV triangle overlap by rasterizing UV space. Repeated UV
        # coordinates at seams are valid and must not be treated as overlap.
        # The generated assets are triangles, so a small fixed raster is
        # sufficient and keeps the statistic deterministic.
        import math as _math

        resolution = 128
        occupancy = {}
        uv_layer = mesh.uv_layers.active

        def edge(a, b, c):
            return (c[0] - a[0]) * (b[1] - a[1]) - (c[1] - a[1]) * (b[0] - a[0])

        for poly in mesh.polygons:
            if len(poly.loop_indices) < 3:
                continue
            points = [tuple(uv_layer.data[li].uv) for li in poly.loop_indices[:3]]
            if abs(edge(points[0], points[1], points[2])) < 1e-10:
                continue
            min_x = max(0, int(_math.floor(min(p[0] for p in points) * resolution)))
            max_x = min(resolution - 1, int(_math.ceil(max(p[0] for p in points) * resolution)))
            min_y = max(0, int(_math.floor(min(p[1] for p in points) * resolution)))
            max_y = min(resolution - 1, int(_math.ceil(max(p[1] for p in points) * resolution)))
            for py in range(min_y, max_y + 1):
                for px in range(min_x, max_x + 1):
                    sample = ((px + 0.5) / resolution, (py + 0.5) / resolution)
                    signs = [edge(points[0], points[1], sample), edge(points[1], points[2], sample), edge(points[2], points[0], sample)]
                    if all(s >= 0 for s in signs) or all(s <= 0 for s in signs):
                        occupancy[(px, py)] = occupancy.get((px, py), 0) + 1
        covered = sum(v >= 1 for v in occupancy.values())
        overlapped = sum(v >= 2 for v in occupancy.values())
        uv_overlap_ratio = overlapped / covered if covered else 0.0
    # Detect winding inconsistencies on ordinary manifold edges. This is more
    # robust than comparing face normals to a radial direction: stretching a
    # valid mesh can change that radial heuristic without flipping a face.
    directed_edges = {}
    for poly in mesh.polygons:
        verts = list(poly.vertices)
        for a, b in zip(verts, verts[1:] + verts[:1]):
            key = tuple(sorted((a, b)))
            direction = 1 if (a, b) == key else -1
            directed_edges.setdefault(key, []).append((poly.index, direction))
    flipped_faces = set()
    for uses in directed_edges.values():
        if len(uses) == 2 and uses[0][1] == uses[1][1]:
            flipped_faces.update(poly_index for poly_index, _ in uses)
    flipped = len(flipped_faces)
    return {"vertex_count": len(mesh.vertices), "face_count": len(mesh.polygons), "boundary_edge_count": boundary, "non_manifold_edge_count": non_manifold, "flipped_normal_count": flipped, "degenerate_face_count": len(degenerate_faces), "uv_overlap_ratio": round(uv_overlap_ratio, 6), "triangle_area_stats": {"min": round(min(areas), 8) if areas else 0, "median": round(sorted(areas)[len(areas) // 2], 8) if areas else 0, "max": round(max(areas), 8) if areas else 0}}


def setup_camera(scene, view, views):
    angle = 2 * math.pi * view / views
    bpy.ops.object.camera_add(location=(4.3 * math.cos(angle), 4.3 * math.sin(angle), 2.6))
    camera = bpy.context.object; look_at(camera, (0, 0, 1.2)); scene.camera = camera
    bpy.ops.object.light_add(type="AREA", location=(2, -2, 5)); bpy.context.object.data.energy = 900; bpy.context.object.data.shape = "DISK"; bpy.context.object.data.size = 5
    bpy.ops.object.light_add(type="AREA", location=(-3, 2, 2)); bpy.context.object.data.energy = 400; bpy.context.object.data.size = 3


def configure_render():
    scene = bpy.context.scene
    # Blender versions expose the Eevee engine under different identifiers.
    # Prefer the current name when available and fall back to the identifier
    # reported by Blender 5.2 on this Windows installation.
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 256
    scene.render.resolution_y = 256
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    return scene


def render(scene, path):
    path.parent.mkdir(parents=True, exist_ok=True); scene.render.filepath = str(path); bpy.ops.render.render(write_still=True)


def diagnostic_material(kind):
    material = bpy.data.materials.new("diagnostic_" + kind)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Strength"].default_value = 1.0
    links.new(emission.outputs[0], output.inputs[0])
    if kind == "uv":
        tex = nodes.new("ShaderNodeTexCoord")
        separate = nodes.new("ShaderNodeSeparateXYZ")
        combine = nodes.new("ShaderNodeCombineColor")
        # Blender 5.2 names these inputs Red/Green/Blue; older builds may
        # expose shorter channel names. Keep the diagnostic material portable.
        blue = combine.inputs.get("Blue") or combine.inputs.get("B")
        if blue is not None:
            blue.default_value = 0.0
        links.new(tex.outputs["UV"], separate.inputs[0])
        red = combine.inputs.get("Red") or combine.inputs.get("R") or combine.inputs[0]
        green = combine.inputs.get("Green") or combine.inputs.get("G") or combine.inputs[1]
        links.new(separate.outputs["X"], red)
        links.new(separate.outputs["Y"], green)
        links.new(combine.outputs[0], emission.inputs["Color"])
    else:
        geometry = nodes.new("ShaderNodeNewGeometry")
        remap = nodes.new("ShaderNodeVectorMath")
        remap.operation = "MULTIPLY_ADD"
        remap.inputs[1].default_value = (0.5, 0.5, 0.5)
        remap.inputs[2].default_value = (0.5, 0.5, 0.5)
        links.new(geometry.outputs["Normal"], remap.inputs[0])
        links.new(remap.outputs[0], emission.inputs["Color"])
    return material


def render_diagnostic(scene, asset, path, kind):
    if kind == "uv":
        render_uv_layout(scene, asset, path)
        return
    material = diagnostic_material(kind)
    for obj in scene.objects:
        if obj.type == "MESH":
            obj.data.materials.clear()
            obj.data.materials.append(material)
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    render(scene, path)


def render_uv_layout(scene, asset, path):
    """Render the actual UV islands as a 2D line drawing."""
    uv = asset.data.uv_layers.active
    if uv is None:
        render(scene, path)
        return
    original_camera = scene.camera
    original_render_visibility = {
        obj: obj.hide_render for obj in scene.objects if obj.type == "MESH"
    }
    for obj in original_render_visibility:
        obj.hide_render = True

    curve_data = bpy.data.curves.new("uv_layout_curves", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = 1
    curve_data.bevel_depth = 0.0025
    curve_data.bevel_resolution = 0
    curve_obj = bpy.data.objects.new("uv_layout", curve_data)
    scene.collection.objects.link(curve_obj)

    line_material = bpy.data.materials.new("uv_layout_material")
    line_material.use_nodes = True
    nodes = line_material.node_tree.nodes
    links = line_material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (0.95, 0.85, 0.08, 1.0)
    emission.inputs["Strength"].default_value = 2.0
    links.new(emission.outputs[0], output.inputs[0])
    curve_data.materials.append(line_material)

    for poly in asset.data.polygons:
        if len(poly.loop_indices) < 3:
            continue
        points = [tuple(uv.data[li].uv) for li in poly.loop_indices]
        spline = curve_data.splines.new("POLY")
        spline.points.add(len(points))
        for point, (u, v) in zip(spline.points, points + [points[0]]):
            point.co = (float(u) - 0.5, float(v) - 0.5, 0.0, 1.0)

    for obj in list(scene.objects):
        obj.select_set(False)
    bpy.ops.object.camera_add(location=(0.0, 0.0, 1.0), rotation=(0.0, 0.0, 0.0))
    camera = bpy.context.object
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 1.08
    scene.camera = camera
    scene.world.color = (0.025, 0.025, 0.025)
    render(scene, path)

    bpy.data.objects.remove(curve_obj, do_unlink=True)
    bpy.data.objects.remove(camera, do_unlink=True)
    bpy.data.curves.remove(curve_data)
    bpy.data.materials.remove(line_material)
    for obj, hidden in original_render_visibility.items():
        if obj.name in bpy.data.objects:
            obj.hide_render = hidden
    scene.camera = original_camera


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--views", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--clean-prob", type=float, default=0.25)
    ap.add_argument("--balanced-defects", action="store_true")
    args = ap.parse_args(argv)
    if not 0.0 <= args.clean_prob <= 1.0:
        ap.error("--clean-prob must be between 0 and 1")
    rng = random.Random(args.seed); args.out.mkdir(parents=True, exist_ok=True); manifest = []
    clean_test_ordinals = {0, 2, 4, 7, 9, 11, 13, 15, 18, 20, 21, 23}
    defect_cursor = 0
    test_defect_cursor = 0
    for i in range(args.n):
        clear_scene(); scene_id = f"asset_{i:05d}"; asset = make_asset(rng)
        split = "test" if i % 10 in (0, 1) else ("val" if i % 10 == 2 else "train")
        test_ordinal = (i // 10) * 2 + (i % 10) if split == "test" else -1
        if split == "test":
            n_defects = 0 if test_ordinal in clean_test_ordinals else rng.choice([1, 1, 2])
        else:
            n_defects = 0 if rng.random() < args.clean_prob else rng.choice([1, 1, 2])
        if n_defects == 0:
            defects = []
        elif args.balanced_defects:
            cursor = test_defect_cursor if split == "test" else defect_cursor
            primary = DEFECTS[cursor % len(DEFECTS)]
            defects = [primary]
            if n_defects > 1:
                defects.append(rng.choice([d for d in DEFECTS if d != primary]))
            defects = sorted(defects)
            if split == "test":
                test_defect_cursor += 1
            else:
                defect_cursor += 1
        else:
            defects = sorted(rng.sample(DEFECTS, n_defects))
        apply_defects(asset, defects)
        scene = configure_render(); views = []
        for view in range(args.views):
            clear_scene(); asset = make_asset(rng)
            apply_defects(asset, defects)
            setup_camera(scene, view, args.views)
            rel = f"images/{scene_id}/view_{view}.png"; render(scene, args.out / rel); views.append(rel)
        # Render UV and normal diagnostics from the same defective asset.
        clear_scene(); asset = make_asset(rng)
        apply_defects(asset, defects)
        setup_camera(scene, 0, args.views)
        stats = geometry_stats(asset)
        uv_rel, normal_rel = f"images/{scene_id}/uv.png", f"images/{scene_id}/normal.png"
        render_diagnostic(scene, asset, args.out / uv_rel, "uv")
        render_diagnostic(scene, asset, args.out / normal_rel, "normal")
        severity = "none" if not defects else ("high" if len(defects) > 1 or "hole" in defects else "medium")
        if split == "test" and test_ordinal % 4 == 0:
            qtype = "repair_planning"
            generalization = "unseen_question_type"
        else:
            qtype = rng.choice(["quality_summary", "defect_detection", "severity"])
            generalization = "unseen_scene" if split == "test" else "in_distribution"
        question = {"quality_summary": "请判断这个 3D 资产是否通过质量检查，并列出主要问题。", "defect_detection": "请识别这个 3D 资产中存在的拓扑、UV 和法线问题。", "severity": "请评估这个 3D 资产的质量问题严重程度。", "repair_planning": "请根据发现的质量问题给出最短的修复计划。"}[qtype]
        answer = {"quality": "pass" if not defects else "fail", "defect_types": defects, "severity": severity}
        if qtype == "repair_planning": answer["repair_plan"] = [REPAIR[d] for d in defects] if defects else ["no repair required"]
        manifest.append({"id": f"sample_{i:06d}", "scene_id": scene_id, "split": split, "generalization": generalization, "question_type": qtype, "question": question, "answer": answer, "images": {"views": views, "uv": uv_rel, "normal": normal_rel}, "metadata": {"asset_id": scene_id, **stats, "camera_views": [{"id": v, "azimuth": v * 360 / args.views, "elevation": 20} for v in range(args.views)]}})
    with (args.out / "manifest.jsonl").open("w", encoding="utf-8") as f:
        for row in manifest: f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("wrote", len(manifest), "samples")


if __name__ == "__main__": main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
