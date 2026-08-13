"""Fail-fast dataset QA for manifest integrity and diagnosis leakage."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data_protocol import read_jsonl, validate_sample


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    args = ap.parse_args()
    rows = read_jsonl(args.manifest)
    root = args.manifest.resolve().parent
    errors = []
    ids = [r.get("id") for r in rows]
    scenes = [r.get("scene_id") for r in rows]
    for row in rows:
        errors.extend(f"{row.get('id')}: {e}" for e in validate_sample(row))
        for value in row.get("images", {}).values():
            paths = value if isinstance(value, list) else [value]
            for rel in paths:
                if rel and not (root / rel).exists():
                    errors.append(f"{row.get('id')}: missing image {rel}")
    duplicates = [x for x, n in Counter(ids).items() if n > 1]
    duplicate_scenes = [x for x, n in Counter(scenes).items() if x and n > 1]
    if duplicates:
        errors.append(f"duplicate sample ids: {duplicates[:5]}")
    if duplicate_scenes:
        errors.append(f"scene ids reused across rows; check scene-level split: {duplicate_scenes[:5]}")
    split_counts = Counter(r.get("split") for r in rows)
    print({"samples": len(rows), "splits": dict(split_counts), "unique_scenes": len(set(scenes)), "errors": len(errors)})
    if errors:
        print("\n".join(errors[:50]))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
