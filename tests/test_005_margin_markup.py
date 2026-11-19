"""Configurable bid margin and listing markup; offline synthetic EA.

margin is X in the bid cap (resale - 5% tax - X); list_markup lists a won item at
the greatest legal tick <= resale + markup. Dispatch-time authority accepts no
price outside [resale, resale + markup] and still requires native caps/ticks.
"""
from dataclasses import replace
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from controller_policy_fixture import Harness
from controller_work_fixture import harness, won, effects
from fc_access.controller_v1.config import ControllerConfig
from fc_access.controller_v1.controller import Controller


def configured(h,**values):
    h.config=replace(h.config,**values)
    h.controller=Controller(h.store,h.adapter,h.cache,config=h.config,ids=h.ids,clock=h.clock.clock,sleep=h.clock.sleep)
    h.controller.ids=h.controller.prices.command_ids=h.controller.pricing.command_ids=h.ids
    h.controller.resume()
    return h


class MarginTests(unittest.TestCase):
    def caps(self,**values):
        h=Harness(self.enterContext(tempfile.TemporaryDirectory()),3);self.addCleanup(h.close)
        if values:configured(h,**values)
        h.controller.step()
        return {m['target']['trade_id']:(m['cap'],m['resale_price']) for m in h.controller.journal.members()}

    def test_lower_margin_raises_each_cap_by_the_difference(self):
        base,low=self.caps(),self.caps(margin=200)
        self.assertEqual(set(base),set(low));self.assertTrue(base)
        for trade,(cap,resale) in base.items():
            new,_=low[trade]
            tick=100 if new<10000 else 250
            self.assertTrue(300-tick<new-cap<=300+tick,(new,cap))  # +300 floored to legal ticks
            self.assertLessEqual(new,resale-resale//20-200)

    def test_config_bounds(self):
        self.assertEqual((ControllerConfig().margin,ControllerConfig().list_markup),(500,0))
        for bad in (dict(margin=-1),dict(margin=1.5),dict(list_markup=-50),dict(list_markup=True),dict(margin=100001)):
            with self.assertRaises(ValueError,msg=bad):ControllerConfig(**bad)


class MarkupTests(unittest.TestCase):
    def make(self,markup):
        h=harness(self.enterContext(tempfile.TemporaryDirectory()));self.addCleanup(h.ea.world.close);self.addCleanup(h.close)
        return configured(h,list_markup=markup) if markup else h

    def test_won_item_lists_at_resale_plus_markup(self):
        h=self.make(500);won(h);resale=h.controller.journal.members()[0]['resale_price']
        for _ in range(2):h.controller.step()  # MANAGING -> MAINTENANCE (move + list)
        self.assertEqual(effects(h),[('list',1),('move',1)])
        listing=h.calls('list')[0]['command']['params']
        self.assertGreater(listing['buy_now_price'],resale);self.assertLessEqual(listing['buy_now_price'],resale+500)
        self.assertEqual(listing['duration'],3600);self.assertLess(listing['starting_bid'],listing['buy_now_price'])
        self.assertEqual(h.store.db.execute("SELECT count(*) FROM c4_members WHERE state='WON_ACCOUNTED'").fetchone()[0],1)

    def test_default_lists_at_resale_price(self):
        h=self.make(0);won(h);resale=h.controller.journal.members()[0]['resale_price']
        for _ in range(2):h.controller.step()
        self.assertEqual(h.calls('list')[0]['command']['params']['buy_now_price'],resale)

    def test_dispatch_authority_rejects_prices_outside_the_markup_window(self):
        h=self.make(500);won(h);h.controller.step();resale=h.controller.journal.members()[0]['resale_price']
        captured=[];real=h.controller.work.dispatch
        def capture(op,p):
            if op=='move':return real(op,p)
            captured.append((op,p))
        with patch.object(h.controller.work,'dispatch',side_effect=capture):h.controller.step()
        op,p=captured[0];self.assertEqual(op,'list')
        for price in (resale+750,resale-250):
            with self.assertRaises((ValueError,sqlite3.IntegrityError),msg=price):real(op,dict(p,buy_now_price=price))
        h.store.list_markup=0  # the same raised listing is refused without a configured markup
        with self.assertRaises((ValueError,sqlite3.IntegrityError)):real(op,p)
        self.assertEqual(effects(h),[('move',1)])


if __name__=='__main__':unittest.main(verbosity=2)
