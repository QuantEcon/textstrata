# Changelog

## Unreleased — 0.1.0.dev0

- Initial port of the 2026-08-04 lecture-intro.zh-cn study into a package: config-driven scan, provenance tiers by precedence, prose-only blame, edit pairs and recurring substitutions, overwrite analysis, derived review state, freshness from state files.
- Regression test reproducing the study's per-lecture numbers on the pinned checkout.
- `baseline.strategy` is validated: unknown values and the planned but unimplemented `state-file` are
  rejected instead of silently scanning with `script-jump`.
- README and `docs/method.md` no longer claim character-level churn is reported; that work is tracked in
  [#4](https://github.com/QuantEcon/textstrata/issues/4).
