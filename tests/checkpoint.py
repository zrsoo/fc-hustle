"""Replay retained evidence at its recorded assessment time, never as current access."""
from datetime import datetime
from unittest.mock import patch


def transaction_at_checkpoint(record):
    from fc_access import transaction_checks

    class CheckpointClock(datetime):
        @classmethod
        def now(cls, tz=None):
            stamp = datetime.fromisoformat(record["updated_at"])
            return stamp.astimezone(tz) if tz else stamp.replace(tzinfo=None)

    with patch.object(transaction_checks, "datetime", CheckpointClock):
        return transaction_checks.assess(record)
