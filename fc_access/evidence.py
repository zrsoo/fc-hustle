"""Separate immutable research evidence from evolving implementation provenance.

Historical mixed manifests remain untouched. Consumers enforce only evidence
entries; current implementations are verified by executable contract tests.
"""
from pathlib import PurePosixPath


def is_evidence(path):
    path = str(path).replace('\\', '/')
    parts = PurePosixPath(path).parts
    if '..' in parts or PurePosixPath(path).is_absolute():
        return False
    # Original before-migration snapshots are sealed historical evidence.
    if path.startswith('docs/research/') and '/before/' in path:
        return True
    if PurePosixPath(path).suffix.lower() in {'.py', '.js', '.cjs', '.ps1', '.html', '.css'}:
        return False
    return path.startswith('docs/research/') or (
        path.startswith('experiments/') and ('runs' in parts or 'fixtures' in parts))


def evidence_hashes(mapping):
    """Select evidence pins from a historical mixed manifest, without changing it."""
    return {path: digest for path, digest in mapping.items() if is_evidence(path)}


def research_semantics(value):
    """Compare replay results while treating implementation hashes as provenance.

    All business results and captured-input hashes remain in the comparison.
    Relative captured filenames in inputs_sha256 are retained too.
    """
    if isinstance(value, list):
        return [research_semantics(v) for v in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, child in value.items():
        if key == 'sources_sha256':
            continue
        if key == 'inputs_sha256':
            child = {p: d for p, d in child.items() if is_evidence(p) or (
                '/' not in p and PurePosixPath(p).suffix not in {'.py', '.js', '.cjs', '.ps1'})}
        result[key] = research_semantics(child)
    return result
