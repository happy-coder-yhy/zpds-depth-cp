"""Command-line interface for local depth files."""

import argparse
import json
import sys

from . import files


def main(argv=None):
    parser = argparse.ArgumentParser(description="S1 metric depth compression (CPU, no models)")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("compress", "decompress"):
        command = commands.add_parser(name)
        command.add_argument("source")
        command.add_argument("destination")
    command = commands.add_parser("inspect")
    command.add_argument("source")
    command = commands.add_parser("verify", help="Check storage error, not depth estimation accuracy")
    command.add_argument("source")
    command.add_argument("compressed")
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            result = files.inspect(args.source)
        elif args.command == "verify":
            result = files.verify(args.source, args.compressed)
        else:
            result = getattr(files, args.command)(args.source, args.destination)
        print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
        return 2 if result.get("passed") is False else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"zpds-depth-cp: {exc}", file=sys.stderr)
        return 1
