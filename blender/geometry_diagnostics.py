"""Imported-mesh topology and connected-component diagnostics."""

from __future__ import annotations

import bpy
from mathutils import Vector

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
