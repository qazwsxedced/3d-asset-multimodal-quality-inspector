# Multimodal VLM Reasoning with Multi-View Images and Structured Metadata for 3D Asset Quality Diagnosis

## Abstract

Vision-language models (VLMs) can process images and text jointly, but their ability to diagnose 3D asset quality in a structured format has not been systematically characterized. This paper presents a controlled Blender-based benchmark for studying how multi-view renders, UV/normal diagnostic maps, and low-level structured geometry metadata affect VLM-based 3D asset diagnosis separately and in combination. We define five input conditions: B0, a single render; B1, multiple renders; B2, multiple renders plus UV/normal maps; B3, multiple renders plus structured geometry metadata; and B4, B3 with LoRA/QLoRA supervised adaptation.

The second-stage benchmark contains 600 independent Blender scenes, five primitive asset families, four camera views, and six controllable defect types. The train, validation, and test splits contain 420, 60, and 120 samples, respectively. We also implement a deterministic metadata-only rule baseline that does not read diagnosis labels, providing a control for the discriminative information contained in low-level geometry statistics. Experiments use Qwen2.5-VL-3B-Instruct and 4-bit LoRA training on an 8 GB GPU.

On the 120-sample test set, zero-shot B0, B1, B2, and B3 all obtain 0 defect Macro-F1. B4 reaches a three-seed mean defect Macro-F1 of 82.55% +/- 0.72%, quality accuracy of 85.83% +/- 4.33%, and severity accuracy of 75.56% +/- 6.25%. Mean defect Macro-F1 is 84.19% +/- 1.48% on unseen scenes and 52.19% +/- 12.55% on unseen question types. Error analysis shows reliable recognition of degenerate faces, holes, non-manifold structures, flipped normals, and UV overlap, while stretched-triangle recall remains 0. These results indicate that task-specific multimodal LoRA adaptation can substantially improve structured 3D quality diagnosis, but they do not support claims of general-purpose VLM reasoning or cross-domain generalization to medical or autonomous-driving tasks.

**Keywords:** vision-language model; multi-view images; structured metadata; 3D asset quality diagnosis; LoRA; QLoRA; Blender

## 1. Introduction

3D asset quality inspection often requires simultaneous reasoning about appearance, topology, UV layout, and normal orientation. Conventional geometry tools can deterministically detect non-manifold edges, boundary edges, degenerate faces, and UV overlap, but they do not naturally answer language queries or combine heterogeneous evidence into a single diagnostic schema. Recent VLMs provide a possible interface for multimodal 3D asset inspection, but their ability to perform this task must be evaluated under controlled conditions.

3D diagnosis differs from ordinary image question answering in several ways. Some defects are visible only from particular viewpoints; others are not visually apparent in a regular render at all. Structured geometry statistics provide precise low-level signals, but they also introduce a risk of answer leakage if metadata directly exposes the target label. A meaningful experiment therefore requires a fixed input protocol, scene-level splitting, controlled defect injection, and explicit output validation.

This work studies the following research question:

> How much do multi-view images, UV/normal diagnostic maps, and low-level structured geometry metadata contribute to a VLM's 3D asset quality diagnosis and structured output ability, separately and jointly?

Our contributions are:

1. A reproducible Blender data-generation pipeline for multi-view 3D asset diagnosis with six controllable defect injections.
2. A B0-B4 ablation protocol that isolates modality changes from LoRA adaptation on fixed test IDs.
3. An evaluation suite covering JSON validity, schema validity, field accuracy, multi-label defect Macro-F1, latency, and generalization groups.
4. A deterministic geometry-rule baseline and three-seed B4 study that separate signal availability, zero-shot VLM behavior, and training stability.

## 2. Task Definition and Method

### 2.1 Diagnosis task

For each independent 3D asset, the model must return one JSON object:

```json
{
  "quality": "pass|fail",
  "defect_types": ["defect name"],
  "severity": "none|low|medium|high",
  "repair_plan": ["short repair action"]
}
```

The defect vocabulary contains `degenerate_faces`, `flipped_normals`, `hole`, `non_manifold`, `stretched_triangles`, and `uv_overlap`. Metadata contains only low-level signals such as face count, boundary-edge count, non-manifold-edge count, degenerate-face count, flipped-normal count, triangle-area statistics, triangle-aspect statistics, and UV-overlap ratios. Direct diagnosis fields such as `has_defect` and `is_manifold` are excluded.

### 2.2 B0-B4 input protocol

| Condition | Input |
|---|---|
| B0 | One regular render |
| B1 | Four regular renders from different views |
| B2 | Four regular renders plus UV/normal diagnostic maps |
| B3 | Four regular renders plus low-level structured geometry metadata |
| B4 | B3 input plus LoRA/QLoRA supervised adaptation |

B4 is trained only under the B3 protocol so that training gains are not confounded with a change in the input specification. All B0-B4 results use fixed test sample IDs.

## 3. Dataset Construction

### 3.1 Scene generation

The second-stage dataset is generated automatically in Blender using five asset families: `ico_sphere`, `cube`, `cylinder`, `cone`, and `torus`. Each sample uses an independent scene. Asset family, scale, rotation, and material color are kept consistent across its four camera views. Camera azimuths are 0, 90, 180, and 270 degrees with a 20-degree elevation.

The dataset contains 600 samples: 420 for training, 60 for validation, and 120 for testing. Splits are grouped by scene ID, preventing views from the same scene from crossing split boundaries. The test set contains 12 clean assets and 108 defective assets.

### 3.2 Defect injection

The generator injects six defect classes into Blender meshes and records both geometry statistics and diagnosis labels:

- **Non-manifold structure:** create abnormal shared-edge topology.
- **UV overlap:** copy valid UV triangle coordinates onto another triangle.
- **Flipped normals:** reverse the vertex order of selected faces.
- **Stretched triangles:** alter local geometry proportions to increase triangle aspect ratio.
- **Degenerate faces:** create zero-area or near-zero-area faces.
- **Holes:** remove local faces and create boundary edges.

The resulting JSONL manifest is checked for field completeness, image paths, scene-level split leakage, and forbidden diagnosis fields. The formal 600-sample dataset has zero validation errors.

## 4. Experimental Setup

### 4.1 Model and training

The base model is Qwen2.5-VL-3B-Instruct. B0-B3 use deterministic zero-shot decoding. B4 uses one epoch of LoRA/QLoRA supervised adaptation with rank 16, alpha 32, dropout 0.05, learning rate `2e-4`, gradient accumulation of 8, 4-bit NF4 quantization, and 25,088-50,176 image pixels. Training is performed on an RTX 4060 Laptop GPU with 8 GB VRAM.

To measure randomness, B4 is trained with seeds 42, 123, and 3407. The main B0-B4 table reports seed 42, while the stability section reports the mean and sample standard deviation across all three seeds.

### 4.2 Metrics

- **Quality accuracy:** accuracy of the `quality` field.
- **Severity accuracy:** accuracy of the `severity` field.
- **Defect exact accuracy:** proportion of samples where the predicted defect set exactly matches the gold set.
- **Defect Macro-F1:** macro-average F1 over multi-label defect classes.
- **JSON valid rate:** proportion of outputs parseable as JSON objects.
- **Schema valid rate:** proportion of outputs satisfying field, enum, and list-type constraints.
- **Latency:** per-sample generation latency, summarized by mean, P50, and P95.

## 5. Results

### 5.1 B0-B4 comparison

| Condition | Quality accuracy | Severity accuracy | Defect Macro-F1 | JSON valid | Schema valid | Mean latency |
|---|---:|---:|---:|---:|---:|---:|
| B0 | 69.17% | 48.33% | 0.00% | 100.00% | 0.00% | 4.62 s |
| B1 | 44.17% | 51.67% | 0.00% | 100.00% | 0.00% | 4.89 s |
| B2 | 20.00% | 53.33% | 0.00% | 100.00% | 0.00% | 4.93 s |
| B3 | 32.50% | 43.33% | 0.00% | 100.00% | 0.00% | 4.16 s |
| B4 | 88.33% | 81.67% | 82.98% | 99.17% | 99.17% | 4.71 s |

Under zero-shot evaluation, adding more modalities does not automatically improve performance. B1 reduces quality accuracy relative to B0, and B2 reduces it further, suggesting that the base model struggles to organize multiple images or interpret the current UV/normal visual encoding. B3 also fails to convert structured metadata into reliable defect predictions. In contrast, B4 substantially improves all major diagnostic metrics while preserving the B3 input protocol.

### 5.2 Deterministic metadata baseline

The rule baseline uses only robust low-level metadata thresholds fitted on the training split and does not read diagnosis labels. On the test set it achieves 95.00% quality accuracy, 93.33% severity accuracy, 92.50% defect exact accuracy, 95.71% defect Macro-F1, and 86.67% repair-plan exact accuracy.

This control shows that the geometry statistics contain sufficient information for deterministic defect separation. The zero-shot VLM failure therefore reflects the difficulty of mapping structured numeric signals to the target diagnostic schema, rather than a complete absence of useful signal in the dataset.

### 5.3 Three-seed stability

| Metric | Mean +/- standard deviation |
|---|---:|
| Quality accuracy | 85.83% +/- 4.33% |
| Severity accuracy | 75.56% +/- 6.25% |
| Defect Macro-F1 | 82.55% +/- 0.72% |
| JSON/schema valid rate | 94.72% +/- 7.70% |

On unseen scenes, quality accuracy is 92.59% +/- 0.64% and defect Macro-F1 is 84.19% +/- 1.48%. On unseen question types, quality accuracy is 65.56% +/- 19.25% and defect Macro-F1 is 52.19% +/- 12.55%. The model is therefore relatively stable on new scenes but much more sensitive to changes in question formulation and task type.

### 5.4 Defect-level error analysis

Seed 42 B4 defect-level results are:

| Defect | Precision | Recall | F1 |
|---|---:|---:|---:|
| degenerate_faces | 1.000 | 1.000 | 1.000 |
| flipped_normals | 1.000 | 0.958 | 0.979 |
| hole | 1.000 | 1.000 | 1.000 |
| non_manifold | 1.000 | 1.000 | 1.000 |
| stretched_triangles | 0.000 | 0.000 | 0.000 |
| uv_overlap | 1.000 | 1.000 | 1.000 |

Stretched triangles are the dominant remaining failure. Although triangle aspect statistics are present in the metadata, the current image, prompt, and training examples do not establish a sufficiently reliable semantic mapping. This finding motivates targeted examples with graded stretch severity, boundary cases, explicit aspect-ratio explanations, and a direct comparison between metadata-only and B4 predictions.

## 6. Discussion

First, the B0-B3 results show that adding modalities is not equivalent to giving a model effective multimodal reasoning. Multi-view images increase information but also increase the difficulty of associating evidence across images. UV/normal maps can become noise if their visual encoding is not learned. Structured metadata is precise, but the model must still learn the mapping from numeric thresholds to defect semantics.

Second, the B4 improvement indicates that task-specific LoRA adaptation can transform the fixed input protocol into a useful structured diagnosis behavior. The B4 model remains below the deterministic rule baseline, but its defect Macro-F1 varies little across seeds, indicating relatively stable learning for the main defect categories.

Third, performance is substantially less stable on unseen question types than on unseen scenes. The task therefore includes instruction understanding and schema generalization in addition to visual recognition. Future work should treat question-template splits, output schema design, and calibration as independent experimental variables.

## 7. Limitations

1. Blender-generated data cannot fully represent production assets with complex topology, materials, occlusion, scanning noise, and artist-specific conventions.
2. The current 600-sample benchmark is sufficient for controlled ablations but not for broad domain-generalization claims.
3. B4 is trained for only one epoch and uses reduced image resolution to fit an 8 GB GPU, creating a trade-off between training cost and visual detail.
4. Stretched-triangle detection remains unreliable, indicating that the current data and prompt design need targeted improvement.
5. The three seeds use the same fixed test set; evaluation on real 3D assets and external benchmarks remains future work.

## 8. Conclusion

This paper presents a controlled VLM research framework for 3D asset quality diagnosis using multi-view images and structured geometry metadata. Across B0-B4 ablations, a deterministic metadata baseline, and three LoRA seeds, we find that zero-shot Qwen2.5-VL-3B has limited defect recognition under the current multimodal protocol, while task-specific B4 adaptation raises defect Macro-F1 to 82.55% +/- 0.72% across seeds. Generalization to unseen scenes is relatively stable, whereas unseen question types remain sensitive to random initialization and task formulation. The project demonstrates a complete research workflow covering data construction, modality ablation, LoRA adaptation, structured evaluation, and error analysis, while identifying stretched-triangle detection, real-asset validation, and stronger generalization protocols as the next priorities.

## References

[1] Hu, E. J., et al. LoRA: Low-Rank Adaptation of Large Language Models. ICLR, 2022.

[2] Dettmers, T., et al. QLoRA: Efficient Finetuning of Quantized LLMs. NeurIPS, 2023.

[3] Qwen Team. Qwen2.5-VL-3B-Instruct model documentation and model card.

[4] Blender Foundation. Blender documentation and Python API reference.

## Reproducibility

The repository contains the data protocol, Blender generation scripts, training entry point, inference adapter, and evaluation scripts. The formal 600-sample images, model weights, LoRA adapters, and per-sample prediction files are treated as local experiment artifacts and are excluded from the public repository.
