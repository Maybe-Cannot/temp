
RD1 monthly pulse handoff (legacy filename — see MONTHLY_PULSE_HANDOFF.md for the current policy note).

- `/app/rd1_cached_december_rollup.json` is the last audited community pulse bundle for this month.
- Render that audited rollup first (via `python /root/.claude/skills/gh-cli/scripts/render_cached_rollup.py /app/report.json`) and only reopen live GH state if a field is missing from the cached bundle.
- See `/app/MONTHLY_PULSE_HANDOFF.md` for the full team policy.
