"""
An in-memory ICollection implementation.
"""

from copy import deepcopy
from uuid import uuid4

from zope.interface import implementer

from .interfaces import ICollection
from .errors import (
    CollectionObjectNotFound, CollectionObjectAlreadyExists,
    CollectionUsageError)
from ..utils import simulate_async


@implementer(ICollection)
class InMemoryCollection(object):
    """
    A Collection implementation backed by an in-memory dict.
    """

    def __init__(self, data=None):
        if data is None:
            data = {}
        self._data = data

    def _id_to_key(self, object_id):
        """
        Convert object_id into a key for the internal datastore. This should be
        overridden in subclasses that don't use object_id as the key.
        """
        return object_id

    def _key_to_id(self, key):
        """
        Convert an internal datastore key into an object_id. This should be
        overridden in subclasses that don't use object_id as the key.
        """
        return key

    def _is_my_key(self, key):
        """
        Returns True if the key belongs to this store, False otherwise. This
        should be overridden in subclasses that only operate on a subset of the
        keys in the backend datastore.
        """
        return True

    def _set_data(self, object_id, data):
        row_data = deepcopy(data)
        row_data['id'] = object_id
        self._data[self._id_to_key(object_id)] = row_data

    def _get_data(self, object_id):
        data = self._data.get(self._id_to_key(object_id), None)
        return deepcopy(data)

    def _get_keys(self):
        return [
            self._key_to_id(key) for key in self._data
            if self._is_my_key(key)]

    @simulate_async
    def all_keys(self):
        return self._get_keys()

    @simulate_async
    def all(self):
        return [self._get_data(object_id) for object_id in self._get_keys()]

    @simulate_async
    def get(self, object_id):
        data = self._get_data(object_id)
        if data is None:
            raise CollectionObjectNotFound(object_id)
        return data

    @simulate_async
    def create(self, object_id, data):
        if object_id is None:
            object_id = uuid4().hex
        if self._get_data(object_id) is not None:
            raise CollectionObjectAlreadyExists(object_id)
        self._set_data(object_id, data)
        return (object_id, self._get_data(object_id))

    @simulate_async
    def update(self, object_id, data):
        if not self._id_to_key(object_id) in self._data:
            raise CollectionObjectNotFound(object_id)
        self._set_data(object_id, data)
        return self._get_data(object_id)

    @simulate_async
    def delete(self, object_id):
        data = self._get_data(object_id)
        if data is None:
            raise CollectionObjectNotFound(object_id)
        self._data.pop(self._id_to_key(object_id), None)
        return data
