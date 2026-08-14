# Phase 2 Results: Multi-Asset Blender Benchmark

## Scope

Phase 2 extends the original single-asset benchmark to a 600-sample Blender dataset with five asset families: `ico_sphere`, `cube`, `cylinder`, `cone`, and `torus`.

- Train / validation / test: 420 / 60 / 120
- Four camera views per asset
- Six injected defect types
- Scene-level split with no shared scene IDs across splits
- Dataset validation errors: 0

The test set contains 12 clean assets and 108 defective assets. All results below are from one Qwen2.5-VL-3B-Instruct run unless otherwise noted; they should be treated as a reproducible baseline, not a multi-seed confidence interval.

## Deterministic metadata baseline

The rule baseline fits robust geometry thresholds on the training split without reading diagnostic labels. On the 120-sample test set it achieved:

| Metric | Result |
|---|---:|
| Quality accuracy | 95.00% |
| Severity accuracy | 93.33% |
| Defect exact accuracy | 92.50% |
| Defect Macro-F1 | 95.71% |
| Repair-plan exact accuracy | 86.67% |

This baseline is an important control: low-level metadata is highly informative when explicit threshold logic is allowed, while a zero-shot VLM may not reliably convert the same statistics into the target schema.

## Zero-shot and LoRA results

| Condition | Input | Quality accuracy | Severity accuracy | Defect Macro-F1 | JSON valid | Schema valid | Mean latency |
|---|---|---:|---:|---:|---:|---:|---:|
| B0 | Single render | 69.17% | 48.33% | 0.00% | 100.00% | 0.00% | 4.62 s |
| B1 | Four rendered views | 44.17% | 51.67% | 0.00% | 100.00% | 0.00% | 4.89 s |
| B2 | Views + UV/normal diagnostics | 20.00% | 53.33% | 0.00% | 100.00% | 0.00% | 4.93 s |
| B3 | Views + structured metadata | 32.50% | 43.33% | 0.00% | 100.00% | 0.00% | 4.16 s |
| B4 | B3 + LoRA/SFT | 88.33% | 81.67% | 82.98% | 99.17% | 99.17% | 4.71 s |

B4 was trained for one epoch on 420 samples with QLoRA, rank 16, alpha 32, learning rate `2e-4`, gradient accumulation 8, and 4-bit loading. Training used 25,088–50,176 image pixels to fit an 8 GB GPU. The final training loss was `0.1141` and validation loss was `0.02128`.

## Generalization

| Group | N | B4 quality accuracy | B4 defect Macro-F1 |
|---|---:|---:|---:|
| Unseen question type | 30 | 76.67% | 65.69% |
| Unseen scene | 90 | 92.22% | 83.33% |

The gap between unseen question types and unseen scenes suggests that output schema and task formulation remain harder than interpolation across new Blender scenes.

## Error analysis

Per-defect B4 results:

| Defect | Precision | Recall | F1 |
|---|---:|---:|---:|
| degenerate faces | 1.000 | 1.000 | 1.000 |
| flipped normals | 1.000 | 0.958 | 0.979 |
| hole | 1.000 | 1.000 | 1.000 |
| non-manifold | 1.000 | 1.000 | 1.000 |
| stretched triangles | 0.000 | 0.000 | 0.000 |
| UV overlap | 1.000 | 1.000 | 1.000 |

The dominant remaining failure is stretched-triangle detection. Its low-level signal is represented by triangle aspect statistics, but the current image/prompt formulation does not teach the VLM a reliable mapping. This is the clearest next research target.

## Interpretation and limitations

The results support the claim that structured multimodal diagnosis can be improved substantially through task-specific LoRA adaptation. They do not support a claim of general-purpose VLM reasoning or cross-domain medical/autonomous-driving generalization. The benchmark is synthetic, one training seed has been evaluated, and the B4 adapter is not a production-quality 3D asset inspector.

## Next experiments

1. Run three B4 seeds and report mean ± standard deviation.
2. Add targeted stretched-triangle examples and aspect-ratio wording to the training prompt.
3. Compare metadata-only, image-only, and B4 predictions on the same fixed test IDs.
4. Add confidence calibration and a human review threshold for deployment-style use.
