"""
Package containing collection implementations.

Available implementations are imported from subpackages.
"""

from .interfaces import ICollection
from .inmemory import InMemoryCollection

__all__ = [
    'ICollection',
    'InMemoryCollection',
]
