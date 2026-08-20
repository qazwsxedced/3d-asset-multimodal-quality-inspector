"""Export self-contained Blender scripts for object/face issue localization.

The inspection worker runs on a temporary copy of an asset.  A standalone
script lets an artist reopen the original asset in Blender and select the same
source objects and polygon indices without having to manually copy IDs from an
HTML report.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Mapping


SELECTION_SCRIPT_VERSION = "1.3"


def build_blender_selection_script(locator_payload: Mapping[str, Any]) -> str:
    """Return a Blender Text Editor script with the locator payload embedded.

    Base64 avoids quoting hazards from user-provided object or material names.
    The generated script deliberately uses only Blender's bundled Python API.
    """
    encoded_payload = base64.b64encode(
        json.dumps(dict(locator_payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return f'''"""Select faces reported by 3D Asset Multimodal Quality Inspector.

Open the original asset in Blender, open this file in the Text Editor, and
click Run Script.  It selects every locatable problem face by default.

For one issue only, set ISSUE_ID below (for example "uv_overlap") and run the
script again.  After running, you can also use select_issue_faces("issue_id")
from Blender's Python Console.  The script prints missing or ambiguously
resolved objects, source topology mismatches, invalid face indices, and face
lists truncated during inspection. Face indices refer to the original source
base mesh, not an applied-modifier or triangulated export mesh. It refuses a
face-count/fingerprint mismatch by default; set ALLOW_TOPOLOGY_MISMATCH only
after manually confirming that the original asset is compatible with this
report.
"""

import base64
import hashlib
import json
import struct

import bpy


SELECTION_SCRIPT_VERSION = {SELECTION_SCRIPT_VERSION!r}
ISSUE_ID = None  # Example: "uv_overlap". None selects every listed issue.
ALLOW_TOPOLOGY_MISMATCH = False  # Keep False to avoid applying stale polygon indices.
LOCATOR = json.loads(base64.b64decode({encoded_payload!r}).decode("utf-8"))


def _topology_fingerprint(obj):
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


def _targets_for_issue(issue_id=None):
    targets = {{}}
    truncations = []
    expected_face_counts = {{}}
    expected_fingerprints = {{}}
    object_selectors = {{}}
    for row in LOCATOR.get("source_issue_breakdown", []):
        object_name = row.get("object_name")
        expected_face_count = int(row.get("face_count", 0) or 0)
        if object_name and expected_face_count > 0:
            expected_face_counts[object_name] = expected_face_count
        if object_name and row.get("topology_fingerprint"):
            expected_fingerprints[object_name] = str(row["topology_fingerprint"])
        if object_name:
            selector = dict(row.get("object_selector") or {{}})
            selector.setdefault("object_name", object_name)
            selector.setdefault("face_count", expected_face_count)
            if row.get("topology_fingerprint"):
                selector.setdefault("topology_fingerprint", str(row["topology_fingerprint"]))
            object_selectors[object_name] = selector
        related = row.get("related_face_indices", {{}}) or {{}}
        counts = row.get("related_face_counts", {{}}) or {{}}
        issue_names = [issue_id] if issue_id else related.keys()
        for name in issue_names:
            if name not in related:
                continue
            indices = {{int(index) for index in related.get(name, [])}}
            if not indices:
                continue
            targets.setdefault(object_name, set()).update(indices)
            expected = int(counts.get(name, len(indices)) or 0)
            if expected > len(indices):
                truncations.append((object_name, name, len(indices), expected))
    return targets, truncations, expected_face_counts, expected_fingerprints, object_selectors


def _distance(left, right):
    if not left or not right or len(left) != len(right):
        return 1e9
    return sum((float(a) - float(b)) ** 2 for a, b in zip(left, right))


def _resolve_object(selector):
    """Resolve by name first, then base-mesh fingerprint and transform evidence."""
    expected_name = selector.get("object_name")
    expected_fingerprint = selector.get("topology_fingerprint")
    if expected_name:
        named = bpy.data.objects.get(expected_name)
        if named is not None and named.type == "MESH":
            if not expected_fingerprint or _topology_fingerprint(named) == expected_fingerprint:
                return named, "name"
    candidates = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        if expected_fingerprint and _topology_fingerprint(obj) != expected_fingerprint:
            continue
        if selector.get("face_count") and len(obj.data.polygons) != int(selector["face_count"]):
            continue
        if selector.get("vertex_count") and len(obj.data.vertices) != int(selector["vertex_count"]):
            continue
        candidates.append(obj)
    if not candidates:
        return None, "not_found"
    candidates.sort(key=lambda obj: (_distance(getattr(obj.matrix_world, "translation", None), selector.get("world_location")), obj.name))
    if len(candidates) > 1:
        first = _distance(getattr(candidates[0].matrix_world, "translation", None), selector.get("world_location"))
        second = _distance(getattr(candidates[1].matrix_world, "translation", None), selector.get("world_location"))
        if abs(first - second) < 1e-12:
            return None, "ambiguous"
    return candidates[0], "fingerprint"


def select_issue_faces(issue_id=ISSUE_ID):
    """Select source faces for one issue, or every issue when *issue_id* is None."""
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    targets, truncations, expected_face_counts, expected_fingerprints, object_selectors = _targets_for_issue(issue_id)
    selected_objects = []
    missing_objects = []
    ambiguous_objects = []
    topology_mismatches = []
    identity_mismatches = []
    invalid_face_indices = []
    resolved_objects = []
    selected_face_references = 0
    for object_name, indices in targets.items():
        obj, resolution = _resolve_object(object_selectors.get(object_name, {{"object_name": object_name}}))
        if obj is None:
            (ambiguous_objects if resolution == "ambiguous" else missing_objects).append(object_name)
            continue
        resolved_objects.append({{"requested": object_name, "resolved": obj.name, "method": resolution}})
        expected_face_count = expected_face_counts.get(object_name)
        actual_face_count = len(obj.data.polygons)
        if expected_face_count and actual_face_count != expected_face_count:
            topology_mismatches.append((object_name, expected_face_count, actual_face_count))
            if not ALLOW_TOPOLOGY_MISMATCH:
                continue
        expected_fingerprint = expected_fingerprints.get(object_name)
        if expected_fingerprint:
            actual_fingerprint = _topology_fingerprint(obj)
            if actual_fingerprint != expected_fingerprint:
                identity_mismatches.append((object_name, expected_fingerprint[:12], actual_fingerprint[:12]))
                if not ALLOW_TOPOLOGY_MISMATCH:
                    continue
        valid_indices = {{int(index) for index in indices if 0 <= int(index) < actual_face_count}}
        invalid = sorted(int(index) for index in indices if int(index) < 0 or int(index) >= actual_face_count)
        if invalid:
            invalid_face_indices.append((object_name, invalid))
        for polygon in obj.data.polygons:
            polygon.select = polygon.index in valid_indices
        obj.select_set(True)
        selected_objects.append(obj)
        selected_face_references += len(valid_indices)
    if selected_objects:
        bpy.context.view_layer.objects.active = selected_objects[0]
        bpy.context.tool_settings.mesh_select_mode = (False, False, True)
        bpy.ops.object.mode_set(mode="EDIT")
    print("[3D Quality Inspector] selected", selected_face_references, "face reference(s) in", len(selected_objects), "object(s).")
    if missing_objects:
        print("[3D Quality Inspector] object name(s) not found:", ", ".join(missing_objects))
    if ambiguous_objects:
        print("[3D Quality Inspector] object name(s) matched multiple meshes:", ", ".join(ambiguous_objects))
    for requested, resolved, method in resolved_objects:
        if requested != resolved or method != "name":
            print(f"[3D Quality Inspector] resolved {{requested}} to {{resolved}} using {{method}} evidence.")
    for object_name, expected, actual in topology_mismatches:
        action = "skipped" if not ALLOW_TOPOLOGY_MISMATCH else "selected with override"
        print(f"[3D Quality Inspector] {{object_name}} topology mismatch: expected {{expected}} faces, found {{actual}}; {{action}}.")
    for object_name, expected, actual in identity_mismatches:
        action = "skipped" if not ALLOW_TOPOLOGY_MISMATCH else "selected with override"
        print(f"[3D Quality Inspector] {{object_name}} mesh fingerprint mismatch: expected {{expected}}, found {{actual}}; {{action}}.")
    for object_name, name, available, expected in truncations:
        print(f"[3D Quality Inspector] {{name}} on {{object_name}}: only {{available}}/{{expected}} face indices were exported (inspection cap).")
    for object_name, indices in invalid_face_indices:
        print(f"[3D Quality Inspector] {{object_name}} has {{len(indices)}} face index(es) outside the current base mesh; they were skipped.")
    if not targets:
        print("[3D Quality Inspector] no face indices are available for this issue. Review the locator JSON and visual evidence.")
    return {{"selected_objects": [obj.name for obj in selected_objects], "missing_objects": missing_objects, "ambiguous_objects": ambiguous_objects, "resolved_objects": resolved_objects, "topology_mismatches": topology_mismatches, "identity_mismatches": identity_mismatches, "invalid_face_indices": invalid_face_indices, "truncated": truncations}}


print("[3D Quality Inspector] available issue IDs:", ", ".join(sorted((LOCATOR.get("issue_related_face_counts", {{}}) or {{}}).keys())) or "none")
select_issue_faces()
'''


def write_blender_selection_script(locator_payload: Mapping[str, Any], output_path: Path) -> Path:
    """Write the self-contained Blender selection script and return its path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_blender_selection_script(locator_payload), encoding="utf-8")
    return output_path
