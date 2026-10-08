#!/usr/bin/env python3
"""Entry point: ``python src/mc-server-images/cli.py <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

SERVERS = ["fabric", "neoforge", "paper", "pumpkin"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli.py", description="Minecraft server image tooling")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("window", help="print the maintenance window as a JSON list")
    p.add_argument("--count", type=int, default=3)

    p = sub.add_parser("plan", help="resolve all window targets and write draft locks")
    p.add_argument("--server", required=True, choices=SERVERS)
    p.add_argument("--out", required=True)
    p.add_argument("--force", action="store_true")
    p.add_argument("--github-output", action="store_true", dest="github_output")

    p = sub.add_parser("build-custom", help="build or fetch custom source artifacts")
    p.add_argument("--server", required=True, choices=SERVERS)
    p.add_argument("--minecraft", required=True)
    p.add_argument("--plan", required=True)
    p.add_argument("--out", required=True)

    p = sub.add_parser("lock", help="finalize a draft lock")
    p.add_argument("--server", required=True, choices=SERVERS)
    p.add_argument("--minecraft", required=True)
    p.add_argument("--plan", required=True)
    p.add_argument("--custom")
    p.add_argument("--out", required=True)

    p = sub.add_parser("stage", help="produce the Docker build context")
    p.add_argument("--server", required=True, choices=SERVERS)
    p.add_argument("--lock", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--custom")

    p = sub.add_parser("check-window", help="exit 0 when the version is in the window, 3 otherwise")
    p.add_argument("--minecraft", required=True)

    p = sub.add_parser("publish", help="push images, retag latest, write status.json")
    p.add_argument("--server", required=True, choices=SERVERS)
    p.add_argument("--artifacts", required=True)
    p.add_argument("--registry", required=True)
    p.add_argument("--dry-run", action="store_true", dest="dry_run")
    p.add_argument("--no-commit", action="store_true", dest="no_commit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command

    if command == "window":
        from sources import mojang

        print(json.dumps(mojang.maintenance_window(args.count)))
        return 0
    if command == "check-window":
        from sources import mojang

        return 0 if args.minecraft in mojang.maintenance_window() else 3
    if command == "plan":
        import resolver

        return resolver.plan_command(args)
    if command == "build-custom":
        import custom_build

        return custom_build.build_custom_command(args)
    if command == "lock":
        import locks

        return locks.finalize_command(args)
    if command == "stage":
        import staging

        return staging.stage_command(args)
    if command == "publish":
        import publish

        return publish.publish_command(args)
    return 2  # pragma: no cover - argparse rejects unknown commands


if __name__ == "__main__":
    sys.exit(main())
