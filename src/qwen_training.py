"""Qwen2.5-VL supervised fine-tuning utilities.

The collator uses batch size 1 by default because each example can have a
different number of images. Gradient accumulation provides the effective
batch size without forcing image padding across unrelated assets.
"""

from __future__ import annotations

import json
from typing import Any

from src.data_protocol import build_condition


def answer_text(answer: dict[str, Any]) -> str:
    """Canonical compact JSON target used for SFT and evaluation."""
    return json.dumps(answer, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def qwen_messages(payload: dict[str, Any], target: str | None = None) -> list[dict[str, Any]]:
    content = [{"type": "image", "image": path} for path in payload["image_paths"]]
    content.append({"type": "text", "text": payload["prompt"]})
    messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
    if target is not None:
        messages.append({"role": "assistant", "content": target})
    return messages


def condition_messages(sample: dict[str, Any], condition: str, manifest_path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = build_condition(sample, condition, manifest_path)
    return qwen_messages(payload), qwen_messages(payload, answer_text(sample["answer"]))


class QwenVLDataCollator:
    """Processor-backed collator for Qwen2.5-VL SFT.

    This implementation intentionally supports ``batch_size=1``. It still
    returns the standard Trainer keys and masks user/prompt tokens with -100,
    so only the assistant JSON contributes to language-model loss.
    """

    def __init__(self, processor: Any, condition: str, manifest_path: str, max_length: int = 2048):
        self.processor = processor
        self.condition = condition
        self.manifest_path = manifest_path
        self.max_length = max_length
        try:
            from qwen_vl_utils import process_vision_info
        except ImportError as exc:  # pragma: no cover - exercised on GPU env
            raise RuntimeError("Install qwen-vl-utils before constructing QwenVLDataCollator") from exc
        self.process_vision_info = process_vision_info

    def _encode(self, messages: list[dict[str, Any]], add_generation_prompt: bool) -> dict[str, Any]:
        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=add_generation_prompt)
        image_inputs, video_inputs = self.process_vision_info(messages)
        encoded = self.processor(text=[text], images=image_inputs, videos=video_inputs, padding=True, truncation=True, max_length=self.max_length, return_tensors="pt")
        return encoded

    def __call__(self, features: list[dict[str, Any]]) -> dict[str, Any]:
        if len(features) != 1:
            raise ValueError("QwenVLDataCollator currently requires per-device batch size 1; use gradient accumulation.")
        user_messages, full_messages = condition_messages(features[0]["sample"], self.condition, self.manifest_path)
        encoded = self._encode(full_messages, add_generation_prompt=False)
        prompt_encoded = self._encode(user_messages, add_generation_prompt=True)
        labels = encoded["input_ids"].clone()
        prompt_len = prompt_encoded["input_ids"].shape[1]
        labels[:, :prompt_len] = -100
        if "attention_mask" in encoded:
            labels[encoded["attention_mask"] == 0] = -100
        encoded["labels"] = labels
        return encoded
