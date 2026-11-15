"""Offline process harness for the actual continuous lifecycle, never Edge."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from actors_fixture import RealClock
from test_00209_bulk import BulkPage
from fc_access.continuous_v1 import runtime
from fc_access.continuous_v1.__main__ import main

real_broker = runtime.broker


def offline_broker(control, run, manifest):
    pages = []
    def factory(port):
        page = BulkPage(Path(manifest['state_dir']), RealClock())
        page.transfer_items = []
        page.pages = {1: []}
        pages.append(page)
        return page
    try:
        return real_broker(control, run, manifest, executor_factory=factory, fixture=True)
    finally:
        for page in pages: page.close()


if __name__ == '__main__':
    runtime.broker = offline_broker
    # Re-exec children through this harness; production's CLI has no fixture flag.
    real_popen = runtime.subprocess.Popen
    def launch(argv, **kw):
        return real_popen([argv[0], str(Path(__file__).resolve()), *argv[3:]], **kw)
    runtime.subprocess.Popen = launch
    raise SystemExit(main())
