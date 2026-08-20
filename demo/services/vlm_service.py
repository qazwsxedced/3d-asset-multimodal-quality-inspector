"""VLM loading, inference, and prediction-schema validation service."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from src.data_protocol import build_condition
from scripts.run_vlm_inference import load_stack, parse_json_object


def normalize_prediction(prediction: dict[str, Any]) -> dict[str, Any]:
    """Repair common schema-key variants without changing semantic values."""
    if not isinstance(prediction, dict):
        return {"_raw": prediction}
    normalized = dict(prediction)
    for source, target in (("repair_plan[]", "repair_plan"), ("defect_types[]", "defect_types")):
        if target not in normalized and source in normalized:
            normalized[target] = normalized.pop(source)
    return normalized


def validate_prediction(prediction: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if prediction.get("quality") not in {"pass", "fail"}:
        errors.append("quality must be pass or fail")
    if prediction.get("severity") not in {"none", "low", "medium", "high"}:
        errors.append("severity is invalid")
    defects = prediction.get("defect_types")
    allowed = {"non_manifold", "uv_overlap", "flipped_normals", "hole", "stretched_triangles", "degenerate_faces"}
    if not isinstance(defects, list) or not all(item in allowed for item in defects):
        errors.append("defect_types must be a list of known defect names")
    if "repair_plan" in prediction and not isinstance(prediction["repair_plan"], list):
        errors.append("repair_plan must be a list")
    return not errors, errors


class VLMService:
    """Cache model stacks and keep multimodal inference outside the UI module."""

    def __init__(self) -> None:
        self._model_cache: dict[str, Any] = {}

    def infer(
        self,
        row: dict[str, Any],
        manifest: Path,
        condition: str,
        model_id: str,
        adapter: Path | None,
        min_pixels: int,
        max_pixels: int,
        max_new_tokens: int,
        offload_dir: Path,
        reference_image: str | None = None,
        generation_prompt: str = "",
    ) -> dict[str, Any]:
        cache_key = "|".join([model_id, str(adapter or ""), str(min_pixels), str(max_pixels), str(offload_dir)])
        if cache_key not in self._model_cache:
            self._model_cache[cache_key] = load_stack(
                model_id,
                adapter,
                min_pixels,
                max_pixels,
                load_in_4bit=True,
                offload_dir=offload_dir,
            )
        model, processor = self._model_cache[cache_key]

        try:
            import torch
            from qwen_vl_utils import process_vision_info
        except ImportError as exc:
            raise RuntimeError("VLM mode requires torch and qwen-vl-utils.") from exc

        payload = build_condition(row, condition, manifest)
        content = [{"type": "image", "image": path} for path in payload["image_paths"]]
        if reference_image and Path(reference_image).exists():
            content.append({"type": "image", "image": reference_image})
        soft_context = []
        if reference_image:
            soft_context.append("A reference image was appended after the rendered evidence. Compare the asset to it and describe identity mismatches.")
        if generation_prompt.strip():
            soft_context.append(f"Generation prompt to verify: {generation_prompt.strip()}")
        content.append({"type": "text", "text": payload["prompt"] + ("\n\nSoft evaluation context:\n" + "\n".join(soft_context) if soft_context else "")})
        messages = [{"role": "user", "content": content}]
        prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = processor(text=[prompt], images=image_inputs, videos=video_inputs, padding=True, return_tensors="pt").to(model.device)
        started = time.perf_counter()
        with torch.inference_mode():
            generated_ids = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        trimmed = [out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)]
        raw = processor.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
        prediction = normalize_prediction(parse_json_object(raw))
        valid, errors = validate_prediction(prediction)
        return {
            "prediction": prediction,
            "raw_output": raw,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "model": model_id,
            "adapter": str(adapter) if adapter else None,
            "device": str(getattr(model, "device", "unknown")),
            "schema_valid": valid,
            "schema_errors": errors,
        }
