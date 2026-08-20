"""Blender scene import and normalization helpers."""

from __future__ import annotations

import math
from pathlib import Path

import bpy
from mathutils import Vector


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
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=str(input_path.resolve()))
        elif hasattr(bpy.ops.import_scene, "obj"):
            bpy.ops.import_scene.obj(filepath=str(input_path.resolve()))
        else:
            raise RuntimeError("This Blender build does not provide the OBJ importer.")
        return
    raise RuntimeError("Supported input formats are .blend, .fbx, and .obj.")
