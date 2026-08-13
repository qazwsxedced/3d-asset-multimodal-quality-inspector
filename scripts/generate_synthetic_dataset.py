"""Generate deterministic proxy data for the asset-quality diagnosis task.

The images are intentionally lightweight QA assets. Blender is the source of
truth for final renders; this script validates the manifest, defect labels,
and B0-B4 evaluation before a GPU is used.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data_protocol import DEFECT_TYPES, SEVERITIES, write_jsonl

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = ImageDraw = None

DEFECT_LIST = sorted(DEFECT_TYPES)
REPAIR = {
    "non_manifold": "merge or separate non-manifold components",
    "uv_overlap": "repack overlapping UV islands",
    "flipped_normals": "recalculate and validate face normals",
    "hole": "fill boundary loops and inspect watertightness",
    "stretched_triangles": "rebuild stretched regions with better topology",
    "degenerate_faces": "remove zero-area faces and re-triangulate",
}


def make_image(path: Path, seed: int, kind: str, defects: list[str], size: int = 256) -> None:
    if Image is None:
        return
    rng = random.Random(seed)
    bg = {"render": (242, 242, 242), "uv": (230, 245, 230), "normal": (225, 235, 250)}[kind]
    image = Image.new("RGB", (size, size), bg)
    draw = ImageDraw.Draw(image)
    if kind == "render":
        draw.ellipse((48, 42, 208, 205), fill=(150, 155, 165), outline=(30, 30, 30), width=2)
        if "hole" in defects:
            draw.ellipse((105, 95, 150, 140), fill=bg, outline=(80, 80, 80), width=2)
        if "flipped_normals" in defects:
            draw.line((65, 90, 190, 55), fill=(220, 40, 40), width=4)
        if "stretched_triangles" in defects:
            for x in range(55, 205, 24):
                draw.line((128, 125, x, 55), fill=(225, 150, 40), width=2)
        if "degenerate_faces" in defects:
            draw.line((80, 185, 185, 185), fill=(190, 30, 30), width=3)
    elif kind == "uv":
        for i in range(8):
            x = 25 + (i % 4) * 52
            y = 35 + (i // 4) * 85
            draw.rectangle((x, y, x + 42, y + 60), outline=(20, 130, 80), width=2)
        if "uv_overlap" in defects:
            draw.rectangle((90, 80, 170, 170), outline=(220, 40, 40), width=5)
            draw.rectangle((115, 60, 195, 150), outline=(220, 40, 40), width=3)
    else:
        for i in range(8):
            x, y = rng.randint(30, 220), rng.randint(30, 220)
            color = (80, 120 + i * 10, 220 - i * 8)
            draw.line((128, 128, x, y), fill=color, width=2)
        if "flipped_normals" in defects:
            draw.line((128, 128, 45, 210), fill=(235, 35, 35), width=5)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def make_sample(
    index: int,
    rng: random.Random,
    root: Path,
    views: int,
    clean_prob: float = 0.25,
    balanced_defects: bool = False,
) -> dict:
    scene_id = f"asset_{index:05d}"
    split = "test" if index % 10 in (0, 1) else ("val" if index % 10 == 2 else "train")
    test_ordinal = (index // 10) * 2 + (index % 10) if split == "test" else -1
    # Sample defect status independently of split/group. The previous
    # index-based rule made every unseen_scene sample clean and every
    # unseen_view sample defective, invalidating the generalization analysis.
    if split == "test":
        # Fixed balanced test status: 12 clean / 12 defective for n=120.
        clean_test_ordinals = {0, 2, 4, 7, 9, 11, 13, 15, 18, 20, 21, 23}
        n_defects = 0 if test_ordinal in clean_test_ordinals else rng.choice([1, 1, 2])
    else:
        n_defects = 0 if rng.random() < clean_prob else rng.choice([1, 1, 2])
    if n_defects == 0:
        defects = []
    elif balanced_defects and split != "test":
        # Rotate the primary label over the six defect classes so that the
        # training distribution does not learn a dominant defect prior.
        primary = DEFECT_LIST[index % len(DEFECT_LIST)]
        defects = [primary]
        if n_defects > 1:
            remaining = [d for d in DEFECT_LIST if d != primary]
            defects.append(rng.choice(remaining))
        defects = sorted(defects)
    else:
        defects = sorted(rng.sample(DEFECT_LIST, n_defects))
    severity = "none" if not defects else ("high" if len(defects) > 1 or "hole" in defects else rng.choice(["low", "medium"]))
    # Hold out repair_planning from train/val so unseen_question_type is a
    # real holdout rather than an index label.
    if split == "test" and test_ordinal % 4 == 0:
        question_type = "repair_planning"
        generalization = "unseen_question_type"
    else:
        question_type = rng.choice(["quality_summary", "defect_detection", "severity"])
        generalization = "unseen_scene" if split == "test" else "in_distribution"
    question = {
        "quality_summary": "请判断这个 3D 资产是否通过质量检查，并列出主要问题。",
        "defect_detection": "请识别这个 3D 资产中存在的拓扑、UV 和法线问题。",
        "severity": "请评估这个 3D 资产的质量问题严重程度。",
        "repair_planning": "请根据发现的质量问题给出最短的修复计划。",
    }[question_type]
    answer = {"quality": "pass" if not defects else "fail", "defect_types": defects, "severity": severity}
    if question_type == "repair_planning":
        answer["repair_plan"] = [REPAIR[d] for d in defects] if defects else ["no repair required"]
    asset_dir = root / "images" / scene_id
    views_rel = []
    for view in range(views):
        rel = f"images/{scene_id}/view_{view}.png"
        views_rel.append(rel)
        make_image(root / rel, index * 101 + view, "render", defects)
    uv_rel, normal_rel = f"images/{scene_id}/uv.png", f"images/{scene_id}/normal.png"
    make_image(root / uv_rel, index * 101 + 50, "uv", defects)
    make_image(root / normal_rel, index * 101 + 60, "normal", defects)
    # Only observable low-level signals are allowed in metadata.
    metadata = {
        "asset_id": scene_id,
        "vertex_count": 768 + index * 3,
        "face_count": 1450 + index * 5,
        "boundary_edge_count": 0 if "hole" not in defects else 2 + defects.index("hole"),
        "non_manifold_edge_count": 0 if "non_manifold" not in defects else 3,
        "uv_overlap_ratio": 0.0 if "uv_overlap" not in defects else 0.18,
        "flipped_normal_count": 0 if "flipped_normals" not in defects else 12,
        "degenerate_face_count": 0 if "degenerate_faces" not in defects else 4,
        "triangle_area_stats": {"min": 0.0 if "degenerate_faces" in defects else 0.002, "median": 0.17, "max": 3.8 if "stretched_triangles" in defects else 1.4},
        "camera_views": [{"id": v, "azimuth": v * 360 / views, "elevation": 20} for v in range(views)],
    }
    return {"id": f"sample_{index:06d}", "scene_id": scene_id, "split": split, "generalization": generalization, "question_type": question_type, "question": question, "answer": answer, "images": {"views": views_rel, "uv": uv_rel, "normal": normal_rel}, "metadata": metadata}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--views", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--clean-prob", type=float, default=0.25)
    ap.add_argument("--balanced-defects", action="store_true")
    args = ap.parse_args()
    if not 0.0 <= args.clean_prob <= 1.0:
        ap.error("--clean-prob must be between 0 and 1")
    args.out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    rows = [make_sample(i, rng, args.out, args.views, args.clean_prob, args.balanced_defects) for i in range(args.n)]
    write_jsonl(args.out / "manifest.jsonl", rows)
    (args.out / "dataset_info.json").write_text(json.dumps({"n": len(rows), "seed": args.seed, "views": args.views, "clean_prob": args.clean_prob, "balanced_defects": args.balanced_defects, "task": "asset_quality_diagnosis", "image_backend": "Pillow" if Image else "metadata_only"}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(rows)} samples to {args.out / 'manifest.jsonl'}")


if __name__ == "__main__":
    main()
