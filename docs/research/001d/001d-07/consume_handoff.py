"""Finite, standard-library-only Objective 002 contract consumer; no live work."""
import json
from pathlib import Path


def main():
    graph = json.loads(Path(__file__).with_name('integration-call-graph-v1.json').read_text(encoding='utf-8'))
    if graph['artifact'] != 'objective-002-integration-call-graph' or graph['version'] != '1.0.0':
        raise ValueError('unsupported_handoff_contract')
    print(json.dumps(dict(version=graph['version'], compatibility=graph['compatibility'],
        entrypoints=graph['entrypoints'],
        nodes=[{k:n[k] for k in ('id','path','symbol','contract')} for n in graph['nodes']],
        operations=graph['operations'], local_operations=graph['local_operations'],
        dependencies=graph['dependencies']), sort_keys=True))


if __name__ == '__main__':
    main()
