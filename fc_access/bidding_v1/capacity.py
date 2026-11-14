"""Durable, disjoint potential-win slots in the auction journal.

Coin reservations are independent: releasing EA escrow never releases a slot.
All mutations run inside the journal's BEGIN IMMEDIATE transaction. Inventory is
accepted only after the production Transfer List completeness/correlation checks.
"""
import json
from contextlib import nullcontext
from datetime import datetime

from .contracts import integer, token


def installed(journal):
    return bool(journal.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='capacity_slots_v1'").fetchone())


def install(journal):
    journal.db.executescript("""
      CREATE TABLE IF NOT EXISTS capacity_slots_v1(
        scope TEXT NOT NULL, trade_id TEXT NOT NULL, item_id TEXT NOT NULL,
        definition_id INTEGER NOT NULL, phase TEXT NOT NULL,
        PRIMARY KEY(scope,trade_id));
      CREATE TABLE IF NOT EXISTS capacity_inventory_v1(
        scope TEXT PRIMARY KEY, read_id TEXT NOT NULL, network_at TEXT NOT NULL,
        items TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS capacity_reads_v1(
        scope TEXT NOT NULL, read_id TEXT NOT NULL, PRIMARY KEY(scope,read_id));
      CREATE TABLE IF NOT EXISTS capacity_migration_v1(id INTEGER PRIMARY KEY);
    """)
    with journal.transaction():
        if not journal.db.execute('SELECT 1 FROM capacity_migration_v1').fetchone():
            # Preserve historical events. Old UNKNOWN intents without an ENROLLED
            # event also consume a slot, including intents recovered after a crash.
            for e in journal.trace():
                apply_event(journal, e['scope'], e['reason'], e['data'], e['trade_id'], recovering=True)
            journal.db.execute('INSERT INTO capacity_migration_v1 VALUES(1)')


def apply_event(journal, scope, reason, data, trade, *, recovering=False):
    """Part of the SAME commit as enrollment, intent or terminal evidence."""
    if reason in {'ENROLLED', 'INTENT_DURABLE'}:
        identity = (data['item_id'], data['definition_id'])
        old = journal.db.execute('SELECT item_id,definition_id,phase FROM capacity_slots_v1 '
            'WHERE scope=? AND trade_id=?', (scope, trade)).fetchone()
        if old:
            if recovering and old[:2] == identity and old[2] in {'LOST', 'RELEASED'}:
                journal.db.execute("UPDATE capacity_slots_v1 SET phase='UNRESOLVED' WHERE scope=? AND trade_id=?", (scope, trade))
                return
            if old[:2] != identity or old[2] != 'UNRESOLVED':
                raise ValueError('capacity_identity_or_terminal_conflict')
            return
        journal.db.execute('INSERT INTO capacity_slots_v1 VALUES(?,?,?,?,?)',
            (scope, trade, *identity, 'UNRESOLVED'))
    elif reason in {'WON_VERIFIED', 'LOST_VERIFIED'}:
        # Terminal duplicates/conflicts never reverse a possible win or reopen a
        # slot already accounted for in the physical pile.
        phase = 'PENDING_RESALE' if reason == 'WON_VERIFIED' else 'LOST'
        journal.db.execute("UPDATE capacity_slots_v1 SET phase=? WHERE scope=? AND trade_id=? AND "
            "(phase='UNRESOLVED' OR (phase='LOST' AND ?='PENDING_RESALE'))",
            (phase, scope, trade, phase))
        if phase == 'PENDING_RESALE':
            _present_wins(journal, scope)


def _inventory(journal, scope):
    row = journal.db.execute('SELECT read_id,network_at,items FROM capacity_inventory_v1 WHERE scope=?', (scope,)).fetchone()
    return (row[0], datetime.fromisoformat(row[1]), json.loads(row[2])) if row else None


def _present_wins(journal, scope):
    inventory = _inventory(journal, scope)
    if inventory:
        for item, definition in inventory[2]:
            journal.db.execute("UPDATE capacity_slots_v1 SET phase='OCCUPIED' WHERE scope=? AND item_id=? "
                "AND definition_id=? AND phase='PENDING_RESALE'", (scope, item, definition))


def observe(journal, scope, rows, *, read_id, network_at, now):
    """Commit proven physical presence/absence and its accounting together.

    Replaying an earlier read cannot remove a newly arrived item. A pending win
    remains reserved even when missing from a complete Transfer List read.
    """
    token(scope); token(read_id)
    items = []
    for row in rows:
        item, definition = row['item']['item_id'], row['item']['definition_id']
        token(item, 'item'); integer(definition, 1)
        items.append((item, definition))
    if len({i[0] for i in items}) != len(items):
        raise ValueError('capacity_inventory_conflict')
    if not 0 <= (now-network_at).total_seconds() <= 30:
        raise ValueError('capacity_inventory_stale')
    with nullcontext() if journal.db.in_transaction else journal.transaction():
        if journal.db.execute('SELECT 1 FROM capacity_reads_v1 WHERE scope=? AND read_id=?', (scope, read_id)).fetchone():
            return False
        prior = _inventory(journal, scope)
        if prior and network_at < prior[1]:
            raise ValueError('capacity_inventory_stale')
        if prior and network_at == prior[1] and sorted(map(tuple, prior[2])) != sorted(items):
            raise ValueError('capacity_inventory_conflict')
        journal.db.execute('INSERT INTO capacity_reads_v1 VALUES(?,?)', (scope, read_id))
        journal.db.execute('INSERT OR REPLACE INTO capacity_inventory_v1 VALUES(?,?,?,?)',
            (scope, read_id, network_at.isoformat(), json.dumps(items)))
        # Only a *new complete read* can free a previously proven occupied slot.
        for trade, item, definition in journal.db.execute("SELECT trade_id,item_id,definition_id FROM capacity_slots_v1 "
                "WHERE scope=? AND phase='OCCUPIED'", (scope,)).fetchall():
            if (item, definition) not in items:
                journal.db.execute("UPDATE capacity_slots_v1 SET phase='RELEASED' WHERE scope=? AND trade_id=?", (scope, trade))
        _present_wins(journal, scope)
        journal._event(scope, 'CAPACITY_OBSERVED', {'read_id': read_id, 'occupied': len(items)})
    return True


def status(journal, scope, *, now):
    # Readers also need one SQLite snapshot: inventory and slot phases must not
    # straddle another process's commit and appear to release/count a win twice.
    if journal.db.in_transaction:
        return _status(journal, scope, now=now)
    journal.db.execute('BEGIN')
    try:
        result = _status(journal, scope, now=now)
        journal.db.execute('COMMIT')
        return result
    except BaseException:
        journal.db.execute('ROLLBACK')
        raise


def _status(journal, scope, *, now):
    if not installed(journal):
        # Read-only historical evidence must remain readable without migration.
        # Missing inventory is UNKNOWN, never an implicit empty Transfer List.
        from .core import AuctionQueue
        q = AuctionQueue(journal=journal, scope=scope)
        return dict(occupied=None, physical_occupied=None, unresolved=len(q.entries),
            pending_resale=len(q.pending_resale), total=None, fresh=False, read_id=None,
            pending_resale_trades=sorted(q.pending_resale))
    inventory = _inventory(journal, scope)
    slots = journal.db.execute('SELECT trade_id,item_id,definition_id,phase FROM capacity_slots_v1 WHERE scope=?', (scope,)).fetchall()
    unresolved = [s for s in slots if s[3] == 'UNRESOLVED']
    pending = [s for s in slots if s[3] in {'PENDING_RESALE', 'RESALE_UNKNOWN'}]
    physical = set(map(tuple, inventory[2])) if inventory else set()
    # If the pile is read before the auction's WON readback, that exact physical
    # item is still accounted for by its unresolved slot. Never count it twice.
    represented = {(s[1], s[2]) for s in unresolved+pending}
    occupied = len(physical-represented) if inventory else None
    fresh = bool(inventory and 0 <= (now-inventory[1]).total_seconds() <= 30)
    return dict(occupied=occupied, physical_occupied=len(physical) if inventory else None,
        unresolved=len(unresolved), pending_resale=len(pending),
        total=occupied+len(unresolved)+len(pending) if inventory else None,
        fresh=fresh, read_id=inventory[0] if inventory else None,
        pending_resale_trades=[s[0] for s in pending])
