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

## Upload a `.blend`

1. Choose a `.blend` file in **Upload .blend asset**.
2. Confirm the Blender executable path (Blender 5.2 is auto-detected on the
   default Windows installation path).
3. Click **Prepare uploaded asset**.
4. Select **Rule baseline** or **Hybrid review**, then click **Run inspection**.

Blender runs in background mode and writes the uploaded asset's four views,
UV layout, normal map, geometry statistics, and a runtime manifest under
`runtime_uploads/`. The source file is copied into an isolated job directory
and is not modified. Runtime manifests are inference inputs, not labeled
evaluation datasets, so they are intentionally not used for benchmark scores.

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
