"""One read-only integration check, never the discovery benchmark or trading."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import secrets
import time
import urllib.request

from fc_access.harness import opener
from experiments.market_discovery.model import envelope, reply
from .server import FollowupServer, persona_projection


def request(base, route, value=None):
    data = None if value is None else json.dumps(value, allow_nan=False).encode()
    req = urllib.request.Request(base + route, data=data, headers={'Content-Type': 'application/json'})
    with opener().open(req, timeout=65) as response:
        raw = response.read(262145)
    if len(raw) > 262144:
        raise ValueError('oversize_response')
    return json.loads(raw)


def assessment(record):
    errors = []
    try:
        if record['schema'] != 1 or record['source'] != 'fc-discovery-followup-v1':
            errors.append('unrecognized_followup_source')
        reply({'result': record['result'], 'timing': record['timing']})
        p = persona_projection(record['persona']['projection'])
        if not p['accepted']:
            errors.append('selected_pc_persona_unverified')
        result = record['result']
        if not record['health_before']['attached']:
            errors.append('attachment_unverified')
        if not record['health_before']['long_poll_active']:
            errors.append('active_long_poll_unverified')
        if not result['success'] or result['platform'] != 'pc' or result['status'] != 200:
            errors.append('native_pc_search_failed')
        network = result['network']
        if not any(n['path'] == '/ut/game/fc27/transfermarket' and n['status'] == 200 and
                   n['session_header_present'] for n in network):
            errors.append('fresh_authenticated_http_200_unverified')
        if any(n['status'] in (401, 403, 429) or n['status'] >= 500 for n in network):
            errors.append('ea_http_error_observed')
        rows = result['auctions'] or []
        if not rows:
            errors.append('nonempty_exact_version_response_unverified')
        for row in rows:
            if row['item']['definition_id'] != record['request']['definition_id']:
                errors.append('wrong_card_version')
        marks = record['delivery']
        for key in ('queue_delivery_ms', 'result_return_ms'):
            value = marks[key]
            if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
                errors.append('missing_delivery_timing')
        for value in record['timing'].values():
            if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
                errors.append('missing_native_timing')
        telemetry = record['worker_telemetry']
        if telemetry['id'] != record['command_id']:
            errors.append('unmatched_worker_telemetry')
        for key in ('worker_dispatch_to_page_return_ms', 'result_post_round_trip_ms'):
            if type(telemetry[key]) not in (float, int) or not math.isfinite(telemetry[key]) or telemetry[key] < 0:
                errors.append('invalid_worker_timing')
        if record['account_mutations'] != 0:
            errors.append('account_mutation_out_of_scope')
    except (KeyError, TypeError, ValueError):
        errors.append('invalid_followup_observation')
    return sorted(set(errors))


def one_search(port, output):
    output = Path(output)
    if output.exists():
        raise ValueError('new_output_path_required')
    output.parent.mkdir(parents=True, exist_ok=True)
    base = f'http://127.0.0.1:{port}'
    record = {'schema': 1, 'source': 'fc-discovery-followup-v1',
              'captured_at': datetime.now(timezone.utc).isoformat(), 'account_mutations': 0}
    # Attachment, the persona projection, and the active long poll are independent
    # prerequisites; none is treated as proof of an authenticated EA response.
    record['health_before'] = request(base, '/health')
    record['persona'] = request(base, '/persona')
    if not record['health_before'].get('attached') or not record['persona']:
        raise ValueError('attach_followup_extension_first')
    if not persona_projection(record['persona']['projection'])['accepted']:
        raise ValueError('selected_pc_persona_rejected')
    identifier = secrets.token_hex(16)
    params = {'definition_id': 233731, 'max_buy': 7000, 'page': 1, 'count': 21, 'fresh': True}
    command = envelope({'id': identifier, 'evidence_key': secrets.token_hex(16),
                        'operation': 'search', 'params': params})
    began = time.perf_counter()
    value = request(base, '/run', command)
    elapsed = (time.perf_counter() - began) * 1000
    # Reject an invalid projection before it can enter a retained artifact.
    # Returning BLOCKED is never permission to persist unvalidated response data.
    reply({'result': value['result'], 'timing': value['timing']})
    delivery = value['delivery']
    if set(delivery) != {'queue_delivery_ms', 'result_return_ms'} or any(
            v is not None and (type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 120000)
            for v in delivery.values()):
        raise ValueError('invalid_delivery')
    # Do not retain the per-run correlation key or the command envelope.
    record.update(command_id=identifier, request=params, result=value['result'],
                  timing=value['timing'], delivery=delivery, end_to_end_ms=elapsed)
    telemetry = None
    for _ in range(20):
        telemetry = request(base, '/telemetry/' + identifier)
        if telemetry is not None:
            break
        time.sleep(0.05)  # localhost only; no EA traffic or search retry
    record['worker_telemetry'] = telemetry
    record['errors'] = assessment(record)
    record['status'] = 'PASS' if not record['errors'] else 'BLOCKED'
    with output.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': record['status'], 'output': output.as_posix(),
                      'errors': record['errors'], 'http_statuses': [n['status'] for n in record['result']['network']],
                      'auction_count': len(record['result']['auctions'] or []), 'end_to_end_ms': elapsed}))
    return bool(record['errors'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    serve = sub.add_parser('serve')
    serve.add_argument('--extension-id', required=True)
    serve.add_argument('--port', type=int, default=8771)
    search = sub.add_parser('search', help='One bounded exact-version search; no automatic retries')
    search.add_argument('--port', type=int, default=8771)
    search.add_argument('--output', type=Path, required=True)
    validate = sub.add_parser('validate', help='Read-only independent assessment of a follow-up capture')
    validate.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'validate':
        record = json.loads(args.input.read_text(encoding='utf-8'))
        errors = assessment(record)
        print(json.dumps({'status': 'PASS' if not errors else 'BLOCKED', 'errors': errors,
                          'scope': 'Recorded follow-up observations; not cryptographic attestation or a benchmark.'}))
        return bool(errors)
    if not 1 <= args.port <= 65535:
        parser.error('invalid_port')
    if args.action == 'serve':
        server = FollowupServer(args.extension_id, port=args.port)
        print(f'Read-only discovery follow-up on 127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    return one_search(args.port, args.output)


if __name__ == '__main__':
    raise SystemExit(main())
