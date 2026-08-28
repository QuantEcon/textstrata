# Changelog

## Unreleased — 0.1.0.dev0

- Initial port of the 2026-08-04 lecture-intro.zh-cn study into a package: config-driven scan, provenance tiers by precedence, prose-only blame, edit pairs and recurring substitutions, overwrite analysis, derived review state, freshness from state files.
- Regression test reproducing the study's per-lecture numbers on the pinned checkout.
- `baseline.strategy` is validated: unknown values and the planned but unimplemented `state-file` are
  rejected instead of silently scanning with `script-jump`.
- README and `docs/method.md` no longer claim character-level churn is reported; that work is tracked in
  [#4](https://github.com/QuantEcon/textstrata/issues/4).
- Character-level churn ([#4](https://github.com/QuantEcon/textstrata/issues/4)): `chars_changed` per pair,
  `prose_chars_added`/`prose_chars_deleted` per commit and `prose_char_churn_by_tier` per document, so F1
  can be read per 1,000 characters as well as per 1,000 lines.
- `state-file` baseline strategy ([#1](https://github.com/QuantEcon/textstrata/issues/1)): the translation
  moment is the first revision of the document's state file — the engine's own record — instead of the
  script-ratio jump. Requires `machine.state_dir`; a document without a state file is untranslated under it.
  The programming.zh-cn reference config adopts it.
- Reviewed tier-override file for lecture-python.zh-cn (preparation for
  [#1](https://github.com/QuantEcon/textstrata/issues/1)): the probable whole-file AI passes inside the
  2025 hand-translation campaign, derived by rule and adjudicated from their before/after pairs, so the
  first report's human churn is not inflated by regenerated files committed under roster names.
- Engine-version strata ([#2](https://github.com/QuantEcon/textstrata/issues/2)): each `ai-sync` commit is
  stamped with `engine_model`/`engine_tool_version` from the state-file history (the record written by or
  immediately after the commit), `run.json` carries per-version totals (`engine_strata`), and
  `overwrites.json` entries are stamped the same way; syncs with no record read `unrecorded`.
- Unpaired additions and deletions are prose-gated ([#14](https://github.com/QuantEcon/textstrata/issues/14)):
  an unpaired line with no target-script content routes to `code-or-markup` instead of
  `addition`/`deletion`, mirroring the paired-line rule, so the omission taxonomy counts prose only.
  The total pair count is unchanged — only categories shift.
