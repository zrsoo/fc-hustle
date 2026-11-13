"""Explicit one-shot production bridge. Importing this package starts no work."""
from .adapter import NativeAdapter
from .contracts import Search, VERSION

__all__ = ['NativeAdapter', 'Search', 'VERSION']
