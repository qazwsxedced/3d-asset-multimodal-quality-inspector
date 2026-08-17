# External `.blend` Validation v1

## Dataset and protocol

This validation set contains 28 ordinary `.blend` files generated as
external-input fixtures rather than as a pre-rendered benchmark:

- 4 clean assets;
- 4 assets for each of the six supported defect types;
- five asset families, with family assignments recorded in `labels.jsonl`;
- labels stored separately from the source files;
- Blender background preprocessing performed independently for every asset;
- four views, a UV diagnostic map, a normal diagnostic map, and geometry
  metadata generated at runtime.

The source assets and runtime renders remain local artifacts. The repository
publishes the generator and batch-processing code, not the generated files.
These fixtures are controlled Blender-generated validation data, not
customer-owned or manually annotated production data.

## Preprocessing reliability

| Metric | Result |
|---|---:|
| Assets submitted | 28 |
| Successful jobs | 28 |
| Failed jobs | 0 |
| Skipped jobs | 0 |
| Total attempts | 28 |
| Mean preprocessing time | 3.50 s |
| P50 preprocessing time | 3.41 s |
| P95 preprocessing time | 3.83 s |

Every job writes an independent record to `preprocess_log.jsonl`. The batch
runner supports configurable retries and timeout limits; this run completed
without needing a retry.

## Same-input comparison

All three modes consumed the same 28 preprocessed assets and the same gold
labels.

| Mode | Quality accuracy | Severity accuracy | Defect Macro-F1 | Schema valid | Review rate |
|---|---:|---:|---:|---:|---:|
| Rule-only | 92.86% | 92.86% | 94.44% | 100.00% | 0.00% |
| VLM-only | 89.29% | 89.29% | 90.00% | 100.00% | 0.00% |
| Hybrid | 92.86% | 92.86% | 94.44% | 100.00% | 10.71% |

The Hybrid policy selects the VLM only when it is schema-valid and agrees with
the deterministic rule on quality, severity, and defect set. Otherwise it
selects the rule result and routes the sample to human review. On this run,
25/28 samples agreed and 3/28 were routed for review.

## Interpretation

The external fixture test supports the engineering claim that the system can
accept ordinary `.blend` inputs, generate inspection evidence, and produce
auditable rule/VLM comparisons. It does not replace evaluation on a
customer-owned asset distribution. The labels are generated from controlled
defect injection, so this is an external-input validation, not an independent
human annotation study.

## Reproduction

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" `
  -b -P blender/generate_external_validation_set.py -- `
  --out data/external_blend_validation_v1 --n-per-category 4 --seed 31

python scripts/run_external_batch.py `
  --assets-dir data/external_blend_validation_v1 `
  --out results/external_batch_v1 `
  --blender "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" `
  --retries 2

python scripts/run_rule_baseline.py `
  --manifest results/external_batch_v1/manifest.jsonl `
  --fit-manifest results/external_batch_v1/manifest.jsonl `
  --fit-split all `
  --out results/external_batch_v1/rule_predictions.jsonl

python scripts/run_vlm_inference.py `
  --manifest results/external_batch_v1/manifest.jsonl `
  --condition B4 --model Qwen/Qwen2.5-VL-3B-Instruct `
  --adapter adapters/qwen_b4_blender_v5_fast `
  --out results/external_batch_v1/vlm_predictions.jsonl `
  --split test --min-pixels 50176 --max-pixels 100352

python scripts/compare_modes.py `
  --gold results/external_batch_v1/manifest.jsonl `
  --rule results/external_batch_v1/rule_predictions.jsonl `
  --vlm results/external_batch_v1/vlm_predictions.jsonl `
  --out-dir results/external_batch_v1/comparison
```
