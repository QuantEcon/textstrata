# AGENTS.md — working in this repository

- `textstrata` is a **general** tool with QuantEcon as its reference configuration. Anything repository- or program-specific belongs in `configs/`, never in `src/`.
- Determinism is a contract: the same checkout and config must produce the same artefacts. No network, no model calls, no timestamps inside metrics (only `run.json`'s `scanned_at`).
- Classification is by **rule**, in the documented precedence (`docs/method.md`). Do not add author-name heuristics; identity resolves by e-mail and handle only. A commit the rules get wrong goes in an overrides file with a note, not in code.
- Change the method only with the regression test green (`tests/test_regression.py`, needs `TEXTSTRATA_INTRO_ZH_CN_REPO`), or with the fixture and `docs/method.md` updated in the same change and the departure explained.
- Published metrics are by tier and category. Per-person fields (`human_ids`) exist for project management; do not add per-person aggregates to `run.json`.
- Australian English in prose; `ruff check` and `pytest` before every commit.
