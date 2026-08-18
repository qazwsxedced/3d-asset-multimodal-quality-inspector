# 3D Asset Multimodal Quality Inspector

This document describes the local 3D asset inspection system published with
this project. It combines deterministic Blender-based checks, diagnostic
images, structured evidence, and optional VLM feedback for `.blend`, `.fbx`,
and `.obj` assets.

## What it checks

- Geometry: triangle count, degenerate faces, normals, non-manifold geometry,
  holes, self-intersections, isolated vertices, and topology risk.
- UVs: UV presence, overlap, out-of-range coordinates, stretch, density, and
  diagnostic heatmaps.
- Materials: PBR channel coverage, texture paths, color-space expectations,
  material-slot count, and missing-resource risks.
- Runtime suitability: estimated memory, texture footprint, draw-call risk,
  LODs, object count, file size, and adaptive inspection strategy.
- Animation: armature and action discovery, skinning coverage, vertex-weight
  validation, excessive influences, and deformation probes.
- Import details: units, transforms, negative scale, coordinate conventions,
  external or embedded resources, multiple UV channels, vertex colors, and
  morph targets when available.

## Scoring model

The system separates two decisions:

1. **Health score** is a deterministic hard-metric score. It is intended to
   answer whether the asset violates measurable quality gates.
2. **Profile fit score** is a policy-weighted score that changes with the
   intended use case, such as real-time/XR, visual display, 3D printing,
   character animation, or textured assets.

The report also shows coverage, confidence, sampled checks, not-checked
components, score contributions, thresholds, evidence, impact, repair steps,
and recheck criteria. A missing or sampled check is not silently presented as
an unconditional pass.

## Inspection modes

- **Rule baseline**: deterministic checks only; best for reproducible gates.
- **VLM diagnosis**: multimodal explanation using rendered evidence and
  structured metadata.
- **Hybrid review**: rule results remain authoritative while the VLM adds
  contextual explanation and repair suggestions.

## Run locally on Windows

From the project directory:

```powershell
.venv\Scripts\python.exe demo\app.py --host 127.0.0.1 --port 7860
```

Then open `http://127.0.0.1:7860` in a browser. The desktop shortcut created
for this workspace starts the same service and opens the browser automatically.

Required local components include Python dependencies from
`requirementsdemo.txt` and a working Blender executable. The Blender path
and threshold JSON can be configured in the demo interface or runtime
configuration.

## Test the inspection pipeline

Generate the controlled FBX/OBJ/BLEND fixtures and run the correctness suite:

```powershell
.venv\Scripts\python.exe scripts\build_inspection_test_assets.py
.venv\Scripts\python.exe scripts\run_inspection_test_suite.py `
  --cases tests\inspection_test_cases.json `
  --out tests\inspection_assets\suite_report.json
```

The suite checks both whether a file can be inspected and whether expected
facts are detected, including missing UVs, missing textures, high polygon
counts, rigging, multiple materials, LODs, and multi-part assets.

## Repository scope

Source code, configuration, test definitions, and reproducible inspection
scripts are included. Blender-generated fixtures, previews, heatmaps,
temporary logs, model weights, and runtime outputs remain local and are
ignored by Git.
