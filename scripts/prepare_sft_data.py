"""Export manifest rows to a human-readable Qwen-style SFT JSON file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data_protocol import build_condition, read_jsonl
from src.qwen_training import answer_text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--condition", choices=["B3", "B4"], default="B4")
    ap.add_argument("--split", choices=["train", "val", "test", "all"], default="train")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    rows = read_jsonl(args.manifest)
    if args.split != "all":
        rows = [row for row in rows if row.get("split") == args.split]
    output = []
    for row in rows:
        payload = build_condition(row, args.condition, args.manifest)
        user_content = [{"type": "image", "image": path} for path in payload["image_paths"]]
        user_content.append({"type": "text", "text": payload["prompt"]})
        output.append({"id": row["id"], "messages": [{"role": "user", "content": user_content}, {"role": "assistant", "content": answer_text(row["answer"])}]})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(output)} SFT records to {args.out}")


if __name__ == "__main__":
    main()
