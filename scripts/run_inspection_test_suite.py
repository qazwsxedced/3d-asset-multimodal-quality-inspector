"""Run the generated FBX/OBJ/Blend fixture set through inspect_asset.py."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True, help="cases.json emitted by build_inspection_test_assets.py")
    parser.add_argument("--blender", required=True)
    parser.add_argument("--config", type=Path, default=Path("config/inspection_thresholds.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    expected_map = {item["name"]: item for item in json.loads((root / "tests/inspection_test_cases.json").read_text(encoding="utf-8"))}
    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    for case in cases:
        case_out = args.out / case["name"]
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
        metadata = {}
        if manifest_path.exists():
            row = json.loads(manifest_path.read_text(encoding="utf-8").splitlines()[0])
            metadata = row.get("metadata", {})
            missing = [key for key in missing if key not in metadata]
            if isinstance(case_spec, dict):
                for assertion in case_spec.get("assertions", []):
                    assertion_passed, detail = check_assertion(metadata, assertion)
                    if not assertion_passed:
                        assertion_failures.append(detail)
        passed = completed.returncode == 0 and manifest_path.exists() and not missing and not assertion_failures
        results.append({
            "name": case["name"],
            "passed": passed,
            "exit_code": completed.returncode,
            "missing_keys": missing,
            "assertion_failures": assertion_failures,
            "log": str(log_path),
        })
    report = {"passed": all(item["passed"] for item in results), "cases": results}
    (args.out / "suite_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
