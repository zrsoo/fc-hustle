"""Strict public contracts. Native IDs and session credentials never belong here."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import re

VERSION = 1


def integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= 2**53-1:
        raise ValueError("invalid_integer")
    return value


def token(value, prefix=None):
    pattern = rf"{prefix}:[a-f0-9]{{24}}" if prefix else r"[a-f0-9]{32}"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError("invalid_correlation")
    return value


def instant(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("utc_required")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Identity:
    trade_id: str
    item_id: str
    definition_id: int
    platform: str = "pc"
    game: str = "fc27"

    def __post_init__(self):
        token(self.trade_id, "trade")
        token(self.item_id, "item")
        integer(self.definition_id, 1)
        if self.platform != "pc" or self.game != "fc27":
            raise ValueError("unsupported_market")


@dataclass(frozen=True)
class Search:
    page: int = 1
    count: int = 21
    fresh: bool = True
    definition_id: int | None = None
    max_bid: int | None = None
    min_buy: int | None = None
    max_buy: int | None = None
    club: int | None = None
    league: int | None = None

    def __post_init__(self):
        if type(self.page) is not int or self.page not in (1, 2) or type(self.count) is not int or self.count != 21 or type(self.fresh) is not bool:
            raise ValueError("invalid_paging")
        for name in ("definition_id", "max_bid", "min_buy", "max_buy", "club", "league"):
            value = getattr(self, name)
            if value is not None:
                integer(value, 1 if name == "definition_id" else 0)
        if self.min_buy is not None and self.max_buy is not None and self.min_buy > self.max_buy:
            raise ValueError("invalid_buy_range")


@dataclass(frozen=True)
class Freshness:
    observed_at: datetime
    network_at: datetime | None
    request_count: int
    read_id: str
    source: str = "native"

    def __post_init__(self):
        instant(self.observed_at)
        if self.network_at is not None:
            instant(self.network_at)
            if self.network_at > self.observed_at:
                raise ValueError("future_network")
        integer(self.request_count)
        token(self.read_id)
        if self.source not in {"native", "fixture"}:
            raise ValueError("invalid_source")

    def fresh(self, now, max_age=30):
        age = (instant(now) - instant(self.network_at)).total_seconds() if self.network_at else -1
        return self.request_count > 0 and 0 <= age <= max_age


@dataclass(frozen=True)
class Coverage:
    complete: bool
    has_more: bool | None
    account_capacity: int | None = None
    evidence_id: str | None = None

    def __post_init__(self):
        if type(self.complete) is not bool or self.has_more is not None and type(self.has_more) is not bool:
            raise ValueError("invalid_coverage")
        if self.account_capacity is not None:
            integer(self.account_capacity, 1)
        if self.evidence_id is not None:
            token(self.evidence_id)
        if self.complete and (self.has_more is not False or self.evidence_id is None):
            raise ValueError("unsupported_complete_coverage")


class State(StrEnum):
    ACTIVE = "ACTIVE"
    LEADING = "LEADING"
    OUTBID = "OUTBID"
    PENDING = "PENDING"
    WON = "WON"
    LOST = "LOST"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AuctionStatus:
    identity: Identity
    state: State
    starting_bid: int
    current_bid: int
    buy_now_price: int
    deadline: datetime
    freshness: Freshness
    owned_item_id: str | None = None
    paid: int | None = None

    def __post_init__(self):
        if not isinstance(self.identity, Identity) or not isinstance(self.state, State) or not isinstance(self.freshness, Freshness):
            raise ValueError("invalid_status")
        integer(self.starting_bid, 1)
        integer(self.current_bid)
        integer(self.buy_now_price)
        instant(self.deadline)
        if self.owned_item_id is not None:
            token(self.owned_item_id, "item")
        if self.paid is not None:
            integer(self.paid, 1)
        if self.state == State.WON and (self.owned_item_id != self.identity.item_id or self.paid != self.current_bid or not self.paid):
            raise ValueError("win_requires_owned_item_and_actual_price")


@dataclass(frozen=True)
class Balance:
    spendable: int
    held: int | None
    freshness: Freshness

    def __post_init__(self):
        integer(self.spendable)
        if self.held is not None:
            integer(self.held)
        if not isinstance(self.freshness, Freshness):
            raise ValueError("invalid_balance")


@dataclass(frozen=True)
class BidIntent:
    command_id: str
    owner: str
    scope: str
    epoch: int
    identity: Identity
    amount: int
    cap: int
    deadline: datetime
    status_read_id: str
    balance_read_id: str

    def __post_init__(self):
        for value in (self.command_id, self.owner, self.scope, self.status_read_id, self.balance_read_id):
            token(value)
        integer(self.epoch, 1)
        integer(self.amount, 1)
        integer(self.cap, self.amount)
        instant(self.deadline)
        if not isinstance(self.identity, Identity):
            raise ValueError("invalid_identity")


class Outcome(StrEnum):
    ACKNOWLEDGED = "ACKNOWLEDGED"  # Native success is not independent verification.
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class BidResult:
    command_id: str
    outcome: Outcome
    reason: str

    def __post_init__(self):
        token(self.command_id)
        if not isinstance(self.outcome, Outcome) or self.reason not in {"NATIVE_ACK", "TIMEOUT", "INVALID_RESULT", "SERVICE_ERROR"}:
            raise ValueError("invalid_result")
        if (self.outcome == Outcome.ACKNOWLEDGED) != (self.reason == "NATIVE_ACK"):
            raise ValueError("inconsistent_result")


@dataclass(frozen=True)
class Snapshot:
    auctions: tuple[AuctionStatus, ...]
    freshness: Freshness
    coverage: Coverage

    def __post_init__(self):
        if not isinstance(self.auctions, tuple) or any(not isinstance(a, AuctionStatus) for a in self.auctions):
            raise ValueError("invalid_snapshot")
        if not isinstance(self.freshness, Freshness) or not isinstance(self.coverage, Coverage):
            raise ValueError("invalid_snapshot_metadata")
