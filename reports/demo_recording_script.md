# Demo Recording Runbook

## Target

Record a 2-3 minute screen capture showing the complete inspection workflow.
The recording should demonstrate the system boundary and the review policy,
not just a successful model response.

## Recommended sequence

1. Show the repository title and explain the problem in one sentence:
   “This prototype combines deterministic 3D geometry checks with Qwen2.5-VL
   diagnosis to reduce repetitive asset-quality inspection.”
2. Launch `demo/app.py` and select **Rule baseline**.
3. Inspect one clean asset and show the PASS result, geometry metadata, and
   generated evidence images.
4. Upload `demo_uv_overlap.blend` and click **Prepare uploaded asset**.
5. Select **Hybrid review** and click **Run inspection**.
6. Show the UV map, the detected `uv_overlap` defect, severity, repair plan,
   and the selected source in the audit record.
7. Select an asset where rule and VLM disagree, then show
   `REVIEW REQUIRED` and the disagreement reasons.
8. Download the HTML report and briefly show that the output is auditable.

## Closing statement

“The rule checker remains the hard quality gate. The VLM adds multimodal
interpretation and repair suggestions, while disagreements are sent to a
human reviewer. This is an industrial-oriented prototype rather than a claim
of autonomous production deployment.”

## Recording checklist

- Hide personal directories, tokens, browser tabs, and unrelated notifications.
- Use 1080p or higher and keep the browser zoom at 100%.
- Keep the terminal visible only when launching the app or showing the report.
- Do not claim that the synthetic or controlled external fixture results are
  customer-production accuracy.
- Save the final recording as `artifacts/demo_walkthrough.mp4` locally; keep
  the binary out of Git unless a hosting decision is made.
