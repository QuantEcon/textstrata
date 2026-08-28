"""The state-file baseline strategy against a synthetic engine-era repository.

The fixture reproduces the shapes observed in lecture-python-programming.zh-cn:
a document and its state file landing in one commit (the `translate init` case),
the pair landing as adjacent single-file commits (the autodiff case), and a
document with no state file at all.
"""
import json
import os
import subprocess
import sys
from datetime import datetime

import pytest

from textstrata.config import Config, ProseConfig
from textstrata.git import file_history
from textstrata.prose import Prose
from textstrata.scan import engine_version_at, scan, state_timeline, translation_moment


def git(repo, *args, date=None):
    env = dict(os.environ,
               GIT_AUTHOR_NAME="Engine", GIT_AUTHOR_EMAIL="engine@example.org",
               GIT_COMMITTER_NAME="Engine", GIT_COMMITTER_EMAIL="engine@example.org",
               GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    r = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def commit(repo, msg, date):
    git(repo, "add", "-A")
    git(repo, "commit", "-m", msg, date=date)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def engine_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "lectures").mkdir(parents=True)
    (repo / ".translate" / "state").mkdir(parents=True)
    git(repo, "init", "-q")
    # a.md: document and state file in one commit
    (repo / "lectures" / "a.md").write_text("# 讲座甲\n\n这是机器翻译的第一稿。\n", encoding="utf-8")
    (repo / ".translate" / "state" / "a.md.yml").write_text(
        "mode: NEW\nmodel: alpha-1\ntool-version: 0.1.0\n", encoding="utf-8")
    shas = {"init": commit(repo, "Initial translation via translate init", "2026-03-20T10:00:00Z")}
    # b.md: document first, state file one second later (the autodiff shape)
    (repo / "lectures" / "b.md").write_text("# 讲座乙\n\n另一篇机器初稿。\n", encoding="utf-8")
    shas["b_doc"] = commit(repo, "Update translation: lectures/b.md", "2026-04-09T04:40:27+00:00")
    (repo / ".translate" / "state" / "b.md.yml").write_text(
        "mode: NEW\nmodel: beta-1\ntool-version: 0.1.5\n", encoding="utf-8")
    shas["b_state"] = commit(repo, "Update translation: .translate/state/b.md.yml", "2026-04-09T04:40:28+00:00")
    # c.md: no state file
    (repo / "lectures" / "c.md").write_text("# 讲座丙\n\n没有状态文件的文稿。\n", encoding="utf-8")
    shas["c_doc"] = commit(repo, "Add c.md by hand", "2026-05-01T09:00:00Z")
    # a later sync touches a.md and its state file: must not move a.md's moment
    (repo / "lectures" / "a.md").write_text(
        "# 讲座甲\n\n这是机器重新同步的稿子。\n\ny = 2\n", encoding="utf-8")
    (repo / ".translate" / "state" / "a.md.yml").write_text(
        "mode: UPDATE\nmodel: alpha-2\ntool-version: 0.2.0\n", encoding="utf-8")
    shas["sync"] = commit(repo, "[translation-sync] resync a.md", "2026-06-01T09:00:00Z")
    # two editor-shaped commits (non-bot, non-sync, off-roster -> ai-assisted),
    # one purely additive and one purely deletive, so every line is unpaired:
    # a prose line and a code line arrive, then a code line leaves
    (repo / "lectures" / "a.md").write_text(
        "# 讲座甲\n\n这是机器重新同步的稿子。\n\ny = 2\n\n新增的一段人写文字。\n\nx = 1\n", encoding="utf-8")
    shas["edit"] = commit(repo, "Edit a.md by hand", "2026-07-01T09:00:00Z")
    (repo / "lectures" / "a.md").write_text(
        "# 讲座甲\n\n这是机器重新同步的稿子。\n\n新增的一段人写文字。\n\nx = 1\n", encoding="utf-8")
    shas["edit2"] = commit(repo, "Drop the scratch code line", "2026-07-02T09:00:00Z")
    return repo, shas


def make_cfg(repo, overrides=None):
    cfg = Config(name="t", repo=repo, base_dir=repo)
    cfg.baseline.strategy = "state-file"
    cfg.baseline.overrides = overrides or {}
    cfg.machine.state_dir = ".translate/state"
    return cfg


def moment(cfg, repo, doc):
    return translation_moment(cfg, repo, Prose(ProseConfig()), doc, file_history(repo, doc), sys.stderr)


def same_instant(date, expected):
    # git renders %aI's UTC offset as either Z or +00:00 depending on version;
    # compare instants, not strings
    return datetime.fromisoformat(date) == datetime.fromisoformat(expected)


def test_state_file_moments(engine_repo, capsys):
    repo, shas = engine_repo
    cfg = make_cfg(repo)
    # same-commit case: the moment is the state file's creating commit
    sha, date = moment(cfg, repo, "lectures/a.md")
    assert sha == shas["init"] and same_instant(date, "2026-03-20T10:00:00+00:00")
    # adjacent-commit case: the state-creating commit is not in the document's
    # history; the moment falls back to the document revision just before it
    assert moment(cfg, repo, "lectures/b.md")[0] == shas["b_doc"]
    # no state file: untranslated, and the log says so
    assert moment(cfg, repo, "lectures/c.md") == (None, None)
    assert "no state file" in capsys.readouterr().err


def test_override_beats_state_file(engine_repo):
    repo, shas = engine_repo
    cfg = make_cfg(repo, overrides={"lectures/c.md": shas["c_doc"][:7]})
    sha, date = moment(cfg, repo, "lectures/c.md")
    assert sha == shas["c_doc"] and same_instant(date, "2026-05-01T09:00:00+00:00")


def test_override_without_match_warns(engine_repo, capsys):
    repo, _shas = engine_repo
    cfg = make_cfg(repo, overrides={"lectures/a.md": "deadbeef"})
    assert moment(cfg, repo, "lectures/a.md") == (None, None)
    assert "matches no commit" in capsys.readouterr().err


def test_engine_version_at(engine_repo):
    repo, _shas = engine_repo
    revs = state_timeline(repo, ".translate/state", "lectures/a.md")
    assert [r[1]["model"] for r in revs] == ["alpha-1", "alpha-2"]
    # a record written seconds after the commit is that sync's own record
    assert engine_version_at(revs, "2026-06-01T08:59:59Z")["model"] == "alpha-2"
    # a commit long before the next record wrote no state: the record last in force applies
    assert engine_version_at(revs, "2026-05-01T00:00:00Z")["model"] == "alpha-1"
    # a commit after the last revision likewise
    assert engine_version_at(revs, "2026-07-01T00:00:00Z")["model"] == "alpha-2"
    # a commit before the state file existed has no record
    assert engine_version_at(revs, "2026-01-01T00:00:00Z") == {}
    assert engine_version_at([], "2026-07-01T00:00:00Z") == {}
    assert state_timeline(repo, ".translate/state", "lectures/c.md") == []


def test_engine_strata_in_scan(engine_repo, tmp_path):
    repo, shas = engine_repo
    cfg = make_cfg(repo)
    cfg.machine.sync = [r"\[translation-sync\]", "^Update translation: "]
    with open(os.devnull, "w") as devnull:
        run = scan(cfg, tmp_path / "out", log=devnull)
    rows = [json.loads(ln) for ln in (tmp_path / "out" / "commits.jsonl").open(encoding="utf-8")]
    by = {(r["document"], r["sha"]): r for r in rows}
    # same-commit mode: the sync is stamped with the record it wrote
    sync = by[("lectures/a.md", shas["sync"])]
    assert sync["tier"] == "ai-sync"
    assert (sync["engine_model"], sync["engine_tool_version"]) == ("alpha-2", "0.2.0")
    # adjacent-commit mode: the doc commit is stamped from the state written seconds later
    bdoc = by[("lectures/b.md", shas["b_doc"])]
    assert bdoc["tier"] == "ai-sync"
    assert (bdoc["engine_model"], bdoc["engine_tool_version"]) == ("beta-1", "0.1.5")
    # non-sync rows carry no stamp
    assert by[("lectures/a.md", shas["init"])]["engine_model"] is None
    # per-version totals, ordered by first appearance
    assert [(s["model"], s["tool_version"], s["sync_commits"]) for s in run["engine_strata"]] == [
        ("beta-1", "0.1.5", 1), ("alpha-2", "0.2.0", 1)]


def test_unpaired_lines_prose_gated(engine_repo, tmp_path):
    repo, shas = engine_repo
    cfg = make_cfg(repo)
    cfg.machine.sync = [r"\[translation-sync\]"]
    with open(os.devnull, "w") as devnull:
        scan(cfg, tmp_path / "out", log=devnull)
    pairs = [json.loads(ln) for ln in (tmp_path / "out" / "pairs.jsonl").open(encoding="utf-8")]
    mine = [p for p in pairs if p["sha"] in (shas["edit"][:8], shas["edit2"][:8])]
    got = {(p["category"], p["after"] or p["before"]) for p in mine}
    # a prose line arriving is an addition; code arriving or leaving is code-or-markup
    assert ("addition", "新增的一段人写文字。") in got
    assert ("code-or-markup", "x = 1") in got
    assert ("code-or-markup", "y = 2") in got
    assert all(p["taxonomy"] == "formatting" for p in mine if p["category"] == "code-or-markup")
    assert not any(p["category"] == "deletion" for p in mine)
