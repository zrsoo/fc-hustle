"""Execute the current browser contract instead of pinning its source bytes."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def check_js(case, name):
    result = subprocess.run(['node', str(ROOT/'tests'/name)], cwd=ROOT,
                            capture_output=True, text=True, timeout=20)
    case.assertEqual(result.returncode, 0, result.stdout+result.stderr)
    case.assertTrue(result.stdout.strip(), 'contract must report its checks')
