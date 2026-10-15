"""Command-line interface for local depth files."""

import argparse
import json
import sys

from . import files
from .storage import PRECISION_PRESETS


def main(argv=None):
    parser = argparse.ArgumentParser(description="Metric depth compression: S1, S2 and S3")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("compress", "decompress"):
        command = commands.add_parser(name)
        command.add_argument("source")
        command.add_argument("destination")
        if name == "compress":
            command.add_argument("--preset", type=str.upper, choices=PRECISION_PRESETS,
                                 default="S1", help="Compression precision (default: S1)")
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
        elif args.command == "compress":
            result = files.compress(args.source, args.destination, preset=args.preset)
        else:
            result = files.decompress(args.source, args.destination)
        print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
        return 2 if result.get("passed") is False else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"zpds-depth-cp: {exc}", file=sys.stderr)
        return 1
