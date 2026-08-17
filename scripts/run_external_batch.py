"""Preprocess and label a directory of external ``.blend`` assets.

Each asset is isolated in its own job directory.  Blender failures are retried
and every attempt is recorded in ``preprocess_log.jsonl``.  Successful jobs
are merged into an evaluation manifest whose images still point to the
generated runtime evidence, while labels remain separate from preprocessing.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[int(q * (len(values) - 1))]


def rel_image_paths(row: dict, job_dir: Path, output_dir: Path) -> dict:
    images = row.get("images", {})
    result = {"views": [], "uv": None, "normal": None}
    for view in images.get("views", []):
        result["views"].append(Path(os.path.relpath(job_dir / view, output_dir)).as_posix())
    for key in ("uv", "normal"):
        if images.get(key):
            result[key] = Path(os.path.relpath(job_dir / images[key], output_dir)).as_posix()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--labels", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--blender", required=True)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--views", type=int, default=4)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if args.retries < 0:
        raise SystemExit("--retries must be non-negative")
    assets_dir = args.assets_dir.resolve()
    labels_path = (args.labels or assets_dir / "labels.jsonl").resolve()
    if not assets_dir.exists():
        raise SystemExit(f"assets directory not found: {assets_dir}")
    if not labels_path.exists():
        raise SystemExit(f"labels file not found: {labels_path}")

    labels = {row["source_file"]: row for row in read_jsonl(labels_path)}
    output_dir = args.out.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir = output_dir / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    manifest_rows: list[dict] = []

    for asset_path in sorted(assets_dir.glob("*.blend")):
        label = labels.get(asset_path.name)
        if not label:
            records.append({"source_file": asset_path.name, "status": "skipped", "error": "missing label"})
            continue
        job_dir = jobs_dir / label["id"]
        job_dir.mkdir(parents=True, exist_ok=True)
        command = [
            args.blender, "-b", "-P", str(Path(__file__).resolve().parents[1] / "blender" / "inspect_asset.py"),
            "--", "--input", str(asset_path), "--out", str(job_dir), "--views", str(args.views),
            "--resolution", str(args.resolution),
        ]
        started = time.perf_counter()
        attempts = 0
        completed = None
        error = None
        while attempts <= args.retries:
            attempts += 1
            try:
                completed = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout)
            except subprocess.TimeoutExpired as exc:
                completed = None
                error = f"timeout after {args.timeout}s"
            if completed is not None and completed.returncode == 0:
                error = None
                break
            if completed is not None:
                error = (completed.stderr or completed.stdout or "Blender returned non-zero status")[-2000:]

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        runtime_manifest = job_dir / "manifest.jsonl"
        record = {
            "id": label["id"], "source_file": asset_path.name, "attempts": attempts,
            "duration_ms": duration_ms, "status": "ok" if runtime_manifest.exists() and error is None else "failed",
            "error": error,
        }
        records.append(record)
        if record["status"] != "ok":
            continue

        runtime_row = read_jsonl(runtime_manifest)[0]
        runtime_row["id"] = label["id"]
        runtime_row["scene_id"] = label["id"]
        runtime_row["generalization"] = "external_asset"
        runtime_row["question_type"] = "defect_detection"
        runtime_row["answer"] = label["answer"]
        runtime_row["images"] = rel_image_paths(runtime_row, job_dir, output_dir)
        runtime_row["metadata"]["asset_family"] = label.get("asset_family", "external")
        runtime_row["metadata"]["source_file"] = asset_path.name
        manifest_rows.append(runtime_row)

    (output_dir / "manifest.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in manifest_rows), encoding="utf-8"
    )
    (output_dir / "preprocess_log.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8"
    )
    durations = [float(row["duration_ms"]) for row in records if row.get("status") == "ok"]
    summary = {
        "total_assets": len(records), "successful": sum(row.get("status") == "ok" for row in records),
        "failed": sum(row.get("status") == "failed" for row in records),
        "skipped": sum(row.get("status") == "skipped" for row in records),
        "attempts_total": sum(int(row.get("attempts", 0)) for row in records),
        "duration_ms": {"mean": sum(durations) / len(durations) if durations else None,
                        "p50": percentile(durations, 0.50), "p95": percentile(durations, 0.95)},
        "manifest": str(output_dir / "manifest.jsonl"),
        "log": str(output_dir / "preprocess_log.jsonl"),
    }
    (output_dir / "batch_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
