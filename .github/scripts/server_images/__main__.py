"""Command line: ``PYTHONPATH=.github/scripts python -m server_images <command>``.

Commands map onto the stages of ``.github/workflows/server-image.yml``:
``plan`` -> ``build-custom`` -> ``lock`` -> ``stage`` -> (docker build,
``python -m server_images.ci_check``) -> ``result`` -> ``publish``.
``site-data`` feeds the website built by ``.github/workflows/web.yml``.
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import GITHUB_REPOSITORY, SERVERS_DIR
from .loaders import SERVERS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m server_images", description="Minecraft server image tooling")
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name: str, help: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help)
        p.add_argument("--server", required=True, choices=SERVERS)
        return p

    p = command("window", "print the server's maintenance window and upcoming releases as JSON")
    p.add_argument("--count", type=int, default=3)

    p = command("check-window", "exit 0 when the version is in the server's window, 3 otherwise")
    p.add_argument("--minecraft", required=True)

    p = command("plan", "resolve all window targets and write draft locks")
    p.add_argument("--out", required=True)
    p.add_argument("--force", action="store_true", help="build every target even if its inputs are unchanged")
    p.add_argument("--github-output", action="store_true", help="append matrix and has_builds to $GITHUB_OUTPUT")

    p = command("build-custom", "build or fetch custom source artifacts")
    p.add_argument("--minecraft", required=True)
    p.add_argument("--plan", required=True)
    p.add_argument("--out", required=True)

    p = command("lock", "finalize a draft lock")
    p.add_argument("--minecraft", required=True)
    p.add_argument("--plan", required=True)
    p.add_argument("--custom")
    p.add_argument("--out", required=True)

    p = command("stage", "produce the Docker build context")
    p.add_argument("--lock", required=True)
    p.add_argument("--custom")
    p.add_argument("--out", required=True)

    p = command("result", "write the result.json of a build job")
    p.add_argument("--minecraft", required=True)
    p.add_argument("--lock", required=True)
    p.add_argument("--passed", required=True, choices=["true", "false"])
    p.add_argument("--out", required=True)

    p = command("publish", "push images, retag latest, write status.json, commit locks")
    p.add_argument("--artifacts", required=True)
    p.add_argument("--plan", help="plan directory; its pending targets are recorded in status.json")
    p.add_argument("--registry", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-commit", action="store_true")

    p = sub.add_parser("site-data", help="export loaders, status and locks of every server as the website's JSON input")
    p.add_argument("--out", required=True)
    p.add_argument("--repo", default=GITHUB_REPOSITORY, help="GitHub owner/name used for image references")
    p.add_argument("--servers", default=str(SERVERS_DIR), help="directory holding <server>/locks/")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Imports are per command: most of them need the network or PyYAML.
    if args.command in ("window", "check-window"):
        from .loaders import get_loader, server_window

        if args.command == "check-window":
            return 0 if args.minecraft in server_window(get_loader(args.server)).window else 3
        detected = server_window(get_loader(args.server), args.count)
        print(json.dumps({"window": detected.window, "upcoming": detected.upcoming}))
        return 0
    if args.command == "plan":
        from . import resolver

        return resolver.plan_command(args)
    if args.command == "build-custom":
        from . import custom_build

        return custom_build.build_custom_command(args)
    if args.command == "lock":
        from . import locks

        return locks.finalize_command(args)
    if args.command == "stage":
        from . import staging

        return staging.stage_command(args)
    if args.command == "result":
        from . import publish

        return publish.result_command(args)
    if args.command == "publish":
        from . import publish

        return publish.publish_command(args)
    if args.command == "site-data":
        from . import site_data

        return site_data.site_data_command(args)
    raise AssertionError(f"unhandled command {args.command}")  # argparse rejects unknown commands


if __name__ == "__main__":
    sys.exit(main())
