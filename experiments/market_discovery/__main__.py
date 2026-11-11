"""python -m experiments.market_discovery --help"""
import argparse
import json
from pathlib import Path

from .bridge_server import SearchServer
from .discovery import Runner
from .flow import simulated_flow
from .replay import Clock, FixtureClock, FixtureTransport, historical
from .transport import SearchTransport


def main():
    parser = argparse.ArgumentParser(description='Isolated read-only market discovery; no account write commands.')
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ('demo', 'replay', 'live', 'flow-demo'):
        p = sub.add_parser(name)
        p.add_argument('--output', type=Path, required=True, help='New artifact file; existing files are never overwritten')
        if name in ('demo', 'live'):
            p.add_argument('--windows', type=int, default=9, choices=range(1,10))
    sub.choices['live'].add_argument('--port', type=int, default=8770)
    p = sub.add_parser('serve')
    p.add_argument('--extension-id', required=True, help='Exact ID of the separately loaded research extension')
    p.add_argument('--port', type=int, default=8770)
    p.add_argument('--transport', choices=['long_poll','alarm_30s'], default='long_poll')
    args = parser.parse_args()
    if args.action == 'serve':
        server = SearchServer(args.extension_id, args.port, poll_seconds=0 if args.transport == 'alarm_30s' else 20)
        print('Read-only search research bridge on 127.0.0.1:' + str(server.server_port), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    # Fail before any observation if a requested artifact already exists.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as out:
        if args.action == 'flow-demo':
            result = simulated_flow()
            result['status'] = result['flow']['state']
        elif args.action == 'replay':
            result = historical()
        elif args.action == 'demo':
            clock = FixtureClock()
            result = Runner(FixtureTransport(clock), clock=clock, mode='SIMULATED').run(args.windows, paced=True)
        else:
            result = Runner(SearchTransport(args.port), clock=Clock(), mode='LIVE_READ_ONLY').run(args.windows, paced=True)
        json.dump(result, out, indent=2, allow_nan=False)
        out.write('\n')
    print(json.dumps({'status':result['status'], 'mode':result['mode'], 'output':str(args.output)}))
    return 1 if result.get('stop_reason') else 0


if __name__ == '__main__':
    raise SystemExit(main())
