# Three-Week Research Execution Plan

## Research hypotheses

H1: Under the same model and prompt, multi-view images improve structured answers in occluded scenes compared with a single view.

H2: UV/normal maps primarily help with texture and normal diagnostics; their benefit may be limited for purely spatial questions.

H3: Structured geometry metadata may provide more stable signals for counting, position, and visibility questions, but may reduce robustness to corrupted metadata.

H4: LoRA/SFT on the B3 protocol can improve JSON validity and field accuracy, but its results must be reported separately from B3 zero-shot.

## Week 1: Data and baseline

- Use 120 lightweight samples to validate the schema, image paths, answer consistency, and evaluation scripts.
- Generate 1,000–2,000 MVP samples in Blender and split them by `scene_id`.
- Fix the Qwen2.5-VL-3B prompt, `temperature=0`, `max_new_tokens`, and image ordering.
- Run B0–B3 zero-shot inference with the same `sample_id` set for every condition.

## Week 2: LoRA/SFT

- Inspect B0–B3 predictions and error distributions before training B4.
- Change only one factor in the first run: B3 input + LoRA rank 16. Log learning rate, epochs, and effective batch size.
- Record GPU model, VRAM, training time, throughput, loss, checkpoints, and dependency versions.
- Compare B3 zero-shot with B4 on a fixed test set; do not use training metrics as the primary result.

## Week 3: Generalization, ablations, and delivery

- Report `unseen_scene`, `unseen_view`, `unseen_combo`, and `unseen_question_type` separately.
- Run three ablations: dataset size, input modality, and LoRA hyperparameters.
- Produce error cases covering occlusion, spatial relations, metadata conflicts, JSON syntax, and missing fields.
- Package batch inference, evaluation, and result aggregation; then prepare the README, presentation, and resume metrics.

## Results template

| condition | split | n | accuracy | macro-F1 | JSON valid | field acc. | P50 ms | P95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | test |  |  |  |  |  |  |  |
| B1 | test |  |  |  |  |  |  |  |
| B2 | test |  |  |  |  |  |  |  |
| B3 | test |  |  |  |  |  |  |  |
| B4 | test |  |  |  |  |  |  |  |

## Reporting discipline

- Use the word “improvement” only when supported by the same test samples, the same decoding settings, repeated experiments, or confidence intervals.
- Results on synthetic 3D data support conclusions about controlled 3D-scene reasoning only.
- Report external benchmarks as separate transfer experiments rather than mixing them into the main table.
- Preserve negative results: if B2 or B3 shows no gain, that is still a research finding about modality effectiveness.
