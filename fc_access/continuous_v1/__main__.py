"""Explicit production controls. Help, config and status never attach to Edge."""
import argparse
import json
from pathlib import Path
import sqlite3

from .control import Control
from .runtime import DEFAULT_STATE, DEFAULT_JOURNAL, child, production_config, run


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state-dir', default=str(DEFAULT_STATE))
    sub = p.add_subparsers(dest='action', required=True)
    sub.add_parser('config'); sub.add_parser('status'); sub.add_parser('stop')
    for name in ('run', 'recover'):
        start = sub.add_parser(name)
        start.add_argument('--context', required=True, help='JSON file with public reviewed context labels')
        start.add_argument('--journal', default=str(DEFAULT_JOURNAL))
        start.add_argument('--cache')
        start.add_argument('--port', type=int, default=8784)
    internal = sub.add_parser('_child')
    internal.add_argument('--run', required=True)
    internal.add_argument('--role', required=True, choices=('monitor','executor','acquirer','bidder','maintenance'))
    args = p.parse_args()
    path = Path(args.state_dir).resolve() / 'control.sqlite3'
    if args.action == 'config':
        print(json.dumps(production_config().export(), sort_keys=True)); return 0
    if args.action in {'run', 'recover'}:
        return run(args.state_dir, context=json.loads(Path(args.context).read_text()), journal=args.journal,
                   cache=args.cache, port=args.port, recovery=args.action == 'recover')
    if args.action == '_child': return child(path, args.run, args.role)
    # Pure read-only status does not create a database or mutate operational rows.
    if not path.exists():
        print(json.dumps(dict(status='NOT_STARTED'))); return 0
    if args.action == 'status':
        control = object.__new__(Control)
        import time
        control.path, control.clock = path, time.monotonic
        control.db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    else:
        control = Control(path)
    try:
        if args.action == 'stop':
            opened = control.latest(None, 'RUN_OPEN')
            if opened and not control.latest(opened['run'], 'RUN_STOPPED'):
                control.stop(opened['run'], 'OPERATOR_STOP')
        print(json.dumps(control.status(), sort_keys=True, allow_nan=False))
    finally:
        control.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
