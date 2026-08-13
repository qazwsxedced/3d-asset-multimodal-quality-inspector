# Experiment results

The public repository keeps aggregate metrics and error-analysis reports, but does not commit per-sample prediction JSONL files, model weights, or inference caches.

Main artifacts:

- `blender_v3_qwen_b0_b4_summary.json`: B0–B4 aggregate metrics on the real Blender dataset
- `../reports/final_results_blender_v3.md`: final experiment report
- `blender_v3_qwen_b4_final_error_analysis.md`: B4 error analysis

Mock/Pillow results are used only to validate the pipeline. They must not be mixed with the real Blender results or presented as resume performance numbers.
