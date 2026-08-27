# Method

*How textstrata turns git history into metrics, and what the numbers can and cannot say.*

## Two axes

Every change is classified on two independent axes:

- **Who** — the *provenance tier* of the commit's author: `ai-initial` (the machine's first draft of a document), `ai-sync` (a machine re-sync), `ai-assisted` (disclosed AI assistance, AI coding agents, and by default anyone not on the roster), `human-editor`, `human-translator` (roster roles), `seed` (content predating translation).
- **What** — the *category* of a before/after line pair: `terminology`, `fluency`, `retranslation`, `addition`, `deletion`, `punctuation-width`, `code-or-markup`, `localise-code-label`. A mapping table (`pairs.CATEGORY_MAP`) folds these into the broader taxonomy terminology / accuracy / fluency / style / formatting / omission. *Accuracy* (a meaning change) cannot be separated from fluency by a string rule and is left to human adjudication.

Keeping the axes separate is what lets a translator's fix to a code comment be counted as "translator" and as "formatting" without a special class for it.

## Tier precedence

Rules are applied in order; the first match wins. Content rules come before author rules, so a machine draft committed under a person's name is still machine.

1. Bot author (other than a declared AI agent), or the machine's sync signature (subject regexes; optionally also a change under the state directory) → `ai-sync`
2. The document's translation moment → `ai-initial`. Per-commit overrides (a reviewed data file) apply here and may not reclassify rules 1–2.
3. Disclosed AI assistance — a configured trailer (`AI-Assisted:`), or an AI-agent author → `ai-assisted`
4. Author e-mail (or GitHub noreply handle) resolves to roster role `editor` → `human-editor`
5. …to role `translator` → `human-translator`. A roster member named in a `Co-authored-by:` trailer on an otherwise non-roster commit is credited (the path for reviewers without accounts).
6. Commit precedes the translation moment → `seed`
7. Anything else → `ai-assisted` (default-deny: a maintainer reviewing with AI assistance is not human signal)

## The translation moment

Strategy `script-jump`: the first revision at which the document's ratio of target-script characters (whitespace removed) reaches `prose.threshold` (default 5%). This is computed from content, not commit messages, and survives generic PR titles.

Strategy `state-file`: the first revision of the document's per-document state file (`machine.state_dir/<name>.yml`, renames followed) marks the moment — the engine's own record that it created the translation, available in repositories that are engine-managed from the start. When the engine landed the document and its state file as adjacent single-file commits, the moment is the last document revision not after the state file's creation. A document with no state file is untranslated under this strategy, and the scan log says so.

Under both strategies, documents whose history defeats the rule (a discarded draft, a regenerated translation, a missing state file) take a per-document override in `baseline.overrides`.

## Prose-only measurement

All stock metrics count **lines containing the target script**. On raw lines most of a translated repository blames to the untranslated seed — code, maths, directives and blank lines pass through translation unchanged — so the prose restriction is what makes "whose words does the reader see" honest. For Latin-script targets no script signal exists; the planned `source-diff` strategy will define prose as lines differing from the aligned source.

## Metrics

| | Metric | Definition |
|---|---|---|
| S1 | Composition | prose lines at HEAD by tier of last author (`git blame -w -M`) |
| S2 | Baseline survival | S1's `ai-initial` share; plus `difflib` similarity of the initial translation to HEAD |
| S3 | Derived review state | `machine-only` (no prose-changing roster commit since translation) → `human-touched` → `audit-stale` (≥ `review_state.stale_after_syncs` machine syncs since the last touch) |
| S4 | Freshness | source commits since the state file's `source-sha` (only with a source repo and state directory) |
| F1 | Human churn | prose lines added + deleted by roster-tier commits, per document — also in changed characters; normalise by machine-delivered lines or characters and stratify by engine version downstream |
| F2 | Overwrites | for each `ai-sync` commit, the prose lines it deleted, blamed at the parent, counted by prior tier |
| F3 | Edit categories | pair counts by category and taxonomy bucket |
| F4 | Recurring substitutions | short `(before, after)` replacements inside terminology / fluency / width pairs, counted across the corpus |
| F5 | Time to first human touch | days from the translation moment to the first prose-changing roster commit |
| F6 | Human-review coverage | documents with a human touch / translated documents |

## Known limits

- **Squash merges** hide human work done inside a machine-drafted PR. `ai-initial` means *as landed*; human effort is a lower bound.
- **Last-toucher blame** credits a whole line to whoever changed one character of it. Human shares are an upper bound at line granularity; churn is therefore also reported in changed characters (`chars_changed` per pair, `prose_chars_added`/`prose_chars_deleted` per commit, `prose_char_churn_by_tier` per document), where a one-character fix counts as one character. Counts come from `SequenceMatcher` opcodes over the paired lines' raw text; unpaired additions and deletions count the full line.
- **Line pairing** inside rewritten paragraphs is heuristic (similarity-matched within a hunk). Category counts are indicative.
- **Identity** is resolved by e-mail and GitHub noreply handle only; display names are ignored. Unresolved authors fall to `ai-assisted` and should be reviewed in `commits.jsonl`.
- **Pre-engine history** has no recorded engine version. Stratify flow metrics by version downstream and label the pre-engine stratum as such; do not read its rates as the shipping engine's.

## Provenance of the method

Ported from the 2026-08-04 study of QuantEcon/lecture-intro.zh-cn ([report and scripts](https://github.com/QuantEcon/project-translation/tree/main/research/2026-08-04-intro-zh-cn-lifecycle-from-git)); `tests/test_regression.py` reproduces its per-lecture numbers on the pinned checkout. Two deliberate departures: *who* and *what* are separate axes (the study's `human_technical` mixed them), and a "human touch" is any prose-changing roster commit rather than a commit whose subject reads as translation editing — so time-to-first-touch is shorter than the study's 149-day median by design.
