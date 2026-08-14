"""Render one arbitrary .blend file for the local quality-inspection demo.

Run from Blender:
  blender -b -P blender/inspect_asset.py -- --input asset.blend --out runtime_dir

The source .blend is never saved or modified. The output directory contains
rendered evidence and a runtime manifest consumed by ``demo/app.py``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

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


def write_runtime_manifest(out: Path, asset: bpy.types.Object, views: list[str], uv: str, normal: str, stats: dict) -> None:
    row = {
        "id": "uploaded_asset_000000",
        "scene_id": "uploaded_asset",
        "split": "test",
        "generalization": "external_asset",
        "question_type": "quality_summary",
        "question": "请判断这个 3D 资产是否通过质量检查，并列出主要问题。",
        "answer": None,
        "images": {"views": views, "uv": uv, "normal": normal},
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
    args = parser.parse_args(argv)
    if not args.input.exists():
        raise SystemExit(f"Input .blend not found: {args.input}")
    if args.views < 1 or args.views > 8:
        raise SystemExit("--views must be between 1 and 8")

    args.out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(args.input.resolve()))
    scene = configure_render()
    scene.render.resolution_x = args.resolution
    scene.render.resolution_y = args.resolution
    if scene.world is None:
        scene.world = bpy.data.worlds.new("InspectionWorld")
    scene.world.color = (0.025, 0.025, 0.025)
    remove_cameras_and_lights()
    asset = join_meshes()
    ensure_uv(asset)
    normalize_asset(asset)
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            obj.hide_render = obj != asset
    if not asset.data.materials:
        asset.data.materials.append(mat("uploaded_default_material", (0.42, 0.50, 0.66)))
    stats = geometry_stats(asset)

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
    normal_relative = "images/uploaded_asset/normal.png"
    render_diagnostic(scene, asset, args.out / uv_relative, "uv")
    render_diagnostic(scene, asset, args.out / normal_relative, "normal")
    write_runtime_manifest(args.out, asset, view_paths, uv_relative, normal_relative, stats)
    print(json.dumps({"manifest": str(args.out / "manifest.jsonl"), "stats": stats}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
