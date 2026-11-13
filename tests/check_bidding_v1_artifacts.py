"""Independent artifact checks; behavioral acceptance remains test_bidding_v1.py."""
import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ArtifactChecks(unittest.TestCase):
    def test_all_seven_criteria_point_to_real_executable_tests_and_implementation(self):
        doc = json.loads((ROOT/"docs/research/001c/001c-02/validation-plan.json").read_text())
        self.assertEqual((doc["schema"], doc["task"], doc["classification"]), (1, "001c-02", "OFFLINE_VALIDATED"))
        self.assertEqual((doc["live_ea_requests"], doc["live_account_mutations"]), (0, 0))
        tree = ast.parse((ROOT/doc["test_file"]).read_text())
        actual = {f"{cls.name}.{method.name}":method for cls in tree.body if isinstance(cls, ast.ClassDef)
                  for method in cls.body if isinstance(method, ast.FunctionDef) and method.name.startswith("test_")}
        self.assertEqual([row["index"] for row in doc["criteria"]], list(range(7)))
        for row in doc["criteria"]:
            self.assertTrue(row["paths"])
            self.assertTrue(row["tests"])
            for path in row["paths"]:
                resolved = (ROOT/path).resolve()
                self.assertTrue(resolved.is_relative_to(ROOT))
                self.assertTrue(resolved.is_file(), path)
            for name in row["tests"]:
                self.assertIn(name, actual)
                # These map to behavioral assertions, not placeholder methods.
                self.assertTrue(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                                    and n.func.attr.startswith("assert") for n in ast.walk(actual[name])), name)

    def test_no_actor_loops_or_runtime_startup_and_persona_bytes_preserved(self):
        for path in (ROOT/"fc_access/bidding_v1").glob("*.py"):
            tree = ast.parse(path.read_text())
            self.assertFalse(any(isinstance(n, (ast.While, ast.AsyncFor)) for n in ast.walk(tree)), path)
            source = path.read_text()
            for forbidden in ("serve_forever", "threading.Thread", "asyncio.create_task", "time.sleep("):
                self.assertNotIn(forbidden, source)
        self.assertEqual((ROOT/"browser/bidding-v1/persona.js").read_bytes(),
                         (ROOT/"experiments/market_discovery_followup_v1/browser/persona.js").read_bytes())
        page = (ROOT/"browser/bidding-v1/page.js").read_text()
        self.assertNotIn("setInterval", page)
        self.assertNotIn("lastSubmission", page)
        self.assertIn('max_bid:"maxBid"', page)
        self.assertIn('min_buy:"minBuy"', page)
        handoff = (ROOT/"docs/research/001c/001c-02/implementation.md").read_text()
        self.assertIn("OFFLINE_VALIDATED", handoff)
        self.assertIn("zero EA requests", handoff)
        self.assertIn("LIVE_VERIFIED", handoff)


if __name__ == "__main__":
    unittest.main(verbosity=2)
