"""
An in-memory ICollection implementation.
"""

from copy import deepcopy
from uuid import uuid4

from zope.interface import implementer

from .interfaces import ICollection
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
        # TODO: Get 'id' out of object data.
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
        return self._get_data(object_id)

    @simulate_async
    def create(self, object_id, data):
        assert 'id' not in data  # TODO: Something better than assert.
        if object_id is None:
            object_id = uuid4().hex
        self._set_data(object_id, data)
        return object_id

    @simulate_async
    def update(self, object_id, data):
        assert object_id is not None  # TODO: Something better than assert.
        assert self._id_to_key(object_id) in self._data
        self._set_data(object_id, data)
        return self._get_data(object_id)

    @simulate_async
    def delete(self, object_id):
        data = self._get_data(object_id)
        self._data.pop(self._id_to_key(object_id), None)
        return data


@implementer(ICollection)
class InMemoryStoreCollection(InMemoryCollection):
    """
    A collection of stores belonging to an owner.
    Forgets things easily.
    """

    def __init__(self, data, owner_id, reactor=None):
        self.owner_id = owner_id
        super(InMemoryStoreCollection, self).__init__(data, reactor=reactor)


@implementer(ICollection)
class InMemoryRowCollection(InMemoryCollection):
    """
    A table of rows belonging to a store.
    Forgets things easily.
    """

    def __init__(self, data, owner_id, store_id, reactor=None):
        self.owner_id = owner_id
        self.store_id = store_id
        super(InMemoryRowCollection, self).__init__(data, reactor=reactor)

    def _id_to_key(self, object_id):
        """
        Convert object_id into a key for the internal datastore.
        """
        return (self.store_id, object_id)

    def _key_to_id(self, key):
        """
        Convert an internal datastore key into an object_id.
        """
        store_id, object_id = key
        assert store_id == self.store_id
        return object_id

    def _is_my_key(self, key):
        """
        Exclude keys for rows belonging to different stores.
        """
        store_id, _object_id = key
        return store_id == self.store_id
