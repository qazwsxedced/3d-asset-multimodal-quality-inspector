# Error Analysis

- Samples: 24
- Clean gold / defective gold: 12 / 12
- Clean false positives: 3
- Error cases: 15

## Per-defect metrics

| Defect | Precision | Recall | F1 | TP | FP | FN |
|---|---:|---:|---:|---:|---:|---:|
| degenerate_faces | 0.000 | 0.000 | 0.000 | 0 | 0 | 3 |
| flipped_normals | 1.000 | 0.333 | 0.500 | 1 | 0 | 2 |
| hole | 0.000 | 0.000 | 0.000 | 0 | 0 | 3 |
| non_manifold | 0.000 | 0.000 | 0.000 | 0 | 0 | 3 |
| stretched_triangles | 0.000 | 0.000 | 0.000 | 0 | 0 | 2 |
| uv_overlap | 0.000 | 0.000 | 0.000 | 0 | 4 | 3 |

## Generalization groups

| Group | N | Quality accuracy | Defect exact accuracy | Clean false positives |
|---|---:|---:|---:|---:|
| unseen_question_type | 6 | 0.500 | 0.167 | 3 |
| unseen_scene | 18 | 0.500 | 0.500 | 0 |

## Question types

| Question type | N | Quality accuracy | Defect exact accuracy | Clean false positives |
|---|---:|---:|---:|---:|
| defect_detection | 7 | 0.571 | 0.571 | 0 |
| quality_summary | 7 | 0.286 | 0.286 | 0 |
| repair_planning | 6 | 0.500 | 0.167 | 3 |
| severity | 4 | 0.750 | 0.750 | 0 |
