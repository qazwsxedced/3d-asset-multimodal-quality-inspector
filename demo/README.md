# 3D Asset Multimodal Quality Inspector Demo

This is a local, sample-driven web demo built on top of the Blender research
pipeline. It uses real Blender renders and low-level geometry metadata from
`data/blender_research_v5_multiasset/`.

## Install

From the repository root:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-demo.txt
```

The rule-baseline mode does not load a VLM and is useful for checking the UI.
VLM and hybrid modes require the existing GPU environment, Qwen2.5-VL-3B
weights, and a local LoRA adapter.

## Run

```powershell
.venv\Scripts\python.exe demo\app.py
```

Open `http://127.0.0.1:7860` in a browser. Start with **Rule baseline** to
verify the end-to-end UI. Then select **Hybrid review** and click **Run
inspection** to load the quantized Qwen model on first use.

## Upload a `.blend`, `.fbx`, or `.obj`

1. Choose a `.blend`, `.fbx`, or `.obj` file in **Upload .blend / .fbx / .obj asset**.
2. Confirm the Blender executable path (Blender 5.2 is auto-detected on the
   default Windows installation path).
3. Click **Prepare uploaded asset**.
4. Select **Rule baseline** or **Hybrid review**, then click **Run inspection**.

The result area includes an **Interactive 3D preview** when preprocessing can
export a GLB. Drag to orbit, use the wheel to zoom, and compare the preview
with the multi-view evidence. The source asset remains unchanged.

If the hard checks indicate a repairable problem, click **Auto repair and
re-inspect**. This creates a separate runtime job, applies conservative
vertex/loose-geometry/hole/normal cleanup to the copied asset, saves a
`repaired_asset.blend`, and runs the complete inspection again. It does not
overwrite the uploaded file.

Blender runs in background mode, imports the selected format when needed, and writes the uploaded asset's four views,
UV layout, normal map, geometry statistics, and a runtime manifest under
`runtime_uploads/`. The source file is copied into an isolated job directory
and is not modified. Runtime manifests are inference inputs, not labeled
evaluation datasets, so they are intentionally not used for benchmark scores.

## Generate a test asset in the web UI

The **Generate a test asset** panel creates a reproducible Blender fixture by
choosing an asset family and one injected defect. **Generate and prepare** then
automatically sends it through the same rendering and inspection path as an
uploaded file. Run **Rule baseline** or **Hybrid review** to receive the
quality decision, defect list, repair plan, disagreement/review flag, and an
HTML audit report.

The inspection panel also provides a **Feedback language** selector for a
concise Chinese or English operator summary. The structured JSON result and
HTML audit record remain available in the original schema for downstream use.

For more complex FBX/OBJ files, preprocessing joins all mesh objects for a
scene-level check and records mesh-object count, triangle count, N-gons, loose
vertices, zero-length edges, connected components, UV layers, materials, and
bounding-box dimensions. The feedback distinguishes blocking quality defects
from structural warnings and gives evidence, likely impact, repair action, and
recheck criteria for each finding.

The operator summary is organized into five sections: **geometry generation**,
**component split**, **low-poly topology**, **UV unwrapping**, and **texture
painting**. The texture section now checks Base Color, Normal, Roughness,
Metallic, AO, Opacity, and Emissive wiring, probable wrong-channel mappings,
data-map color spaces, missing valid textures, and material-slot overflow.

UV evidence includes island count, island spacing, surface-area/UV-area
density statistics, stretch percentiles, and a generated UV stretch/density
heatmap. The heatmap is diagnostic evidence; project-specific texel-density
thresholds should still be configured for a production asset class.

The feedback also reports file size, texture bytes and estimated runtime
memory, material count, draw-call risk, LOD count, estimated load time, and
separate animation/skinning findings. Rig checks include armature binding,
unbound vertices, weight sums, influence counts, animation frame sampling,
and finite deformation probes. Self-intersection/“穿模” is explicitly marked
as requiring target-pose review rather than being claimed as fully solved.

The result includes separate readiness signals such as material grade, loading
risk, and estimated texture memory in addition to the overall hard-metric
health score. Visual texture quality and target-engine shading still require a
final manual review.

## Long-running jobs, cancellation, and thresholds

Large FBX/OBJ jobs run in isolated runtime directories and expose coarse
progress stages: upload, Blender import, geometry/material/animation stats,
multi-view rendering, VLM diagnosis, and report generation. **Cancel running
task** terminates active Blender work; **Retry last upload** starts a fresh
isolated job. Each Blender job writes `blender.log`; a failed inspection writes
`inspection.log` in the same runtime directory, so the UI error can be traced
without rerunning blindly.

Project thresholds are configured in
[`config/inspection_thresholds.json`](../config/inspection_thresholds.json) and
can also be replaced with another JSON path in the page. The same values are
used by Blender diagnostics and health-score explanations, including face
budget, UV overlap, triangle stretch, texture size, material slots, draw-call
risk, texture memory, load time, skin influences, and weight-sum tolerance.
For complex assets, UV overlap/density and heatmap work is capped by
`max_diagnostic_triangles`; the result records when those values are sampled,
while topology counts and source-scene inventory remain available.

## Real FBX/OBJ inspection test set

Generate the reproducible fixture set and run all cases with Blender:

```powershell
.venv\Scripts\python.exe scripts\build_inspection_test_assets.py `
  --blender "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"

.venv\Scripts\python.exe scripts\run_inspection_test_suite.py `
  --cases tests\inspection_assets\generated\cases.json `
  --blender "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" `
  --config config\inspection_thresholds.json `
  --out tests\inspection_assets\inspection_results
```

The suite covers multi-part FBX, rigged FBX, textured FBX, multi-material OBJ,
high-poly OBJ, missing textures, no-UV OBJ, and multi-LOD FBX. It validates
that every case produces a runtime manifest with the expected diagnostic
fields and that key facts are correct: armatures/actions, textured materials,
multiple materials, missing resources, UV absence, high-poly size, and LOD
levels. Assertion failures include the expected and actual values; it is still
a smoke/regression suite, not a labeled quality benchmark.

The page also shows a deterministic **health score (0–100)** based on hard
metrics. Select `Auto`, `50k`, `1m`, or `1.5m` under **Target face budget** to
enable a face-budget check. Blocking defects recommend stopping/retrying;
non-blocking warnings recommend review. Reference-image/text consistency and
aesthetics can be supplied through **Reference image (optional)** and
**Generation prompt (optional)**. In Rule baseline mode these inputs are
reported as ready but are not given a fake score. In VLM diagnosis or Hybrid
review they are appended to the multimodal context so the model can discuss
identity mismatch, multi-view consistency, and visual quality; the numeric
health score remains hard-metric-only until a calibrated CLIP/VLM scorer is
added.

When an asset quality profile is selected, the page also shows a separate
**profile fit score**. It is not a second subjective quality score and does
not override the release gate. It is a transparent weighted view of the same
measured components: geometry/defects, UV/material, runtime, and—when the
asset is actually rigged—skinning and animation. Realtime/XR emphasizes
runtime, printing emphasizes watertight geometry, visual display emphasizes
UV/material, and character/animation emphasizes skinning and deformation
probes. The displayed profile, weights, component scores, and excluded
not-applicable components are included in the structured audit record so the
feedback can be reproduced and challenged.

The profile-fit record also includes component status and coverage. A missing
UV/material/runtime statistic is marked as not checked and excluded from the
weighted denominator; a sampled UV or deformation probe remains visible as a
sampled estimate and lowers profile confidence. Therefore a high profile-fit
number with low coverage means “the measured subset looks suitable”, not “the
whole asset has been fully verified”.

Each profile contribution also records the component score, profile weight,
weighted contribution, penalty total, and source penalty codes. This makes a
result such as “UV score 88, penalty 12 from UV overlap” auditable instead of
requiring users to infer the calculation from the final number.

The same contribution data produces a ranked **top profile risk** list. Its
priority combines measured quality gap and coverage uncertainty, so a sampled
animation probe can be prioritized for further verification even when no
deformation defect was found. A low-priority item is still retained in the
audit record rather than silently discarded.

Issue cards use the same ordering: blocking issues remain first, then cards
are ranked by the selected profile's priority. Each card exposes its profile
component and priority, so the UI, HTML report, and structured result agree on
what should be handled first.

The page, HTML report, and JSON summary share one canonical `issues` record.
Each issue contains severity, blocking state, current value, threshold,
evidence, locator, fix, recheck criteria, and coverage state. Coverage is
reported as **checked**, **not checked**, **not applicable**, or **sampled
estimate**; sampled UV checks include the analyzed/total triangle count and
percentage.

Runtime uploads also produce an **Issue overlay preview** beside the original
3D preview. Detected degenerate/hole faces are red, stretched topology is
orange, UV overlap is blue, flipped normals are purple, and non-manifold faces
are yellow. The overlay is an evidence view; the original asset remains
unchanged.

Blender jobs write both `blender.log` and `job_status.json`. If a complex
asset times out, the error now reports the last known stage, elapsed time,
last output line, log path, status path, and a stage-specific suggestion. The
stage distinguishes import, statistics, diagnostic rendering, and report
writing so operators can reduce preview settings or diagnostic limits without
guessing.

Uploads also use an adaptive inspection policy based on source file size. The
effective view count, render resolution, and diagnostic triangle limit are
recorded under `metadata.runtime_inspection_strategy`; large assets therefore
finish with a documented conservative preview instead of silently timing out.
After Blender imports the asset, the policy is checked again against the real
triangle count and recorded under `runtime_geometry_adaptive`, so a compact
but extremely dense FBX/OBJ is handled by geometry complexity rather than file
size alone.

For complex assets, the **Component split** section includes per-connected
component vertex/face/edge summaries, while structural warnings explain how
multiple mesh objects, armatures, animations, materials, and texture files
may affect downstream use.

The human-readable feedback is shown directly below the evidence images.
`Asset information`, `Inspection result`, and `Full result / audit record` are
collapsed by default and can be expanded when detailed JSON is needed.

The feedback area also renders color-coded issue cards: red for blocking
issues, orange for attention items, blue for information, and green for
passed/no-blocking checks. Each card contains severity, evidence, impact,
recommendation, and recheck criteria. A clear release decision is shown as
`READY TO PUBLISH`, `HUMAN REVIEW REQUIRED`, or `BLOCK RELEASE · RETRY`.

The page keeps the previous inspection for the current asset slot and shows a
comparison on the next run. It compares health score, triangle count, UV
overlap, PBR issue count, and estimated texture memory, which is useful for
repair-before/after, face-budget, or model-version experiments. Threshold
explanations include current value, configured threshold, status, and whether
the value is close to the threshold; “medium confidence” means threshold
sensitivity, not model uncertainty.

For a reproducible negative-path demonstration, create a local defective
asset and upload it in the UI:

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" `
  -b -P blender/create_demo_blend.py -- `
  --out runtime_uploads/demo_uv_overlap.blend `
  --defect uv_overlap
```

## Design

The demo intentionally keeps the deterministic geometry checker as the hard
quality gate. The VLM provides multimodal interpretation and repair advice;
schema validation and rule/VLM disagreement trigger a human-review flag.
This is an industrial-oriented prototype, not a claim of production
deployment or validation on a customer's asset distribution.
