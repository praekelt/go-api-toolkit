"""
Tests for the in-memory collection.
"""

from twisted.trial.unittest import TestCase
from twisted.internet.defer import (
    inlineCallbacks, gatherResults, maybeDeferred)
from zope.interface.verify import verifyObject

from go_api.collections.errors import (
    CollectionObjectNotFound, CollectionObjectAlreadyExists)
from go_api.collections.inmemory import InMemoryCollection
from go_api.collections.interfaces import ICollection


class TestInMemoryCollection(TestCase):
    """
    Tests from the in-memory collection.
    """

    def filtered_all(self, collection):
        """
        Get all objects in a collection. Some backends may have some index
        deletion lag, so we might need to filter the results. This
        implementation doesn't do any filtering, but subclasses can override.

        This waits for all deferreds to fire before returning.
        """
        d = collection.all()
        d.addCallback(lambda objs: [maybeDeferred(lambda: o) for o in objs])
        d.addCallback(gatherResults)
        d.addCallback(lambda objs: [o for o in objs if o is not None])
        return d

    def ensure_equal(self, foo, bar, msg=None):
        """
        Similar to .assertEqual(), but raises an exception instead of failing.

        This should be used to differentiate state setup confirmation (which is
        not part of the behaviour being tested) from assertions about the code
        under test.
        """
        if msg is None:
            msg = "%r != %r" % (foo, bar)
        if foo != bar:
            raise Exception(msg)

    def test_collection_provides_ICollection(self):
        """
        The return value of .get_row_collection() is an object that provides
        ICollection.
        """
        collection = InMemoryCollection()
        verifyObject(ICollection, collection)

    @inlineCallbacks
    def test_init_defaults(self):
        """
        Initializing without parameters should produce an empty data store.
        """
        collection = InMemoryCollection()
        keys = yield collection.all_keys()
        self.assertEqual(keys, [])

    @inlineCallbacks
    def test_init_with_datastore(self):
        """
        Initializing with a data store specified should use that data store.
        """
        store = {}
        collection = InMemoryCollection(store)
        yield collection.create("key", {"datum": "ipsum"})
        self.assertEqual(store, {
            "key": {"id": "key", "datum": "ipsum"},
        })

    @inlineCallbacks
    def test_all_keys_empty(self):
        """
        Listing all rows returns an empty list when no rows exist in the store.
        """
        collection = InMemoryCollection()
        keys = yield collection.all_keys()
        self.assertEqual(keys, [])

    @inlineCallbacks
    def test_all_empty(self):
        """
        Listing all rows returns an empty list when no rows exist in the store.
        """
        collection = InMemoryCollection()
        all_data = yield self.filtered_all(collection)
        self.assertEqual(all_data, [])

    @inlineCallbacks
    def test_all_not_empty(self):
        """
        Listing all rows returns a non-empty list when rows exist in the store.
        """
        collection = InMemoryCollection()
        key = yield collection.create(None, {})
        data = yield collection.get(key)

        all_data = yield self.filtered_all(collection)
        self.assertEqual(all_data, [data])

    @inlineCallbacks
    def test_create_no_id_no_data(self):
        """
        Creating an object with no object_id should generate one.
        """
        collection = InMemoryCollection()

        key = yield collection.create(None, {})
        data = yield collection.get(key)
        self.assertEqual(data, {'id': key})

    @inlineCallbacks
    def test_create_with_id_no_data(self):
        """
        Creating an object with an object_id should not generate a new one.
        """
        collection = InMemoryCollection()

        key = yield collection.create('key', {})
        self.assertEqual(key, 'key')
        data = yield collection.get(key)
        self.assertEqual(data, {'id': 'key'})

    @inlineCallbacks
    def test_create_no_id_with_data(self):
        collection = InMemoryCollection()

        key = yield collection.create(None, {'foo': 'bar'})
        keys = yield collection.all_keys()
        self.assertEqual(keys, [key])
        data = yield collection.get(key)
        self.assertEqual(data, {'foo': 'bar', 'id': key})

    @inlineCallbacks
    def test_create_existing_id(self):
        collection = InMemoryCollection()
        key = yield collection.create(None, {'foo': 'bar'})
        d = collection.create(key, {'baz': 'boo'})
        yield self.failUnlessFailure(d, CollectionObjectAlreadyExists)
        data = yield collection.get(key)
        self.assertEqual(data, {'foo': 'bar', 'id': key})

    @inlineCallbacks
    def test_delete_missing_row(self):
        collection = InMemoryCollection()
        d = collection.delete('foo')
        yield self.failUnlessFailure(d, CollectionObjectNotFound)
        keys = yield collection.all_keys()
        self.assertEqual(keys, [])

    @inlineCallbacks
    def test_delete_existing_row(self):
        collection = InMemoryCollection()

        key = yield collection.create(None, {})
        keys = yield collection.all_keys()
        self.ensure_equal(keys, [key])

        data = yield collection.delete(key)
        self.assertEqual(data, {'id': key})
        keys = yield collection.all_keys()
        self.assertEqual(keys, [])

    @inlineCallbacks
    def test_collection_update(self):
        collection = InMemoryCollection()

        key = yield collection.create(None, {})
        data = yield collection.get(key)
        self.ensure_equal(data, {'id': key})

        data = yield collection.update(
            key, {'id': key, 'foo': 'bar'})
        self.assertEqual(data, {'id': key, 'foo': 'bar'})
        data = yield collection.get(key)
        self.assertEqual(data, {'id': key, 'foo': 'bar'})

    @inlineCallbacks
    def test_collection_update_missing_row(self):
        collection = InMemoryCollection()
        d = collection.update('foo', {})
        yield self.failUnlessFailure(d, CollectionObjectNotFound)
        keys = yield collection.all_keys()
        self.assertEqual(keys, [])
