"""Regression against the 2026-08-04 lecture-intro.zh-cn study.

Runs only when TEXTSTRATA_INTRO_ZH_CN_REPO points at a checkout of
QuantEcon/lecture-intro.zh-cn at 0466562 (and TEXTSTRATA_ROSTER at QuantEcon's
team/reviewers.yml). Compares the quantities the study's method and this one
define identically: translation date, ai-initial and ai-sync shares of prose
lines at HEAD, and initial->HEAD similarity, per lecture; the corpus prose-line
total and pair count. Not compared: human-tier splits (the study mixed who and
what) and days-to-first-touch (the study keyed it on commit subjects).
"""
import csv
import json
import os
import subprocess
from pathlib import Path

import pytest

from textstrata.config import load_config
from textstrata.scan import scan

HERE = Path(__file__).parent
FIXTURE = HERE / "regression" / "2026-08-04-intro-zh-cn" / "lecture_metrics.csv"
STUDY_SHA = "046656207b69e2b51219528fd8e22c88f7a8635a"


@pytest.mark.skipif(not os.environ.get("TEXTSTRATA_INTRO_ZH_CN_REPO"), reason="needs a lecture-intro.zh-cn checkout")
def test_intro_zh_cn_matches_study(tmp_path):
    repo = Path(os.environ["TEXTSTRATA_INTRO_ZH_CN_REPO"]).resolve()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=False).stdout.strip()
    assert head == STUDY_SHA, f"checkout must be at {STUDY_SHA[:7]}, got {head[:7]}"
    roster = os.environ.get("TEXTSTRATA_ROSTER")
    cfg_text = (HERE.parent / "configs" / "quantecon" / "intro-zh-cn.yml").read_text(encoding="utf-8")
    cfg_text = cfg_text.replace("repo: ../../../project-translation/repos/lecture-intro.zh-cn", f"repo: {repo}")
    cfg_text = cfg_text.replace("  repo: ../../../project-translation/repos/lecture-python-intro\n", "")
    cfg_text = cfg_text.replace("source:\n", "")
    cfg_text = cfg_text.replace("  roster: ../../../project-translation/team/reviewers.yml\n",
                                f"  roster: {roster}\n" if roster else "")
    cfg_text = cfg_text.replace("overrides: overrides/intro-zh-cn.yml",
                                f"overrides: {HERE.parent / 'configs/quantecon/overrides/intro-zh-cn.yml'}")
    cfg_path = tmp_path / "cfg.yml"
    cfg_path.write_text(cfg_text, encoding="utf-8")
    with open(os.devnull, "w") as devnull:
        run = scan(load_config(cfg_path), tmp_path / "out", log=devnull)
    assert run["prose_lines"] == 9214
    assert run["pairs"] == 4510
    docs = json.loads((tmp_path / "out" / "documents.json").read_text(encoding="utf-8"))
    expected = {r["lecture"]: r for r in csv.DictReader(FIXTURE.open(encoding="utf-8"))}
    compared = 0
    for path, d in docs.items():
        name = Path(path).stem
        if name not in expected:
            continue
        e = expected[name]
        compared += 1
        assert d["translation_date"][:10] == e["translated"], name
        assert abs(d["composition_pct"].get("ai-initial", 0) - float(e["ai_init"])) <= 0.15, name
        assert abs(d["composition_pct"].get("ai-sync", 0) - float(e["ai_sync"])) <= 0.15, name
        assert abs(d["similarity_initial_head"] - float(e["sim"])) <= 0.002, name
    assert compared == 44
