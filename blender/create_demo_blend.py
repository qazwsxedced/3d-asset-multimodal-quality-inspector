"""Create a small local .blend asset with one auditable quality defect.

This is a demo fixture generator, not part of the benchmark data pipeline.
Example:
  blender -b -P blender/create_demo_blend.py -- --out runtime_uploads/demo_uv_overlap.blend --defect uv_overlap
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from generate_scene_dataset import ASSET_FAMILIES, DEFECTS, MATERIAL_COLORS, apply_defects, make_asset


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--defect", choices=DEFECTS, required=True)
    parser.add_argument("--family", choices=ASSET_FAMILIES, default="torus")
    args = parser.parse_args(argv)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    asset = make_asset(random.Random(19), args.family, scale=1.0, rotation=0.0, color=MATERIAL_COLORS[0])
    apply_defects(asset, [args.defect])
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out.resolve()))
    print(f"saved demo asset: {args.out} ({args.defect})")


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
