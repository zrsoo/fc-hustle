"""Read and admit one finite batch, then exit. This command never dispatches bids."""
import argparse
import json
from pathlib import Path
from .contracts import Search, context
from .executor import EdgeExecutor
from .foundation import DEFAULT_JOURNAL, Foundation


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--context', required=True, help='JSON file containing public production context labels')
    p.add_argument('--definition-id', type=int, required=True)
    p.add_argument('--journal', default=str(DEFAULT_JOURNAL))
    p.add_argument('--interval', type=float, default=0)
    args = p.parse_args()
    value = context(json.loads(Path(args.context).read_text()))
    f = Foundation(EdgeExecutor(), context=value, journal_path=args.journal, interval=args.interval)
    try:
        discovery = f.read('search', Search.discovery(args.definition_id).params())
        watched = f.read('watched')
        funds = f.read('balance')
        decisions = [f.admit(discovery, r['trade_id'], funds) for r in discovery['result']['auctions']]
        print(json.dumps(dict(schema=1, decisions=decisions, registry=f.registry.current(),
                              watched_count=len(watched['result']['auctions']))))
    finally:
        f.close()


if __name__ == '__main__':
    main()
