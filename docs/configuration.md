# Configuration

One YAML file per target repository. Relative paths resolve against the config file's directory.

```yaml
name: lecture-intro.zh-cn          # label used in artefacts
repo: ../repos/lecture-intro.zh-cn # local git checkout to scan
files: "lectures/*.md"             # documents (git ls-files glob)
source:
  repo: ../repos/lecture-python-intro   # optional: the source-language checkout (freshness)
prose:
  strategy: script                 # script | source-diff (planned)
  script: Han                      # Han, Arabic, Malayalam, Devanagari, Cyrillic, Greek, Hangul, Hiragana, Katakana
  # script_regex: "[...]"          # custom character class instead of `script`
  threshold: 0.05                  # script ratio that marks the translation moment
  # punctuation_map: {",": "，"}   # width normalisation; defaults to a Han map for script: Han
baseline:
  strategy: script-jump            # script-jump | state-file (planned)
  overrides:                       # document -> sha prefix, when the first script-bearing revision is wrong
    lectures/long_run_growth.md: cd9808c
machine:
  bots: ['\[bot\]', 'dependabot', 'github-actions']     # author/e-mail regexes (AI agents excluded, see disclosure)
  sync: ['\[translation-sync\]', '\[action-translation\]', 'resync']   # subject regexes
  state_dir: .translate/state      # optional: per-document state files (freshness, provenance)
  require_state_change: false      # when true, a sync must also touch state_dir to count
disclosure:
  trailers: [AI-Assisted]          # commit trailers that mark AI assistance
  authors: ['copilot-swe-agent']   # AI coding agents: ai-assisted, never ai-sync
people:
  roster: ../team/reviewers.yml    # people file, see below
  roles: {editor: human-editor, translator: human-translator}
review_state:
  stale_after_syncs: 3             # machine syncs since the last human touch -> audit-stale
  min_prose_lines: 1               # prose lines a roster commit must change to count as a touch
overrides: overrides/intro-zh-cn.yml   # per-commit tier overrides (reviewed data file)
```

## People roster

```yaml
people:                       # `reviewers:` is accepted as an alias
  - id: HumphreyYang          # `handle:` is accepted as an alias
    role: editor              # mapped to a tier via people.roles
    emails: [39026988+HumphreyYang@users.noreply.github.com, u6474961@anu.edu.au]
    names: [Humphrey Yang]    # informational only; never used for resolution
```

Resolution is by e-mail, then by the handle embedded in a GitHub noreply address. Anyone not resolved is `ai-assisted` by default; list unresolved authors from `commits.jsonl` and either add them to the roster or leave them — the default-deny is deliberate.

## Per-commit overrides

```yaml
overrides:
  8b97f8a: {tier: seed, note: "English seed commit that predates translation"}
  18d9991: human-translator   # shorthand
```

Overrides apply after the machine and baseline rules (which they cannot reclassify) and before the author rules. Keep them few and annotated: every entry is a claim that the rules got a commit wrong.
