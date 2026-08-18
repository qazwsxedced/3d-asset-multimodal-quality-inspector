"""Build a reproducible FBX/OBJ/Blend inspection fixture set in Blender.

Run:
  blender -b --python scripts/build_inspection_test_assets.py -- --out tests/inspection_assets/generated
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy


def reset() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def select_all() -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in bpy.context.scene.objects:
        obj.select_set(True)
    if bpy.context.scene.objects:
        bpy.context.view_layer.objects.active = next(iter(bpy.context.scene.objects))


def add_material(name: str, color: tuple[float, float, float], image_path: Path | None = None, missing_path: Path | None = None):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    bsdf = next(node for node in nodes if node.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    target = image_path or missing_path
    if target:
        if image_path:
            image = bpy.data.images.new(name + "_albedo", width=256, height=256)
            image.generated_color = (*color, 1.0)
            image.filepath_raw = str(image_path)
            image.file_format = "PNG"
            image.save()
        else:
            image = bpy.data.images.new(name + "_missing", width=1024, height=1024)
            image.source = "FILE"
            image.filepath = str(target)
        texture = nodes.new("ShaderNodeTexImage")
        texture.name = name + "_BaseColor"
        texture.image = image
        links.new(texture.outputs["Color"], bsdf.inputs["Base Color"])
    return material


def add_cube(name: str, location: tuple[float, float, float], material=None, scale=1.0):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = (scale, scale, scale)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if material:
        obj.data.materials.append(material)
    return obj


def export_fbx(path: Path) -> None:
    select_all()
    bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, apply_unit_scale=True, object_types={"MESH", "ARMATURE"})


def export_obj(path: Path) -> None:
    select_all()
    try:
        bpy.ops.wm.obj_export(filepath=str(path), export_materials=True, export_uv=True, export_normals=True, export_selected_objects=True)
    except TypeError:
        bpy.ops.wm.obj_export(filepath=str(path))


def make_multi_part(out: Path) -> None:
    reset()
    red = add_material("Part_Red", (0.7, 0.08, 0.05))
    blue = add_material("Part_Blue", (0.05, 0.2, 0.8))
    add_cube("Body", (-1.2, 0, 0), red, 1.0)
    add_cube("Attachment", (1.2, 0, 0), blue, 0.6)
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.35, depth=2.0, location=(0, 0, 1.2))
    bpy.context.object.name = "Antenna"
    bpy.context.object.data.materials.append(red)
    export_fbx(out / "multi_part_fbx.fbx")


def make_rigged(out: Path) -> None:
    reset()
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=8, y_subdivisions=8, size=2)
    mesh = bpy.context.object
    mesh.name = "Character_LOD0"
    bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
    armature = bpy.context.object
    armature.name = "Character_Rig"
    bone = armature.data.edit_bones[0]
    bone.name = "Root"
    bone.head = (0, 0, -1)
    bone.tail = (0, 0, 1)
    bpy.ops.object.mode_set(mode="OBJECT")
    mesh.parent = armature
    modifier = mesh.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    group = mesh.vertex_groups.new(name="Root")
    for vertex in mesh.data.vertices:
        group.add([vertex.index], 1.0, "REPLACE")
    armature.location.x = 0
    armature.keyframe_insert(data_path="location", frame=1)
    armature.location.x = 1
    armature.keyframe_insert(data_path="location", frame=24)
    export_fbx(out / "rigged_fbx.fbx")


def make_textured(out: Path) -> None:
    reset()
    material = add_material("Textured_Material", (0.25, 0.55, 0.85), out / "textured_albedo.png")
    add_cube("TexturedAsset", (0, 0, 0), material, 1.0)
    export_fbx(out / "textured_fbx.fbx")


def make_multi_material(out: Path) -> None:
    reset()
    first = add_material("Mat_Red", (0.8, 0.1, 0.05))
    second = add_material("Mat_Green", (0.05, 0.7, 0.15))
    left = add_cube("Left", (-1.0, 0, 0), first, 0.8)
    right = add_cube("Right", (1.0, 0, 0), second, 0.8)
    left.data.materials.append(second)
    right.data.materials.append(first)
    export_obj(out / "multi_material_obj.obj")


def make_high_poly(out: Path) -> None:
    reset()
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=6, radius=1.0)
    bpy.context.object.name = "HighPolyAsset"
    export_obj(out / "high_poly_obj.obj")


def make_missing_texture(out: Path) -> None:
    reset()
    missing = out / "does_not_exist" / "missing_albedo.png"
    material = add_material("Missing_Texture_Material", (0.5, 0.5, 0.5), missing_path=missing)
    add_cube("MissingTextureAsset", (0, 0, 0), material, 1.0)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "missing_texture_blend.blend"))


def make_no_uv(out: Path) -> None:
    reset()
    add_cube("NoUVAsset", (0, 0, 0), add_material("NoUV_Material", (0.4, 0.4, 0.4)))
    obj = bpy.context.object
    while obj.data.uv_layers:
        obj.data.uv_layers.remove(obj.data.uv_layers[0])
    export_obj(out / "no_uv_obj.obj")


def make_lods(out: Path) -> None:
    reset()
    material = add_material("LOD_Material", (0.4, 0.5, 0.7))
    for index, scale in enumerate((1.0, 0.8, 0.6)):
        add_cube(f"Prop_LOD{index}", (index * 2.0, 0, 0), material, scale)
    export_fbx(out / "multi_lod_fbx.fbx")


BUILDERS = {
    "multi_part_fbx": make_multi_part,
    "rigged_fbx": make_rigged,
    "textured_fbx": make_textured,
    "multi_material_obj": make_multi_material,
    "high_poly_obj": make_high_poly,
    "missing_texture_blend": make_missing_texture,
    "no_uv_obj": make_no_uv,
    "multi_lod_fbx": make_lods,
}


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, builder in BUILDERS.items():
        builder(args.out)
    (args.out / "cases.json").write_text(json.dumps([
        {"name": name, "file": str((args.out / filename).resolve()), "format": suffix}
        for name, filename, suffix in (
            ("multi_part_fbx", "multi_part_fbx.fbx", "fbx"), ("rigged_fbx", "rigged_fbx.fbx", "fbx"),
            ("textured_fbx", "textured_fbx.fbx", "fbx"), ("multi_material_obj", "multi_material_obj.obj", "obj"),
            ("high_poly_obj", "high_poly_obj.obj", "obj"), ("missing_texture_blend", "missing_texture_blend.blend", "blend"),
            ("no_uv_obj", "no_uv_obj.obj", "obj"), ("multi_lod_fbx", "multi_lod_fbx.fbx", "fbx"),
        )
    ], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(args.out.resolve()), "cases": len(BUILDERS)}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
