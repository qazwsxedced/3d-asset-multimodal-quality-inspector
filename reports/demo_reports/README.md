# Public Demo Evidence

These HTML files are sanitized audit-report examples from the local `.blend`
upload demo. They are included as qualitative evidence of the inspection flow,
not as an independent benchmark or a production acceptance guarantee.

| File | Scenario | Expected behavior |
|---|---|---|
| `hybrid_uv_overlap_review.html` | Controlled UV-overlap fixture | Rule/VLM disagreement is routed to human review |
| `rule_clean_asset_pass.html` | Controlled clean fixture | Rule baseline returns `PASS` with no defects |

The original runtime reports remain outside the public repository. These copies
contain no local absolute filesystem paths.
