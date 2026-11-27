"""Unified `faceless` command-line entry point.

One command dispatches to every stage, so you do not need to remember
`python -m src.<module>` for each. Examples:

    faceless run --niche "history mysteries" --publish-at-peak
    faceless trends --manual-only --input data/trends_input.json
    faceless script --format short --count 2 --style history_mystery
    faceless narrate --input data/scripts.json
    faceless music --narration a.mp3 --output mixed.mp3
    faceless video --format short --fetch-stock
    faceless qa --video out.mp4 --script-json script.json
    faceless research --topic "Antikythera mechanism"
    faceless thumbnail --variants --topic "..." --slug demo
    faceless seo --long data/scripts_long.json --short data/scripts_shorts.json
    faceless review --stats data/video_stats.json
    faceless upload --video out.mp4 --title "..." --dry-run

Each subcommand forwards its remaining args to that module's main(),
so every existing flag keeps working. `faceless` with no subcommand
prints help. The console_scripts entry point in pyproject.toml maps
`faceless` here.
"""

from __future__ import annotations

import argparse
import importlib
import sys

# subcommand -> module with a main(argv) callable.
COMMANDS = {
    "run": "src.run",
    "trends": "src.trends",
    "script": "src.script",
    "narrate": "src.narrate",
    "music": "src.music",
    "video": "src.video",
    "qa": "src.qa",
    "seo": "src.seo",
    "thumbnail": "src.thumbnail",
    "review": "src.review",
    "research": "src.research",
    "upload": "src.upload",
    "scheduler": "src.scheduler",
    "crosspost": "scripts.auto_crosspost",
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="faceless",
        description="Faceless YouTube creator — one CLI for every pipeline stage.")
    parser.add_argument("command", nargs="?", choices=sorted(COMMANDS),
                        help="Pipeline stage to run.")
    parser.add_argument("args", nargs=argparse.REMAINDER,
                        help="Arguments forwarded to the stage.")
    parsed = parser.parse_args(argv)
    if not parsed.command:
        parser.print_help()
        return 0
    module = importlib.import_module(COMMANDS[parsed.command])
    return module.main(parsed.args)


if __name__ == "__main__":
    raise SystemExit(main())
