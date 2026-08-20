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
2. Confirm the Blender executable path. Blender 5.2 is auto-detected on the
   default Windows installation path and common macOS/Linux paths; you can
   also set `BLENDER_EXECUTABLE` or `BLENDER_PATH` before launching.
3. Click **Prepare uploaded asset**.
4. Select **Rule baseline** or **Hybrid review**, then click **Run inspection**.

If the browser file picker does not respond, paste the absolute local path into
**Local asset path fallback / 本机文件路径备用入口** and click **Use local path /
使用本机路径**. This uses the same staging, Blender import, evidence, and
report-generation pipeline as a browser upload.

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
Animation coverage is separated into `binding_only` (weights and armature
binding were checked, but no action was available), `sampled_pose` (actions
and representative poses were sampled), and `not_checked` (animation data was
present but no executable skinning probe was available). A binding-only result
must not be interpreted as proof that animation playback is correct.

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

Blender process management is implemented in `src/blender_runner.py`. It
records `job_status.json`, distinguishes completed, failed, cancelled, and
timed-out jobs, and terminates child processes as a group on Windows, macOS,
and Linux. Terminal status values use the shared `JobStatus` enum from
`src/inspection_enums.py`, so the runner, tests, and downstream consumers use
the same vocabulary.

The **Task control / 任务控制** panel exposes the persisted task ID after an
upload, generated fixture, or repair. **Query status** reads the corresponding
`runtime_uploads/**/job_status.json` record after a page refresh or process
restart; **Refresh history** lists the newest 50 discovered tasks. Failed,
cancelled, and timed-out records are marked retryable, while completed or
currently running records are not. `src/task_store.py` also provides a
dry-run-first retention scan for old terminal jobs. The original synchronous
buttons remain available for compatibility, and the page also provides
background submission buttons backed by `src/task_queue.py`. Background jobs
return immediately, persist queue state and `result.json`, and can be loaded
back into the same previews after completion. Pause/resume, automatic deletion
scheduling, and multi-process workers are not yet enabled; a process restart
marks unfinished queue tasks as failed and retryable instead of pretending they
resumed.

Uploaded files are validated and staged by `src/asset_staging.py`. OBJ files
copy locally referenced `.mtl` and texture resources into the isolated job
directory; each job records file size, SHA-256, copied sidecars, and staging
warnings in `staging.json` and the runtime manifest.

Runtime evidence paths are resolved relative to the isolated job directory and
must remain inside that directory. Missing or escaping paths are ignored rather
than loaded, so a malformed manifest cannot make the page read arbitrary local
files. After Blender exits successfully, the upload service validates PNG
dimensions and pixel variation, parses the GLB 2.0 JSON/mesh container, and
checks the locator JSON and selection script. Uniform UV evidence is allowed
when the asset has no UV and the check is not applicable. An
incomplete output is reported with the exact artifact and job log instead of
being presented as a usable inspection. Inspection failures are written as
structured JSON logs with the operation, exception type, message, UTC time, and
traceback; the operator-facing error remains a concise bilingual explanation.

HTML and JSON audit export are isolated in `src/report_service.py`. Every HTML
report contains the decision summary, canonical issue cards, visual evidence,
and a collapsible provenance/audit section; the adjacent JSON download uses the
same canonical structured payload for downstream tools. `src/provenance.py`
records the task ID, input hash, configured and effective threshold-config
hashes, detector version, inspection mode, condition, and UTC detection time.
For an uploaded asset, the effective hash points to the runtime threshold file
actually used by Blender; this prevents a report from claiming reproducibility
from a different config.
The page's feedback summary also includes a collapsed **检测追溯 / Inspection
traceability** panel. It shows short hash values and the detector version without
making the default report verbose; the complete hashes remain in the downloadable
JSON audit record.

The JSON export is versioned with `audit_schema_version` so external consumers
can reject or migrate an incompatible result format explicitly.

The typed result envelope lives in `src/inspection_result.py`. It groups asset,
geometry, UV, material, animation, runtime, score, issue, and provenance data;
the report exporter uses this envelope while the UI keeps a compatibility view
of the legacy result keys during the migration. Before JSON or HTML export,
the envelope normalizes issue records and validates schema version, coverage
states, severity, blocking state, evidence, impact, fix, recheck, and locator
fields. An incomplete result aborts export with field-level errors instead of
creating a misleading audit file.

The inspection callback is split into `demo/services/asset_service.py`,
`rule_engine.py`, `vlm_service.py`, and `inspection_service.py`. Blender's
worker entry point delegates scene inventory, geometry, UV, material/PBR,
performance, animation, and object/face localization to modules under
`blender/`. Issue locators expose object names, related face counts, and capped
face-index lists; large assets also report when those indices were sampled or
truncated.

After an inspection, the **Issue locator / 问题定位** panel provides a
selectable issue list. Selecting an issue shows its evidence target, source
objects, related-face count, capped face-index list, and whether the index list
was truncated. The issue cards also provide quick links to the corresponding
3D overlay, UV, heatmap, or normal evidence panel. The **Download issue
locator JSON** button exports the same object/face evidence as a standalone
machine-readable file for DCC repair tools or downstream automation. **Download
Blender face-selection script** exports a self-contained `apply_issue_locator.py`:
open the original asset in Blender, open the script in the Text Editor, and run
it to select every locatable problem face. To select one issue only, set its
`ISSUE_ID` near the top of that script (for example `"uv_overlap"`). The script
also records that face indices belong to the original source base mesh. It
resolves an object by exact name first, then falls back to the stored topology
fingerprint plus vertex/face counts and world position when an FBX/OBJ importer
renames it. It reports renamed, missing, ambiguous, modified, triangulated, or
out-of-range targets and skips a changed model by default instead of applying
stale indices; only set `ALLOW_TOPOLOGY_MISMATCH = True` after manual
verification.

The page also includes **Object picker / 点击对象定位** above the issue cards.
It uses a small Babylon.js canvas alongside Gradio's stable `Model3D` preview:
clicking a mesh object, or its object button, sends the mesh name back to the
page and selects the highest-priority matching issue. When an issue overlay is
available, the picker loads that overlay and reads the clicked material marker,
so a surface click can select the corresponding issue card and report the
clicked overlay triangle. Because GLB export may triangulate the source mesh,
the clicked overlay triangle is evidence for the visual region, while original
source face indices remain canonical in the locator JSON and Blender script.
If the Babylon CDN is unavailable, the normal preview and object buttons remain
available; the page reports that 3D picking is unavailable instead of claiming
a successful hit.

PBR material issues use the same locator chain: the report records the affected
material, the source objects that use it, the face count assigned to that
material slot, and the slot index when available. This makes a channel or color
space warning actionable even when the asset contains many mesh components;
the material locator remains empty when the source manifest has no reliable
object-to-material mapping.

Asset convention warnings distinguish intentional-but-reviewable conditions
from higher-risk transform defects: non-unit scale is reported as information,
while negative or near-zero scale is raised to a warning because it can affect
normals, mirroring, or export transforms.
Transform warnings also carry the affected mesh-object names into the issue
locator, so a multi-part FBX can be repaired selectively instead of requiring
a scene-wide transform pass. The same object-level locator is used for source
objects without UVs and objects containing unassigned material slots when that
mapping is available from the Blender inventory.

Additional deterministic detectors can be registered through
`src/detector_registry.py`. The built-in registry currently covers geometry,
UV, materials, runtime performance, and animation/skinning.

Score weights and defect penalties are configured in
[`config/inspection_scoring.json`](../config/inspection_scoring.json). Each
score records `score_config_version` and `score_config_hash`.

The repository includes cross-platform GitHub Actions in
`.github/workflows/ci.yml`. Python unit and regression-contract tests run on
Ubuntu, Windows, and macOS for Python 3.11 and 3.12. Blender fixture tests
remain an explicit integration command because hosted runners do not provide
a stable Blender version by default.

Project thresholds are configured in
[`config/inspection_thresholds.json`](../config/inspection_thresholds.json) and
can also be replaced with another JSON path in the page. The same values are
used by Blender diagnostics and health-score explanations, including face
budget, UV overlap, triangle stretch, texture size, material slots, draw-call
risk, texture memory, load time, skin influences, and weight-sum tolerance.
Thresholds are validated by the shared [`src/threshold_config.py`](../src/threshold_config.py)
schema before an uploaded inspection starts: unknown keys, invalid types,
non-finite values, and out-of-range values are reported with the exact field
name. Direct Blender-side loading also falls back to the complete default set
when a config is missing or invalid, so a malformed file cannot silently
produce a partial threshold set.
For complex assets, UV overlap/density and heatmap work is capped by
`max_diagnostic_triangles`; the result records when those values are sampled,
while topology counts and source-scene inventory remain available.

## Real FBX/OBJ inspection test set

Generate the reproducible fixture set and run all cases with Blender:

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b `
  --python scripts\build_inspection_test_assets.py -- `
  --out tests\inspection_assets\generated

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
levels. Assertion failures include the expected and actual values. Every case
also checks that the required images and GLB pass content-level validation,
that `issue_locator.json` and `apply_issue_locator.py` exist inside its output
folder, and that Blender receives an absolute output path on Windows. It is
still a smoke/regression suite, not a labeled quality benchmark.

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

Coverage classification is shared by the page, detector plug-ins, and scoring
layer through `src/coverage_policy.py`. Material inspection therefore remains
`checked` even when a material deliberately has zero image textures, runtime
inspection can be checked from any available runtime statistic, and animation
deformation probes are explicitly reported as `sampled` rather than full
frame-by-frame verification.
The policy also rejects null, empty, or invalid metric payloads; a legitimate
numeric zero remains valid, so “zero texture images” and “zero PBR issues” are
not confused with “no material inspection was produced”.

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
