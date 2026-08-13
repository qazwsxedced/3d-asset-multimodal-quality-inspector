"""Train Qwen2.5-VL-3B with LoRA/QLoRA on the B4 diagnosis protocol."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data_protocol import build_condition, read_jsonl
from src.qwen_training import QwenVLDataCollator


class ManifestDataset:
    def __init__(self, rows: list[dict[str, Any]]): self.rows = rows
    def __len__(self) -> int: return len(self.rows)
    def __getitem__(self, index: int) -> dict[str, Any]: return {"sample": self.rows[index]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-samples", type=int, default=0)
    ap.add_argument("--max-length", type=int, default=4096)
    ap.add_argument("--max-pixels", type=int, default=401408)
    ap.add_argument("--min-pixels", type=int, default=200704)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--learning-rate", type=float, default=2e-4)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--gradient-accumulation-steps", type=int, default=8)
    ap.add_argument("--save-steps", type=int, default=100)
    ap.add_argument("--logging-steps", type=int, default=5)
    ap.add_argument("--load-in-4bit", action="store_true")
    ap.add_argument("--bf16", action="store_true")
    ap.add_argument("--trust-remote-code", action="store_true")
    args = ap.parse_args()
    all_rows = read_jsonl(args.manifest)
    train_rows = [r for r in all_rows if r.get("split") == "train"]
    eval_rows = [r for r in all_rows if r.get("split") == "val"]
    if args.max_samples: train_rows = train_rows[:args.max_samples]
    if not train_rows: raise SystemExit("No train samples found")
    preview = [build_condition(r, "B4", args.manifest) for r in train_rows[:2]]
    config = {"model": args.model, "condition": "B4", "train_samples": len(train_rows), "eval_samples": len(eval_rows), "max_length": args.max_length, "max_pixels": args.max_pixels, "min_pixels": args.min_pixels, "epochs": args.epochs, "learning_rate": args.learning_rate, "lora_r": args.lora_r, "lora_alpha": args.lora_alpha, "lora_dropout": args.lora_dropout, "gradient_accumulation_steps": args.gradient_accumulation_steps, "load_in_4bit": args.load_in_4bit, "bf16": args.bf16, "preview": preview}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "run_config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.dry_run:
        print(json.dumps(config, ensure_ascii=False, indent=2)); return
    try:
        import torch
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import AutoProcessor, BitsAndBytesConfig, Qwen2_5_VLForConditionalGeneration, Trainer, TrainingArguments
    except ImportError as exc:
        raise SystemExit("Full LoRA training requires torch, transformers, peft and bitsandbytes. Run scripts/check_gpu_env.py first.") from exc
    if not torch.cuda.is_available(): raise SystemExit("CUDA is required for the current QLoRA training entry point.")
    dtype = torch.bfloat16 if args.bf16 else torch.float16
    processor = AutoProcessor.from_pretrained(args.model, min_pixels=args.min_pixels, max_pixels=args.max_pixels, trust_remote_code=args.trust_remote_code)
    model_kwargs = {"torch_dtype": dtype, "device_map": "auto", "trust_remote_code": args.trust_remote_code}
    if args.load_in_4bit:
        model_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=dtype, bnb_4bit_use_double_quant=True)
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(args.model, **model_kwargs)
    if args.load_in_4bit: model = prepare_model_for_kbit_training(model)
    lora_config = LoraConfig(r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=args.lora_dropout, bias="none", task_type="CAUSAL_LM", target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()
    if hasattr(model, "enable_input_require_grads"): model.enable_input_require_grads()
    model.config.use_cache = False
    collator = QwenVLDataCollator(processor, "B4", str(args.manifest), max_length=args.max_length)
    training_args = TrainingArguments(output_dir=str(args.output), num_train_epochs=args.epochs, per_device_train_batch_size=1, per_device_eval_batch_size=1, gradient_accumulation_steps=args.gradient_accumulation_steps, learning_rate=args.learning_rate, lr_scheduler_type="cosine", warmup_steps=0, weight_decay=0.01, logging_steps=args.logging_steps, save_steps=args.save_steps, save_total_limit=2, eval_strategy="steps" if eval_rows else "no", eval_steps=args.save_steps, bf16=args.bf16, fp16=not args.bf16, gradient_checkpointing=True, remove_unused_columns=False, report_to="none")
    trainer = Trainer(model=model, args=training_args, train_dataset=ManifestDataset(train_rows), eval_dataset=ManifestDataset(eval_rows) if eval_rows else None, data_collator=collator)
    trainer.train(); trainer.save_model(str(args.output)); trainer.save_state()
    print(f"saved LoRA adapter and trainer state to {args.output}")


if __name__ == "__main__": main()
