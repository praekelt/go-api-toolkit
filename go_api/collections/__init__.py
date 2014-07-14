"""
Package containing collection implementations.

Available implementations are imported from subpackages.
"""

from go_store_service.collections.inmemory import (
    InMemoryCollection, InMemoryCollectionBackend)

from go_store_service.collections.riak import RiakCollectionBackend

__all__ = [
    'InMemoryCollection', 'InMemoryCollectionBackend',
    'RiakCollectionBackend',
]
