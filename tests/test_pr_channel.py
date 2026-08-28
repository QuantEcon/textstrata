"""The PR-API channel collector against a recorded, stubbed API — no network."""
import json
import re
import sys

import pytest

from textstrata.config import Config, ConfigError
from textstrata.pr_channel import _concat, _hunk_tail, collect

COMMENTS = [
    {"id": 11, "path": "lectures/a.md", "line": 12, "user": {"login": "HumphreyYang"},
     "body": "This is reverting code comments back to English",
     "pull_request_url": "https://api.github.com/repos/o/r/pulls/7",
     "created_at": "2026-04-14T01:00:00Z",
     "diff_hunk": "@@ -10,2 +10,2 @@\n 上下文行\n+# Update wealth"},
    {"id": 12, "path": "lectures/a.md", "line": 13, "user": {"login": "HumphreyYang"},
     "body": "请修正：\n```suggestion\n# 更新财富\n```\n如上。",
     "pull_request_url": "https://api.github.com/repos/o/r/pulls/7",
     "created_at": "2026-04-14T01:05:00Z",
     "diff_hunk": "@@ -13 +13 @@\n+# Update wealth"},
    {"id": 13, "path": "lectures/b.md", "line": 2, "user": {"login": "Copilot"},
     "body": "Consider handling the empty case.",
     "pull_request_url": "https://api.github.com/repos/o/r/pulls/9",
     "created_at": "2026-05-01T00:00:00Z", "diff_hunk": ""},
    # outside the files glob: never collected
    {"id": 14, "path": "README.md", "line": 1, "user": {"login": "HumphreyYang"},
     "body": "readme note", "pull_request_url": "https://api.github.com/repos/o/r/pulls/7",
     "created_at": "2026-04-14T02:00:00Z", "diff_hunk": ""},
    # before `since`: skipped
    {"id": 15, "path": "lectures/a.md", "line": 3, "user": {"login": "someoneelse"},
     "body": "early note", "pull_request_url": "https://api.github.com/repos/o/r/pulls/7",
     "created_at": "2026-01-01T00:00:00Z", "diff_hunk": ""},
]
PRS = {7: {"merged_at": None, "state": "closed"},
       9: {"merged_at": "2026-05-02T00:00:00Z", "state": "closed"}}


def fake_api(path):
    if "pulls/comments" in path:
        return COMMENTS
    m = re.search(r"/pulls/(\d+)$", path)
    return PRS[int(m.group(1))]


def make_cfg(tmp_path):
    (tmp_path / "roster.yml").write_text(
        "people:\n  - id: HumphreyYang\n    role: editor\n    emails: [x@example.org]\n",
        encoding="utf-8")
    cfg = Config(name="t", repo=tmp_path, base_dir=tmp_path)
    cfg.pr_channel.repo = "o/r"
    cfg.pr_channel.since = "2026-02-01"
    cfg.people.roster = "roster.yml"
    return cfg


def test_collect(tmp_path, capsys):
    cfg = make_cfg(tmp_path)
    summary = collect(cfg, tmp_path / "out", log=sys.stderr, api=fake_api)
    recs = [json.loads(ln) for ln in (tmp_path / "out" / "pr_channel.jsonl").open(encoding="utf-8")]
    assert [r["comment_id"] for r in recs] == [11, 12, 13]   # glob and since filters applied, sorted
    by_id = {r["comment_id"]: r for r in recs}
    # roster resolution by login, and the closed-unmerged PR is the point of the channel
    assert by_id[11]["roster_id"] == "HumphreyYang" and by_id[11]["role"] == "editor"
    assert by_id[11]["pr_state"] == "closed" and by_id[13]["pr_state"] == "merged"
    # suggestion fences carry the before (hunk tail) / after (fence body) pair
    assert by_id[12]["kind"] == "suggestion"
    assert by_id[12]["before"] == "# Update wealth" and by_id[12]["after"] == "# 更新财富"
    assert by_id[11]["kind"] == "comment" and by_id[11]["before"] is None
    # the Copilot reviewer is collected as a bot, not dropped
    assert by_id[13]["bot"] is True and by_id[11]["bot"] is False
    assert summary["comments"] == 3 and summary["suggestions"] == 1
    assert summary["human"] == 2 and summary["bot"] == 1
    assert summary["by_role"] == {"editor": 2, "bot": 1}
    assert summary["pr_states"] == {"closed": 2, "merged": 1}
    assert "3 review comments" in capsys.readouterr().err


def test_collect_needs_repo(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.pr_channel.repo = None
    with pytest.raises(ConfigError, match="pr_channel.repo"):
        collect(cfg, tmp_path / "out", api=fake_api)


def test_concat_and_hunk_tail():
    # gh --paginate concatenates array pages; single documents pass through
    assert _concat('[{"a": 1}]\n[{"b": 2}]') == [{"a": 1}, {"b": 2}]
    assert _concat('{"state": "closed"}') == {"state": "closed"}
    assert _concat("") == []
    assert _hunk_tail("@@ -1,2 +1,2 @@\n context\n+new line") == "new line"
    assert _hunk_tail("") == ""
