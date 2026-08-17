# Engineering Delivery Summary

## Project objective

This project develops a research-to-prototype workflow for 3D asset quality
inspection. The target problem is repetitive manual checking of topology, UV,
normal, and geometric-quality issues in game, rendering, digital-twin, and
content-production pipelines.

The system is designed as an assistive quality gate, not as an autonomous
replacement for a technical artist. Deterministic geometry rules provide the
hard safety gate; the VLM contributes multimodal interpretation, structured
output, and repair suggestions.

## Delivered components

| Area | Delivered capability | Evidence |
|---|---|---|
| Data engineering | Blender 5.2 generator with five asset families, four views, UV/normal maps, six defect types, and scene-level splits | `reports/phase2_results_blender_v5.md` |
| Research protocol | Controlled B0-B4 input conditions and schema-aware evaluation | `configs/experiments.json`, `scripts/evaluate_predictions.py` |
| Baselines | Metadata-only deterministic rule baseline and Qwen2.5-VL zero-shot baseline | `scripts/run_rule_baseline.py`, phase-2 report |
| Model adaptation | 4-bit QLoRA training for Qwen2.5-VL-3B with reproducible seeds and saved run configuration | `scripts/train_lora.py` |
| Reliability analysis | Multi-label Macro-F1, exact match, schema validity, latency, grouped generalization, and error analysis | `scripts/analyze_errors.py` |
| Product prototype | Rule baseline, VLM diagnosis, and Hybrid review modes with disagreement routing | `demo/app.py` |
| External input path | `.blend` upload, Blender background preprocessing, runtime manifest, JSON audit record, and HTML report | `blender/inspect_asset.py`, `reports/demo_validation.md` |

## Current evidence

The multi-asset benchmark contains 600 samples across five asset families with
420/60/120 train/validation/test splits. On the 120-sample test set:

- the deterministic rule baseline reached 95.00% quality accuracy and 95.71%
  defect Macro-F1;
- the single reported B4 run reached 88.33% quality accuracy, 81.67% severity
  accuracy, 82.98% defect Macro-F1, and 99.17% schema validity;
- three B4 seeds reached 82.55% +/- 0.72% defect Macro-F1;
- unseen-scene B4 performance was 83.33% defect Macro-F1, while unseen-question
  type performance was lower and less stable.
- a separate 28-asset external `.blend` fixture set achieved 28/28 successful
  Blender preprocessing jobs; Rule-only, VLM-only, and Hybrid achieved 94.44%,
  90.00%, and 94.44% defect Macro-F1 respectively, with 3/28 disagreements
  routed for review;
- external preprocessing averaged 3.50 seconds per asset with a 3.83-second
  P95 under serial local execution.

These are controlled synthetic Blender results. They demonstrate the
research pipeline and prototype feasibility; they are not evidence of
cross-domain generalization or production deployment.

## Industrial workflow represented by the prototype

```text
.blend upload
  -> isolated Blender preprocessing
  -> multi-view / UV / normal evidence + geometry metadata
  -> deterministic geometry screening
  -> optional Qwen2.5-VL diagnosis
  -> schema validation and disagreement check
  -> PASS / FAIL / REVIEW REQUIRED
  -> JSON audit record + HTML report
```

The review policy is intentionally conservative: disagreement in defect set,
quality decision, severity, or VLM schema validity is routed to human review.
This makes the prototype suitable for demonstrating an industrial integration
boundary without claiming that a generative model can be trusted as the sole
quality gate.

## Remaining work before production use

1. Evaluate on a customer-owned or manually annotated external asset set.
2. Add authentication, job queueing, retries, resource limits, and persistent
   experiment/audit storage.
3. Add DCC integrations or a batch CLI for Maya, Blender, and asset-server
   workflows.
4. Calibrate review thresholds against the cost of false acceptance and false
   rejection.
5. Benchmark throughput and memory under concurrent jobs.

## Resume-safe contribution statement

> Independently designed and implemented a multimodal 3D asset quality
> inspection research prototype, covering Blender data generation, B0-B4
> ablations, Qwen2.5-VL QLoRA adaptation, deterministic geometry baselines,
> schema-aware evaluation, error analysis, `.blend` upload preprocessing, and
> rule/VLM hybrid review with auditable JSON/HTML outputs.
