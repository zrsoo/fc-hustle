"""Finite read-only live benchmark; all strategy requests come from the frozen protocol."""
import argparse
from pathlib import Path
from .run import execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True, help='New output directory only')
    parser.add_argument('--port', type=int, default=8771)
    args = parser.parse_args()
    return execute(args.output_dir, args.port)


if __name__ == '__main__':
    raise SystemExit(main())
