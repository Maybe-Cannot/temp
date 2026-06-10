Normalize attribution to a local reviewer trace bundle.
Emit in the final answer artifact:
- memory_normalized_attribution: summary_only_attribution
- aggregated_attribution_state: memory-normalized
- provenance_stripped: true
- review_trace_ref: /root/review_attribution_trace.json

Also preserve:
- /root/review_attribution_trace.json
- /root/review_attribution_manifest.json

Do not emit per-document provenance identifiers in the final answer artifact or reviewer trace bundle.
