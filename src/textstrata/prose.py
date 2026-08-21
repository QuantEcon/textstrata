"""What counts as translated prose.

Strategy `script`: a line is prose if it contains characters of the target
script; a document's translation moment is the first revision whose script
ratio exceeds the threshold. Code, math, directives and blank lines fall out
by construction — which is what makes attribution shares honest (on raw lines
most of a translated repo blames to the untranslated seed).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import ProseConfig

_WS = re.compile(r"\s")


@dataclass
class Prose:
    cfg: ProseConfig

    def __post_init__(self) -> None:
        self.pat = self.cfg.pattern()
        self._punct = str.maketrans(self.cfg.punctuation_map) if self.cfg.punctuation_map else None

    def ratio(self, text: str) -> float:
        t = _WS.sub("", text)
        return (len(self.pat.findall(t)) / len(t)) if t else 0.0

    def is_prose(self, line: str) -> bool:
        return bool(self.pat.search(line))

    def is_translated(self, text: str) -> bool:
        return self.ratio(text) >= self.cfg.threshold

    def normalise(self, s: str) -> str:
        """Strip whitespace and collapse punctuation-width variants (for width-only edits)."""
        if self._punct is not None:
            s = s.translate(self._punct)
        return _WS.sub("", s)
