"""Offline projection of sealed pre-002 local support metadata.

Historical function digests describe captures; they never select an allowed
implementation. Current transports use the strict function_available contract.
"""
from copy import deepcopy
from fc_access.production_v1.contracts import parse_response as parse_current_response


def parse_response(value, command, **kwargs):
    projected = value
    result = value.get('result', {})
    if command['operation'] == 'status_support' and 'source_sha256' in result:
        projected = deepcopy(value)
        result = projected['result']
        digest = result.pop('source_sha256')
        result.pop('source_match')  # descriptive historical conclusion, not a gate
        result['function_available'] = digest is not None
    return parse_current_response(projected, command, **kwargs)
