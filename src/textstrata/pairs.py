"""Change categories — *what* kind of change — from before/after line pairs.

A commit's `-U0` diff is split into hunks, old and new lines are paired within
each hunk by similarity, and every pair is categorised by a deterministic
string rule. The rule's buckets map onto the flywheel taxonomy (terminology /
accuracy / fluency / style / formatting / omission) via CATEGORY_MAP; accuracy
cannot be separated from fluency by a string rule and is left to adjudication.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass

from .prose import Prose

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
CODEISH = re.compile(r"^\s*(import |from |def |class |plt\.|ax\.|fig|np\.|pd\.|@|#|`{3}|\}\}|\{\{)|[=\[\]]")
PUNCT_ONLY = re.compile(r"[\d\s.,，。%$()（）:：;；*#\-—>]*")

CATEGORIES = ("terminology", "fluency", "retranslation", "addition", "deletion",
              "punctuation-width", "code-or-markup", "localise-code-label")

# mechanical bucket -> flywheel taxonomy
CATEGORY_MAP = {
    "terminology": "terminology",
    "fluency": "fluency",            # accuracy is a subset, split only by adjudication
    "retranslation": "fluency",
    "addition": "omission",
    "deletion": "omission",
    "punctuation-width": "style",
    "code-or-markup": "formatting",
    "localise-code-label": "formatting",
}

SHORT = 14   # max chars for a replacement to count as a word-choice edit


@dataclass
class Hunk:
    ostart: int
    nstart: int
    old: list[str]
    new: list[str]


def parse_hunks(diff_text: str) -> list[Hunk]:
    hunks: list[Hunk] = []
    cur: Hunk | None = None
    for line in diff_text.splitlines():
        m = HUNK.match(line)
        if m:
            cur = Hunk(int(m.group(1)), int(m.group(3)), [], [])
            hunks.append(cur)
        elif cur is not None and line.startswith("-") and not line.startswith("---"):
            cur.old.append(line[1:])
        elif cur is not None and line.startswith("+") and not line.startswith("+++"):
            cur.new.append(line[1:])
    return hunks


def categorise(old: str, new: str, prose: Prose) -> tuple[str, float]:
    o_p, n_p = prose.is_prose(old), prose.is_prose(new)
    sm = difflib.SequenceMatcher(None, old, new)
    sim = sm.ratio()
    if not o_p and n_p and CODEISH.search(old):
        return "localise-code-label", sim
    if not o_p and not n_p:
        return "code-or-markup", sim
    if prose.normalise(old) == prose.normalise(new):
        return "punctuation-width", sim
    ops = sm.get_opcodes()
    reps = [(old[i1:i2], new[j1:j2]) for t, i1, i2, j1, j2 in ops if t == "replace"]
    ins = [new[j1:j2] for t, i1, i2, j1, j2 in ops if t == "insert"]
    dels = [old[i1:i2] for t, i1, i2, j1, j2 in ops if t == "delete"]
    if (sim >= 0.6 and reps
            and all(len(a) <= SHORT and len(b) <= SHORT for a, b in reps)
            and all(len(x) <= SHORT for x in ins) and all(len(x) <= SHORT for x in dels)):
        return "terminology", sim
    if sim >= 0.35:
        return "fluency", sim
    return "retranslation", sim


def changed_chars(old: str, new: str) -> tuple[int, int]:
    """(deleted, added) character counts between paired lines, from SequenceMatcher opcodes."""
    dels = adds = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new).get_opcodes():
        if tag in ("replace", "delete"):
            dels += i2 - i1
        if tag in ("replace", "insert"):
            adds += j2 - j1
    return dels, adds


def line_pairs(h: Hunk, prose: Prose) -> tuple[list[tuple[int, str, str]], list[str], list[tuple[int, str]]]:
    """Pair old/new lines within a hunk. Returns (pairs[(old_lineno, old, new)], adds, dels[(old_lineno, old)])."""
    old, new = h.old, h.new
    if not old:
        return [], list(new), []
    if not new:
        return [], [], [(h.ostart + i, o) for i, o in enumerate(old)]
    sm = difflib.SequenceMatcher(None, [prose.normalise(x)[:60] for x in old],
                                 [prose.normalise(x)[:60] for x in new])
    pairs: list[tuple[int, str, str]] = []
    adds: list[str] = []
    dels: list[tuple[int, str]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "equal"):
            o_blk, n_blk = old[i1:i2], new[j1:j2]
            for k in range(max(len(o_blk), len(n_blk))):
                o = o_blk[k] if k < len(o_blk) else None
                n = n_blk[k] if k < len(n_blk) else None
                if o is not None and n is not None:
                    pairs.append((h.ostart + i1 + k, o, n))
                elif n is not None:
                    adds.append(n)
                elif o is not None:
                    dels.append((h.ostart + i1 + k, o))
        elif tag == "insert":
            adds.extend(new[j1:j2])
        elif tag == "delete":
            dels.extend((h.ostart + i, old[i]) for i in range(i1, i2))
    return pairs, adds, dels


def mine_substitutions(old: str, new: str, prose: Prose, counter: Counter,
                       examples: dict[tuple[str, str], tuple[str, str]]) -> None:
    """Short (before, after) replacements inside a pair — glossary candidates when they recur."""
    sm = difflib.SequenceMatcher(None, old, new)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace":
            continue
        a, b = old[i1:i2].strip(), new[j1:j2].strip()
        if not (0 < len(a) <= SHORT and 0 < len(b) <= SHORT):
            continue
        if not (prose.is_prose(a) or prose.is_prose(b)):
            continue
        if PUNCT_ONLY.fullmatch(a):
            continue
        counter[(a, b)] += 1
        examples.setdefault((a, b), (old.strip()[:120], new.strip()[:120]))
