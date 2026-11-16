"""Balance service-contract regression, using the shipped browser bridge offline."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]


class NativeBalance(unittest.TestCase):
    def test_captured_native_currency_chain_and_invalid_balance_contracts(self):
        result=subprocess.run(['node','tests/controller_balance_native_checks.cjs'],cwd=ROOT,
            capture_output=True,encoding='utf-8',errors='strict',timeout=45)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('PASS 39 balance cases',result.stdout)

    def test_retained_live_read_contracts_and_independent_pricing_replay(self):
        import sys
        result=subprocess.run([sys.executable,'tests/check_controller_bridge_audit.py'],cwd=ROOT,
            capture_output=True,encoding='utf-8',errors='strict',timeout=45)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('"status": "PASS"',result.stdout)


if __name__=='__main__':unittest.main(verbosity=2)
