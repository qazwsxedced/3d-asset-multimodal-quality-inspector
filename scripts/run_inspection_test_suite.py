"""Run the generated FBX/OBJ/Blend fixture set through inspect_asset.py."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtime_artifacts import validate_runtime_artifacts


REQUIRED_ARTIFACTS = ("issue_locator", "issue_selection_script")


def get_path(value: object, path: str) -> object:
    """Read dotted metadata paths, including list indexes, for assertions."""
    current = value
    for part in path.split("."):
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def check_assertion(metadata: dict, assertion: dict) -> tuple[bool, dict]:
    path = str(assertion.get("path", ""))
    operator = str(assertion.get("op", "eq"))
    expected = assertion.get("value")
    actual = get_path(metadata, path)
    try:
        if operator == "eq":
            passed = actual == expected
        elif operator == "ne":
            passed = actual != expected
        elif operator == "gt":
            passed = actual is not None and actual > expected
        elif operator == "gte":
            passed = actual is not None and actual >= expected
        elif operator == "lt":
            passed = actual is not None and actual < expected
        elif operator == "lte":
            passed = actual is not None and actual <= expected
        elif operator == "contains":
            passed = isinstance(actual, (list, str, dict)) and expected in actual
        elif operator == "nonempty":
            passed = bool(actual)
        else:
            passed = False
    except (TypeError, ValueError):
        passed = False
    return passed, {"path": path, "op": operator, "expected": expected, "actual": actual, "label": assertion.get("label", path)}


def check_artifact_contract(row: dict[str, Any], case_out: Path) -> list[dict[str, str]]:
    """Verify every Blender run emits usable locator artifacts, not only a manifest."""
    failures: list[dict[str, str]] = []
    artifacts = row.get("artifacts", {}) or {}
    if not isinstance(artifacts, dict):
        return [{"artifact": "artifacts", "reason": "manifest artifacts field is not an object"}]
    case_root = case_out.resolve()
    for key in REQUIRED_ARTIFACTS:
        relative_path = artifacts.get(key)
        if not relative_path:
            failures.append({"artifact": key, "reason": "missing from manifest"})
            continue
        artifact_path = (case_out / str(relative_path)).resolve()
        try:
            artifact_path.relative_to(case_root)
        except ValueError:
            failures.append({"artifact": key, "reason": "path escapes case output directory"})
            continue
        if not artifact_path.is_file():
            failures.append({"artifact": key, "reason": "file does not exist"})
            continue
        try:
            if key == "issue_locator":
                payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict) or not payload.get("schema_version"):
                    failures.append({"artifact": key, "reason": "missing locator schema version"})
                elif "source_issue_breakdown" not in payload:
                    failures.append({"artifact": key, "reason": "missing source object breakdown"})
            elif key == "issue_selection_script":
                compile(artifact_path.read_text(encoding="utf-8"), str(artifact_path), "exec")
        except (OSError, UnicodeError, json.JSONDecodeError, SyntaxError) as exc:
            failures.append({"artifact": key, "reason": f"invalid artifact: {exc}"})
    return failures


def resolve_runtime_artifact_paths(row: dict[str, Any], case_out: Path) -> dict[str, Any]:
    """Resolve generated evidence paths for semantic artifact validation."""
    images = row.get("images", {}) or {}
    artifacts = row.get("artifacts", {}) or {}
    if not isinstance(images, dict):
        images = {}
    if not isinstance(artifacts, dict):
        artifacts = {}

    def resolve(value: object) -> str | None:
        if not value:
            return None
        return str((case_out / str(value)).resolve())

    views = images.get("views", [])
    if not isinstance(views, list):
        views = []
    return {
        "views": [resolve(item) for item in views],
        "uv": resolve(images.get("uv")),
        "uv_heatmap": resolve(images.get("uv_heatmap")),
        "normal": resolve(images.get("normal")),
        "model": resolve(images.get("model")),
        "model_overlay": resolve(images.get("model_overlay")),
        "issue_locator": resolve(artifacts.get("issue_locator")),
        "issue_selection_script": resolve(artifacts.get("issue_selection_script")),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True, help="cases.json emitted by build_inspection_test_assets.py")
    parser.add_argument("--blender", required=True)
    parser.add_argument("--config", type=Path, default=Path("config/inspection_thresholds.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = ROOT
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    expected_map = {item["name"]: item for item in json.loads((root / "tests/inspection_test_cases.json").read_text(encoding="utf-8"))}
    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    for case in cases:
        # Blender may start with a different process working directory on
        # Windows. Absolute output paths prevent manifests from pointing at
        # one directory while render files are written to another.
        case_out = (args.out / case["name"]).resolve()
        case_out.mkdir(parents=True, exist_ok=True)
        command = [
            args.blender, "-b", "-P", str(root / "blender/inspect_asset.py"), "--",
            "--input", case["file"], "--out", str(case_out), "--views", "1", "--resolution", "96",
            "--config", str(args.config.resolve()),
        ]
        completed = subprocess.run(command, cwd=str(root), capture_output=True, text=True, timeout=360)
        log_path = case_out / "suite.log"
        log_path.write_text((completed.stdout or "") + "\n" + (completed.stderr or ""), encoding="utf-8", errors="replace")
        manifest_path = case_out / "manifest.jsonl"
        case_spec = expected_map.get(case["name"], {})
        expected_keys = case_spec.get("expected", []) if isinstance(case_spec, dict) else case_spec
        missing = list(expected_keys)
        assertion_failures = []
        artifact_failures = []
        metadata = {}
        if manifest_path.exists():
            row = json.loads(manifest_path.read_text(encoding="utf-8").splitlines()[0])
            metadata = row.get("metadata", {})
            artifact_failures = check_artifact_contract(row, case_out)
            artifact_failures.extend(validate_runtime_artifacts(row, resolve_runtime_artifact_paths(row, case_out)))
            missing = [key for key in missing if key not in metadata]
            if isinstance(case_spec, dict):
                for assertion in case_spec.get("assertions", []):
                    assertion_passed, detail = check_assertion(metadata, assertion)
                    if not assertion_passed:
                        assertion_failures.append(detail)
        passed = completed.returncode == 0 and manifest_path.exists() and not missing and not assertion_failures and not artifact_failures
        results.append({
            "name": case["name"],
            "passed": passed,
            "exit_code": completed.returncode,
            "missing_keys": missing,
            "assertion_failures": assertion_failures,
            "artifact_failures": artifact_failures,
            "log": str(log_path),
        })
    report = {"passed": all(item["passed"] for item in results), "cases": results}
    (args.out / "suite_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
