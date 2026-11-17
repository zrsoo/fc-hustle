"""Reproducible synthetic trace. Generates no native/live or sealed evidence."""
from collections import Counter
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from controller_policy_fixture import Harness


def record(*, historical=False):
    with tempfile.TemporaryDirectory() as td:
        h=Harness(td,10)
        try:
            if historical:
                # Explicit replay of the sealed 004 policy in this isolated
                # socket-free fixture. Current production always refreshes;
                # historical observations and request counts are not rewritten.
                h.controller._refresh_selection=lambda batch,candidates:candidates
            state=h.controller.step();members=len(state['members'])
            for n,row in enumerate(h.ea.rows):row.update(bid_state='outbid',current_bid=200,expires=100-n)
            h.controller.step()
            for row in h.ea.rows:row.update(trade_state='closed',bid_state='outbid',expires=0)
            h.ea.credits=40000
            final=h.controller.step()
            return dict(schema=1,classification='SYNTHETIC_OFFLINE_ONLY',
                initial_confirmed_members=members,terminal_lost=h.store.db.execute("SELECT count(*) FROM c4_members WHERE state='LOST'").fetchone()[0],
                final={k:final[k] for k in ('phase','lifecycle','reason')},
                requests=dict(Counter(x['command']['operation'] for x in h.ea.calls if x['command']['operation']!='price_helpers')),
                trace=[dict(operation=x['command']['operation'],phase=x['phase'],at=x['at']) for x in h.ea.calls if x['command']['operation']!='price_helpers'],
                acquisition=h.metrics('ACQUISITION'),cycles=h.metrics('CYCLE'),
                maximum_parallel_requests=h.ea.max_active,
                global_ten_participation_guarantee=final['global_ten_participation_guarantee'])
        finally:h.close()


if __name__=='__main__':
    value=record()
    if len(sys.argv)>1:Path(sys.argv[1]).write_text(json.dumps(value,indent=2)+'\n')
    else:print(json.dumps(value,indent=2))
