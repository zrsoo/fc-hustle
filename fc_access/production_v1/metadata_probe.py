"""Explicit consumed special-version probe; shared finite runner."""
import json
from .repair_probe import run
if __name__=="__main__":print(json.dumps(run("metadata-smoke-02")))
