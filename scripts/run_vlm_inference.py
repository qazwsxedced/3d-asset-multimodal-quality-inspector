"""Qwen2.5-VL inference adapter for B0-B4 and optional LoRA adapter."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data_protocol import build_condition, read_jsonl, write_jsonl


def parse_json_object(text: str) -> dict:
    try:
        value = json.loads(text.strip())
        return value if isinstance(value, dict) else {"_raw": value}
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(text[start:end + 1])
                return value if isinstance(value, dict) else {"_raw": value}
            except json.JSONDecodeError:
                pass
        return {"_raw": text}


def resolve_device(torch) -> str:
    """Choose the best available device without assuming CUDA is installed."""
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(getattr(torch.backends, "mps", None), "is_available", lambda: False)
    if mps():
        return "mps"
    return "cpu"


def load_stack(model_id: str, adapter: Path | None, min_pixels: int, max_pixels: int, load_in_4bit: bool, offload_dir: Path):
    try:
        import torch
        from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
    except ImportError as exc:
        raise SystemExit("Missing torch/transformers. Run scripts/install_gpu.ps1 first.") from exc
    device = resolve_device(torch)
    use_4bit = bool(load_in_4bit and device == "cuda")
    if load_in_4bit and not use_4bit:
        print(f"4-bit CUDA quantization is unavailable on {device}; loading without bitsandbytes quantization.", file=sys.stderr)
    model_kwargs = {"torch_dtype": torch.float16 if device in {"cuda", "mps"} else torch.float32}
    if device == "cuda":
        offload_dir.mkdir(parents=True, exist_ok=True)
        model_kwargs.update({"device_map": "auto", "offload_folder": str(offload_dir), "offload_buffers": True})
    if use_4bit:
        from transformers import BitsAndBytesConfig
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(model_id, **model_kwargs)
    if device != "cuda":
        model.to(device)
    processor = AutoProcessor.from_pretrained(model_id, min_pixels=min_pixels, max_pixels=max_pixels)
    if adapter:
        try:
            from peft import PeftModel
            adapter_kwargs = {"offload_folder": str(offload_dir), "offload_buffers": True} if device == "cuda" else {}
            model = PeftModel.from_pretrained(model, str(adapter), **adapter_kwargs)
        except ImportError as exc:
            raise SystemExit("Loading --adapter requires peft.") from exc
    return model, processor


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--condition", choices=["B0", "B1", "B2", "B3", "B4"], required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-new-tokens", type=int, default=192)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--split", choices=["train", "val", "test", "all"], default="test")
    ap.add_argument("--min-pixels", type=int, default=200704)
    ap.add_argument("--max-pixels", type=int, default=401408)
    ap.add_argument("--load-in-4bit", action="store_true")
    ap.add_argument("--offload-dir", type=Path, default=Path("offload/inference"))
    args = ap.parse_args()
    model, processor = load_stack(args.model, args.adapter, args.min_pixels, args.max_pixels, args.load_in_4bit or args.adapter is not None, args.offload_dir)
    try:
        from qwen_vl_utils import process_vision_info
    except ImportError as exc:
        raise SystemExit("Missing qwen-vl-utils.") from exc
    rows = read_jsonl(args.manifest)
    if args.split != "all": rows = [row for row in rows if row.get("split") == args.split]
    if args.start < 0:
        raise SystemExit("--start must be non-negative")
    rows = rows[args.start:]
    if args.limit: rows = rows[:args.limit]
    outputs = []
    for row in rows:
        payload = build_condition(row, args.condition, args.manifest)
        content = [{"type": "image", "image": path} for path in payload["image_paths"]] + [{"type": "text", "text": payload["prompt"]}]
        messages = [{"role": "user", "content": content}]
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = processor(text=[text], images=image_inputs, videos=video_inputs, padding=True, return_tensors="pt").to(model.device)
        started = time.perf_counter()
        generated_ids = model.generate(**inputs, max_new_tokens=args.max_new_tokens, do_sample=False)
        trimmed = [out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)]
        response = processor.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
        outputs.append({"id": row["id"], "condition": args.condition, "prediction": parse_json_object(response), "raw_output": response, "latency_ms": round((time.perf_counter() - started) * 1000, 2), "model": args.model, "adapter": str(args.adapter) if args.adapter else None})
    write_jsonl(args.out, outputs)
    print(f"wrote {len(outputs)} predictions to {args.out}")


if __name__ == "__main__": main()
