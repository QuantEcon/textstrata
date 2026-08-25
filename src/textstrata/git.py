"""Thin, cacheable wrappers over the git commands the analysis needs.

Everything is plumbing-level and deterministic: `git log --follow --numstat`,
`git show`, `git blame --line-porcelain`, `git diff -U0`. No network.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

REC, SEP = "\x02", "\x01"


class GitError(RuntimeError):
    pass


def run(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)
    if r.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {r.stderr.decode(errors='replace')[:400]}")
    return r.stdout.decode("utf-8", errors="replace")


@dataclass
class Commit:
    sha: str
    author: str
    email: str
    date: str           # ISO 8601, author date
    subject: str
    adds: int = 0       # numstat for the followed path
    dels: int = 0
    path: str = ""      # path as of this commit (renames followed)
    body: str = ""      # lazily filled
    trailers: dict[str, list[str]] = field(default_factory=dict)

    @property
    def sha7(self) -> str:
        return self.sha[:7]


def head_sha(repo: Path) -> str:
    return run(repo, "rev-parse", "HEAD").strip()


def ls_files(repo: Path, glob: str) -> list[str]:
    return [p for p in run(repo, "ls-files", "--", glob).split("\n") if p]


def file_history(repo: Path, path: str) -> list[Commit]:
    """Oldest-first commits touching `path`, following renames, with per-file numstat."""
    out = run(repo, "log", "--follow", f"--format={REC}%H{SEP}%an{SEP}%ae{SEP}%aI{SEP}%s",
              "--numstat", "--", path)
    commits: list[Commit] = []
    cur: Commit | None = None
    for line in out.splitlines():
        if line.startswith(REC):
            sha, an, ae, date, subject = line[1:].split(SEP, 4)
            cur = Commit(sha=sha, author=an, email=ae, date=date, subject=subject, path=path)
            commits.append(cur)
        elif line.strip() and cur is not None:
            m = re.match(r"^(\d+|-)\t(\d+|-)\t(.*)$", line)
            if m:
                a, d, p = m.groups()
                cur.adds = 0 if a == "-" else int(a)
                cur.dels = 0 if d == "-" else int(d)
                if "=>" in p:
                    m2 = re.match(r"^(.*)\{(.*) => (.*)\}(.*)$", p)
                    cur.path = ((m2.group(1) + m2.group(3) + m2.group(4)).replace("//", "/")
                                if m2 else p.split(" => ")[-1].strip())
                else:
                    cur.path = p
    commits.reverse()
    return commits


@lru_cache(maxsize=4096)
def _show_cached(repo: str, sha: str, path: str) -> str:
    try:
        return run(Path(repo), "show", f"{sha}:{path}")
    except GitError:
        return ""


def show(repo: Path, sha: str, path: str) -> str:
    return _show_cached(str(repo), sha, path)


@lru_cache(maxsize=8192)
def _meta_cached(repo: str, sha: str) -> tuple[str, str, str, str, str]:
    out = run(Path(repo), "show", "-s", f"--format=%an{SEP}%ae{SEP}%aI{SEP}%s{SEP}%b", sha)
    an, ae, date, subject, body = out.split(SEP, 4)
    return an, ae, date, subject, body


TRAILER = re.compile(r"^([A-Za-z][A-Za-z-]*):\s*(.+?)\s*$", re.MULTILINE)


def commit_meta(repo: Path, sha: str) -> Commit:
    """Author, date, subject, body and parsed trailers for any commit (cached)."""
    an, ae, date, subject, body = _meta_cached(str(repo), sha)
    c = Commit(sha=sha, author=an, email=ae, date=date, subject=subject, body=body)
    c.trailers = parse_trailers(body)
    return c


def parse_trailers(body: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, val in TRAILER.findall(body or ""):
        out.setdefault(key.lower(), []).append(val)
    return out


@lru_cache(maxsize=8192)
def changed_paths(repo: Path | str, sha: str) -> tuple[str, ...]:
    out = run(Path(repo), "show", "--name-only", "--format=", sha)
    return tuple(p for p in out.split("\n") if p)


BLAME_HDR = re.compile(r"^([0-9a-f]{40}) (\d+) (\d+)")


def blame_lines(repo: Path, rev: str, path: str) -> list[tuple[str, int, str]]:
    """[(sha, final_line_no, text)] for `path` at `rev`, whitespace- and move-insensitive."""
    out = run(repo, "blame", "-w", "-M", "--line-porcelain", rev, "--", path)
    rows: list[tuple[str, int, str]] = []
    cur_sha, cur_ln = None, 0
    for line in out.splitlines():
        m = BLAME_HDR.match(line)
        if m:
            cur_sha, cur_ln = m.group(1), int(m.group(3))
        elif line.startswith("\t") and cur_sha:
            rows.append((cur_sha, cur_ln, line[1:]))
    return rows


def diff_u0(repo: Path, sha: str, path: str) -> str:
    return run(repo, "diff", "-U0", f"{sha}^", sha, "--", path)


def log_range(repo: Path, rng: str, path: str) -> list[tuple[str, str, str]]:
    out = run(repo, "log", f"--format=%H{SEP}%aI{SEP}%s", rng, "--", path)
    return [tuple(ln.split(SEP, 2)) for ln in out.splitlines() if ln.strip()]  # type: ignore[misc]
