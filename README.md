# textstrata

**Git-derived metrics for machine-drafted, human-edited text.**

`textstrata` reads a repository's history and classifies every change to every document along two axes — **who** made it (a provenance tier: the machine's initial draft, a machine re-sync, disclosed AI assistance, a human editor, a human translator) and **what** kind of change it was (terminology, fluency, retranslation, formatting, punctuation width, addition/deletion) — then rolls the result up into metrics that show how a corpus is evolving:

| Metric | Question it answers |
|---|---|
| **Composition** | Of the prose a reader sees today, what share was last written by the machine, by a human editor, by a translator? |
| **Baseline survival** | How much of the original machine draft is still the skeleton? |
| **Derived review state** | Has a human ever touched this document — and is that still true after the machine's last re-sync? (`machine-only` → `human-touched` → `audit-stale`) |
| **Human churn** | How much do humans change per thousand lines the machine delivers — and is it falling release over release? |
| **Overwrites** | When the machine re-syncs, whose lines does it replace? (In the study this was built on, 68% of the prose a re-sync replaced had been written by a human editor.) |
| **Edit categories and recurring substitutions** | What do editors actually fix? Which corrections recur — i.e. belong in a glossary or a prompt rule? |

It was built for [QuantEcon](https://quantecon.org)'s machine-translated lecture series, where it measures the [action-translation](https://github.com/QuantEcon/action-translation) engine against the native editors who correct its output. Nothing in the core is specific to translation: any repository where an AI drafts text and people curate it has the same strata.

**Status: pre-alpha.** The method is established ([the study it ports](https://github.com/QuantEcon/project-translation/tree/main/research/2026-08-04-intro-zh-cn-lifecycle-from-git)); the package is being assembled. General by design, supported for QuantEcon's repositories; other users are welcome but should expect the configuration surface to move.

## How it works

1. **Translation moment.** Per document, the first revision whose target-script ratio exceeds a threshold is the machine baseline — *content* locates it, so a machine draft committed under a person's name is still classified as machine.
2. **Tiers by precedence.** Bot or machine sync signature → `ai-sync`; the translation moment → `ai-initial`; disclosed AI assistance (`AI-Assisted:` trailer, agent author) → `ai-assisted`; author resolves to a roster role → `human-editor` / `human-translator`; before the translation moment → `seed`; everything else → `ai-assisted` (default-deny). Content rules outrank author rules.
3. **Prose-only blame.** `git blame -w -M` at HEAD, restricted to lines containing the target script, so code, math, directives and blank lines don't dilute the shares.
4. **Pairs.** Each non-machine commit's `-U0` diff is split into hunks, lines are paired by similarity, and each pair is categorised by a deterministic string rule and mined for short recurring substitutions.
5. **Overwrites.** For each machine sync, the prose lines it deleted are blamed at the parent commit to find whose words were replaced.

Everything is plain `git` plumbing — no network, no model calls — and deterministic: the same inputs produce the same numbers.

## Usage

```sh
pip install textstrata            # (not yet published)
textstrata scan configs/quantecon/intro-zh-cn.yml -o out/intro-zh-cn
textstrata summary out/intro-zh-cn
```

A scan writes `run.json` (corpus totals), `documents.json` (per-document metrics), `commits.jsonl` (every document×commit with its tier and prose churn), `pairs.jsonl`, `substitutions.csv` and `overwrites.json`. Dashboards and reports consume these artefacts; `textstrata` itself renders nothing.

## Configuration

One YAML file per target repository — see [docs/configuration.md](docs/configuration.md) and the QuantEcon reference configurations in [configs/quantecon/](configs/quantecon/). The file declares what counts as prose (`script: Han | Arabic | Malayalam | …`), how machine commits are recognised (subject signatures, bot authors, an optional state directory), where the people roster lives and which roles map to which tiers, and a reviewed overrides file for the handful of commits no rule gets right.

## Limits worth knowing

- Squash merges hide human cleanup done inside a machine-drafted PR: `ai-initial` means *as landed*, so human effort is a **lower bound**.
- Blame credits the last toucher: a one-character fix claims the whole line, so human shares are an **upper bound** at line granularity. Churn is also reported in changed characters.
- Pairing lines inside rewritten paragraphs is heuristic; category counts are indicative, not exact.
- Latin-script targets (e.g. French from English) have no script signal; the `source-diff` prose strategy for them is planned, not implemented.

## Licence

MIT. © QuantEcon.
