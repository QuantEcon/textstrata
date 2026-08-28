"""Optional PR-API channel — the only network-touching module in the package.

Records review comments and suggestion fences per document as a separate
human-signal channel (design: issue #5). Squash merges and closed-unmerged
PRs hide this signal from git entirely; the channel recovers it without ever
blending it into blame. The scan neither reads nor writes these artefacts,
so its determinism contract is untouched.

    pr_channel.jsonl   one record per review comment anchored to a configured document
    pr_channel.json    collection summary (volumes by kind, role and PR state)
"""
from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .config import Config, ConfigError
from .roster import Roster

SUGGESTION = re.compile(r"```suggestion[^\n]*\n(.*?)```", re.DOTALL)


class GhError(RuntimeError):
    pass


def _concat(text: str):
    """`gh api --paginate` concatenates JSON documents; merge arrays, pass dicts through."""
    dec = json.JSONDecoder()
    idx, out, text = 0, None, text.strip()
    while idx < len(text):
        obj, idx = dec.raw_decode(text, idx)
        out = (out or []) + obj if isinstance(obj, list) else obj
        while idx < len(text) and text[idx] in " \n\r\t":
            idx += 1
    return [] if out is None else out


def gh_api(path: str):
    r = subprocess.run(["gh", "api", "--paginate", path], capture_output=True, check=False)
    if r.returncode != 0:
        raise GhError(f"gh api {path}: {r.stderr.decode(errors='replace')[:400]}")
    return _concat(r.stdout.decode("utf-8", errors="replace"))


def _hunk_tail(diff_hunk: str) -> str:
    """The commented line: the last content line of the comment's diff hunk."""
    lines = [ln for ln in (diff_hunk or "").splitlines() if not ln.startswith("@@")]
    return lines[-1][1:] if lines else ""


def collect(cfg: Config, out_dir: Path, log=sys.stderr, api=gh_api) -> dict:
    pc = cfg.pr_channel
    if not pc.repo:
        raise ConfigError("collect-pr needs pr_channel.repo (an owner/name slug) in the config")
    roster = Roster.load(cfg.resolve(cfg.people.roster))
    bots = [re.compile(p, re.IGNORECASE) for p in cfg.machine.bots + cfg.disclosure.authors]
    out_dir.mkdir(parents=True, exist_ok=True)

    comments = api(f"repos/{pc.repo}/pulls/comments?per_page=100&sort=created&direction=asc")
    pr_state: dict[int, str] = {}
    records: list[dict] = []
    for c in comments:
        path = c.get("path") or ""
        if not fnmatch.fnmatch(path, cfg.files):
            continue
        if pc.since and (c.get("created_at") or "") < pc.since:
            continue
        pr = int(c["pull_request_url"].rstrip("/").rsplit("/", 1)[-1])
        if pr not in pr_state:
            p = api(f"repos/{pc.repo}/pulls/{pr}")
            pr_state[pr] = "merged" if p.get("merged_at") else p.get("state", "unknown")
        login = (c.get("user") or {}).get("login") or ""
        person = roster.by_handle.get(login.lower())
        # the comments endpoint reports Copilot's reviewer as a bare "Copilot" login
        bot = login.lower() == "copilot" or any(p.search(login) for p in bots)
        body = c.get("body") or ""
        m = SUGGESTION.search(body)
        records.append({"pr": pr, "pr_state": pr_state[pr], "comment_id": c["id"],
                        "document": path, "line": c.get("line") or c.get("original_line"),
                        "author_login": login, "roster_id": person.id if person else None,
                        "role": person.role if person else None, "bot": bot,
                        "kind": "suggestion" if m else "comment",
                        "created_at": c.get("created_at"), "body_chars": len(body),
                        "in_reply_to": c.get("in_reply_to_id"),
                        "before": _hunk_tail(c.get("diff_hunk", "")) if m else None,
                        "after": m.group(1).rstrip("\n") if m else None})
    records.sort(key=lambda r: (r["pr"], r["comment_id"]))

    with (out_dir / "pr_channel.jsonl").open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {
        "repo": pc.repo,
        "collected_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "comments": len(records),
        "suggestions": sum(1 for r in records if r["kind"] == "suggestion"),
        "human": sum(1 for r in records if not r["bot"]),
        "bot": sum(1 for r in records if r["bot"]),
        "documents": len({r["document"] for r in records}),
        "by_role": dict(Counter(r["role"] or ("bot" if r["bot"] else "unresolved") for r in records)),
        "pr_states": dict(Counter(r["pr_state"] for r in records)),
    }
    (out_dir / "pr_channel.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    print(f"{pc.repo}: {summary['comments']} review comments on {summary['documents']} documents "
          f"({summary['human']} human, {summary['bot']} bot; {summary['suggestions']} suggestions)",
          file=log)
    return summary
