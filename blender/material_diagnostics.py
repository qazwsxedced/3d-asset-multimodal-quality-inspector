"""Material, texture, and PBR channel diagnostics."""

from __future__ import annotations

import re
from pathlib import Path

import bpy

from inspection_config import load_thresholds

DEFAULT_THRESHOLDS = Path(__file__).resolve().parents[1] / "config" / "inspection_thresholds.json"

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

    def _node_key(node):
        pointer = getattr(node, "as_pointer", None)
        return pointer() if callable(pointer) else f"{getattr(node, 'bl_idname', '')}:{getattr(node, 'name', '')}"

    def _node_detail(node):
        return {
            "type": str(getattr(node, "type", "")),
            "bl_idname": str(getattr(node, "bl_idname", "")),
            "name": str(getattr(node, "name", "")),
            "label": str(getattr(node, "label", "") or ""),
        }

    def trace_image_source_detailed(node, visited=None, output_socket=None):
        """Follow shader chains and retain an auditable node path."""
        if visited is None:
            visited = set()
        if node is None:
            return None, [], [], "empty_source"
        node_key = _node_key(node)
        if node_key in visited:
            return None, [], [], "cycle_or_revisited_node"
        visited.add(node_key)
        detail = _node_detail(node)
        if node.type == "TEX_IMAGE" and node.image:
            return node, [node.type], [detail], None
        if node.type == "GROUP" and getattr(node, "node_tree", None):
            for group_output in node.node_tree.nodes:
                if group_output.type != "GROUP_OUTPUT":
                    continue
                # A group can expose several outputs.  Follow the output that
                # actually feeds the Principled socket instead of taking the
                # first image found anywhere inside the group.
                target_sockets = []
                if output_socket is not None:
                    output_name = str(getattr(output_socket, "name", "") or "")
                    if output_name:
                        target = group_output.inputs.get(output_name)
                        if target is not None:
                            target_sockets.append(target)
                    if not target_sockets:
                        try:
                            output_index = list(node.outputs).index(output_socket)
                        except (ValueError, TypeError):
                            output_index = None
                        if output_index is not None and output_index < len(group_output.inputs):
                            target_sockets.append(group_output.inputs[output_index])
                if not target_sockets:
                    target_sockets = list(group_output.inputs)
                for socket in target_sockets:
                    for link in socket.links:
                        image_node, chain, details, reason = trace_image_source_detailed(
                            link.from_node,
                            visited,
                            getattr(link, "from_socket", None),
                        )
                        if image_node:
                            return image_node, [node.type, *chain], [detail, *details], reason
            return None, [node.type], [detail], "unresolved_group_output"
        for input_socket in node.inputs:
            for link in input_socket.links:
                image_node, chain, details, reason = trace_image_source_detailed(
                    link.from_node,
                    visited,
                    getattr(link, "from_socket", None),
                )
                if image_node:
                    return image_node, [node.type, *chain], [detail, *details], reason
        return None, [node.type], [detail], "no_image_source"

    def trace_image_source(node, visited=None):
        """Backward-compatible compact form used by older callers."""
        image_node, chain, _details, _reason = trace_image_source_detailed(node, visited)
        return image_node, chain

    image_role_tokens = {
        "Base Color": ("basecolor", "base_color", "albedo", "diffuse", "diffusecolor"),
        "Normal": ("normal", "norm", "nrm", "normalmap"),
        "Roughness": ("rough", "roughness"),
        "Metallic": ("metal", "metallic"),
        "Ambient Occlusion": ("ao", "occlusion", "ambient"),
        "Alpha": ("alpha", "opacity", "transparency"),
        "Emission Color": ("emission", "emissive", "glow"),
    }

    def semantic_role_hints(image_name):
        normalized = re.sub(r"[^a-z0-9]+", "_", str(image_name or "").lower()).strip("_")
        parts = set(filter(None, normalized.split("_")))
        compact = normalized.replace("_", "")

        def matches(token):
            # Short tokens such as ``ao`` must be a complete filename token;
            # longer forms also match compact names such as ``basecolor``.
            return token in parts or (len(token) >= 4 and token in compact)

        return sorted({
            channel
            for channel, tokens in image_role_tokens.items()
            if any(matches(token) for token in tokens)
        })

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
        filepath_lower = str(resolved or getattr(image, "filepath", "") or "").lower()
        tiles = list(getattr(image, "tiles", []) or []) if image.source == "TILED" else []
        tile_numbers = [int(getattr(tile, "number", 0) or 0) for tile in tiles]
        tile_count = len(tiles)
        is_udim = image.source == "TILED" or "<udim>" in filepath_lower or "####" in filepath_lower
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
            "udim": is_udim,
            "udim_tile_count": tile_count,
            "udim_tiles": tile_numbers[:200],
            "packed_texture": bool(image.packed_file),
            "role_hints": semantic_role_hints(image.name),
        }

    for material in materials:
        report = {"name": material.name, "node_based": bool(material.use_nodes), "channels": {}, "issues": [], "semantic_notes": []}
        if not material.use_nodes or not material.node_tree:
            report["issues"].append("material_without_nodes")
            material_reports.append(report)
            continue
        principled_nodes = [node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"]
        bsdf = principled_nodes[0] if principled_nodes else None
        group_count = sum(node.type == "GROUP" for node in material.node_tree.nodes)
        group_names = sorted({str(getattr(node, "node_tree", None).name) for node in material.node_tree.nodes if node.type == "GROUP" and getattr(node, "node_tree", None)})
        uv_map_names = sorted({
            str(getattr(node, "uv_map", "") or "")
            for node in material.node_tree.nodes
            if node.type in {"UVMAP", "TEX_IMAGE"} and getattr(node, "uv_map", "")
        })
        report["node_group_count"] = group_count
        report["node_group_names"] = group_names
        report["uv_map_names"] = uv_map_names
        if group_count:
            report["semantic_notes"].append("node_group_chain_inspected")
        if len(uv_map_names) > 1:
            report["semantic_notes"].append("multiple_uv_channels")
        image_nodes = [node for node in material.node_tree.nodes if node.type == "TEX_IMAGE" and node.image]
        image_node_records = []
        for image_node in image_nodes:
            image_record = image_info(image_node.image)
            image_record.update({
                "node_name": str(image_node.name),
                "uv_map": str(getattr(image_node, "uv_map", "") or ""),
                "output_link_count": sum(len(getattr(output, "links", []) or []) for output in image_node.outputs),
                "used_by_material_graph": any(getattr(output, "links", []) for output in image_node.outputs),
            })
            image_node_records.append(image_record)
            if image_node.image.name not in seen:
                seen.add(image_node.image.name)
                images.append(image_record)
        report["image_nodes"] = image_node_records[:100]
        if bsdf is None:
            report["issues"].append("missing_principled_bsdf")
        if bsdf:
            for channel in pbr_channels:
                socket = bsdf.inputs.get(channel)
                links = list(socket.links) if socket else []
                info = {
                    "connected": bool(links),
                    "source_node": links[0].from_node.name if links else None,
                    "source_socket": socket.name if socket else None,
                    "source_chain": [],
                    "source_node_path": [],
                    "source_trace_status": "not_connected" if not links else "unresolved",
                    "image": None,
                }
                if links:
                    source_node = links[0].from_node
                    image_node, source_chain, source_node_path, trace_reason = trace_image_source_detailed(source_node)
                    info["source_chain"] = source_chain
                    info["source_node_path"] = source_node_path[:32]
                    if image_node and image_node.image:
                        info["image"] = image_info(image_node.image)
                        info["image"]["uv_map_names"] = uv_map_names
                        info["image"]["uv_map"] = str(getattr(image_node, "uv_map", "") or "")
                        expected_non_color = channel in data_channels
                        if expected_non_color and image_node.image.colorspace_settings.name != "Non-Color":
                            report["issues"].append(f"{channel}:expected_non_color")
                        role_hints = semantic_role_hints(image_node.image.name)
                        info["semantic_role_hints"] = role_hints
                        # Only report a likely channel mismatch when the
                        # filename contains one unambiguous role that differs
                        # from the socket.  Ambiguous names (for example a
                        # packed texture named ``roughness_metallic``) remain
                        # evidence for review instead of becoming false errors.
                        if len(role_hints) == 1 and role_hints[0] != channel:
                            report["issues"].append(f"{channel}:possible_wrong_channel")
                        if channel == "Normal" and "NORMAL_MAP" not in source_chain:
                            report["issues"].append("Normal:missing_normal_map_node")
                        if image_node.image.source == "TILED":
                            report["semantic_notes"].append("udim_texture")
                        if image_node.image.packed_file:
                            report["semantic_notes"].append("packed_texture")
                        info["source_trace_status"] = "resolved_image"
                    elif source_node.type == "GROUP":
                        report["semantic_notes"].append(f"{channel}:group_chain_unresolved")
                        info["source_trace_status"] = trace_reason or "unresolved_group_output"
                    else:
                        info["source_trace_status"] = trace_reason or "procedural_or_unresolved"
                if links:
                    info["status"] = "connected" if info["image"] else "procedural_or_unresolved"
                elif socket is None:
                    info["status"] = "not_a_principled_socket"
                else:
                    default_value = getattr(socket, "default_value", None)
                    has_nonzero_constant = False
                    if isinstance(default_value, (float, int)):
                        has_nonzero_constant = abs(float(default_value)) > 1e-6
                    elif default_value is not None:
                        try:
                            has_nonzero_constant = any(abs(float(value)) > 1e-6 for value in default_value)
                        except TypeError:
                            has_nonzero_constant = False
                    info["status"] = "constant" if has_nonzero_constant else "not_connected"
                report["channels"][channel] = info
        connected_image_channels = {}
        for channel, channel_info in report["channels"].items():
            image_record = channel_info.get("image") or {}
            image_name = image_record.get("name")
            if image_name:
                connected_image_channels.setdefault(image_name, []).append(channel)
        report["connected_image_channels"] = connected_image_channels
        report["connected_image_roles"] = sorted({
            role
            for image_name in connected_image_channels
            for image_record in image_node_records
            if image_record.get("name") == image_name
            for role in image_record.get("role_hints", [])
        })
        orphan_roles = []
        for image_record in image_node_records:
            if image_record.get("output_link_count", 0) == 0 and image_record.get("role_hints"):
                orphan_roles.extend(image_record.get("role_hints", []))
                report["issues"].append(f"orphan_image_texture:{image_record.get('name', 'unknown')}")
        if orphan_roles:
            report["semantic_notes"].append("orphan_image_texture")
            report["unconnected_image_roles"] = sorted(set(orphan_roles))
        else:
            report["unconnected_image_roles"] = []
        shared_channels = [channels for channels in connected_image_channels.values() if len(channels) > 1]
        if shared_channels:
            report["semantic_notes"].append("image_shared_across_channels")
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
        report["semantic_notes"] = sorted(set(report["semantic_notes"]))
        pbr_issue_count += len(report["issues"])
        material_reports.append(report)
    missing = [image for image in images if not image["exists"]]
    low_resolution = [image for image in images if max(image["width"], image["height"]) < int(thresholds["min_texture_size"])]
    oversized = [image for image in images if max(image["width"], image["height"]) > int(thresholds["max_texture_size"])]
    texture_total_bytes = sum(image["byte_size"] for image in images if image["exists"])
    texture_memory_bytes = sum(image["width"] * image["height"] * 4 * 4 // 3 for image in images if image["exists"])
    unassigned_slots = sum(slot.material is None for slot in asset.material_slots)
    udim_images = sum(bool(image.get("udim")) for image in images)
    udim_tile_count = sum(int(image.get("udim_tile_count", 0) or 0) for image in images)
    packed_texture_count = sum(bool(image.get("packed_texture")) for image in images)
    multiple_uv_material_count = sum(len(report.get("uv_map_names", [])) > 1 for report in material_reports)
    node_group_material_count = sum(int(report.get("node_group_count", 0) or 0) > 0 for report in material_reports)
    unresolved_chain_count = sum(
        1
        for report in material_reports
        for channel in report.get("channels", {}).values()
        if channel.get("source_trace_status") in {"unresolved_group_output", "procedural_or_unresolved", "cycle_or_revisited_node"}
    )
    orphan_image_texture_count = sum(
        sum(str(issue).startswith("orphan_image_texture:") for issue in report.get("issues", []))
        for report in material_reports
    )
    all_uv_map_names = sorted({
        name
        for report in material_reports
        for name in report.get("uv_map_names", [])
        if name
    })
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
        "udim_tile_count": udim_tile_count,
        "packed_texture_count": packed_texture_count,
        "multiple_uv_material_count": multiple_uv_material_count,
        "node_group_material_count": node_group_material_count,
        "pbr_unresolved_chain_count": unresolved_chain_count,
        "orphan_image_texture_count": orphan_image_texture_count,
        "material_uv_map_names": all_uv_map_names,
        "external_image_count": external_images,
        "pbr_channel_issue_count": pbr_issue_count,
        "textureless_material_count": len(textureless_materials),
        "textureless_materials": textureless_materials[:100],
        "pbr_material_reports": material_reports[:100],
        "texture_images": images[:100],
    }
