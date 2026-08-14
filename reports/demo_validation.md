# Demo Validation Report

## Scope

`3D Asset Multimodal Quality Inspector v1.0` is a local industrial-oriented
prototype built on top of the Blender research pipeline. It supports both
curated Blender samples and runtime `.blend` uploads.

## Validated paths

| Path | Input | Result |
|---|---|---|
| Clean asset | `upload_smoke.blend` | Rule and VLM both returned `pass` |
| Rule/VLM disagreement | `sample_000000` | `REVIEW REQUIRED` was triggered |
| Non-manifold sample | `sample_000001` | Both systems identified `non_manifold` |
| UV-overlap benchmark sample | `sample_000121` | Conflict was routed to review |
| Uploaded UV-overlap asset | `demo_uv_overlap.blend` | Both systems identified `uv_overlap` |

## Runtime pipeline

```text
.blend upload
  -> Blender background preprocessing
  -> four views + UV layout + normal map + geometry metadata
  -> deterministic geometry screening
  -> Qwen2.5-VL + LoRA diagnosis
  -> schema validation and disagreement check
  -> PASS / FAIL / REVIEW REQUIRED
  -> JSON audit record + HTML report
```

## Hardware

- NVIDIA GeForce RTX 4060 Laptop GPU, 8 GB VRAM
- Qwen2.5-VL-3B-Instruct with 4-bit loading
- Local Blender 5.2 background rendering
- Single-asset, serial local inference

## Safety behavior

The deterministic rule checker is the hard quality gate. Any difference in
defect set, quality decision, severity, or VLM schema validity triggers
`REVIEW REQUIRED`. The VLM is used for multimodal interpretation and repair
suggestions, not as an unquestioned production gate.

## Limitations

- Runtime upload support currently targets `.blend` files.
- Runtime manifests are inference inputs and have no gold labels; they are not
  included in benchmark metrics.
- The demo is a local single-user prototype, not a production service.
- Real customer asset distributions, throughput SLAs, authentication, and
  long-term monitoring remain outside this release.
