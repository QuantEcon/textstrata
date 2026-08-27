"""The scan: one pass over a target repository producing the run's artefacts.

    run.json           what was scanned (repo, HEAD, config) and corpus totals
    commits.jsonl      every (document, commit) with its tier and prose churn
    documents.json     per-document stock and flow metrics
    pairs.jsonl        before/after line pairs from non-machine commits, categorised
    substitutions.csv  recurring short replacements (glossary candidates)
    overwrites.json    prose lines each ai-sync commit replaced, by the prior tier
"""
from __future__ import annotations

import csv
import difflib
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .config import TIERS, Config, load_overrides
from .git import (
    Commit,
    GitError,
    blame_lines,
    commit_meta,
    diff_u0,
    file_history,
    head_sha,
    log_range,
    ls_files,
    show,
)
from .pairs import CATEGORY_MAP, categorise, changed_chars, line_pairs, mine_substitutions, parse_hunks
from .prose import Prose
from .roster import Roster
from .tiers import HUMAN_TIERS, TierContext

PR_RE = re.compile(r"#(\d+)")


@dataclass
class DocResult:
    path: str
    translated: bool
    translation_sha: str | None = None
    translation_date: str | None = None
    n_commits: int = 0
    lines_head: int = 0
    prose_lines_head: int = 0
    composition: dict[str, int] = field(default_factory=dict)        # prose lines by tier at HEAD
    composition_pct: dict[str, float] = field(default_factory=dict)
    baseline_survival_pct: float | None = None                       # == composition_pct[ai-initial]
    similarity_initial_head: float | None = None
    commits_by_tier: dict[str, int] = field(default_factory=dict)
    prose_churn_by_tier: dict[str, int] = field(default_factory=dict)  # prose lines added+deleted
    prose_char_churn_by_tier: dict[str, int] = field(default_factory=dict)  # prose characters added+deleted
    first_human_touch: str | None = None
    last_human_touch: str | None = None
    days_to_first_human_touch: int | None = None
    syncs_since_last_human_touch: int = 0
    review_state: str = "machine-only"                               # machine-only | human-touched | audit-stale
    human_ids: list[str] = field(default_factory=list)               # roster ids (for planning, not publication)
    source: dict = field(default_factory=dict)                       # staleness vs source repo


def _days(a: str, b: str) -> int:
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days


def read_state(repo: Path, state_dir: str | None, doc: str) -> dict[str, str]:
    """action-translation style per-document state file: flat `key: value` YAML."""
    if not state_dir:
        return {}
    p = repo / state_dir / (Path(doc).name + ".yml")
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def translation_moment(cfg: Config, repo: Path, prose: Prose, f: str,
                       hist: list[Commit], log=sys.stderr) -> tuple[str | None, str | None]:
    """The document's translation moment under the configured baseline strategy.

    A `baseline.overrides` entry wins regardless of strategy: it is the reviewed
    correction for a document whose history defeats the rule.
    """
    forced = cfg.baseline.overrides.get(f)
    if forced:
        t_sha, t_date = None, None
        for c in hist:
            if c.sha.startswith(forced):
                t_sha, t_date = c.sha, c.date
        return t_sha, t_date
    if cfg.baseline.strategy == "state-file":
        return _state_file_moment(cfg, repo, f, hist, log)
    for c in hist:  # script-jump
        if prose.is_translated(show(repo, c.sha, c.path)):
            return c.sha, c.date
    return None, None


def _state_file_moment(cfg: Config, repo: Path, f: str, hist: list[Commit],
                       log) -> tuple[str | None, str | None]:
    state_path = cfg.machine.state_dir.rstrip("/") + "/" + Path(f).name + ".yml"  # type: ignore[union-attr]
    st_hist = file_history(repo, state_path)
    if not st_hist:
        print(f"  {f}: no state file at {state_path}; untranslated under state-file "
              "(a baseline.overrides entry corrects this)", file=log)
        return None, None
    first = st_hist[0]
    for c in hist:
        if c.sha == first.sha:
            return c.sha, c.date
    # the engine sometimes lands a document and its state file as adjacent
    # single-file commits; the document revision the state file describes is
    # then the last one not after the state file's creation
    created = datetime.fromisoformat(first.date)
    prior = [c for c in hist if datetime.fromisoformat(c.date) <= created]
    c = prior[-1] if prior else hist[0]
    return c.sha, c.date


def scan(cfg: Config, out_dir: Path, log=sys.stderr) -> dict:
    repo = cfg.repo
    prose = Prose(cfg.prose)
    roster = Roster.load(cfg.resolve(cfg.people.roster))
    ctx = TierContext(cfg, roster, load_overrides(cfg))
    out_dir.mkdir(parents=True, exist_ok=True)
    head = head_sha(repo)
    files = ls_files(repo, cfg.files)
    print(f"{cfg.name}: {len(files)} documents at {head[:7]}", file=log)

    commit_rows: list[dict] = []
    docs: dict[str, DocResult] = {}
    tier_of: dict[tuple[str, str], str] = {}
    histories: dict[str, list[Commit]] = {}

    # ---- pass 1: history, translation moment, tiers ---------------------------------
    for f in files:
        hist = file_history(repo, f)
        histories[f] = hist
        t_sha, t_date = translation_moment(cfg, repo, prose, f, hist, log)
        before = True
        for c in hist:
            if c.sha == t_sha:
                before = False
            # trailers are needed for rules 3 and 5 (cached per commit)
            c.trailers = commit_meta(repo, c.sha).trailers
            tier = ctx.classify(c, t_sha, before and c.sha != t_sha)
            tier_of[(f, c.sha)] = tier
            commit_rows.append({"document": f, "sha": c.sha, "author": c.author, "email": c.email,
                                "date": c.date, "subject": c.subject, "tier": tier,
                                "adds": c.adds, "dels": c.dels, "prose_adds": 0, "prose_dels": 0,
                                "prose_chars_added": 0, "prose_chars_deleted": 0})
        d = DocResult(path=f, translated=t_sha is not None, translation_sha=t_sha,
                      translation_date=t_date, n_commits=len(hist))
        docs[f] = d
        print(f"  {f}: {len(hist)} commits, translated {str(t_date)[:10]}", file=log)

    def tier_for(f: str, sha: str) -> str:
        t = tier_of.get((f, sha))
        if t is None:
            d = docs[f]
            t = ctx.classify_sha(repo, sha, d.translation_sha, d.translation_date)
            tier_of[(f, sha)] = t
        return t

    # ---- pass 2: blame, similarity, churn, pairs, overwrites ----------------------------
    pairs_out: list[dict] = []
    subs: Counter = Counter()
    sub_examples: dict[tuple[str, str], tuple[str, str]] = {}
    overwrites: dict[str, dict] = {}
    rows_by_key = {(r["document"], r["sha"]): r for r in commit_rows}

    for f, d in docs.items():
        if not d.translated:
            continue
        hist = histories[f]
        # composition at HEAD, prose lines only
        comp: Counter = Counter()
        head_text = show(repo, "HEAD", f)
        d.lines_head = head_text.count("\n")
        for sha, _ln, text in blame_lines(repo, "HEAD", f):
            if prose.is_prose(text):
                comp[tier_for(f, sha)] += 1
        d.prose_lines_head = sum(comp.values())
        d.composition = dict(comp)
        tot = d.prose_lines_head or 1
        d.composition_pct = {k: round(100 * v / tot, 1) for k, v in comp.items()}
        d.baseline_survival_pct = d.composition_pct.get("ai-initial", 0.0)
        # similarity initial -> HEAD
        t_path = next((c.path for c in hist if c.sha == d.translation_sha), f)
        init_lines = show(repo, d.translation_sha, t_path).splitlines()  # type: ignore[arg-type]
        head_lines = head_text.splitlines()
        if init_lines and head_lines:
            d.similarity_initial_head = round(
                difflib.SequenceMatcher(None, init_lines, head_lines).ratio(), 4)
        # commits after the translation moment
        post = [c for c in hist if d.translation_date and c.date > d.translation_date]
        d.commits_by_tier = dict(Counter(tier_of[(f, c.sha)] for c in post))
        # per-commit diffs: prose churn, pairs, overwrites
        churn: Counter = Counter()
        char_churn: Counter = Counter()
        for c in post:
            tier = tier_of[(f, c.sha)]
            try:
                hunks = parse_hunks(diff_u0(repo, c.sha, c.path))
            except GitError:
                continue
            p_adds = sum(1 for h in hunks for ln in h.new if prose.is_prose(ln))
            p_dels = sum(1 for h in hunks for ln in h.old if prose.is_prose(ln))
            churn[tier] += p_adds + p_dels
            # and in characters, so a one-character fix is not credited with the whole line
            paired = [line_pairs(h, prose) for h in hunks]
            pc_adds = pc_dels = 0
            for pairs, adds, dels in paired:
                for _ln, o, n in pairs:
                    if prose.is_prose(o) or prose.is_prose(n):
                        d_chars, a_chars = changed_chars(o, n)
                        pc_dels += d_chars
                        pc_adds += a_chars
                pc_adds += sum(len(x) for x in adds if prose.is_prose(x))
                pc_dels += sum(len(x) for _ln, x in dels if prose.is_prose(x))
            char_churn[tier] += pc_adds + pc_dels
            row = rows_by_key[(f, c.sha)]
            row["prose_adds"], row["prose_dels"] = p_adds, p_dels
            row["prose_chars_added"], row["prose_chars_deleted"] = pc_adds, pc_dels
            pr = PR_RE.search(c.subject)
            if tier == "ai-sync":
                # what did the machine replace? blame the deleted prose lines at the parent
                try:
                    parent_blame = {ln: sha for sha, ln, _t in blame_lines(repo, f"{c.sha}^", c.path)}
                except GitError:
                    parent_blame = {}
                prior: Counter = Counter()
                examples: list[dict] = []
                for h in hunks:
                    for i, old in enumerate(h.old):
                        if not prose.is_prose(old):
                            continue
                        osha = parent_blame.get(h.ostart + i)
                        if not osha:
                            continue
                        pt = tier_for(f, osha)
                        prior[pt] += 1
                        if pt in HUMAN_TIERS and len(examples) < 50:
                            examples.append({"line": h.ostart + i, "before": old.strip()[:160],
                                             "after": (h.new[i].strip()[:160] if i < len(h.new) else "")})
                if prior:
                    overwrites.setdefault(c.sha, {"date": c.date, "subject": c.subject, "documents": {}})
                    overwrites[c.sha]["documents"][f] = {"prose_deleted_by_prior_tier": dict(prior),
                                                         "examples": examples}
                continue
            if tier == "seed":
                continue
            for pairs, adds, dels in paired:
                for _ln, o, n in pairs:
                    if o.strip() == n.strip():
                        continue
                    cat, sim = categorise(o, n, prose)
                    d_chars, a_chars = changed_chars(o, n)
                    pairs_out.append({"document": f, "sha": c.sha[:8], "date": c.date[:10],
                                      "tier": tier, "pr": pr.group(1) if pr else None,
                                      "category": cat, "taxonomy": CATEGORY_MAP[cat],
                                      "similarity": round(sim, 3), "chars_changed": d_chars + a_chars,
                                      "before": o, "after": n})
                    if tier in HUMAN_TIERS and cat in ("terminology", "punctuation-width", "fluency"):
                        mine_substitutions(o, n, prose, subs, sub_examples)
                for n in adds:
                    if n.strip():
                        pairs_out.append({"document": f, "sha": c.sha[:8], "date": c.date[:10],
                                          "tier": tier, "pr": pr.group(1) if pr else None,
                                          "category": "addition", "taxonomy": "omission",
                                          "similarity": 0.0, "chars_changed": len(n),
                                          "before": "", "after": n})
                for _ln, o in dels:
                    if o.strip():
                        pairs_out.append({"document": f, "sha": c.sha[:8], "date": c.date[:10],
                                          "tier": tier, "pr": pr.group(1) if pr else None,
                                          "category": "deletion", "taxonomy": "omission",
                                          "similarity": 0.0, "chars_changed": len(o),
                                          "before": o, "after": ""})
        d.prose_churn_by_tier = dict(churn)
        d.prose_char_churn_by_tier = dict(char_churn)
        # a human "touch" is a roster-tier commit that changed prose (technical fixes do not count)
        humans = [c for c in post if tier_of[(f, c.sha)] in HUMAN_TIERS
                  and (rows_by_key[(f, c.sha)]["prose_adds"] + rows_by_key[(f, c.sha)]["prose_dels"])
                  >= cfg.review_state.min_prose_lines]
        if humans:
            d.first_human_touch = min(c.date for c in humans)
            d.last_human_touch = max(c.date for c in humans)
            d.days_to_first_human_touch = _days(d.translation_date, d.first_human_touch)  # type: ignore[arg-type]
            ids = set()
            for c in humans:
                person = roster.resolve_email(c.email)
                ids.add(person.id if person else c.author)
            d.human_ids = sorted(ids)
            d.syncs_since_last_human_touch = sum(
                1 for c in post if tier_of[(f, c.sha)] == "ai-sync" and c.date > d.last_human_touch)
            d.review_state = ("audit-stale"
                              if d.syncs_since_last_human_touch >= cfg.review_state.stale_after_syncs
                              else "human-touched")
        # staleness against the source repository
        src_repo = cfg.resolve(cfg.source.repo)
        if src_repo is not None:
            st = read_state(repo, cfg.machine.state_dir, f)
            d.source = {"source_sha": st.get("source-sha"), "model": st.get("model"),
                        "synced_at": st.get("synced-at"), "mode": st.get("mode"),
                        "tool_version": st.get("tool-version"), "pending_commits": None}
            if st.get("source-sha"):
                try:
                    pend = log_range(src_repo, f"{st['source-sha']}..HEAD", f)
                    d.source["pending_commits"] = len(pend)
                    d.source["pending_subjects"] = [s for _h, _d, s in pend][:5]
                except GitError:
                    pass

    # ---- write artefacts ----------------------------------------------------------------
    translated = [d for d in docs.values() if d.translated]
    corpus: Counter = Counter()
    for d in translated:
        corpus.update(d.composition)
    tot = sum(corpus.values()) or 1
    run = {
        "textstrata": __version__,
        "config": cfg.name,
        "repo": str(repo),
        "head": head,
        "scanned_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "documents": len(files),
        "translated": len(translated),
        "prose_lines": sum(corpus.values()),
        "composition": dict(corpus),
        "composition_pct": {k: round(100 * v / tot, 1) for k, v in corpus.items()},
        "review_state": dict(Counter(d.review_state for d in translated)),
        "pairs": len(pairs_out),
        "pair_categories": dict(Counter(p["category"] for p in pairs_out)),
        "recurring_substitutions": sum(1 for c in subs.values() if c >= 2),
        "tiers": list(TIERS),
    }
    (out_dir / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
    with (out_dir / "commits.jsonl").open("w", encoding="utf-8") as fh:
        for r in commit_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out_dir / "documents.json").write_text(
        json.dumps({f: asdict(d) for f, d in docs.items()}, ensure_ascii=False, indent=1), encoding="utf-8")
    with (out_dir / "pairs.jsonl").open("w", encoding="utf-8") as fh:
        for p in pairs_out:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    with (out_dir / "substitutions.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["before", "after", "count", "example_before", "example_after"])
        for (a, b), n in subs.most_common():
            if n >= 2:
                ex = sub_examples.get((a, b), ("", ""))
                w.writerow([a, b, n, ex[0], ex[1]])
    (out_dir / "overwrites.json").write_text(json.dumps(overwrites, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    print(f"prose lines {run['prose_lines']}: " + ", ".join(
        f"{k} {v}%" for k, v in sorted(run["composition_pct"].items())), file=log)
    print(f"pairs {run['pairs']}; recurring substitutions {run['recurring_substitutions']}; "
          f"review state {run['review_state']}", file=log)
    return run
