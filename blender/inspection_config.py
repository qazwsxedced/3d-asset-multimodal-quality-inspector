"""Configuration and adaptive inspection policies for Blender workers."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.threshold_config import load_thresholds as load_validated_thresholds


def load_thresholds(path: Path) -> dict:
    return load_validated_thresholds(path)


def choose_geometry_adaptive_settings(args: argparse.Namespace, thresholds: dict, geometry: dict) -> dict:
    """Reduce expensive evidence rendering when imported geometry is large."""
    triangle_count = int(geometry.get("triangle_count", 0) or 0)
    vertex_count = int(geometry.get("vertex_count", 0) or 0)
    requested_views = int(args.views)
    requested_resolution = int(args.resolution)
    requested_limit = int(thresholds.get("max_diagnostic_triangles", 50_000))
    if triangle_count >= 1_000_000:
        strategy = "geometry_ultra_conservative"
        views, resolution, diagnostic_limit = 1, min(requested_resolution, 96), min(requested_limit, 10_000)
        reason = "triangle_count >= 1,000,000"
    elif triangle_count >= 250_000:
        strategy = "geometry_large_conservative"
        views, resolution, diagnostic_limit = min(requested_views, 2), min(requested_resolution, 128), min(requested_limit, 20_000)
        reason = "triangle_count >= 250,000"
    elif triangle_count >= 100_000:
        strategy = "geometry_large_balanced"
        views, resolution, diagnostic_limit = min(requested_views, 3), min(requested_resolution, 160), min(requested_limit, 30_000)
        reason = "triangle_count >= 100,000"
    else:
        strategy = "geometry_default"
        views, resolution, diagnostic_limit = requested_views, requested_resolution, requested_limit
        reason = "triangle_count below adaptive geometry thresholds"
    return {
        "strategy": strategy,
        "reason": reason,
        "vertex_count": vertex_count,
        "triangle_count": triangle_count,
        "requested_views": requested_views,
        "requested_resolution": requested_resolution,
        "requested_max_diagnostic_triangles": requested_limit,
        "effective_views": max(1, min(8, views)),
        "effective_resolution": max(64, resolution),
        "effective_max_diagnostic_triangles": max(1, diagnostic_limit),
    }
