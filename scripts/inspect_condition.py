from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data_protocol import build_condition, read_jsonl


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=Path, required=True)
    ap.add_argument("--condition", choices=["B0", "B1", "B2", "B3", "B4"], required=True)
    args = ap.parse_args()
    rows = read_jsonl(args.sample)
    if not rows:
        raise SystemExit("manifest is empty")
    print(json.dumps(build_condition(rows[0], args.condition, args.sample), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
