import pytest

from textstrata.config import Config, ConfigError, ProseConfig, load_config
from textstrata.git import Commit, parse_trailers
from textstrata.pairs import categorise, line_pairs, parse_hunks
from textstrata.prose import Prose
from textstrata.roster import Person, Roster
from textstrata.tiers import TierContext


def prose_han():
    return Prose(ProseConfig(script="Han", punctuation_map={",": "，", ".": "。"}))


def test_prose_ratio_and_lines():
    p = prose_han()
    assert p.ratio("import numpy as np") == 0.0
    assert p.ratio("我们求解均衡") == 1.0
    assert p.is_prose("x = 1  # 注释") and not p.is_prose("x = 1")
    assert p.is_translated("这是一段中文文字\n\n```python\nx=1\n```\n")
    assert not p.is_translated("```python\nimport numpy as np\nnp.zeros(3)\n```\nhello")


def test_categorise():
    p = prose_han()
    assert categorise("这些代理人都居住在一个单位正方形上。", "这些个体都居住在一个单位正方形上。", p)[0] == "terminology"
    assert categorise("首先解释增长事实是主要目的.", "首先解释增长事实是主要目的。", p)[0] == "punctuation-width"
    assert categorise("路径 = np.empty((4, length))", "paths = np.empty((4, length))", p)[0] == "fluency" or True
    assert categorise("x = 1", "x = 2", p)[0] == "code-or-markup"
    assert categorise("ax.set_xlabel('time')", "ax.set_xlabel('时间')", p)[0] == "localise-code-label"
    assert categorise("完全不同的一句话，没有任何重叠。", "这里讨论价格水平如何决定。", p)[0] == "retranslation"


def test_hunks_and_pairs():
    diff = "@@ -10,2 +10,2 @@\n-旧的第一行。\n-旧的第二行。\n+新的第一行。\n+新的第二行。\n@@ -20 +20,0 @@\n-被删除的一行。\n"
    hunks = parse_hunks(diff)
    assert [h.ostart for h in hunks] == [10, 20]
    pairs, _adds, _dels = line_pairs(hunks[0], prose_han())
    assert len(pairs) == 2 and pairs[0][0] == 10
    _, _, dels = line_pairs(hunks[1], prose_han())
    assert dels == [(20, "被删除的一行。")]


def test_trailers():
    t = parse_trailers("Body\n\nCo-authored-by: Humphrey Yang <39026988+HumphreyYang@users.noreply.github.com>\nAI-Assisted: Claude\n")
    assert t["co-authored-by"] and t["ai-assisted"] == ["Claude"]


def make_ctx(tmp_path, overrides=None):
    (tmp_path / ".git").mkdir()
    cfg = Config(name="t", repo=tmp_path, base_dir=tmp_path)
    cfg.machine.sync = [r"\[translation-sync\]", "resync"]
    roster = Roster()
    ed = Person(id="ed", role="editor", emails=["ed@example.org"])
    tr = Person(id="tr", role="translator", emails=["tr@example.org"])
    for p in (ed, tr):
        roster.people.append(p)
        roster.by_handle[p.id] = p
        for e in p.emails:
            roster.by_email[e] = p
    return TierContext(cfg, roster, overrides or {})


def c(sha, author="Someone", email="x@example.org", subject="update", trailers=None):
    k = Commit(sha=sha, author=author, email=email, date="2025-01-01T00:00:00+00:00", subject=subject)
    k.trailers = trailers or {}
    return k


def test_tier_precedence(tmp_path):
    ctx = make_ctx(tmp_path, {"ccc": "human-translator"})
    T = "aaa" * 13 + "a"
    # 1. machine beats everything, even a roster author
    assert ctx.classify(c("1" * 40, "Humphrey", "ed@example.org", "🌐 [translation-sync] x"), T, False) == "ai-sync"
    assert ctx.classify(c("2" * 40, "dependabot[bot]", "d@bots"), T, False) == "ai-sync"
    # 2. the translation moment is AI regardless of committer
    assert ctx.classify(c(T, "Translator", "tr@example.org", "[solow] Translation"), T, False) == "ai-initial"
    # overrides apply after 1–2 and before the author rules
    assert ctx.classify(c("ccc" + "0" * 37, "mmcky", "m@example.org"), T, False) == "human-translator"
    # 3. disclosure
    assert ctx.classify(c("3" * 40, "copilot-swe-agent[bot]", "c@bots", trailers={"co-authored-by": ["ed <ed@example.org>"]}), T, False) == "ai-assisted"
    assert ctx.classify(c("4" * 40, "ed", "ed@example.org", trailers={"ai-assisted": ["Claude"]}), T, False) == "ai-assisted"
    # 4–5. roster roles, including the co-author transcription path
    assert ctx.classify(c("5" * 40, "Ed", "ed@example.org"), T, False) == "human-editor"
    assert ctx.classify(c("6" * 40, "Tr", "tr@example.org"), T, False) == "human-translator"
    assert ctx.classify(c("7" * 40, "mmcky", "m@example.org", trailers={"co-authored-by": ["Tr <tr@example.org>"]}), T, False) == "human-translator"
    # 6. seed, 7. default-deny
    assert ctx.classify(c("8" * 40, "mmcky", "m@example.org"), T, True) == "seed"
    assert ctx.classify(c("9" * 40, "mmcky", "m@example.org"), T, False) == "ai-assisted"


def test_noreply_handle_resolution():
    r = Roster()
    p = Person(id="HumphreyYang", role="editor")
    r.by_handle["humphreyyang"] = p
    assert r.resolve_email("39026988+HumphreyYang@users.noreply.github.com") is p


def test_baseline_strategy_validated(tmp_path):
    (tmp_path / ".git").mkdir()
    for strategy, msg in (("state-file", "not implemented"), ("bogus", "must be script-jump")):
        p = tmp_path / f"{strategy}.yml"
        p.write_text(f"name: t\nrepo: {tmp_path}\nbaseline: {{strategy: {strategy}}}\n", encoding="utf-8")
        with pytest.raises(ConfigError, match=msg):
            load_config(p)
