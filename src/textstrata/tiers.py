"""Provenance tiers — *who* made a change — assigned per commit by precedence.

    1. bot author (other than a declared AI agent), or the
       machine's sync signature                                 -> ai-sync
    2. the document's translation moment                       -> ai-initial
       (per-commit overrides are applied here: they may not reclassify machine
        or baseline commits)
    3. disclosed AI assistance: trailer, or an AI-agent author  -> ai-assisted
    4. author resolves to roster role `editor`                  -> human-editor
    5. author resolves to roster role `translator`              -> human-translator
       (a roster member named in a Co-authored-by trailer on an otherwise
        non-roster commit is credited — the transcription path)
    6. commit precedes the translation moment                   -> seed
    7. anything else, the maintainer included                   -> ai-assisted (default-deny)

Content rules (1–2) outrank author rules (3–7): the translation moment is AI
regardless of who committed it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .git import Commit, changed_paths, commit_meta
from .roster import Roster

HUMAN_TIERS = ("human-editor", "human-translator")


@dataclass
class TierContext:
    cfg: Config
    roster: Roster
    overrides: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        m = self.cfg.machine
        self._bots = [re.compile(p, re.IGNORECASE) for p in m.bots]
        self._sync = [re.compile(p, re.IGNORECASE) for p in m.sync]
        self._agents = [re.compile(p, re.IGNORECASE) for p in self.cfg.disclosure.authors]
        self._trailers = {t.lower() for t in self.cfg.disclosure.trailers}
        self._roles = dict(self.cfg.people.roles)

    # --- rule 1 -----------------------------------------------------------------
    def is_bot(self, c: Commit) -> bool:
        # declared AI agents (rule 3) are not "the machine": their commits are AI-assisted, not sync
        if self.is_agent(c):
            return False
        return any(p.search(c.author) or p.search(c.email) for p in self._bots)

    def is_sync(self, c: Commit) -> bool:
        if not any(p.search(c.subject) for p in self._sync):
            return False
        m = self.cfg.machine
        if m.state_dir and m.require_state_change:
            prefix = m.state_dir.rstrip("/") + "/"
            return any(p.startswith(prefix) for p in changed_paths(str(self.cfg.repo), c.sha))
        return True

    # --- rule 3 -----------------------------------------------------------------
    def is_agent(self, c: Commit) -> bool:
        return any(p.search(c.author) or p.search(c.email) for p in self._agents)

    def discloses_ai(self, c: Commit) -> bool:
        return any(k in self._trailers for k in c.trailers)

    # --- rules 4–5 --------------------------------------------------------------
    def role_tier(self, c: Commit) -> str | None:
        person = self.roster.resolve_email(c.email)
        if person is None:
            for val in c.trailers.get("co-authored-by", []):
                person = self.roster.resolve_trailer(val)
                if person is not None:
                    break
        if person is None:
            return None
        return self._roles.get(person.role)

    def override_for(self, c: Commit) -> str | None:
        for prefix, tier in self.overrides.items():
            if c.sha.startswith(prefix):
                return tier
        return None

    def classify(self, c: Commit, translation_sha: str | None, before_translation: bool) -> str:
        if self.is_bot(c) or self.is_sync(c):
            return "ai-sync"
        if translation_sha and c.sha == translation_sha:
            return "ai-initial"
        ov = self.override_for(c)
        if ov is not None:
            return ov
        if self.is_agent(c) or self.discloses_ai(c):
            return "ai-assisted"
        tier = self.role_tier(c)
        if tier is not None:
            return tier
        if before_translation:
            return "seed"
        return "ai-assisted"

    def classify_sha(self, repo: Path, sha: str, translation_sha: str | None,
                     translation_date: str | None) -> str:
        """Classify a commit that is not in the document's followed history (e.g. a merge)."""
        c = commit_meta(repo, sha)
        before = bool(translation_date and c.date < translation_date)
        return self.classify(c, translation_sha, before)
