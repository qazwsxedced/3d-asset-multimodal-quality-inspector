"""Dataset protocol for the 3D asset quality-diagnosis experiments.

The protocol intentionally separates observable evidence from gold labels.
Metadata may contain low-level geometry statistics, but it must not contain
diagnosis conclusions such as ``has_defect`` or ``defect_types``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

CONDITIONS = {"B0", "B1", "B2", "B3", "B4"}
QUESTION_TYPES = {"quality_summary", "defect_detection", "severity", "repair_planning"}
DEFECT_TYPES = {
    "non_manifold",
    "uv_overlap",
    "flipped_normals",
    "hole",
    "stretched_triangles",
    "degenerate_faces",
}
SEVERITIES = {"none", "low", "medium", "high"}

# These names are forbidden at any nesting level in model-facing metadata.
METADATA_BLACKLIST = {
    "answer", "gold", "target", "label", "has_defect", "is_defective",
    "defect", "defects", "defect_type", "defect_types", "quality",
    "severity", "repair_plan", "diagnosis", "ground_truth",
}


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
    return rows


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _find_blacklisted(value: Any, prefix: str = "metadata") -> list[str]:
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_lower = str(key).lower()
            if key_lower in METADATA_BLACKLIST:
                found.append(f"{prefix}.{key}")
            found.extend(_find_blacklisted(child, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            found.extend(_find_blacklisted(child, f"{prefix}[{idx}]"))
    return found


def validate_sample(sample: dict[str, Any]) -> list[str]:
    required = ["id", "scene_id", "split", "question_type", "question", "answer", "images", "metadata"]
    errors = [f"missing field: {key}" for key in required if key not in sample]
    question_type = sample.get("question_type")
    if question_type not in QUESTION_TYPES:
        errors.append(f"question_type must be one of {sorted(QUESTION_TYPES)}")
    answer = sample.get("answer")
    if not isinstance(answer, dict):
        errors.append("answer must be an object")
    else:
        if not isinstance(answer.get("defect_types"), list):
            errors.append("answer.defect_types must be a list")
        elif not set(answer["defect_types"]).issubset(DEFECT_TYPES):
            errors.append("answer.defect_types contains an unknown defect")
        if answer.get("severity") not in SEVERITIES:
            errors.append("answer.severity is invalid")
    metadata = sample.get("metadata")
    if not isinstance(metadata, dict):
        errors.append("metadata must be an object")
    else:
        for path in _find_blacklisted(metadata):
            errors.append(f"blacklisted diagnosis field: {path}")
    images = sample.get("images", {})
    if not isinstance(images, dict) or not isinstance(images.get("views"), list) or not images["views"]:
        errors.append("images.views must be a non-empty list")
    for key in ("uv", "normal"):
        if not isinstance(images, dict) or not images.get(key):
            errors.append(f"images.{key} is required")
    return errors


def _resolve(root: Path, value: str | None) -> str | None:
    if not value:
        return None
    return str((root / value).resolve())


def compact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Recursively remove fields that leak diagnosis labels."""
    if not isinstance(metadata, dict):
        raise TypeError("metadata must be a dict")
    cleaned = {}
    for key, value in metadata.items():
        if str(key).lower() in METADATA_BLACKLIST:
            continue
        if isinstance(value, dict):
            cleaned[key] = compact_metadata(value)
        elif isinstance(value, list):
            cleaned[key] = [compact_metadata(x) if isinstance(x, dict) else x for x in value]
        else:
            cleaned[key] = value
    leaked = _find_blacklisted(cleaned)
    if leaked:
        raise ValueError(f"metadata blacklist violation after compaction: {leaked}")
    return cleaned


def answer_schema(question_type: str) -> dict[str, Any]:
    """Return a compact schema description placed in every supervised prompt."""
    common = {"quality": "pass|fail", "defect_types": "list of defect names", "severity": "none|low|medium|high"}
    if question_type == "repair_planning":
        common["repair_plan"] = "list of short repair actions"
    return common


def build_condition(sample: dict[str, Any], condition: str, manifest_path: str | Path) -> dict[str, Any]:
    """Build a model-facing multimodal payload for one B0-B4 condition."""
    if condition not in CONDITIONS:
        raise ValueError(f"condition must be one of {sorted(CONDITIONS)}")
    root = Path(manifest_path).resolve().parent
    images = sample["images"]
    selected = images["views"][:1] if condition == "B0" else list(images["views"])
    image_paths = [_resolve(root, p) for p in selected]
    if condition == "B2":
        image_paths += [_resolve(root, images.get("uv")), _resolve(root, images.get("normal"))]
    image_paths = [p for p in image_paths if p]
    prompt = (
        f"{sample['question']}\n"
        "请严格只输出一个 JSON 对象，不要输出 Markdown、解释或额外文字。\n"
        f"JSON 字段约束：{json.dumps(answer_schema(sample['question_type']), ensure_ascii=False)}"
    )
    if condition == "B2":
        prompt += "\n图像顺序：前面的图像是不同相机视角；倒数第二张是 UV layout diagnostic map；最后一张是 normal diagnostic map。"
    if condition in {"B3", "B4"}:
        metadata = compact_metadata(sample["metadata"])
        prompt += "\n低层结构化几何统计如下（它们不是诊断结论）：\n" + json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    return {"id": sample["id"], "condition": condition, "image_paths": image_paths, "prompt": prompt, "gold": sample["answer"]}
