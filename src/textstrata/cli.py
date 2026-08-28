"""Command-line entry point."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, load_config
from .scan import scan


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="textstrata",
                                 description="git-derived metrics for machine-drafted, human-edited text")
    ap.add_argument("--version", action="version", version=f"textstrata {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="scan one target repository and write the run's artefacts")
    s.add_argument("config", help="path to a textstrata config YAML")
    s.add_argument("-o", "--out", default=None, help="output directory (default: ./out/<name>)")
    s.add_argument("-q", "--quiet", action="store_true")
    r = sub.add_parser("summary", help="print the corpus summary of a finished scan")
    r.add_argument("out_dir")
    p = sub.add_parser("collect-pr",
                       help="collect the PR-API review-comment channel (needs gh; network)")
    p.add_argument("config", help="path to a textstrata config YAML with a pr_channel block")
    p.add_argument("-o", "--out", default=None, help="output directory (default: ./out/<name>)")
    p.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd in ("scan", "collect-pr"):
        try:
            cfg = load_config(a.config)
        except ConfigError as e:
            print(f"config error: {e}", file=sys.stderr)
            return 2
        out = Path(a.out) if a.out else Path("out") / cfg.name
    if a.cmd == "scan":
        with open(os.devnull, "w") as devnull:
            run = scan(cfg, out, log=devnull if a.quiet else sys.stderr)
        print(json.dumps({k: run[k] for k in ("config", "head", "translated", "prose_lines",
                                                "composition_pct", "review_state", "pairs")},
                         ensure_ascii=False))
        return 0
    if a.cmd == "collect-pr":
        from .pr_channel import GhError, collect
        try:
            with open(os.devnull, "w") as devnull:
                summary = collect(cfg, out, log=devnull if a.quiet else sys.stderr)
        except ConfigError as e:
            print(f"config error: {e}", file=sys.stderr)
            return 2
        except GhError as e:
            print(str(e), file=sys.stderr)
            return 1
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    if a.cmd == "summary":
        run = json.loads((Path(a.out_dir) / "run.json").read_text(encoding="utf-8"))
        print(f"{run['config']} @ {run['head'][:7]} — {run['translated']}/{run['documents']} documents translated, "
              f"{run['prose_lines']} prose lines")
        for k, v in sorted(run["composition_pct"].items(), key=lambda kv: -kv[1]):
            print(f"  {k:17}{v:6.1f}%")
        print(f"  review state: {run['review_state']}")
        print(f"  pairs: {run['pairs']} {run['pair_categories']}; recurring substitutions: {run['recurring_substitutions']}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
