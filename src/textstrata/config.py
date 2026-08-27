"""Configuration: one YAML file per target repository.

Everything repository- or program-specific lives here — which script marks
translated prose, how machine commits are recognised, where the people roster
is, which tiers the roster roles map to — so the analysis modules stay generic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Unicode ranges per script. `re` has no \p{Script=...}, so ranges are spelled out.
SCRIPTS: dict[str, str] = {
    "Han": "㐀-䶿一-鿿豈-﫿",
    "Arabic": "؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿",
    "Malayalam": "ഀ-ൿ",
    "Devanagari": "ऀ-ॿ",
    "Cyrillic": "Ѐ-ӿ",
    "Greek": "Ͱ-Ͽ",
    "Hangul": "가-힯ᄀ-ᇿ",
    "Hiragana": "぀-ゟ",
    "Katakana": "゠-ヿ",
}

TIERS = ("ai-sync", "ai-initial", "ai-assisted", "human-editor", "human-translator", "seed")

# Full-width punctuation normalisation used to detect width-only edits (Han scripts).
HAN_PUNCT_MAP: dict[str, str] = {
    ",": "，", ".": "。", "(": "（", ")": "）", ":": "：", ";": "；", "?": "？", "!": "！",
    '"': "", "“": "", "”": "", "'": "", "‘": "", "’": "", "、": "，", "《": "", "》": "",
}


class ConfigError(ValueError):
    pass


@dataclass
class ProseConfig:
    strategy: str = "script"            # script | source-diff (planned)
    script: str | None = "Han"
    script_regex: str | None = None     # overrides `script`
    threshold: float = 0.05             # ratio that marks the translation moment
    punctuation_map: dict[str, str] = field(default_factory=dict)

    def pattern(self) -> re.Pattern[str]:
        if self.script_regex:
            return re.compile(self.script_regex)
        if self.script not in SCRIPTS:
            raise ConfigError(f"unknown script {self.script!r}; known: {sorted(SCRIPTS)}")
        return re.compile(f"[{SCRIPTS[self.script]}]")


@dataclass
class BaselineConfig:
    strategy: str = "script-jump"       # script-jump | state-file
    overrides: dict[str, str] = field(default_factory=dict)   # file -> sha prefix


@dataclass
class MachineConfig:
    bots: list[str] = field(default_factory=lambda: [r"\[bot\]", r"dependabot", r"github-actions"])
    sync: list[str] = field(default_factory=list)             # subject regexes
    state_dir: str | None = None                              # e.g. .translate/state
    require_state_change: bool = False                        # sync must also touch state_dir


@dataclass
class DisclosureConfig:
    trailers: list[str] = field(default_factory=lambda: ["AI-Assisted"])
    authors: list[str] = field(default_factory=lambda: [r"copilot-swe-agent"])   # AI agents


@dataclass
class PeopleConfig:
    roster: str | None = None
    roles: dict[str, str] = field(default_factory=lambda: {
        "editor": "human-editor", "translator": "human-translator"})


@dataclass
class ReviewStateConfig:
    stale_after_syncs: int = 3          # ai-sync commits since last human touch -> audit-stale
    min_prose_lines: int = 1            # prose lines a roster commit must change to count as a touch


@dataclass
class SourceConfig:
    repo: str | None = None
    files: str | None = None            # defaults to target `files`


@dataclass
class Config:
    name: str
    repo: Path
    files: str = "lectures/*.md"
    source: SourceConfig = field(default_factory=SourceConfig)
    prose: ProseConfig = field(default_factory=ProseConfig)
    baseline: BaselineConfig = field(default_factory=BaselineConfig)
    machine: MachineConfig = field(default_factory=MachineConfig)
    disclosure: DisclosureConfig = field(default_factory=DisclosureConfig)
    people: PeopleConfig = field(default_factory=PeopleConfig)
    review_state: ReviewStateConfig = field(default_factory=ReviewStateConfig)
    overrides_file: str | None = None   # per-commit tier overrides (sha prefix -> tier)
    base_dir: Path = field(default_factory=Path)

    def resolve(self, p: str | None) -> Path | None:
        if p is None:
            return None
        path = Path(p).expanduser()
        return path if path.is_absolute() else (self.base_dir / path).resolve()


def _sub(cls: type, data: dict[str, Any] | None, name: str):
    data = dict(data or {})
    fields = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
    unknown = set(data) - fields
    if unknown:
        raise ConfigError(f"{name}: unknown keys {sorted(unknown)}")
    return cls(**data)


def load_config(path: str | Path) -> Config:
    path = Path(path).expanduser().resolve()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    for key in ("name", "repo"):
        if key not in raw:
            raise ConfigError(f"{path}: missing required key {key!r}")
    known = {"name", "repo", "files", "source", "prose", "baseline", "machine",
             "disclosure", "people", "review_state", "overrides"}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"{path}: unknown keys {sorted(unknown)}")
    prose = _sub(ProseConfig, raw.get("prose"), "prose")
    if prose.strategy == "script" and not prose.punctuation_map and prose.script == "Han":
        prose.punctuation_map = dict(HAN_PUNCT_MAP)
    if prose.strategy not in ("script", "source-diff"):
        raise ConfigError(f"prose.strategy must be script or source-diff, got {prose.strategy!r}")
    if prose.strategy == "source-diff":
        raise ConfigError("prose.strategy source-diff is planned but not implemented (Stage 2)")
    baseline = _sub(BaselineConfig, raw.get("baseline"), "baseline")
    if baseline.strategy not in ("script-jump", "state-file"):
        raise ConfigError(f"baseline.strategy must be script-jump or state-file, got {baseline.strategy!r}")
    machine = _sub(MachineConfig, raw.get("machine"), "machine")
    if baseline.strategy == "state-file" and not machine.state_dir:
        raise ConfigError("baseline.strategy state-file requires machine.state_dir")
    cfg = Config(
        name=str(raw["name"]),
        repo=Path(raw["repo"]),
        files=str(raw.get("files", "lectures/*.md")),
        source=_sub(SourceConfig, raw.get("source"), "source"),
        prose=prose,
        baseline=baseline,
        machine=machine,
        disclosure=_sub(DisclosureConfig, raw.get("disclosure"), "disclosure"),
        people=_sub(PeopleConfig, raw.get("people"), "people"),
        review_state=_sub(ReviewStateConfig, raw.get("review_state"), "review_state"),
        overrides_file=raw.get("overrides"),
        base_dir=path.parent,
    )
    cfg.repo = cfg.resolve(str(cfg.repo))  # type: ignore[assignment]
    if not (cfg.repo / ".git").exists():
        raise ConfigError(f"repo {cfg.repo} is not a git checkout")
    for role, tier in cfg.people.roles.items():
        if tier not in TIERS:
            raise ConfigError(f"people.roles.{role}: unknown tier {tier!r}; known: {TIERS}")
    return cfg


def load_overrides(cfg: Config) -> dict[str, str]:
    """Per-commit tier overrides: {sha_prefix: tier}. A reviewed data file, not code."""
    p = cfg.resolve(cfg.overrides_file)
    if p is None:
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    entries = raw.get("overrides", raw) if isinstance(raw, dict) else {}
    out: dict[str, str] = {}
    for sha, val in entries.items():
        tier = val["tier"] if isinstance(val, dict) else val
        if tier not in TIERS:
            raise ConfigError(f"override {sha}: unknown tier {tier!r}")
        out[str(sha)] = tier
    return out
