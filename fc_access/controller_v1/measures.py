"""Interchangeable measures for the bid-denial signature. No EA requests here.

The semantic monitor classifies consecutive native 461 / service 403 bid denials
with healthy reads as ``STALE_DOCUMENT_WRITE_DENIAL``. What the supervisor then
*attempts* is a measure, selected by name at launch:

``noop``     attempts nothing. The signature is logged (WRITE_DENIAL_SIGNATURE)
             and the runtime stops on PERSISTENT_WRITE_FAILURE, as before.
``relogin``  reloads the official tab and walks the normal saved sign-in
             (recovery.DocumentRecovery); on success the supervisor starts a
             fresh worker with a higher owner epoch.

A measure has a ``name``, ``active`` (whether the supervisor intercepts the stop)
and, when active, ``attempt(cancelled)`` returning
``dict(outcome='READY'|'CHALLENGE'|'FAILED'|'CANCELLED', reason=str|None, steps=list)``.
To add one, implement that shape and register it in ``MEASURES``.
"""
import json
from pathlib import Path


class NoOpMeasure:
    name = 'noop'
    active = False

    def attempt(self, cancelled):
        raise RuntimeError('noop_measure_is_never_attempted')


class ContinueMeasure:
    """Bid through 461 denials: each is a no-effect outcome and the batch goes
    on and the controller pauses acquisition with an escalating wait. The
    runtime stops only after limits.denial_window seconds (2 h) of denials with
    no accepted bid (PERSISTENT_BID_DENIAL). No measure is attempted here; a
    page refresh once per wave is the supervisor's --wave-refresh-after."""
    name = 'continue'
    active = False
    tolerate_denials = True

    def attempt(self, cancelled):
        raise RuntimeError('continue_measure_is_never_attempted')


class ReloginMeasure:
    name = 'relogin'
    active = True

    def __init__(self, account):
        from .recovery import DocumentRecovery
        DocumentRecovery(account)  # validates the label before any launch
        self.account = account

    def attempt(self, cancelled):
        from .recovery import DocumentRecovery
        return DocumentRecovery(self.account, cancelled=cancelled).run()


def recovery_account(path):
    """Private local JSON {"account_label": ...}, kept outside Git."""
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if type(value) is not dict or set(value) != {'account_label'}:
        raise ValueError('invalid_recovery_config')
    return value['account_label']


MEASURES = {
    'noop': lambda config: NoOpMeasure(),
    'continue': lambda config: ContinueMeasure(),
    'relogin': lambda config: ReloginMeasure(recovery_account(config)) if config else _missing_config(),
}


def _missing_config():
    raise ValueError('measure_requires_recovery_config')


def measure(name, *, recovery_config=None):
    if name not in MEASURES:
        raise ValueError('unknown_write_denial_measure')
    return MEASURES[name](recovery_config)
