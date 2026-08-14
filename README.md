# Multimodal VLM Reasoning with Multi-View Images and Structured Metadata

This repository contains a reproducible research project for multimodal algorithm applications. It studies the following question:

> How do multi-view images, UV/normal diagnostic maps, and low-level structured geometry statistics affect a VLM's ability to diagnose 3D asset quality, separately and in combination?

The project decomposes the task into five controlled conditions:

- **B0:** One regular render
- **B1:** Multiple views
- **B2:** Multiple views + UV/normal diagnostic maps
- **B3:** Multiple views + low-level structured geometry metadata
- **B4:** B3 + LoRA/SFT

## Public repository scope

This repository publishes source code, the data protocol, experiment configurations, aggregate metrics, and error analysis. Batch-rendered images, model weights, LoRA adapters, inference offload caches, and per-sample prediction files are local experiment artifacts and are excluded from Git.

The final real-Blender results are documented in:

- `reports/final_results_blender_v3.md`
- `results/blender_v3_qwen_b0_b4_summary.json`
- `results/blender_v3_qwen_b4_final_error_analysis.md`

Mock/Pillow data is used only to validate the engineering pipeline. It must not be used as a substitute for the real Blender test results.

## Quick start

The data generation and evaluation pipeline uses Python's standard library. Installing Pillow additionally enables PNG preview generation.

```powershell
python scripts/generate_synthetic_dataset.py --out data/synthetic --n 120 --seed 7
python scripts/validate_dataset.py --manifest data/synthetic/manifest.jsonl
python scripts/run_mock_baseline.py --manifest data/synthetic/manifest.jsonl --condition B0 --out results/mock_b0.jsonl
python scripts/evaluate_predictions.py --gold data/synthetic/manifest.jsonl --pred results/mock_b0.jsonl --out results/mock_b0_metrics.json
```

Run the deterministic metadata-only baseline:

```powershell
python scripts/run_rule_baseline.py `
  --manifest data/blender_research_v3/manifest.jsonl `
  --fit-manifest data/blender_research_v3/manifest.jsonl `
  --fit-split train `
  --out results/rule_test.jsonl `
  --split test
```

Inspect the assembled inputs and prompt for an experimental condition:

```powershell
python scripts/inspect_condition.py --sample data/synthetic/manifest.jsonl --condition B3
```

Validate dataset integrity:

```powershell
python scripts/validate_dataset.py --manifest data/synthetic/manifest.jsonl
```

Real-model inference requires a GPU, `torch`, `transformers`, `peft`, `qwen-vl-utils`, and Qwen2.5-VL-3B-Instruct weights:

```powershell
python scripts/run_vlm_inference.py `
  --manifest data/synthetic/manifest.jsonl `
  --condition B3 `
  --model Qwen/Qwen2.5-VL-3B-Instruct `
  --out results/qwen_b3.jsonl
```

On GPUs with limited VRAM, use `--load-in-4bit` and split a large test set with
`--start` and `--limit`; concatenate the JSONL parts before evaluation.

Prepare B4 SFT data and inspect the GPU environment:

```powershell
python scripts/prepare_sft_data.py --manifest data/synthetic/manifest.jsonl --condition B4 --split train --out data/sft_b4_train.json
python scripts/check_gpu_env.py
```

LoRA/QLoRA training uses batch size 1 with gradient accumulation:

```powershell
python scripts/train_lora.py --manifest data/synthetic/manifest.jsonl --model Qwen/Qwen2.5-VL-3B-Instruct --output adapters/qwen_b4 --load-in-4bit --bf16
```

## Data format

Each JSONL row represents a single 3D asset quality-diagnosis sample:

```json
{
  "id": "scene_000001",
  "split": "train",
  "question_type": "defect_detection",
  "question": "Identify topology, UV, and normal issues in this 3D asset.",
  "answer": {"quality": "fail", "defect_types": ["uv_overlap"], "severity": "medium"},
  "images": {"views": ["images/.../view_0.png"], "uv": "...", "normal": "..."},
  "metadata": {"non_manifold_edge_count": 0, "uv_overlap_ratio": 0.18, "triangle_area_stats": {...}}
}
```

All paths are relative to the manifest directory. `metadata` is the structured input for B3/B4 and contains only low-level statistics. It must not contain diagnostic conclusion fields such as `has_defect`, `defect_types`, `severity`, or `quality`.

## Research design

### Dataset split

- Train/validation/test splits are grouped by `scene_id` to prevent view-level leakage.
- The test protocol includes unseen scenes, object combinations, camera views, and question types.
- The original MVP target was 1,000–2,000 high-quality samples, followed by expansion to 3,000–5,000 samples after pipeline stabilization.

### Metrics

- Quality accuracy: `answer.quality`
- Severity accuracy: `answer.severity`
- Multi-label defect Macro-F1 and exact match: `answer.defect_types`
- JSON validity rate: whether the prediction can be parsed as an object
- Field-level accuracy for `quality`, `severity`, `defect_types`, and `repair_plan`
- Inference latency: mean, P50, and P95 wall-clock latency per sample
- Generalization: metrics grouped by `generalization`, rather than reporting only one aggregate score

### Controls

- Keep the model, prompt template, decoding parameters, and maximum token count fixed.
- Keep the same `sample_id` across B0–B4.
- Record peak memory, model version, dataset version, Git commit, and random seed.
- Train B4 only with the B3 input protocol so modality effects are not confused with fine-tuning effects.

## Repository layout

```text
blender/                 Blender data-generation scripts
configs/                 B0–B4 and training hyperparameters
scripts/                 Data, inference, evaluation, and error-analysis entry points
src/                     Data protocol and experiment utilities
data/                    Dataset manifests and local generated data
results/                 Aggregate metrics and selected reports
reports/                 Experiment plan and final results
```

## Scope and limitations

Synthetic 3D data supports controlled 3D-scene experiments, but it does not support claims about cross-domain generalization to medicine or autonomous driving. External benchmarks should be reported as separate transfer experiments with their own data distribution, prompts, and evaluation criteria.

`run_mock_baseline.py` and `run_ablation_mock.py` validate the data-to-prediction-to-evaluation loop only. They do not simulate image understanding, so their B0–B3 numbers must not be used in a resume or as research conclusions.
