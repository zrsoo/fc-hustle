"""Negative regressions for independent offline receipts/publication contracts."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import check_00302_production as check


class ReceiptRejections(unittest.TestCase):
    def receipt(self):
        return dict(task='003-02',evidence_class='OFFLINE_REGRESSIONS_ONLY',group='python',status='PASS',results=[dict(
            command=['{python}','-m','unittest','discover','-s','tests','-v'],exit_code=0,stdout='out',stderr='err',
            elapsed_seconds=200,finished='2026-11-15T00:00:00+00:00',tests_run=800)])

    def logs(self, name):
        return '' if name=='out' else 'Ran 800 tests in 200.000s\n\nOK\n'

    def test_failed_or_incomplete_full_suite_cannot_pass(self):
        for transform in (lambda r:r['results'][0].update(exit_code=1),lambda r:r.update(results=[]),
                          lambda r:r['results'][0].update(tests_run=10),lambda r:r.update(evidence_class='LIVE_VERIFIED')):
            row=self.receipt(); transform(row)
            with self.assertRaises(ValueError): check.validate_receipt('python',row,self.logs)

    def test_failed_output_or_skips_cannot_be_hidden_by_exit_code(self):
        for log in ('Ran 800 tests in 200s\nFAILED (failures=1)', 'Ran 800 tests in 200s\nOK (skipped=2)', ''):
            with self.assertRaises(ValueError):
                check.validate_receipt('python',self.receipt(),lambda name:log)
        check.validate_receipt('python',self.receipt(),self.logs)

    def test_missing_behavioral_modules_are_rejected(self):
        for index in range(8):
            with self.assertRaisesRegex(ValueError,'behavioral_module_not_verified'):
                check.behavioral_receipts(index, 'unrelated tests passed')

    def test_untracked_or_uncommitted_changes_are_not_published(self):
        for mode in ('untracked','dirty','remote'):
            def git(*args):
                if args[0]=='ls-files': return '' if mode=='untracked' else '\n'.join(check.PUBLICATION_PATHS)
                if args[0]=='status': return ' M source' if mode=='dirty' else ''
                if args[0]=='branch': return 'main'
                if args[0]=='ls-remote': raise ValueError('remote_unavailable')
                return 'commit'
            with patch.object(check,'git',side_effect=git), self.assertRaises(ValueError): check.publication()


if __name__=='__main__': unittest.main(verbosity=2)
