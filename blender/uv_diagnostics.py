"""UV layout, density, stretch, island, and coverage diagnostics."""

from __future__ import annotations

import math
from pathlib import Path

import bpy

from inspection_config import load_thresholds

DEFAULT_THRESHOLDS = Path(__file__).resolve().parents[1] / "config" / "inspection_thresholds.json"

def uv_diagnostics(asset: bpy.types.Object, thresholds: dict | None = None) -> dict:
    """Measure UV completeness, density, stretch, islands and spacing."""
    thresholds = thresholds or load_thresholds(DEFAULT_THRESHOLDS)
    mesh = asset.data
    layer = mesh.uv_layers.active
    if layer is None:
        return {
            "uv_status": "not_present",
            "uv_loop_count": 0,
            "uv_out_of_bounds_loop_count": 0,
            "uv_zero_area_triangle_count": 0,
            "uv_valid_triangle_count": 0,
            "uv_island_count": 0,
            "uv_density_stats": {},
            "uv_stretch_stats": {},
            "uv_min_island_gap": None,
            "uv_analysis_sampled": False,
            "uv_analysis_total_triangle_count": sum(max(0, len(poly.vertices) - 2) for poly in mesh.polygons),
            "uv_analysis_analyzed_triangle_count": 0,
            "uv_analysis_coverage_ratio": 0.0,
        }

    coords = [tuple(float(value) for value in layer.data[index].uv) for index in range(len(layer.data))]
    out_of_bounds = sum(x < 0.0 or x > 1.0 or y < 0.0 or y > 1.0 for x, y in coords)
    zero_area = 0
    analyzed_triangles = 0
    triangles = []
    polygon_uv_edges = {}
    max_triangles = max(1, int(thresholds["max_diagnostic_triangles"]))
    polygon_step = max(1, math.ceil(len(mesh.polygons) / max_triangles))
    for poly_index, poly in enumerate(mesh.polygons):
        if poly_index % polygon_step:
            continue
        loops = list(poly.loop_indices)
        if len(loops) < 3:
            continue
        anchor = coords[loops[0]]
        for index in range(1, len(loops) - 1):
            analyzed_triangles += 1
            b = coords[loops[index]]
            c = coords[loops[index + 1]]
            area = abs((b[0] - anchor[0]) * (c[1] - anchor[1]) - (b[1] - anchor[1]) * (c[0] - anchor[0]))
            if area < 1e-10:
                zero_area += 1
            a3 = asset.matrix_world @ mesh.vertices[poly.vertices[0]].co
            b3 = asset.matrix_world @ mesh.vertices[poly.vertices[index]].co
            c3 = asset.matrix_world @ mesh.vertices[poly.vertices[index + 1]].co
            area3d = ((b3 - a3).cross(c3 - a3)).length * 0.5
            uv_area = area * 0.5
            if area3d > 1e-10 and uv_area > 1e-10:
                triangles.append({"poly_index": poly.index, "uv": (anchor, b, c), "uv_area": uv_area, "area3d": area3d})
        for index, vertex in enumerate(poly.vertices):
            next_index = (index + 1) % len(poly.vertices)
            key = tuple(sorted((vertex, poly.vertices[next_index])))
            polygon_uv_edges.setdefault(key, []).append((poly.index, coords[loops[index]], coords[loops[next_index]]))

    densities = [triangle["uv_area"] / triangle["area3d"] for triangle in triangles]
    density_median = sorted(densities)[len(densities) // 2] if densities else 0.0
    stretches = [max(density / density_median, density_median / density) if density and density_median else 0.0 for density in densities]

    parent = {poly.index: poly.index for poly in mesh.polygons}

    def find(value):
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    def uv_pair_matches(left, right):
        return (max(abs(left[0][0] - right[0][0]), abs(left[0][1] - right[0][1])) < 1e-5 and
                max(abs(left[1][0] - right[1][0]), abs(left[1][1] - right[1][1])) < 1e-5) or (
                max(abs(left[0][0] - right[1][0]), abs(left[0][1] - right[1][1])) < 1e-5 and
                max(abs(left[1][0] - right[0][0]), abs(left[1][1] - right[0][1])) < 1e-5)

    for uses in polygon_uv_edges.values():
        if len(uses) == 2 and uv_pair_matches(uses[0][1:], uses[1][1:]):
            union(uses[0][0], uses[1][0])
    islands = {}
    for triangle, stretch in zip(triangles, stretches):
        island_id = find(triangle["poly_index"])
        island = islands.setdefault(island_id, {"uv_area": 0.0, "area3d": 0.0, "triangles": 0, "points": []})
        island["uv_area"] += triangle["uv_area"]
        island["area3d"] += triangle["area3d"]
        island["triangles"] += 1
        island["points"].extend(triangle["uv"])
    island_records = []
    for island_id, island in islands.items():
        xs = [point[0] for point in island["points"]]
        ys = [point[1] for point in island["points"]]
        island_records.append({
            "island_id": island_id,
            "uv_area": round(island["uv_area"], 8),
            "surface_area": round(island["area3d"], 8),
            "triangle_count": island["triangles"],
            "bounds": [round(min(xs), 6), round(min(ys), 6), round(max(xs), 6), round(max(ys), 6)],
        })
    min_gap = None
    gap_pair_limit = max(1, int(thresholds["max_component_gap_pairs"]))
    gap_pair_count = 0
    gap_complete = True
    for index, left in enumerate(island_records):
        for right in island_records[index + 1:]:
            if gap_pair_count >= gap_pair_limit:
                gap_complete = False
                break
            gap_pair_count += 1
            horizontal = max(0.0, max(left["bounds"][0], right["bounds"][0]) - min(left["bounds"][2], right["bounds"][2]))
            vertical = max(0.0, max(left["bounds"][1], right["bounds"][1]) - min(left["bounds"][3], right["bounds"][3]))
            gap = math.sqrt(horizontal * horizontal + vertical * vertical)
            min_gap = gap if min_gap is None else min(min_gap, gap)
        if not gap_complete:
            break
    xs = [point[0] for point in coords]
    ys = [point[1] for point in coords]

    def stats(values):
        ordered = sorted(values)
        if not ordered:
            return {"min": 0.0, "p05": 0.0, "median": 0.0, "p95": 0.0, "max": 0.0}
        return {
            "min": round(ordered[0], 8),
            "p05": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.05))], 8),
            "median": round(ordered[len(ordered) // 2], 8),
            "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 8),
            "max": round(ordered[-1], 8),
        }
    return {
        "uv_status": "present",
        "uv_loop_count": len(coords),
        "uv_out_of_bounds_loop_count": out_of_bounds,
        "uv_zero_area_triangle_count": zero_area,
        "uv_valid_triangle_count": len(triangles),
        "uv_island_count": len(island_records),
        "uv_islands": sorted(island_records, key=lambda item: item["uv_area"], reverse=True)[:100],
        "uv_density_stats": stats(densities),
        "uv_stretch_stats": stats(stretches),
        "uv_min_island_gap": round(min_gap, 8) if min_gap is not None else None,
        "uv_analysis_sampled": polygon_step > 1,
        "uv_analysis_triangle_limit": max_triangles,
        "uv_analysis_total_triangle_count": sum(max(0, len(poly.vertices) - 2) for poly in mesh.polygons),
        "uv_analysis_analyzed_triangle_count": analyzed_triangles,
        "uv_analysis_coverage_ratio": round(
            analyzed_triangles / max(1, sum(max(0, len(poly.vertices) - 2) for poly in mesh.polygons)), 6
        ),
        "uv_island_gap_analysis_complete": gap_complete,
        "uv_bounds": {
            "min": [round(min(xs), 6), round(min(ys), 6)] if xs else [0.0, 0.0],
            "max": [round(max(xs), 6), round(max(ys), 6)] if xs else [0.0, 0.0],
        },
    }
