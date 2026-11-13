"""One authorized bulk invocation followed by independent native readback.

Explicit operator action only. No loop, scheduler, alternative listing or retry.
"""
import argparse
import json
from pathlib import Path
from .contracts import groups, preflight
from .probe import run, save, OUT
from .server import Store

DATABASE=Path('private-captures/002-bulk-transfer-operations/window.sqlite3')


def once(operation):
    name={'bulk_clear_sold':'clear-sold','bulk_relist_all':'relist-all'}[operation]
    if (OUT/(name+'.json')).exists():
        raise ValueError('existing_bulk_attempt_no_replay')
    journal=Store.open_reconciler(DATABASE)
    try:
        if journal.db.execute('SELECT 1 FROM bulk_intents WHERE operation=?',(operation,)).fetchone():
            raise ValueError('bulk_operation_already_consumed_no_retry')
        authorized=journal.db.execute('SELECT sold,expired FROM bulk_authorization').fetchone()
    finally:journal.db.close()
    before=run('bulk_inventory','before-'+name)
    if not before['response']['success']:
        raise ValueError('fresh_prewrite_read_failed')
    inventory=before['response']['inventory'];rows=inventory['rows'];g=groups(rows)
    native=inventory.get('native_counts')
    if native is None or native['sold']!=len(g['sold']) or native['expired']!=len(g['expired']):
        raise ValueError('native_state_filter_disagrees')
    target=preflight(operation,rows,authorized_sold=authorized[0],authorized_expired=authorized[1])
    p=dict(before_read_id=before['command']['id'],expected_item_ids=sorted(r['item_id'] for r in target),
        expected_inventory_ids=sorted(r['item_id'] for r in rows),expected_sold_count=len(g['sold']),expected_expired_count=len(g['expired']))
    if operation=='bulk_relist_all':p['duration_seconds']=3600
    write=run(operation,name,p)
    if not write['response']['success']:
        raise ValueError('mutation_failed_or_ambiguous_no_retry')
    after=run('bulk_inventory','after-'+name)
    if not after['response']['success']:
        raise ValueError('postwrite_read_failed_no_write_retry')
    journal=Store.open_reconciler(DATABASE)
    try:
        result=journal.reconcile(operation,after['command']['id'])
    finally:journal.db.close()
    receipt=dict(operation=operation,mutation_command_id=write['command']['id'],
        before_read_id=before['command']['id'],after_read_id=after['command']['id'],result=result)
    save(OUT/(name+'-reconciliation.json'),receipt)
    print(json.dumps(receipt))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=['bulk_clear_sold','bulk_relist_all'])
    once(p.parse_args().operation)
