# Final Results on the Real Blender Dataset

## Experiment scope

- Dataset: `data/blender_research_v3/manifest.jsonl`
- Blender: 5.2.0 LTS
- Samples: 120; train/val/test = 84/12/24
- Test set: 12 clean + 12 defective samples with a scene-level split
- Model: Qwen2.5-VL-3B-Instruct
- B4: 4-bit QLoRA, LoRA rank 16, 1 epoch, learning rate 2e-4
- Final adapter: `adapters/qwen_b4_blender_v3`; a second run did not improve the main metrics and is not used as the final adapter

## B0–B4 results

| Condition | Input | Quality accuracy | Defect Macro-F1 | Defect exact | JSON valid | Schema valid | Severity accuracy | Mean latency |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| B0 | One regular render | 50.0% | 0.0% | 0.0% | 100.0% | 0.0% | 20.8% | 8567 ms |
| B1 | Multiple views | 50.0% | 0.0% | 0.0% | 100.0% | 0.0% | 20.8% | 7449 ms |
| B2 | Multiple views + UV/normal maps | 50.0% | 0.0% | 0.0% | 100.0% | 0.0% | 20.8% | 8293 ms |
| B3 | Multiple views + structured metadata | 62.5% | 0.0% | 0.0% | 100.0% | 0.0% | 25.0% | 7078 ms |
| B4 | B3 protocol + LoRA/SFT | 50.0% | 8.3% | 41.7% | 100.0% | 95.8% | 45.8% | 2129 ms |

Pixel limits and quantization settings differed across conditions, so latency is reported only as an engineering reference and should not be treated as a strict speed comparison.

## Conclusions

1. On real Blender renders, zero-shot B0–B2 did not identify the six fine-grained defect types.
2. B3 increased quality accuracy to 62.5%, while defect Macro-F1 remained 0. The model could partially judge pass/fail but did not reliably map statistics to defect labels.
3. B4 achieved a defect Macro-F1 of 8.3% and a schema validity rate of 95.8%, but fine-grained defect transfer in the real image domain remained weak.
4. A second training run with the same configuration did not change the main metrics, so repeated training is not supported by the current evidence.
5. The 54.2% Macro-F1 obtained on proxy Pillow data must not be presented as the real Blender result.

## Final error analysis

Report: `results/blender_v3_qwen_b4_final_error_analysis.md`

- Clean false positives: 3/12
- `flipped_normals` F1: 0.500
- `degenerate_faces`, `hole`, `non_manifold`, and `stretched_triangles` F1: 0
- `uv_overlap` recall: 0, with 4 false positives
- Unseen-scene defect Macro-F1: 0
- Unseen-question-type defect Macro-F1: 0.167

The dominant failure mode was defect omission rather than the single-defect `hole` bias observed in the proxy-data experiment.

## Resume-safe project description

> **Multimodal VLM Reasoning with Multi-View Images and Structured Metadata**
> PyTorch, Qwen2.5-VL-3B, QLoRA/PEFT, Blender

- Built a Blender 5.2 data-generation pipeline for multi-view renders, UV layouts, normal diagnostic maps, and low-level geometry statistics, producing 120 scene-level-split 3D asset quality-diagnosis samples.
- Designed and implemented a B0–B4 multimodal ablation protocol with JSON/schema evaluation, multi-label Macro-F1, grouped generalization metrics, and per-sample error analysis.
- Fine-tuned Qwen2.5-VL-3B with 4-bit QLoRA; on a held-out real-Blender test set, B4 achieved 100% JSON validity, 95.8% schema validity, and 8.3% defect Macro-F1.
- Found that structured metadata improved pass/fail judgment, while fine-grained defect recognition remained limited by domain shift and defect omissions in the real-rendering domain.

Do not write that real Blender defect Macro-F1 reached 54.2%; 54.2% belongs only to the proxy Pillow-data experiment.

## Next steps

- Extend beyond a single icosphere to varied object topologies and material distributions.
- Vary the strength and spatial location of each defect instead of using fixed injection patterns.
- Expand the training set to 1,000–2,000 samples before reevaluating LoRA.
- Combine the VLM with a deterministic geometry checker through tool use or retrieval.
