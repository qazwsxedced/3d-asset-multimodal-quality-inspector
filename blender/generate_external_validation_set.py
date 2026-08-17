"""Create a small manually auditable external-asset validation fixture.

The generated files are ordinary ``.blend`` assets.  ``labels.jsonl`` records
the known injected defect for each file and is kept separate from the Blender
asset so the preprocessing path remains identical to an uploaded asset.

Example:
  blender -b -P blender/generate_external_validation_set.py -- \
    --out data/external_blend_validation_v1 --n-per-category 4 --seed 31
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from generate_scene_dataset import ASSET_FAMILIES, DEFECTS, MATERIAL_COLORS, apply_defects, make_asset


def severity(defects: list[str]) -> str:
    return "none" if not defects else ("high" if len(defects) > 1 or "hole" in defects else "medium")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--n-per-category", type=int, default=4)
    parser.add_argument("--seed", type=int, default=31)
    args = parser.parse_args(argv)
    if args.n_per_category < 1:
        raise SystemExit("--n-per-category must be positive")

    args.out.mkdir(parents=True, exist_ok=True)
    categories: list[list[str]] = [[] for _ in range(args.n_per_category)]
    for defect in DEFECTS:
        categories.extend([[defect] for _ in range(args.n_per_category)])

    labels: list[dict] = []
    for index, defects in enumerate(categories):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        rng = random.Random(args.seed + index * 997)
        family = ASSET_FAMILIES[index % len(ASSET_FAMILIES)]
        filename = f"asset_{index:03d}_{'clean' if not defects else defects[0]}.blend"
        asset = make_asset(
            rng,
            family=family,
            scale=round(rng.uniform(0.9, 1.1), 4),
            rotation=round(rng.uniform(-3.14, 3.14), 4),
            color=MATERIAL_COLORS[index % len(MATERIAL_COLORS)],
        )
        apply_defects(asset, defects)
        output = args.out / filename
        bpy.ops.wm.save_as_mainfile(filepath=str(output.resolve()))
        labels.append({
            "id": f"external_{index:03d}",
            "source_file": filename,
            "asset_family": family,
            "answer": {
                "quality": "pass" if not defects else "fail",
                "defect_types": defects,
                "severity": severity(defects),
            },
        })

    (args.out / "labels.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in labels),
        encoding="utf-8",
    )
    print(json.dumps({"assets": len(labels), "labels": str(args.out / "labels.jsonl")}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
